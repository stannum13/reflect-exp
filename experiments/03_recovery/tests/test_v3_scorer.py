from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import importlib
import inspect

import numpy as np
import pytest


contracts = importlib.import_module("experiments.03_recovery.src.v3_contracts")
runtime = importlib.import_module("experiments.03_recovery.src.v3_runtime")
scorer = importlib.import_module("experiments.03_recovery.src.v3_scorer")


def episode(scenario: str, architecture: object = None) -> object:
    architecture = contracts.Architecture.R3 if architecture is None else architecture
    return runtime.run_episode(runtime.V3EpisodeSpec(architecture, scenario, 20261891, contracts.PRIMARY_CONTROLLER_ID))


@pytest.mark.parametrize("scenario", contracts.SCENARIO_IDS)
def test_independent_scorer_reconstructs_success_from_full_raw(scenario: str) -> None:
    raw = episode(scenario)
    result = scorer.score_episode(raw)
    assert result.terminal == "SUCCESS"
    assert result.mission_postcondition is True
    assert result.dwell_satisfied is True
    assert all(value == 0 for value in result.violation_counts.values())
    assert len(result.rows) == contracts.EPISODE_TICKS


def test_scorer_does_not_import_runtime_or_trust_executor_debug() -> None:
    source = inspect.getsource(scorer)
    assert "v3_runtime" not in source
    assert "last_executed_object" not in source
    raw = episode("anchor-nominal")
    falsified = replace(raw, executor_debug={"aborted": True, "success": False, "unsafe_count": 999})
    assert scorer.score_episode(raw) == scorer.score_episode(falsified)


def test_terminal_requires_authorized_alternative_and_abort_is_reconstructed_failure() -> None:
    raw = episode("semantic-object-unavailable", contracts.Architecture.R0)
    result = scorer.score_episode(raw)
    assert result.terminal == "FAILURE"
    assert result.mission_postcondition is False
    assert result.violation_counts["forbidden"] == 0


def test_trajectory_and_action_bytes_are_authoritative() -> None:
    raw = episode("motion-target-shift")
    damaged = replace(raw, trajectory_bytes=raw.trajectory_bytes[:-1] + bytes((raw.trajectory_bytes[-1] ^ 1,)))
    result = scorer.score_episode(damaged)
    assert result.terminal == "FAILURE"
    assert result.violation_counts["invalid_action"] > 0


def test_contact_authority_is_full_retained_envelope_not_executor_boolean() -> None:
    raw = episode("anchor-nominal")
    trace = {name: value.copy() for name, value in raw.trace.items()}
    trace["obstacle_contact"][:] = True
    falsified_debug_trace = replace(raw, trace=trace)
    assert scorer.score_episode(falsified_debug_trace).terminal == "SUCCESS"


def test_trace_target_error_and_action_valid_are_non_authoritative() -> None:
    raw = episode("anchor-nominal")
    baseline = scorer.score_episode(raw)
    trace = {name: value.copy() for name, value in raw.trace.items()}
    trace["target_error_m"][:] = 99.0
    trace["action_valid"][:] = False
    tampered = replace(raw, trace=trace)
    assert scorer.score_episode(tampered) == baseline


def test_executor_reported_valid_tick_count_is_non_authoritative() -> None:
    raw = episode("semantic-object-unavailable")
    baseline = scorer.score_episode(raw)
    receipts = [dict(item) for item in raw.execution_receipts]
    assert receipts
    receipts[0]["executed_valid_ticks"] = 0
    tampered = replace(raw, execution_receipts=tuple(receipts))
    assert scorer.score_episode(tampered) == baseline


def test_scorer_recomputes_eef_and_target_error_from_qpos_and_world_truth() -> None:
    raw = episode("anchor-nominal")
    trace = {name: value.copy() for name, value in raw.trace.items()}
    trace["eef_xy"][:] += np.asarray((0.01, -0.01))
    tampered = replace(raw, trace=trace)
    result = scorer.score_episode(tampered)
    assert result.terminal == "FAILURE"
    assert result.violation_counts["invalid_action"] > 0


def test_scorer_recomputes_reference_from_trajectory_not_matching_executor_fields() -> None:
    raw = episode("anchor-nominal")
    index = next(index for index, item in enumerate(raw.action_envelopes) if item["mode"] == "EXECUTE")
    trace = {name: value.copy() for name, value in raw.trace.items()}
    trace["q_ref"][index, 0] += 0.001
    trace["actuator_cmd_nm"][index, 0] += 0.005
    envelopes = [dict(item) for item in raw.action_envelopes]
    envelopes[index]["joint_reference"] = trace["q_ref"][index].tolist()
    envelopes[index]["executed_actuator_nm"] = trace["actuator_cmd_nm"][index].tolist()
    tampered = replace(raw, trace=trace, action_envelopes=tuple(envelopes))
    result = scorer.score_episode(tampered)
    assert result.terminal == "FAILURE"
    assert result.violation_counts["invalid_action"] > 0


def test_t3_snapshot_provenance_and_evidence_hash_are_authoritative() -> None:
    raw = episode("anchor-nominal")
    ledger = [dict(item) for item in raw.memory_ledger]
    ledger[0] = {**ledger[0], "snapshot": deepcopy(ledger[0]["snapshot"])}
    ledger[0]["snapshot"]["facts"][0]["provenance"] = "forged-observation"
    tampered = replace(raw, memory_ledger=tuple(ledger))
    assert scorer.score_episode(tampered).terminal == "FAILURE"


def test_t3_facts_are_reconstructed_from_append_only_events_not_self_hashed_snapshot() -> None:
    raw = episode("anchor-nominal")
    ledger = [deepcopy(dict(item)) for item in raw.memory_ledger]
    ledger[0]["snapshot"]["facts"][0]["semantic_label"] = "forged-but-self-hashed"
    ledger[0]["snapshot_sha256"] = contracts.sha256_bytes(contracts.canonical_bytes(ledger[0]["snapshot"]))
    tampered = replace(raw, memory_ledger=tuple(ledger))
    result = scorer.score_episode(tampered)
    assert result.terminal == "FAILURE"
    assert result.violation_counts["stale"] > 0


def test_all_positive_controls_independently_force_terminal_failure() -> None:
    raw = episode("semantic-object-unavailable")
    audit = scorer.positive_control_audit(raw)
    assert set(audit) == {
        "unsafe", "forbidden", "collision", "stale", "invalid_action",
        "wrong_object", "missed_dwell", "loop", "reset",
    }
    assert all(item["terminal"] == "FAILURE" for item in audit.values())
    assert all(int(item["detected_count"]) > 0 for item in audit.values())


def test_counterfactual_candidate_scorer_recomputes_raw_trace_and_rejects_tamper() -> None:
    raw = episode("motion-target-shift")
    state = raw.failure_event_states[0]
    candidate = runtime.run_counterfactual_continuation(raw, state, contracts.DecisionLevel.MOTION, window_ticks=25)
    receipt = scorer.score_counterfactual_candidate(state, candidate)
    assert receipt["independently_scored"] is True
    assert receipt["input_sha256"] == candidate["raw_sha256"]
    assert receipt["passed"] is True
    damaged = deepcopy(candidate)
    damaged["ticks"][0]["qpos_after"][0] += 0.01
    with pytest.raises(ValueError, match="counterfactual"):
        scorer.score_counterfactual_candidate(state, damaged)
