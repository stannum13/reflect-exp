from __future__ import annotations

import importlib

import numpy as np

from .helpers import config, policy_input


rep = importlib.import_module("experiments.01_policy_control.src.representations")
contracts = importlib.import_module("experiments.01_policy_control.src.contracts")


def test_p6_bounded_residual_and_nominal_endpoints() -> None:
    cfg = config()
    value = policy_input(response_ns=500_000_000)
    chunk = rep.emit_chunk(contracts.CommandStack.P6, value, cfg)
    assert chunk.representation == "BOUNDED_RESIDUAL"
    assert chunk.actions.shape == (1, 3)
    assert np.max(np.abs(chunk.actions)) <= 0.25
    assert rep.minimum_jerk_nominal(value.q_initial, value.q_initial_target, 0).tobytes() == value.q_initial.tobytes()
    assert rep.minimum_jerk_nominal(value.q_initial, value.q_initial_target, 1_000_000_000).tobytes() == value.q_initial_target.tobytes()


def test_p6_executor_uses_only_chunk_and_frozen_nominal() -> None:
    cfg = config()
    value = policy_input(response_ns=500_000_000)
    chunk = rep.emit_chunk(contracts.CommandStack.P6, value, cfg)
    state = rep.initial_executor_state(value.q_initial)
    first, _, _ = rep.reference_for_tick(contracts.CommandStack.P6, chunk, value.q_initial, np.zeros(3), 500_000_000, state, cfg)
    mutated_q = np.array(value.q_initial, copy=True)
    second, _, _ = rep.reference_for_tick(contracts.CommandStack.P6, chunk, mutated_q, np.zeros(3), 500_000_000, state, cfg)
    assert first.q_ref.tobytes() == second.q_ref.tobytes()
