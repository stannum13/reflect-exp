"""Create-only V3 qualification evidence, diagnostics, and full raw replay."""

from __future__ import annotations

import ast
import csv
import gzip
import hashlib
import html
import io
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zlib
from typing import Iterable, Mapping, Sequence

import numpy as np
import mujoco

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
from .v3_runtime import V3EpisodeRaw, V3EpisodeSpec, precheck, run_episode, unreachable_precheck_control
from .v3_scorer import ScoreResult, positive_control_audit, score_episode


_SEED_MODULES = (
    "experiments.03_recovery.run_v3_qualification",
    "experiments.03_recovery.run_v3_outcome",
    "experiments.03_recovery.src.v3_evidence",
    "experiments.03_recovery.src.v3_outcome",
    "experiments.03_recovery.src.contracts",
    "experiments.01_policy_control.src.arm",
    "experiments.01_policy_control.src.contracts",
    "experiments.01_policy_control.src.kinematics",
    "experiments.01_policy_control.src.representations",
)
_EXPLICIT_INPUTS = (
    "experiments/01_policy_control/configs/base.yaml",
    "docs/superpowers/specs/2026-08-23-hierarchical-recovery-v3-preregistered.md",
    "pyproject.toml",
    "uv.lock",
)
_BANNED_DECISION_TOKENS = (b"scenario", b"cause", b"expected_level", b"intended_level", b"domain")
_OBSERVABLE_PARAMETERS = (
    "tick", "trace_rows", "action_valid", "geometry_feasible", "semantic_preconditions_valid",
    "memory_version", "command_content_sha256", "successful_execution_content_sha256",
    "command_gap_ticks", "reobserve_index",
)
_FORBIDDEN_BOUNDARY_IDENTIFIERS = {
    "scenario_id", "realization", "hidden_cause", "external_force", "impulse_nm", "impulse_ticks",
    "dropout_ticks", "target_shift_xy", "obstacle_xy", "obstacle_radius_m", "semantic_delay_ticks",
    "injection_tick", "delivery_tick", "expected_level", "intended_level", "scenario_domain", "cause",
}


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


def cause_boundary_audit() -> dict[str, object]:
    """Statically close every runtime call into the observable and policy boundary."""
    runtime_path = _root() / "experiments/03_recovery/src/v3_runtime.py"
    policy_path = _root() / "experiments/03_recovery/src/v3_policy.py"
    runtime_payload = runtime_path.read_bytes()
    tree = ast.parse(runtime_payload, filename=str(runtime_path))
    observable_definition = next(
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_observable"
    )
    parameters = tuple(item.arg for item in (*observable_definition.args.args, *observable_definition.args.kwonlyargs))
    forbidden = sorted({node.id for node in ast.walk(observable_definition) if isinstance(node, ast.Name)} & _FORBIDDEN_BOUNDARY_IDENTIFIERS)
    observable_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_observable"
    ]
    observable_call_keywords = [tuple(item.arg for item in node.keywords) for node in observable_calls]
    policy_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "decide"
    ]
    policy_shapes = [
        {"positional": len(node.args), "keywords": [item.arg for item in node.keywords]}
        for node in policy_calls
    ]
    definitions = {
        node.name: node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    dependency_names = {"_observable", "_path_clear_from_observation", "_command_gap_from_action_history", "retained_load_estimate_nm"}
    pending = list(dependency_names)
    while pending:
        name = pending.pop()
        node = definitions.get(name)
        if node is None:
            continue
        called = {
            call.func.id for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in definitions
        }
        additions = called - dependency_names
        dependency_names.update(additions)
        pending.extend(additions)
    transitive_forbidden = sorted({
        identifier
        for name in dependency_names
        for node in ast.walk(definitions[name])
        for identifier in (
            node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else "",
        )
        if identifier in _FORBIDDEN_BOUNDARY_IDENTIFIERS
    })
    typed_sources_closed = bool(
        b"_path_clear(active, obstacle_active, realization" not in runtime_payload
        and b"command_gap_ticks=gap_ticks" not in runtime_payload
        and b"_path_clear_from_observation(active, world.observed_obstacle(), world.site_xy())" in runtime_payload
        and b"_command_gap_from_action_history(action_envelopes)" in runtime_payload
    )
    passed = bool(
        parameters == _OBSERVABLE_PARAMETERS
        and not forbidden
        and len(observable_calls) >= 2
        and all(keywords == _OBSERVABLE_PARAMETERS for keywords in observable_call_keywords)
        and policy_calls
        and all(item == {"positional": 3, "keywords": []} for item in policy_shapes)
        and not transitive_forbidden
        and typed_sources_closed
    )
    return {
        "passed": passed,
        "observable_parameters": list(parameters),
        "forbidden_identifiers": forbidden,
        "observable_call_count": len(observable_calls),
        "observable_call_keywords": [list(item) for item in observable_call_keywords],
        "policy_call_count": len(policy_calls),
        "policy_call_shapes": policy_shapes,
        "dependency_closure": sorted(dependency_names),
        "transitive_forbidden_identifiers": transitive_forbidden,
        "typed_sources_closed": typed_sources_closed,
        "runtime_sha256": sha256_bytes(runtime_payload),
        "policy_sha256": sha256_bytes(policy_path.read_bytes()),
    }


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
        "memory-events.jsonl": _jsonl(raw.memory_events),
        "observations.jsonl": _jsonl(raw.observations),
        "decisions.jsonl": _jsonl(raw.decisions),
        "budget-resets.jsonl": _jsonl(raw.budget_resets),
        "execution-receipts.jsonl": _jsonl(raw.execution_receipts),
        "commands.jsonl": _jsonl(raw.commands),
        "trajectories.bin": raw.trajectory_bytes,
        "action-envelopes.jsonl": _jsonl(raw.action_envelopes),
        "contact-envelopes.jsonl": _jsonl(raw.contact_envelopes),
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
    control = unreachable_precheck_control()
    receipt = precheck(control)
    return {
        "control_id": control.control_id,
        "episode_id": None,
        "disposition": receipt.disposition,
        "reason": receipt.reason,
        "architecture_independent": receipt.architecture_independent,
        "geometry_sha256": receipt.geometry_sha256,
        "precheck_input": control,
        "precheck_receipt": receipt,
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


def _rsvg_binary() -> Path:
    path = shutil.which("rsvg-convert")
    if path is None:
        raise RuntimeError("frozen SVG rasterizer rsvg-convert is unavailable")
    return Path(path).resolve()


def _diagnostic_png(svg: bytes) -> bytes:
    """Rasterize the exact authenticated SVG, preserving every displayed cell."""
    result = subprocess.run(
        (str(_rsvg_binary()), "--format=png"), input=svg, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=True,
    )
    if not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("frozen SVG rasterizer emitted invalid PNG")
    return result.stdout


def _sequence(raw: V3EpisodeRaw) -> str:
    return ">".join(item.level.value for item in raw.decisions if item.level is not DecisionLevel.NONE) or "NONE"


def _disturbance_audit(raws: Mapping[str, V3EpisodeRaw]) -> dict[str, object]:
    anchor = next(
        item for item in raws.values()
        if item.spec.architecture is Architecture.R3 and item.spec.scenario_id == "anchor-nominal"
        and item.spec.seed == 20261891 and item.spec.controller_id == PRIMARY_CONTROLLER_ID
    )

    def domains(raw: V3EpisodeRaw) -> dict[str, str]:
        physical = b"".join(np.asarray(raw.trace[name]).tobytes() for name in (
            "q", "dq", "eef_xy", "applied_force_nm", "contact_count", "contact_force_norm_n", "contact_torque_norm_nm",
        ))
        return {
            "physical": sha256_bytes(physical),
            "action": sha256_bytes(canonical_bytes(raw.action_envelopes) + canonical_bytes(raw.commands) + raw.trajectory_bytes),
            "memory": sha256_bytes(canonical_bytes(raw.memory_events) + canonical_bytes(raw.memory_ledger)),
            "world": sha256_bytes(canonical_bytes(raw.world_ledger)),
        }

    anchor_domains = domains(anchor)
    intended_changes = {
        "anchor-slow-policy": {"physical", "action"},
        "control-impulse": {"physical"},
        "control-dropout": {"physical", "action"},
        "motion-target-shift": {"physical", "action", "memory", "world"},
        "motion-path-infeasible": {"physical", "action", "world"},
        "semantic-object-unavailable": {"physical", "action", "memory", "world"},
        "semantic-restriction-change": {"physical", "action", "memory", "world"},
    }
    required_unchanged = {
        "anchor-slow-policy": {"memory"}, "control-impulse": {"memory"}, "control-dropout": {"memory"},
        "motion-path-infeasible": {"memory"},
    }
    receipts: list[dict[str, object]] = []
    for raw in sorted(raws.values(), key=lambda item: item.spec.episode_id):
        scenario = raw.spec.scenario_id
        tick = raw.realization.injection_tick
        passed = raw.injection_rows == (tick,) and int(raw.trace["tick"][tick]) == tick
        details: dict[str, object] = {"episode_id": raw.spec.episode_id, "scenario_id": scenario, "injection_tick": tick}
        if raw.spec.architecture is Architecture.R3 and raw.spec.seed == 20261891 and scenario in intended_changes:
            observed_domains = domains(raw)
            changed = {name for name, digest in observed_domains.items() if digest != anchor_domains[name]}
            passed = passed and intended_changes[scenario] <= changed and not (required_unchanged.get(scenario, set()) & changed)
            details.update({
                "matched_anchor_episode_id": anchor.spec.episode_id,
                "anchor_domain_sha256": anchor_domains,
                "disturbed_domain_sha256": observed_domains,
                "changed_domains": sorted(changed),
                "required_changed_domains": sorted(intended_changes[scenario]),
                "required_unchanged_domains": sorted(required_unchanged.get(scenario, set())),
            })
        if scenario == "control-impulse":
            force = np.asarray(raw.trace["applied_force_nm"])
            nz = np.flatnonzero(np.linalg.norm(force, axis=1) > 0.0).tolist()
            expected = list(range(tick, tick + raw.realization.impulse_ticks))
            vector = (1.0 if raw.realization.seed % 2 else -1.0) * raw.realization.impulse_nm * np.asarray((1.0, -1.0, 0.5))
            passed = passed and nz == expected and np.array_equal(force[expected], np.tile(vector, (len(expected), 1)))
            details.update({"nonzero_force_ticks": nz, "expected_force_ticks": expected, "force_vector_nm": vector.tolist()})
        elif scenario == "control-dropout":
            held = [int(item["tick"]) for item in raw.action_envelopes if item.get("hold_reason") == "COMMAND_WITHHELD"]
            expected = list(range(tick, tick + raw.realization.dropout_ticks))
            passed = passed and held == expected
            details.update({"withheld_ticks": held, "expected_withheld_ticks": expected})
        elif scenario == "motion-target-shift":
            events = [item for item in raw.world_ledger if item["event"] == "TARGET_SHIFT"]
            expected_target = np.asarray(raw.realization.target_a_xy) + np.asarray(raw.realization.target_shift_xy)
            passed = passed and len(events) == 1 and int(events[0]["tick"]) == tick and np.array_equal(np.asarray(events[0]["target_xy"]), expected_target)
            details.update({"events": events, "expected_target_xy": expected_target.tolist()})
        elif scenario == "motion-path-infeasible":
            events = [item for item in raw.world_ledger if item["event"] == "OBSTACLE_ACTIVATED"]
            waypoint_commands = [item for item in raw.commands if len(item["path_xy"]) > 1]
            passed = passed and len(events) == 1 and int(events[0]["tick"]) == tick and bool(waypoint_commands) and not bool(np.asarray(raw.trace["obstacle_contact"]).any())
            details.update({"obstacle_events": events, "waypoint_command_count": len(waypoint_commands)})
        elif scenario.startswith("semantic-"):
            delivery = tick + raw.realization.semantic_delay_ticks
            delivered = [item for item in raw.semantic_events if item["event"] == "DELIVERED_OBSERVATION"]
            snapshots = [item for item in raw.memory_ledger if int(item["tick"]) == delivery]
            selected = [item for item in raw.world_ledger if item["event"] == "AUTHORIZED_ALTERNATIVE_SELECTED" and int(item["tick"]) >= delivery]
            holds = [item for item in raw.action_envelopes if int(item["tick"]) == delivery and item["mode"] == "HOLD"]
            forbidden_a = [item for item in raw.action_envelopes if int(item["tick"]) >= delivery and item["mode"] == "EXECUTE" and item["object_id"] == "object-a"]
            appropriate_resolution = not forbidden_a and (
                raw.spec.architecture is Architecture.R0
                or any(item["target_object_id"] == "object-b" for item in selected)
            )
            passed = passed and len(delivered) == 1 and int(delivered[0]["delivery_tick"]) == delivery and bool(snapshots) and bool(holds) and appropriate_resolution
            details.update({"delivery_tick": delivery, "delivered": delivered, "snapshot_count": len(snapshots), "safe_hold_count": len(holds), "alternative_events": selected})
        elif scenario == "anchor-slow-policy":
            generated = [int(item["generated_tick"]) for item in raw.commands]
            passed = passed and tick + 10 in generated and all(value >= tick + 10 for value in generated)
            details["command_generation_ticks"] = generated
        details["passed"] = bool(passed)
        receipts.append(details)
    return {"passed": all(bool(item["passed"]) for item in receipts), "receipts": receipts}


def _injection_audit(raws: Mapping[str, V3EpisodeRaw]) -> dict[str, object]:
    receipts = [{
        "episode_id": episode_id,
        "sampled_tick": raw.realization.injection_tick,
        "retained_rows": list(raw.injection_rows),
        "passed": raw.injection_rows == (raw.realization.injection_tick,)
        and int(raw.trace["tick"][raw.realization.injection_tick]) == raw.realization.injection_tick,
    } for episode_id, raw in sorted(raws.items())]
    return {"passed": all(item["passed"] for item in receipts), "receipts": receipts}


def _budget_audit(raws: Mapping[str, V3EpisodeRaw], scores: Mapping[str, ScoreResult]) -> dict[str, object]:
    receipts: list[dict[str, object]] = []
    for episode_id, raw in sorted(raws.items()):
        prior = {DecisionLevel.CONTROL: 2, DecisionLevel.MOTION: 2, DecisionLevel.SEMANTIC: 1}
        prior_tick = -REOBSERVE_TICKS
        prior_after: object | None = None
        valid = True
        transitions = []
        for decision in raw.decisions:
            before = decision.budget_before
            after = decision.budget_after
            if prior_after is not None and canonical_bytes(before) != canonical_bytes(prior_after):
                matching_resets = [
                    item for item in raw.budget_resets
                    if item["new_content_sha256"] == before.active_content_sha256 and int(item["tick"]) <= decision.observed_tick
                ]
                valid = valid and bool(matching_resets) and (
                    before.control_remaining, before.motion_remaining, before.semantic_remaining
                ) == (2, 2, 1)
                prior = {DecisionLevel.CONTROL: 2, DecisionLevel.MOTION: 2, DecisionLevel.SEMANTIC: 1}
            if decision.level in prior:
                valid = valid and decision.observed_tick - prior_tick >= REOBSERVE_TICKS and prior[decision.level] > 0
                prior[decision.level] -= 1
                prior_tick = decision.observed_tick
                expected_counts = {
                    DecisionLevel.CONTROL: (before.control_remaining - 1, before.motion_remaining, before.semantic_remaining),
                    DecisionLevel.MOTION: (before.control_remaining, before.motion_remaining - 1, before.semantic_remaining),
                    DecisionLevel.SEMANTIC: (before.control_remaining, before.motion_remaining, before.semantic_remaining - 1),
                }[decision.level]
                valid = valid and expected_counts == (
                    after.control_remaining, after.motion_remaining, after.semantic_remaining
                ) and after.active_content_sha256 == before.active_content_sha256 and after.last_observed_tick == decision.observed_tick
                transitions.append({"tick": decision.observed_tick, "level": decision.level.value, "remaining": prior[decision.level]})
            else:
                valid = valid and canonical_bytes(before) == canonical_bytes(after)
            prior_after = after
        scorer = scores[episode_id]
        for reset in raw.budget_resets:
            matching = [item for item in raw.execution_receipts if item["receipt_sha256"] == reset["execution_receipt_sha256"]]
            valid = valid and reset["old_content_sha256"] != reset["new_content_sha256"] and len(matching) == 1 and scorer.violation_counts["reset"] == 0
        receipts.append({"episode_id": episode_id, "passed": bool(valid), "transitions": transitions, "reset_count": len(raw.budget_resets)})
    return {"passed": all(bool(item["passed"]) for item in receipts), "receipts": receipts}


def _not_run_audit(not_run: Mapping[str, object]) -> dict[str, object]:
    retained = not_run["precheck_input"]
    fresh = _not_run_control()
    target = np.asarray(getattr(retained, "target_a_xy"), dtype=np.float64)
    q0 = np.asarray(getattr(retained, "q0"), dtype=np.float64)
    arm_reach = 0.75
    radius = float(np.linalg.norm(target))
    receipt_equal = canonical_bytes(fresh) == canonical_bytes(not_run)
    return {
        "passed": bool(radius > arm_reach and receipt_equal and not_run["disposition"] == "NOT_RUN"),
        "target_radius_m": radius,
        "arm_reach_m": arm_reach,
        "q0": q0.tolist(),
        "receipt_recomputed_equal": receipt_equal,
        "reason": not_run["reason"],
    }


def _precheck_audit(raws: Mapping[str, V3EpisodeRaw], not_run: Mapping[str, object]) -> dict[str, object]:
    receipts = []
    for episode_id, raw in sorted(raws.items()):
        fresh = precheck(raw.spec)
        passed = bool(
            canonical_bytes(fresh) == canonical_bytes(raw.precheck)
            and fresh.architecture_independent
            and fresh.realization_sha256 == raw.realization.parameter_sha256
        )
        receipts.append({
            "episode_id": episode_id,
            "passed": passed,
            "input_sha256": fresh.realization_sha256,
            "geometry_sha256": fresh.geometry_sha256,
            "disposition": fresh.disposition,
        })
    outcome_path = (_root() / "experiments/03_recovery/src/v3_outcome.py").read_bytes()
    outcome_plan_closed = bool(
        b"for spec in specs:" in outcome_path
        and b"receipt = precheck(spec)" in outcome_path
        and b"raw = run_episode(spec)" in outcome_path
        and outcome_path.index(b"receipt = precheck(spec)") < outcome_path.index(b"raw = run_episode(spec)")
    )
    control = _not_run_audit(not_run)
    return {
        "passed": bool(len(receipts) == len(raws) == 18 and all(item["passed"] for item in receipts) and outcome_plan_closed and control["passed"]),
        "qualification_receipts": receipts,
        "qualification_identity_count": len(receipts),
        "outcome_planned_identity_count": 360,
        "outcome_precheck_before_execution": outcome_plan_closed,
        "not_run_control": control,
    }


def _gate_rows(
    raws: Mapping[str, V3EpisodeRaw],
    scores: Mapping[str, ScoreResult],
    controls: Mapping[str, Mapping[str, object]],
    not_run: Mapping[str, object],
    replay: Mapping[str, object],
) -> list[dict[str, object]]:
    def select(architecture: Architecture, scenario: str, seed: int, controller: str = PRIMARY_CONTROLLER_ID) -> V3EpisodeRaw:
        return next(item for item in raws.values() if item.spec.architecture is architecture and item.spec.scenario_id == scenario and item.spec.seed == seed and item.spec.controller_id == controller)

    disturbance_receipt = _disturbance_audit(raws)

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

    budget_receipt = _budget_audit(raws, scores)
    boundary_receipt = cause_boundary_audit()
    boundaries = bool(boundary_receipt["passed"])
    scorer_closed = all(score_episode(raw) == scores[episode_id] for episode_id, raw in raws.items()) and b"v3_runtime" not in (_root() / "experiments/03_recovery/src/v3_scorer.py").read_bytes()
    positives = set(controls) == {"unsafe", "forbidden", "collision", "stale", "invalid_action", "wrong_object", "missed_dwell", "loop", "reset"} and all(item["terminal"] == "FAILURE" and int(item["detected_count"]) > 0 for item in controls.values())
    return [
        {"gate": 1, "passed": _injection_audit(raws)["passed"], "evidence": "every sampled injection tick equals its retained boundary row"},
        {"gate": 2, "passed": disturbance_receipt["passed"], "evidence": "scenario-specific units, intervals, world events and effects independently audited"},
        {"gate": 3, "passed": policies_distinct, "evidence": "observable R0/R1/R2/R3 sequences retained"},
        {"gate": 4, "passed": controllers_distinct, "evidence": "real P6/P4 path and bytes differ"},
        {"gate": 5, "passed": budget_receipt["passed"], "evidence": "independent 2/2/1 transitions, elapsed time and guarded reset receipts"},
        {"gate": 6, "passed": boundaries, "evidence": "decision/observable cause boundary closed"},
        {"gate": 7, "passed": scorer_closed, "evidence": "independent scorer reconstructs immutable raw"},
        {"gate": 8, "passed": positives, "evidence": "nine scorer terminal positive controls"},
        {"gate": 9, "passed": bool(replay["raw_matched"] and replay["derived_matched"]), "evidence": "raw replay and derived reconstruction byte exact"},
        {"gate": 10, "passed": _precheck_audit(raws, not_run)["passed"], "evidence": "every qualification identity and frozen outcome plan is prechecked before execution"},
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
    examples = {"working": working, "nonworking": nonworking, "not_run": not_run["control_id"]}
    gate_audits = {
        "injection": _injection_audit(raws),
        "disturbance": _disturbance_audit(raws),
        "budgets": _budget_audit(raws, scores),
        "cause_boundary": cause_boundary_audit(),
        "not_run": _precheck_audit(raws, not_run),
    }
    payloads: dict[str, bytes] = {
        "qualification-summary.json": canonical_bytes(summary),
        "hard-gates.csv": _csv(gate_csv_rows, ("gate", "passed", "evidence")),
        "replay.json": canonical_bytes(replay),
        "examples.json": canonical_bytes(examples),
        "gate-audits.json": canonical_bytes(gate_audits),
        "injection-timing.csv": _csv(injection_rows, ("episode_id", "scenario_id", "seed", "sampled_tick", "retained_tick", "parameter_sha256", "physical_trace_sha256")),
        "injection-timing.svg": _diagnostic_svg("Sampled and retained injection ticks", injection_rows, ("scenario_id", "seed", "sampled_tick", "retained_tick", "physical_trace_sha256")),
        "injection-timing.png": _diagnostic_png(_diagnostic_svg("Sampled and retained injection ticks", injection_rows, ("scenario_id", "seed", "sampled_tick", "retained_tick", "physical_trace_sha256"))),
        "controller-paths.csv": _csv(controller_rows, ("controller_id", "call_path", "trajectory_sha256", "q_ref_sha256", "torque_sha256")),
        "controller-paths.svg": _diagnostic_svg("Existing P6 and repaired P4 byte identities", controller_rows, ("controller_id", "call_path", "trajectory_sha256", "q_ref_sha256", "torque_sha256")),
        "controller-paths.png": _diagnostic_png(_diagnostic_svg("Existing P6 and repaired P4 byte identities", controller_rows, ("controller_id", "call_path", "trajectory_sha256", "q_ref_sha256", "torque_sha256"))),
        "budget-sequences.csv": _csv(budget_rows, ("episode_id", "tick", "level", "control_remaining", "motion_remaining", "semantic_remaining")),
        "budget-sequences.svg": _diagnostic_svg("Time-advanced decision and budget sequences", budget_rows, ("episode_id", "tick", "level", "control_remaining", "motion_remaining", "semantic_remaining")),
        "budget-sequences.png": _diagnostic_png(_diagnostic_svg("Time-advanced decision and budget sequences", budget_rows, ("episode_id", "tick", "level", "control_remaining", "motion_remaining", "semantic_remaining"))),
        "scorer-controls.csv": _csv(control_rows, ("control", "terminal", "detected_count")),
        "scorer-controls.svg": _diagnostic_svg("Independent scorer terminal positive controls", control_rows, ("control", "terminal", "detected_count")),
        "scorer-controls.png": _diagnostic_png(_diagnostic_svg("Independent scorer terminal positive controls", control_rows, ("control", "terminal", "detected_count"))),
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


def tree_sha256(root: Path) -> str:
    inventory = [
        {"path": name, "bytes": len(payload), "sha256": sha256_bytes(payload)}
        for name, payload in sorted(_tree_bytes(root).items())
    ]
    return sha256_bytes(canonical_bytes(inventory))


def publish_durable_archive(output: Path, destination: Path) -> dict[str, object]:
    """Publish a deterministic, content-addressed archive suitable for git retention."""
    if not output.is_dir():
        raise FileNotFoundError(output)
    destination.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0, compresslevel=9) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as archive:
            for name, payload in sorted(_tree_bytes(output).items()):
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                info.mtime = 0
                info.mode = 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                archive.addfile(info, io.BytesIO(payload))
    payload = buffer.getvalue()
    digest = sha256_bytes(payload)
    archive_name = f"{digest}.tar.gz"
    archive_path = destination / archive_name
    if archive_path.exists():
        if archive_path.is_symlink() or not archive_path.is_file() or archive_path.read_bytes() != payload:
            raise RuntimeError("durable archive create-only member mismatch")
    else:
        _write(archive_path, payload)
    receipt = {
        "schema_version": 1,
        "archive": archive_name,
        "archive_sha256": digest,
        "archive_bytes": len(payload),
        "tree_sha256": tree_sha256(output),
        "member_count": len(_tree_bytes(output)),
    }
    manifest_payload = canonical_bytes(receipt)
    manifest_path = destination / "manifest.json"
    if manifest_path.exists():
        if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.read_bytes() != manifest_payload:
            raise RuntimeError("durable archive manifest mismatch")
    else:
        _write(manifest_path, manifest_payload)
    return receipt


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
        "outcome_matrix": {
            "episode_count": 360,
            "seeds": list(range(20261801, 20261811)),
            "primary_cells": 320,
            "sensitivity_cells": 40,
            "approval_binding_required": True,
        },
    }
    environment = current_environment()
    return {
        "schema_version": 1,
        "status": "QUALIFICATION_IMPLEMENTATION_UNAPPROVED",
        "self_authorizes_outcomes": False,
        "source_commit": subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=_root(), text=True).strip(),
        "source_closure": closure,
        "source_closure_sha256": sha256_bytes(canonical_bytes(closure)),
        "configuration": configuration,
        "configuration_sha256": sha256_bytes(canonical_bytes(configuration)),
        "environment": environment,
        "environment_sha256": sha256_bytes(canonical_bytes(environment)),
    }


def current_environment() -> dict[str, object]:
    executable = Path(sys.executable).resolve()
    rasterizer = _rsvg_binary()
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": str(executable),
        "python_executable_sha256": sha256_bytes(executable.read_bytes()),
        "numpy": np.__version__,
        "mujoco": mujoco.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "png_renderer": "RSVG_EXACT_SVG_RASTER_V1",
        "png_renderer_executable": str(rasterizer),
        "png_renderer_executable_sha256": sha256_bytes(rasterizer.read_bytes()),
        "png_renderer_version": subprocess.check_output((str(rasterizer), "--version"), text=True).strip(),
        "zlib": zlib.ZLIB_VERSION,
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
    if freeze["environment"] != _freeze_record(qualification_specs())["environment"]:
        raise RuntimeError("V3 qualification environment drift")
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
    "cause_boundary_audit",
    "current_environment",
    "episode_payloads",
    "qualification_specs",
    "publish_durable_archive",
    "reconstruct",
    "run_qualification",
    "source_closure",
    "tree_sha256",
    "verify_source_closure",
]
