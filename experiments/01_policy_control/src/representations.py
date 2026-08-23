"""Deterministic policy/executor implementations for the six command stacks."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace
from typing import Sequence

import numpy as np

from reflect.types import ActionChunk, ControlReference

from .contracts import ClampReport, CommandStack, ExecutorState, ExperimentConfig, PolicyInput, frozen_vector
from .kinematics import absolute_ik, differential_ik_command, differential_ik_reference, forward_kinematics, linear_knot_reference


@dataclass(frozen=True)
class P4ExecutorTuning:
    lookahead_ticks: int
    dq_feedforward: bool

    def __post_init__(self) -> None:
        if type(self.lookahead_ticks) is not int or self.lookahead_ticks not in {1, 12, 25, 49}:
            raise ValueError("P4 lookahead must be exactly 1, 12, 25, or 49 ticks")
        if type(self.dq_feedforward) is not bool:
            raise ValueError("P4 dq feedforward must be boolean")


def with_p4_executor_tuning(chunk: ActionChunk, tuning: P4ExecutorTuning) -> ActionChunk:
    if chunk.metadata.get("stack_id") != CommandStack.P4.value or chunk.representation != "EEF_TRAJECTORY":
        raise ValueError("P4 executor tuning requires a P4 Cartesian trajectory")
    if set(chunk.metadata) != {"stack_id"}:
        raise ValueError("P4 chunk metadata is not the legacy closed schema")
    return replace(chunk, metadata={"stack_id": "P4", "p4_lookahead_ticks": tuning.lookahead_ticks, "p4_dq_feedforward": tuning.dq_feedforward})


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
        actions = absolute_ik(target, q_observed, links, damping, config)[None, :]
        representation = "JOINT_POSITION"
    elif stack is CommandStack.P2:
        start = forward_kinematics(q_observed, links)
        rows: list[np.ndarray] = []
        previous = q_observed
        for index in range(horizon):
            alpha = index / (horizon - 1)
            previous = absolute_ik((1.0 - alpha) * start + alpha * target, previous, links, damping, config)
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
    elif stack is CommandStack.P6:
        nominal = minimum_jerk_nominal(policy_input.q_initial, policy_input.q_initial_target, policy_input.response_time_ns, config)
        stale_target_q = absolute_ik(target, q_observed, links, damping, config)
        actions = np.clip(stale_target_q - nominal, -config.residual.component_limit_rad, config.residual.component_limit_rad)[None, :]
        representation = "BOUNDED_RESIDUAL"
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
            {"stack_id": stack.value, "joint_limit_rad": config.arm.joint_max_rad,
             "velocity_limit_rad_s": config.controller.qdot_limit_rad_s,
             "torque_limit_nm": config.arm.torque_max_nm,
             "success_radius_m": config.thresholds["success_radius_m"],
             "cost_revision": config.mpc.cost_revision}
            if stack is CommandStack.P5 else (
                {"stack_id": stack.value, "q_initial": tuple(policy_input.q_initial.tolist()), "q_initial_target": tuple(policy_input.q_initial_target.tolist()), "nominal_revision": config.residual.nominal_revision}
                if stack is CommandStack.P6 else {"stack_id": stack.value}
            )
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
    dq_reference = np.zeros(3)
    if stack is CommandStack.P1:
        candidate = chunk.actions[0]
    elif stack is CommandStack.P2:
        candidate = linear_knot_reference(chunk.actions, relative_ns, int(round(chunk.dt_s * 1e9)))
    elif stack in {CommandStack.P3, CommandStack.P4}:
        period_ns = int(round(chunk.dt_s * 1e9))
        tuned = stack is CommandStack.P4 and "p4_lookahead_ticks" in chunk.metadata
        if stack is CommandStack.P4 and ("p4_lookahead_ticks" in chunk.metadata) != ("p4_dq_feedforward" in chunk.metadata):
            raise ValueError("P4 executor tuning metadata is incomplete")
        xy = chunk.actions[0] if stack is CommandStack.P3 else linear_knot_reference(chunk.actions, relative_ns, period_ns)
        if tuned:
            candidate, qdot_candidate = differential_ik_command(xy, np.asarray(q), config.arm.link_lengths_m, config.controller.ik_damping_candidates[0], config, lookahead_ticks=int(chunk.metadata["p4_lookahead_ticks"]))
            if chunk.metadata["p4_dq_feedforward"]:
                dq_reference = qdot_candidate
        else:
            candidate = differential_ik_reference(xy, np.asarray(q), config.arm.link_lengths_m, config.controller.ik_damping_candidates[0], config)
    elif stack is CommandStack.P5:
        target = chunk.actions[0]
        planner_period_ns = int(round(config.controller.mpc_period_s * 1e9))
        planner_tick = relative_ns % planner_period_ns == 0
        if planner_tick or not state.p5_planner_enabled:
            selected = min(
                mpc_candidates(config),
                key=lambda qdot: mpc_cost(np.asarray(q), target, qdot, state.p5_qdot_previous, config, config.mpc.smoothness_weight),
            )
            candidate = np.asarray(q) + config.controller.mpc_period_s * selected
            p5_previous = selected
            planner_reference = candidate
        else:
            candidate = state.p5_planner_q_ref
            p5_previous = state.p5_qdot_previous
            planner_reference = state.p5_planner_q_ref
    elif stack is CommandStack.P6:
        q_initial = np.asarray(chunk.metadata["q_initial"], dtype=np.float64)
        q_initial_target = np.asarray(chunk.metadata["q_initial_target"], dtype=np.float64)
        candidate = minimum_jerk_nominal(q_initial, q_initial_target, time_ns, config) + chunk.actions[0]
    else:
        raise NotImplementedError(stack.value)
    bounded, did_slew = _slew(candidate, state.latched_q_ref, config)
    before_joint_clip = bounded
    bounded = np.clip(bounded, config.arm.joint_min_rad, config.arm.joint_max_rad)
    outward = ((bounded >= config.arm.joint_max_rad) & (dq_reference > 0)) | ((bounded <= config.arm.joint_min_rad) & (dq_reference < 0))
    if np.any(before_joint_clip != bounded):
        dq_reference = np.where(outward, 0.0, dq_reference)
    reference = ControlReference(chunk.chunk_id, time_ns, bounded, dq_reference, None, None, "JOINT_PD")
    next_state = ExecutorState(
        chunk.chunk_id,
        bounded,
        p5_previous if stack is CommandStack.P5 else state.p5_qdot_previous,
        planner_reference if stack is CommandStack.P5 else state.p5_planner_q_ref,
        True if stack is CommandStack.P5 else state.p5_planner_enabled,
    )
    return reference, next_state, ClampReport(reference_clamped=did_slew)


def minimum_jerk_nominal(q_initial: np.ndarray, q_target: np.ndarray, time_ns: int, config: ExperimentConfig) -> np.ndarray:
    duration_ns = config.residual.nominal_duration_s * 1_000_000_000
    s = float(np.clip(time_ns / duration_ns, 0.0, 1.0))
    cubic, quartic, quintic = config.residual.blend_coefficients
    h = cubic * s**3 + quartic * s**4 + quintic * s**5
    return frozen_vector(np.asarray(q_initial) + h * (np.asarray(q_target) - np.asarray(q_initial)), "nominal", shape=(3,))


def p5_transition(
    state: ExecutorState,
    event: str,
    *,
    chunk_id: str | None = None,
    active_still_valid: bool = False,
    qdot: np.ndarray | None = None,
    q_ref: np.ndarray | None = None,
) -> ExecutorState:
    if event == "REJECT":
        return state
    zero = np.zeros(3)
    if event in {"EPISODE_START", "EXPIRY", "SAFE_HOLD"}:
        return ExecutorState(None, state.latched_q_ref, zero, state.latched_q_ref, False)
    if event == "ACCEPT":
        if chunk_id is None:
            raise ValueError("ACCEPT requires chunk_id")
        previous = state.p5_qdot_previous if active_still_valid and state.p5_planner_enabled else zero
        return ExecutorState(chunk_id, state.latched_q_ref, previous, state.p5_planner_q_ref, True)
    if event == "PLANNER_SELECTED":
        if qdot is None or q_ref is None or not state.p5_planner_enabled:
            raise ValueError("PLANNER_SELECTED requires enabled state, qdot, and q_ref")
        return ExecutorState(state.active_chunk_id, state.latched_q_ref, qdot, q_ref, True)
    raise ValueError(f"unknown P5 transition: {event}")


def mpc_candidates(config: ExperimentConfig) -> tuple[np.ndarray, ...]:
    result = [frozen_vector(np.zeros(3), "candidate", shape=(3,))]
    directions = sorted(itertools.product(config.mpc.raw_direction_values, repeat=3))
    for magnitude in config.mpc.magnitudes_rad_s:
        for raw in directions:
            vector = np.asarray(raw, dtype=np.float64)
            norm = float(np.linalg.norm(vector))
            if norm:
                result.append(frozen_vector(magnitude * vector / norm, "candidate", shape=(3,)))
    return tuple(result)


def dimensionless_mpc_cost(
    normalized_errors: Sequence[float],
    terminal_error: float,
    normalized_effort: float,
    normalized_smoothness: float,
    normalized_barriers: Sequence[float],
    config: ExperimentConfig,
    smoothness_weight: float,
) -> float:
    if len(normalized_errors) != config.controller.mpc_horizon_steps or len(normalized_barriers) != len(normalized_errors):
        raise ValueError("MPC cost domains must match the frozen horizon")
    integration = config.controller.mpc_period_s / (config.controller.mpc_period_s * config.controller.mpc_horizon_steps)
    stages = sum(
        integration * (
            config.mpc.stage_error_weight * error * error
            + config.mpc.effort_weight * normalized_effort * normalized_effort
            + config.mpc.barrier_weight * barrier * barrier
            + smoothness_weight * normalized_smoothness * normalized_smoothness
        )
        for error, barrier in zip(normalized_errors, normalized_barriers, strict=True)
    )
    return float(config.mpc.terminal_error_weight * terminal_error * terminal_error + stages)


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
    effort = np.linalg.norm(velocity) / (math.sqrt(3.0) * config.mpc.velocity_scale_rad_s)
    smoothness = np.linalg.norm(velocity - np.asarray(qdot_previous)) / (math.sqrt(3.0) * config.mpc.velocity_scale_rad_s)
    errors: list[float] = []
    barriers: list[float] = []
    for _ in range(config.controller.mpc_horizon_steps):
        current = current + config.controller.mpc_period_s * velocity
        if np.any(np.abs(current) > config.arm.joint_max_rad):
            return math.inf
        errors.append(float(np.linalg.norm(np.asarray(target) - forward_kinematics(current, config.arm.link_lengths_m)) / config.mpc.error_scale_m))
        barriers.append(float(np.linalg.norm(np.maximum(0.0, np.abs(current) - config.arm.solver_joint_max_rad)) / (math.sqrt(3.0) * config.mpc.soft_joint_margin_rad)))
    return dimensionless_mpc_cost(errors, errors[-1], effort, smoothness, barriers, config, smoothness_weight)
