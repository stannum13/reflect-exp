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

    previous = value.observation.robot_state.q
    expected_rows = []
    start = kin.forward_kinematics(previous, cfg.arm.link_lengths_m)
    for index in range(len(p2.actions)):
        alpha = index / (len(p2.actions) - 1)
        previous = kin.absolute_ik((1 - alpha) * start + alpha * target, previous, cfg.arm.link_lengths_m, cfg.controller.ik_damping_candidates[0], cfg)
        expected_rows.append(previous)
    assert p2.actions.tobytes() == np.vstack(expected_rows).tobytes()


def test_p2_p4_valid_prefix_and_p3_p4_current_q_numeric_references() -> None:
    cfg = config()
    value = policy_input(period_ns=100_000_000, response_ns=300_000_000)
    kin = importlib.import_module("experiments.01_policy_control.src.kinematics")
    q = np.array([0.30, -0.60, 0.25])
    for stack in (contracts.CommandStack.P2, contracts.CommandStack.P4):
        chunk = representations.emit_chunk(stack, value, cfg)
        relative_ns = 150_000_000
        interpolated = kin.linear_knot_reference(chunk.actions, relative_ns, 100_000_000)
        candidate = interpolated if stack is contracts.CommandStack.P2 else kin.differential_ik_reference(interpolated, q, cfg.arm.link_lengths_m, cfg.controller.ik_damping_candidates[0], cfg)
        state = representations.initial_executor_state(candidate)
        reference, _, _ = representations.reference_for_tick(stack, chunk, q, np.zeros(3), chunk.valid_from_ns + relative_ns, state, cfg)
        assert reference.q_ref.tobytes() == candidate.tobytes()
        assert chunk.valid_from_ns + relative_ns < chunk.expires_at_ns
    for stack in (contracts.CommandStack.P3, contracts.CommandStack.P4):
        chunk = representations.emit_chunk(stack, value, cfg)
        xy = chunk.actions[0]
        expected = kin.differential_ik_reference(xy, q, cfg.arm.link_lengths_m, cfg.controller.ik_damping_candidates[0], cfg)
        state = representations.initial_executor_state(expected)
        reference, _, _ = representations.reference_for_tick(stack, chunk, q, np.zeros(3), chunk.valid_from_ns, state, cfg)
        assert reference.q_ref.tobytes() == expected.tobytes()


def test_complete_nested_policy_input_snapshot_is_unchanged_for_every_stack() -> None:
    cfg = config()
    value = policy_input()
    def snapshot():
        belief = value.observation.object_beliefs[0]
        return (
            value.observation.robot_state.q.tobytes(), value.observation.robot_state.dq.tobytes(),
            belief.pose.tobytes(), tuple(belief.state.items()),
            value.skill.target_pose.position.tobytes(), value.skill.target_pose.quaternion_wxyz.tobytes(),
            tuple((item.kind, tuple(item.parameters.items())) for item in value.skill.constraints),
            value.skill.success_predicate.kind, tuple(value.skill.success_predicate.parameters.items()),
            value.q_initial.tobytes(), value.q_initial_target.tobytes(),
        )
    before = snapshot()
    for stack in contracts.CommandStack:
        representations.emit_chunk(stack, value, cfg)
        assert snapshot() == before
