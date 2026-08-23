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
from .v3_evidence import _inventory, _write_episode, source_closure
from .v3_runtime import V3EpisodeSpec, precheck, run_episode
from .v3_scorer import score_episode


OUTCOME_ROOT_NAME = "hierarchical-recovery-v3"
APPROVAL_DECISION = "APPROVE_HIERARCHICAL_RECOVERY_V3_OUTCOME_EXECUTION"


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
        "schema_version", "decision", "qualified_source_commit", "source_closure_sha256",
        "qualification_freeze_sha256", "qualification_raw_manifest_sha256",
        "qualification_derived_manifest_sha256", "approval_report_sha256",
    }
    binding = _read_canonical_json(approval_binding)
    if set(binding) != required or binding["schema_version"] != 1 or binding["decision"] != APPROVAL_DECISION:
        raise OutcomeAuthorizationError("approval binding schema or decision is invalid")
    try:
        report_payload = approval_report.read_bytes()
        freeze_payload = (qualification_root / "qualification-freeze.json").read_bytes()
        raw_payload = (qualification_root / "raw/manifest.json").read_bytes()
        derived_payload = (qualification_root / "derived/manifest.json").read_bytes()
        freeze = json.loads(freeze_payload.decode("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OutcomeAuthorizationError("approval qualification/report input is missing or invalid") from exc
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
    if freeze.get("self_authorizes_outcomes") is not False:
        raise OutcomeAuthorizationError("qualification freeze has invalid authorization semantics")
    if freeze.get("source_closure") != source_closure():
        raise OutcomeAuthorizationError("qualified source closure drifted before outcomes")
    return dict(binding)


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
    if output.exists():
        raise FileExistsError(output)
    specs = outcome_specs()
    output.mkdir(parents=True)
    freeze = {
        "schema_version": 1,
        "stage": RunStage.OUTCOME.value,
        "approval": approval,
        "source_closure": source_closure(),
        "source_closure_sha256": sha256_bytes(canonical_bytes(source_closure())),
        "episode_ids": [item.episode_id for item in specs],
    }
    _write(output / "outcome-freeze.json", canonical_bytes(freeze))
    rows: list[dict[str, object]] = []
    for spec in specs:
        receipt = precheck(spec)
        if receipt.disposition == "NOT_RUN":
            rows.append({
                "episode_id": spec.episode_id,
                "architecture": spec.architecture.value,
                "scenario_id": spec.scenario_id,
                "seed": spec.seed,
                "controller_id": spec.controller_id,
                "disposition": "NOT_RUN",
                "terminal": None,
                "unsafe": 0, "forbidden": 0, "collision": 0, "invalid_action": 0,
                "stale": 0, "loop": 0, "reset": 0,
                "precheck_sha256": sha256_bytes(canonical_bytes(receipt)),
            })
            continue
        raw = run_episode(spec)
        score = score_episode(raw)
        episode_manifest = _write_episode(output / "raw", raw)
        counts = score.violation_counts
        rows.append({
            "episode_id": spec.episode_id,
            "architecture": spec.architecture.value,
            "scenario_id": spec.scenario_id,
            "seed": spec.seed,
            "controller_id": spec.controller_id,
            "disposition": "TERMINAL",
            "terminal": score.terminal,
            "unsafe": counts["unsafe"], "forbidden": counts["forbidden"],
            "collision": counts["collision"], "invalid_action": counts["invalid_action"],
            "stale": counts["stale"], "loop": counts["loop"], "reset": counts["reset"],
            "precheck_sha256": sha256_bytes(canonical_bytes(receipt)),
            "episode_manifest_sha256": episode_manifest["manifest_sha256"],
        })
    rows_payload = b"".join(canonical_bytes(item) for item in rows)
    raw_manifest = {
        "schema_version": 1,
        "episode_dispositions": len(rows),
        "files": _inventory({"outcome-rows.jsonl": rows_payload}),
    }
    _write(output / "raw/outcome-rows.jsonl", rows_payload)
    _write(output / "raw/manifest.json", canonical_bytes(raw_manifest))
    decision = _outcome_decision(rows)
    _write(output / "derived/decision.json", canonical_bytes(decision))
    return decision


__all__ = [
    "APPROVAL_DECISION", "OUTCOME_ROOT_NAME", "OutcomeAuthorizationError", "outcome_specs",
    "run_outcomes", "verify_outcome_approval",
]
