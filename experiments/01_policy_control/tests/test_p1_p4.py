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


def test_p1_p4_exact_values_expiry_and_closed_endpoints() -> None:
    cfg = config()
    value = policy_input(period_ns=100_000_000, response_ns=300_000_000)
    kin = importlib.import_module("experiments.01_policy_control.src.kinematics")
    target = value.skill.target_pose.position[:2]
    p1, p2, p3, p4 = [representations.emit_chunk(stack, value, cfg) for stack in tuple(contracts.CommandStack)[:4]]
    expected_q = kin.absolute_ik(target, value.observation.robot_state.q, cfg.arm.link_lengths_m, cfg.controller.ik_damping_candidates[0], cfg)
    assert p1.actions[0].tobytes() == expected_q.tobytes()
    assert p3.actions[0].tobytes() == target.tobytes()
    assert p2.actions[0].tobytes() == value.observation.robot_state.q.tobytes()
    assert p4.actions[0].tobytes() == kin.forward_kinematics(value.observation.robot_state.q, cfg.arm.link_lengths_m).tobytes()
    assert p4.actions[-1].tobytes() == target.tobytes()
    assert all(chunk.expires_at_ns == 550_000_000 for chunk in (p1, p2, p3, p4))
