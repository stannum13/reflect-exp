"""Frozen direct-outcome matrix over the production hierarchy runtime."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import numpy as np

_contracts = importlib.import_module("experiments.03_recovery.src.v3_contracts")
_runtime = importlib.import_module("experiments.03_recovery.src.v3_runtime")
_evidence = importlib.import_module("experiments.03_recovery.src.v3_evidence")
_outcome = importlib.import_module("experiments.03_recovery.src.v3_outcome")
_scorer = importlib.import_module("experiments.03_recovery.src.v3_scorer")
Architecture = _contracts.Architecture
PRIMARY_CONTROLLER_ID = _contracts.PRIMARY_CONTROLLER_ID
RunStage = _contracts.RunStage
SENSITIVITY_CONTROLLER_ID = _contracts.SENSITIVITY_CONTROLLER_ID
canonical_bytes = _contracts.canonical_bytes
sha256_bytes = _contracts.sha256_bytes
PrecheckControlSpec = _runtime.PrecheckControlSpec
PrecheckReceipt = _runtime.PrecheckReceipt
precheck = _runtime.precheck
run_episode = _runtime.run_episode


EXPERIMENT_ID = "exp15-direct-hierarchy-replication-v2"
PRIMARY_SEEDS = tuple(range(20262301, 20262311))
SENSITIVITY_SEEDS = PRIMARY_SEEDS[:5]
FAMILIES = (
    "control-impulse",
    "control-dropout",
    "motion-target-shift",
    "motion-path-infeasible",
    "semantic-object-unavailable",
    "semantic-restriction-change",
)
SEVERITIES = ("LOW", "HIGH")
OUTCOME_ROW_FIELDS = (
    "episode_id", "architecture", "family", "severity", "seed", "controller_id",
    "matrix_role", "terminal", "mission_success", "safety_composite", "progress",
    "retry_count", "control_wakes", "motion_wakes", "semantic_wakes",
    "recovery_latency_ticks", "aborts", "peak_torque_nm", "rms_torque_nm",
    "peak_contact_force_n", "trajectory_length_rad", "action_cost",
)


@dataclass(frozen=True)
class DirectSpec:
    architecture: Architecture
    family: str
    severity: str
    seed: int
    controller_id: str
    matrix_role: str
    stage: RunStage = RunStage.OUTCOME

    @property
    def scenario_id(self) -> str:
        return self.family

    @property
    def episode_id(self) -> str:
        controller = "P6" if self.controller_id == PRIMARY_CONTROLLER_ID else "P4"
        return f"exp15v2-{controller}-{self.architecture.value}-{self.family}-{self.severity.lower()}-{self.seed}"


@dataclass(frozen=True)
class DirectRealization:
    scenario_id: str
    stage: RunStage
    seed: int
    q0: tuple[float, float, float]
    target_a_xy: tuple[float, float]
    target_b_xy: tuple[float, float]
    injection_tick: int
    impulse_nm: float
    impulse_ticks: int
    dropout_ticks: int
    target_shift_xy: tuple[float, float]
    obstacle_xy: tuple[float, float]
    obstacle_radius_m: float
    damping_multiplier: float
    semantic_delay_ticks: int
    parameter_sha256: str


def matrix_specs() -> tuple[DirectSpec, ...]:
    primary = (
        DirectSpec(architecture, family, severity, seed, PRIMARY_CONTROLLER_ID, "PRIMARY")
        for architecture in Architecture
        for family in FAMILIES
        for severity in SEVERITIES
        for seed in PRIMARY_SEEDS
    )
    sensitivity = (
        DirectSpec(Architecture.R3, family, severity, seed, SENSITIVITY_CONTROLLER_ID, "SENSITIVITY")
        for family in FAMILIES
        for severity in SEVERITIES
        for seed in SENSITIVITY_SEEDS
    )
    specs = tuple(sorted((*primary, *sensitivity), key=lambda item: item.episode_id))
    if len(specs) != 540 or len({item.episode_id for item in specs}) != 540:
        raise RuntimeError("Exp15 frozen matrix identity error")
    return specs


def make_realization(spec: DirectSpec) -> DirectRealization:
    if spec.family not in FAMILIES or spec.severity not in SEVERITIES:
        raise ValueError("Exp15 family/severity outside freeze")
    if spec.seed not in PRIMARY_SEEDS:
        raise ValueError("Exp15 seed outside freeze")
    namespace = int.from_bytes(
        hashlib.sha256(f"{EXPERIMENT_ID}:{spec.family}:{spec.severity}:{spec.seed}".encode("ascii")).digest()[:8],
        "little",
    )
    rng = np.random.Generator(np.random.PCG64(namespace))
    q0 = tuple(float(item) for item in np.array((0.35, -0.70, 0.35)) + rng.uniform(-0.025, 0.025, 3))
    target_a = np.array((0.55, 0.08)) + rng.uniform(-0.018, 0.018, 2)
    target_b = np.array((0.49, -0.14)) + rng.uniform(-0.018, 0.018, 2)
    direction = float(rng.uniform(-math.pi, math.pi))
    shift_m = 0.040 if spec.severity == "LOW" else 0.065
    shift = shift_m * np.asarray((math.cos(direction), math.sin(direction)))
    angles = np.cumsum(np.asarray(q0))
    links = np.asarray((0.30, 0.25, 0.20))
    start = np.asarray((np.dot(links, np.cos(angles)), np.dot(links, np.sin(angles))))
    obstacle = (start + target_a) / 2.0 + rng.uniform(-0.006, 0.006, 2)
    high = spec.severity == "HIGH"
    values = {
        "scenario_id": spec.family,
        "stage": RunStage.OUTCOME,
        "seed": spec.seed,
        "q0": q0,
        "target_a_xy": tuple(float(item) for item in target_a),
        "target_b_xy": tuple(float(item) for item in target_b),
        "injection_tick": int(rng.integers(600, 901)),
        "impulse_nm": 0.26 if high else 0.14,
        "impulse_ticks": 10 if high else 5,
        "dropout_ticks": 50 if high else 25,
        "target_shift_xy": tuple(float(item) for item in shift),
        "obstacle_xy": tuple(float(item) for item in obstacle),
        "obstacle_radius_m": 0.0475 if high else 0.0375,
        "damping_multiplier": float(rng.uniform(0.90, 1.10)),
        "semantic_delay_ticks": 10 if high else 2,
    }
    identity = {key: value for key, value in values.items() if key not in {"stage"}}
    return DirectRealization(**values, parameter_sha256=sha256_bytes(canonical_bytes(identity)))


def _cell_precheck(spec: DirectSpec, realization: DirectRealization | None = None) -> tuple[DirectRealization, object]:
    realization = realization or make_realization(spec)
    receipt = precheck(PrecheckControlSpec(
        f"{EXPERIMENT_ID}:{spec.family}:{spec.severity}:{spec.seed}",
        realization.q0,
        realization.target_a_xy,
        realization.target_b_xy,
        realization.obstacle_xy,
        realization.obstacle_radius_m,
    ))
    return realization, receipt


def run_cell(spec: DirectSpec, *, realization: DirectRealization | None = None, receipt: object | None = None) -> object:
    if realization is None or receipt is None:
        realization, receipt = _cell_precheck(spec, realization)
    return run_episode(spec, realization_override=realization, precheck_override=receipt)


def _not_run_row(spec: DirectSpec, realization: DirectRealization, receipt: object) -> dict[str, object]:
    receipt_payload = _receipt_payload(receipt)
    return {
        "episode_id": spec.episode_id,
        "architecture": spec.architecture.value,
        "family": spec.family,
        "severity": spec.severity,
        "seed": spec.seed,
        "controller_id": spec.controller_id,
        "matrix_role": spec.matrix_role,
        "disposition": "NOT_RUN",
        "parameter_sha256": realization.parameter_sha256,
        "architecture_independent": receipt.architecture_independent,
        "precheck_receipt": receipt_payload,
        "precheck_receipt_sha256": sha256_bytes(canonical_bytes(receipt_payload)),
    }


def _receipt_payload(receipt: object) -> dict[str, object]:
    return {
        "disposition": receipt.disposition,
        "reason": receipt.reason,
        "architecture_independent": receipt.architecture_independent,
        "precheck_input": dict(receipt.precheck_input),
        "realization_sha256": receipt.realization_sha256,
        "geometry_sha256": receipt.geometry_sha256,
        "straight_path_blocked": receipt.straight_path_blocked,
        "waypoint_path_clear": receipt.waypoint_path_clear,
        "target_a_ik_error_m": receipt.target_a_ik_error_m,
        "target_b_ik_error_m": receipt.target_b_ik_error_m,
    }


def _invalid_execution_row(
    spec: DirectSpec,
    error: Exception,
    *,
    stage: str,
    source_commit: str,
    freeze_sha256: str,
    realization: DirectRealization | None = None,
) -> dict[str, object]:
    return {
        "episode_id": spec.episode_id,
        "architecture": spec.architecture.value,
        "family": spec.family,
        "severity": spec.severity,
        "seed": spec.seed,
        "controller_id": spec.controller_id,
        "matrix_role": spec.matrix_role,
        "disposition": "INVALID_EXECUTION",
        "execution_stage": stage,
        "exception_class": type(error).__name__,
        "exception_message": str(error),
        "parameter_sha256": None if realization is None else realization.parameter_sha256,
        "source_commit": source_commit,
        "freeze_sha256": freeze_sha256,
    }
def score_cell(raw: object) -> dict[str, object]:
    score = _scorer.score_episode(raw)
    counts = score.violation_counts
    levels = [item.level.value for item in raw.decisions]
    errors = np.asarray(raw.trace["target_error_m"], dtype=np.float64)
    injection = int(raw.realization.injection_tick)
    initial_error = max(float(errors[injection]), 1e-12)
    progress = float(np.clip((initial_error - float(errors[-1])) / initial_error, 0.0, 1.0))
    torque = np.asarray(raw.trace["actuator_cmd_nm"], dtype=np.float64)
    q = np.asarray(raw.trace["q"], dtype=np.float64)
    contact_force = np.asarray(raw.trace["contact_force_norm_n"], dtype=np.float64)
    decisions = [item for item in raw.decisions if item.level.value != "NONE"]
    first_tick = min((item.observed_tick for item in decisions), default=injection)
    safety = any(int(counts[key]) > 0 for key in (
        "unsafe", "forbidden", "collision", "invalid_action", "stale", "wrong_object", "loop", "reset",
    ))
    values = {
        "episode_id": raw.spec.episode_id,
        "architecture": raw.spec.architecture.value,
        "family": raw.spec.family,
        "severity": raw.spec.severity,
        "seed": raw.spec.seed,
        "controller_id": raw.spec.controller_id,
        "matrix_role": raw.spec.matrix_role,
        "terminal": score.terminal,
        "mission_success": score.terminal == "SUCCESS",
        "safety_composite": bool(safety),
        "progress": progress,
        "retry_count": len(decisions),
        "control_wakes": levels.count("CONTROL"),
        "motion_wakes": levels.count("MOTION"),
        "semantic_wakes": levels.count("SEMANTIC"),
        "recovery_latency_ticks": max(0, first_tick - injection),
        "aborts": levels.count("SAFE_ABORT"),
        "peak_torque_nm": float(np.max(np.abs(torque))),
        "rms_torque_nm": float(np.sqrt(np.mean(np.square(torque)))),
        "peak_contact_force_n": float(np.max(contact_force)),
        "trajectory_length_rad": float(np.sum(np.linalg.norm(np.diff(q, axis=0), axis=1))),
        "action_cost": float(np.sum(np.abs(torque)) * 0.002),
    }
    return {name: values[name] for name in OUTCOME_ROW_FIELDS}


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source_closure() -> list[dict[str, object]]:
    paths = {
        _root() / item["path"] for item in _evidence.source_closure()
    }
    paths.update({
        Path(__file__),
        _root() / "experiments/15_direct_hierarchy_replication/__init__.py",
        _root() / "experiments/15_direct_hierarchy_replication/src/__init__.py",
        _root() / "experiments/15_direct_hierarchy_replication/run.py",
        _root() / "experiments/15_direct_hierarchy_replication/analyze.py",
        _root() / "experiments/15_direct_hierarchy_replication/src/analysis.py",
        _root() / "experiments/15_direct_hierarchy_replication/src/compact_evidence.py",
        _root() / "experiments/15_direct_hierarchy_replication/tests/__init__.py",
        _root() / "experiments/15_direct_hierarchy_replication/tests/test_experiment.py",
        _root() / "experiments/15_direct_hierarchy_replication/tests/test_compact_evidence.py",
        _root() / "docs/superpowers/specs/2026-08-24-exp15-v2-clean-replication.md",
        _root() / "pyproject.toml",
        _root() / "uv.lock",
    })
    result = []
    for path in sorted(item.resolve() for item in paths if item.is_file()):
        payload = path.read_bytes()
        result.append({"path": path.relative_to(_root()).as_posix(), "bytes": len(payload), "sha256": sha256_bytes(payload)})
    return result


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _validate_source_approval(path: Path | None, source_commit: str) -> tuple[dict[str, object], str]:
    if path is None or not path.is_file():
        raise RuntimeError("Exp15 V2 source audit approval is required before freeze")
    payload = path.read_bytes()
    approval = json.loads(payload.decode("ascii"))
    expected_keys = {
        "schema_version", "experiment_id", "source_commit", "verdict",
        "review_scope", "reviewer",
    }
    if (
        canonical_bytes(approval) != payload
        or set(approval) != expected_keys
        or approval["schema_version"] != 1
        or approval["experiment_id"] != EXPERIMENT_ID
        or approval["source_commit"] != source_commit
        or approval["verdict"] != "APPROVE"
        or approval["review_scope"] != "SOURCE_PREREGISTRATION_BEFORE_FREEZE"
        or not approval["reviewer"]
    ):
        raise RuntimeError("Exp15 V2 source audit approval mismatch")
    return approval, sha256_bytes(payload)


def freeze(
    output: Path,
    *,
    source_commit: str,
    tracked_path: Path | None = None,
    source_approval: Path | None = None,
) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(output)
    if len(source_commit) != 40:
        raise ValueError("Exp15 freeze requires a full source commit")
    approval, approval_sha256 = _validate_source_approval(source_approval, source_commit)
    closure = _source_closure()
    configuration = dict(frozen_configuration())
    configuration["episode_ids"] = [item.episode_id for item in matrix_specs()]
    document = {
        "schema_version": 1,
        "stage": "FROZEN_BEFORE_OUTCOME",
        "self_authorizes_claims": False,
        "study_type": "PREREGISTERED_REPLICATION_INFORMED_BY_EXP13",
        "causal_lowest_claim": False,
        "source_commit": source_commit,
        "source_audit_approval": approval,
        "source_audit_approval_sha256": approval_sha256,
        "source_closure": closure,
        "source_closure_sha256": sha256_bytes(canonical_bytes(closure)),
        "configuration": configuration,
        "configuration_sha256": sha256_bytes(canonical_bytes(configuration)),
        "environment": _evidence.current_environment(),
    }
    document["environment_sha256"] = sha256_bytes(canonical_bytes(document["environment"]))
    output.mkdir(parents=True)
    payload = canonical_bytes(document)
    _write(output / "freeze.json", payload)
    if tracked_path is not None:
        _write(tracked_path, payload)
    return document


def _episode_manifest(output: Path, raw: object) -> dict[str, object]:
    destination = output / "raw/episodes" / raw.spec.episode_id
    payloads = _evidence.episode_payloads(raw)
    for name, payload in sorted(payloads.items()):
        _write(destination / name, payload)
    manifest = {
        "schema_version": 1,
        "episode_id": raw.spec.episode_id,
        "seed": raw.spec.seed,
        "injection_tick": raw.realization.injection_tick,
        "files": _evidence._inventory(payloads),
    }
    payload = canonical_bytes(manifest)
    _write(destination / "manifest.json", payload)
    return {"manifest_sha256": sha256_bytes(payload)}


def _validate_freeze(output: Path) -> dict[str, object]:
    payload = (output / "freeze.json").read_bytes()
    document = json.loads(payload.decode("ascii"))
    if canonical_bytes(document) != payload:
        raise RuntimeError("Exp15 freeze is not canonical")
    closure = _source_closure()
    if document["source_closure"] != closure or document["source_closure_sha256"] != sha256_bytes(canonical_bytes(closure)):
        raise RuntimeError("Exp15 source closure drift")
    if document["configuration"]["episode_ids"] != [item.episode_id for item in matrix_specs()]:
        raise RuntimeError("Exp15 matrix drift")
    return document


def _preflight_file_record(path: Path, root: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
    }


def preflight(output: Path) -> dict[str, object]:
    """Precheck and seal every matrix identity before any outcome can execute."""
    freeze_document = _validate_freeze(output)
    freeze_sha256 = sha256_bytes((output / "freeze.json").read_bytes())
    index_path = output / "preflight/preflight-index.json"
    if index_path.is_file():
        return _validate_preflight(output)
    if (output / "raw/dispositions").exists():
        raise RuntimeError("Exp15 full-matrix preflight must precede every outcome")
    receipt_root = output / "preflight/receipts"
    for spec in matrix_specs():
        path = receipt_root / f"{spec.episode_id}.json"
        if path.is_file():
            continue
        try:
            realization, receipt = _cell_precheck(spec)
            payload = {
                "schema_version": 1,
                "episode_id": spec.episode_id,
                "disposition": receipt.disposition,
                "parameter_sha256": realization.parameter_sha256,
                "receipt": _receipt_payload(receipt),
            }
        except Exception as error:
            payload = {
                "schema_version": 1,
                "episode_id": spec.episode_id,
                "disposition": "INVALID_PREFLIGHT",
                "parameter_sha256": None,
                "exception_class": type(error).__name__,
                "exception_message": str(error),
            }
        _write(path, canonical_bytes(payload))
    paths = sorted(receipt_root.glob("*.json"))
    expected = {item.episode_id for item in matrix_specs()}
    if len(paths) != 540 or {item.stem for item in paths} != expected:
        raise RuntimeError("Exp15 full-matrix preflight identity mismatch")
    rows = [json.loads(path.read_text(encoding="ascii")) for path in paths]
    counts = {
        name: sum(row["disposition"] == name for row in rows)
        for name in ("READY", "NOT_RUN", "INVALID_PREFLIGHT")
    }
    document = {
        "schema_version": 1,
        "stage": "FULL_MATRIX_PREFLIGHT_COMPLETE_BEFORE_OUTCOME",
        "source_commit": freeze_document["source_commit"],
        "freeze_sha256": freeze_sha256,
        "total": 540,
        **counts,
        "files": [_preflight_file_record(path, output / "preflight") for path in paths],
    }
    _write(index_path, canonical_bytes(document))
    return _validate_preflight(output)


def _validate_preflight(output: Path) -> dict[str, object]:
    index_path = output / "preflight/preflight-index.json"
    if not index_path.is_file():
        raise RuntimeError("Exp15 full-matrix preflight is required before outcomes")
    payload = index_path.read_bytes()
    document = json.loads(payload.decode("ascii"))
    exact_keys = {
        "schema_version", "stage", "source_commit", "freeze_sha256", "total",
        "READY", "NOT_RUN", "INVALID_PREFLIGHT", "files",
    }
    if canonical_bytes(document) != payload or set(document) != exact_keys:
        raise RuntimeError("Exp15 preflight index schema mismatch")
    freeze = _validate_freeze(output)
    freeze_sha256 = sha256_bytes((output / "freeze.json").read_bytes())
    if (
        document["schema_version"] != 1
        or document["stage"] != "FULL_MATRIX_PREFLIGHT_COMPLETE_BEFORE_OUTCOME"
        or document["source_commit"] != freeze["source_commit"]
        or document["freeze_sha256"] != freeze_sha256
        or document["total"] != 540
    ):
        raise RuntimeError("Exp15 preflight freeze binding mismatch")
    expected_ids = {item.episode_id for item in matrix_specs()}
    paths = sorted((output / "preflight/receipts").glob("*.json"))
    if len(paths) != 540 or {path.stem for path in paths} != expected_ids:
        raise RuntimeError("Exp15 preflight receipt identity mismatch")
    actual_files = [_preflight_file_record(path, output / "preflight") for path in paths]
    if document["files"] != actual_files:
        raise RuntimeError("Exp15 preflight receipt inventory mismatch")
    rows = []
    for path in paths:
        row_payload = path.read_bytes()
        row = json.loads(row_payload.decode("ascii"))
        if canonical_bytes(row) != row_payload or row.get("episode_id") != path.stem:
            raise RuntimeError("Exp15 preflight receipt is not canonical")
        if row.get("disposition") not in {"READY", "NOT_RUN", "INVALID_PREFLIGHT"}:
            raise RuntimeError("Exp15 preflight disposition mismatch")
        rows.append(row)
    for name in ("READY", "NOT_RUN", "INVALID_PREFLIGHT"):
        if document[name] != sum(row["disposition"] == name for row in rows):
            raise RuntimeError("Exp15 preflight count mismatch")
    if sum(document[name] for name in ("READY", "NOT_RUN", "INVALID_PREFLIGHT")) != 540:
        raise RuntimeError("Exp15 preflight total mismatch")
    return document


def _disposition_inventory(output: Path, *, limit: int | None = None) -> list[dict[str, object]]:
    root = output / "raw/dispositions"
    inventory = []
    paths = sorted(root.glob("*.json"))
    if limit is not None:
        paths = paths[:limit]
    for path in paths:
        payload = path.read_bytes()
        inventory.append({
            "path": path.name,
            "bytes": len(payload),
            "sha256": sha256_bytes(payload),
        })
    return inventory


def disposition_inventory_sha256(output: Path, *, limit: int | None = None) -> str:
    return sha256_bytes(canonical_bytes(_disposition_inventory(output, limit=limit)))


def release_first50(output: Path, approval_path: Path) -> dict[str, object]:
    _validate_freeze(output)
    _validate_preflight(output)
    dispositions = sorted((output / "raw/dispositions").glob("*.json"))
    if len(dispositions) != 50:
        raise RuntimeError("Exp15 V2 first-50 release requires exactly 50 sealed dispositions")
    payload = approval_path.read_bytes()
    approval = json.loads(payload.decode("ascii"))
    expected = {
        "schema_version", "experiment_id", "verdict", "review_scope", "reviewer",
        "freeze_sha256", "disposition_count", "disposition_inventory_sha256",
    }
    freeze_sha256 = sha256_bytes((output / "freeze.json").read_bytes())
    if (
        canonical_bytes(approval) != payload
        or set(approval) != expected
        or approval["schema_version"] != 1
        or approval["experiment_id"] != EXPERIMENT_ID
        or approval["verdict"] != "APPROVE"
        or approval["review_scope"] != "FIRST_50_CONTINUATION"
        or not approval["reviewer"]
        or approval["freeze_sha256"] != freeze_sha256
        or approval["disposition_count"] != 50
        or approval["disposition_inventory_sha256"] != disposition_inventory_sha256(output)
    ):
        raise RuntimeError("Exp15 V2 first-50 approval mismatch")
    release = {
        **approval,
        "approval_sha256": sha256_bytes(payload),
        "stage": "FIRST_50_INDEPENDENT_RELEASE",
    }
    path = output / "first50-release.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="ascii"))
        if existing != release:
            raise RuntimeError("Exp15 V2 first-50 release already differs")
    else:
        _write(path, canonical_bytes(release))
    return release


def _validate_first50_release(output: Path) -> None:
    dispositions = sorted((output / "raw/dispositions").glob("*.json"))
    if len(dispositions) < 50:
        return
    path = output / "first50-release.json"
    if not path.is_file():
        raise RuntimeError("Exp15 V2 paused at first 50; independent continuation approval required")
    payload = path.read_bytes()
    release = json.loads(payload.decode("ascii"))
    expected = {
        "schema_version", "experiment_id", "verdict", "review_scope", "reviewer",
        "freeze_sha256", "disposition_count", "disposition_inventory_sha256",
        "approval_sha256", "stage",
    }
    approval_payload = {key: value for key, value in release.items() if key not in {"approval_sha256", "stage"}}
    first50_ids = [path.stem for path in dispositions[:50]]
    if (
        canonical_bytes(release) != payload
        or set(release) != expected
        or release["schema_version"] != 1
        or release["experiment_id"] != EXPERIMENT_ID
        or release["verdict"] != "APPROVE"
        or release["review_scope"] != "FIRST_50_CONTINUATION"
        or not release["reviewer"]
        or release["stage"] != "FIRST_50_INDEPENDENT_RELEASE"
        or release["freeze_sha256"] != sha256_bytes((output / "freeze.json").read_bytes())
        or release["disposition_count"] != 50
        or first50_ids != [spec.episode_id for spec in matrix_specs()[:50]]
        or release["disposition_inventory_sha256"] != disposition_inventory_sha256(output, limit=50)
        or release["approval_sha256"] != sha256_bytes(canonical_bytes(approval_payload))
    ):
        raise RuntimeError("Exp15 V2 first-50 release state mismatch")


def execute(output: Path, *, limit: int | None = None) -> dict[str, int]:
    freeze_document = _validate_freeze(output)
    _validate_preflight(output)
    freeze_sha256 = sha256_bytes((output / "freeze.json").read_bytes())
    disposition_root = output / "raw/dispositions"
    completed_before = len(list(disposition_root.glob("*.json"))) if disposition_root.exists() else 0
    _validate_first50_release(output)
    allowance = len(matrix_specs()) if limit is None else int(limit)
    if not (output / "first50-release.json").is_file():
        allowance = min(allowance, 50 - completed_before)
    written = 0
    for spec in matrix_specs():
        path = disposition_root / f"{spec.episode_id}.json"
        if path.is_file():
            continue
        if written >= allowance:
            break
        preflight_path = output / "preflight/receipts" / f"{spec.episode_id}.json"
        preflight_row = json.loads(preflight_path.read_text(encoding="ascii"))
        realization = None
        if preflight_row["disposition"] == "INVALID_PREFLIGHT":
            error = RuntimeError(
                f"{preflight_row['exception_class']}: {preflight_row['exception_message']}"
            )
            _write(path, canonical_bytes(_invalid_execution_row(
                spec, error, stage="PRECHECK", source_commit=freeze_document["source_commit"],
                freeze_sha256=freeze_sha256,
            )))
            written += 1
            continue
        try:
            realization, receipt = _cell_precheck(spec)
        except Exception as error:
            _write(path, canonical_bytes(_invalid_execution_row(
                spec, error, stage="PRECHECK", source_commit=freeze_document["source_commit"],
                freeze_sha256=freeze_sha256, realization=realization,
            )))
            written += 1
            continue
        observed_preflight = {
            "schema_version": 1,
            "episode_id": spec.episode_id,
            "disposition": receipt.disposition,
            "parameter_sha256": realization.parameter_sha256,
            "receipt": _receipt_payload(receipt),
        }
        if canonical_bytes(observed_preflight) != canonical_bytes(preflight_row):
            error = RuntimeError("Exp15 cell precheck drifted from sealed full-matrix preflight")
            _write(path, canonical_bytes(_invalid_execution_row(
                spec, error, stage="PRECHECK", source_commit=freeze_document["source_commit"],
                freeze_sha256=freeze_sha256, realization=realization,
            )))
            written += 1
            continue
        if receipt.disposition == "NOT_RUN":
            if not receipt.architecture_independent:
                error = RuntimeError("Exp15 NOT_RUN precheck must be architecture-independent")
                _write(path, canonical_bytes(_invalid_execution_row(
                    spec, error, stage="PRECHECK", source_commit=freeze_document["source_commit"],
                    freeze_sha256=freeze_sha256, realization=realization,
                )))
                written += 1
                continue
            _write(path, canonical_bytes(_not_run_row(spec, realization, receipt)))
            written += 1
            continue
        if receipt.disposition != "READY":
            error = RuntimeError(f"Exp15 unknown precheck disposition: {receipt.disposition}")
            _write(path, canonical_bytes(_invalid_execution_row(
                spec, error, stage="PRECHECK", source_commit=freeze_document["source_commit"],
                freeze_sha256=freeze_sha256, realization=realization,
            )))
            written += 1
            continue
        try:
            raw = run_cell(spec, realization=realization, receipt=receipt)
        except Exception as error:
            _write(path, canonical_bytes(_invalid_execution_row(
                spec, error, stage="RUNTIME", source_commit=freeze_document["source_commit"],
                freeze_sha256=freeze_sha256, realization=realization,
            )))
            written += 1
            continue
        try:
            score = score_cell(raw)
        except Exception as error:
            _write(path, canonical_bytes(_invalid_execution_row(
                spec, error, stage="SCORER", source_commit=freeze_document["source_commit"],
                freeze_sha256=freeze_sha256, realization=realization,
            )))
            written += 1
            continue
        try:
            manifest = _episode_manifest(output, raw)
        except Exception as error:
            _write(path, canonical_bytes(_invalid_execution_row(
                spec, error, stage="EVIDENCE", source_commit=freeze_document["source_commit"],
                freeze_sha256=freeze_sha256, realization=realization,
            )))
            written += 1
            continue
        row = {
            **score,
            "disposition": "COMPLETE",
            "parameter_sha256": raw.realization.parameter_sha256,
            "episode_manifest_sha256": manifest["manifest_sha256"],
        }
        _write(path, canonical_bytes(row))
        written += 1
    completed = completed_before + written
    result = {"completed": completed, "remaining": 540 - completed, "total": 540}
    if completed == 50 and not (output / "first50-release.json").is_file():
        result["paused_for_first50_review"] = True
    return result


def frozen_configuration() -> Mapping[str, object]:
    return MappingProxyType({
        "experiment_id": EXPERIMENT_ID,
        "primary_seeds": PRIMARY_SEEDS,
        "sensitivity_seeds": SENSITIVITY_SEEDS,
        "families": FAMILIES,
        "severities": SEVERITIES,
        "primary_cells": 480,
        "sensitivity_cells": 60,
        "total_cells": 540,
        "bootstrap_draws": 10_000,
        "fixed_best_simpler_comparator": "R2",
        "causal_claims": False,
    })


__all__ = [
    "DirectRealization", "DirectSpec", "EXPERIMENT_ID", "FAMILIES", "OUTCOME_ROW_FIELDS",
    "PRIMARY_SEEDS", "SENSITIVITY_SEEDS", "SEVERITIES", "frozen_configuration",
    "disposition_inventory_sha256", "execute", "freeze", "make_realization", "matrix_specs",
    "preflight", "release_first50", "run_cell", "score_cell",
]
