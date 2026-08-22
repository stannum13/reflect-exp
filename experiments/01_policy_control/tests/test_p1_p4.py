from __future__ import annotations

import importlib
import math

import numpy as np

from .helpers import config, policy_input


representations = importlib.import_module("experiments.01_policy_control.src.representations")
contracts = importlib.import_module("experiments.01_policy_control.src.contracts")


def test_p1_through_p4_shapes_domains_and_immutability() -> None:
    cfg = config()
    value = policy_input()
    expected = {
        contracts.CommandStack.P1: ((1, 3), "JOINT_POSITION"),
        contracts.CommandStack.P2: ((math.ceil(0.8 / 0.1) + 1, 3), "JOINT_POSITION"),
        contracts.CommandStack.P3: ((1, 2), "EEF_TRAJECTORY"),
        contracts.CommandStack.P4: ((math.ceil(0.8 / 0.1) + 1, 2), "EEF_TRAJECTORY"),
    }
    snapshot = value.observation.robot_state.q.tobytes()
    for stack, (shape, domain) in expected.items():
        chunk = representations.emit_chunk(stack, value, cfg)
        assert chunk.actions.shape == shape
        assert chunk.representation == domain
        assert chunk.metadata["stack_id"] == stack.value
        assert not chunk.actions.flags.writeable
    assert value.observation.robot_state.q.tobytes() == snapshot


def test_reference_executor_returns_finite_joint_reference() -> None:
    cfg = config()
    value = policy_input()
    state = representations.initial_executor_state(value.q_initial)
    for stack in tuple(contracts.CommandStack)[:4]:
        chunk = representations.emit_chunk(stack, value, cfg)
        reference, state, _ = representations.reference_for_tick(
            stack, chunk, value.q_initial, np.zeros(3), chunk.valid_from_ns, state, cfg
        )
        assert reference.q_ref is not None and reference.q_ref.shape == (3,)
        assert np.isfinite(reference.q_ref).all()
