from __future__ import annotations

import importlib

import numpy as np
import pytest

from .helpers import config, policy_input


rep = importlib.import_module("experiments.01_policy_control.src.representations")
contracts = importlib.import_module("experiments.01_policy_control.src.contracts")


def test_exact_79_predictive_candidates() -> None:
    candidates = rep.mpc_candidates(config())
    assert len(candidates) == 79
    assert np.array_equal(candidates[0], np.zeros(3))
    assert {round(float(np.linalg.norm(item)), 2) for item in candidates} == {0.0, 0.25, 0.75, 1.50}


def test_p5_objective_moves_and_updates_frozen_velocity_state() -> None:
    cfg = config()
    value = policy_input()
    chunk = rep.emit_chunk(contracts.CommandStack.P5, value, cfg)
    assert chunk.representation == "MPC_GOAL" and chunk.actions.shape == (1, 2)
    state = rep.initial_executor_state(value.q_initial)
    reference, updated, _ = rep.reference_for_tick(
        contracts.CommandStack.P5, chunk, value.q_initial, np.zeros(3), chunk.valid_from_ns, state, cfg
    )
    assert updated.p5_planner_enabled
    assert np.linalg.norm(updated.p5_qdot_previous) > 0.0
    assert reference.q_ref is not None


def test_infeasible_candidate_loses_to_hold() -> None:
    cfg = config()
    q = np.full(3, cfg.arm.joint_max_rad - 0.001)
    target = np.array([0.75, 0.0])
    assert np.isinf(rep.mpc_cost(q, target, np.ones(3) * 1.5, np.zeros(3), cfg, 0.02))


def test_hand_calculated_anti_hold_costs() -> None:
    cfg = config()
    hold_4 = rep.dimensionless_mpc_cost([0.04 / 0.06] * 10, 0.04 / 0.06, 0.0, 0.0, [0.0] * 10, cfg, 0.02)
    move_4 = rep.dimensionless_mpc_cost([0.04 / 0.06 * (1 - k / 10) for k in range(1, 11)], 0.0, 0.5, 0.5, [0.0] * 10, cfg, 0.02)
    hold_6 = rep.dimensionless_mpc_cost([1.0] * 10, 1.0, 0.0, 0.0, [0.0] * 10, cfg, 0.02)
    move_6 = rep.dimensionless_mpc_cost([(1 - k / 10) for k in range(1, 11)], 0.0, 0.5, 0.5, [0.0] * 10, cfg, 0.02)
    assert hold_4 == pytest.approx(0.8888888888888888)
    assert move_4 < 0.136667
    assert hold_6 == pytest.approx(2.0)
    assert move_6 < 0.295


def test_p5_transition_complete_lifecycle() -> None:
    state = rep.initial_executor_state(np.zeros(3))
    accepted = rep.p5_transition(state, "ACCEPT", chunk_id="a", active_still_valid=False)
    assert accepted.p5_planner_enabled and np.array_equal(accepted.p5_qdot_previous, np.zeros(3))
    selected = rep.p5_transition(accepted, "PLANNER_SELECTED", qdot=np.array([0.25, 0.0, 0.0]), q_ref=np.array([0.005, 0.0, 0.0]))
    replaced = rep.p5_transition(selected, "ACCEPT", chunk_id="b", active_still_valid=True)
    assert np.array_equal(replaced.p5_qdot_previous, selected.p5_qdot_previous)
    assert rep.p5_transition(replaced, "REJECT") is replaced
    expired = rep.p5_transition(replaced, "EXPIRY")
    assert not expired.p5_planner_enabled and np.array_equal(expired.p5_qdot_previous, np.zeros(3))
    reaccepted = rep.p5_transition(expired, "ACCEPT", chunk_id="c", active_still_valid=False)
    coincident = rep.p5_transition(reaccepted, "PLANNER_SELECTED", qdot=np.array([0.75, 0.0, 0.0]), q_ref=np.array([0.015, 0.0, 0.0]))
    assert coincident.active_chunk_id == "c" and coincident.p5_qdot_previous[0] == 0.75
