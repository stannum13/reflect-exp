"""Scenario generation, empirical metrics, selection, and inference for Experiment 01."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
import hashlib
import math
import re
import time
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

import numpy as np

from reflect.rollout import RolloutMetadata, RolloutRecord, sha256_json
from reflect.types import Constraint, ObjectBelief, Observation, Pose, Predicate, RobotState, SkillSpec

from .contracts import (
    CommandStack,
    Condition,
    EpisodeMetrics,
    ExperimentConfig,
    FaultKind,
    PolicyInput,
    Scenario,
    SeedMetrics,
)
from .kinematics import absolute_ik, forward_kinematics
from .arm import PlanarArm, bounded_pd
from .representations import emit_chunk
from . import timing


_COMPASS = np.array(
    [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)],
    dtype=np.float64,
)
_COMPASS /= np.linalg.norm(_COMPASS, axis=1, keepdims=True)


@dataclass
class EpisodeTargetOwner:
    """The sole mutable owner of the simulator's live target."""

    scenario: Scenario
    current_target: np.ndarray

    @classmethod
    def from_scenario(cls, scenario: Scenario) -> "EpisodeTargetOwner":
        return cls(scenario, np.array(scenario.initial_target, dtype=np.float64, copy=True))

    def set_target(self, target: np.ndarray) -> None:
        value = np.array(target, dtype=np.float64, copy=True)
        if value.shape != (2,) or not np.isfinite(value).all():
            raise ValueError("live target must be a finite XY vector")
        self.current_target = value

    def snapshot(self) -> np.ndarray:
        result = np.array(self.current_target, dtype=np.float64, copy=True)
        result.setflags(write=False)
        return result


class ProposalDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    RADIUS_REJECTED = "RADIUS_REJECTED"
    IK_REJECTED = "IK_REJECTED"


@dataclass(frozen=True)
class ScenarioProposal:
    proposal_index: int
    q0: np.ndarray
    targets: np.ndarray
    disposition: ProposalDisposition

    def __post_init__(self) -> None:
        q0 = np.array(self.q0, dtype=np.float64, order="C", copy=True)
        targets = np.array(self.targets, dtype=np.float64, order="C", copy=True)
        if q0.shape != (3,) or targets.shape != (3, 2):
            raise ValueError("scenario proposal arrays have invalid shapes")
        q0.setflags(write=False)
        targets.setflags(write=False)
        object.__setattr__(self, "q0", q0)
        object.__setattr__(self, "targets", targets)
        object.__setattr__(self, "disposition", ProposalDisposition(self.disposition))


@dataclass(frozen=True)
class ScenarioRecord:
    scenario: Scenario
    proposals: tuple[ScenarioProposal, ...]
    rng_streams: tuple[str, str]
    identity_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, Scenario) or not self.proposals:
            raise ValueError("scenario record requires a scenario and proposal ledger")
        if self.proposals[-1].disposition is not ProposalDisposition.ACCEPTED:
            raise ValueError("scenario ledger must end in one accepted proposal")
        if any(item.disposition is ProposalDisposition.ACCEPTED for item in self.proposals[:-1]):
            raise ValueError("scenario ledger cannot continue after acceptance")
        object.__setattr__(self, "proposals", tuple(self.proposals))
        if self.rng_streams != ("q0", "directions"):
            raise ValueError("scenario RNG streams do not match the protocol")
        expected = sha256_json(_scenario_record_wire(self.scenario, self.proposals, self.rng_streams))
        if self.identity_sha256 != expected:
            raise ValueError("scenario identity hash mismatch")

    @property
    def seed(self) -> int:
        return self.scenario.seed

    @property
    def q0(self) -> np.ndarray:
        return self.scenario.q0

    @property
    def initial_target(self) -> np.ndarray:
        return self.scenario.initial_target

    @property
    def one_move_path(self) -> np.ndarray:
        return self.scenario.one_move_path

    @property
    def two_move_path(self) -> np.ndarray:
        return self.scenario.two_move_path

    @property
    def stationary_path(self) -> np.ndarray:
        return self.scenario.stationary_path


@dataclass(frozen=True)
class EpisodeIdentity:
    implementation_sha: str
    working_tree_clean: bool
    dirty_diff_hash: str | None
    source_lock_hash: str
    os_arch: str
    cpu: str
    gpu: str | None
    python_version: str
    dependency_versions: Mapping[str, str]
    task_config_hash: str
    model_hashes: Mapping[str, str]

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", self.implementation_sha) is None:
            raise ValueError("implementation_sha must be a lowercase 40-hex Git SHA")
        if re.fullmatch(r"[0-9a-f]{64}", self.source_lock_hash) is None:
            raise ValueError("source_lock_hash must be a lowercase SHA-256")
        if re.fullmatch(r"[0-9a-f]{64}", self.task_config_hash) is None:
            raise ValueError("task_config_hash must be a lowercase SHA-256")
        if type(self.working_tree_clean) is not bool or self.working_tree_clean != (self.dirty_diff_hash is None):
            raise ValueError("working tree identity is inconsistent")
        if self.dirty_diff_hash is not None and re.fullmatch(r"[0-9a-f]{64}", self.dirty_diff_hash) is None:
            raise ValueError("dirty_diff_hash must be a lowercase SHA-256")
        if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in self.model_hashes.values()):
            raise ValueError("model hashes must be lowercase SHA-256 values")
        for name in ("os_arch", "cpu", "python_version"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be nonempty")
        object.__setattr__(self, "dependency_versions", MappingProxyType(dict(self.dependency_versions)))
        object.__setattr__(self, "model_hashes", MappingProxyType(dict(self.model_hashes)))


@dataclass(frozen=True)
class RawTick:
    tick: int
    error_m: float
    q_ref: tuple[float, float, float]
    dq_ref: tuple[float, float, float]
    chunk_valid: bool
    safe_hold: bool
    torque_saturated: bool
    reference_clamped: bool
    recovery_dwell: bool
    policy_compute_ns: int
    controller_compute_ns: int


def _rng(seed: int, namespace: str) -> np.random.Generator:
    digest = hashlib.sha256(f"{seed}:{namespace}".encode()).digest()
    return np.random.Generator(np.random.PCG64(int.from_bytes(digest[:16], "big")))


def _scenario_record_wire(
    scenario: Scenario,
    proposals: Sequence[ScenarioProposal],
    rng_streams: tuple[str, str],
) -> dict[str, object]:
    return {
        "seed": scenario.seed,
        "rng_streams": list(rng_streams),
        "scenario": {
            "q0": scenario.q0,
            "initial_target": scenario.initial_target,
            "one_move_path": scenario.one_move_path,
            "two_move_path": scenario.two_move_path,
            "stationary_path": scenario.stationary_path,
        },
        "proposals": [
            {
                "proposal_index": item.proposal_index,
                "q0": item.q0,
                "targets": item.targets,
                "disposition": item.disposition.value,
            }
            for item in proposals
        ],
    }


def generate_scenario(seed: int, config: ExperimentConfig) -> ScenarioRecord:
    q_rng, direction_rng = _rng(seed, "q0"), _rng(seed, "directions")
    proposals: list[ScenarioProposal] = []
    for proposal_index in range(32):
        q0 = np.array([0.35, -0.70, 0.35]) + q_rng.uniform(-0.08, 0.08, 3)
        xy0 = forward_kinematics(q0, config.arm.link_lengths_m)
        initial = xy0 + 0.04 * _COMPASS[int(direction_rng.integers(0, 8))]
        move1 = initial + 0.06 * _COMPASS[int(direction_rng.integers(0, 8))]
        move2 = move1 + 0.06 * _COMPASS[int(direction_rng.integers(0, 8))]
        targets = (initial, move1, move2)
        target_array = np.vstack(targets)
        radii = [float(np.linalg.norm(item)) for item in targets]
        if not all(0.30 <= radius <= 0.70 for radius in radii):
            proposals.append(ScenarioProposal(proposal_index, q0, target_array, ProposalDisposition.RADIUS_REJECTED))
            continue
        solutions = [absolute_ik(item, q0, config.arm.link_lengths_m, 0.01, config) for item in targets]
        if not all(np.all(np.abs(solution) <= 2.55) for solution in solutions):
            proposals.append(ScenarioProposal(proposal_index, q0, target_array, ProposalDisposition.IK_REJECTED))
            continue
        proposals.append(ScenarioProposal(proposal_index, q0, target_array, ProposalDisposition.ACCEPTED))
        scenario = Scenario(seed, q0, initial, np.vstack((initial, move1)), target_array, np.vstack((initial, initial)))
        streams = ("q0", "directions")
        identity = sha256_json(_scenario_record_wire(scenario, proposals, streams))
        return ScenarioRecord(scenario, tuple(proposals), streams, identity)
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
    q_references: np.ndarray | Sequence[np.ndarray],
    saturation_ticks: int,
    total_ticks: int,
    unsafe_count: int,
    clamp_ticks: int,
    compute_ns: Sequence[int],
    config: ExperimentConfig,
) -> EpisodeMetrics:
    errors = np.asarray(errors, dtype=np.float64)
    ages = np.asarray(action_ages_s, dtype=np.float64)
    if errors.ndim != 1 or not len(errors) or not np.isfinite(errors).all():
        raise ValueError("error domain is missing or nonfinite")
    if ages.ndim != 1 or not len(ages) or not np.isfinite(ages).all():
        raise ValueError("action age domain is missing or nonfinite")
    if isinstance(q_references, np.ndarray):
        reference_segments = (np.asarray(q_references, dtype=np.float64),)
    else:
        reference_segments = tuple(np.asarray(item, dtype=np.float64) for item in q_references)
    usable = tuple(item for item in reference_segments if item.ndim == 2 and item.shape[1:] == (3,) and len(item) >= 2)
    if not usable or len(usable) != len(reference_segments):
        raise ValueError("reference domain is missing")
    discontinuities = np.concatenate([np.linalg.norm(np.diff(item, axis=0), axis=1) for item in usable])
    jerk_domains = [np.linalg.norm(np.diff(item, n=3, axis=0) / config.arm.timestep_s**3, axis=1) for item in usable if len(item) >= 4]
    jerk = np.concatenate(jerk_domains) if jerk_domains else np.array([0.0])
    recovered = sum(value is not None for value in recovery_times)
    censored = [config.thresholds.recovery_censor_s if value is None else float(value) for value in recovery_times]
    compute = [float(item) for item in compute_ns]
    if not compute or total_ticks <= 0:
        raise ValueError("compute and tick domains must be nonempty")
    return EpisodeMetrics(
        recovery_s=float(np.mean(censored)) if censored else 0.0,
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


def _raw_tick_wire(rows: Sequence[RawTick]) -> dict[str, object]:
    return {
        "tick": [item.tick for item in rows],
        "error_m": [item.error_m for item in rows],
        "q_ref": [list(item.q_ref) for item in rows],
        "dq_ref": [list(item.dq_ref) for item in rows],
        "chunk_valid": [item.chunk_valid for item in rows],
        "safe_hold": [item.safe_hold for item in rows],
        "torque_saturated": [item.torque_saturated for item in rows],
        "reference_clamped": [item.reference_clamped for item in rows],
        "recovery_dwell": [item.recovery_dwell for item in rows],
        "policy_compute_ns": [item.policy_compute_ns for item in rows],
        "controller_compute_ns": [item.controller_compute_ns for item in rows],
    }


def run_episode(
    stack: CommandStack,
    condition: Condition,
    scenario_record: ScenarioRecord,
    config: ExperimentConfig,
    identity: EpisodeIdentity,
) -> RolloutRecord:
    """Run one bounded episode from a preregistered immutable scenario record."""
    stack = CommandStack(stack)
    scenario = scenario_record.scenario
    if identity.task_config_hash != sha256_json(timing.scheduler_config(config)):
        raise ValueError("injected task config hash does not match the experiment config")
    target_owner = EpisodeTargetOwner.from_scenario(scenario)
    arm = PlanarArm(config)
    arm.reset(scenario.q0)
    rollout_id = f"{stack.value}-{condition.condition_id}-{scenario.seed:08d}"
    period_ticks = int(round(1.0 / condition.policy_hz / config.arm.timestep_s))
    latency_ticks = int(round(condition.latency_ms / 1000 / config.arm.timestep_s))
    fault_extra_ticks = period_ticks + 1 if condition.fault is FaultKind.OUT_OF_ORDER else 0
    request_cutoff = timing.last_request_tick(config.timing.episode_ticks, latency_ticks, fault_extra_ticks, period_ticks)
    targets = scenario.stationary_path if condition.fault is FaultKind.STATIONARY_CONTROL else (scenario.one_move_path if condition.move_count == 1 else scenario.two_move_path)
    target_owner.set_target(targets[0])
    scheduler = timing.SchedulerState.initial(scenario.q0, config, rollout_id=rollout_id)
    q_reference_previous = np.array(scenario.q0, copy=True)
    observation_sequence = 0
    errors: list[float] = []
    ages: list[float] = []
    raw_rows: list[RawTick] = []
    reference_segments: list[np.ndarray] = []
    current_segment: list[np.ndarray] = []
    policy_compute_times: list[int] = []
    controller_compute_times: list[int] = []
    saturation_ticks = clamp_ticks = unsafe_count = 0
    dropped = delayed = False
    dropped_request_ids: list[int] = []
    initial_q_target = absolute_ik(scenario.initial_target, scenario.q0, config.arm.link_lengths_m, config.controller.ik_damping_candidates[0], config)

    def snapshot(tick: int, q: np.ndarray, dq: np.ndarray) -> Observation:
        nonlocal observation_sequence
        target = target_owner.snapshot()
        result = Observation(
            observation_sequence,
            tick * 2_000_000,
            tick * 2_000_000,
            RobotState(q, dq),
            (ObjectBelief("target", "target", target, 1.0, {}, 1.0, tick * 2_000_000, ("scenario-record",)),),
            "track",
            "track_target",
        )
        observation_sequence += 1
        return result

    for tick in range(config.timing.episode_ticks):
        if tick == 1000 and len(targets) >= 2:
            target_owner.set_target(targets[1])
        if tick == 2000 and len(targets) >= 3:
            target_owner.set_target(targets[2])
        q, dq = arm.state()
        scheduler = replace(scheduler, q=q, dq=dq)
        observation = snapshot(tick, q, dq) if tick % 5 == 0 else None
        request = None
        drop = False
        extra_delay = 0
        policy_elapsed = 0
        if tick % period_ticks == 0 and tick <= request_cutoff:
            if observation is None:
                observation = snapshot(tick, q, dq)
            should_inject = tick >= 1000
            drop = condition.fault is FaultKind.DROP and should_inject and not dropped
            if drop:
                dropped = True
                dropped_request_ids.append(observation.sequence_id)
            elif condition.fault is FaultKind.OUT_OF_ORDER and should_inject and not delayed:
                delayed = True
                extra_delay = period_ticks + 1
            response_tick = tick + latency_ticks + extra_delay
            target = target_owner.snapshot()
            skill = SkillSpec(
                "track", "track_target", ("target",),
                Pose(np.array([target[0], target[1], 0.0]), np.array([1.0, 0.0, 0.0, 0.0])),
                (Constraint("workspace", {"radius_m": 0.70}),),
                Predicate("eef_error", {"max_m": 0.025}), 6.25, 0,
            )
            captured = PolicyInput(observation, skill, response_tick * 2_000_000, period_ticks * 2_000_000, scenario.q0, initial_q_target)
            started = time.perf_counter_ns()
            chunk = emit_chunk(stack, captured, config)
            policy_elapsed = time.perf_counter_ns() - started
            if not drop:
                policy_compute_times.append(policy_elapsed)
            request = timing.PolicyRequest(observation, tick, period_ticks, chunk)
        transition = timing.transition_tick(
            scheduler,
            config,
            request=request,
            latency_ticks=latency_ticks,
            drop=drop,
            extra_delay_ticks=extra_delay,
            telemetry=observation,
            planner_due=tick % int(round(config.controller.mpc_period_s / config.arm.timestep_s)) == 0,
            record_execution=tick % 5 == 0,
        )
        scheduler = transition.state
        if transition.control_reference is not None:
            command_q = transition.control_reference.q_ref
            command_dq = transition.control_reference.dq_ref
            representation_clamped = bool(transition.control_report and transition.control_report.reference_clamped)
            active = scheduler.active_chunk
        else:
            if transition.safe_hold_command is None:
                raise RuntimeError("scheduler returned neither control nor safe hold")
            command_q = transition.safe_hold_command.q_ref
            command_dq = transition.safe_hold_command.dq_ref
            representation_clamped = False
            active = None
        controller_started = time.perf_counter_ns()
        previous_for_pd = command_q if transition.safe_hold else q_reference_previous
        q_ref, torque, pd_report = bounded_pd(
            q, dq, command_q, previous_for_pd,
            config.controller.pd_candidates[0][0], config.controller.pd_candidates[0][1], config,
        )
        controller_elapsed = time.perf_counter_ns() - controller_started
        controller_compute_times.append(controller_elapsed)
        q_reference_previous = np.array(q_ref, copy=True)
        reference_clamped = representation_clamped or pd_report.reference_clamped or pd_report.joint_clamped
        clamp_ticks += int(reference_clamped)
        saturation_ticks += int(pd_report.torque_clamped)
        vectors = (q, dq, command_q, command_dq, q_ref, torque)
        if any(np.asarray(item).shape != (3,) or not np.isfinite(item).all() for item in vectors):
            unsafe_count += 1
        if np.any(q_ref < config.arm.joint_min_rad) or np.any(q_ref > config.arm.joint_max_rad):
            unsafe_count += 1
        if tick >= 1000:
            if active is not None:
                current_segment.append(np.array(q_ref, copy=True))
            elif current_segment:
                if len(current_segment) >= 2:
                    reference_segments.append(np.asarray(current_segment))
                current_segment = []
        if active is not None and tick % 5 == 0:
            ages.append((tick * 2_000_000 - active.source_observation_time_ns) / 1e9)
        arm.step(torque)
        error = float(np.linalg.norm(target_owner.snapshot() - arm.site_xy()))
        errors.append(error)
        raw_rows.append(
            RawTick(
                tick,
                error,
                tuple(float(item) for item in q_ref),
                tuple(float(item) for item in command_dq),
                active is not None,
                transition.safe_hold,
                pd_report.torque_clamped,
                reference_clamped,
                error <= config.thresholds.success_radius_m,
                policy_elapsed,
                controller_elapsed,
            )
        )
    if current_segment and len(current_segment) >= 2:
        reference_segments.append(np.asarray(current_segment))
    timing.validate_terminal_state(scheduler, allowed_dropped_requests=tuple(dropped_request_ids))

    recovery_times: list[float | None] = []
    dwell = int(round(config.thresholds.success_dwell_s / config.arm.timestep_s))
    for displacement_tick in (1000, 2000)[: condition.move_count]:
        domain = errors[displacement_tick : displacement_tick + 1000]
        recovered_at = None
        for index in range(max(0, len(domain) - dwell + 1)):
            if all(value <= config.thresholds.success_radius_m for value in domain[index : index + dwell]):
                recovered_at = index * config.arm.timestep_s
                break
        recovery_times.append(recovered_at)
    metric_errors = np.asarray(errors[750:] if condition.fault is FaultKind.STATIONARY_CONTROL else errors[1000:])
    metrics = compute_episode_metrics(
        recovery_times,
        metric_errors,
        np.asarray(ages),
        tuple(reference_segments),
        saturation_ticks,
        config.timing.episode_ticks,
        unsafe_count,
        clamp_ticks,
        policy_compute_times,
        config,
    )
    negative_valid = True
    if condition.fault is FaultKind.STATIONARY_CONTROL:
        negative_valid = negative_control_passes(np.asarray(errors[750:]), recovery_event=bool(recovery_times))
    metrics = replace(metrics, valid=metrics.valid and negative_valid and unsafe_count == 0)
    duration_ns = int(round(config.timing.episode_ticks * config.arm.timestep_s * 1e9))
    metadata = RolloutMetadata(
        experiment_id="experiment-01", claim_revision=1,
        git_sha=identity.implementation_sha, working_tree_clean=identity.working_tree_clean,
        dirty_diff_hash=identity.dirty_diff_hash, source_lock_hash=identity.source_lock_hash,
        os_arch=identity.os_arch, cpu=identity.cpu, gpu=identity.gpu,
        python_version=identity.python_version, dependency_versions=identity.dependency_versions,
        seed=scenario.seed, simulator="mujoco", task_config_hash=identity.task_config_hash,
        model_hashes=identity.model_hashes, action_schema_version=1, observation_schema_version=1,
        wall_start_ns=0, wall_end_ns=duration_ns, monotonic_start_ns=0,
        monotonic_end_ns=duration_ns, status="pass" if metrics.valid else "fail",
    )
    metric_wire = asdict(metrics) | {
        "condition_id": condition.condition_id,
        "stack_id": stack.value,
        "seed": scenario.seed,
        "scenario_identity_sha256": scenario_record.identity_sha256,
        "scenario_record": _scenario_record_wire(
            scenario_record.scenario,
            scenario_record.proposals,
            scenario_record.rng_streams,
        ),
        "request_cutoff_tick": request_cutoff,
        "terminal_queue_count": len(scheduler.queue),
        "terminal_unmatched_request_ids": list(scheduler.unmatched_requests),
        "declared_dropped_request_ids": list(scheduler.declared_dropped_requests),
        "policy_compute_series_ns": policy_compute_times,
        "controller_compute_series_ns": controller_compute_times,
        "controller_compute_p50_ns": int(nearest_rank(controller_compute_times, 0.50)),
        "controller_compute_p95_ns": int(nearest_rank(controller_compute_times, 0.95)),
        "raw_500hz": _raw_tick_wire(raw_rows),
    }
    return RolloutRecord(
        metadata,
        timing.scheduler_config(config),
        metric_wire,
        scheduler.events,
        scheduler.observations,
        scheduler.actions,
        scheduler.control_references,
        "Experiment 01 deterministic rollout.\n",
    )
