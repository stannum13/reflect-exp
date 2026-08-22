"""Scenario generation, empirical metrics, selection, and inference for Experiment 01."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
import time
from typing import Iterable, Sequence

import numpy as np

from reflect.events import ExecutionEvent, ExecutionEventType
from reflect.rollout import RolloutMetadata, RolloutRecord
from reflect.types import Constraint, ObjectBelief, Observation, Pose, Predicate, RobotState, SkillSpec

from .contracts import (
    CommandStack,
    Condition,
    EpisodeMetrics,
    ExperimentConfig,
    FaultKind,
    Scenario,
    SeedMetrics,
)
from .kinematics import absolute_ik, forward_kinematics
from .arm import PlanarArm, bounded_pd
from .representations import emit_chunk, initial_executor_state, reference_for_tick


_COMPASS = np.array(
    [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)],
    dtype=np.float64,
)
_COMPASS /= np.linalg.norm(_COMPASS, axis=1, keepdims=True)


def _rng(seed: int, namespace: str) -> np.random.Generator:
    digest = hashlib.sha256(f"{seed}:{namespace}".encode()).digest()
    return np.random.Generator(np.random.PCG64(int.from_bytes(digest[:16], "big")))


def generate_scenario(seed: int, config: ExperimentConfig) -> Scenario:
    q_rng, direction_rng = _rng(seed, "q0"), _rng(seed, "directions")
    for _ in range(32):
        q0 = np.array([0.35, -0.70, 0.35]) + q_rng.uniform(-0.08, 0.08, 3)
        xy0 = forward_kinematics(q0, config.arm.link_lengths_m)
        initial = xy0 + 0.04 * _COMPASS[int(direction_rng.integers(0, 8))]
        move1 = initial + 0.06 * _COMPASS[int(direction_rng.integers(0, 8))]
        move2 = move1 + 0.06 * _COMPASS[int(direction_rng.integers(0, 8))]
        targets = (initial, move1, move2)
        radii = [float(np.linalg.norm(item)) for item in targets]
        if not all(0.30 <= radius <= 0.70 for radius in radii):
            continue
        solutions = [absolute_ik(item, q0, config.arm.link_lengths_m, 0.01, config) for item in targets]
        if not all(np.all(np.abs(solution) <= 2.55) for solution in solutions):
            continue
        return Scenario(seed, q0, initial, np.vstack((initial, move1)), np.vstack((initial, move1, move2)), np.vstack((initial, initial)))
    raise ValueError("scenario proposal limit exhausted")


def core_conditions(config: ExperimentConfig) -> tuple[Condition, ...]:
    return tuple(
        Condition(f"core-{rate:02d}-{latency:03d}-{moves}", rate, latency, moves, FaultKind.NONE)
        for rate in config.timing.policy_rates_hz
        for latency in config.timing.latencies_ms
        for moves in config.conditions.move_counts
    )


def probe_conditions(config: ExperimentConfig) -> tuple[Condition, ...]:
    return (
        Condition("probe-drop", config.conditions.probe_policy_hz, config.conditions.probe_latency_ms, config.conditions.probe_move_count, FaultKind.DROP),
        Condition("probe-out-of-order", config.conditions.probe_policy_hz, config.conditions.probe_latency_ms, config.conditions.probe_move_count, FaultKind.OUT_OF_ORDER),
    )


def negative_control_condition(config: ExperimentConfig) -> Condition:
    return Condition("control-stationary", config.conditions.stationary_policy_hz, config.conditions.stationary_latency_ms, 0, FaultKind.STATIONARY_CONTROL)


def nearest_rank(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(item) for item in values if math.isfinite(float(item)))
    if not ordered:
        raise ValueError("percentile domain is empty")
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def compute_episode_metrics(
    recovery_times: Sequence[float | None],
    errors: np.ndarray,
    action_ages_s: np.ndarray,
    q_references: np.ndarray,
    saturation_ticks: int,
    total_ticks: int,
    unsafe_count: int,
    clamp_ticks: int,
    compute_ns: Sequence[int],
    config: ExperimentConfig,
) -> EpisodeMetrics:
    errors = np.asarray(errors, dtype=np.float64)
    ages = np.asarray(action_ages_s, dtype=np.float64)
    references = np.asarray(q_references, dtype=np.float64)
    if errors.ndim != 1 or not len(errors) or not np.isfinite(errors).all():
        raise ValueError("error domain is missing or nonfinite")
    if ages.ndim != 1 or not len(ages) or not np.isfinite(ages).all():
        raise ValueError("action age domain is missing or nonfinite")
    if references.ndim != 2 or references.shape[1:] != (3,) or len(references) < 2:
        raise ValueError("reference domain is missing")
    discontinuities = np.linalg.norm(np.diff(references, axis=0), axis=1)
    if len(references) >= 4:
        jerk = np.linalg.norm(np.diff(references, n=3, axis=0) / config.arm.timestep_s**3, axis=1)
    else:
        jerk = np.array([0.0])
    recovered = sum(value is not None for value in recovery_times)
    censored = [config.thresholds.recovery_censor_s if value is None else float(value) for value in recovery_times]
    compute = [float(item) for item in compute_ns]
    if not compute or total_ticks <= 0:
        raise ValueError("compute and tick domains must be nonempty")
    return EpisodeMetrics(
        recovery_s=float(np.mean(censored)),
        recovered_events=recovered,
        displacement_events=len(recovery_times),
        final_error_m=float(errors[-1]),
        mean_error_m=float(np.mean(errors)),
        p95_error_m=nearest_rank(errors, 0.95),
        age_p95_s=nearest_rank(ages, 0.95),
        jerk_p95=nearest_rank(jerk, 0.95),
        saturation_fraction=saturation_ticks / total_ticks,
        discontinuity_mean=float(np.mean(discontinuities)),
        discontinuity_p95=nearest_rank(discontinuities, 0.95),
        unsafe_count=unsafe_count,
        clamp_fraction=clamp_ticks / total_ticks,
        compute_p50_ns=int(nearest_rank(compute, 0.50)),
        compute_p95_ns=int(nearest_rank(compute, 0.95)),
    )


def aggregate_seed_metrics(stack_id: str, seed: int, records: Sequence[tuple[EpisodeMetrics, str]]) -> SeedMetrics:
    if len(records) != 24 or not all(metrics.valid for metrics, _ in records):
        return SeedMetrics(stack_id, seed, math.nan, False, tuple(item[1] for item in records))
    return SeedMetrics(stack_id, seed, float(np.mean([item[0].recovery_s for item in records])), True, tuple(item[1] for item in records))


def negative_control_passes(errors_after_1_5_s: np.ndarray, *, recovery_event: bool) -> bool:
    values = np.asarray(errors_after_1_5_s, dtype=np.float64)
    return bool(len(values) and np.isfinite(values).all() and np.all(values <= 0.025) and not recovery_event)


def run_episode(stack: CommandStack, condition: Condition, seed: int, config: ExperimentConfig) -> RolloutRecord:
    """Run one bounded simulator episode using only request-time target snapshots."""
    scenario = generate_scenario(seed, config)
    arm = PlanarArm(config)
    arm.reset(scenario.q0)
    rollout_id = f"{stack.value}-{condition.condition_id}-{seed:08d}"
    period_ticks = int(round(1.0 / condition.policy_hz / config.arm.timestep_s))
    latency_ticks = int(round(condition.latency_ms / 1000 / config.arm.timestep_s))
    targets = scenario.stationary_path if condition.fault is FaultKind.STATIONARY_CONTROL else (scenario.one_move_path if condition.move_count == 1 else scenario.two_move_path)
    target = np.array(targets[0], copy=True)
    pending: list[tuple[int, int, object]] = []
    observations: list[Observation] = []
    actions = []
    references = []
    events: list[ExecutionEvent] = []
    event_sequence = 0
    observation_sequence = 0
    active = None
    executor_state = initial_executor_state(scenario.q0)
    q_reference_previous = np.array(scenario.q0, copy=True)
    errors: list[float] = []
    ages: list[float] = []
    metric_references: list[np.ndarray] = []
    compute_times: list[int] = []
    saturation_ticks = clamp_ticks = unsafe_count = 0
    dropped = delayed = False

    def append_event(kind: ExecutionEventType, tick: int, payload: dict[str, object], *, skill_id: str | None = "track") -> None:
        nonlocal event_sequence
        events.append(ExecutionEvent(kind, tick * 2_000_000, tick * 2_000_000, rollout_id, event_sequence, "experiment01", "config-v1", ("target",), skill_id, payload))
        event_sequence += 1

    def snapshot(tick: int) -> Observation:
        nonlocal observation_sequence
        q, dq = arm.state()
        value = Observation(
            observation_sequence,
            tick * 2_000_000,
            tick * 2_000_000,
            RobotState(q, dq),
            (ObjectBelief("target", "target", np.array(target, copy=True), 1.0, {}, 1.0, tick * 2_000_000, ("synthetic",)),),
            "track",
            "track_target",
        )
        observation_sequence += 1
        observations.append(value)
        append_event(ExecutionEventType.OBSERVATION_RECEIVED, tick, {"observation_id": value.sequence_id, "observation_role": "policy_and_telemetry" if tick % period_ticks == 0 else "telemetry"})
        return value

    for tick in range(config.timing.episode_ticks):
        if tick == 1000 and len(targets) >= 2:
            target = np.array(targets[1], copy=True)
        if tick == 2000 and len(targets) >= 3:
            target = np.array(targets[2], copy=True)

        observation = snapshot(tick) if tick % 5 == 0 else None
        if tick % period_ticks == 0:
            if observation is None:
                observation = snapshot(tick)
            q, _ = arm.state()
            target_pose = Pose(np.array([target[0], target[1], 0.0]), np.array([1.0, 0.0, 0.0, 0.0]))
            skill = SkillSpec("track", "track_target", ("target",), target_pose, (Constraint("workspace", {"radius_m": 0.70}),), Predicate("eef_error", {"max_m": 0.025}), 6.25, 0)
            initial_q_target = absolute_ik(scenario.initial_target, scenario.q0, config.arm.link_lengths_m, config.controller.ik_damping_candidates[0], config)
            from .contracts import PolicyInput
            policy_input = PolicyInput(observation, skill, 0, period_ticks * 2_000_000, scenario.q0, initial_q_target)
            append_event(ExecutionEventType.POLICY_REQUESTED, tick, {"observation_id": observation.sequence_id, "drop_injection": False})
            should_inject = tick >= 1000
            if condition.fault is FaultKind.DROP and should_inject and not dropped:
                dropped = True
                events[-1] = ExecutionEvent(events[-1].event_type, events[-1].monotonic_time_ns, events[-1].wall_time_ns, rollout_id, events[-1].sequence_id, "experiment01", "config-v1", ("target",), "track", {"observation_id": observation.sequence_id, "drop_injection": True})
            else:
                extra = 0
                if condition.fault is FaultKind.OUT_OF_ORDER and should_inject and not delayed:
                    extra = period_ticks + 1
                    delayed = True
                pending.append((tick + latency_ticks + extra, observation.sequence_id, policy_input))

        for delivery_tick, source_id, captured in sorted(tuple(pending)):
            if delivery_tick != tick:
                continue
            pending.remove((delivery_tick, source_id, captured))
            captured = type(captured)(captured.observation, captured.skill, tick * 2_000_000, captured.policy_period_ns, captured.q_initial, captured.q_initial_target)
            started = time.perf_counter_ns()
            chunk = emit_chunk(stack, captured, config)
            compute_times.append(time.perf_counter_ns() - started)
            actions.append(chunk)
            append_event(ExecutionEventType.POLICY_RESPONDED, tick, {"chunk_id": chunk.chunk_id})
            if active is not None and source_id < active.source_observation_id:
                append_event(ExecutionEventType.CHUNK_REJECTED_OUT_OF_ORDER, tick, {"chunk_id": chunk.chunk_id})
            elif tick * 2_000_000 >= chunk.expires_at_ns:
                append_event(ExecutionEventType.CHUNK_REJECTED_EXPIRED, tick, {"chunk_id": chunk.chunk_id})
            else:
                if active is not None and tick * 2_000_000 < active.expires_at_ns:
                    append_event(ExecutionEventType.CHUNK_REPLACED, tick, {"chunk_id": active.chunk_id})
                active = chunk
                append_event(ExecutionEventType.CHUNK_ACCEPTED, tick, {"chunk_id": chunk.chunk_id})

        q, dq = arm.state()
        now_ns = tick * 2_000_000
        if active is not None and now_ns >= active.expires_at_ns:
            active = None
            executor_state = initial_executor_state(q)
        if active is None:
            requested = q
            torque = np.zeros(3)
            q_reference_previous = q
        else:
            reference, executor_state, report = reference_for_tick(stack, active, q, dq, now_ns, executor_state, config)
            requested = reference.q_ref
            q_ref, torque, pd_report = bounded_pd(q, dq, requested, q_reference_previous, config.controller.pd_candidates[0][0], config.controller.pd_candidates[0][1], config)
            q_reference_previous = q_ref
            clamp_ticks += int(report.reference_clamped or pd_report.reference_clamped or pd_report.joint_clamped)
            saturation_ticks += int(pd_report.torque_clamped)
            metric_references.append(np.array(q_ref, copy=True))
            ages.append((now_ns - active.source_observation_time_ns) / 1e9)
            if tick % 5 == 0:
                references.append(reference)
                append_event(ExecutionEventType.ACTION_EXECUTED, tick, {"source_chunk_id": reference.source_chunk_id})
        arm.step(torque)
        if tick >= 1000:
            error = float(np.linalg.norm(np.asarray(target) - arm.site_xy()))
            errors.append(error)

    if len(metric_references) < 4:
        metric_references = [scenario.q0] * 4
    if not ages:
        ages = [0.0]
    recovery_times: list[float | None] = []
    for start_index in (0, 1000)[: max(0, condition.move_count)]:
        domain = errors[start_index : start_index + 1000]
        recovered_at = None
        dwell = int(round(config.thresholds.success_dwell_s / config.arm.timestep_s))
        for index in range(max(0, len(domain) - dwell + 1)):
            if all(value <= config.thresholds.success_radius_m for value in domain[index : index + dwell]):
                recovered_at = index * config.arm.timestep_s
                break
        recovery_times.append(recovered_at)
    if not recovery_times:
        recovery_times = [0.0]
    metrics = compute_episode_metrics(recovery_times, np.asarray(errors or [0.0]), np.asarray(ages), np.asarray(metric_references), saturation_ticks, config.timing.episode_ticks, unsafe_count, clamp_ticks, compute_times or [0], config)
    metadata = RolloutMetadata(
        experiment_id="experiment-01", claim_revision=1, git_sha="0" * 40,
        working_tree_clean=True, dirty_diff_hash=None, source_lock_hash="0" * 64,
        os_arch="local", cpu="local", gpu=None, python_version="3.11.13",
        dependency_versions={"numpy": np.__version__}, seed=seed, simulator="mujoco",
        task_config_hash="0" * 64, model_hashes={}, action_schema_version=1,
        observation_schema_version=1, wall_start_ns=0, wall_end_ns=6_250_000_000,
        monotonic_start_ns=0, monotonic_end_ns=6_250_000_000, status="pass",
    )
    metric_wire = asdict(metrics) | {"condition_id": condition.condition_id, "stack_id": stack.value, "seed": seed}
    return RolloutRecord(metadata, {"condition_id": condition.condition_id, "stack_id": stack.value}, metric_wire, tuple(events), tuple(observations), tuple(actions), tuple(references), "Experiment 01 deterministic rollout.\n")
