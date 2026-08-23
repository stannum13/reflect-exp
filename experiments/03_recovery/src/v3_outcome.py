"""Frozen, reviewer-authorized V3 outcome path.

Importing and planning are side-effect free. Held-out realizations are sampled only
inside :func:`run_outcomes`, after the immutable approval binding is authenticated.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from .v3_contracts import (
    Architecture,
    OUTCOME_SEEDS,
    PRIMARY_CONTROLLER_ID,
    RunStage,
    SCENARIO_IDS,
    SENSITIVITY_CONTROLLER_ID,
    canonical_bytes,
    sha256_bytes,
)
from .v3_evidence import _assert_trees_equal, _freeze_record, _inventory, _write_episode, qualification_specs, source_closure
from .v3_runtime import V3EpisodeSpec, precheck, run_episode
from .v3_scorer import score_episode
from .v3_outcome_analysis import analyze_outcomes


OUTCOME_ROOT_NAME = "hierarchical-recovery-v3"
APPROVAL_DECISION = "APPROVED_FOR_OUTCOME"


class OutcomeAuthorizationError(RuntimeError):
    pass


def outcome_specs() -> tuple[V3EpisodeSpec, ...]:
    specs = [
        V3EpisodeSpec(architecture, scenario, seed, PRIMARY_CONTROLLER_ID, RunStage.OUTCOME)
        for architecture in Architecture
        for scenario in SCENARIO_IDS
        for seed in OUTCOME_SEEDS
    ]
    specs.extend(
        V3EpisodeSpec(Architecture.R3, scenario, seed, SENSITIVITY_CONTROLLER_ID, RunStage.OUTCOME)
        for scenario in SCENARIO_IDS
        for seed in OUTCOME_SEEDS[:5]
    )
    result = tuple(sorted(specs, key=lambda item: item.episode_id))
    if len(result) != 360 or len({item.episode_id for item in result}) != 360:
        raise RuntimeError("frozen V3 outcome matrix identity error")
    return result


def _read_canonical_json(path: Path) -> dict[str, object]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OutcomeAuthorizationError(f"approval input is missing or invalid: {path}") from exc
    if not isinstance(value, dict) or canonical_bytes(value) != payload:
        raise OutcomeAuthorizationError(f"approval input is not canonical: {path}")
    return value


def verify_outcome_approval(
    qualification_root: Path, approval_binding: Path, approval_report: Path
) -> dict[str, object]:
    """Authenticate reviewer approval against the exact qualification and source."""
    required = {
        "schema_version", "qualified_source_commit", "source_closure_sha256",
        "qualification_freeze_sha256", "qualification_raw_manifest_sha256",
        "qualification_derived_manifest_sha256", "approval_report_sha256",
    }
    binding = _read_canonical_json(approval_binding)
    if set(binding) != required or binding["schema_version"] != 1:
        raise OutcomeAuthorizationError("approval binding schema is invalid")
    try:
        report_payload = approval_report.read_bytes()
        report = json.loads(report_payload.decode("ascii"))
        freeze_payload = (qualification_root / "qualification-freeze.json").read_bytes()
        raw_payload = (qualification_root / "raw/manifest.json").read_bytes()
        derived_payload = (qualification_root / "derived/manifest.json").read_bytes()
        freeze = json.loads(freeze_payload.decode("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OutcomeAuthorizationError("approval qualification/report input is missing or invalid") from exc
    report_required = {
        "schema_version", "verdict", "critical_findings", "important_findings",
        "qualified_source_commit", "source_closure_sha256", "qualification_freeze_sha256",
        "qualification_raw_manifest_sha256", "qualification_derived_manifest_sha256",
    }
    if not isinstance(report, dict) or canonical_bytes(report) != report_payload or set(report) != report_required:
        raise OutcomeAuthorizationError("approval report schema is invalid")
    if report["verdict"] != APPROVAL_DECISION:
        raise OutcomeAuthorizationError("reviewer verdict is not APPROVED_FOR_OUTCOME")
    if report["critical_findings"] != [] or report["important_findings"] != []:
        raise OutcomeAuthorizationError("reviewer verdict contains blocking findings")
    actual = {
        "qualified_source_commit": freeze.get("source_commit"),
        "source_closure_sha256": freeze.get("source_closure_sha256"),
        "qualification_freeze_sha256": sha256_bytes(freeze_payload),
        "qualification_raw_manifest_sha256": sha256_bytes(raw_payload),
        "qualification_derived_manifest_sha256": sha256_bytes(derived_payload),
        "approval_report_sha256": sha256_bytes(report_payload),
    }
    if any(binding[key] != value for key, value in actual.items()):
        raise OutcomeAuthorizationError("approval hashes do not bind the current qualification/report")
    for key, value in actual.items():
        if key != "approval_report_sha256" and report[key] != value:
            raise OutcomeAuthorizationError("approval report content does not bind the qualification")
    if freeze.get("self_authorizes_outcomes") is not False:
        raise OutcomeAuthorizationError("qualification freeze has invalid authorization semantics")
    if freeze.get("source_closure") != source_closure():
        raise OutcomeAuthorizationError("qualified source closure drifted before outcomes")
    current = _freeze_record(qualification_specs())
    for key in ("configuration", "configuration_sha256", "environment", "environment_sha256"):
        if freeze.get(key) != current[key]:
            raise OutcomeAuthorizationError(f"qualified {key} drifted before outcomes")
    return {**binding, "reviewer_verdict": str(report["verdict"]), "critical_findings": [], "important_findings": []}


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _outcome_decision(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    inventory_complete = len(rows) == 360 and len({str(item["episode_id"]) for item in rows}) == 360
    safety_closed = all(sum(int(item[metric]) for item in rows) == 0 for metric in (
        "unsafe", "forbidden", "collision", "invalid_action", "stale", "loop", "reset",
    ))
    return {
        "schema_version": 1,
        "authority": "NONCONFIRMATORY_ENGINEERING_SCREEN_ONLY",
        "inventory_complete": inventory_complete,
        "safety_closed": safety_closed,
        "episode_dispositions": len(rows),
        "scientific_result": "PENDING_PREREGISTERED_ANALYSIS" if inventory_complete and safety_closed else "INVALID_EXPERIMENT",
    }


def dry_run_outcomes(*, qualification_root: Path, approval_binding: Path, approval_report: Path) -> dict[str, object]:
    """Authenticate approval and inventory the frozen plan without creating output or sampling."""
    approval = verify_outcome_approval(qualification_root, approval_binding, approval_report)
    specs = outcome_specs()
    return {
        "status": "AUTHORIZED_DRY_RUN",
        "approval_report_sha256": approval["approval_report_sha256"],
        "episode_count": len(specs),
        "episode_ids_sha256": sha256_bytes(canonical_bytes([item.episode_id for item in specs])),
    }


def _counterfactual_sufficient(raw: object) -> bool:
    expected = []
    for observable in raw.observations:
        if not observable.controller_safe:
            continue
        if not observable.semantic_preconditions_valid:
            expected.append("SEMANTIC")
        elif not observable.action_valid or not observable.geometry_feasible:
            expected.append("MOTION")
        elif observable.failure_detected:
            expected.append("CONTROL")
    selected = [item.level.value for item in raw.decisions if item.level.value in {"CONTROL", "MOTION", "SEMANTIC"}]
    return bool(not expected or all(level in selected for level in expected))


def _terminal_row(spec: V3EpisodeSpec, receipt: object, raw: object, episode_manifest: Mapping[str, object]) -> dict[str, object]:
    score = score_episode(raw)
    counts = score.violation_counts
    levels = [item.level.value for item in raw.decisions]
    return {
        "episode_id": spec.episode_id, "architecture": spec.architecture.value,
        "scenario_id": spec.scenario_id, "seed": spec.seed, "controller_id": spec.controller_id,
        "disposition": "TERMINAL", "terminal": score.terminal,
        "unsafe": counts["unsafe"], "forbidden": counts["forbidden"], "collision": counts["collision"],
        "invalid_action": counts["invalid_action"], "stale": counts["stale"], "loop": counts["loop"], "reset": counts["reset"],
        "control_interventions": levels.count("CONTROL"), "motion_interventions": levels.count("MOTION"),
        "semantic_interventions": levels.count("SEMANTIC"), "lowest_sufficient_correct": _counterfactual_sufficient(raw),
        "physical_trace_sha256": sha256_bytes(raw.trace["q"].tobytes()),
        "parameter_use_sha256": sha256_bytes(canonical_bytes(raw.parameter_use_receipt)),
        "precheck_input": receipt.precheck_input, "precheck_receipt": receipt,
        "precheck_sha256": sha256_bytes(canonical_bytes(receipt)),
        "episode_manifest_sha256": episode_manifest["manifest_sha256"],
    }


def run_outcomes(
    output: Path,
    *,
    qualification_root: Path,
    approval_binding: Path,
    approval_report: Path,
) -> dict[str, object]:
    """Execute and seal the exact 360-cell outcome matrix after immutable approval."""
    if output.name != OUTCOME_ROOT_NAME:
        raise OutcomeAuthorizationError("outcome output root name is invalid")
    approval = verify_outcome_approval(qualification_root, approval_binding, approval_report)
    specs = outcome_specs()
    freeze = {
        "schema_version": 1,
        "stage": RunStage.OUTCOME.value,
        "approval": approval,
        "source_closure": source_closure(),
        "source_closure_sha256": sha256_bytes(canonical_bytes(source_closure())),
        "episode_ids": [item.episode_id for item in specs],
    }
    if output.exists():
        if not (output / "outcome-freeze.json").is_file() or (output / "outcome-freeze.json").read_bytes() != canonical_bytes(freeze):
            raise OutcomeAuthorizationError("existing outcome root does not match immutable approval/freeze")
        if (output / "raw/manifest.json").is_file():
            rows = (output / "raw/outcome-rows.jsonl").read_text(encoding="ascii").splitlines()
            return {"status": "SEALED_AWAITING_RECONSTRUCTION", "episode_dispositions": len(rows)}
    else:
        output.mkdir(parents=True)
        _write(output / "outcome-freeze.json", canonical_bytes(freeze))
    disposition_root = output / "raw/dispositions"
    for spec in specs:
        disposition_path = disposition_root / f"{spec.episode_id}.json"
        if disposition_path.is_file():
            continue
        receipt = precheck(spec)
        if receipt.disposition == "NOT_RUN":
            row = {
                "episode_id": spec.episode_id,
                "architecture": spec.architecture.value,
                "scenario_id": spec.scenario_id,
                "seed": spec.seed,
                "controller_id": spec.controller_id,
                "disposition": "NOT_RUN",
                "terminal": None,
                "unsafe": 0, "forbidden": 0, "collision": 0, "invalid_action": 0,
                "stale": 0, "loop": 0, "reset": 0,
                "control_interventions": 0, "motion_interventions": 0, "semantic_interventions": 0,
                "lowest_sufficient_correct": None,
                "physical_trace_sha256": None, "parameter_use_sha256": receipt.realization_sha256,
                "precheck_input": receipt.precheck_input,
                "precheck_receipt": receipt,
                "precheck_sha256": sha256_bytes(canonical_bytes(receipt)),
            }
            _write(disposition_path, canonical_bytes(row))
            continue
        try:
            raw = run_episode(spec)
            episode_manifest = _write_episode(output / "raw", raw)
            row = _terminal_row(spec, receipt, raw, episode_manifest)
            _write(disposition_path, canonical_bytes(row))
        except BaseException as exc:
            interrupted = {
                "episode_id": spec.episode_id, "architecture": spec.architecture.value,
                "scenario_id": spec.scenario_id, "seed": spec.seed, "controller_id": spec.controller_id,
                "disposition": "INTERRUPTED" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "INVALID",
                "error_type": type(exc).__name__, "precheck_input": receipt.precheck_input,
                "precheck_receipt": receipt,
            }
            _write(disposition_path, canonical_bytes(interrupted))
            raise
    rows = [json.loads(path.read_text(encoding="ascii")) for path in sorted(disposition_root.glob("*.json"))]
    rows_payload = b"".join(canonical_bytes(item) for item in rows)
    raw_manifest = {
        "schema_version": 1,
        "episode_dispositions": len(rows),
        "files": _inventory({"outcome-rows.jsonl": rows_payload}),
    }
    _write(output / "raw/outcome-rows.jsonl", rows_payload)
    _write(output / "raw/manifest.json", canonical_bytes(raw_manifest))
    return {"status": "SEALED_AWAITING_RECONSTRUCTION", "episode_dispositions": len(rows)}


def reconstruct_outcomes(
    output: Path, clean: Path, *, qualification_root: Path, approval_binding: Path, approval_report: Path
) -> dict[str, object]:
    """Re-execute immutable raw, compare byte-exactly, then publish all scientific deliverables."""
    if clean.exists() or not (output / "raw/manifest.json").is_file():
        raise FileExistsError(clean)
    replay = clean / OUTCOME_ROOT_NAME
    replay.parent.mkdir(parents=True)
    run_outcomes(
        replay, qualification_root=qualification_root,
        approval_binding=approval_binding, approval_report=approval_report,
    )
    _assert_trees_equal(output / "raw", replay / "raw")
    integrity = {
        "approval": True, "inventory": True, "freeze": True, "cause": True,
        "replay": True, "reconstruction": True,
    }
    decision = analyze_outcomes(output, construct_integrity=integrity)
    analyze_outcomes(replay, construct_integrity=integrity)
    _assert_trees_equal(output / "derived", replay / "derived")
    return {
        "matched": True, "episode_dispositions": 360,
        "raw_manifest_sha256": sha256_bytes((output / "raw/manifest.json").read_bytes()),
        "derived_manifest_sha256": sha256_bytes((output / "derived/manifest.json").read_bytes()),
        "scientific_result": decision["scientific_result"],
    }


__all__ = [
    "APPROVAL_DECISION", "OUTCOME_ROOT_NAME", "OutcomeAuthorizationError", "dry_run_outcomes", "outcome_specs",
    "reconstruct_outcomes", "run_outcomes", "verify_outcome_approval",
]
