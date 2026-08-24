"""Frozen runner, validator, estimator, and reconstructor for Experiment 11 V2."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import itertools
import json
from pathlib import Path
import platform
import random
import struct
import subprocess
from typing import Any, Iterable, Mapping, Sequence
import zlib

from .kernel_v2 import CLAIM_SCOPE, PLANNER_ID, canonical, simulate
from .replay_v2 import ReplayError, score_episode


ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "configs/trigger-robustness-v2.json"
SEEDS_PATH = ROOT / "configs/seeds-v2.json"
RETIREMENT_PATH = ROOT / "configs/retired-attempts-v2.json"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="ascii"))
SEED_MANIFEST = json.loads(SEEDS_PATH.read_text(encoding="ascii"))
SEEDS = tuple(SEED_MANIFEST["seeds"])
SOURCE_PATHS = (
    ".python-version",
    "docs/superpowers/plans/2026-08-24-trigger-robustness-dose-response-v2.md",
    "experiments/__init__.py",
    "experiments/11_trigger_robustness/__init__.py",
    "experiments/11_trigger_robustness/configs/retired-attempts-v2.json",
    "experiments/11_trigger_robustness/configs/seeds-v2.json",
    "experiments/11_trigger_robustness/configs/trigger-robustness-v2.json",
    "experiments/11_trigger_robustness/src/__init__.py",
    "experiments/11_trigger_robustness/src/experiment_v2.py",
    "experiments/11_trigger_robustness/src/kernel_v2.py",
    "experiments/11_trigger_robustness/src/replay_v2.py",
    "pyproject.toml",
    "uv.lock",
)
METRICS = (
    "completion", "progress", "retries", "wakes", "false_wakes", "late_wakes", "wasted_wakes", "thrash",
    "trigger_precision", "trigger_recall", "cost_proxy", "storage_reads", "storage_writes", "storage_bytes",
    "storage_age", "escalation_event", "escalation_failure",
)


class IntegrityError(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jsonl(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical(row) for row in rows)


def csv_data(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row[field] for field in fields})
    return output.getvalue().encode("ascii")


def read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="ascii"))))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]


def _head() -> str:
    return subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=REPO, text=True).strip()


def _git_blob(commit: str, path: str) -> bytes:
    try:
        return subprocess.check_output(("git", "show", f"{commit}:{path}"), cwd=REPO)
    except subprocess.CalledProcessError as exc:
        raise IntegrityError("implementation source commit closure mismatch") from exc


def quality_by_id(identifier: str, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    source = CONFIG if config is None else config
    try:
        return next(dict(row) for row in source["quality_profiles"] if row["id"] == identifier)
    except StopIteration as exc:
        raise IntegrityError("unknown quality profile") from exc


def episode_id(cell: Mapping[str, Any]) -> str:
    keys = ("storage_variant", "trigger_policy", "quality_id", "disturbance_family", "severity")
    return "__".join(str(cell[key]) for key in keys) + f"__H{cell['horizon']}__{cell['prompt_envelope']}__S{cell['seed']}"


def _matrix(seeds: Sequence[int], *, fixture: bool) -> tuple[dict[str, Any], ...]:
    qualities = ("Q00_CLEAN", "Q09_HOSTILE") if fixture else tuple(row["id"] for row in CONFIG["quality_profiles"])
    families = ("POSE_SHIFT", "CONTROL_FAILURE") if fixture else tuple(CONFIG["disturbance_families"])
    severities = ("HIGH",) if fixture else tuple(CONFIG["severities"])
    horizons = (4,) if fixture else tuple(CONFIG["mission_horizons"])
    rows = []
    for storage, policy, quality, family, severity, horizon, envelope, seed in itertools.product(
        CONFIG["storage_variants"], CONFIG["trigger_policies"], qualities, families, severities,
        horizons, CONFIG["prompt_envelopes"], seeds,
    ):
        cell = {"claim_scope": CLAIM_SCOPE, "disturbance_family": family, "horizon": horizon, "planner_id": PLANNER_ID,
                "prompt_envelope": envelope, "quality_id": quality, "seed": seed, "severity": severity,
                "storage_variant": storage, "trigger_policy": policy}
        cell["episode_id"] = episode_id(cell)
        rows.append(cell)
    return tuple(rows)


def frozen_matrix() -> tuple[dict[str, Any], ...]:
    return _matrix(SEEDS, fixture=False)


def fixture_matrix() -> tuple[dict[str, Any], ...]:
    return _matrix(tuple(CONFIG["calibration_seeds"]), fixture=True)


def run_episode(cell: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    return simulate(cell, CONFIG, quality_by_id(str(cell["quality_id"])))


def source_closure() -> list[dict[str, Any]]:
    return [{"bytes": (REPO / path).stat().st_size, "path": path, "sha256": sha((REPO / path).read_bytes())} for path in sorted(SOURCE_PATHS)]


def audit_source_closure(closure: Sequence[Mapping[str, Any]]) -> None:
    if [dict(row) for row in closure] != source_closure():
        raise IntegrityError("source/config/seed/package-init closure mismatch")
    available = {str(row["path"]) for row in closure}
    module_paths = {Path(path).stem: path for path in available if path.startswith("experiments/11_trigger_robustness/src/") and path.endswith(".py")}
    for relative in module_paths.values():
        tree = ast.parse((REPO / relative).read_text(encoding="ascii"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level and node.module:
                target = node.module.split(".")[0]
                if target not in module_paths:
                    raise IntegrityError(f"unclosed local import {target}")


def freeze_receipt(cells: Sequence[Mapping[str, Any]], implementation_git_sha: str, *, fixture: bool) -> dict[str, Any]:
    closure = source_closure()
    audit_source_closure(closure)
    return {
        "claim_scope": CLAIM_SCOPE, "config_sha256": sha(CONFIG_PATH.read_bytes()),
        "environment": {"platform": platform.platform(), "python": platform.python_version()}, "fixture": fixture,
        "implementation_git_sha": implementation_git_sha, "matrix_count": len(cells), "matrix_sha256": sha(jsonl(cells)),
        "planner_id": PLANNER_ID, "retirement_registry_sha256": sha(RETIREMENT_PATH.read_bytes()), "schema_version": 2,
        "seed_manifest_sha256": sha(SEEDS_PATH.read_bytes()), "source_closure": closure,
        "source_closure_sha256": sha(canonical(closure)), "study_id": CONFIG["study_id"],
    }


def _validate_source(freeze: Mapping[str, Any], cells: Sequence[Mapping[str, Any]], *, allow_fixture: bool) -> None:
    fixture = bool(freeze.get("fixture"))
    if fixture and not allow_fixture:
        raise IntegrityError("fixture evidence is not canonical evidence")
    expected = freeze_receipt(cells, str(freeze.get("implementation_git_sha")), fixture=fixture)
    if dict(freeze) != expected:
        raise IntegrityError("canonical freeze/config/seed/matrix/source mismatch")
    commit = str(freeze["implementation_git_sha"])
    if commit != _head():
        try:
            subprocess.check_call(("git", "merge-base", "--is-ancestor", commit, "HEAD"), cwd=REPO)
        except subprocess.CalledProcessError as exc:
            raise IntegrityError("implementation commit is not an ancestor") from exc
    if not fixture:
        for member in freeze["source_closure"]:
            if sha(_git_blob(commit, str(member["path"]))) != member["sha256"]:
                raise IntegrityError("implementation source commit closure mismatch")


def inventory(root: Path, *, exclude: Sequence[str] = ()) -> list[dict[str, Any]]:
    excluded = set(exclude)
    members: list[dict[str, Any]] = []
    if root.is_symlink() or not root.is_dir():
        raise IntegrityError("evidence root must be a regular directory, not a symlink")
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        if path.is_symlink():
            raise IntegrityError("symlink is forbidden in evidence inventory")
        if path.is_file():
            payload = path.read_bytes()
            members.append({"bytes": len(payload), "path": relative, "sha256": sha(payload)})
        elif not path.is_dir():
            raise IntegrityError("non-regular evidence object")
    return members


def _validate_manifest(root: Path, name: str, *, schema: int = 2) -> dict[str, Any]:
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise IntegrityError("manifest must be a regular file")
    payload = path.read_bytes()
    manifest = json.loads(payload)
    if canonical(manifest) != payload or set(manifest) != {"members", "schema_version"} or manifest["schema_version"] != schema:
        raise IntegrityError("manifest canonical schema mismatch")
    declared = manifest["members"]
    if not isinstance(declared, list) or declared != inventory(root, exclude=(name,)):
        raise IntegrityError("recursive inventory mismatch or unlisted member")
    names = [row.get("path") for row in declared]
    if len(names) != len(set(names)) or any(Path(str(item)).is_absolute() or ".." in Path(str(item)).parts for item in names):
        raise IntegrityError("invalid manifest member path")
    return manifest


def _write_manifest(root: Path, name: str = "manifest.json") -> None:
    (root / name).write_bytes(canonical({"members": inventory(root), "schema_version": 2}))


def load_retirement_registry() -> dict[str, Any]:
    payload = RETIREMENT_PATH.read_bytes()
    registry = json.loads(payload)
    if canonical(registry) != payload:
        raise IntegrityError("retirement registry must be canonical")
    if set(registry) != {"attempts", "schema_version"} or registry["schema_version"] != 2:
        raise IntegrityError("retirement registry schema mismatch")
    expected_top = {
        "EXP11_V1_UNPUBLISHED_CONTAMINATED_NAMESPACE": {"attempt_id", "claim_authority", "disposition", "ledger"},
        "EXP11_V1_PUBLISHED": {"attempt_id", "claim_authority", "derived_manifest_sha256", "disposition", "ledger", "raw_manifest_sha256", "result_tree_git_sha256"},
    }
    if {row.get("attempt_id") for row in registry["attempts"]} != set(expected_top):
        raise IntegrityError("retirement registry attempt identity mismatch")
    for row in registry["attempts"]:
        if set(row) != expected_top[str(row["attempt_id"])] or row["claim_authority"] != "NONE":
            raise IntegrityError("retirement registry closed schema mismatch")
    published = next(row for row in registry["attempts"] if row["attempt_id"] == "EXP11_V1_PUBLISHED")
    if published["disposition"] != "INVALID_REJECTED":
        raise IntegrityError("V1 disposition mismatch")
    if published["raw_manifest_sha256"] != sha((ROOT / "results/v1/raw/manifest.json").read_bytes()):
        raise IntegrityError("retired raw manifest mismatch")
    if published["derived_manifest_sha256"] != sha((ROOT / "results/v1/derived/manifest.json").read_bytes()):
        raise IntegrityError("retired derived manifest mismatch")
    return registry


def _validate_raw(raw: Path, *, allow_fixture: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _validate_manifest(raw, "manifest.json")
    expected_names = {"cells.jsonl", "config.json", "freeze.json", "seeds.json", "starts.jsonl", "terminals.jsonl", "ticks.jsonl"}
    if {row["path"] for row in inventory(raw, exclude=("manifest.json",))} != expected_names:
        raise IntegrityError("raw inventory mismatch")
    if (raw / "config.json").read_bytes() != CONFIG_PATH.read_bytes():
        raise IntegrityError("raw config identity drift")
    if (raw / "seeds.json").read_bytes() != SEEDS_PATH.read_bytes():
        raise IntegrityError("raw seed identity drift")
    freeze_payload = (raw / "freeze.json").read_bytes()
    freeze = json.loads(freeze_payload)
    if canonical(freeze) != freeze_payload:
        raise IntegrityError("freeze is not canonical")
    cells = _read_jsonl(raw / "cells.jsonl")
    expected_cells = list(fixture_matrix() if freeze.get("fixture") else frozen_matrix())
    if cells != expected_cells:
        raise IntegrityError("matrix identity drift")
    _validate_source(freeze, cells, allow_fixture=allow_fixture)
    starts = _read_jsonl(raw / "starts.jsonl")
    terminals = _read_jsonl(raw / "terminals.jsonl")
    ticks = _read_jsonl(raw / "ticks.jsonl")
    if len(starts) != len(cells) or len(terminals) != len(cells):
        raise IntegrityError("episode inventory mismatch")
    ticks_by = {cell["episode_id"]: [] for cell in cells}
    for row in ticks:
        if row.get("episode_id") not in ticks_by:
            raise IntegrityError("unknown tick episode")
        ticks_by[str(row["episode_id"])].append(row)
    scores = []
    for cell, start, terminal in zip(cells, starts, terminals, strict=True):
        if start.get("cell") != cell or terminal.get("episode_id") != cell["episode_id"]:
            raise IntegrityError("ordered episode identity mismatch")
        try:
            scores.append(score_episode(start, ticks_by[cell["episode_id"]], terminal, CONFIG))
        except ReplayError as exc:
            raise IntegrityError(str(exc)) from exc
    return cells, scores


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _aggregate(rows: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(tuple(row[key] for key in keys), []).append(row)
    output = []
    for identity, selected in sorted(groups.items()):
        output.append({**dict(zip(keys, identity, strict=True)), "n": len(selected),
                       **{metric: round(_mean([float(row[metric]) for row in selected]), 8) for metric in METRICS}})
    return output


def preregistered_effect_ids() -> set[str]:
    return set(CONFIG["effect_ids"])


def _effect_definitions() -> list[dict[str, str]]:
    definitions = []
    for policy, prompt in itertools.product(CONFIG["trigger_policies"], CONFIG["prompt_envelopes"]):
        definitions.append({"axis": "storage", "candidate_field": "storage_variant", "candidate": "LIVE_EPISODIC", "comparator": "LIVE_BELIEF",
                            "hold_field_1": "trigger_policy", "hold_value_1": policy, "hold_field_2": "prompt_envelope", "hold_value_2": prompt,
                            "effect_id": f"STORAGE_LIVE_EPISODIC_MINUS_LIVE_BELIEF__{policy}__{prompt}"})
    for storage, policy, prompt in itertools.product(CONFIG["storage_variants"], CONFIG["trigger_policies"][1:], CONFIG["prompt_envelopes"]):
        definitions.append({"axis": "policy", "candidate_field": "trigger_policy", "candidate": policy, "comparator": "PERIODIC_ONLY",
                            "hold_field_1": "storage_variant", "hold_value_1": storage, "hold_field_2": "prompt_envelope", "hold_value_2": prompt,
                            "effect_id": f"POLICY_{policy}_MINUS_PERIODIC_ONLY__{storage}__{prompt}"})
    for storage, policy in itertools.product(CONFIG["storage_variants"], CONFIG["trigger_policies"]):
        definitions.append({"axis": "prompt", "candidate_field": "prompt_envelope", "candidate": "VERBOSE_TYPED", "comparator": "COMPACT_TYPED",
                            "hold_field_1": "storage_variant", "hold_value_1": storage, "hold_field_2": "trigger_policy", "hold_value_2": policy,
                            "effect_id": f"PROMPT_VERBOSE_TYPED_MINUS_COMPACT_TYPED__{storage}__{policy}"})
    if {row["effect_id"] for row in definitions} != preregistered_effect_ids():
        raise IntegrityError("effect preregistration mismatch")
    return definitions


def _paired_seed_values(rows: Sequence[Mapping[str, Any]], definition: Mapping[str, str], metric: str, *, stratum: Mapping[str, Any] | None = None) -> tuple[list[int], list[float]]:
    subset = [row for row in rows if row[definition["hold_field_1"]] == definition["hold_value_1"] and row[definition["hold_field_2"]] == definition["hold_value_2"]]
    if stratum:
        subset = [row for row in subset if all(row[key] == value for key, value in stratum.items())]
    seeds, values = [], []
    for seed in sorted({int(row["seed"]) for row in subset}):
        candidate = [float(row[metric]) for row in subset if int(row["seed"]) == seed and row[definition["candidate_field"]] == definition["candidate"]]
        comparator = [float(row[metric]) for row in subset if int(row["seed"]) == seed and row[definition["candidate_field"]] == definition["comparator"]]
        if candidate and len(candidate) == len(comparator):
            seeds.append(seed)
            values.append(_mean(candidate) - _mean(comparator))
    return seeds, values


def _bootstrap(values: Sequence[float], *, draws: int, seed: int) -> tuple[float, float, str]:
    rng = random.Random(seed)
    indices = [[rng.randrange(len(values)) for _ in values] for _ in range(draws)]
    estimates = sorted(_mean([values[index] for index in draw]) for draw in indices)
    return estimates[int(draws * 0.025)], estimates[min(draws - 1, int(draws * 0.975))], sha(canonical(indices))


def _contrasts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    draws = int(CONFIG["bootstrap_draws"])
    required_n = len(SEEDS) if len(rows) == len(frozen_matrix()) else len(CONFIG["calibration_seeds"])
    required_draws = int(CONFIG["contrast_gate"]["bootstrap_draws"]) if required_n == 12 else draws
    for definition_index, definition in enumerate(_effect_definitions()):
        for metric_index, metric in enumerate(CONFIG["contrast_metrics"]):
            seeds, values = _paired_seed_values(rows, definition, metric)
            if not values:
                continue
            low, high, draw_hash = _bootstrap(values, draws=draws, seed=int(CONFIG["bootstrap_seed"]) + definition_index * 31 + metric_index)
            gate = "PASS" if len(seeds) == required_n and draws == required_draws else "FAIL"
            output.append({"axis": definition["axis"], "bootstrap_draws": draws, "candidate": definition["candidate"],
                           "ci_high": round(high, 8), "ci_low": round(low, 8), "comparator": definition["comparator"],
                           "draw_indices_sha256": draw_hash, "effect_id": definition["effect_id"], "effective_seed_n": len(seeds),
                           "estimate": round(_mean(values), 8), "gate": gate, "metric": metric, "seed_cluster_sha256": sha(canonical(seeds))})
    return output


def _heterogeneity(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for definition in _effect_definitions():
        for family in CONFIG["disturbance_families"]:
            for metric in CONFIG["contrast_metrics"]:
                seeds, values = _paired_seed_values(rows, definition, metric, stratum={"disturbance_family": family})
                if values:
                    output.append({"disturbance_family": family, "effect_id": definition["effect_id"], "effective_seed_n": len(seeds),
                                   "estimate": round(_mean(values), 8), "metric": metric})
    return output


def _graph_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return _aggregate(rows, ("storage_variant", "trigger_policy", "quality_id"))


COLORS = {"PERIODIC_ONLY": "#0072B2", "FAILURE_THRESHOLD": "#D55E00", "EVENT_DRIVEN": "#009E73", "HYBRID": "#CC79A7"}


def _svg(graph: Sequence[Mapping[str, Any]]) -> bytes:
    width, height = 1000, 540
    qids = [row["id"] for row in CONFIG["quality_profiles"] if any(item["quality_id"] == row["id"] for item in graph)]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#ffffff"/><text x="500" y="22" text-anchor="middle" font-family="sans-serif" font-size="16">Exp11 V2 completion; stores separated</text>']
    for panel, storage in enumerate(CONFIG["storage_variants"]):
        left, top, plot_w, plot_h = 65 + panel * 500, 55, 415, 390
        parts.append(f'<text x="{left + plot_w / 2}" y="42" text-anchor="middle" font-family="sans-serif" font-size="13">{storage}</text>')
        parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#222"/><line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#222"/>')
        for policy_index, policy in enumerate(CONFIG["trigger_policies"]):
            selected = [row for row in graph if row["storage_variant"] == storage and row["trigger_policy"] == policy]
            values = [next(float(row["completion"]) for row in selected if row["quality_id"] == qid) for qid in qids]
            points = " ".join(f"{left + index * plot_w / max(1, len(qids)-1):.2f},{top + (1-value)*plot_h:.2f}" for index, value in enumerate(values))
            parts.append(f'<polyline data-storage="{storage}" data-policy="{policy}" points="{points}" fill="none" stroke="{COLORS[policy]}" stroke-width="2"/>')
            parts.append(f'<text x="{left + 8}" y="{top + 16 + 16*policy_index}" font-family="sans-serif" font-size="10" fill="{COLORS[policy]}">{policy}</text>')
    parts.append("</svg>")
    return ("".join(parts) + "\n").encode("ascii")


def _png(graph: Sequence[Mapping[str, Any]]) -> bytes:
    width, height = 1000, 540
    pixels = bytearray([255] * width * height * 3)
    rgb = {"PERIODIC_ONLY": (0, 114, 178), "FAILURE_THRESHOLD": (213, 94, 0), "EVENT_DRIVEN": (0, 158, 115), "HYBRID": (204, 121, 167)}
    qids = [row["id"] for row in CONFIG["quality_profiles"] if any(item["quality_id"] == row["id"] for item in graph)]

    def mark(x: int, y: int, color: tuple[int, int, int]) -> None:
        for yy in range(max(0, y - 2), min(height, y + 3)):
            for xx in range(max(0, x - 2), min(width, x + 3)):
                pixels[(yy * width + xx) * 3:(yy * width + xx) * 3 + 3] = bytes(color)

    for panel, storage in enumerate(CONFIG["storage_variants"]):
        left = 65 + panel * 500
        for policy in CONFIG["trigger_policies"]:
            for index, qid in enumerate(qids):
                value = next(float(row["completion"]) for row in graph if row["storage_variant"] == storage and row["trigger_policy"] == policy and row["quality_id"] == qid)
                mark(left + round(index * 415 / max(1, len(qids)-1)), 55 + round((1-value) * 390), rgb[policy])
    raw = b"".join(b"\x00" + bytes(pixels[y*width*3:(y+1)*width*3]) for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _derived_payloads(raw: Path) -> dict[str, bytes]:
    cells, scores = _validate_raw(raw, allow_fixture=True)
    episodes = [{**cell, **score} for cell, score in zip(cells, scores, strict=True)]
    episode_fields = tuple(cells[0]) + tuple(key for key in scores[0] if key not in cells[0])
    cell_rows = _aggregate(episodes, ("storage_variant", "trigger_policy", "quality_id", "disturbance_family", "severity", "horizon", "prompt_envelope"))
    dose_rows = _aggregate(episodes, ("storage_variant", "trigger_policy", "quality_id", "prompt_envelope"))
    graph_rows = _graph_rows(episodes)
    contrasts = _contrasts(episodes)
    heterogeneity = _heterogeneity(episodes)
    slopes = []
    for storage, policy, prompt in itertools.product(CONFIG["storage_variants"], CONFIG["trigger_policies"], CONFIG["prompt_envelopes"]):
        selected = [row for row in dose_rows if row["storage_variant"] == storage and row["trigger_policy"] == policy and row["prompt_envelope"] == prompt]
        if not selected:
            continue
        ordered = [row["id"] for row in CONFIG["quality_profiles"] if any(item["quality_id"] == row["id"] for item in selected)]
        values = [next(float(row["completion"]) for row in selected if row["quality_id"] == qid) for qid in ordered]
        drops = [values[index + 1] - values[index] for index in range(len(values) - 1)]
        cliff = min(range(len(drops)), key=lambda index: drops[index])
        slopes.append({"clean_to_hostile_slope": round((values[-1] - values[0]) / max(1, len(values)-1), 8),
                       "cliff_after_quality": ordered[cliff], "largest_adjacent_drop": round(drops[cliff], 8),
                       "prompt_envelope": prompt, "storage_variant": storage, "trigger_policy": policy})
    working = max(episodes, key=lambda row: (row["completion"], row["progress"], -row["cost_proxy"]))
    nonworking = min(episodes, key=lambda row: (row["completion"], row["progress"], -row["retries"]))
    graph_bytes = csv_data(graph_rows, tuple(graph_rows[0]))
    metadata = {"graph_table_sha256": sha(graph_bytes), "renderer": "STDLIB_ZLIB_TWO_PANEL_V2", "schema_version": 2,
                "storage_pooling": "NONE", "transformations": ["ARITHMETIC_MEAN_OVER_DECLARED_NUISANCE_AXES"],
                "nuisance_axes": ["disturbance_family", "severity", "horizon", "prompt_envelope", "seed"]}
    gate_counts = {"FAIL": sum(row["gate"] == "FAIL" for row in contrasts), "PASS": sum(row["gate"] == "PASS" for row in contrasts)}
    report = ("# Experiment 11 V2 Trigger Robustness Dose Response\n\n"
              f"Scope: `{CLAIM_SCOPE}`; deterministic typed oracle, not VLA evidence.\n\n"
              f"Validated episodes: {len(episodes):,}; exact ticks: {sum(int(row['tick_count']) for row in scores):,}; paired seed clusters: {len({row['seed'] for row in episodes})}.\n\n"
              f"Preregistered paired effects: {len(preregistered_effect_ids())}; contrast rows: {len(contrasts)}; gates PASS={gate_counts['PASS']}, FAIL={gate_counts['FAIL']}.\n\n"
              "Graphs retain separate LIVE_BELIEF and LIVE_EPISODIC series. Derived tables, statistics, SVG, and PNG are recomputed from authenticated raw ledgers.\n")
    return {
        "RESULT.md": report.encode("ascii"), "cell-summary.csv": csv_data(cell_rows, tuple(cell_rows[0])),
        "dose-response.csv": csv_data(dose_rows, tuple(dose_rows[0])), "dose-response.png": _png(graph_rows),
        "dose-response.svg": _svg(graph_rows), "episodes.csv": csv_data(episodes, episode_fields),
        "examples.json": canonical({"nonworking": nonworking, "working": working}),
        "graph-table.csv": graph_bytes, "heterogeneity.csv": csv_data(heterogeneity, tuple(heterogeneity[0])),
        "paired-contrasts.csv": csv_data(contrasts, tuple(contrasts[0])), "plot-metadata.json": canonical(metadata),
        "slopes-cliffs.csv": csv_data(slopes, tuple(slopes[0])),
    }


def _validate_derived(raw: Path, derived: Path) -> None:
    _validate_manifest(derived, "manifest.json")
    expected = _derived_payloads(raw)
    actual_names = {row["path"] for row in inventory(derived, exclude=("manifest.json",))}
    if actual_names != set(expected):
        raise IntegrityError("derived inventory mismatch")
    for name, payload in expected.items():
        if (derived / name).read_bytes() != payload:
            raise IntegrityError(f"derived recomputed mismatch: {name}")


def validate(root: Path, *, allow_fixture: bool = False) -> tuple[int, int]:
    _validate_manifest(root, "manifest.json")
    if {row["path"] for row in inventory(root, exclude=("manifest.json",)) if "/" not in str(row["path"])}:
        raise IntegrityError("unlisted root sibling")
    load_retirement_registry()
    cells, scores = _validate_raw(root / "raw", allow_fixture=allow_fixture)
    _validate_derived(root / "raw", root / "derived")
    return len(cells), sum(int(row["tick_count"]) for row in scores)


def publish(root: Path, cells: Sequence[Mapping[str, Any]], *, implementation_git_sha: str, fixture: bool) -> None:
    if root.exists():
        raise IntegrityError("create-only evidence root exists")
    if implementation_git_sha != _head():
        raise IntegrityError("implementation commit must equal current HEAD")
    if not fixture:
        for member in source_closure():
            if sha(_git_blob(implementation_git_sha, str(member["path"]))) != member["sha256"]:
                raise IntegrityError("implementation source is not committed")
    raw = root / "raw"
    derived = root / "derived"
    raw.mkdir(parents=True)
    starts, ticks, terminals = [], [], []
    for cell in cells:
        start, episode_ticks, terminal = run_episode(cell)
        starts.append(start)
        ticks.extend(episode_ticks)
        terminals.append(terminal)
    (raw / "cells.jsonl").write_bytes(jsonl(cells))
    (raw / "config.json").write_bytes(CONFIG_PATH.read_bytes())
    (raw / "freeze.json").write_bytes(canonical(freeze_receipt(cells, implementation_git_sha, fixture=fixture)))
    (raw / "seeds.json").write_bytes(SEEDS_PATH.read_bytes())
    (raw / "starts.jsonl").write_bytes(jsonl(starts))
    (raw / "terminals.jsonl").write_bytes(jsonl(terminals))
    (raw / "ticks.jsonl").write_bytes(jsonl(ticks))
    _write_manifest(raw)
    derived.mkdir()
    for name, payload in _derived_payloads(raw).items():
        (derived / name).write_bytes(payload)
    _write_manifest(derived)
    _write_manifest(root)
    validate(root, allow_fixture=fixture)


def reconstruct(source: Path, target: Path, *, expected_root_manifest_sha256: str, allow_fixture: bool = False) -> None:
    manifest = source / "manifest.json"
    if not manifest.is_file() or manifest.is_symlink() or sha(manifest.read_bytes()) != expected_root_manifest_sha256:
        raise IntegrityError("root manifest receipt mismatch")
    validate(source, allow_fixture=allow_fixture)
    freeze = json.loads((source / "raw/freeze.json").read_text(encoding="ascii"))
    cells = fixture_matrix() if freeze["fixture"] else frozen_matrix()
    publish(target, cells, implementation_git_sha=str(freeze["implementation_git_sha"]), fixture=bool(freeze["fixture"]))
    if inventory(source) != inventory(target):
        raise IntegrityError("full reconstruction mismatch")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    full = sub.add_parser("full")
    full.add_argument("root", type=Path)
    full.add_argument("--implementation-git-sha", required=True)
    check = sub.add_parser("validate")
    check.add_argument("root", type=Path)
    check.add_argument("--allow-fixture", action="store_true")
    rebuild = sub.add_parser("reconstruct")
    rebuild.add_argument("source", type=Path)
    rebuild.add_argument("target", type=Path)
    rebuild.add_argument("--expected-root-manifest-sha256", required=True)
    rebuild.add_argument("--allow-fixture", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "full":
        publish(args.root, frozen_matrix(), implementation_git_sha=args.implementation_git_sha, fixture=False)
    elif args.command == "validate":
        validate(args.root, allow_fixture=args.allow_fixture)
    else:
        reconstruct(args.source, args.target, expected_root_manifest_sha256=args.expected_root_manifest_sha256, allow_fixture=args.allow_fixture)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
