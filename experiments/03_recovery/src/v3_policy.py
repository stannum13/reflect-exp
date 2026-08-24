"""Observable-only V3 hierarchy policy and exact 2/2/1 budget transition."""

from __future__ import annotations

from dataclasses import replace

from .v3_contracts import Architecture, BudgetState, DecisionEvent, DecisionLevel, ObservableState, initial_budget


def _reset_if_verified(observable: ObservableState, budget: BudgetState) -> BudgetState:
    changed = observable.command_content_sha256 != budget.active_content_sha256
    verified = observable.successful_execution_content_sha256 == observable.command_content_sha256
    if changed and verified:
        return replace(initial_budget(observable.command_content_sha256), last_observed_tick=observable.tick)
    return budget


def _consume(level: DecisionLevel, budget: BudgetState, tick: int) -> BudgetState | None:
    if level is DecisionLevel.CONTROL and budget.control_remaining:
        return replace(budget, control_remaining=budget.control_remaining - 1, last_observed_tick=tick)
    if level is DecisionLevel.MOTION and budget.motion_remaining:
        return replace(budget, motion_remaining=budget.motion_remaining - 1, last_observed_tick=tick)
    if level is DecisionLevel.SEMANTIC and budget.semantic_remaining:
        return replace(budget, semantic_remaining=budget.semantic_remaining - 1, last_observed_tick=tick)
    return None


def _requested(architecture: Architecture, observable: ObservableState, budget: BudgetState) -> DecisionLevel:
    if architecture is Architecture.R0:
        return DecisionLevel.CONTROL
    if architecture is Architecture.R1:
        return DecisionLevel.SEMANTIC
    if architecture is Architecture.R2:
        return DecisionLevel.MOTION if budget.motion_remaining else DecisionLevel.SEMANTIC
    if not observable.semantic_preconditions_valid:
        return DecisionLevel.SEMANTIC
    if not observable.action_valid or not observable.geometry_feasible:
        return DecisionLevel.MOTION
    return DecisionLevel.CONTROL


def decide(architecture: Architecture, observable: ObservableState, budget: BudgetState) -> DecisionEvent:
    """Choose an intervention using only the typed observable and budget."""
    architecture = Architecture(architecture)
    if not isinstance(observable, ObservableState) or not isinstance(budget, BudgetState):
        raise TypeError("V3 policy requires typed observable and budget")
    active = _reset_if_verified(observable, budget)
    if not observable.failure_detected:
        return DecisionEvent(architecture, DecisionLevel.NONE, "NO_FAILURE", observable.tick, observable.sha256, active, active)
    if not observable.controller_safe:
        return DecisionEvent(architecture, DecisionLevel.SAFE_ABORT, "UNSAFE_CONTROLLER", observable.tick, observable.sha256, active, active)
    requested = _requested(architecture, observable, active)
    consumed = _consume(requested, active, observable.tick)
    if consumed is None:
        return DecisionEvent(architecture, DecisionLevel.SAFE_ABORT, "BUDGET_EXHAUSTED", observable.tick, observable.sha256, active, active)
    return DecisionEvent(architecture, requested, f"{architecture.value}_{requested.value}", observable.tick, observable.sha256, active, consumed)


__all__ = ["decide"]
