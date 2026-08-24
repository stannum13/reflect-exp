"""Pure deterministic recovery policy over observable contract state."""

from __future__ import annotations

from dataclasses import replace

from .contracts import Architecture, ObservableFailure, RecoveryBudget, RecoveryDecision, RecoveryLevel


_ORDER = {
    RecoveryLevel.NONE: 0,
    RecoveryLevel.CONTROL: 1,
    RecoveryLevel.MOTION: 2,
    RecoveryLevel.SEMANTIC: 3,
    RecoveryLevel.SAFE_ABORT: 4,
}


def _consume(level: RecoveryLevel, budget: RecoveryBudget) -> RecoveryBudget | None:
    if level is RecoveryLevel.CONTROL and budget.control_remaining:
        return replace(budget, control_remaining=budget.control_remaining - 1)
    if level is RecoveryLevel.MOTION and budget.motion_remaining:
        return replace(budget, motion_remaining=budget.motion_remaining - 1)
    if level is RecoveryLevel.SEMANTIC and budget.semantic_remaining:
        return replace(budget, semantic_remaining=budget.semantic_remaining - 1)
    return None


def _at_least(level: RecoveryLevel, previous: RecoveryLevel) -> RecoveryLevel:
    return previous if _ORDER[previous] > _ORDER[level] else level


def _next_available(level: RecoveryLevel, budget: RecoveryBudget, *, architecture: Architecture) -> tuple[RecoveryLevel, RecoveryBudget | None]:
    current = level
    while current is not RecoveryLevel.SAFE_ABORT:
        consumed = _consume(current, budget)
        if consumed is not None:
            return current, consumed
        if architecture is Architecture.LOCAL_ONLY or architecture is Architecture.SEMANTIC_ALWAYS:
            return RecoveryLevel.SAFE_ABORT, None
        current = {
            RecoveryLevel.CONTROL: RecoveryLevel.MOTION,
            RecoveryLevel.MOTION: RecoveryLevel.SEMANTIC,
            RecoveryLevel.SEMANTIC: RecoveryLevel.SAFE_ABORT,
        }.get(current, RecoveryLevel.SAFE_ABORT)
    return RecoveryLevel.SAFE_ABORT, None


def decide_recovery(
    architecture: Architecture,
    observable_failure: ObservableFailure,
    budget: RecoveryBudget,
    previous_command_sha256: str,
) -> RecoveryDecision:
    """Select one bounded recovery action without accepting scorer truth."""
    architecture = Architecture(architecture)
    if not isinstance(observable_failure, ObservableFailure) or not isinstance(budget, RecoveryBudget):
        raise TypeError("recovery requires typed observable state and budget")

    reset = observable_failure.new_command_generated and observable_failure.command_sha256 != previous_command_sha256
    active_budget = RecoveryBudget.initial(observable_failure.command_sha256) if reset else budget

    if not observable_failure.detected:
        return RecoveryDecision(RecoveryLevel.NONE, "NO_FAILURE", active_budget, observable_failure.observed_tick, observable_failure.command_sha256)
    if not observable_failure.controller_safe:
        return RecoveryDecision(RecoveryLevel.SAFE_ABORT, "CONTROLLER_UNSAFE", active_budget, observable_failure.observed_tick, observable_failure.command_sha256)

    if architecture is Architecture.LOCAL_ONLY:
        requested = RecoveryLevel.CONTROL
    elif architecture is Architecture.SEMANTIC_ALWAYS:
        requested = RecoveryLevel.SEMANTIC
    elif architecture is Architecture.MOTION_THEN_SEMANTIC:
        requested = RecoveryLevel.SEMANTIC if _ORDER[observable_failure.previous_level] >= _ORDER[RecoveryLevel.MOTION] else RecoveryLevel.MOTION
    elif not observable_failure.semantic_preconditions_valid:
        requested = RecoveryLevel.SEMANTIC
    elif not observable_failure.action_valid or not observable_failure.geometry_feasible:
        requested = RecoveryLevel.MOTION
    else:
        requested = RecoveryLevel.CONTROL

    requested = _at_least(requested, observable_failure.previous_level)
    selected, remaining = _next_available(requested, active_budget, architecture=architecture)
    if remaining is None:
        return RecoveryDecision(RecoveryLevel.SAFE_ABORT, "RECOVERY_BUDGET_EXHAUSTED", active_budget, observable_failure.observed_tick, observable_failure.command_sha256)
    return RecoveryDecision(selected, f"{architecture.value}_{selected.value}_RECOVERY", remaining, observable_failure.observed_tick, observable_failure.command_sha256)


__all__ = ["decide_recovery"]
