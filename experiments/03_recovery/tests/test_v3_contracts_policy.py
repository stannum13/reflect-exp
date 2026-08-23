from __future__ import annotations

from dataclasses import fields
import importlib
import inspect

import pytest

contracts = importlib.import_module("experiments.03_recovery.src.v3_contracts")
policy = importlib.import_module("experiments.03_recovery.src.v3_policy")

Architecture = contracts.Architecture
BudgetState = contracts.BudgetState
CALIBRATION_SEEDS = contracts.CALIBRATION_SEEDS
DecisionLevel = contracts.DecisionLevel
ObservableState = contracts.ObservableState
initial_budget = contracts.initial_budget
make_realization = contracts.make_realization
decide = policy.decide


ZERO = "0" * 64


def observation(**changes: object) -> ObservableState:
    values: dict[str, object] = {
        "tick": 700,
        "history_start_tick": 675,
        "tracking_error_mean_m": 0.0,
        "tracking_error_slope_m_per_tick": 0.0,
        "external_load_mean_nm": 0.0,
        "command_gap_ticks": 0,
        "controller_safe": True,
        "action_valid": True,
        "geometry_feasible": True,
        "semantic_preconditions_valid": True,
        "memory_version": 1,
        "command_content_sha256": ZERO,
        "successful_execution_content_sha256": ZERO,
        "reobserve_index": 0,
    }
    values.update(changes)
    return ObservableState(**values)


def test_calibration_realizations_reach_sampled_tick_and_reject_outcome_namespace() -> None:
    assert CALIBRATION_SEEDS == (20261891, 20261892, 20261893, 20261894)
    values = [make_realization("control-impulse", seed) for seed in CALIBRATION_SEEDS]
    assert all(600 <= item.injection_tick <= 900 for item in values)
    assert len({item.parameter_sha256 for item in values}) == 4
    with pytest.raises(ValueError, match="calibration"):
        make_realization("control-impulse", 20261801)


def test_observable_and_policy_signatures_exclude_hidden_taxonomy() -> None:
    forbidden = {"scenario_id", "scenario_domain", "cause", "hidden_cause", "expected_level", "intended_level"}
    assert forbidden.isdisjoint(field.name for field in fields(ObservableState))
    assert set(inspect.signature(decide).parameters) == {"architecture", "observable", "budget"}


def test_control_signals_are_derived_observables_not_scenario_labels() -> None:
    budget = initial_budget(ZERO)
    load = observation(external_load_mean_nm=contracts.EXTERNAL_LOAD_THRESHOLD_NM + 0.01)
    gap = observation(command_gap_ticks=3)
    assert decide(Architecture.R3, load, budget).level is DecisionLevel.CONTROL
    assert decide(Architecture.R3, gap, budget).level is DecisionLevel.CONTROL


def test_architectures_select_from_observable_content_and_consume_exact_budgets() -> None:
    control = observation(tracking_error_mean_m=0.12)
    motion = observation(action_valid=False)
    semantic = observation(semantic_preconditions_valid=False)
    budget = initial_budget(ZERO)

    assert decide(Architecture.R0, control, budget).level is DecisionLevel.CONTROL
    assert decide(Architecture.R1, control, budget).level is DecisionLevel.SEMANTIC
    assert decide(Architecture.R2, control, budget).level is DecisionLevel.MOTION
    assert decide(Architecture.R3, control, budget).level is DecisionLevel.CONTROL
    assert decide(Architecture.R3, motion, budget).level is DecisionLevel.MOTION
    assert decide(Architecture.R3, semantic, budget).level is DecisionLevel.SEMANTIC

    first = decide(Architecture.R0, control, budget)
    assert first.budget_after == BudgetState(1, 2, 1, ZERO, 700)
    second = decide(Architecture.R0, observation(tick=725, tracking_error_mean_m=0.12, reobserve_index=1), first.budget_after)
    assert second.budget_after == BudgetState(0, 2, 1, ZERO, 725)
    exhausted = decide(Architecture.R0, observation(tick=750, tracking_error_mean_m=0.12, reobserve_index=2), second.budget_after)
    assert exhausted.level is DecisionLevel.SAFE_ABORT


def test_budget_reset_requires_different_content_and_verified_execution_receipt() -> None:
    budget = BudgetState(0, 1, 0, ZERO, 725)
    same = observation(tick=750, command_content_sha256=ZERO, successful_execution_content_sha256=ZERO)
    assert decide(Architecture.R3, same, budget).budget_before == budget

    new_hash = "1" * 64
    new_without_receipt = observation(tick=750, command_content_sha256=new_hash, successful_execution_content_sha256=ZERO)
    assert decide(Architecture.R3, new_without_receipt, budget).budget_before == budget

    verified = observation(tick=750, command_content_sha256=new_hash, successful_execution_content_sha256=new_hash)
    reset = decide(Architecture.R3, verified, budget)
    assert reset.budget_before == BudgetState(2, 2, 1, new_hash, 750)


def test_no_failure_is_a_nonintervention_event() -> None:
    result = decide(Architecture.R3, observation(), initial_budget(ZERO))
    assert result.level is DecisionLevel.NONE
    assert result.budget_before == result.budget_after
