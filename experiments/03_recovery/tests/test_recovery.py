from __future__ import annotations

import importlib

import pytest


c = importlib.import_module("experiments.03_recovery.src.contracts")
r = importlib.import_module("experiments.03_recovery.src.recovery")


def failure(level: c.RecoveryLevel, command_hash: str = "1" * 64, *, safe: bool = True) -> c.ObservableFailure:
    return c.ObservableFailure(
        tracking_persistent=level is c.RecoveryLevel.CONTROL,
        controller_safe=safe,
        action_valid=level not in {c.RecoveryLevel.MOTION, c.RecoveryLevel.SEMANTIC},
        geometry_feasible=level is not c.RecoveryLevel.MOTION,
        semantic_preconditions_valid=level is not c.RecoveryLevel.SEMANTIC,
        previous_level=c.RecoveryLevel.NONE,
        command_sha256=command_hash,
        new_command_generated=False,
        observed_tick=750,
    )


@pytest.mark.parametrize(
    ("architecture", "observed", "expected"),
    [
        *[(c.Architecture.LOCAL_ONLY, item, c.RecoveryLevel.CONTROL) for item in (c.RecoveryLevel.CONTROL, c.RecoveryLevel.MOTION, c.RecoveryLevel.SEMANTIC)],
        *[(c.Architecture.SEMANTIC_ALWAYS, item, c.RecoveryLevel.SEMANTIC) for item in (c.RecoveryLevel.CONTROL, c.RecoveryLevel.MOTION, c.RecoveryLevel.SEMANTIC)],
        *[(c.Architecture.MOTION_THEN_SEMANTIC, item, c.RecoveryLevel.MOTION) for item in (c.RecoveryLevel.CONTROL, c.RecoveryLevel.MOTION, c.RecoveryLevel.SEMANTIC)],
        (c.Architecture.LAYER_MATCHED, c.RecoveryLevel.CONTROL, c.RecoveryLevel.CONTROL),
        (c.Architecture.LAYER_MATCHED, c.RecoveryLevel.MOTION, c.RecoveryLevel.MOTION),
        (c.Architecture.LAYER_MATCHED, c.RecoveryLevel.SEMANTIC, c.RecoveryLevel.SEMANTIC),
    ],
)
def test_architecture_table(architecture: c.Architecture, observed: c.RecoveryLevel, expected: c.RecoveryLevel) -> None:
    budget = c.RecoveryBudget.initial("1" * 64)
    assert r.decide_recovery(architecture, failure(observed), budget, "1" * 64).level is expected


def test_no_failure_never_wakes_recovery() -> None:
    observable = c.ObservableFailure(False, True, True, True, True, c.RecoveryLevel.NONE, "1" * 64, False, 500)
    for architecture in c.Architecture:
        decision = r.decide_recovery(architecture, observable, c.RecoveryBudget.initial("1" * 64), "1" * 64)
        assert decision.level is c.RecoveryLevel.NONE
        assert decision.budget == c.RecoveryBudget.initial("1" * 64)


def test_exact_budgets_exhaust_to_safe_abort() -> None:
    budget = c.RecoveryBudget.initial("1" * 64)
    assert (budget.control_remaining, budget.motion_remaining, budget.semantic_remaining) == (2, 2, 1)
    first = r.decide_recovery(c.Architecture.LOCAL_ONLY, failure(c.RecoveryLevel.CONTROL), budget, "1" * 64)
    second = r.decide_recovery(c.Architecture.LOCAL_ONLY, failure(c.RecoveryLevel.CONTROL), first.budget, "1" * 64)
    third = r.decide_recovery(c.Architecture.LOCAL_ONLY, failure(c.RecoveryLevel.CONTROL), second.budget, "1" * 64)
    assert (first.level, second.level, third.level) == (c.RecoveryLevel.CONTROL, c.RecoveryLevel.CONTROL, c.RecoveryLevel.SAFE_ABORT)


def test_motion_then_semantic_escalates_monotonically() -> None:
    budget = c.RecoveryBudget.initial("1" * 64)
    observable = failure(c.RecoveryLevel.SEMANTIC)
    decision = r.decide_recovery(c.Architecture.MOTION_THEN_SEMANTIC, observable, budget, "1" * 64)
    assert decision.level is c.RecoveryLevel.MOTION
    after = c.ObservableFailure(True, True, True, True, True, c.RecoveryLevel.MOTION, "1" * 64, False, 751)
    assert r.decide_recovery(c.Architecture.MOTION_THEN_SEMANTIC, after, decision.budget, "1" * 64).level is c.RecoveryLevel.SEMANTIC


def test_new_command_hash_is_the_only_budget_reset() -> None:
    exhausted = c.RecoveryBudget(0, 0, 0, "1" * 64)
    repeated = c.ObservableFailure(True, True, True, True, True, c.RecoveryLevel.CONTROL, "1" * 64, True, 751)
    assert r.decide_recovery(c.Architecture.LAYER_MATCHED, repeated, exhausted, "1" * 64).level is c.RecoveryLevel.SAFE_ABORT
    new = c.ObservableFailure(True, True, True, True, True, c.RecoveryLevel.NONE, "2" * 64, True, 751)
    decision = r.decide_recovery(c.Architecture.LAYER_MATCHED, new, exhausted, "1" * 64)
    assert decision.level is c.RecoveryLevel.CONTROL
    assert decision.budget == c.RecoveryBudget(1, 2, 1, "2" * 64)


def test_nonfinite_or_unsafe_controller_fails_closed() -> None:
    decision = r.decide_recovery(c.Architecture.LAYER_MATCHED, failure(c.RecoveryLevel.CONTROL, safe=False), c.RecoveryBudget.initial("1" * 64), "1" * 64)
    assert decision.level is c.RecoveryLevel.SAFE_ABORT


def test_monotonic_guard_rejects_deescalation_without_new_command() -> None:
    observable = c.ObservableFailure(True, True, True, True, True, c.RecoveryLevel.MOTION, "1" * 64, False, 751)
    decision = r.decide_recovery(c.Architecture.LAYER_MATCHED, observable, c.RecoveryBudget.initial("1" * 64), "1" * 64)
    assert decision.level is c.RecoveryLevel.MOTION
