from __future__ import annotations

import importlib

import numpy as np

from .helpers import config, policy_input


rep = importlib.import_module("experiments.01_policy_control.src.representations")
contracts = importlib.import_module("experiments.01_policy_control.src.contracts")


def test_exact_79_predictive_candidates() -> None:
    candidates = rep.mpc_candidates()
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
