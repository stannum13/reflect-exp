"""Reconstructible storage x trigger factorial V2."""

from __future__ import annotations

import csv
import hashlib
import importlib
import io
import itertools
import json
from pathlib import Path
import platform
import struct
import subprocess
from typing import Any, Iterable, Mapping, Sequence
import zlib

import numpy as np

from .factorial_v2_scorer import LedgerScoreError, PLANNER_ID, score_episode


ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "configs/storage-trigger-factorial-v2.json"
SEEDS_PATH = ROOT / "configs/seeds-v2.json"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="ascii"))
SEED_MANIFEST = json.loads(SEEDS_PATH.read_text(encoding="ascii"))
STORAGE_VARIANTS = tuple(CONFIG["storage_variants"])
TRIGGER_VARIANTS = tuple(CONFIG["trigger_variants"])
DISTURBANCE_FAMILIES = tuple(CONFIG["disturbance_families"])
SEVERITIES = tuple(CONFIG["severities"])
HORIZONS = tuple(CONFIG["mission_horizons"])
SEEDS = tuple(SEED_MANIFEST["seeds"])
CLAIM_SCOPE = "SYNTHETIC_WHITE_BOX_ENGINEERING_ORACLE_NOT_VLA"
SOURCE_PATHS = (
    "experiments/10_storage_trigger/src/factorial_v2.py",
    "experiments/10_storage_trigger/src/factorial_v2_scorer.py",
    "experiments/10_storage_trigger/src/factorial.py",
    "experiments/10_storage_trigger/configs/storage-trigger-factorial-v2.json",
    "experiments/10_storage_trigger/configs/seeds-v2.json",
    "experiments/04_memory/src/unfixed_ablation.py",
)


class FactorialV2Error(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_bytes(row) for row in rows)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def csv_bytes(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row[field] for field in fields})
    return output.getvalue().encode("ascii")


def _read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="ascii"))))


def _head() -> str:
    return subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=REPO, text=True).strip()


def _episode_id(storage: str, trigger: str, family: str, severity: str, horizon: int, seed: int) -> str:
    return f"{storage}__{trigger}__{family}__{severity}__H{horizon}__S{seed}"


def frozen_matrix() -> tuple[dict[str, Any], ...]:
    return tuple({
        "claim_scope": CLAIM_SCOPE,
        "disturbance_family": family,
        "episode_id": _episode_id(storage, trigger, family, severity, horizon, seed),
        "horizon": horizon,
        "planner_id": PLANNER_ID,
        "seed": seed,
        "severity": severity,
        "storage_variant": storage,
        "trigger_variant": trigger,
    } for storage, trigger, family, severity, horizon, seed in itertools.product(
        STORAGE_VARIANTS, TRIGGER_VARIANTS, DISTURBANCE_FAMILIES, SEVERITIES, HORIZONS, SEEDS,
    ))


def fixture_matrix() -> tuple[dict[str, Any], ...]:
    cells = []
    for storage, trigger, family, horizon, seed in itertools.product(
        ("NO_MEMORY", "FIXED_SNAPSHOT", "LIVE_EPISODIC"),
        ("NO_REPLAN", "PERIODIC_ONLY", "HYBRID"),
        ("POSE_SHIFT", "CONTROL_FAILURE"), (4, 8), tuple(CONFIG["calibration_seeds"]),
    ):
        cells.append({
            "claim_scope": CLAIM_SCOPE, "disturbance_family": family,
            "episode_id": _episode_id(storage, trigger, family, "HIGH", horizon, seed),
            "horizon": horizon, "planner_id": PLANNER_ID, "seed": seed, "severity": "HIGH",
            "storage_variant": storage, "trigger_variant": trigger,
        })
    return tuple(cells)


def _legacy():
    return importlib.import_module("experiments.10_storage_trigger.src.factorial")


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _world(entities: Mapping[str, Any], restrictions: Mapping[str, Any]) -> dict[str, Any]:
    return {"entities": _copy(entities), "restrictions": _copy(restrictions)}


def _plan(view: Mapping[str, Any]) -> dict[str, Any]:
    eligible = sorted(
        (entity for entity, state in view["entities"].items() if state["availability"] == "AVAILABLE" and not view["restrictions"].get(state["room_id"], False)),
        key=lambda entity: (view["entities"][entity]["room_id"], entity),
    )
    failures = set(view["failures"])
    alternatives = [entity for entity in eligible if entity not in failures]
    target = alternatives[0] if alternatives else (eligible[0] if eligible else None)
    return {
        "affordance": "service_valve", "planner_id": PLANNER_ID,
        "pose": view["entities"].get(target, {}).get("pose") if target else None,
        "subgoals": ["approach", "inspect", "actuate", "verify"], "target": target,
    }


def _valid(entities: Mapping[str, Any], restrictions: Mapping[str, Any], plan: Mapping[str, Any]) -> bool:
    target = plan.get("target")
    if target not in entities:
        return False
    state = entities[str(target)]
    return state["availability"] == "AVAILABLE" and not restrictions.get(str(state["room_id"]), False) and plan.get("pose") == state["pose"]


def _trigger_state(trigger: Any) -> dict[str, Any]:
    return {"armed": trigger.armed, "last_wake": trigger.last_wake, "pending_event": trigger.pending_event}


def run_episode(cell: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    legacy = _legacy()
    initial = legacy.initial_task(int(cell["seed"]))
    entities, restrictions = legacy._copy_world(initial)
    store = legacy.StorageState(str(cell["storage_variant"]), initial)
    trigger = legacy.TriggerState(str(cell["trigger_variant"]))
    plan = _plan(store.view(0))
    start = {"cell": dict(cell), "initial_plan": _copy(plan), "initial_world": _world(entities, restrictions)}
    progress = 0
    consecutive_failures = 0
    pending_attempt_event = False
    control_remaining = 0
    control_target: str | None = None
    steps: list[dict[str, Any]] = []
    horizon = int(cell["horizon"])
    disturbance_tick = max(2, horizon // 2)
    for tick in range(1, horizon + int(CONFIG["recovery_allowance_ticks"]) + 1):
        world_before = _world(entities, restrictions)
        plan_before = _copy(plan)
        events: list[dict[str, Any]] = []
        if tick == disturbance_tick:
            generated, control_remaining, control_target = legacy._disturbance_events(
                initial, entities, str(cell["disturbance_family"]), str(cell["severity"]), tick, str(plan["target"]),
            )
            events.extend(generated)
            for event in generated:
                legacy._apply_event(entities, restrictions, event)
                store.ingest(event)
        material_event = bool(events) or pending_attempt_event
        pending_attempt_event = False
        failures_before = consecutive_failures
        trigger_before = _trigger_state(trigger)
        wake, reason = trigger.decide(
            tick=tick, material_event=material_event, failures=consecutive_failures,
            plan_valid=_valid(entities, restrictions, plan),
        )
        if wake:
            plan = _plan(store.view(tick))
        trigger_receipt = {
            "inputs": {"failures": failures_before, "material_event": material_event},
            "reason": reason, "state_after": _trigger_state(trigger), "state_before": trigger_before, "wake": wake,
        }
        valid_action = _valid(entities, restrictions, plan)
        fault_before = control_remaining
        success = valid_action
        if valid_action and control_remaining > 0 and plan["target"] == control_target:
            success = False
            control_remaining -= 1
        action = {
            "attempted": True, "control_fault_after": control_remaining,
            "control_fault_before": fault_before, "pose": plan.get("pose"),
            "success": success, "target": plan.get("target"),
        }
        if not success:
            consecutive_failures += 1
            store.ingest({"event_kind": "ATTEMPT", "subject_id": plan.get("target"), "tick": tick, "value": "FAILED"})
            pending_attempt_event = True
        else:
            progress += 1
            consecutive_failures = 0
            trigger.note_success()
        steps.append({
            "action": action, "cell": dict(cell), "episode_id": cell["episode_id"], "events": events,
            "plan_after": _copy(plan), "plan_before": plan_before, "storage": store.stats(tick),
            "tick": tick, "trigger": trigger_receipt, "world_after": _world(entities, restrictions),
            "world_before": world_before,
        })
        if progress >= horizon:
            break
    try:
        episode = score_episode(start, steps, CONFIG)
    except LedgerScoreError as exc:
        raise FactorialV2Error(str(exc)) from exc
    return episode, start, steps


EPISODE_FIELDS = (
    "episode_id", "seed", "storage_variant", "trigger_variant", "disturbance_family", "severity", "horizon",
    "planner_id", "claim_scope", "completion", "progress", "repeated_failures", "false_triggers",
    "late_trigger_ticks", "wasted_triggers", "semantic_wakes", "motion_wakes", "control_wakes",
    "semantic_latency_proxy_ms", "motion_latency_proxy_ms", "control_latency_proxy_ms", "trigger_latency_ticks_mean",
    "retries", "escalations", "aborts", "stale_decisions", "storage_reads", "storage_writes", "storage_bytes",
    "storage_age_ticks", "budget_cost_proxy",
)


def _source_closure() -> list[dict[str, Any]]:
    return [{"bytes": (REPO / path).stat().st_size, "path": path, "sha256": _sha((REPO / path).read_bytes())} for path in SOURCE_PATHS]


def _git_blob(commit: str, path: str) -> bytes:
    try:
        return subprocess.check_output(("git", "show", f"{commit}:{path}"), cwd=REPO)
    except subprocess.CalledProcessError as exc:
        raise FactorialV2Error("implementation source commit closure mismatch") from exc


def _freeze(cells: Sequence[Mapping[str, Any]], commit: str, *, fixture: bool) -> dict[str, Any]:
    closure = _source_closure()
    identities = [row["episode_id"] for row in sorted(cells, key=lambda row: row["episode_id"])]
    return {
        "claim_scope": CLAIM_SCOPE, "configuration_sha256": _sha(CONFIG_PATH.read_bytes()),
        "environment": {"numpy": np.__version__, "platform": platform.platform(), "python": platform.python_version()},
        "episode_ids": identities, "fixture": fixture, "implementation_git_sha": commit,
        "matrix_identity_sha256": _sha(canonical_bytes(identities)), "planner_id": PLANNER_ID,
        "schema_version": 2, "seed_manifest_sha256": _sha(SEEDS_PATH.read_bytes()),
        "source_closure": closure, "source_closure_sha256": _sha(canonical_bytes(closure)),
        "study_id": CONFIG["study_id"],
    }


def _validate_source(freeze: Mapping[str, Any]) -> None:
    if freeze.get("implementation_git_sha") != _head():
        # Evidence commits may descend from the source commit; the blob checks below are authoritative.
        try:
            subprocess.check_call(("git", "merge-base", "--is-ancestor", str(freeze["implementation_git_sha"]), "HEAD"), cwd=REPO)
        except subprocess.CalledProcessError as exc:
            raise FactorialV2Error("implementation commit is not an ancestor") from exc
    closure = _source_closure()
    if closure != freeze.get("source_closure") or _sha(canonical_bytes(closure)) != freeze.get("source_closure_sha256"):
        raise FactorialV2Error("implementation source closure mismatch")
    if not freeze.get("fixture"):
        for member in closure:
            if _sha(_git_blob(str(freeze["implementation_git_sha"]), str(member["path"]))) != member["sha256"]:
                raise FactorialV2Error("implementation source commit closure mismatch")
    expected_environment = {"numpy": np.__version__, "platform": platform.platform(), "python": platform.python_version()}
    if freeze.get("environment") != expected_environment:
        raise FactorialV2Error("frozen execution environment mismatch")


def _inventory(root: Path, *, exclude: Sequence[str] = ()) -> list[dict[str, Any]]:
    excluded = set(exclude)
    output = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        if path.is_symlink():
            raise FactorialV2Error("symlink is forbidden in evidence inventory")
        if path.is_file():
            payload = path.read_bytes()
            output.append({"bytes": len(payload), "path": relative, "sha256": _sha(payload)})
        elif not path.is_dir():
            raise FactorialV2Error("non-regular evidence member")
    return output


def _validate_inventory(root: Path, declared: Sequence[Mapping[str, Any]], *, manifest_name: str) -> None:
    seen: set[str] = set()
    for member in declared:
        relative = str(member.get("path"))
        parsed = Path(relative)
        if parsed.is_absolute() or ".." in parsed.parts or relative in seen:
            raise FactorialV2Error("invalid evidence inventory path")
        seen.add(relative)
    actual = _inventory(root, exclude=(manifest_name,))
    if actual != [dict(member) for member in declared]:
        raise FactorialV2Error("recursive evidence inventory mismatch or unlisted member")
    expected_dirs = {Path(name).parent.as_posix() for name in seen if Path(name).parent.as_posix() != "."}
    actual_dirs = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir() and not path.is_symlink()}
    if actual_dirs != expected_dirs:
        raise FactorialV2Error("recursive evidence directory inventory mismatch")


def _mean(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    return sum(float(row[field]) for row in rows) / len(rows) if rows else 0.0


METRICS = (
    "completion", "progress", "repeated_failures", "false_triggers", "late_trigger_ticks", "wasted_triggers",
    "semantic_wakes", "motion_wakes", "control_wakes", "semantic_latency_proxy_ms", "motion_latency_proxy_ms",
    "control_latency_proxy_ms", "trigger_latency_ticks_mean", "stale_decisions", "retries", "escalations", "aborts",
    "storage_reads", "storage_writes", "storage_bytes", "storage_age_ticks", "budget_cost_proxy",
)


def _group(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> list[dict[str, Any]]:
    output = []
    for key in sorted({tuple(row[field] for field in fields) for row in rows}):
        selected = [row for row in rows if tuple(row[field] for field in fields) == key]
        output.append({**dict(zip(fields, key, strict=True)), "episode_count": len(selected), **{f"{metric}_mean": round(_mean(selected, metric), 8) for metric in METRICS}})
    return output


def _contrasts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    definitions = [
        (f"HYBRID_MINUS_PERIODIC__{storage}", "trigger_variant", "HYBRID", "PERIODIC_ONLY", "storage_variant", storage)
        for storage in STORAGE_VARIANTS
    ] + [
        (f"LIVE_EPISODIC_MINUS_FIXED__{trigger}", "storage_variant", "LIVE_EPISODIC", "FIXED_SNAPSHOT", "trigger_variant", trigger)
        for trigger in TRIGGER_VARIANTS
    ]
    metrics = ("completion", "progress", "late_trigger_ticks", "wasted_triggers", "budget_cost_proxy")
    output = []
    for definition_index, (name, axis, candidate, comparator, hold_axis, hold) in enumerate(definitions):
        subset = [row for row in rows if row[hold_axis] == hold]
        seeds = sorted({int(row["seed"]) for row in subset})
        for metric_index, metric in enumerate(metrics):
            values = []
            used_seeds = []
            for seed in seeds:
                candidate_rows = [row for row in subset if int(row["seed"]) == seed and row[axis] == candidate]
                comparator_rows = [row for row in subset if int(row["seed"]) == seed and row[axis] == comparator]
                if candidate_rows and len(candidate_rows) == len(comparator_rows):
                    values.append(_mean(candidate_rows, metric) - _mean(comparator_rows, metric))
                    used_seeds.append(seed)
            if not values:
                continue
            array = np.asarray(values, dtype=np.float64)
            rng = np.random.Generator(np.random.PCG64(int(CONFIG["bootstrap_seed"]) + definition_index * 17 + metric_index))
            indices = rng.integers(0, len(array), size=(int(CONFIG["bootstrap_draws"]), len(array)))
            draws = array[indices].mean(axis=1)
            q025, q975 = np.quantile(draws, (0.025, 0.975), method="linear")
            output.append({
                "bootstrap_draws": CONFIG["bootstrap_draws"], "candidate": candidate, "comparator": comparator,
                "contrast": name, "effective_seed_n": len(used_seeds), "estimate": round(float(array.mean()), 8),
                "metric": metric, "q025": round(float(q025), 8), "q975": round(float(q975), 8),
                "seed_cluster_sha256": _sha(canonical_bytes(used_seeds)),
            })
    return output


FONT = {
    " ": ("00000",) * 7, "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
}
FONT.update({
    "0": ("01110","10001","10011","10101","11001","10001","01110"), "1": ("00100","01100","00100","00100","00100","00100","01110"),
    "2": ("01110","10001","00001","00010","00100","01000","11111"), "3": ("11110","00001","00001","01110","00001","00001","11110"),
    "4": ("00010","00110","01010","10010","11111","00010","00010"), "5": ("11111","10000","10000","11110","00001","00001","11110"),
    "6": ("01110","10000","10000","11110","10001","10001","01110"), "7": ("11111","00001","00010","00100","01000","01000","01000"),
    "8": ("01110","10001","10001","01110","10001","10001","01110"), "9": ("01110","10001","10001","01111","00001","00001","01110"),
})
FONT.update(dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (
    ("01110","10001","10001","11111","10001","10001","10001"),("11110","10001","10001","11110","10001","10001","11110"),
    ("01111","10000","10000","10000","10000","10000","01111"),("11110","10001","10001","10001","10001","10001","11110"),
    ("11111","10000","10000","11110","10000","10000","11111"),("11111","10000","10000","11110","10000","10000","10000"),
    ("01111","10000","10000","10111","10001","10001","01111"),("10001","10001","10001","11111","10001","10001","10001"),
    ("01110","00100","00100","00100","00100","00100","01110"),("00001","00001","00001","00001","10001","10001","01110"),
    ("10001","10010","10100","11000","10100","10010","10001"),("10000","10000","10000","10000","10000","10000","11111"),
    ("10001","11011","10101","10101","10001","10001","10001"),("10001","11001","10101","10011","10001","10001","10001"),
    ("01110","10001","10001","10001","10001","10001","01110"),("11110","10001","10001","11110","10000","10000","10000"),
    ("01110","10001","10001","10001","10101","10010","01101"),("11110","10001","10001","11110","10100","10010","10001"),
    ("01111","10000","10000","01110","00001","00001","11110"),("11111","00100","00100","00100","00100","00100","00100"),
    ("10001","10001","10001","10001","10001","10001","01110"),("10001","10001","10001","10001","10001","01010","00100"),
    ("10001","10001","10001","10101","10101","10101","01010"),("10001","10001","01010","00100","01010","10001","10001"),
    ("10001","10001","01010","00100","00100","00100","00100"),("11111","00001","00010","00100","01000","10000","11111"),
))))


def _png(width: int, height: int, pixels: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    scanlines = b"".join(b"\x00" + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(scanlines, 9)) + chunk(b"IEND", b"")


def _draw_text(pixels: bytearray, width: int, x0: int, y0: int, text: str, color: tuple[int, int, int], scale: int = 1) -> None:
    for index, character in enumerate(text.upper()):
        glyph = FONT.get(character, FONT[" "])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    for sy in range(scale):
                        for sx in range(scale):
                            x, y = x0 + index * 6 * scale + gx * scale + sx, y0 + gy * scale + sy
                            if 0 <= x < width and y >= 0 and (y * width + x) * 3 + 2 < len(pixels):
                                offset = (y * width + x) * 3
                                pixels[offset:offset + 3] = bytes(color)


def _graph(summary: Sequence[Mapping[str, Any]]) -> tuple[bytes, bytes, bytes]:
    by = {(row["storage_variant"], row["trigger_variant"]): float(row["completion_mean"]) for row in summary}
    width, height = 900, 430
    pixels = bytearray([255] * width * height * 3)
    _draw_text(pixels, width, 250, 15, "EXP10 V2 COMPLETION", (0, 0, 0), 2)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/><g font-family="monospace" font-size="11"><text x="300" y="25">EXP10 V2 COMPLETION</text>']
    for yi, storage in enumerate(STORAGE_VARIANTS):
        y0 = 120 + yi * 55
        _draw_text(pixels, width, 5, y0 + 16, storage, (0, 0, 0))
        svg.append(f'<text x="5" y="{y0 + 24}">{storage}</text>')
        for xi, trigger in enumerate(TRIGGER_VARIANTS):
            value = by.get((storage, trigger))
            rgb = (217, 217, 217) if value is None else (round(247 - 239 * value), round(251 - 170 * value), round(255 - 99 * value))
            x0, cell_w, cell_h = 210 + xi * 135, 125, 46
            for y in range(y0, y0 + cell_h):
                for x in range(x0, x0 + cell_w):
                    offset = (y * width + x) * 3
                    pixels[offset:offset + 3] = bytes(rgb)
            label = "NA" if value is None else f"{value:.3f}"
            _draw_text(pixels, width, x0 + 44, y0 + 19, label, (255, 255, 255) if value and value > 0.65 else (0, 0, 0))
            svg.append(f'<rect x="{x0}" y="{y0}" width="{cell_w}" height="{cell_h}" fill="#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}" stroke="#333"/><text x="{x0 + 42}" y="{y0 + 27}">{label}</text>')
    for xi, trigger in enumerate(TRIGGER_VARIANTS):
        x0 = 210 + xi * 135
        _draw_text(pixels, width, x0, 85, trigger, (0, 0, 0))
        svg.append(f'<text x="{x0}" y="95">{trigger}</text>')
    _draw_text(pixels, width, 300, 405, "COMPLETION RATE", (0, 0, 0))
    svg.append('<text x="350" y="415">COMPLETION RATE</text></g></svg>\n')
    style = {
        "background": "#ffffff", "cell_missing": "#d9d9d9", "cell_one": "#08519c", "cell_zero": "#f7fbff",
        "font": "BITMAP_5X7_V1", "height": height, "metric": "completion_mean", "png_contains_labels": True,
        "theme_independent": True, "width": width, "x_order": list(TRIGGER_VARIANTS), "y_order": list(STORAGE_VARIANTS),
    }
    return "".join(svg).encode("ascii"), _png(width, height, bytes(pixels)), canonical_bytes(style)


def _derive(rows: Sequence[Mapping[str, Any]]) -> dict[str, bytes]:
    cell = _group(rows, ("storage_variant", "trigger_variant", "disturbance_family", "severity", "horizon"))
    storage_trigger = _group(rows, ("storage_variant", "trigger_variant"))
    trigger_profile = _group(rows, ("trigger_variant",))
    family_horizon = _group(rows, ("disturbance_family", "severity", "horizon"))
    contrasts = _contrasts(rows)
    samples = []
    for storage, trigger in itertools.product(STORAGE_VARIANTS, TRIGGER_VARIANTS):
        selected = sorted((row for row in rows if row["storage_variant"] == storage and row["trigger_variant"] == trigger), key=lambda row: row["episode_id"])
        for requested, desired in (("WORKING", 1), ("NONWORKING", 0)):
            match = next((row for row in selected if int(row["completion"]) == desired), None)
            samples.append({
                "disposition": "OBSERVED" if match else "CLASS_NOT_OBSERVED", "episode_id": match["episode_id"] if match else None,
                "requested_class": requested, "storage_variant": storage, "trigger_variant": trigger,
            })
    svg, png, style = _graph(storage_trigger)
    strongest = max((row for row in contrasts if row["metric"] == "completion"), key=lambda row: abs(float(row["estimate"])))
    report = (
        "# Experiment 10 Storage x Trigger Factorial V2\n\nStatus: SYNTHETIC_WHITE_BOX_ENGINEERING_RESULT\n\n"
        f"Completed {len(rows)} paired deterministic episodes with {PLANNER_ID}. Strongest aggregate completion contrast was "
        f"{strongest['contrast']}: {float(strongest['estimate']):+.4f} (95% {float(strongest['q025']):+.4f} to {float(strongest['q975']):+.4f}).\n\n"
        "This is exact white-box regression evidence for the frozen simulator only. Family/horizon/severity decompositions are in heterogeneity.csv; 100% cells and zero-width intervals are not population-generalization evidence.\n"
    ).encode("ascii")
    tables = {
        "cell-summary.csv": cell, "contrasts.csv": contrasts, "heterogeneity.csv": family_horizon,
        "storage-trigger-summary.csv": storage_trigger, "trigger-profile.csv": trigger_profile,
    }
    files = {
        "RESULTS.md": report,
        "annotations.json": canonical_bytes({"samples": samples, "selection": "FIRST_CANONICAL_REQUESTED_CLASS_PER_STORAGE_TRIGGER"}),
        "plot-style.json": style, "storage-trigger.png": png, "storage-trigger.svg": svg,
    }
    for name, table in tables.items():
        files[name] = csv_bytes(table, tuple(table[0]) if table else ())
    return files


def _validate_raw(
    raw: Path, *, allow_fixture: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if raw.is_symlink() or not raw.is_dir():
        raise FactorialV2Error("raw evidence root must be a regular directory")
    manifest_payload = (raw / "raw-manifest.json").read_bytes()
    manifest = json.loads(manifest_payload)
    if canonical_bytes(manifest) != manifest_payload:
        raise FactorialV2Error("raw manifest is not canonical")
    _validate_inventory(raw, manifest.get("members", ()), manifest_name="raw-manifest.json")
    if (raw / "config.json").read_bytes() != CONFIG_PATH.read_bytes():
        raise FactorialV2Error("frozen config mismatch")
    if (raw / "seeds.json").read_bytes() != SEEDS_PATH.read_bytes():
        raise FactorialV2Error("frozen seed manifest mismatch")
    freeze = json.loads((raw / "freeze.json").read_text(encoding="ascii"))
    if bool(freeze.get("fixture")) and not allow_fixture:
        raise FactorialV2Error("fixture evidence is not an authorized frozen outcome matrix")
    if freeze.get("configuration_sha256") != _sha(CONFIG_PATH.read_bytes()) or freeze.get("seed_manifest_sha256") != _sha(SEEDS_PATH.read_bytes()):
        raise FactorialV2Error("config/seed freeze mismatch")
    _validate_source(freeze)
    episodes = _read_csv(raw / "episodes.csv")
    starts = [json.loads(line) for line in (raw / "starts.jsonl").read_text(encoding="ascii").splitlines()]
    steps = [json.loads(line) for line in (raw / "steps.jsonl").read_text(encoding="ascii").splitlines()]
    expected_ids = list(freeze.get("episode_ids", ()))
    actual_ids = sorted(row["episode_id"] for row in episodes)
    if actual_ids != expected_ids or _sha(canonical_bytes(actual_ids)) != freeze.get("matrix_identity_sha256"):
        raise FactorialV2Error("exact matrix identity mismatch")
    if not freeze.get("fixture") and actual_ids != sorted(row["episode_id"] for row in frozen_matrix()):
        raise FactorialV2Error("frozen Cartesian matrix mismatch")
    starts_by_id = {str(row["cell"]["episode_id"]): row for row in starts}
    if len(starts_by_id) != len(starts) or set(starts_by_id) != set(actual_ids):
        raise FactorialV2Error("start/matrix identity mismatch")
    steps_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in steps:
        steps_by_id.setdefault(str(row["episode_id"]), []).append(row)
    if set(steps_by_id) != set(actual_ids):
        raise FactorialV2Error("step/matrix identity mismatch")
    scored = []
    for episode in episodes:
        episode_id = episode["episode_id"]
        cell = starts_by_id[episode_id]["cell"]
        expected_id = _episode_id(
            str(cell["storage_variant"]), str(cell["trigger_variant"]), str(cell["disturbance_family"]),
            str(cell["severity"]), int(cell["horizon"]), int(cell["seed"]),
        )
        if expected_id != episode_id or any(str(episode[field]) != str(cell[field]) for field in (
            "episode_id", "seed", "storage_variant", "trigger_variant", "disturbance_family", "severity", "horizon", "planner_id", "claim_scope",
        )):
            raise FactorialV2Error("episode cell identity mismatch")
        if not freeze.get("fixture") and dict(cell) not in frozen_matrix():
            raise FactorialV2Error("episode is outside frozen matrix")
        initial = _legacy().initial_task(int(cell["seed"]))
        expected_world = {"entities": initial["entities"], "restrictions": initial["restrictions"]}
        if starts_by_id[episode_id]["initial_world"] != expected_world:
            raise FactorialV2Error("initial world/source seed mismatch")
        try:
            score = score_episode(starts_by_id[episode_id], steps_by_id[episode_id], CONFIG)
        except LedgerScoreError as exc:
            raise FactorialV2Error(str(exc)) from exc
        for field in EPISODE_FIELDS:
            actual = episode[field]
            expected = score[field]
            if field in {"episode_id", "storage_variant", "trigger_variant", "disturbance_family", "severity", "planner_id", "claim_scope"}:
                equal = actual == str(expected)
            else:
                equal = float(actual) == float(expected)
            if not equal:
                raise FactorialV2Error(f"independent score mismatch for {field}")
        scored.append(score)
    if int(manifest.get("episode_count", -1)) != len(scored) or int(manifest.get("step_count", -1)) != len(steps):
        raise FactorialV2Error("manifest count mismatch")
    return scored, starts, steps


def _publish(output: Path, cells: Sequence[Mapping[str, Any]], *, implementation_git_sha: str, fixture: bool) -> None:
    if output.exists():
        raise FactorialV2Error("output must be absent")
    if implementation_git_sha != _head():
        raise FactorialV2Error("implementation commit must equal current HEAD")
    if not fixture:
        for member in _source_closure():
            if _sha(_git_blob(implementation_git_sha, str(member["path"]))) != member["sha256"]:
                raise FactorialV2Error("implementation source is not committed")
    raw, derived = output / "raw", output / "derived"
    raw.mkdir(parents=True)
    derived.mkdir()
    episodes: list[dict[str, Any]] = []
    starts: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for cell in cells:
        episode, start, episode_steps = run_episode(cell)
        episodes.append(episode)
        starts.append(start)
        steps.extend(episode_steps)
    episodes.sort(key=lambda row: row["episode_id"])
    starts.sort(key=lambda row: row["cell"]["episode_id"])
    steps.sort(key=lambda row: (row["episode_id"], row["tick"]))
    (raw / "config.json").write_bytes(CONFIG_PATH.read_bytes())
    (raw / "seeds.json").write_bytes(SEEDS_PATH.read_bytes())
    (raw / "freeze.json").write_bytes(canonical_bytes(_freeze(cells, implementation_git_sha, fixture=fixture)))
    (raw / "episodes.csv").write_bytes(csv_bytes(episodes, EPISODE_FIELDS))
    (raw / "starts.jsonl").write_bytes(jsonl_bytes(starts))
    (raw / "steps.jsonl").write_bytes(jsonl_bytes(steps))
    manifest = {
        "episode_count": len(episodes), "members": _inventory(raw), "schema_version": 2, "step_count": len(steps),
    }
    (raw / "raw-manifest.json").write_bytes(canonical_bytes(manifest))
    scored, _, _ = _validate_raw(raw, allow_fixture=fixture)
    for name, payload in _derive(scored).items():
        (derived / name).write_bytes(payload)
    (derived / "derived-manifest.json").write_bytes(canonical_bytes({"members": _inventory(derived), "schema_version": 2}))


def run_fixture(output: Path, *, implementation_git_sha: str) -> None:
    _publish(output, fixture_matrix(), implementation_git_sha=implementation_git_sha, fixture=True)


def run_frozen(output: Path, *, implementation_git_sha: str) -> None:
    _publish(output, frozen_matrix(), implementation_git_sha=implementation_git_sha, fixture=False)


def reconstruct(raw: Path, destination: Path) -> None:
    if destination.exists():
        raise FactorialV2Error("reconstruction destination must be absent")
    scored, _, _ = _validate_raw(raw, allow_fixture=False)
    destination.mkdir()
    for name, payload in _derive(scored).items():
        (destination / name).write_bytes(payload)
    (destination / "derived-manifest.json").write_bytes(canonical_bytes({"members": _inventory(destination), "schema_version": 2}))


def reconstruct_fixture(raw: Path, destination: Path) -> None:
    if destination.exists():
        raise FactorialV2Error("reconstruction destination must be absent")
    scored, _, _ = _validate_raw(raw, allow_fixture=True)
    destination.mkdir()
    for name, payload in _derive(scored).items():
        (destination / name).write_bytes(payload)
    (destination / "derived-manifest.json").write_bytes(canonical_bytes({"members": _inventory(destination), "schema_version": 2}))


__all__ = [
    "EPISODE_FIELDS", "FactorialV2Error", "canonical_bytes", "csv_bytes", "fixture_matrix", "frozen_matrix", "jsonl_bytes",
    "reconstruct", "reconstruct_fixture", "run_episode", "run_fixture", "run_frozen",
]
