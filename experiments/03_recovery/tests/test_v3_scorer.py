from __future__ import annotations

from dataclasses import replace
import importlib
import inspect

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


def test_all_positive_controls_independently_force_terminal_failure() -> None:
    raw = episode("semantic-object-unavailable")
    audit = scorer.positive_control_audit(raw)
    assert set(audit) == {
        "unsafe", "forbidden", "collision", "stale", "invalid_action",
        "wrong_object", "missed_dwell", "loop", "reset",
    }
    assert all(item["terminal"] == "FAILURE" for item in audit.values())
    assert all(int(item["detected_count"]) > 0 for item in audit.values())
