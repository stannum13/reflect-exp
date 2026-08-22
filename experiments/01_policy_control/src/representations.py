"""Deterministic policy/executor implementations for the six command stacks."""

from __future__ import annotations

import itertools
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
    elif stack is CommandStack.P5:
        actions = target[None, :]
        representation = "MPC_GOAL"
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
        metadata=(
            {"stack_id": stack.value, "cost_revision": 1, "joint_limit_rad": config.arm.joint_max_rad,
             "velocity_limit_rad_s": config.controller.qdot_limit_rad_s,
             "torque_limit_nm": config.arm.torque_max_nm,
             "success_radius_m": config.thresholds["success_radius_m"]}
            if stack is CommandStack.P5 else {"stack_id": stack.value}
        ),
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
    elif stack is CommandStack.P5:
        target = chunk.actions[0]
        planner_period_ns = int(round(config.controller.mpc_period_s * 1e9))
        planner_tick = relative_ns % planner_period_ns == 0
        if planner_tick or not state.p5_planner_enabled:
            selected = min(
                mpc_candidates(),
                key=lambda qdot: mpc_cost(np.asarray(q), target, qdot, state.p5_qdot_previous, config, config.controller.mpc_smoothness_candidates[0]),
            )
            candidate = np.asarray(q) + config.controller.mpc_period_s * selected
            p5_previous = selected
            planner_reference = candidate
        else:
            candidate = state.p5_planner_q_ref
            p5_previous = state.p5_qdot_previous
            planner_reference = state.p5_planner_q_ref
    else:
        raise NotImplementedError(stack.value)
    bounded, did_slew = _slew(candidate, state.latched_q_ref, config)
    bounded = np.clip(bounded, config.arm.joint_min_rad, config.arm.joint_max_rad)
    reference = ControlReference(chunk.chunk_id, time_ns, bounded, np.zeros(3), None, None, "JOINT_PD")
    next_state = ExecutorState(
        chunk.chunk_id,
        bounded,
        p5_previous if stack is CommandStack.P5 else state.p5_qdot_previous,
        planner_reference if stack is CommandStack.P5 else state.p5_planner_q_ref,
        True if stack is CommandStack.P5 else state.p5_planner_enabled,
    )
    return reference, next_state, ClampReport(reference_clamped=did_slew)


def mpc_candidates() -> tuple[np.ndarray, ...]:
    result = [frozen_vector(np.zeros(3), "candidate", shape=(3,))]
    directions = sorted(itertools.product((-1.0, 0.0, 1.0), repeat=3))
    for magnitude in (0.25, 0.75, 1.50):
        for raw in directions:
            vector = np.asarray(raw, dtype=np.float64)
            norm = float(np.linalg.norm(vector))
            if norm:
                result.append(frozen_vector(magnitude * vector / norm, "candidate", shape=(3,)))
    return tuple(result)


def mpc_cost(
    q: np.ndarray,
    target: np.ndarray,
    qdot: np.ndarray,
    qdot_previous: np.ndarray,
    config: ExperimentConfig,
    smoothness_weight: float,
) -> float:
    current = np.array(q, dtype=np.float64, copy=True)
    velocity = np.asarray(qdot, dtype=np.float64)
    stage = 0.0
    effort = np.linalg.norm(velocity) / (math.sqrt(3.0) * 1.5)
    smoothness = np.linalg.norm(velocity - np.asarray(qdot_previous)) / (math.sqrt(3.0) * 1.5)
    for _ in range(10):
        current = current + 0.02 * velocity
        if np.any(np.abs(current) > config.arm.joint_max_rad):
            return math.inf
        error = np.linalg.norm(np.asarray(target) - forward_kinematics(current, config.arm.link_lengths_m)) / 0.06
        barrier = np.linalg.norm(np.maximum(0.0, np.abs(current) - 2.55)) / (math.sqrt(3.0) * 0.15)
        stage += 0.1 * (error * error + 0.01 * effort * effort + 100.0 * barrier * barrier + smoothness_weight * smoothness * smoothness)
    terminal = np.linalg.norm(np.asarray(target) - forward_kinematics(current, config.arm.link_lengths_m)) / 0.06
    return float(terminal * terminal + stage)
