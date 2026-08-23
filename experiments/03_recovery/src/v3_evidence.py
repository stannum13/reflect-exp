"""Create-only V3 qualification evidence, diagnostics, and full raw replay."""

from __future__ import annotations

import ast
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Iterable, Mapping, Sequence

import numpy as np

from .v3_contracts import (
    Architecture,
    CALIBRATION_SEEDS,
    DecisionLevel,
    EPISODE_TICKS,
    PRIMARY_CONTROLLER_ID,
    REOBSERVE_TICKS,
    SCENARIO_IDS,
    SENSITIVITY_CONTROLLER_ID,
    TIMESTEP_S,
    canonical_bytes,
    sha256_bytes,
)
from .v3_runtime import V3EpisodeRaw, V3EpisodeSpec, precheck, run_episode
from .v3_scorer import ScoreResult, positive_control_audit, score_episode


_SEED_MODULES = (
    "experiments.03_recovery.run_v3_qualification",
    "experiments.03_recovery.src.v3_evidence",
    "experiments.01_policy_control.src.arm",
    "experiments.01_policy_control.src.contracts",
    "experiments.01_policy_control.src.kinematics",
    "experiments.01_policy_control.src.representations",
)
_EXPLICIT_INPUTS = ("experiments/01_policy_control/configs/base.yaml",)
_BANNED_DECISION_TOKENS = (b"scenario", b"cause", b"expected_level", b"intended_level", b"domain")


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def qualification_specs() -> tuple[V3EpisodeSpec, ...]:
    specs = [V3EpisodeSpec(Architecture.R3, scenario, 20261891, PRIMARY_CONTROLLER_ID) for scenario in SCENARIO_IDS]
    specs.extend(V3EpisodeSpec(architecture, "semantic-object-unavailable", 20261893, PRIMARY_CONTROLLER_ID) for architecture in Architecture)
    specs.extend(V3EpisodeSpec(architecture, "control-impulse", 20261892, PRIMARY_CONTROLLER_ID) for architecture in Architecture)
    specs.extend((
        V3EpisodeSpec(Architecture.R3, "anchor-nominal", 20261894, PRIMARY_CONTROLLER_ID),
        V3EpisodeSpec(Architecture.R3, "anchor-nominal", 20261894, SENSITIVITY_CONTROLLER_ID),
    ))
    result = tuple(sorted(specs, key=lambda item: item.episode_id))
    if len(result) != 18 or len({item.episode_id for item in result}) != 18:
        raise RuntimeError("V3 qualification matrix identity error")
    return result


def _module_file(module: str) -> Path | None:
    base = _root().joinpath(*module.split("."))
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None


def _module_name(path: Path) -> str:
    relative = path.relative_to(_root())
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(parts)


def _local_imports(path: Path) -> set[str]:
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    result: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                parent = base[: len(base) - (node.level - 1)]
                prefix = ".".join(parent)
                names = [prefix + ("." + node.module if node.module else "")]
            elif node.module:
                names = [node.module]
        for name in names:
            if name.startswith("experiments.") or name == "experiments" or name.startswith("reflect.") or name == "reflect":
                if _module_file(name) is not None:
                    result.add(name)
    return result


def _package_initializers(path: Path) -> set[Path]:
    result: set[Path] = set()
    relative = path.relative_to(_root())
    parent = relative.parent
    while parent != Path("."):
        candidate = _root() / parent / "__init__.py"
        if candidate.is_file():
            result.add(candidate)
        parent = parent.parent
    return result


def source_closure() -> list[dict[str, object]]:
    pending = list(_SEED_MODULES)
    visited: set[str] = set()
    files: set[Path] = set()
    while pending:
        module = pending.pop()
        if module in visited:
            continue
        visited.add(module)
        path = _module_file(module)
        if path is None:
            raise RuntimeError(f"local source module missing: {module}")
        files.add(path)
        files.update(_package_initializers(path))
        pending.extend(sorted(_local_imports(path) - visited))
    files.update(_root() / name for name in _EXPLICIT_INPUTS)
    rows = []
    for path in sorted(files):
        payload = path.read_bytes()
        rows.append({"path": path.relative_to(_root()).as_posix(), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    return rows


def verify_source_closure(recorded: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    actual = source_closure()
    if [dict(item) for item in recorded] != actual:
        raise RuntimeError("V3 qualification import closure drift")
    return actual


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _jsonl(rows: Iterable[object]) -> bytes:
    return b"".join(canonical_bytes(item) for item in rows)


def _npz(trace: Mapping[str, np.ndarray]) -> bytes:
    stream = io.BytesIO()
    np.savez_compressed(stream, **{name: trace[name] for name in sorted(trace)})
    return stream.getvalue()


def _score_wire(score: ScoreResult) -> dict[str, object]:
    return {
        "terminal": score.terminal,
        "mission_postcondition": score.mission_postcondition,
        "dwell_satisfied": score.dwell_satisfied,
        "violation_counts": dict(score.violation_counts),
    }


def episode_payloads(raw: V3EpisodeRaw) -> dict[str, bytes]:
    score = score_episode(raw)
    return {
        "spec.json": canonical_bytes(raw.spec),
        "realization.json": canonical_bytes(raw.realization),
        "precheck.json": canonical_bytes(raw.precheck),
        "parameter-use.json": canonical_bytes(raw.parameter_use_receipt),
        "hidden-cause.json": canonical_bytes(raw.hidden_cause),
        "controller-binding.json": canonical_bytes(raw.controller_binding),
        "world-ledger.jsonl": _jsonl(raw.world_ledger),
        "semantic-events.jsonl": _jsonl(raw.semantic_events),
        "memory-ledger.jsonl": _jsonl(raw.memory_ledger),
        "observations.jsonl": _jsonl(raw.observations),
        "decisions.jsonl": _jsonl(raw.decisions),
        "budget-resets.jsonl": _jsonl(raw.budget_resets),
        "execution-receipts.jsonl": _jsonl(raw.execution_receipts),
        "commands.jsonl": _jsonl(raw.commands),
        "trajectories.bin": raw.trajectory_bytes,
        "action-envelopes.jsonl": _jsonl(raw.action_envelopes),
        "trace.npz": _npz(raw.trace),
        "scorer-rows.jsonl": _jsonl(score.rows),
        "scorer.json": canonical_bytes(_score_wire(score)),
        "terminal.json": canonical_bytes({"terminal": score.terminal, "mission_postcondition": score.mission_postcondition, "dwell_satisfied": score.dwell_satisfied}),
    }


def _inventory(payloads: Mapping[str, bytes]) -> list[dict[str, object]]:
    return [{"path": name, "bytes": len(payload), "sha256": sha256_bytes(payload)} for name, payload in sorted(payloads.items())]


def _write_episode(root: Path, raw: V3EpisodeRaw) -> dict[str, object]:
    destination = root / "episodes" / raw.spec.episode_id
    if destination.exists():
        raise FileExistsError(destination)
    payloads = episode_payloads(raw)
    for name, payload in sorted(payloads.items()):
        _write(destination / name, payload)
    manifest = {
        "schema_version": 1,
        "episode_id": raw.spec.episode_id,
        "seed": raw.spec.seed,
        "injection_tick": raw.realization.injection_tick,
        "files": _inventory(payloads),
    }
    manifest_payload = canonical_bytes(manifest)
    _write(destination / "manifest.json", manifest_payload)
    return {
        "episode_id": raw.spec.episode_id,
        "seed": raw.spec.seed,
        "scenario_id": raw.spec.scenario_id,
        "architecture": raw.spec.architecture.value,
        "controller_id": raw.spec.controller_id,
        "manifest_sha256": sha256_bytes(manifest_payload),
    }


def _validate_episode(destination: Path) -> dict[str, object]:
    manifest = json.loads((destination / "manifest.json").read_text(encoding="ascii"))
    actual = []
    for path in sorted(destination.iterdir()):
        if path.name == "manifest.json":
            continue
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("qualification episode member is not a regular file")
        payload = path.read_bytes()
        actual.append({"path": path.name, "bytes": len(payload), "sha256": sha256_bytes(payload)})
    if actual != manifest["files"] or manifest["episode_id"] != destination.name:
        raise RuntimeError("qualification episode inventory mismatch")
    return manifest


def _not_run_control() -> dict[str, object]:
    spec = V3EpisodeSpec(Architecture.R3, "motion-path-infeasible", 20261894, PRIMARY_CONTROLLER_ID)
    receipt = precheck(spec, force_not_run=True)
    return {
        "control_id": "architecture-independent-unreachable-positive-control",
        "episode_id": spec.episode_id,
        "disposition": receipt.disposition,
        "reason": receipt.reason,
        "architecture_independent": receipt.architecture_independent,
        "geometry_sha256": receipt.geometry_sha256,
    }


def _build_raw(output: Path, specs: Sequence[V3EpisodeSpec]) -> tuple[dict[str, V3EpisodeRaw], dict[str, ScoreResult], dict[str, dict[str, object]], dict[str, object]]:
    raw_root = output / "raw"
    if raw_root.exists():
        raise FileExistsError(raw_root)
    (raw_root / "episodes").mkdir(parents=True)
    raws: dict[str, V3EpisodeRaw] = {}
    scores: dict[str, ScoreResult] = {}
    episode_rows = []
    for spec in sorted(specs, key=lambda item: item.episode_id):
        raw = run_episode(spec)
        score = score_episode(raw)
        raws[spec.episode_id] = raw
        scores[spec.episode_id] = score
        episode_rows.append(_write_episode(raw_root, raw))
    control_source = next(
        raw for raw in raws.values()
        if raw.spec.architecture is Architecture.R3 and raw.spec.scenario_id == "semantic-object-unavailable" and raw.spec.seed == 20261891
    )
    controls = positive_control_audit(control_source)
    not_run = _not_run_control()
    controls_payload = canonical_bytes(controls)
    not_run_payload = canonical_bytes(not_run)
    _write(raw_root / "positive-controls.json", controls_payload)
    _write(raw_root / "not-run-positive-control.json", not_run_payload)
    manifest = {
        "schema_version": 1,
        "episode_count": len(episode_rows),
        "calibration_seeds": CALIBRATION_SEEDS,
        "episodes": episode_rows,
        "positive_controls_sha256": sha256_bytes(controls_payload),
        "not_run_positive_control": not_run,
        "not_run_positive_control_sha256": sha256_bytes(not_run_payload),
    }
    _write(raw_root / "manifest.json", canonical_bytes(manifest))
    return raws, scores, controls, not_run


def _csv(rows: Sequence[Mapping[str, object]], columns: Sequence[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(columns), lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column) for column in columns})
    return stream.getvalue().encode("ascii")


def _diagnostic_svg(title: str, rows: Sequence[Mapping[str, object]], columns: Sequence[str]) -> bytes:
    width = 1100
    row_height = 18
    height = 58 + row_height * (len(rows) + 1)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        f'<text x="12" y="22" font-family="monospace" font-size="14">{html.escape(title)}</text>',
    ]
    x_positions = [12 + index * (width - 24) / max(1, len(columns)) for index in range(len(columns))]
    for x, column in zip(x_positions, columns, strict=True):
        parts.append(f'<text x="{x:.1f}" y="45" font-family="monospace" font-size="10">{html.escape(column)}</text>')
    for row_index, row in enumerate(rows):
        y = 45 + row_height * (row_index + 1)
        for x, column in zip(x_positions, columns, strict=True):
            value = str(row.get(column, ""))
            if len(value) > 22:
                value = value[:19] + "..."
            parts.append(f'<text x="{x:.1f}" y="{y}" font-family="monospace" font-size="9">{html.escape(value)}</text>')
    parts.append("</svg>\n")
    return "".join(parts).encode("ascii")


def _sequence(raw: V3EpisodeRaw) -> str:
    return ">".join(item.level.value for item in raw.decisions if item.level is not DecisionLevel.NONE) or "NONE"


def _gate_rows(
    raws: Mapping[str, V3EpisodeRaw],
    scores: Mapping[str, ScoreResult],
    controls: Mapping[str, Mapping[str, object]],
    not_run: Mapping[str, object],
    replay: Mapping[str, object],
) -> list[dict[str, object]]:
    def select(architecture: Architecture, scenario: str, seed: int, controller: str = PRIMARY_CONTROLLER_ID) -> V3EpisodeRaw:
        return next(item for item in raws.values() if item.spec.architecture is architecture and item.spec.scenario_id == scenario and item.spec.seed == seed and item.spec.controller_id == controller)

    reached = all(item.injection_rows == (item.realization.injection_tick,) and int(item.trace["tick"][item.realization.injection_tick]) == item.realization.injection_tick for item in raws.values())
    anchor = select(Architecture.R3, "anchor-nominal", 20261891)
    disturbances = [select(Architecture.R3, scenario, 20261891) for scenario in SCENARIO_IDS[2:]]
    disturbance_changed = all(item.trace["q"].tobytes() != anchor.trace["q"].tobytes() and item.parameter_use_receipt["injection_tick"] == item.realization.injection_tick for item in disturbances)

    semantic_expected = {
        Architecture.R0: "CONTROL>CONTROL>SAFE_ABORT",
        Architecture.R1: "SEMANTIC",
        Architecture.R2: "MOTION>MOTION>SEMANTIC",
        Architecture.R3: "SEMANTIC",
    }
    control_expected = {
        Architecture.R0: "CONTROL",
        Architecture.R1: "SEMANTIC",
        Architecture.R2: "MOTION",
        Architecture.R3: "CONTROL",
    }
    policies_distinct = all(_sequence(select(arch, "semantic-object-unavailable", 20261893)) == expected for arch, expected in semantic_expected.items()) and all(_sequence(select(arch, "control-impulse", 20261892)) == expected for arch, expected in control_expected.items())

    p6 = select(Architecture.R3, "anchor-nominal", 20261894, PRIMARY_CONTROLLER_ID)
    p4 = select(Architecture.R3, "anchor-nominal", 20261894, SENSITIVITY_CONTROLLER_ID)
    controllers_distinct = (
        p6.controller_binding["call_path"] != p4.controller_binding["call_path"]
        and p6.trajectory_bytes != p4.trajectory_bytes
        and p6.trace["q_ref"].tobytes() != p4.trace["q_ref"].tobytes()
        and p6.trace["actuator_cmd_nm"].tobytes() != p4.trace["actuator_cmd_nm"].tobytes()
    )

    time_budget = True
    resets_valid = True
    for raw in raws.values():
        intervention_ticks = [item.observed_tick for item in raw.decisions if item.level not in {DecisionLevel.NONE, DecisionLevel.SAFE_ABORT}]
        time_budget = time_budget and all(later - earlier >= REOBSERVE_TICKS for earlier, later in zip(intervention_ticks, intervention_ticks[1:]))
        resets_valid = resets_valid and all(
            item["old_content_sha256"] != item["new_content_sha256"]
            and item["successful_execution_receipt_sha256"] == item["new_content_sha256"]
            for item in raw.budget_resets
        )
    boundaries = all(not any(token in canonical_bytes(item).lower() for token in _BANNED_DECISION_TOKENS) for raw in raws.values() for item in (*raw.observations, *raw.decisions))
    scorer_closed = all(score_episode(raw) == scores[episode_id] for episode_id, raw in raws.items()) and b"v3_runtime" not in (_root() / "experiments/03_recovery/src/v3_scorer.py").read_bytes()
    positives = set(controls) == {"unsafe", "forbidden", "collision", "stale", "invalid_action", "wrong_object", "missed_dwell", "loop", "reset"} and all(item["terminal"] == "FAILURE" and int(item["detected_count"]) > 0 for item in controls.values())
    return [
        {"gate": 1, "passed": reached, "evidence": "sampled injection tick equals retained row"},
        {"gate": 2, "passed": disturbance_changed, "evidence": "six disturbances differ from matched physical anchor"},
        {"gate": 3, "passed": policies_distinct, "evidence": "observable R0/R1/R2/R3 sequences retained"},
        {"gate": 4, "passed": controllers_distinct, "evidence": "real P6/P4 path and bytes differ"},
        {"gate": 5, "passed": time_budget and resets_valid, "evidence": "25-tick reobserve and guarded content resets"},
        {"gate": 6, "passed": boundaries, "evidence": "decision/observable cause boundary closed"},
        {"gate": 7, "passed": scorer_closed, "evidence": "independent scorer reconstructs immutable raw"},
        {"gate": 8, "passed": positives, "evidence": "nine scorer terminal positive controls"},
        {"gate": 9, "passed": bool(replay["raw_matched"] and replay["derived_matched"]), "evidence": "raw replay and derived reconstruction byte exact"},
        {"gate": 10, "passed": not_run["disposition"] == "NOT_RUN" and bool(not_run["architecture_independent"]), "evidence": "architecture-independent NOT_RUN control"},
    ]


def _derive(
    output: Path,
    raws: Mapping[str, V3EpisodeRaw],
    scores: Mapping[str, ScoreResult],
    controls: Mapping[str, Mapping[str, object]],
    not_run: Mapping[str, object],
    replay: Mapping[str, object],
) -> dict[str, object]:
    derived = output / "derived"
    if derived.exists():
        raise FileExistsError(derived)
    gates = _gate_rows(raws, scores, controls, not_run, replay)
    passed = sum(bool(item["passed"]) for item in gates)
    status = "READY_FOR_FRESH_READ_ONLY_REVIEW" if passed == 10 and len(raws) == 18 else "INVALID_OR_INCOMPLETE_QUALIFICATION"
    summary = {
        "status": status,
        "self_authorizes_outcomes": False,
        "episode_count": len(raws),
        "terminal_counts": {
            "SUCCESS": sum(item.terminal == "SUCCESS" for item in scores.values()),
            "FAILURE": sum(item.terminal == "FAILURE" for item in scores.values()),
        },
        "hard_gates_passed": passed,
        "hard_gates_total": 10,
        "calibration_seeds": CALIBRATION_SEEDS,
    }
    injection_rows = [{
        "episode_id": raw.spec.episode_id,
        "scenario_id": raw.spec.scenario_id,
        "seed": raw.spec.seed,
        "sampled_tick": raw.realization.injection_tick,
        "retained_tick": raw.injection_rows[0],
        "parameter_sha256": raw.realization.parameter_sha256,
        "physical_trace_sha256": sha256_bytes(raw.trace["q"].tobytes()),
    } for raw in sorted(raws.values(), key=lambda item: item.spec.episode_id)]
    controller_rows = [{
        "controller_id": raw.spec.controller_id,
        "call_path": raw.controller_binding["call_path"],
        "trajectory_sha256": sha256_bytes(raw.trajectory_bytes),
        "q_ref_sha256": sha256_bytes(raw.trace["q_ref"].tobytes()),
        "torque_sha256": sha256_bytes(raw.trace["actuator_cmd_nm"].tobytes()),
    } for raw in sorted(raws.values(), key=lambda item: item.spec.controller_id) if raw.spec.scenario_id == "anchor-nominal" and raw.spec.seed == 20261894]
    budget_rows = [{
        "episode_id": raw.spec.episode_id,
        "tick": decision.observed_tick,
        "level": decision.level.value,
        "control_remaining": decision.budget_after.control_remaining,
        "motion_remaining": decision.budget_after.motion_remaining,
        "semantic_remaining": decision.budget_after.semantic_remaining,
    } for raw in sorted(raws.values(), key=lambda item: item.spec.episode_id) for decision in raw.decisions]
    control_rows = [{"control": name, "terminal": item["terminal"], "detected_count": item["detected_count"]} for name, item in sorted(controls.items())]
    gate_csv_rows = [{"gate": item["gate"], "passed": item["passed"], "evidence": item["evidence"]} for item in gates]
    working = next(episode_id for episode_id, score in sorted(scores.items()) if score.terminal == "SUCCESS" and "semantic-object-unavailable" in episode_id and "R3" in episode_id)
    nonworking = next(episode_id for episode_id, score in sorted(scores.items()) if score.terminal == "FAILURE")
    examples = {"working": working, "nonworking": nonworking, "not_run": not_run["episode_id"]}
    payloads: dict[str, bytes] = {
        "qualification-summary.json": canonical_bytes(summary),
        "hard-gates.csv": _csv(gate_csv_rows, ("gate", "passed", "evidence")),
        "replay.json": canonical_bytes(replay),
        "examples.json": canonical_bytes(examples),
        "injection-timing.csv": _csv(injection_rows, ("episode_id", "scenario_id", "seed", "sampled_tick", "retained_tick", "parameter_sha256", "physical_trace_sha256")),
        "injection-timing.svg": _diagnostic_svg("Sampled and retained injection ticks", injection_rows, ("scenario_id", "seed", "sampled_tick", "retained_tick", "physical_trace_sha256")),
        "controller-paths.csv": _csv(controller_rows, ("controller_id", "call_path", "trajectory_sha256", "q_ref_sha256", "torque_sha256")),
        "controller-paths.svg": _diagnostic_svg("Existing P6 and repaired P4 byte identities", controller_rows, ("controller_id", "call_path", "trajectory_sha256", "q_ref_sha256", "torque_sha256")),
        "budget-sequences.csv": _csv(budget_rows, ("episode_id", "tick", "level", "control_remaining", "motion_remaining", "semantic_remaining")),
        "budget-sequences.svg": _diagnostic_svg("Time-advanced decision and budget sequences", budget_rows, ("episode_id", "tick", "level", "control_remaining", "motion_remaining", "semantic_remaining")),
        "scorer-controls.csv": _csv(control_rows, ("control", "terminal", "detected_count")),
        "scorer-controls.svg": _diagnostic_svg("Independent scorer terminal positive controls", control_rows, ("control", "terminal", "detected_count")),
        "qualification-hashes.json": canonical_bytes({
            "freeze_sha256": sha256_bytes((output / "qualification-freeze.json").read_bytes()),
            "raw_manifest_sha256": sha256_bytes((output / "raw/manifest.json").read_bytes()),
            "source_closure_sha256": sha256_bytes(canonical_bytes(source_closure())),
        }),
    }
    manifest = {"schema_version": 1, "files": _inventory(payloads)}
    for name, payload in sorted(payloads.items()):
        _write(derived / name, payload)
    _write(derived / "manifest.json", canonical_bytes(manifest))
    return summary


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _assert_trees_equal(expected: Path, actual: Path) -> None:
    expected_files = _tree_bytes(expected)
    actual_files = _tree_bytes(actual)
    if expected_files != actual_files:
        names = sorted(set(expected_files) ^ set(actual_files) | {name for name in set(expected_files) & set(actual_files) if expected_files[name] != actual_files[name]})
        raise RuntimeError(f"V3 qualification reconstruction mismatch: {names[:5]}")


def _freeze_record(specs: Sequence[V3EpisodeSpec]) -> dict[str, object]:
    closure = source_closure()
    configuration = {
        "stage": "PRE_OUTCOME_QUALIFICATION_ONLY",
        "episode_ticks": EPISODE_TICKS,
        "timestep_s": TIMESTEP_S,
        "reobserve_ticks": REOBSERVE_TICKS,
        "budgets": {"control": 2, "motion": 2, "semantic": 1},
        "calibration_seeds": CALIBRATION_SEEDS,
        "episode_ids": [item.episode_id for item in specs],
        "controllers": (PRIMARY_CONTROLLER_ID, SENSITIVITY_CONTROLLER_ID),
    }
    return {
        "schema_version": 1,
        "status": "QUALIFICATION_IMPLEMENTATION_UNAPPROVED",
        "self_authorizes_outcomes": False,
        "source_commit": subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=_root(), text=True).strip(),
        "source_closure": closure,
        "source_closure_sha256": sha256_bytes(canonical_bytes(closure)),
        "configuration": configuration,
        "configuration_sha256": sha256_bytes(canonical_bytes(configuration)),
    }


def run_qualification(output: Path) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(output)
    specs = qualification_specs()
    output.mkdir(parents=True)
    freeze = _freeze_record(specs)
    _write(output / "qualification-freeze.json", canonical_bytes(freeze))
    raws, scores, controls, not_run = _build_raw(output, specs)
    with tempfile.TemporaryDirectory(prefix="hierarchy-v3-qualification-replay.") as temp_name:
        replay_root = Path(temp_name)
        _write(replay_root / "qualification-freeze.json", canonical_bytes(freeze))
        replay_raws, replay_scores, replay_controls, replay_not_run = _build_raw(replay_root, specs)
        _assert_trees_equal(output / "raw", replay_root / "raw")
        replay = {
            "raw_matched": True,
            "derived_matched": True,
            "episodes_replayed": len(specs),
            "raw_manifest_sha256": sha256_bytes((output / "raw/manifest.json").read_bytes()),
        }
        summary = _derive(output, raws, scores, controls, not_run, replay)
        _derive(replay_root, replay_raws, replay_scores, replay_controls, replay_not_run, replay)
        _assert_trees_equal(output / "derived", replay_root / "derived")
    return summary


def _spec_from_row(row: Mapping[str, object]) -> V3EpisodeSpec:
    return V3EpisodeSpec(Architecture(str(row["architecture"])), str(row["scenario_id"]), int(row["seed"]), str(row["controller_id"]))


def reconstruct(output: Path, clean: Path) -> dict[str, object]:
    if clean.exists():
        raise FileExistsError(clean)
    freeze = json.loads((output / "qualification-freeze.json").read_text(encoding="ascii"))
    verify_source_closure(freeze["source_closure"])
    raw_manifest = json.loads((output / "raw/manifest.json").read_text(encoding="ascii"))
    specs = tuple(_spec_from_row(item) for item in raw_manifest["episodes"])
    clean.mkdir(parents=True)
    _write(clean / "qualification-freeze.json", (output / "qualification-freeze.json").read_bytes())
    raws, scores, controls, not_run = _build_raw(clean, specs)
    _assert_trees_equal(output / "raw", clean / "raw")
    replay = json.loads((output / "derived/replay.json").read_text(encoding="ascii"))
    _derive(clean, raws, scores, controls, not_run, replay)
    _assert_trees_equal(output / "derived", clean / "derived")
    _assert_trees_equal(output, clean)
    return {
        "matched": True,
        "episodes_replayed": len(specs),
        "raw_tree_sha256": sha256_bytes((clean / "raw/manifest.json").read_bytes()),
        "derived_tree_sha256": sha256_bytes((clean / "derived/manifest.json").read_bytes()),
    }


__all__ = [
    "episode_payloads",
    "qualification_specs",
    "reconstruct",
    "run_qualification",
    "source_closure",
    "verify_source_closure",
]
