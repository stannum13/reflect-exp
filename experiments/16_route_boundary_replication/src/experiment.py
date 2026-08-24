"""Frozen direct-outcome matrix over the production hierarchy runtime."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import subprocess
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


EXPERIMENT_ID = "exp16-route-boundary-replication-v1"
SOURCE_APPROVAL_PATH = "experiments/16_route_boundary_replication/EXP16_V1_SOURCE_AUDIT_APPROVAL.json"
FIRST50_APPROVAL_PATH = "experiments/16_route_boundary_replication/EXP16_V1_FIRST50_APPROVAL.json"
PRIMARY_SEEDS = tuple(range(20262401, 20262411))
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
COMPLETE_DISPOSITION_KEYS = set(OUTCOME_ROW_FIELDS) | {
    "disposition", "parameter_sha256", "episode_manifest_sha256",
}
NOT_RUN_DISPOSITION_KEYS = {
    "architecture", "architecture_independent", "controller_id", "disposition",
    "episode_id", "family", "matrix_role", "parameter_sha256",
    "precheck_receipt", "precheck_receipt_sha256", "seed", "severity",
}
INVALID_DISPOSITION_KEYS = {
    "architecture", "controller_id", "disposition", "episode_id",
    "exception_class", "exception_message", "execution_stage", "family",
    "freeze_sha256", "matrix_role", "parameter_sha256", "seed", "severity",
    "source_commit",
}


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
        return f"exp16v1-{controller}-{self.architecture.value}-{self.family}-{self.severity.lower()}-{self.seed}"


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
        raise RuntimeError("Exp16 frozen matrix identity error")
    return specs


def make_realization(spec: DirectSpec) -> DirectRealization:
    if spec.family not in FAMILIES or spec.severity not in SEVERITIES:
        raise ValueError("Exp16 family/severity outside freeze")
    if spec.seed not in PRIMARY_SEEDS:
        raise ValueError("Exp16 seed outside freeze")
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
        _root() / "experiments/16_route_boundary_replication/__init__.py",
        _root() / "experiments/16_route_boundary_replication/src/__init__.py",
        _root() / "experiments/16_route_boundary_replication/run.py",
        _root() / "experiments/16_route_boundary_replication/analyze.py",
        _root() / "experiments/16_route_boundary_replication/src/analysis.py",
        _root() / "experiments/16_route_boundary_replication/src/compact_evidence.py",
        _root() / "experiments/16_route_boundary_replication/tests/__init__.py",
        _root() / "experiments/16_route_boundary_replication/tests/test_experiment.py",
        _root() / "experiments/16_route_boundary_replication/tests/test_compact_evidence.py",
        _root() / "docs/superpowers/specs/2026-08-24-exp16-route-boundary-replication.md",
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


def _load_git_approval(approval_ref: str | None, expected_path: str) -> tuple[dict[str, object], bytes, str, str]:
    if approval_ref is None or ":" not in approval_ref:
        raise RuntimeError("Exp16 V1 independent approval Git ref is required")
    commit, path = approval_ref.split(":", 1)
    if (
        len(commit) != 40
        or any(char not in "0123456789abcdef" for char in commit)
        or path != expected_path
    ):
        raise RuntimeError("Exp16 V1 independent approval Git ref mismatch")
    try:
        subprocess.run(
            ("git", "merge-base", "--is-ancestor", commit, "HEAD"), cwd=_root(),
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        ancestry = subprocess.check_output(
            ("git", "rev-list", "--parents", "-n", "1", commit), cwd=_root(), text=True,
        ).strip().split()
        changed = subprocess.check_output(
            ("git", "diff-tree", "--no-commit-id", "--name-only", "-r", f"{commit}^", commit),
            cwd=_root(), text=True,
        ).splitlines()
        payload = subprocess.check_output(("git", "show", approval_ref), cwd=_root())
    except subprocess.CalledProcessError as error:
        raise RuntimeError("Exp16 V1 independent approval Git object unavailable") from error
    if len(ancestry) != 2 or ancestry[0] != commit or changed != [expected_path]:
        raise RuntimeError("Exp16 V1 approval must be a separate one-file Git commit")
    try:
        approval = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Exp16 V1 independent approval encoding mismatch") from error
    if canonical_bytes(approval) != payload:
        raise RuntimeError("Exp16 V1 independent approval is not canonical")
    return approval, payload, commit, ancestry[1]


def _validate_source_approval(approval_ref: str | None, source_commit: str) -> tuple[dict[str, object], str, str, str]:
    if approval_ref is None:
        raise RuntimeError("Exp16 V1 source audit approval is required before freeze")
    approval, payload, approval_commit, approval_parent = _load_git_approval(approval_ref, SOURCE_APPROVAL_PATH)
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
        or approval_parent != source_commit
    ):
        raise RuntimeError("Exp16 V1 source audit approval mismatch")
    return approval, sha256_bytes(payload), approval_ref, approval_commit


def _verify_source_commit_closure(source_commit: str, closure: list[dict[str, object]]) -> None:
    if len(source_commit) != 40 or any(char not in "0123456789abcdef" for char in source_commit):
        raise RuntimeError("Exp16 V1 source commit closure requires a full lowercase commit SHA")
    try:
        subprocess.run(
            ("git", "merge-base", "--is-ancestor", source_commit, "HEAD"),
            cwd=_root(), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError("Exp16 V1 source commit is not an ancestor of current HEAD") from error
    paths = [str(item["path"]) for item in closure]
    if paths != sorted(set(paths)):
        raise RuntimeError("Exp16 V1 source commit closure path set is not exact")
    try:
        tree_paths = set(subprocess.check_output(
            ("git", "ls-tree", "-r", "--name-only", source_commit),
            cwd=_root(), text=True,
        ).splitlines())
    except subprocess.CalledProcessError as error:
        raise RuntimeError("Exp16 V1 source commit tree is unavailable") from error
    if not set(paths) <= tree_paths:
        raise RuntimeError("Exp16 V1 source commit closure contains untracked paths")
    for item in closure:
        path = str(item["path"])
        current = _root() / path
        if current.is_symlink() or not current.is_file():
            raise RuntimeError(f"Exp16 V1 source commit closure path invalid: {path}")
        try:
            committed = subprocess.check_output(
                ("git", "show", f"{source_commit}:{path}"), cwd=_root(),
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(f"Exp16 V1 source commit closure missing path: {path}") from error
        current_payload = current.read_bytes()
        expected = {
            "path": path,
            "bytes": len(committed),
            "sha256": sha256_bytes(committed),
        }
        if item != expected or current_payload != committed:
            raise RuntimeError(f"Exp16 V1 source commit closure drift: {path}")


def freeze(
    output: Path,
    *,
    source_commit: str,
    tracked_path: Path | None = None,
    source_approval_ref: str | None = None,
) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(output)
    if len(source_commit) != 40:
        raise ValueError("Exp16 freeze requires a full source commit")
    approval, approval_sha256, approval_ref, approval_commit = _validate_source_approval(source_approval_ref, source_commit)
    closure = _source_closure()
    _verify_source_commit_closure(source_commit, closure)
    configuration = dict(frozen_configuration())
    configuration["episode_ids"] = [item.episode_id for item in matrix_specs()]
    document = {
        "schema_version": 1,
        "stage": "FROZEN_BEFORE_OUTCOME",
        "self_authorizes_claims": False,
        "study_type": "PREREGISTERED_ROUTE_BOUNDARY_REPLICATION_OF_EXP15",
        "causal_lowest_claim": False,
        "source_commit": source_commit,
        "source_audit_approval": approval,
        "source_audit_approval_sha256": approval_sha256,
        "source_audit_approval_ref": approval_ref,
        "source_audit_approval_commit": approval_commit,
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
    expected_keys = {
        "schema_version", "stage", "self_authorizes_claims", "study_type",
        "causal_lowest_claim", "source_commit", "source_audit_approval",
        "source_audit_approval_sha256", "source_audit_approval_ref",
        "source_audit_approval_commit", "source_closure", "source_closure_sha256",
        "configuration", "configuration_sha256", "environment", "environment_sha256",
    }
    if (
        canonical_bytes(document) != payload
        or set(document) != expected_keys
        or document["schema_version"] != 1
        or document["stage"] != "FROZEN_BEFORE_OUTCOME"
        or document["self_authorizes_claims"] is not False
        or document["causal_lowest_claim"] is not False
        or document["study_type"] != "PREREGISTERED_ROUTE_BOUNDARY_REPLICATION_OF_EXP15"
    ):
        raise RuntimeError("Exp16 freeze schema/canonical mismatch")
    closure = _source_closure()
    if document["source_closure"] != closure or document["source_closure_sha256"] != sha256_bytes(canonical_bytes(closure)):
        raise RuntimeError("Exp16 source closure drift")
    _verify_source_commit_closure(document["source_commit"], closure)
    configuration = dict(frozen_configuration())
    configuration["episode_ids"] = [item.episode_id for item in matrix_specs()]
    configuration = json.loads(canonical_bytes(configuration).decode("ascii"))
    if (
        document["configuration"] != configuration
        or document["configuration_sha256"] != sha256_bytes(canonical_bytes(configuration))
    ):
        raise RuntimeError("Exp16 matrix drift")
    if document["environment_sha256"] != sha256_bytes(canonical_bytes(document["environment"])):
        raise RuntimeError("Exp16 environment binding mismatch")
    approval, approval_sha256, approval_ref, approval_commit = _validate_source_approval(
        document["source_audit_approval_ref"], document["source_commit"],
    )
    if (
        document["source_audit_approval"] != approval
        or document["source_audit_approval_sha256"] != approval_sha256
        or document["source_audit_approval_ref"] != approval_ref
        or document["source_audit_approval_commit"] != approval_commit
        or approval["source_commit"] != document["source_commit"]
    ):
        raise RuntimeError("Exp16 freeze source approval binding mismatch")
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
        raise RuntimeError("Exp16 full-matrix preflight must precede every outcome")
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
        raise RuntimeError("Exp16 full-matrix preflight identity mismatch")
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
        raise RuntimeError("Exp16 full-matrix preflight is required before outcomes")
    payload = index_path.read_bytes()
    document = json.loads(payload.decode("ascii"))
    exact_keys = {
        "schema_version", "stage", "source_commit", "freeze_sha256", "total",
        "READY", "NOT_RUN", "INVALID_PREFLIGHT", "files",
    }
    if canonical_bytes(document) != payload or set(document) != exact_keys:
        raise RuntimeError("Exp16 preflight index schema mismatch")
    freeze = _validate_freeze(output)
    freeze_sha256 = sha256_bytes((output / "freeze.json").read_bytes())
    if (
        document["schema_version"] != 1
        or document["stage"] != "FULL_MATRIX_PREFLIGHT_COMPLETE_BEFORE_OUTCOME"
        or document["source_commit"] != freeze["source_commit"]
        or document["freeze_sha256"] != freeze_sha256
        or document["total"] != 540
    ):
        raise RuntimeError("Exp16 preflight freeze binding mismatch")
    expected_ids = {item.episode_id for item in matrix_specs()}
    paths = sorted((output / "preflight/receipts").glob("*.json"))
    if len(paths) != 540 or {path.stem for path in paths} != expected_ids:
        raise RuntimeError("Exp16 preflight receipt identity mismatch")
    actual_files = [_preflight_file_record(path, output / "preflight") for path in paths]
    if document["files"] != actual_files:
        raise RuntimeError("Exp16 preflight receipt inventory mismatch")
    rows = []
    for path in paths:
        row_payload = path.read_bytes()
        row = json.loads(row_payload.decode("ascii"))
        if canonical_bytes(row) != row_payload or row.get("episode_id") != path.stem:
            raise RuntimeError("Exp16 preflight receipt is not canonical")
        if row.get("disposition") not in {"READY", "NOT_RUN", "INVALID_PREFLIGHT"}:
            raise RuntimeError("Exp16 preflight disposition mismatch")
        rows.append(row)
    for name in ("READY", "NOT_RUN", "INVALID_PREFLIGHT"):
        if document[name] != sum(row["disposition"] == name for row in rows):
            raise RuntimeError("Exp16 preflight count mismatch")
    if sum(document[name] for name in ("READY", "NOT_RUN", "INVALID_PREFLIGHT")) != 540:
        raise RuntimeError("Exp16 preflight total mismatch")
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


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= set("0123456789abcdef")


def _validate_disposition(
    output: Path,
    path: Path,
    spec: DirectSpec,
    freeze_document: dict[str, object],
) -> dict[str, object]:
    payload = path.read_bytes()
    try:
        row = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Exp16 V1 first-50 disposition encoding invalid") from error
    if canonical_bytes(row) != payload or row.get("episode_id") != spec.episode_id or path.stem != spec.episode_id:
        raise RuntimeError("Exp16 V1 first-50 disposition identity/canonical mismatch")
    common = {
        "architecture": spec.architecture.value,
        "family": spec.family,
        "severity": spec.severity,
        "seed": spec.seed,
        "controller_id": spec.controller_id,
        "matrix_role": spec.matrix_role,
    }
    if any(row.get(key) != value for key, value in common.items()):
        raise RuntimeError("Exp16 V1 first-50 disposition matrix binding mismatch")
    disposition = row.get("disposition")
    expected_keys = {
        "COMPLETE": COMPLETE_DISPOSITION_KEYS,
        "NOT_RUN": NOT_RUN_DISPOSITION_KEYS,
        "INVALID_EXECUTION": INVALID_DISPOSITION_KEYS,
    }.get(disposition)
    if expected_keys is None or set(row) != expected_keys:
        raise RuntimeError("Exp16 V1 first-50 disposition schema mismatch")
    episode = output / "raw/episodes" / spec.episode_id
    if disposition == "COMPLETE":
        if not _is_sha256(row["parameter_sha256"]) or not _is_sha256(row["episode_manifest_sha256"]):
            raise RuntimeError("Exp16 V1 COMPLETE hash schema mismatch")
        if row["terminal"] not in {"SUCCESS", "FAILURE"} or not isinstance(row["mission_success"], bool):
            raise RuntimeError("Exp16 V1 COMPLETE terminal schema mismatch")
        if row["mission_success"] != (row["terminal"] == "SUCCESS") or not isinstance(row["safety_composite"], bool):
            raise RuntimeError("Exp16 V1 COMPLETE outcome binding mismatch")
        integer_fields = (
            "retry_count", "control_wakes", "motion_wakes", "semantic_wakes",
            "recovery_latency_ticks", "aborts",
        )
        if any(not isinstance(row[name], int) or isinstance(row[name], bool) or row[name] < 0 for name in integer_fields):
            raise RuntimeError("Exp16 V1 COMPLETE count schema mismatch")
        numeric_fields = (
            "progress", "peak_torque_nm", "rms_torque_nm", "peak_contact_force_n",
            "trajectory_length_rad", "action_cost",
        )
        if any(
            not isinstance(row[name], (int, float))
            or isinstance(row[name], bool)
            or not math.isfinite(float(row[name]))
            for name in numeric_fields
        ):
            raise RuntimeError("Exp16 V1 COMPLETE metric schema mismatch")
        if not 0.0 <= float(row["progress"]) <= 1.0 or any(float(row[name]) < 0 for name in numeric_fields[1:]):
            raise RuntimeError("Exp16 V1 COMPLETE metric range mismatch")
        manifest_path = episode / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise RuntimeError("Exp16 V1 COMPLETE manifest missing")
        manifest_payload = manifest_path.read_bytes()
        manifest = json.loads(manifest_payload.decode("ascii"))
        if (
            canonical_bytes(manifest) != manifest_payload
            or set(manifest) != {"schema_version", "episode_id", "seed", "injection_tick", "files"}
            or manifest["schema_version"] != 1
            or manifest["episode_id"] != spec.episode_id
            or manifest["seed"] != spec.seed
            or not isinstance(manifest["injection_tick"], int)
            or not isinstance(manifest["files"], list)
            or sha256_bytes(manifest_payload) != row["episode_manifest_sha256"]
        ):
            raise RuntimeError("Exp16 V1 COMPLETE manifest binding mismatch")
        actual_files = []
        seen = set()
        for item in manifest["files"]:
            if set(item) != {"path", "bytes", "sha256"} or not isinstance(item["path"], str):
                raise RuntimeError("Exp16 V1 COMPLETE manifest member schema mismatch")
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts or item["path"] in seen:
                raise RuntimeError("Exp16 V1 COMPLETE manifest member path mismatch")
            seen.add(item["path"])
            member = episode / relative
            if member.is_symlink() or not member.is_file():
                raise RuntimeError("Exp16 V1 COMPLETE manifest member missing")
            member_payload = member.read_bytes()
            actual_files.append({
                "path": item["path"], "bytes": len(member_payload),
                "sha256": sha256_bytes(member_payload),
            })
        if manifest["files"] != actual_files or "failure-event-states.jsonl" not in seen:
            raise RuntimeError("Exp16 V1 COMPLETE manifest inventory mismatch")
    elif disposition == "NOT_RUN":
        receipt = row["precheck_receipt"]
        receipt_keys = {
            "disposition", "reason", "architecture_independent", "precheck_input",
            "realization_sha256", "geometry_sha256", "straight_path_blocked",
            "waypoint_path_clear", "target_a_ik_error_m", "target_b_ik_error_m",
        }
        if (
            set(receipt) != receipt_keys
            or receipt["disposition"] != "NOT_RUN"
            or receipt["architecture_independent"] is not True
            or row["architecture_independent"] is not True
            or not _is_sha256(row["parameter_sha256"])
            or not _is_sha256(row["precheck_receipt_sha256"])
            or row["precheck_receipt_sha256"] != sha256_bytes(canonical_bytes(receipt))
            or not _is_sha256(receipt["realization_sha256"])
            or not _is_sha256(receipt["geometry_sha256"])
        ):
            raise RuntimeError("Exp16 V1 NOT_RUN receipt binding mismatch")
        preflight_path = output / "preflight/receipts" / f"{spec.episode_id}.json"
        preflight_payload = preflight_path.read_bytes()
        preflight_row = json.loads(preflight_payload.decode("ascii"))
        if (
            canonical_bytes(preflight_row) != preflight_payload
            or preflight_row.get("disposition") != "NOT_RUN"
            or preflight_row.get("parameter_sha256") != row["parameter_sha256"]
            or preflight_row.get("receipt") != receipt
        ):
            raise RuntimeError("Exp16 V1 NOT_RUN preflight binding mismatch")
        if episode.exists():
            raise RuntimeError("Exp16 V1 NOT_RUN unexpectedly has episode evidence")
    else:
        freeze_sha256 = sha256_bytes((output / "freeze.json").read_bytes())
        if (
            row["source_commit"] != freeze_document["source_commit"]
            or row["freeze_sha256"] != freeze_sha256
            or row["execution_stage"] not in {"PRECHECK", "RUNTIME", "SCORER", "EVIDENCE"}
            or not isinstance(row["exception_class"], str) or not row["exception_class"]
            or not isinstance(row["exception_message"], str)
            or (row["parameter_sha256"] is not None and not _is_sha256(row["parameter_sha256"]))
            or episode.exists()
        ):
            raise RuntimeError("Exp16 V1 INVALID_EXECUTION binding mismatch")
    return row


def _validate_first50_dispositions(output: Path) -> None:
    freeze_document = _validate_freeze(output)
    paths = sorted((output / "raw/dispositions").glob("*.json"))
    specs = matrix_specs()[:50]
    if len(paths) < 50 or [path.stem for path in paths[:50]] != [spec.episode_id for spec in specs]:
        raise RuntimeError("Exp16 V1 first-50 disposition identity mismatch")
    for path, spec in zip(paths[:50], specs, strict=True):
        _validate_disposition(output, path, spec, freeze_document)


def release_first50(output: Path, approval_ref: str) -> dict[str, object]:
    freeze_document = _validate_freeze(output)
    _validate_preflight(output)
    dispositions = sorted((output / "raw/dispositions").glob("*.json"))
    if len(dispositions) != 50:
        raise RuntimeError("Exp16 V1 first-50 release requires exactly 50 sealed dispositions")
    _validate_first50_dispositions(output)
    approval, payload, approval_commit, approval_parent = _load_git_approval(approval_ref, FIRST50_APPROVAL_PATH)
    expected = {
        "schema_version", "experiment_id", "verdict", "review_scope", "reviewer",
        "source_commit", "freeze_sha256", "disposition_count",
        "disposition_inventory_sha256", "approval_parent_commit",
    }
    freeze_sha256 = sha256_bytes((output / "freeze.json").read_bytes())
    if (
        set(approval) != expected
        or approval["schema_version"] != 1
        or approval["experiment_id"] != EXPERIMENT_ID
        or approval["verdict"] != "APPROVE"
        or approval["review_scope"] != "FIRST_50_CONTINUATION"
        or not approval["reviewer"]
        or approval["source_commit"] != freeze_document["source_commit"]
        or approval["freeze_sha256"] != freeze_sha256
        or approval["disposition_count"] != 50
        or approval["disposition_inventory_sha256"] != disposition_inventory_sha256(output)
        or approval["approval_parent_commit"] != approval_parent
    ):
        raise RuntimeError("Exp16 V1 first-50 approval mismatch")
    try:
        subprocess.run(
            ("git", "merge-base", "--is-ancestor", freeze_document["source_commit"], approval_parent),
            cwd=_root(), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError("Exp16 V1 first-50 approval ancestry mismatch") from error
    release = {
        "schema_version": 1,
        "experiment_id": EXPERIMENT_ID,
        "source_commit": freeze_document["source_commit"],
        "freeze_sha256": freeze_sha256,
        "disposition_count": 50,
        "disposition_inventory_sha256": approval["disposition_inventory_sha256"],
        "approval_ref": approval_ref,
        "approval_commit": approval_commit,
        "approval_sha256": sha256_bytes(payload),
        "stage": "FIRST_50_INDEPENDENT_RELEASE",
    }
    path = output / "first50-release.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="ascii"))
        if existing != release:
            raise RuntimeError("Exp16 V1 first-50 release already differs")
    else:
        _write(path, canonical_bytes(release))
    return release


def _validate_first50_release(output: Path) -> None:
    dispositions = sorted((output / "raw/dispositions").glob("*.json"))
    if len(dispositions) < 50:
        return
    path = output / "first50-release.json"
    if not path.is_file():
        raise RuntimeError("Exp16 V1 paused at first 50; independent continuation approval required")
    _validate_first50_dispositions(output)
    payload = path.read_bytes()
    release = json.loads(payload.decode("ascii"))
    expected = {
        "schema_version", "experiment_id", "source_commit", "freeze_sha256",
        "disposition_count", "disposition_inventory_sha256", "approval_ref",
        "approval_commit", "approval_sha256", "stage",
    }
    first50_ids = [path.stem for path in dispositions[:50]]
    freeze_document = _validate_freeze(output)
    try:
        approval, approval_payload, approval_commit, approval_parent = _load_git_approval(
            release.get("approval_ref"), FIRST50_APPROVAL_PATH,
        )
    except RuntimeError as error:
        raise RuntimeError("Exp16 V1 first-50 release state mismatch") from error
    if (
        canonical_bytes(release) != payload
        or set(release) != expected
        or release["schema_version"] != 1
        or release["experiment_id"] != EXPERIMENT_ID
        or release["stage"] != "FIRST_50_INDEPENDENT_RELEASE"
        or release["source_commit"] != freeze_document["source_commit"]
        or release["freeze_sha256"] != sha256_bytes((output / "freeze.json").read_bytes())
        or release["disposition_count"] != 50
        or first50_ids != [spec.episode_id for spec in matrix_specs()[:50]]
        or release["disposition_inventory_sha256"] != disposition_inventory_sha256(output, limit=50)
        or release["approval_commit"] != approval_commit
        or release["approval_sha256"] != sha256_bytes(approval_payload)
        or approval.get("schema_version") != 1
        or approval.get("experiment_id") != EXPERIMENT_ID
        or approval.get("verdict") != "APPROVE"
        or approval.get("review_scope") != "FIRST_50_CONTINUATION"
        or not approval.get("reviewer")
        or approval.get("source_commit") != freeze_document["source_commit"]
        or approval.get("freeze_sha256") != release["freeze_sha256"]
        or approval.get("disposition_count") != 50
        or approval.get("disposition_inventory_sha256") != release["disposition_inventory_sha256"]
        or approval.get("approval_parent_commit") != approval_parent
    ):
        raise RuntimeError("Exp16 V1 first-50 release state mismatch")


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
            error = RuntimeError("Exp16 cell precheck drifted from sealed full-matrix preflight")
            _write(path, canonical_bytes(_invalid_execution_row(
                spec, error, stage="PRECHECK", source_commit=freeze_document["source_commit"],
                freeze_sha256=freeze_sha256, realization=realization,
            )))
            written += 1
            continue
        if receipt.disposition == "NOT_RUN":
            if not receipt.architecture_independent:
                error = RuntimeError("Exp16 NOT_RUN precheck must be architecture-independent")
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
            error = RuntimeError(f"Exp16 unknown precheck disposition: {receipt.disposition}")
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
        "runtime_route_unavailable": "SAFE_ABORT_COMPLETE_SCORED_FAILURE",
    })


__all__ = [
    "DirectRealization", "DirectSpec", "EXPERIMENT_ID", "FAMILIES", "OUTCOME_ROW_FIELDS",
    "PRIMARY_SEEDS", "SENSITIVITY_SEEDS", "SEVERITIES", "frozen_configuration",
    "disposition_inventory_sha256", "execute", "freeze", "make_realization", "matrix_specs",
    "preflight", "release_first50", "run_cell", "score_cell",
]
