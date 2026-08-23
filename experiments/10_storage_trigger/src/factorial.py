"""Synthetic storage x triggering factorial with an explicitly non-VLA planner."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
import hashlib
import importlib
import io
import itertools
import json
from pathlib import Path
import struct
from typing import Any, Iterable, Mapping, Sequence
import zlib

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "storage-trigger-factorial-v1.json"
SEEDS_PATH = ROOT / "configs" / "seeds-v1.json"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="ascii"))
SEED_MANIFEST = json.loads(SEEDS_PATH.read_text(encoding="ascii"))
STORAGE_VARIANTS = tuple(CONFIG["storage_variants"])
TRIGGER_VARIANTS = tuple(CONFIG["trigger_variants"])
DISTURBANCE_FAMILIES = tuple(CONFIG["disturbance_families"])
SEVERITIES = tuple(CONFIG["severities"])
HORIZONS = tuple(CONFIG["mission_horizons"])
SEEDS = tuple(SEED_MANIFEST["seeds"])
PLANNER_ID = "ORACLE_TYPED_SEMANTIC_V1"
CLAIM_SCOPE = "SYNTHETIC_ENGINEERING_ORACLE_NOT_VLA"


class FactorialError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _jsonl(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(_canonical(row) for row in rows)


def _episode_id(storage: str, trigger: str, family: str, severity: str, horizon: int, seed: int) -> str:
    return f"{storage}__{trigger}__{family}__{severity}__H{horizon}__S{seed}"


def frozen_matrix() -> tuple[dict[str, Any], ...]:
    rows = []
    for storage, trigger, family, severity, horizon, seed in itertools.product(
        STORAGE_VARIANTS, TRIGGER_VARIANTS, DISTURBANCE_FAMILIES, SEVERITIES, HORIZONS, SEEDS
    ):
        rows.append({
            "claim_scope": CLAIM_SCOPE,
            "disturbance_family": family,
            "episode_id": _episode_id(storage, trigger, family, severity, horizon, seed),
            "horizon": horizon,
            "planner_id": PLANNER_ID,
            "seed": seed,
            "severity": severity,
            "storage_variant": storage,
            "trigger_variant": trigger,
        })
    return tuple(rows)


def initial_task(seed: int) -> dict[str, Any]:
    exp04 = importlib.import_module("experiments.04_memory.src.unfixed_ablation")
    observations, _truth = exp04.generate_seed(seed)
    entities: dict[str, dict[str, Any]] = {}
    restrictions: dict[str, bool] = {}
    for event in observations[0]["events"]:
        subject = str(event["subject_id"])
        kind = str(event["event_kind"])
        if kind == "RESTRICTION":
            restrictions[subject] = bool(event["value"])
        else:
            field_name = {"ROOM": "room_id", "AVAILABILITY": "availability", "POSE": "pose"}[kind]
            entities.setdefault(subject, {})[field_name] = event["value"]
    eligible = sorted(
        (entity for entity, state in entities.items() if state["availability"] == "AVAILABLE" and not restrictions[state["room_id"]]),
        key=lambda entity: (entities[entity]["room_id"], entity),
    )
    return {
        "entities": entities,
        "initial_target": eligible[0],
        "restrictions": restrictions,
        "source_generator": "experiments.04_memory.src.unfixed_ablation.generate_seed",
    }


def _copy_world(initial: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, bool]]:
    entities = json.loads(json.dumps(initial["entities"]))
    restrictions = json.loads(json.dumps(initial["restrictions"]))
    return entities, restrictions


def _apply_event(entities: dict[str, dict[str, Any]], restrictions: dict[str, bool], event: Mapping[str, Any]) -> None:
    kind = str(event["event_kind"])
    subject = str(event["subject_id"])
    if kind == "RESTRICTION":
        restrictions[subject] = bool(event["value"])
    elif kind in {"ROOM", "AVAILABILITY", "POSE"}:
        field_name = {"ROOM": "room_id", "AVAILABILITY": "availability", "POSE": "pose"}[kind]
        entities[subject][field_name] = event["value"]


@dataclass
class StorageState:
    variant: str
    initial: Mapping[str, Any]
    belief_entities: dict[str, dict[str, Any]] = field(init=False)
    belief_restrictions: dict[str, bool] = field(init=False)
    episodes: list[dict[str, Any]] = field(default_factory=list)
    transient: list[dict[str, Any]] = field(default_factory=list)
    reads: int = 0
    writes: int = 0
    latest_write_tick: int = 0

    def __post_init__(self) -> None:
        if self.variant not in STORAGE_VARIANTS:
            raise FactorialError("unknown storage variant")
        self.belief_entities, self.belief_restrictions = _copy_world(self.initial)

    def ingest(self, event: Mapping[str, Any]) -> None:
        row = dict(event)
        tick = int(row["tick"])
        if self.variant == "NO_MEMORY":
            self.transient = [row]
            return
        if self.variant == "FIXED_SNAPSHOT":
            return
        if self.variant in {"EPISODIC_ONLY", "LIVE_EPISODIC"}:
            self.episodes.append(row)
            self.writes += 1
            self.latest_write_tick = tick
        if self.variant in {"LIVE_BELIEF", "LIVE_EPISODIC"} and row["event_kind"] != "ATTEMPT":
            _apply_event(self.belief_entities, self.belief_restrictions, row)
            self.writes += 1
            self.latest_write_tick = tick

    def view(self, tick: int) -> dict[str, Any]:
        self.reads += 1
        if self.variant == "NO_MEMORY":
            entities, restrictions = _copy_world(self.initial)
            events = list(self.transient)
            self.transient.clear()
            for event in events:
                _apply_event(entities, restrictions, event)
            failures = [event["subject_id"] for event in events if event["event_kind"] == "ATTEMPT"]
        elif self.variant == "EPISODIC_ONLY":
            entities, restrictions = _copy_world(self.initial)
            for event in self.episodes:
                _apply_event(entities, restrictions, event)
            failures = [event["subject_id"] for event in self.episodes if event["event_kind"] == "ATTEMPT"]
        else:
            entities = json.loads(json.dumps(self.belief_entities))
            restrictions = dict(self.belief_restrictions)
            failures = [event["subject_id"] for event in self.episodes if event["event_kind"] == "ATTEMPT"]
        return {"entities": entities, "failures": sorted(set(failures)), "restrictions": restrictions, "tick": tick}

    def stats(self, tick: int = 0) -> dict[str, Any]:
        if self.variant == "NO_MEMORY":
            size = 0
        elif self.variant == "EPISODIC_ONLY":
            size = len(_canonical(self.episodes))
        elif self.variant == "LIVE_EPISODIC":
            size = len(_canonical({"entities": self.belief_entities, "episodes": self.episodes, "restrictions": self.belief_restrictions}))
        else:
            size = len(_canonical({"entities": self.belief_entities, "restrictions": self.belief_restrictions}))
        return {
            "age_ticks": max(0, tick - self.latest_write_tick),
            "bytes": size,
            "reads": self.reads,
            "writes": self.writes,
        }


@dataclass
class TriggerState:
    variant: str
    armed: bool = True
    last_wake: int = -10_000
    pending_event: bool = False

    def __post_init__(self) -> None:
        if self.variant not in TRIGGER_VARIANTS:
            raise FactorialError("unknown trigger variant")

    def decide(self, *, tick: int, material_event: bool, failures: int, plan_valid: bool) -> tuple[bool, str]:
        if self.variant == "NO_REPLAN":
            return False, "DISABLED"
        if self.variant == "PERIODIC_ONLY":
            return (True, "PERIODIC") if tick % int(CONFIG["period_ticks"]) == 0 else (False, "NONE")
        failure_due = failures >= int(CONFIG["failure_threshold"]) and self.armed
        if self.variant == "FAILURE_THRESHOLD":
            if failure_due:
                self.armed = False
                self.last_wake = tick
                return True, "FAILURE"
            return False, "NONE"
        if self.variant == "EVENT_DRIVEN":
            if material_event:
                self.last_wake = tick
                return True, "EVENT"
            return False, "NONE"
        self.pending_event = self.pending_event or material_event
        reason = "EVENT" if self.pending_event else ("FAILURE" if failure_due else ("PERIODIC" if tick % int(CONFIG["period_ticks"]) == 0 else "NONE"))
        if reason == "NONE":
            return False, reason
        if tick - self.last_wake < int(CONFIG["hybrid_cooldown_ticks"]):
            return False, "COOLDOWN_SUPPRESSED"
        self.last_wake = tick
        if reason == "EVENT":
            self.pending_event = False
        if reason == "FAILURE":
            self.armed = False
        return True, reason

    def note_success(self) -> None:
        self.armed = True


def _eligible(view: Mapping[str, Any]) -> list[str]:
    return sorted(
        (
            entity for entity, state in view["entities"].items()
            if state["availability"] == "AVAILABLE" and not view["restrictions"].get(state["room_id"], False)
        ),
        key=lambda entity: (view["entities"][entity]["room_id"], entity),
    )


def _plan(view: Mapping[str, Any]) -> dict[str, Any]:
    eligible = _eligible(view)
    failures = set(view["failures"])
    alternatives = [entity for entity in eligible if entity not in failures]
    target = alternatives[0] if alternatives else (eligible[0] if eligible else None)
    return {
        "affordance": "service_valve",
        "planner_id": PLANNER_ID,
        "pose": view["entities"].get(target, {}).get("pose") if target else None,
        "subgoals": ["approach", "inspect", "actuate", "verify"],
        "target": target,
    }


def _valid(entities: Mapping[str, Mapping[str, Any]], restrictions: Mapping[str, bool], plan: Mapping[str, Any]) -> bool:
    target = plan.get("target")
    if target not in entities:
        return False
    state = entities[str(target)]
    if state["availability"] != "AVAILABLE" or restrictions.get(str(state["room_id"]), False):
        return False
    return plan.get("pose") == state["pose"]


def _disturbance_events(
    initial: Mapping[str, Any], entities: Mapping[str, Mapping[str, Any]], family: str, severity: str, tick: int, target: str,
) -> tuple[list[dict[str, Any]], int, str | None]:
    candidates = [entity for entity in sorted(entities) if entity != target]
    events: list[dict[str, Any]] = []
    if family == "POSE_SHIFT":
        delta = 0.4 if severity == "LOW" else 1.2
        pose = entities[target]["pose"]
        events.append({"event_kind": "POSE", "subject_id": target, "tick": tick, "value": [round(pose[0] + delta, 6), round(pose[1] - delta, 6)]})
    elif family == "AVAILABILITY_LOSS":
        events.append({"event_kind": "AVAILABILITY", "subject_id": target, "tick": tick, "value": "UNAVAILABLE"})
        if severity == "HIGH" and candidates:
            events.append({"event_kind": "AVAILABILITY", "subject_id": candidates[0], "tick": tick, "value": "UNAVAILABLE"})
    elif family == "RESTRICTION_CHANGE":
        events.append({"event_kind": "RESTRICTION", "subject_id": entities[target]["room_id"], "tick": tick, "value": True})
        if severity == "HIGH" and candidates:
            events.append({"event_kind": "RESTRICTION", "subject_id": entities[candidates[0]]["room_id"], "tick": tick, "value": True})
    else:
        return [], 1 if severity == "LOW" else 3, target
    return events, 0, None


def run_episode(cell: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    initial = initial_task(int(cell["seed"]))
    entities, restrictions = _copy_world(initial)
    store = StorageState(str(cell["storage_variant"]), initial)
    trigger = TriggerState(str(cell["trigger_variant"]))
    plan = _plan(store.view(0))
    semantic_wakes = 1
    motion_wakes = 1
    control_wakes = retries = escalations = repeated_failures = 0
    stale_decisions = 0
    false_triggers = wasted_triggers = late_trigger_ticks = 0
    progress = 0
    consecutive_failures = 0
    last_failed_target: str | None = None
    control_remaining = 0
    control_target: str | None = None
    pending_attempt_event = False
    required_since: int | None = None
    trigger_latencies: list[int] = []
    steps: list[dict[str, Any]] = []
    horizon = int(cell["horizon"])
    disturbance_tick = max(2, horizon // 2)
    for tick in range(1, horizon + int(CONFIG["recovery_allowance_ticks"]) + 1):
        events: list[dict[str, Any]] = []
        if tick == disturbance_tick:
            generated, control_remaining, control_target = _disturbance_events(
                initial, entities, str(cell["disturbance_family"]), str(cell["severity"]), tick, str(plan["target"])
            )
            events.extend(generated)
            for event in generated:
                _apply_event(entities, restrictions, event)
                store.ingest(event)
        material_event = bool(events) or pending_attempt_event
        pending_attempt_event = False
        valid_before = _valid(entities, restrictions, plan)
        failures_before = consecutive_failures
        if (not valid_before or consecutive_failures > 0) and required_since is None:
            required_since = tick
        wake, wake_reason = trigger.decide(
            tick=tick, material_event=material_event, failures=consecutive_failures, plan_valid=valid_before
        )
        plan_before = dict(plan)
        plan_changed = False
        if wake:
            semantic_wakes += 1
            view = store.view(tick)
            plan = _plan(view)
            if plan != plan_before:
                plan_changed = True
                motion_wakes += 1
            else:
                wasted_triggers += 1
            if valid_before and consecutive_failures == 0 and not material_event:
                false_triggers += 1
            if wake_reason == "FAILURE":
                escalations += 1
            if required_since is not None:
                trigger_latencies.append(tick - required_since)
                required_since = None
        valid_after = _valid(entities, restrictions, plan)
        stale_decision = not valid_after
        stale_decisions += int(stale_decision)
        failed = stale_decision
        if valid_after and control_remaining > 0 and plan["target"] == control_target:
            failed = True
            control_remaining -= 1
        if failed:
            retries += 1
            control_wakes += 1
            consecutive_failures += 1
            if last_failed_target == plan.get("target"):
                repeated_failures += 1
            last_failed_target = str(plan.get("target"))
            attempt = {"event_kind": "ATTEMPT", "subject_id": plan.get("target"), "tick": tick, "value": "FAILED"}
            store.ingest(attempt)
            pending_attempt_event = True
            if required_since is None:
                required_since = tick
        else:
            progress += 1
            consecutive_failures = 0
            last_failed_target = None
            trigger.note_success()
        if required_since is not None and not wake:
            late_trigger_ticks += 1
        stats = store.stats(tick)
        steps.append({
            "claim_scope": CLAIM_SCOPE,
            "completion_progress": min(progress, horizon) / horizon,
            "consecutive_failures": consecutive_failures,
            "control_wake": int(failed),
            "disturbance_family": cell["disturbance_family"],
            "episode_id": cell["episode_id"],
            "events": events,
            "execution_failed": failed,
            "failures_before": failures_before,
            "horizon": horizon,
            "material_event": material_event,
            "motion_wake": int(wake and plan != plan_before),
            "plan": plan,
            "plan_changed": plan_changed,
            "plan_valid": valid_after,
            "plan_valid_before": valid_before,
            "planner_id": PLANNER_ID,
            "seed": cell["seed"],
            "semantic_wake": int(wake),
            "severity": cell["severity"],
            "stale_decision": stale_decision,
            "storage": stats,
            "storage_variant": cell["storage_variant"],
            "tick": tick,
            "trigger_reason": wake_reason,
            "trigger_variant": cell["trigger_variant"],
        })
        if progress >= horizon:
            break
    stats = store.stats(steps[-1]["tick"])
    total_latency = sum(trigger_latencies)
    semantic_latency_proxy = semantic_wakes * 0.2 + stats["reads"] * 0.03 + stats["bytes"] / 100_000
    motion_latency_proxy = motion_wakes * 0.12
    control_latency_proxy = control_wakes * 0.04
    cost_proxy = semantic_wakes * 10 + motion_wakes * 4 + control_wakes * 2 + stats["reads"] * 0.05 + stats["bytes"] / 1024
    episode = {
        **cell,
        "aborts": int(progress < horizon),
        "budget_cost_proxy": round(cost_proxy, 6),
        "completion": int(progress >= horizon),
        "control_wakes": control_wakes,
        "control_latency_proxy_ms": round(control_latency_proxy, 6),
        "escalations": escalations,
        "false_triggers": false_triggers,
        "late_trigger_ticks": late_trigger_ticks,
        "motion_wakes": motion_wakes,
        "motion_latency_proxy_ms": round(motion_latency_proxy, 6),
        "progress": round(min(progress, horizon) / horizon, 6),
        "repeated_failures": repeated_failures,
        "retries": retries,
        "semantic_latency_proxy_ms": round(semantic_latency_proxy, 6),
        "semantic_wakes": semantic_wakes,
        "storage_age_ticks": stats["age_ticks"],
        "storage_bytes": stats["bytes"],
        "storage_reads": stats["reads"],
        "storage_writes": stats["writes"],
        "stale_decisions": stale_decisions,
        "trigger_latency_ticks_mean": round(total_latency / len(trigger_latencies), 6) if trigger_latencies else 0.0,
        "wasted_triggers": wasted_triggers,
    }
    return episode, steps


EPISODE_FIELDS = (
    "episode_id", "seed", "storage_variant", "trigger_variant", "disturbance_family", "severity", "horizon",
    "planner_id", "claim_scope", "completion", "progress", "repeated_failures", "false_triggers",
    "late_trigger_ticks", "wasted_triggers", "semantic_wakes", "motion_wakes", "control_wakes",
    "semantic_latency_proxy_ms", "motion_latency_proxy_ms", "control_latency_proxy_ms", "trigger_latency_ticks_mean",
    "retries", "escalations", "aborts", "stale_decisions",
    "storage_reads", "storage_writes", "storage_bytes", "storage_age_ticks", "budget_cost_proxy",
)


def _csv_bytes(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row[field] for field in fields})
    return output.getvalue().encode("ascii")


def _read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="ascii"))))


def _mean(rows: Sequence[Mapping[str, Any]], field: str) -> float:
    return sum(float(row[field]) for row in rows) / len(rows) if rows else 0.0


def _group_summary(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> list[dict[str, Any]]:
    metrics = (
        "completion", "progress", "repeated_failures", "false_triggers", "late_trigger_ticks", "wasted_triggers",
        "semantic_wakes", "motion_wakes", "control_wakes", "semantic_latency_proxy_ms", "motion_latency_proxy_ms",
        "control_latency_proxy_ms", "trigger_latency_ticks_mean", "stale_decisions",
        "retries", "escalations", "aborts", "storage_reads", "storage_writes", "storage_bytes",
        "storage_age_ticks", "budget_cost_proxy",
    )
    output = []
    keys = sorted({tuple(row[field] for field in fields) for row in rows})
    for key in keys:
        selected = [row for row in rows if tuple(row[field] for field in fields) == key]
        output.append({**dict(zip(fields, key, strict=True)), "episode_count": len(selected), **{f"{metric}_mean": round(_mean(selected, metric), 8) for metric in metrics}})
    return output


def _paired_contrasts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    definitions = []
    for storage in STORAGE_VARIANTS:
        definitions.append((f"HYBRID_MINUS_PERIODIC__{storage}", "trigger_variant", "HYBRID", "PERIODIC_ONLY", "storage_variant", storage))
    for trigger in TRIGGER_VARIANTS:
        definitions.append((f"LIVE_EPISODIC_MINUS_FIXED__{trigger}", "storage_variant", "LIVE_EPISODIC", "FIXED_SNAPSHOT", "trigger_variant", trigger))
    metrics = ("completion", "progress", "late_trigger_ticks", "wasted_triggers", "budget_cost_proxy")
    output = []
    for definition_index, (contrast, axis, candidate, comparator, hold_axis, hold_value) in enumerate(definitions):
        subset = [row for row in rows if row[hold_axis] == hold_value]
        seeds = sorted({int(row["seed"]) for row in subset})
        for metric in metrics:
            differences = []
            used_seeds = []
            for seed in seeds:
                candidate_rows = [row for row in subset if int(row["seed"]) == seed and row[axis] == candidate]
                comparator_rows = [row for row in subset if int(row["seed"]) == seed and row[axis] == comparator]
                if candidate_rows and len(candidate_rows) == len(comparator_rows):
                    differences.append(_mean(candidate_rows, metric) - _mean(comparator_rows, metric))
                    used_seeds.append(seed)
            if not differences:
                continue
            values = np.asarray(differences, dtype=np.float64)
            rng = np.random.Generator(np.random.PCG64(int(CONFIG["bootstrap_seed"]) + definition_index * 17 + metrics.index(metric)))
            indices = rng.integers(0, len(values), size=(int(CONFIG["bootstrap_draws"]), len(values)))
            draws = values[indices].mean(axis=1)
            q025, q975 = np.quantile(draws, (0.025, 0.975), method="linear")
            output.append({
                "bootstrap_draws": CONFIG["bootstrap_draws"], "candidate": candidate, "comparator": comparator,
                "contrast": contrast, "effective_seed_n": len(used_seeds), "estimate": round(float(values.mean()), 8),
                "metric": metric, "q025": round(float(q025), 8), "q975": round(float(q975), 8),
                "seed_cluster_sha256": _sha(_canonical(used_seeds)),
            })
    return output


def _png(width: int, height: int, pixels: bytes) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    scanlines = b"".join(b"\x00" + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))
    return signature + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(scanlines, 9)) + chunk(b"IEND", b"")


def _graph(summary: Sequence[Mapping[str, Any]]) -> tuple[bytes, bytes, bytes]:
    by = {(row["storage_variant"], row["trigger_variant"]): float(row["completion_mean"]) for row in summary}
    style = {
        "background": "#ffffff", "cell_missing": "#d9d9d9", "cell_zero": "#f7fbff", "cell_one": "#08519c",
        "font": "monospace", "height": 360, "metric": "completion_mean", "theme_independent": True,
        "width": 600, "x_order": list(TRIGGER_VARIANTS), "y_order": list(STORAGE_VARIANTS),
    }
    width, height = 600, 360
    pixels = bytearray([255] * width * height * 3)
    svg_parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/><g font-family="monospace" font-size="11">']
    for y_index, storage in enumerate(STORAGE_VARIANTS):
        svg_parts.append(f'<text x="5" y="{86 + y_index * 48}">{storage}</text>')
        for x_index, trigger in enumerate(TRIGGER_VARIANTS):
            value = by.get((storage, trigger))
            rgb = (217, 217, 217) if value is None else (round(247 - 239 * value), round(251 - 170 * value), round(255 - 99 * value))
            x0, y0, cell_w, cell_h = 160 + x_index * 82, 60 + y_index * 48, 76, 40
            for y in range(y0, y0 + cell_h):
                for x in range(x0, x0 + cell_w):
                    index = (y * width + x) * 3
                    pixels[index:index + 3] = bytes(rgb)
            color = "#d9d9d9" if value is None else f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            label = "NA" if value is None else f"{value:.3f}"
            svg_parts.append(f'<rect x="{x0}" y="{y0}" width="{cell_w}" height="{cell_h}" fill="{color}" stroke="#333"/><text x="{x0 + 18}" y="{y0 + 24}">{label}</text>')
    for x_index, trigger in enumerate(TRIGGER_VARIANTS):
        svg_parts.append(f'<text transform="translate({180 + x_index * 82},52) rotate(-35)">{trigger}</text>')
    svg_parts.append('<text x="160" y="335">Completion rate; exact values in storage-trigger-summary.csv</text></g></svg>\n')
    return "".join(svg_parts).encode("ascii"), _png(width, height, bytes(pixels)), _canonical(style)


def _rescore_steps(rows: Sequence[Mapping[str, Any]], horizon: int) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: int(row["tick"]))
    if not ordered or [int(row["tick"]) for row in ordered] != list(range(1, len(ordered) + 1)):
        raise FactorialError("step chronology is invalid")
    semantic_wakes = 1 + sum(int(row["semantic_wake"]) for row in ordered)
    motion_wakes = 1 + sum(int(row["motion_wake"]) for row in ordered)
    control_wakes = sum(int(bool(row["execution_failed"])) for row in ordered)
    stale_decisions = sum(int(bool(row["stale_decision"])) for row in ordered)
    false_triggers = sum(
        int(
            bool(row["semantic_wake"]) and bool(row["plan_valid_before"])
            and int(row["failures_before"]) == 0 and not bool(row["material_event"])
        )
        for row in ordered
    )
    wasted_triggers = sum(int(bool(row["semantic_wake"]) and not bool(row["plan_changed"])) for row in ordered)
    escalations = sum(int(bool(row["semantic_wake"]) and row["trigger_reason"] == "FAILURE") for row in ordered)
    repeated_failures = 0
    last_failed_target: str | None = None
    required_since: int | None = None
    late_trigger_ticks = 0
    trigger_latencies: list[int] = []
    for row in ordered:
        tick = int(row["tick"])
        if (not bool(row["plan_valid_before"]) or int(row["failures_before"]) > 0) and required_since is None:
            required_since = tick
        if bool(row["semantic_wake"]) and required_since is not None:
            trigger_latencies.append(tick - required_since)
            required_since = None
        if bool(row["execution_failed"]):
            target = str(row["plan"].get("target"))
            if last_failed_target == target:
                repeated_failures += 1
            last_failed_target = target
            if required_since is None:
                required_since = tick
        else:
            last_failed_target = None
        if required_since is not None and not bool(row["semantic_wake"]):
            late_trigger_ticks += 1
    final = ordered[-1]
    stats = final["storage"]
    progress = round(float(final["completion_progress"]), 6)
    semantic_latency = semantic_wakes * 0.2 + int(stats["reads"]) * 0.03 + int(stats["bytes"]) / 100_000
    cost = semantic_wakes * 10 + motion_wakes * 4 + control_wakes * 2 + int(stats["reads"]) * 0.05 + int(stats["bytes"]) / 1024
    return {
        "aborts": int(progress < 1.0),
        "budget_cost_proxy": round(cost, 6),
        "completion": int(progress >= 1.0),
        "control_latency_proxy_ms": round(control_wakes * 0.04, 6),
        "control_wakes": control_wakes,
        "escalations": escalations,
        "false_triggers": false_triggers,
        "late_trigger_ticks": late_trigger_ticks,
        "motion_latency_proxy_ms": round(motion_wakes * 0.12, 6),
        "motion_wakes": motion_wakes,
        "progress": progress,
        "repeated_failures": repeated_failures,
        "retries": control_wakes,
        "semantic_latency_proxy_ms": round(semantic_latency, 6),
        "semantic_wakes": semantic_wakes,
        "stale_decisions": stale_decisions,
        "storage_age_ticks": int(stats["age_ticks"]),
        "storage_bytes": int(stats["bytes"]),
        "storage_reads": int(stats["reads"]),
        "storage_writes": int(stats["writes"]),
        "trigger_latency_ticks_mean": round(sum(trigger_latencies) / len(trigger_latencies), 6) if trigger_latencies else 0.0,
        "wasted_triggers": wasted_triggers,
    }


def _validate_episode_scores(episodes: Sequence[Mapping[str, Any]], steps: Sequence[Mapping[str, Any]]) -> None:
    by_episode: dict[str, list[Mapping[str, Any]]] = {}
    for row in steps:
        by_episode.setdefault(str(row["episode_id"]), []).append(row)
    if set(by_episode) != {str(row["episode_id"]) for row in episodes}:
        raise FactorialError("step/episode inventory mismatch")
    integer_fields = {
        "aborts", "completion", "control_wakes", "escalations", "false_triggers", "late_trigger_ticks",
        "motion_wakes", "repeated_failures", "retries", "semantic_wakes", "stale_decisions", "storage_age_ticks",
        "storage_bytes", "storage_reads", "storage_writes", "wasted_triggers",
    }
    for episode in episodes:
        expected = _rescore_steps(by_episode[str(episode["episode_id"])], int(episode["horizon"]))
        for metric, value in expected.items():
            actual = int(episode[metric]) if metric in integer_fields else float(episode[metric])
            if actual != value:
                raise FactorialError(f"episode score mismatch for {metric}")


def _derive(raw: Path) -> dict[str, bytes]:
    manifest_bytes = (raw / "raw-manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if _canonical(manifest) != manifest_bytes:
        raise FactorialError("raw manifest is not canonical")
    actual_members = []
    for path in sorted(raw.iterdir()):
        if path.is_file() and path.name != "raw-manifest.json":
            actual_members.append({"bytes": path.stat().st_size, "path": path.name, "sha256": _sha(path.read_bytes())})
    if manifest.get("members") != actual_members:
        raise FactorialError("raw manifest member mismatch")
    rows = _read_csv(raw / "episodes.csv")
    if len(rows) != manifest["episode_count"] or len({row["episode_id"] for row in rows}) != len(rows):
        raise FactorialError("raw manifest episode identity mismatch")
    if {row["planner_id"] for row in rows} != {PLANNER_ID} or {row["claim_scope"] for row in rows} != {CLAIM_SCOPE}:
        raise FactorialError("planner/claim identity mismatch")
    steps = [json.loads(line) for line in (raw / "steps.jsonl").read_text(encoding="ascii").splitlines()]
    if len(steps) != manifest["step_count"]:
        raise FactorialError("step count mismatch")
    _validate_episode_scores(rows, steps)
    cell = _group_summary(rows, ("storage_variant", "trigger_variant", "disturbance_family", "severity", "horizon"))
    storage_trigger = _group_summary(rows, ("storage_variant", "trigger_variant"))
    trigger_profile = _group_summary(rows, ("trigger_variant",))
    contrasts = _paired_contrasts(rows)
    samples = []
    for storage, trigger in itertools.product(STORAGE_VARIANTS, TRIGGER_VARIANTS):
        selected = sorted((row for row in rows if row["storage_variant"] == storage and row["trigger_variant"] == trigger), key=lambda row: row["episode_id"])
        for label, desired in (("WORKING", "1"), ("NONWORKING", "0")):
            match = next((row for row in selected if row["completion"] == desired), None)
            samples.append({
                "class": label if match else "CLASS_NOT_OBSERVED", "episode_id": match["episode_id"] if match else None,
                "storage_variant": storage, "trigger_variant": trigger,
            })
    svg, png, style = _graph(storage_trigger)
    strongest = max((row for row in contrasts if row["metric"] == "completion"), key=lambda row: abs(float(row["estimate"])), default=None)
    strongest_text = "No complete paired contrast was available."
    if strongest:
        strongest_text = f"Strongest completion contrast was {strongest['contrast']}: {float(strongest['estimate']):+.4f} (95% {float(strongest['q025']):+.4f} to {float(strongest['q975']):+.4f}; seed-cluster n={strongest['effective_seed_n']})."
    report = (
        "# Experiment 10 Storage x Trigger Factorial\n\n"
        f"Status: SYNTHETIC_ENGINEERING_RESULT\n\nCompleted {len(rows)} paired synthetic episodes with {PLANNER_ID}. "
        + strongest_text + "\n\nThis deterministic typed planner is not pi0.5, a VLA, or frontline model evidence. Results isolate only the frozen storage and trigger implementations in this synthetic task.\n"
    ).encode("ascii")
    cell_fields = tuple(cell[0]) if cell else ()
    storage_fields = tuple(storage_trigger[0]) if storage_trigger else ()
    trigger_fields = tuple(trigger_profile[0]) if trigger_profile else ()
    contrast_fields = tuple(contrasts[0]) if contrasts else ()
    return {
        "RESULTS.md": report,
        "annotations.json": _canonical({"samples": samples, "selection": "FIRST_CANONICAL_WORKING_AND_NONWORKING_PER_STORAGE_TRIGGER"}),
        "cell-summary.csv": _csv_bytes(cell, cell_fields),
        "contrasts.csv": _csv_bytes(contrasts, contrast_fields),
        "plot-style.json": style,
        "storage-trigger-summary.csv": _csv_bytes(storage_trigger, storage_fields),
        "storage-trigger.svg": svg,
        "storage-trigger.png": png,
        "trigger-profile.csv": _csv_bytes(trigger_profile, trigger_fields),
    }


def _publish(output: Path, cells: Sequence[Mapping[str, Any]], *, implementation_git_sha: str) -> None:
    if output.exists() or len(implementation_git_sha) != 40:
        raise FactorialError("output must be absent and implementation SHA exact")
    raw = output / "raw"
    derived = output / "derived"
    raw.mkdir(parents=True)
    derived.mkdir()
    episodes: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for cell in cells:
        episode, episode_steps = run_episode(cell)
        episodes.append(episode)
        steps.extend(episode_steps)
    episodes.sort(key=lambda row: row["episode_id"])
    steps.sort(key=lambda row: (row["episode_id"], row["tick"]))
    (raw / "config.json").write_bytes(CONFIG_PATH.read_bytes())
    (raw / "seeds.json").write_bytes(SEEDS_PATH.read_bytes())
    (raw / "episodes.csv").write_bytes(_csv_bytes(episodes, EPISODE_FIELDS))
    (raw / "steps.jsonl").write_bytes(_jsonl(steps))
    members = [{"bytes": path.stat().st_size, "path": path.name, "sha256": _sha(path.read_bytes())} for path in sorted(raw.iterdir())]
    manifest = {
        "claim_scope": CLAIM_SCOPE, "episode_count": len(episodes), "implementation_git_sha": implementation_git_sha,
        "implementation_source_sha256": _sha(Path(__file__).read_bytes()), "matrix_identity_sha256": _sha(_canonical([row["episode_id"] for row in episodes])),
        "members": members, "planner_id": PLANNER_ID, "schema_version": 1, "step_count": len(steps),
    }
    (raw / "raw-manifest.json").write_bytes(_canonical(manifest))
    files = _derive(raw)
    for name, content in files.items():
        (derived / name).write_bytes(content)
    derived_members = [{"bytes": path.stat().st_size, "path": path.name, "sha256": _sha(path.read_bytes())} for path in sorted(derived.iterdir())]
    (derived / "derived-manifest.json").write_bytes(_canonical({"members": derived_members, "schema_version": 1}))


def run_fixture(output: Path, *, implementation_git_sha: str) -> None:
    cells = [
        row for row in frozen_matrix()
        if row["storage_variant"] in {"FIXED_SNAPSHOT", "LIVE_EPISODIC"}
        and row["trigger_variant"] in {"NO_REPLAN", "HYBRID"}
        and row["disturbance_family"] in {"POSE_SHIFT", "CONTROL_FAILURE"}
        and row["severity"] == "HIGH" and row["horizon"] == 4 and row["seed"] in SEEDS[:2]
    ]
    _publish(output, cells, implementation_git_sha=implementation_git_sha)


def run_frozen(output: Path, *, implementation_git_sha: str) -> None:
    _publish(output, frozen_matrix(), implementation_git_sha=implementation_git_sha)


def reconstruct(raw: Path, destination: Path) -> None:
    if destination.exists() or not raw.is_dir() or raw.is_symlink():
        raise FactorialError("raw must be regular and destination absent")
    files = _derive(raw)
    destination.mkdir()
    for name, content in files.items():
        (destination / name).write_bytes(content)
    members = [{"bytes": path.stat().st_size, "path": path.name, "sha256": _sha(path.read_bytes())} for path in sorted(destination.iterdir())]
    (destination / "derived-manifest.json").write_bytes(_canonical({"members": members, "schema_version": 1}))
