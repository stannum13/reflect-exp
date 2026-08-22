"""Deterministic policy/executor implementations for the six command stacks."""

from __future__ import annotations

import math

import numpy as np

from reflect.types import ActionChunk, ControlReference

from .contracts import ClampReport, CommandStack, ExecutorState, ExperimentConfig, PolicyInput, frozen_vector
from .kinematics import absolute_ik, differential_ik_reference, forward_kinematics, linear_knot_reference


def initial_executor_state(q: np.ndarray) -> ExecutorState:
    q = frozen_vector(q, "q", shape=(3,))
    zero = frozen_vector(np.zeros(3), "zero", shape=(3,))
    return ExecutorState(None, q, zero, q, False)


def _target(policy_input: PolicyInput) -> np.ndarray:
    pose = policy_input.skill.target_pose
    if pose is None:
        raise ValueError("target pose is required")
    return np.array(pose.position[:2], dtype=np.float64, copy=True)


def emit_chunk(stack: CommandStack, policy_input: PolicyInput, config: ExperimentConfig) -> ActionChunk:
    stack = CommandStack(stack)
    target = _target(policy_input)
    q_observed = np.asarray(policy_input.observation.robot_state.q)
    period_s = policy_input.policy_period_ns / 1e9
    horizon = math.ceil(config.timing.chunk_horizon_s / period_s) + 1
    links = config.arm.link_lengths_m
    damping = config.controller.ik_damping_candidates[0]
    if stack is CommandStack.P1:
        actions = absolute_ik(target, q_observed, links, damping)[None, :]
        representation = "JOINT_POSITION"
    elif stack is CommandStack.P2:
        start = forward_kinematics(q_observed, links)
        rows: list[np.ndarray] = []
        previous = q_observed
        for index in range(horizon):
            alpha = index / (horizon - 1)
            previous = absolute_ik((1.0 - alpha) * start + alpha * target, previous, links, damping)
            rows.append(previous)
        actions = np.vstack(rows)
        representation = "JOINT_POSITION"
    elif stack is CommandStack.P3:
        actions = target[None, :]
        representation = "EEF_TRAJECTORY"
    elif stack is CommandStack.P4:
        start = forward_kinematics(q_observed, links)
        actions = np.vstack([(1.0 - i / (horizon - 1)) * start + i / (horizon - 1) * target for i in range(horizon)])
        representation = "EEF_TRAJECTORY"
    else:
        raise NotImplementedError(stack.value)
    expiry = policy_input.response_time_ns + math.ceil(config.timing.expiry_periods * policy_input.policy_period_ns)
    return ActionChunk(
        chunk_id=f"{policy_input.observation.sequence_id}:{stack.value}",
        skill_id=policy_input.skill.skill_id,
        source_observation_id=policy_input.observation.sequence_id,
        source_observation_time_ns=policy_input.observation.source_time_ns,
        generated_time_ns=policy_input.response_time_ns,
        valid_from_ns=policy_input.response_time_ns,
        expires_at_ns=expiry,
        dt_s=period_s,
        actions=actions,
        representation=representation,
        expected_phase="track_target",
        metadata={"stack_id": stack.value},
    )


def _slew(candidate: np.ndarray, previous: np.ndarray, config: ExperimentConfig) -> tuple[np.ndarray, bool]:
    step = config.controller.reference_slew_rad_s * config.arm.timestep_s
    delta = np.asarray(candidate) - np.asarray(previous)
    return np.asarray(previous) + np.clip(delta, -step, step), bool(np.any(np.abs(delta) > step))


def reference_for_tick(
    stack: CommandStack,
    chunk: ActionChunk,
    q: np.ndarray,
    dq: np.ndarray,
    time_ns: int,
    state: ExecutorState,
    config: ExperimentConfig,
) -> tuple[ControlReference, ExecutorState, ClampReport]:
    stack = CommandStack(stack)
    relative_ns = max(0, time_ns - chunk.valid_from_ns)
    if stack is CommandStack.P1:
        candidate = chunk.actions[0]
    elif stack is CommandStack.P2:
        candidate = linear_knot_reference(chunk.actions, relative_ns, int(round(chunk.dt_s * 1e9)))
    elif stack in {CommandStack.P3, CommandStack.P4}:
        xy = chunk.actions[0] if stack is CommandStack.P3 else linear_knot_reference(chunk.actions, relative_ns, int(round(chunk.dt_s * 1e9)))
        candidate = differential_ik_reference(xy, np.asarray(q), config.arm.link_lengths_m, config.controller.ik_damping_candidates[0], config.arm.timestep_s)
    else:
        raise NotImplementedError(stack.value)
    bounded, did_slew = _slew(candidate, state.latched_q_ref, config)
    bounded = np.clip(bounded, config.arm.joint_min_rad, config.arm.joint_max_rad)
    reference = ControlReference(chunk.chunk_id, time_ns, bounded, np.zeros(3), None, None, "JOINT_PD")
    next_state = ExecutorState(chunk.chunk_id, bounded, state.p5_qdot_previous, state.p5_planner_q_ref, state.p5_planner_enabled)
    return reference, next_state, ClampReport(reference_clamped=did_slew)
