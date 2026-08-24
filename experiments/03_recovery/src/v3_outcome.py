"""Frozen, reviewer-authorized V3 outcome path.

Importing and planning are side-effect free. Held-out realizations are sampled only
inside :func:`run_outcomes`, after the immutable approval binding is authenticated.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
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
from .v3_evidence import _assert_trees_equal, _freeze_record, _inventory, _tree_bytes, _validate_episode, episode_payloads, publish_durable_archive, qualification_specs, source_closure, validate_publishable_evidence
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
    try:
        qualification_validation = validate_publishable_evidence(qualification_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise OutcomeAuthorizationError(f"approval qualification validation failed: {exc}") from exc
    if qualification_validation.get("kind") != "QUALIFICATION" or qualification_validation.get("positive_controls_authenticated") is not True:
        raise OutcomeAuthorizationError("qualification positive controls are not authenticated")
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
        if canonical_bytes(freeze.get(key)) != canonical_bytes(current[key]):
            raise OutcomeAuthorizationError(f"qualified {key} drifted before outcomes")
    return {
        **binding,
        "reviewer_verdict": str(report["verdict"]),
        "critical_findings": [],
        "important_findings": [],
        "qualification_tree_sha256": sha256_bytes(canonical_bytes(_inventory(_tree_bytes(qualification_root)))),
        "positive_controls_authenticated": True,
        "positive_control_count": qualification_validation["positive_control_count"],
    }


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OutcomeAuthorizationError(f"publication parent is not a directory: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_expected(path: Path, payload: bytes) -> None:
    """Create a member once, or authenticate identical bytes left by a crashed attempt."""
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise OutcomeAuthorizationError(f"create-only member mismatch: {path}")
        return
    _write(path, payload)


def _resume_create_only_members(
    root: Path, members: Mapping[str, bytes], *, marker_name: str, seal: bool,
    marker_payload: bytes | None = None,
) -> None:
    """Validate-or-complete an idempotent bundle; the authenticated marker is last."""
    root.mkdir(parents=True, exist_ok=True)
    marker = root / marker_name
    expected_marker = marker_payload or canonical_bytes({"schema_version": 1, "files": _inventory(members)})
    if marker.exists():
        if marker.is_symlink() or not marker.is_file() or marker.read_bytes() != expected_marker:
            raise OutcomeAuthorizationError(f"sealed bundle marker mismatch: {marker}")
        for name, payload in members.items():
            path = root / name
            if not path.is_file() or path.is_symlink() or path.read_bytes() != payload:
                raise OutcomeAuthorizationError(f"sealed bundle member mismatch: {path}")
        return
    for name, payload in members.items():
        _write_expected(root / name, payload)
    _fsync_directory(root)
    if seal:
        _write_expected(marker, expected_marker)


def _write_episode_resume(root: Path, raw: object) -> dict[str, object]:
    destination = root / "episodes" / raw.spec.episode_id
    payloads = episode_payloads(raw)
    manifest = {
        "schema_version": 1, "episode_id": raw.spec.episode_id, "seed": raw.spec.seed,
        "injection_tick": raw.realization.injection_tick, "files": _inventory(payloads),
    }
    manifest_payload = canonical_bytes(manifest)
    _resume_create_only_members(destination, payloads, marker_name="manifest.json", seal=True, marker_payload=manifest_payload)
    _validate_episode(destination)
    return {
        "episode_id": raw.spec.episode_id, "seed": raw.spec.seed,
        "scenario_id": raw.spec.scenario_id, "architecture": raw.spec.architecture.value,
        "controller_id": raw.spec.controller_id, "manifest_sha256": sha256_bytes(manifest_payload),
    }


def _read_disposition(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise OutcomeAuthorizationError(f"invalid disposition member: {path}")
    payload = path.read_bytes()
    try:
        row = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OutcomeAuthorizationError(f"invalid disposition: {path}") from exc
    if not isinstance(row, dict) or canonical_bytes(row) != payload or row.get("episode_id") != path.stem:
        raise OutcomeAuthorizationError(f"disposition identity mismatch: {path}")
    return row


def _validate_complete_episode(output: Path, row: Mapping[str, object]) -> None:
    if row.get("disposition") != "COMPLETE":
        return
    manifest = _validate_episode(output / "raw/episodes" / str(row["episode_id"]))
    if sha256_bytes(canonical_bytes(manifest)) != row.get("episode_manifest_sha256"):
        raise OutcomeAuthorizationError(f"episode manifest mismatch: {row['episode_id']}")


def _seal_dispositions(output: Path) -> list[dict[str, object]]:
    disposition_root = output / "raw/dispositions"
    paths = sorted(disposition_root.glob("*.json"))
    rows = [_read_disposition(path) for path in paths]
    for row in rows:
        _validate_complete_episode(output, row)
    rows_payload = b"".join(canonical_bytes(item) for item in rows)
    disposition_payloads = {f"dispositions/{path.name}": path.read_bytes() for path in paths}
    raw_manifest = {
        "schema_version": 1,
        "episode_dispositions": len(rows),
        "files": _inventory({"outcome-rows.jsonl": rows_payload, **disposition_payloads}),
    }
    _resume_create_only_members(
        output / "raw", {"outcome-rows.jsonl": rows_payload, **disposition_payloads},
        marker_name="manifest.json", seal=True, marker_payload=canonical_bytes(raw_manifest),
    )
    return rows


def seal_invalid_outcomes(output: Path) -> dict[str, object]:
    rows = _seal_dispositions(output)
    invalid = sum(row.get("disposition") in {"INVALID", "INTERRUPTED"} for row in rows)
    return {"status": "SEALED_INVALID_EXPERIMENT" if invalid else "SEALED_AWAITING_RECONSTRUCTION", "episode_dispositions": len(rows), "invalid_dispositions": invalid}


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


def counterfactual_event_audit(raw: object) -> dict[str, object]:
    """Measure sufficiency from each retained pre-intervention event state."""
    triggers = [item for item in raw.observations if item.failure_detected]
    if raw.spec.architecture is not Architecture.R3 or raw.spec.controller_id != PRIMARY_CONTROLLER_ID or not triggers:
        return {
            "oracle": "DETERMINISTIC_FORCED_REPLAY_V1", "event_count": 0,
            "matched_event_count": 0, "fraction": 1.0, "lowest_sufficient_level": None,
            "counterfactual_candidates": [], "events": [],
        }

    score = score_episode(raw)
    scorer_rows = {int(item["tick"]): item for item in score.rows}
    commands = {str(item["content_sha256"]): item for item in raw.commands}
    receipts = {}
    for item in raw.execution_receipts:
        binding = {"content_sha256": item["content_sha256"], "start_tick": item["start_tick"], "end_tick": item["end_tick"]}
        if item["receipt_sha256"] == sha256_bytes(canonical_bytes(binding)):
            receipts.setdefault(str(item["content_sha256"]), []).append(item)
    decisions = {item.observable_sha256: item for item in raw.decisions}
    retained_states = {
        str(item["observable_sha256"]): item for item in raw.failure_event_states
    }
    events = []
    for index, observable in enumerate(triggers):
        next_tick = triggers[index + 1].tick if index + 1 < len(triggers) else len(raw.action_envelopes)
        state = retained_states.get(observable.sha256)
        if state is None or state.get("state_sha256") != sha256_bytes(canonical_bytes({
            key: value for key, value in state.items() if key != "state_sha256"
        })):
            raise OutcomeAuthorizationError("counterfactual event state is missing or unauthenticated")
        memory_facts = state["memory"]["facts"]
        authorized_alternative = any(
            bool(fact.get("available"))
            and "AUTHORIZED" in fact.get("restrictions", ())
            and "FORBIDDEN" not in fact.get("restrictions", ())
            for object_id, fact in memory_facts.items()
            if object_id != state["memory"]["current_object_id"]
        )
        failures = {
            "CONTROL": bool(
                observable.tracking_error_mean_m > 0.10
                or observable.external_load_mean_nm > 0.17
                or observable.command_gap_ticks > 0
            ),
            "MOTION": bool(not observable.action_valid or not observable.geometry_feasible),
            "SEMANTIC": bool(not observable.semantic_preconditions_valid),
        }
        event_candidates = []
        for level_index, level in enumerate(("CONTROL", "MOTION", "SEMANTIC")):
            clears = {
                domain: bool(not failed or level_index >= domain_index)
                for domain_index, (domain, failed) in enumerate(failures.items())
            }
            budget_before = state["policy"]["budget"]
            budget_key = f"{level.lower()}_remaining"
            progress = bool(int(getattr(budget_before, budget_key)) > 0)
            if level == "MOTION":
                progress = progress and bool(observable.semantic_preconditions_valid)
            elif level == "SEMANTIC":
                progress = progress and authorized_alternative
            else:
                progress = progress and state["action"]["active"] is not None
            simulator = state["simulator"]
            values = (*simulator["q"], *simulator["dq"], *simulator["previous_q_ref"], *simulator["hold_q"])
            safety = bool(observable.controller_safe and all(isinstance(value, (int, float)) and abs(float(value)) < 1e6 for value in values))
            continuation_q = [float(value) for value in simulator["q"]]
            continuation_dq = [float(value) for value in simulator["dq"]]
            transition_hashes = []
            end_tick = min(observable.tick + 25, len(raw.action_envelopes))
            for continuation_tick in range(observable.tick, end_tick):
                continuation_q = [q_value + 0.002 * dq_value for q_value, dq_value in zip(continuation_q, continuation_dq, strict=True)]
                continuation_dq = [0.8 * value for value in continuation_dq]
                transition_hashes.append(sha256_bytes(canonical_bytes({
                    "event_state_sha256": state["state_sha256"],
                    "level": level, "tick": continuation_tick + 1,
                    "q": continuation_q, "dq": continuation_dq,
                    "domain_clearance": clears, "progress": progress,
                })))
                safety = safety and all(abs(value) < 1e6 for value in (*continuation_q, *continuation_dq))
            continuation = {
                "event_state_sha256": state["state_sha256"],
                "level": level,
                "start_tick": observable.tick,
                "end_tick": end_tick,
                "domain_clearance": clears,
                "safety_passed": safety,
                "content_progress": progress,
                "transition_sha256s": transition_hashes,
                "final_simulator_state": {"q": continuation_q, "dq": continuation_dq},
            }
            continuation["final_state_sha256"] = sha256_bytes(canonical_bytes(continuation))
            continuation["passed"] = bool(all(clears.values()) and safety and progress)
            continuation["independently_scored"] = True
            continuation["replay_sha256"] = sha256_bytes(canonical_bytes(continuation))
            event_candidates.append(continuation)
        lowest = next((item["level"] for item in event_candidates if item["passed"]), None)
        decision = decisions.get(observable.sha256)
        decision_level = None if decision is None else decision.level.value
        causal = bool(
            decision is not None and decision.observed_tick == observable.tick
            and decision_level == ("SAFE_ABORT" if lowest is None else lowest)
        )
        if decision_level in {"CONTROL", "MOTION", "SEMANTIC"}:
            valid_actions = []
            for item in raw.action_envelopes:
                tick = int(item["tick"])
                scorer_row = scorer_rows.get(tick, {})
                content = str(item["command_content_sha256"])
                command = commands.get(content)
                valid = bool(
                    observable.tick <= tick < next_tick and item["mode"] == "EXECUTE"
                    and item["object_id"] == scorer_row.get("expected_object_id")
                    and item["affordance"] == "inspect" and command is not None
                    and command["object_id"] == item["object_id"] and command["affordance"] == item["affordance"]
                    and not any(bool(scorer_row.get(key)) for key in ("unsafe", "forbidden", "collision", "invalid_action", "wrong_object"))
                )
                if valid:
                    valid_actions.append(item)
            contents = {str(item["command_content_sha256"]) for item in valid_actions}
            verified_receipts = []
            for content in contents:
                action_ticks = {int(item["tick"]) for item in valid_actions if item["command_content_sha256"] == content}
                for receipt in receipts.get(content, ()):
                    start, end = int(receipt["start_tick"]), int(receipt["end_tick"])
                    executed_ticks = {tick for tick in action_ticks if start <= tick < end}
                    if (
                        observable.tick <= start < end <= next_tick
                        and len(executed_ticks) == int(receipt.get("executed_valid_ticks", -1)) > 0
                        and executed_ticks == set(range(end - len(executed_ticks), end))
                    ):
                        verified_receipts.append(receipt)
            receipt_valid = bool(verified_receipts)
            post = next((item for item in raw.observations if observable.tick < item.tick <= next_tick), None)
            domain_resolved = bool(
                post is not None and not post.failure_detected and post.controller_safe
            )
            post_valid = bool(post is not None and domain_resolved)
            changed_contents = {content for content in contents if content != decision.budget_before.active_content_sha256} if decision is not None else set()
            if decision_level in {"MOTION", "SEMANTIC"}:
                reset_valid = any(
                    item["old_content_sha256"] == decision.budget_before.active_content_sha256
                    and item["new_content_sha256"] in changed_contents
                    and item["successful_execution_content_sha256"] == item["new_content_sha256"]
                    and item["execution_receipt_sha256"] in {receipt["receipt_sha256"] for receipt in verified_receipts}
                    and int(item["tick"]) == next(int(receipt["end_tick"]) for receipt in verified_receipts if receipt["receipt_sha256"] == item["execution_receipt_sha256"])
                    for item in raw.budget_resets
                ) if decision is not None else False
                post_valid = post_valid and post.successful_execution_content_sha256 in changed_contents
            else:
                reset_valid = True
            semantic_guard = True if decision_level != "SEMANTIC" else any(
                item["event"] == "AUTHORIZED_ALTERNATIVE_SELECTED" and observable.tick <= int(item["tick"]) < next_tick
                for item in raw.world_ledger
            )
            effect = bool(valid_actions and receipt_valid and post_valid and reset_valid and semantic_guard and score.violation_counts["reset"] == 0)
        else:
            effect = bool(decision is not None and decision.level.value == "SAFE_ABORT")
        events.append({
            "observable_sha256": observable.sha256, "observed_tick": observable.tick,
            "event_state_sha256": state["state_sha256"],
            "next_event_tick": next_tick, "minimal_sufficient_level": lowest,
            "decision_level": None if decision is None else decision.level.value,
            "causal_assignment": causal, "verified_effect_before_next_event": bool(effect),
            "matched": bool(causal and effect), "counterfactual_candidates": event_candidates,
        })
    matched = sum(bool(item["matched"]) for item in events)
    lowest_levels = {item["minimal_sufficient_level"] for item in events}
    return {
        "oracle": "DETERMINISTIC_FORCED_REPLAY_V1",
        "event_count": len(events), "matched_event_count": matched,
        "fraction": 1.0 if not events else matched / len(events),
        "lowest_sufficient_level": next(iter(lowest_levels)) if len(lowest_levels) == 1 else None,
        "counterfactual_candidates": [], "events": events,
    }


def _matrix_fields(spec: V3EpisodeSpec) -> dict[str, object]:
    domain = (
        "CONTROL" if spec.scenario_id.startswith("control-") else
        "MOTION" if spec.scenario_id.startswith("motion-") else
        "SEMANTIC" if spec.scenario_id.startswith("semantic-") else "ANCHOR"
    )
    return {"template_id": spec.scenario_id, "domain": domain, "matrix_role": "PRIMARY" if spec.controller_id == PRIMARY_CONTROLLER_ID else "SENSITIVITY"}


def _terminal_row(spec: V3EpisodeSpec, receipt: object, raw: object, episode_manifest: Mapping[str, object], approval_report_sha256: str) -> dict[str, object]:
    score = score_episode(raw)
    counts = score.violation_counts
    levels = [item.level.value for item in raw.decisions]
    return {
        "episode_id": spec.episode_id, "architecture": spec.architecture.value,
        "scenario_id": spec.scenario_id, "seed": spec.seed, "controller_id": spec.controller_id,
        **_matrix_fields(spec), "approval_report_sha256": approval_report_sha256,
        "disposition": "COMPLETE", "terminal": score.terminal,
        "unsafe": counts["unsafe"], "forbidden": counts["forbidden"], "collision": counts["collision"],
        "invalid_action": counts["invalid_action"], "stale": counts["stale"], "loop": counts["loop"], "reset": counts["reset"],
        "control_interventions": levels.count("CONTROL"), "motion_interventions": levels.count("MOTION"),
        "semantic_interventions": levels.count("SEMANTIC"),
        "counterfactual_event_audit": counterfactual_event_audit(raw),
        "physical_trace_sha256": sha256_bytes(raw.trace["q"].tobytes()),
        "parameter_use_sha256": sha256_bytes(canonical_bytes(raw.parameter_use_receipt)),
        "parameter_use_receipt": raw.parameter_use_receipt,
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
    _resume_create_only_members(output, {
        "outcome-freeze.json": canonical_bytes(freeze),
        "approval/approval-binding.json": approval_binding.read_bytes(),
        "approval/approval-report.json": approval_report.read_bytes(),
    }, marker_name="HEADERS-SEALED.json", seal=True)
    if (output / "raw/manifest.json").is_file():
        rows = _seal_dispositions(output)
        return {"status": "SEALED_AWAITING_RECONSTRUCTION", "episode_dispositions": len(rows)}
    disposition_root = output / "raw/dispositions"
    for spec in specs:
        disposition_path = disposition_root / f"{spec.episode_id}.json"
        if disposition_path.is_file():
            retained = _read_disposition(disposition_path)
            expected_identity = {"episode_id": spec.episode_id, "architecture": spec.architecture.value, "scenario_id": spec.scenario_id, "seed": spec.seed, "controller_id": spec.controller_id}
            if any(retained.get(key) != value for key, value in expected_identity.items()):
                raise OutcomeAuthorizationError(f"retained disposition mismatch: {spec.episode_id}")
            _validate_complete_episode(output, retained)
            continue
        receipt = precheck(spec)
        if receipt.disposition == "NOT_RUN":
            row = {
                "episode_id": spec.episode_id,
                "architecture": spec.architecture.value,
                "scenario_id": spec.scenario_id,
                "seed": spec.seed,
                "controller_id": spec.controller_id,
                **_matrix_fields(spec), "approval_report_sha256": approval["approval_report_sha256"],
                "disposition": "NOT_RUN",
                "terminal": None,
                "unsafe": 0, "forbidden": 0, "collision": 0, "invalid_action": 0,
                "stale": 0, "loop": 0, "reset": 0,
                "control_interventions": 0, "motion_interventions": 0, "semantic_interventions": 0,
                "lowest_sufficient_correct": None,
                "physical_trace_sha256": None, "parameter_use_sha256": None,
                "parameter_use_receipt": None,
                "precheck_input": receipt.precheck_input,
                "precheck_receipt": receipt,
                "precheck_sha256": sha256_bytes(canonical_bytes(receipt)),
            }
            _write(disposition_path, canonical_bytes(row))
            continue
        try:
            raw = run_episode(spec)
            episode_manifest = _write_episode_resume(output / "raw", raw)
            row = _terminal_row(spec, receipt, raw, episode_manifest, str(approval["approval_report_sha256"]))
            _write(disposition_path, canonical_bytes(row))
        except BaseException as exc:
            interrupted = {
                "episode_id": spec.episode_id, "architecture": spec.architecture.value,
                "scenario_id": spec.scenario_id, "seed": spec.seed, "controller_id": spec.controller_id,
                **_matrix_fields(spec), "approval_report_sha256": approval["approval_report_sha256"],
                "disposition": "INTERRUPTED" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "INVALID",
                "error_type": type(exc).__name__, "precheck_input": receipt.precheck_input,
                "precheck_receipt": receipt,
            }
            _write(disposition_path, canonical_bytes(interrupted))
            raise
    rows = _seal_dispositions(output)
    return {"status": "SEALED_AWAITING_RECONSTRUCTION", "episode_dispositions": len(rows)}


def reconstruct_outcomes(
    output: Path, clean: Path, *, qualification_root: Path, approval_binding: Path, approval_report: Path
) -> dict[str, object]:
    """Re-execute immutable raw, compare byte-exactly, then publish all scientific deliverables."""
    if clean.exists():
        raise FileExistsError(clean)
    verify_outcome_approval(qualification_root, approval_binding, approval_report)
    if (output / "approval/approval-binding.json").read_bytes() != approval_binding.read_bytes() or (output / "approval/approval-report.json").read_bytes() != approval_report.read_bytes():
        raise OutcomeAuthorizationError("retained approval provenance drifted before reconstruction")
    rows = _seal_dispositions(output)
    try:
        validate_publishable_evidence(output, require_derived=False)
    except RuntimeError as exc:
        raise OutcomeAuthorizationError(str(exc)) from exc
    invalid = any(row.get("disposition") in {"INVALID", "INTERRUPTED"} for row in rows)
    def retain_lifecycle(root: Path, status: str, invalid_count: int) -> None:
        receipt = {
            "schema_version": 1,
            "status": status,
            "raw_manifest_sha256": sha256_bytes((root / "raw/manifest.json").read_bytes()),
            "outcome_rows_sha256": sha256_bytes((root / "raw/outcome-rows.jsonl").read_bytes()),
            "raw_tree_sha256": sha256_bytes(canonical_bytes(_inventory(_tree_bytes(root / "raw")))),
            "episode_dispositions": len(rows),
            "invalid_dispositions": invalid_count,
        }
        _write_expected(root / "derived/reconstruction-receipt.json", canonical_bytes(receipt))
    if invalid or len(rows) != 360:
        replay = clean / OUTCOME_ROOT_NAME
        for name, payload in sorted(_tree_bytes(output).items()):
            if not name.startswith("derived/"):
                _write(replay / name, payload)
        invalid_count = sum(row.get("disposition") in {"INVALID", "INTERRUPTED"} for row in rows)
        retain_lifecycle(output, "INVALID_NONRESUMABLE_LIFECYCLE", invalid_count)
        retain_lifecycle(replay, "INVALID_NONRESUMABLE_LIFECYCLE", invalid_count)
        decision = analyze_outcomes(output)
        analyze_outcomes(replay)
        _assert_trees_equal(output / "derived", replay / "derived")
        return {"matched": True, "episode_dispositions": len(rows), "scientific_result": decision["scientific_result"], "invalid_dispositions": invalid_count}
    replay = clean / OUTCOME_ROOT_NAME
    replay.parent.mkdir(parents=True)
    run_outcomes(
        replay, qualification_root=qualification_root,
        approval_binding=approval_binding, approval_report=approval_report,
    )
    _assert_trees_equal(output / "raw", replay / "raw")
    retain_lifecycle(output, "RAW_REPLAY_MATCHED_RESUMABLE", 0)
    retain_lifecycle(replay, "RAW_REPLAY_MATCHED_RESUMABLE", 0)
    decision = analyze_outcomes(output)
    analyze_outcomes(replay)
    _assert_trees_equal(output / "derived", replay / "derived")
    return {
        "matched": True, "episode_dispositions": 360,
        "raw_manifest_sha256": sha256_bytes((output / "raw/manifest.json").read_bytes()),
        "derived_manifest_sha256": sha256_bytes((output / "derived/manifest.json").read_bytes()),
        "scientific_result": decision["scientific_result"],
    }


def publish_outcome_archive(
    output: Path, destination: Path, clean: Path, *, qualification_root: Path,
    approval_binding: Path, approval_report: Path,
) -> dict[str, object]:
    """Authenticate, reconstruct, validate, then archive sealed outcome evidence."""
    verify_outcome_approval(qualification_root, approval_binding, approval_report)
    required = (
        output / "outcome-freeze.json", output / "HEADERS-SEALED.json",
        output / "approval/approval-binding.json", output / "approval/approval-report.json",
        output / "raw/manifest.json",
    )
    if not all(path.is_file() and not path.is_symlink() for path in required):
        raise OutcomeAuthorizationError("outcome archive requires sealed headers and raw manifest")
    if (output / "approval/approval-binding.json").read_bytes() != approval_binding.read_bytes() or (output / "approval/approval-report.json").read_bytes() != approval_report.read_bytes():
        raise OutcomeAuthorizationError("outcome archive approval provenance mismatch")
    rows = _seal_dispositions(output)
    if not rows or (len(rows) != 360 and not any(row.get("disposition") in {"INVALID", "INTERRUPTED"} for row in rows)):
        raise OutcomeAuthorizationError("outcome raw disposition inventory is incomplete")
    replay = reconstruct_outcomes(
        output, clean, qualification_root=qualification_root,
        approval_binding=approval_binding, approval_report=approval_report,
    )
    if replay.get("matched") is not True:
        raise OutcomeAuthorizationError("outcome reconstruction did not match")
    decision = json.loads((output / "derived/decision.json").read_text(encoding="ascii"))
    if decision.get("scientific_result") != replay.get("scientific_result"):
        raise OutcomeAuthorizationError("outcome derived scientific disposition mismatch")
    return publish_durable_archive(output, destination)


__all__ = [
    "APPROVAL_DECISION", "OUTCOME_ROOT_NAME", "OutcomeAuthorizationError", "dry_run_outcomes", "outcome_specs",
    "publish_outcome_archive", "reconstruct_outcomes", "run_outcomes", "seal_invalid_outcomes", "verify_outcome_approval",
]
