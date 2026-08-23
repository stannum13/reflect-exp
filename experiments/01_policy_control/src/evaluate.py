"""Scenario generation, empirical metrics, selection, and inference for Experiment 01."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
import hashlib
import math
from pathlib import Path
import re
import time
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

import numpy as np

from reflect.rollout import RolloutMetadata, RolloutRecord, canonical_json_bytes, sha256_json
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


class PilotStage(str, Enum):
    BASE = "base"
    PD_60_6 = "pd_60_6"
    PD_100_10 = "pd_100_10"
    IK_0_001 = "ik_0_001"
    IK_0_05 = "ik_0_05"
    P5_0_01 = "p5_0_01"
    P5_0_04 = "p5_0_04"
    FINAL_FOUR = "final_four"


_PILOT_STAGE_ORDER = tuple(PilotStage)
_STACK_ORDER = tuple(item.value for item in CommandStack)


def pilot_stage_order() -> tuple[PilotStage, ...]:
    return _PILOT_STAGE_ORDER


def _hash(value: object, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


@dataclass(frozen=True)
class StackSeedScore:
    stack_id: str
    seed: int
    condition_bundle_sha256s: tuple[str, str, str]
    score: float

    def __post_init__(self) -> None:
        if self.stack_id not in _STACK_ORDER or type(self.seed) is not int or self.seed < 0:
            raise ValueError("stack/seed score identity is invalid")
        hashes = tuple(_hash(item, "condition bundle hash") for item in self.condition_bundle_sha256s)
        if len(hashes) != 3 or not math.isfinite(float(self.score)):
            raise ValueError("stack/seed score requires three bundles and a finite score")
        object.__setattr__(self, "condition_bundle_sha256s", hashes)
        object.__setattr__(self, "score", float(self.score))


@dataclass(frozen=True)
class PilotCandidate:
    stage: PilotStage
    parameter_vector: Mapping[str, object]
    parameter_hash: str
    fixed_survivors: tuple[str, ...]
    feasible: bool
    reuse_hashes: tuple[str, ...]
    stack_seed_scores: tuple[StackSeedScore, ...]
    global_score: float | None
    tie_rank: int
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", PilotStage(self.stage))
        vector = dict(self.parameter_vector)
        if set(vector) != {"pd", "ik", "p5_smoothness"}:
            raise ValueError("parameter vector schema is not closed")
        pd = vector["pd"]
        if not isinstance(pd, (tuple, list)) or len(pd) != 2:
            raise ValueError("parameter vector PD must contain two values")
        normalized = {"pd": [float(pd[0]), float(pd[1])], "ik": float(vector["ik"]), "p5_smoothness": float(vector["p5_smoothness"])}
        if not all(math.isfinite(value) for value in (*normalized["pd"], normalized["ik"], normalized["p5_smoothness"])):
            raise ValueError("parameter vector must be finite")
        object.__setattr__(self, "parameter_vector", MappingProxyType(normalized))
        if self.parameter_hash != sha256_json(normalized):
            raise ValueError("parameter hash does not bind the parameter vector")
        survivors = tuple(self.fixed_survivors)
        if tuple(sorted(survivors, key=_STACK_ORDER.index)) != survivors or len(set(survivors)) != len(survivors):
            raise ValueError("fixed survivors must be unique in P1-P6 order")
        object.__setattr__(self, "fixed_survivors", survivors)
        reuse = tuple(_hash(item, "reuse hash") for item in self.reuse_hashes)
        object.__setattr__(self, "reuse_hashes", reuse)
        scores = tuple(sorted(self.stack_seed_scores, key=lambda item: (_STACK_ORDER.index(item.stack_id), item.seed)))
        if len({(item.stack_id, item.seed) for item in scores}) != len(scores):
            raise ValueError("stack/seed scores must be unique")
        object.__setattr__(self, "stack_seed_scores", scores)
        expected_rank = _PILOT_STAGE_ORDER.index(self.stage) + 1
        if type(self.feasible) is not bool or self.tie_rank != expected_rank:
            raise ValueError("candidate feasibility/tie rank is invalid")
        if self.feasible != (self.global_score is not None):
            raise ValueError("feasible candidate must have exactly one global score")
        if self.global_score is not None and not math.isfinite(float(self.global_score)):
            raise ValueError("global score must be finite or null")
        reasons = tuple(self.reasons)
        if self.feasible and reasons:
            raise ValueError("feasible candidate cannot carry failure reasons")
        if not self.feasible and not reasons:
            raise ValueError("infeasible candidate requires a reason")
        object.__setattr__(self, "reasons", reasons)


def _candidate_vector(stage: PilotStage) -> dict[str, object]:
    vectors: dict[PilotStage, dict[str, object]] = {
        PilotStage.BASE: {"pd": [80.0, 8.0], "ik": 0.01, "p5_smoothness": 0.02},
        PilotStage.PD_60_6: {"pd": [60.0, 6.0], "ik": 0.01, "p5_smoothness": 0.02},
        PilotStage.PD_100_10: {"pd": [100.0, 10.0], "ik": 0.01, "p5_smoothness": 0.02},
        PilotStage.IK_0_001: {"pd": [80.0, 8.0], "ik": 0.001, "p5_smoothness": 0.02},
        PilotStage.IK_0_05: {"pd": [80.0, 8.0], "ik": 0.05, "p5_smoothness": 0.02},
        PilotStage.P5_0_01: {"pd": [80.0, 8.0], "ik": 0.01, "p5_smoothness": 0.01},
        PilotStage.P5_0_04: {"pd": [80.0, 8.0], "ik": 0.01, "p5_smoothness": 0.04},
        PilotStage.FINAL_FOUR: {"pd": [80.0, 8.0], "ik": 0.01, "p5_smoothness": 0.02},
    }
    return vectors[stage]


@dataclass(frozen=True)
class PilotParameterSpec:
    stage: PilotStage
    parameter_vector: Mapping[str, object]
    parameter_hash: str
    tie_rank: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", PilotStage(self.stage))
        vector = dict(self.parameter_vector)
        if self.parameter_hash != sha256_json(vector):
            raise ValueError("parameter spec hash mismatch")
        object.__setattr__(self, "parameter_vector", MappingProxyType(vector))
        if type(self.tie_rank) is not int or self.tie_rank <= 0:
            raise ValueError("parameter spec tie rank must be positive")


def pilot_candidates(
    *,
    selected_pd: tuple[float, float] = (80.0, 8.0),
    selected_ik: float = 0.01,
    selected_p5_smoothness: float = 0.02,
) -> tuple[PilotParameterSpec, ...]:
    result = []
    for rank, stage in enumerate(_PILOT_STAGE_ORDER, start=1):
        vector = _candidate_vector(stage)
        if stage in {PilotStage.IK_0_001, PilotStage.IK_0_05, PilotStage.P5_0_01, PilotStage.P5_0_04, PilotStage.FINAL_FOUR}:
            vector["pd"] = list(selected_pd)
        if stage in {PilotStage.P5_0_01, PilotStage.P5_0_04, PilotStage.FINAL_FOUR}:
            vector["ik"] = selected_ik
        if stage is PilotStage.FINAL_FOUR:
            vector["p5_smoothness"] = selected_p5_smoothness
        result.append(PilotParameterSpec(stage, vector, sha256_json(vector), rank))
    return tuple(result)


_TUNING_CONDITION_IDS = ("tune-05-700-2", "tune-10-300-2", "tune-20-000-1")


@dataclass(frozen=True)
class PilotEpisodeScore:
    stack_id: str
    seed: int
    condition_id: str
    bundle_sha256: str
    recovery_s: float | None
    valid: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.stack_id not in _STACK_ORDER or type(self.seed) is not int or self.seed < 0:
            raise ValueError("pilot episode score identity is invalid")
        if self.condition_id not in _TUNING_CONDITION_IDS:
            raise ValueError("pilot episode is outside the tuning subset")
        _hash(self.bundle_sha256, "episode bundle hash")
        if self.valid != (self.recovery_s is not None):
            raise ValueError("valid pilot episode requires exactly one recovery score")
        if self.recovery_s is not None and (not math.isfinite(float(self.recovery_s)) or self.recovery_s < 0):
            raise ValueError("pilot recovery score must be finite and nonnegative")
        if self.valid != (self.reason is None):
            raise ValueError("invalid pilot episode requires exactly one reason")


def evaluate_candidate(
    stage: PilotStage,
    parameter_vector: Mapping[str, object],
    survivors: Sequence[str],
    episodes: Sequence[PilotEpisodeScore],
    *,
    predecessor_candidate: PilotCandidate | None = None,
) -> PilotCandidate:
    stage = PilotStage(stage)
    vector = dict(parameter_vector)
    allowed_pd = ([80.0, 8.0], [60.0, 6.0], [100.0, 10.0])
    allowed_ik = (0.01, 0.001, 0.05)
    allowed_smoothness = (0.02, 0.01, 0.04)
    stage_scalar = {
        PilotStage.BASE: ([80.0, 8.0], 0.01, 0.02),
        PilotStage.PD_60_6: ([60.0, 6.0], 0.01, 0.02),
        PilotStage.PD_100_10: ([100.0, 10.0], 0.01, 0.02),
        PilotStage.IK_0_001: (None, 0.001, 0.02),
        PilotStage.IK_0_05: (None, 0.05, 0.02),
        PilotStage.P5_0_01: (None, None, 0.01),
        PilotStage.P5_0_04: (None, None, 0.04),
        PilotStage.FINAL_FOUR: (None, None, None),
    }[stage]
    if (
        set(vector) != {"pd", "ik", "p5_smoothness"}
        or vector.get("pd") not in allowed_pd or vector.get("ik") not in allowed_ik
        or vector.get("p5_smoothness") not in allowed_smoothness
        or (stage_scalar[0] is not None and vector.get("pd") != stage_scalar[0])
        or (stage_scalar[1] is not None and vector.get("ik") != stage_scalar[1])
        or (stage_scalar[2] is not None and vector.get("p5_smoothness") != stage_scalar[2])
    ):
        raise ValueError("candidate parameter vector does not match the frozen stage")
    fixed = tuple(survivors)
    needs_predecessor = stage in {
        PilotStage.IK_0_001, PilotStage.IK_0_05, PilotStage.P5_0_01,
        PilotStage.P5_0_04, PilotStage.FINAL_FOUR,
    }
    if needs_predecessor != (predecessor_candidate is not None):
        raise ValueError("candidate predecessor selection evidence is missing or unexpected")
    reuse: tuple[str, ...] = ()
    if predecessor_candidate is not None:
        predecessor_vector = dict(predecessor_candidate.parameter_vector)
        if vector["pd"] != predecessor_vector["pd"]:
            raise ValueError("candidate PD does not derive from the selected predecessor")
        if stage in {PilotStage.P5_0_01, PilotStage.P5_0_04, PilotStage.FINAL_FOUR} and vector["ik"] != predecessor_vector["ik"]:
            raise ValueError("candidate IK does not derive from the selected predecessor")
        if stage is PilotStage.FINAL_FOUR and vector["p5_smoothness"] != predecessor_vector["p5_smoothness"]:
            raise ValueError("final-four vector does not equal the selected predecessor")
        source_scores = predecessor_candidate.stack_seed_scores
        if stage in {PilotStage.P5_0_01, PilotStage.P5_0_04}:
            source_scores = tuple(item for item in source_scores if item.stack_id == "P5")
        reuse = tuple(
            digest for score in source_scores for digest in score.condition_bundle_sha256s
        )
    rows = tuple(episodes)
    expected = {(stack, seed, condition) for stack in fixed for seed in range(4) for condition in _TUNING_CONDITION_IDS}
    actual = {(item.stack_id, item.seed, item.condition_id) for item in rows}
    invalid = [item for item in rows if not item.valid]
    reasons: list[str] = []
    if actual != expected:
        reasons.append("INCOMPLETE_FIXED_SURVIVOR_DOMAIN")
    reasons.extend(f"{item.bundle_sha256}:{item.reason}" for item in invalid)
    scores = []
    if not reasons:
        for stack in fixed:
            for seed in range(4):
                domain = sorted(
                    (item for item in rows if item.stack_id == stack and item.seed == seed),
                    key=lambda item: _TUNING_CONDITION_IDS.index(item.condition_id),
                )
                scores.append(StackSeedScore(stack, seed, tuple(item.bundle_sha256 for item in domain), float(np.mean([item.recovery_s for item in domain]))))
    global_score = None
    if not reasons:
        stack_means = [float(np.mean([item.score for item in scores if item.stack_id == stack])) for stack in fixed]
        global_score = float(np.mean(stack_means))
    return PilotCandidate(
        stage,
        vector,
        sha256_json(vector),
        fixed,
        not reasons,
        reuse,
        tuple(scores),
        global_score,
        _PILOT_STAGE_ORDER.index(stage) + 1,
        tuple(reasons),
    )


def _score_candidate(candidate: PilotCandidate, survivors: tuple[str, ...]) -> float:
    expected = {(stack, seed) for stack in survivors for seed in range(4)}
    actual = {(item.stack_id, item.seed) for item in candidate.stack_seed_scores}
    if actual != expected:
        raise ValueError("candidate stack/seed domain is incomplete")
    stack_means = []
    for stack in survivors:
        stack_means.append(float(np.mean([item.score for item in candidate.stack_seed_scores if item.stack_id == stack])))
    return float(np.mean(stack_means))


def select_global_candidate(candidates: Sequence[PilotCandidate], survivors: Sequence[str]) -> PilotCandidate:
    fixed = tuple(survivors)
    if not fixed or not candidates:
        raise ValueError("selection requires candidates and fixed survivors")
    scored: list[tuple[float, int, PilotCandidate]] = []
    for candidate in candidates:
        if candidate.fixed_survivors != fixed:
            raise ValueError("candidate survivor domain changed during selection")
        if candidate.feasible:
            score = _score_candidate(candidate, fixed)
            if not math.isclose(score, float(candidate.global_score), rel_tol=0.0, abs_tol=1e-15):
                raise ValueError("candidate global score does not match stack/seed evidence")
            scored.append((score, candidate.tie_rank, candidate))
    if not scored:
        raise ValueError("no feasible global candidate")
    return min(scored, key=lambda item: (item[0], item[1]))[2]


def select_p5_smoothness(candidates: Sequence[PilotCandidate]) -> PilotCandidate | None:
    feasible = [item for item in candidates if item.feasible]
    if not feasible:
        return None
    return select_global_candidate(candidates, (CommandStack.P5.value,))


@dataclass(frozen=True)
class BaseStackOutcome:
    stack_id: str
    episode_count: int
    hard_failure: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class BaseQualification:
    survivors: tuple[str, ...]
    killed_stacks: tuple[str, ...]
    lifecycle_state: str
    scientific_result: str
    reasons: tuple[str, ...]


_PILOT_SELECTION_SEAL = object()


@dataclass(frozen=True, init=False)
class PilotSelectionEvidence:
    base_qualification: BaseQualification
    selected_pd: PilotCandidate
    selected_ik: PilotCandidate
    selected_p5: PilotCandidate | None
    candidate_evaluations_sha256: str

    def __init__(
        self, base_qualification: BaseQualification, selected_pd: PilotCandidate,
        selected_ik: PilotCandidate, selected_p5: PilotCandidate | None,
        candidate_evaluations_sha256: str, *, _seal: object,
    ) -> None:
        if _seal is not _PILOT_SELECTION_SEAL:
            raise ValueError("pilot selection evidence must be mechanically derived")
        object.__setattr__(self, "base_qualification", base_qualification)
        object.__setattr__(self, "selected_pd", selected_pd)
        object.__setattr__(self, "selected_ik", selected_ik)
        object.__setattr__(self, "selected_p5", selected_p5)
        object.__setattr__(self, "candidate_evaluations_sha256", _hash(
            candidate_evaluations_sha256, "candidate evaluations hash",
        ))

    @property
    def survivors(self) -> tuple[str, ...]:
        return tuple(
            stack for stack in self.base_qualification.survivors
            if stack != "P5" or self.selected_p5 is not None
        )

    @property
    def killed_stacks(self) -> tuple[str, ...]:
        extra = ("P5",) if "P5" in self.base_qualification.survivors and self.selected_p5 is None else ()
        return tuple(sorted((*self.base_qualification.killed_stacks, *extra), key=_STACK_ORDER.index))


def derive_pilot_selection(
    pd_inputs: Sequence["CandidateReproductionInput"],
    ik_inputs: Sequence["CandidateReproductionInput"],
    p5_inputs: Sequence["CandidateReproductionInput"],
) -> PilotSelectionEvidence:
    pd_raw = tuple(pd_inputs)
    if not all(isinstance(item, CandidateReproductionInput) for item in pd_raw):
        raise ValueError("pilot selection accepts only raw episode-bearing candidate inputs")
    if tuple(item.stage for item in pd_raw) != (
        PilotStage.BASE, PilotStage.PD_60_6, PilotStage.PD_100_10,
    ) or any(item.predecessor_candidate is not None for item in pd_raw):
        raise ValueError("PD selection requires exact raw candidate inputs without caller predecessors")
    base_rows = tuple(pd_raw[0].episodes)
    base_outcomes = tuple(BaseStackOutcome(
        stack,
        sum(item.stack_id == stack for item in base_rows),
        any(item.stack_id == stack and not item.valid for item in base_rows),
        tuple(item.reason for item in base_rows if item.stack_id == stack and item.reason is not None),
    ) for stack in _STACK_ORDER)
    qualification = qualify_base(base_outcomes)
    if qualification.lifecycle_state != "RUNNING":
        raise ValueError("terminal base qualification cannot produce adaptive selection")
    pd = tuple(evaluate_candidate(
        item.stage,
        item.parameter_vector,
        qualification.survivors,
        tuple(row for row in item.episodes if row.stack_id in qualification.survivors),
    ) for item in pd_raw)
    selected_pd = select_global_candidate(pd, qualification.survivors)
    ik_raw = tuple(ik_inputs)
    if not all(isinstance(item, CandidateReproductionInput) for item in ik_raw):
        raise ValueError("IK selection accepts only raw episode-bearing candidate inputs")
    if tuple(item.stage for item in ik_raw) != (PilotStage.IK_0_001, PilotStage.IK_0_05) or any(
        item.predecessor_candidate is not None or item.survivors != qualification.survivors
        for item in ik_raw
    ):
        raise ValueError("IK selection requires exact raw alternatives without caller predecessors")
    ik = tuple(evaluate_candidate(
        item.stage, item.parameter_vector, qualification.survivors, item.episodes,
        predecessor_candidate=selected_pd,
    ) for item in ik_raw)
    selected_ik = select_global_candidate((selected_pd, *ik), qualification.survivors)
    p5_raw = tuple(p5_inputs)
    selected_ik_vector = dict(selected_ik.parameter_vector)
    if "P5" in qualification.survivors:
        if not all(isinstance(item, CandidateReproductionInput) for item in p5_raw):
            raise ValueError("P5 selection accepts only raw episode-bearing candidate inputs")
        if tuple(item.stage for item in p5_raw) != (
            PilotStage.BASE, PilotStage.P5_0_01, PilotStage.P5_0_04,
        ) or any(item.predecessor_candidate is not None or item.survivors != ("P5",) for item in p5_raw):
            raise ValueError("P5 selection requires exact raw candidates without caller predecessors")
        if any(
            dict(item.parameter_vector)["pd"] != selected_ik_vector["pd"]
            or dict(item.parameter_vector)["ik"] != selected_ik_vector["ik"]
            for item in p5_raw
        ):
            raise ValueError("P5 raw candidates do not bind the mechanically selected PD/IK")
        baseline_raw = p5_raw[0]
        if dict(baseline_raw.parameter_vector)["p5_smoothness"] != 0.02:
            raise ValueError("P5 baseline raw input must use the frozen 0.02 scalar")
        baseline_eval = evaluate_candidate(
            PilotStage.FINAL_FOUR, baseline_raw.parameter_vector, ("P5",),
            baseline_raw.episodes, predecessor_candidate=selected_ik,
        )
        p5_baseline = PilotCandidate(
            PilotStage.BASE, baseline_eval.parameter_vector, baseline_eval.parameter_hash,
            baseline_eval.fixed_survivors, baseline_eval.feasible,
            baseline_eval.reuse_hashes, baseline_eval.stack_seed_scores,
            baseline_eval.global_score, 1, baseline_eval.reasons,
        )
        p5 = (p5_baseline,) + tuple(evaluate_candidate(
            item.stage, item.parameter_vector, ("P5",), item.episodes,
            predecessor_candidate=selected_ik,
        ) for item in p5_raw[1:])
        selected_p5 = select_p5_smoothness(p5)
    else:
        if p5_raw:
            raise ValueError("base-killed P5 cannot have smoothness candidates")
        p5 = ()
        selected_p5 = None
    recorded_candidates = (*pd, *ik, *p5[1:])
    digest = hashlib.sha256(candidate_evaluations_bytes(recorded_candidates)).hexdigest()
    return PilotSelectionEvidence(
        qualification, selected_pd, selected_ik, selected_p5, digest,
        _seal=_PILOT_SELECTION_SEAL,
    )


def qualify_base(outcomes: Sequence[BaseStackOutcome]) -> BaseQualification:
    ordered = tuple(outcomes)
    if tuple(item.stack_id for item in ordered) != _STACK_ORDER or any(item.episode_count != 12 for item in ordered):
        raise ValueError("base qualification requires 12 episodes for each P1-P6 stack")
    p1 = ordered[0]
    if p1.hard_failure:
        return BaseQualification((), (), "STOPPED", "INCONCLUSIVE", p1.reasons or ("P1_BASE_HARD_FAILURE",))
    killed = tuple(item.stack_id for item in ordered[1:] if item.hard_failure)
    survivors = tuple(item.stack_id for item in ordered if not item.hard_failure)
    reasons = tuple(reason for item in ordered if item.hard_failure for reason in (item.reasons or (f"{item.stack_id}_BASE_HARD_FAILURE",)))
    return BaseQualification(survivors, killed, "RUNNING", "PENDING", reasons)


def expected_pilot_episode_counts(
    survivors: Sequence[str],
    *,
    base_killed: Sequence[str] = (),
    p5_all_smoothness_infeasible: bool = False,
) -> dict[str, object]:
    survivor_set = set(survivors)
    killed = set(base_killed)
    if survivor_set & killed or not survivor_set | killed <= set(_STACK_ORDER):
        raise ValueError("pilot stack sets are invalid")
    counts: dict[str, int] = {}
    for stack in _STACK_ORDER:
        if stack in killed:
            counts[stack] = 12
        elif stack not in survivor_set:
            counts[stack] = 84 if stack == "P5" and p5_all_smoothness_infeasible else 12
        elif stack == "P5":
            counts[stack] = 188
        else:
            counts[stack] = 164
    return {"by_stack": counts, "total": sum(counts.values())}


@dataclass(frozen=True)
class PilotShard:
    shard_id: str
    stack_id: str
    seed: int
    episode_ids: tuple[str, ...]
    scientific_failure: bool = False

    def __post_init__(self) -> None:
        if self.stack_id not in _STACK_ORDER or type(self.seed) is not int or self.seed < 0:
            raise ValueError("pilot shard identity is invalid")
        episodes = tuple(self.episode_ids)
        if episodes != tuple(sorted(episodes)) or len(episodes) != len(set(episodes)) or not episodes:
            raise ValueError("pilot shard episodes must be nonempty sorted unique IDs")
        object.__setattr__(self, "episode_ids", episodes)


@dataclass(frozen=True)
class PilotManifest:
    revision: int
    stage: PilotStage
    predecessor_sha256: str
    config_sha256: str
    implementation_sha: str
    parameter_sha256: str
    shards: tuple[PilotShard, ...]
    reuse_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.revision not in (1, 2):
            raise ValueError("pilot revision must be 1 or 2")
        object.__setattr__(self, "stage", PilotStage(self.stage))
        _hash(self.predecessor_sha256, "predecessor hash")
        _hash(self.config_sha256, "config hash")
        if re.fullmatch(r"[0-9a-f]{40}", self.implementation_sha) is None:
            raise ValueError("implementation SHA must be lowercase 40-hex")
        _hash(self.parameter_sha256, "parameter hash")
        shards = tuple(self.shards)
        keys = [(_STACK_ORDER.index(item.stack_id), item.seed, item.shard_id) for item in shards]
        if keys != sorted(keys) or len({item.shard_id for item in shards}) != len(shards):
            raise ValueError("pilot shards must be unique in stack/seed order")
        episode_ids = [episode for item in shards for episode in item.episode_ids]
        if len(episode_ids) != len(set(episode_ids)):
            raise ValueError("manifest episodes must be unique")
        object.__setattr__(self, "shards", shards)
        object.__setattr__(self, "reuse_hashes", tuple(_hash(item, "reuse hash") for item in self.reuse_hashes))


def pilot_manifest_bytes(manifest: PilotManifest) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "revision": manifest.revision,
            "stage": manifest.stage.value,
            "predecessor_sha256": manifest.predecessor_sha256,
            "config_sha256": manifest.config_sha256,
            "implementation_sha": manifest.implementation_sha,
            "parameter_sha256": manifest.parameter_sha256,
            "shards": [
                {
                    "shard_id": item.shard_id,
                    "stack_id": item.stack_id,
                    "seed": item.seed,
                    "episode_ids": list(item.episode_ids),
                    "scientific_failure": item.scientific_failure,
                }
                for item in manifest.shards
            ],
            "reuse_hashes": list(manifest.reuse_hashes),
        }
    ) + b"\n"


def build_stage_shards(stage: PilotStage, survivors: Sequence[str], seeds: Sequence[int]) -> tuple[PilotShard, ...]:
    stage = PilotStage(stage)
    stacks = (
        (("P5",) if "P5" in survivors else ())
        if stage in {PilotStage.P5_0_01, PilotStage.P5_0_04}
        else tuple(survivors)
    )
    if tuple(sorted(stacks, key=_STACK_ORDER.index)) != stacks:
        raise ValueError("stage survivors must be in P1-P6 order")
    seed_values = tuple(seeds)
    if len(seed_values) != 4 or tuple(sorted(seed_values)) != seed_values or len(set(seed_values)) != 4:
        raise ValueError("pilot stage requires four sorted unique seeds")
    condition_ids = tuple(f"core-or-probe-{index:02d}" for index in range(26)) if stage is PilotStage.FINAL_FOUR else _TUNING_CONDITION_IDS
    return tuple(
        PilotShard(
            f"{stack}:{stage.value}:{seed:08d}",
            stack,
            seed,
            tuple(sorted(f"{stage.value}:{stack}:{seed:08d}:{condition}" for condition in condition_ids)),
        )
        for stack in stacks
        for seed in seed_values
    )


def build_pilot_manifest(
    stage: PilotStage,
    *,
    revision: int,
    predecessor_sha256: str,
    config_sha256: str,
    implementation_sha: str,
    parameter_sha256: str,
    survivors: Sequence[str],
    seeds: Sequence[int],
    reuse_hashes: Sequence[str] = (),
) -> PilotManifest:
    return PilotManifest(
        revision,
        stage,
        predecessor_sha256,
        config_sha256,
        implementation_sha,
        parameter_sha256,
        build_stage_shards(stage, survivors, seeds),
        tuple(reuse_hashes),
    )


@dataclass(frozen=True)
class StageTerminalDisposition:
    stage: PilotStage
    first_failing_shard_id: str
    reason: str
    trigger_completion_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", PilotStage(self.stage))
        allowed = {
            "DIMENSIONAL_MISMATCH", "NONFINITE_REFERENCE_OR_STATE",
            "JOINT_LIMIT_ESCAPE", "UNSTABLE_DIVERGENCE",
            "EASIEST_RECOVERY_FAILURE",
        }
        if not self.first_failing_shard_id or self.reason not in allowed:
            raise ValueError("terminal disposition identity is incomplete")
        _hash(self.trigger_completion_sha256, "trigger completion hash")


@dataclass(frozen=True)
class PilotShardCompletion:
    stage: PilotStage
    shard_id: str
    completed_episode_ids: tuple[str, ...]
    completion_sha256: str
    scientific_failure: bool
    reasons: tuple[str, ...] = ()
    reuse_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", PilotStage(self.stage))
        episodes = tuple(self.completed_episode_ids)
        if not self.shard_id or not episodes or episodes != tuple(sorted(set(episodes))):
            raise ValueError("completion episode inventory must be nonempty sorted and unique")
        object.__setattr__(self, "completed_episode_ids", episodes)
        _hash(self.completion_sha256, "completion hash")
        if type(self.scientific_failure) is not bool or self.scientific_failure != bool(self.reasons):
            raise ValueError("completion scientific failure and reasons are inconsistent")
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "reuse_hashes", tuple(_hash(item, "completion reuse hash") for item in self.reuse_hashes))


@dataclass(frozen=True)
class PilotDisposition:
    lifecycle_state: str
    scientific_result: str
    terminal_stage: PilotStage
    total_episode_count: int
    final_four_episode_count: int
    later_stage_commands: tuple[str, ...]
    remaining_final_four_stacks: tuple[str, ...]
    requires_final_four: bool
    completed_shard_ids: tuple[str, ...]
    completion_sha256s: tuple[str, ...]
    survivor_stacks: tuple[str, ...]
    killed_stacks: tuple[str, ...]
    reuse_hashes: tuple[str, ...]


def pilot_disposition(
    last_manifest: PilotManifest,
    *,
    prior_manifests: Sequence[PilotManifest] = (),
    completions: Sequence[PilotShardCompletion],
    terminal_disposition: StageTerminalDisposition | None = None,
    selection_evidence: PilotSelectionEvidence | None = None,
) -> PilotDisposition:
    manifests = tuple(prior_manifests) + (last_manifest,)
    expected_stages = _PILOT_STAGE_ORDER[: _PILOT_STAGE_ORDER.index(last_manifest.stage) + 1]
    if tuple(item.stage for item in manifests) != expected_stages:
        raise ValueError("pilot disposition requires the complete ordered stage prefix")
    if any(item.revision != last_manifest.revision or item.config_sha256 != last_manifest.config_sha256 or item.implementation_sha != last_manifest.implementation_sha for item in manifests):
        raise ValueError("pilot manifests do not share one revision/config/implementation")
    for predecessor, current in zip(manifests, manifests[1:]):
        if current.predecessor_sha256 != hashlib.sha256(pilot_manifest_bytes(predecessor)).hexdigest():
            raise ValueError("pilot manifest predecessor hash chain is broken")
    selected_vector = (
        None if selection_evidence is None else {
            "pd": list(selection_evidence.selected_pd.parameter_vector["pd"]),
            "ik": selection_evidence.selected_ik.parameter_vector["ik"],
            "p5_smoothness": (
                selection_evidence.selected_p5.parameter_vector["p5_smoothness"]
                if selection_evidence.selected_p5 is not None else 0.02
            ),
        }
    )
    for manifest in manifests:
        vector = _candidate_vector(manifest.stage)
        if manifest.stage in {
            PilotStage.IK_0_001, PilotStage.IK_0_05,
            PilotStage.P5_0_01, PilotStage.P5_0_04, PilotStage.FINAL_FOUR,
        }:
            if selected_vector is None:
                raise ValueError("adaptive manifest parameter hashes require selection evidence")
            vector["pd"] = list(selected_vector["pd"])
        if manifest.stage in {PilotStage.P5_0_01, PilotStage.P5_0_04, PilotStage.FINAL_FOUR}:
            assert selected_vector is not None
            vector["ik"] = selected_vector["ik"]
        if manifest.stage is PilotStage.FINAL_FOUR:
            assert selected_vector is not None
            vector["p5_smoothness"] = selected_vector["p5_smoothness"]
        if manifest.parameter_sha256 != sha256_json(vector):
            raise ValueError("pilot manifest parameter hash does not bind the exact selected stage vector")
        expected_reuse: tuple[str, ...] = ()
        if selection_evidence is not None and manifest.stage in {PilotStage.IK_0_001, PilotStage.IK_0_05}:
            expected_reuse = tuple(
                digest for score in selection_evidence.selected_pd.stack_seed_scores
                for digest in score.condition_bundle_sha256s
            )
        elif selection_evidence is not None and manifest.stage in {PilotStage.P5_0_01, PilotStage.P5_0_04}:
            expected_reuse = tuple(
                digest for score in selection_evidence.selected_ik.stack_seed_scores
                if score.stack_id == "P5" for digest in score.condition_bundle_sha256s
            )
        elif selection_evidence is not None and manifest.stage is PilotStage.FINAL_FOUR:
            predecessor_selection = selection_evidence.selected_p5 or selection_evidence.selected_ik
            expected_reuse = tuple(
                digest for score in predecessor_selection.stack_seed_scores
                for digest in score.condition_bundle_sha256s
            )
        if manifest.reuse_hashes != expected_reuse:
            raise ValueError("pilot manifest reuse hashes do not bind the selected predecessor bundles")
    declared = tuple((manifest.stage, shard) for manifest in manifests for shard in manifest.shards)
    completed = tuple(completions)
    if len({item.completion_sha256 for item in completed}) != len(completed):
        raise ValueError("completion hashes must be unique")
    if len(completed) > len(declared):
        raise ValueError("completion inventory extends after the declared prefix")
    for index, item in enumerate(completed):
        stage, shard = declared[index]
        if item.stage is not stage or item.shard_id != shard.shard_id or item.completed_episode_ids != shard.episode_ids:
            raise ValueError("completion inventory does not equal the strict declared shard prefix")
    base_manifest = manifests[0]
    base_seeds = tuple(item.seed for item in base_manifest.shards if item.stack_id == "P1")
    if len(base_seeds) != 4 or tuple(sorted(set(base_seeds))) != base_seeds:
        raise ValueError("base manifest must bind exactly four ordered tuning seeds")
    expected_base = build_stage_shards(PilotStage.BASE, _STACK_ORDER, base_seeds)
    if base_manifest.shards != expected_base:
        raise ValueError("base manifest does not contain the immutable full canonical shard inventory")
    base_declared_count = len(expected_base)
    base_completed = completed[:base_declared_count]
    base_is_complete = len(base_completed) == base_declared_count
    base_killed = tuple(
        stack for stack in _STACK_ORDER[1:]
        if any(item.shard_id.startswith(f"{stack}:") and item.scientific_failure for item in base_completed)
    ) if base_is_complete else ()
    base_survivors = tuple(stack for stack in _STACK_ORDER if stack not in base_killed) if base_is_complete else ()
    if len(manifests) > 1 and not base_is_complete:
        raise ValueError("later manifests require complete base qualification evidence")
    if len(manifests) > 1:
        if not isinstance(selection_evidence, PilotSelectionEvidence):
            raise ValueError("adaptive manifests require mechanically derived selection evidence")
        base_outcomes = tuple(BaseStackOutcome(
            stack, sum(
                len(item.completed_episode_ids) for item in base_completed
                if item.shard_id.startswith(f"{stack}:")
            ),
            stack in base_killed,
            tuple(
                reason for item in base_completed
                if item.shard_id.startswith(f"{stack}:") for reason in item.reasons
            ),
        ) for stack in _STACK_ORDER)
        if selection_evidence.base_qualification != qualify_base(base_outcomes):
            raise ValueError("selection evidence does not derive from completed base qualification")
    for manifest in manifests[1:]:
        if manifest.stage is PilotStage.FINAL_FOUR:
            seeds = tuple(item.seed for item in manifest.shards if item.stack_id == "P1")
            if len(seeds) != 4 or tuple(sorted(set(seeds))) != seeds:
                raise ValueError("final-four manifest must bind exactly four ordered evaluation seeds")
            assert selection_evidence is not None
            expected_survivors = selection_evidence.survivors
        else:
            seeds = base_seeds
            expected_survivors = base_survivors
        expected = build_stage_shards(manifest.stage, expected_survivors, seeds)
        if manifest.shards != expected:
            raise ValueError("stage manifest does not contain its full selection-derived canonical shard inventory")
    episode_ids = [episode for item in completed for episode in item.completed_episode_ids]
    if len(episode_ids) != len(set(episode_ids)):
        raise ValueError("completed pilot episodes cannot be counted twice")
    total = len(episode_ids)
    final_count = sum(len(item.completed_episode_ids) for item in completed if item.stage is PilotStage.FINAL_FOUR)
    killed = selection_evidence.killed_stacks if selection_evidence is not None else base_killed
    survivors = selection_evidence.survivors if selection_evidence is not None else base_survivors
    reuse = tuple(dict.fromkeys(hash_value for manifest in manifests for hash_value in manifest.reuse_hashes))
    completion_reuse = tuple(dict.fromkeys(hash_value for item in completed for hash_value in item.reuse_hashes))
    if completion_reuse != reuse:
        raise ValueError("completion reuse hashes differ from the manifest predecessor selection")
    if terminal_disposition is not None:
        if terminal_disposition.stage is not last_manifest.stage:
            raise ValueError("terminal disposition does not name the last stage")
        if not completed:
            raise ValueError("terminal disposition requires its completed trigger")
        trigger = completed[-1]
        if any(item.scientific_failure for item in completed[:-1]):
            raise ValueError("completion exists after the first scientific failure trigger")
        if (
            trigger.shard_id != terminal_disposition.first_failing_shard_id
            or trigger.completion_sha256 != terminal_disposition.trigger_completion_sha256
            or not trigger.shard_id.startswith("P1:") or not trigger.scientific_failure
            or terminal_disposition.reason not in trigger.reasons
        ):
            raise ValueError("terminal disposition must seal the final completed failing P1 trigger")
        return PilotDisposition(
            "STOPPED", "INCONCLUSIVE", last_manifest.stage, total, final_count,
            (), (), False, tuple(item.shard_id for item in completed),
            tuple(item.completion_sha256 for item in completed), survivors, killed, reuse,
        )
    if len(completed) != len(declared):
        raise ValueError("nonterminal pilot disposition requires every declared completion inventory")
    return PilotDisposition(
        "COMPLETE" if last_manifest.stage is PilotStage.FINAL_FOUR else "RUNNING",
        "PENDING",
        last_manifest.stage,
        total,
        final_count,
        tuple(stage.value for stage in _PILOT_STAGE_ORDER[_PILOT_STAGE_ORDER.index(last_manifest.stage) + 1 :]),
        (),
        last_manifest.stage is not PilotStage.FINAL_FOUR,
        tuple(item.shard_id for item in completed),
        tuple(item.completion_sha256 for item in completed),
        survivors,
        killed,
        reuse,
    )


def _candidate_wire(candidate: PilotCandidate) -> dict[str, object]:
    return {
        "stage": candidate.stage.value,
        "parameter_vector": dict(candidate.parameter_vector),
        "parameter_hash": candidate.parameter_hash,
        "fixed_survivors": list(candidate.fixed_survivors),
        "feasible": candidate.feasible,
        "reuse_hashes": list(candidate.reuse_hashes),
        "stack_seed_scores": [
            {
                "stack_id": item.stack_id,
                "seed": item.seed,
                "condition_bundle_sha256s": list(item.condition_bundle_sha256s),
                "score": item.score,
            }
            for item in candidate.stack_seed_scores
        ],
        "global_score": candidate.global_score,
        "tie_rank": candidate.tie_rank,
        "reasons": list(candidate.reasons),
    }


def candidate_evaluations_bytes(candidates: Sequence[PilotCandidate]) -> bytes:
    ordered = tuple(candidates)
    keys = [(_PILOT_STAGE_ORDER.index(item.stage), item.tie_rank) for item in ordered]
    if keys != sorted(keys):
        raise ValueError("candidate evaluations are not in frozen order")
    return canonical_json_bytes([_candidate_wire(item) for item in ordered]) + b"\n"


@dataclass(frozen=True)
class SmoothnessEpisodeScore:
    stack_id: str
    stage: PilotStage
    seed: int
    condition_id: str
    episode_id: str
    bundle_sha256: str
    jerk_p95: float
    discontinuity_p95: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", PilotStage(self.stage))
        if self.stack_id != "P1" or self.stage is not PilotStage.FINAL_FOUR:
            raise ValueError("smoothness evidence must be P1 final-four evidence")
        if not re.fullmatch(r"core-(05|10|20)-(000|100|300|700)-[12]", self.condition_id):
            raise ValueError("smoothness evidence must name one exact core condition")
        if type(self.seed) is not int or self.seed < 0 or not isinstance(self.episode_id, str) or not self.episode_id:
            raise ValueError("smoothness episode identity is invalid")
        _hash(self.bundle_sha256, "smoothness bundle hash")
        if any(not math.isfinite(float(value)) or value < 0 for value in (self.jerk_p95, self.discontinuity_p95)):
            raise ValueError("smoothness episode metrics must be finite and nonnegative")


@dataclass(frozen=True)
class P1SmoothnessBaseline:
    seed_ids: tuple[int, ...]
    episode_ids: tuple[str, ...]
    episode_bundle_sha256s: tuple[str, ...]
    jerk_episode_p95s: tuple[float, ...]
    discontinuity_episode_p95s: tuple[float, ...]
    jerk_p95: float
    discontinuity_p95: float


def compute_p1_smoothness_baseline(rows: Sequence[SmoothnessEpisodeScore]) -> P1SmoothnessBaseline:
    ordered = tuple(sorted(rows, key=lambda item: (item.seed, item.episode_id)))
    seeds = tuple(sorted({item.seed for item in ordered}))
    expected_conditions = {
        f"core-{rate:02d}-{latency:03d}-{moves}"
        for rate in (5, 10, 20) for latency in (0, 100, 300, 700) for moves in (1, 2)
    }
    keys = tuple((item.seed, item.condition_id) for item in ordered)
    if (
        len(ordered) != 96 or len(set(keys)) != 96 or len(seeds) != 4
        or any({item.condition_id for item in ordered if item.seed == seed} != expected_conditions for seed in seeds)
    ):
        raise ValueError("P1 smoothness baseline requires 24 core episodes for each of four seeds")
    if len({item.episode_id for item in ordered}) != len(ordered):
        raise ValueError("P1 smoothness episode IDs must be unique")
    return P1SmoothnessBaseline(
        seeds,
        tuple(item.episode_id for item in ordered),
        tuple(item.bundle_sha256 for item in ordered),
        tuple(float(item.jerk_p95) for item in ordered),
        tuple(float(item.discontinuity_p95) for item in ordered),
        nearest_rank((item.jerk_p95 for item in ordered), 0.95),
        nearest_rank((item.discontinuity_p95 for item in ordered), 0.95),
    )


@dataclass(frozen=True)
class SeedPrimary:
    stack_id: str
    seed: int
    recovery_s: float
    bundle_sha256: str
    valid: bool = True

    def __post_init__(self) -> None:
        if self.stack_id not in _STACK_ORDER or type(self.seed) is not int or self.seed < 0:
            raise ValueError("seed primary identity is invalid")
        if not math.isfinite(float(self.recovery_s)) or self.recovery_s < 0:
            raise ValueError("seed primary recovery must be finite and nonnegative")
        _hash(self.bundle_sha256, "seed bundle hash")


@dataclass(frozen=True)
class BootstrapContrast:
    stack_id: str
    seed_ids: tuple[int, ...]
    estimate_s: float
    lower_s: float
    upper_s: float


@dataclass(frozen=True)
class BootstrapDecision:
    resamples: int
    family_size: int
    confidence: float
    contrasts: tuple[BootstrapContrast, ...]


def paired_bootstrap(
    rows: Sequence[SeedPrimary],
    frozen_manifest_hash: str,
    *,
    resamples: int = 10_000,
) -> BootstrapDecision:
    _hash(frozen_manifest_hash, "frozen manifest hash")
    if type(resamples) is not int or resamples != 10_000:
        raise ValueError("paired bootstrap requires exactly 10,000 resamples")
    ordered = tuple(sorted(rows, key=lambda item: (_STACK_ORDER.index(item.stack_id), item.seed)))
    if len({(item.stack_id, item.seed) for item in ordered}) != len(ordered):
        raise ValueError("seed primary identities must be unique")
    if any(not item.valid for item in ordered):
        raise ValueError("paired bootstrap does not impute invalid seeds")
    by_stack = {stack: tuple(item for item in ordered if item.stack_id == stack) for stack in _STACK_ORDER}
    anchor = by_stack["P1"]
    if len(anchor) != 32:
        raise ValueError("paired bootstrap requires 32 complete P1 seeds")
    seed_ids = tuple(item.seed for item in anchor)
    anchor_values = np.asarray([item.recovery_s for item in anchor])
    contrasts = []
    for stack in _STACK_ORDER[1:]:
        candidate = by_stack[stack]
        if not candidate:
            continue
        if tuple(item.seed for item in candidate) != seed_ids:
            raise ValueError("paired bootstrap seed domains differ")
        deltas = np.asarray([item.recovery_s for item in candidate]) - anchor_values
        digest = hashlib.sha256((frozen_manifest_hash + "bootstrap" + stack).encode("ascii")).digest()
        rng = np.random.Generator(np.random.PCG64(int.from_bytes(digest[:16], "big")))
        indexes = rng.integers(0, len(seed_ids), size=(resamples, len(seed_ids)))
        samples = np.mean(deltas[indexes], axis=1)
        contrasts.append(
            BootstrapContrast(
                stack,
                seed_ids,
                float(np.mean(deltas)),
                nearest_rank(samples, 0.001),
                nearest_rank(samples, 0.999),
            )
        )
    return BootstrapDecision(resamples, 5, 0.99, tuple(contrasts))


@dataclass(frozen=True)
class GateMetrics:
    stack_id: str
    easiest_recovered: int
    easiest_total: int
    core_recovered: int
    core_total: int
    unsafe_count: int
    joint_limit_violations: int
    clamp_ticks: int
    saturation_ticks: int
    total_ticks: int
    jerk_episode_p95s: tuple[float, ...]
    discontinuity_episode_p95s: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.stack_id not in _STACK_ORDER:
            raise ValueError("gate stack is invalid")
        integer_fields = (
            "easiest_recovered", "easiest_total", "core_recovered", "core_total",
            "unsafe_count", "joint_limit_violations", "clamp_ticks", "saturation_ticks", "total_ticks",
        )
        if any(type(getattr(self, name)) is not int or getattr(self, name) < 0 for name in integer_fields):
            raise ValueError("gate counts must be nonnegative exact integers")
        if self.easiest_recovered > self.easiest_total or self.core_recovered > self.core_total:
            raise ValueError("recovered counts cannot exceed totals")
        for name in ("jerk_episode_p95s", "discontinuity_episode_p95s"):
            values = tuple(float(item) for item in getattr(self, name))
            if not values or any(not math.isfinite(item) or item < 0 for item in values):
                raise ValueError("smoothness gate domains must be nonempty finite nonnegative values")
            object.__setattr__(self, name, values)


@dataclass(frozen=True)
class GateDecision:
    stack_id: str
    passes: bool
    reasons: tuple[str, ...]
    jerk_p95: float
    discontinuity_p95: float


def apply_gate(metrics: GateMetrics, baseline: P1SmoothnessBaseline, config: ExperimentConfig) -> GateDecision:
    if metrics.stack_id not in _STACK_ORDER or metrics.easiest_total <= 0 or metrics.core_total <= 0 or metrics.total_ticks <= 0:
        raise ValueError("gate metric domains must be positive")
    jerk = nearest_rank(metrics.jerk_episode_p95s, 0.95)
    discontinuity = nearest_rank(metrics.discontinuity_episode_p95s, 0.95)
    reasons = []
    checks = (
        (metrics.easiest_recovered / metrics.easiest_total >= config.thresholds.easiest_recovery_fraction, "EASIEST_RECOVERY"),
        (metrics.core_recovered / metrics.core_total >= config.thresholds.core_recovery_fraction, "CORE_RECOVERY"),
        (metrics.unsafe_count == 0, "UNSAFE_OUTPUT"),
        (metrics.joint_limit_violations == 0, "JOINT_LIMIT"),
        (metrics.clamp_ticks / metrics.total_ticks <= config.thresholds.clamp_fraction, "CLAMP_FRACTION"),
        (metrics.saturation_ticks / metrics.total_ticks <= config.thresholds.saturation_fraction, "SATURATION_FRACTION"),
        (jerk <= config.thresholds.smoothness_multiplier * baseline.jerk_p95, "JERK"),
        (discontinuity <= config.thresholds.smoothness_multiplier * baseline.discontinuity_p95, "DISCONTINUITY"),
    )
    reasons.extend(reason for passed, reason in checks if not passed)
    return GateDecision(metrics.stack_id, not reasons, tuple(reasons), jerk, discontinuity)


@dataclass(frozen=True)
class PromotionDecision:
    scientific_result: str
    lifecycle_state: str
    promoted_stacks: tuple[str, ...]
    promoted_wire_representations: tuple[str, ...]
    superior_stacks: tuple[str, ...]
    reasons: tuple[str, ...]


_WIRE_BY_STACK = {
    "P1": "JOINT_POSITION",
    "P2": "JOINT_POSITION",
    "P3": "EEF_TRAJECTORY",
    "P4": "EEF_TRAJECTORY",
    "P5": "MPC_GOAL",
    "P6": "BOUNDED_RESIDUAL",
}


_RESOURCE_COMPLETION_SEAL = object()


@dataclass(frozen=True, init=False)
class ResourceCompletionEvidence:
    phase: str
    revision: int
    protocol_sha256: str
    predecessor_protocol_sha256: str | None
    disposition_sha256: str
    expected_shard_ids: tuple[str, ...]
    completed_shard_ids: tuple[str, ...]
    ledger_sha256s: tuple[str, ...]
    completion_sha256s: tuple[str, ...]
    retained_bytes: int
    temporary_peak_bytes: int
    quarantine_bytes: int
    wall_ns: int
    cpu_ns: int
    lifecycle_bytes: int
    preflight_sha256: str
    resource_state: str

    def __init__(
        self, phase: str, revision: int, protocol_sha256: str,
        predecessor_protocol_sha256: str | None, disposition_sha256: str,
        expected_shard_ids: tuple[str, ...], completed_shard_ids: tuple[str, ...],
        ledger_sha256s: tuple[str, ...], completion_sha256s: tuple[str, ...],
        retained_bytes: int, temporary_peak_bytes: int, quarantine_bytes: int,
        wall_ns: int, cpu_ns: int, lifecycle_bytes: int,
        preflight_sha256: str, resource_state: str,
        *, _seal: object,
    ) -> None:
        if _seal is not _RESOURCE_COMPLETION_SEAL:
            raise ValueError("resource completion evidence must be derived from canonical artifacts")
        if phase not in {"pilot", "confirmation"} or type(revision) is not int or revision <= 0:
            raise ValueError("resource evidence phase/revision is invalid")
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "protocol_sha256", _hash(protocol_sha256, "resource protocol hash"))
        if phase == "pilot":
            if predecessor_protocol_sha256 is not None:
                raise ValueError("pilot resource evidence cannot name a predecessor protocol")
        else:
            _hash(predecessor_protocol_sha256, "confirmation predecessor protocol hash")
        object.__setattr__(self, "predecessor_protocol_sha256", predecessor_protocol_sha256)
        object.__setattr__(self, "disposition_sha256", _hash(disposition_sha256, "resource disposition hash"))
        expected = tuple(expected_shard_ids)
        completed = tuple(completed_shard_ids)
        if not expected or len(set(expected)) != len(expected):
            raise ValueError("resource expected shard domain must be nonempty and unique")
        if completed != expected[:len(completed)]:
            raise ValueError("resource completed shard domain must be the exact declared prefix")
        ledgers = tuple(_hash(item, "resource ledger hash") for item in ledger_sha256s)
        completions = tuple(_hash(item, "resource completion hash") for item in completion_sha256s)
        if len(ledgers) != len(completed) or len(completions) != len(completed):
            raise ValueError("resource hashes must bind every completed shard")
        for name, value in (
            ("retained_bytes", retained_bytes), ("temporary_peak_bytes", temporary_peak_bytes),
            ("quarantine_bytes", quarantine_bytes),
            ("wall_ns", wall_ns), ("cpu_ns", cpu_ns),
            ("lifecycle_bytes", lifecycle_bytes),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"resource {name} must be a nonnegative exact integer")
        mib = 1024 * 1024
        phase_bytes_cap = (2_016 + 128) * mib if phase == "pilot" else (10_032 + 256) * mib
        wall_cap = (8 if phase == "pilot" else 24) * 3_600 * 1_000_000_000
        cpu_cap = (80 if phase == "pilot" else 240) * 3_600 * 1_000_000_000
        if (
            retained_bytes > phase_bytes_cap or temporary_peak_bytes > 32 * mib
            or quarantine_bytes > 64 * mib or wall_ns > wall_cap or cpu_ns > cpu_cap
            or lifecycle_bytes <= 0 or lifecycle_bytes > 14_576 * mib
        ):
            raise ValueError("resource evidence exceeds a frozen phase/lifecycle ceiling")
        object.__setattr__(self, "expected_shard_ids", expected)
        object.__setattr__(self, "completed_shard_ids", completed)
        object.__setattr__(self, "ledger_sha256s", ledgers)
        object.__setattr__(self, "completion_sha256s", completions)
        object.__setattr__(self, "retained_bytes", retained_bytes)
        object.__setattr__(self, "temporary_peak_bytes", temporary_peak_bytes)
        object.__setattr__(self, "quarantine_bytes", quarantine_bytes)
        object.__setattr__(self, "wall_ns", wall_ns)
        object.__setattr__(self, "cpu_ns", cpu_ns)
        object.__setattr__(self, "lifecycle_bytes", lifecycle_bytes)
        object.__setattr__(self, "preflight_sha256", _hash(preflight_sha256, "resource preflight hash"))
        if resource_state not in {"COMPLETE", "INCOMPLETE", "STOPPED"}:
            raise ValueError("resource evidence state is invalid")
        object.__setattr__(self, "resource_state", resource_state)

    @property
    def complete(self) -> bool:
        return self.resource_state == "COMPLETE" and self.completed_shard_ids == self.expected_shard_ids


def _resource_completion_from_validated_artifacts(
    *, phase: str, revision: int, protocol_sha256: str,
    predecessor_protocol_sha256: str | None, disposition_sha256: str,
    expected_shard_ids: tuple[str, ...], completed_shard_ids: tuple[str, ...],
    ledger_sha256s: tuple[str, ...], completion_sha256s: tuple[str, ...],
    retained_bytes: int, temporary_peak_bytes: int, quarantine_bytes: int,
    wall_ns: int, cpu_ns: int, lifecycle_bytes: int,
    preflight_sha256: str, resource_state: str,
) -> ResourceCompletionEvidence:
    """Private artifact-layer handoff after descriptor-relative validation."""
    return ResourceCompletionEvidence(
        phase, revision, protocol_sha256, predecessor_protocol_sha256,
        disposition_sha256, expected_shard_ids, completed_shard_ids,
        ledger_sha256s, completion_sha256s, retained_bytes,
        temporary_peak_bytes, quarantine_bytes,
        wall_ns, cpu_ns, lifecycle_bytes, preflight_sha256, resource_state,
        _seal=_RESOURCE_COMPLETION_SEAL,
    )


_PILOT_REPRODUCTION_SEAL = object()


@dataclass(frozen=True, init=False)
class PilotReproductionEvidence:
    revision: int
    protocol_sha256: str
    candidate_evaluations_sha256: str
    smoothness_baseline_sha256: str
    resource_disposition_sha256: str

    def __init__(
        self, revision: int, protocol_sha256: str,
        candidate_evaluations_sha256: str, smoothness_baseline_sha256: str,
        resource_disposition_sha256: str, *, _seal: object,
    ) -> None:
        if _seal is not _PILOT_REPRODUCTION_SEAL or type(revision) is not int or revision <= 0:
            raise ValueError("pilot reproduction evidence must come from verified raw inputs")
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "protocol_sha256", protocol_sha256)
        object.__setattr__(self, "candidate_evaluations_sha256", candidate_evaluations_sha256)
        object.__setattr__(self, "smoothness_baseline_sha256", smoothness_baseline_sha256)
        object.__setattr__(self, "resource_disposition_sha256", resource_disposition_sha256)
        for name in (
            "protocol_sha256", "candidate_evaluations_sha256", "smoothness_baseline_sha256",
            "resource_disposition_sha256",
        ):
            _hash(getattr(self, name), name)


def promotion_decision(
    bootstrap: BootstrapDecision,
    gates: Sequence[GateDecision],
    *,
    p1_valid: bool,
    negative_control_valid: bool,
    resource_evidence: ResourceCompletionEvidence,
    pilot_reproduction: PilotReproductionEvidence,
    killed_stacks: Sequence[str] = (),
) -> PromotionDecision:
    gate_by_stack = {item.stack_id: item for item in gates}
    if resource_evidence.phase != "confirmation":
        raise ValueError("promotion requires confirmation resource disposition evidence")
    if not isinstance(pilot_reproduction, PilotReproductionEvidence):
        raise ValueError("promotion requires verified pilot reproduction evidence")
    if (
        resource_evidence.revision != pilot_reproduction.revision
        or resource_evidence.predecessor_protocol_sha256 != pilot_reproduction.protocol_sha256
    ):
        raise ValueError("confirmation resources do not bind the verified pilot revision/protocol")
    if not resource_evidence.complete or not p1_valid or not negative_control_valid or not gate_by_stack.get("P1", GateDecision("P1", False, (), 0, 0)).passes:
        reasons = tuple(reason for reason, passed in (("RESOURCE_INCOMPLETE", resource_evidence.complete), ("P1_INVALID", p1_valid), ("NEGATIVE_CONTROL_INVALID", negative_control_valid)) if not passed)
        return PromotionDecision("INCONCLUSIVE", "STOPPED", (), (), (), reasons or ("P1_GATE_FAILED",))
    contrasts = {item.stack_id: item for item in bootstrap.contrasts}
    eligible = [item for item in gates if item.passes and item.stack_id != "P1" and item.stack_id in contrasts]
    superior = sorted((item.stack_id for item in eligible if contrasts[item.stack_id].upper_s <= -0.10), key=lambda stack: (contrasts[stack].upper_s, _STACK_ORDER.index(stack)))
    noninferior = sorted((item.stack_id for item in eligible if item.stack_id not in superior and contrasts[item.stack_id].upper_s <= 0.10), key=lambda stack: (contrasts[stack].upper_s, _STACK_ORDER.index(stack)))
    ranking = sorted(
        ("P1", *superior, *noninferior),
        key=lambda stack: ((0.0 if stack == "P1" else contrasts[stack].upper_s), _STACK_ORDER.index(stack)),
    )
    promoted = tuple(ranking[:2])
    wires = tuple(dict.fromkeys(_WIRE_BY_STACK[item] for item in promoted))
    if superior:
        scientific = "SUPPORTED"
    else:
        valid_nonanchors = [item for item in bootstrap.contrasts if gate_by_stack.get(item.stack_id, GateDecision(item.stack_id, False, (), 0, 0)).passes]
        all_exclude = bool(valid_nonanchors) and all(item.lower_s > -0.10 for item in valid_nonanchors)
        all_killed = set(_STACK_ORDER[1:]).issubset(set(killed_stacks))
        scientific = "NOT_SUPPORTED" if all_exclude or all_killed else "INCONCLUSIVE"
    return PromotionDecision(scientific, "COMPLETE" if scientific != "INCONCLUSIVE" else "STOPPED", promoted, wires, tuple(superior), ())


def verify_pilot_reproduction(
    candidates: Sequence["CandidateReproductionInput"],
    frozen_candidate_bytes: bytes,
    smoothness_rows: Sequence[SmoothnessEpisodeScore],
    frozen_baseline: P1SmoothnessBaseline,
    *,
    resource_evidence: ResourceCompletionEvidence,
) -> PilotReproductionEvidence:
    if resource_evidence.phase != "pilot" or not resource_evidence.complete:
        raise ValueError("pilot reproduction requires complete resource disposition evidence")
    if not all(isinstance(item, CandidateReproductionInput) for item in candidates):
        raise ValueError("pilot reproduction accepts only raw evidence-bearing inputs")
    reproduced = tuple(evaluate_candidate(
        item.stage, item.parameter_vector, item.survivors, item.episodes,
        predecessor_candidate=item.predecessor_candidate,
    ) for item in candidates)
    for index, (raw, candidate) in enumerate(zip(candidates, reproduced)):
        predecessor = raw.predecessor_candidate
        if predecessor is not None and candidate_evaluations_bytes((predecessor,)) not in {
            candidate_evaluations_bytes((item,)) for item in reproduced[:index]
        }:
            raise ValueError("candidate predecessor is not an earlier reproduced selection")
    if candidate_evaluations_bytes(reproduced) != frozen_candidate_bytes:
        raise ValueError("candidate evaluations do not reproduce frozen bytes")
    if compute_p1_smoothness_baseline(smoothness_rows) != frozen_baseline:
        raise ValueError("P1 smoothness baseline does not reproduce frozen evidence")
    baseline_bytes = canonical_json_bytes({
        "seed_ids": list(frozen_baseline.seed_ids),
        "episode_ids": list(frozen_baseline.episode_ids),
        "episode_bundle_sha256s": list(frozen_baseline.episode_bundle_sha256s),
        "jerk_episode_p95s": list(frozen_baseline.jerk_episode_p95s),
        "discontinuity_episode_p95s": list(frozen_baseline.discontinuity_episode_p95s),
        "jerk_p95": frozen_baseline.jerk_p95,
        "discontinuity_p95": frozen_baseline.discontinuity_p95,
    })
    return PilotReproductionEvidence(
        resource_evidence.revision,
        resource_evidence.protocol_sha256,
        hashlib.sha256(frozen_candidate_bytes).hexdigest(),
        hashlib.sha256(baseline_bytes).hexdigest(),
        resource_evidence.disposition_sha256,
        _seal=_PILOT_REPRODUCTION_SEAL,
    )


@dataclass(frozen=True)
class CandidateReproductionInput:
    stage: PilotStage
    parameter_vector: Mapping[str, object]
    survivors: tuple[str, ...]
    episodes: tuple[PilotEpisodeScore, ...]
    predecessor_candidate: PilotCandidate | None = None


@dataclass(frozen=True)
class PlotRow:
    stack_id: str
    seed: int
    condition_id: str
    policy_hz: int
    latency_ms: int
    move_count: int
    fault: str
    recovery_s: float
    error_m: float
    jerk_p95: float
    age_p95_s: float
    timeline: tuple[float, ...] = ()
    valid: bool = True


_PLOT_NAMES = (
    "recovery-vs-latency.svg",
    "tracking-error-vs-rate.svg",
    "joint-jerk.svg",
    "action-age.svg",
    "timeline.svg",
)


def _svg(title: str, x_label: str, y_label: str, series: Sequence[tuple[str, Sequence[tuple[float, float]]]]) -> bytes:
    colors = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf")
    all_points = tuple(point for _, points in series for point in points)
    xs = [item[0] for item in all_points] or [0.0]
    ys = [item[1] for item in all_points] or [0.0]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400" viewBox="0 0 640 400">', '<rect width="640" height="400" fill="white"/>', f'<text x="20" y="28" font-family="sans-serif" font-size="16">{title}</text>', '<path d="M50 350H620M50 50V350" stroke="#222" fill="none"/>', f'<text x="300" y="390" font-family="sans-serif" font-size="12">{x_label}</text>', f'<text x="8" y="45" font-family="sans-serif" font-size="12">{y_label}</text>']
    for index, (label, points) in enumerate(series):
        ordered = tuple(points)
        if not ordered:
            continue
        coords = " ".join(f"{50 + 550 * ((x - xmin) / (xmax - xmin) if xmax != xmin else 0.5):.3f},{350 - 280 * ((y - ymin) / (ymax - ymin) if ymax != ymin else 0.5):.3f}" for x, y in ordered)
        lines.append(f'<polyline points="{coords}" fill="none" stroke="{colors[index % len(colors)]}" stroke-width="2"/>')
        lines.append(f'<text x="{500}" y="{60 + 18 * index}" font-family="sans-serif" font-size="12" fill="{colors[index % len(colors)]}">{label}</text>')
    lines.append("</svg>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_svg_plots(rows: Sequence[PlotRow], promoted_stacks: Sequence[str]) -> Mapping[str, bytes]:
    ordered = tuple(sorted((item for item in rows if item.valid), key=lambda item: (_STACK_ORDER.index(item.stack_id), item.seed, item.condition_id)))
    stacks = tuple(dict.fromkeys(("P1", *promoted_stacks)))
    if not stacks or stacks[0] != "P1" or any(stack not in _STACK_ORDER for stack in stacks):
        raise ValueError("plot stack domain must contain P1 and valid promoted stacks")
    keys_by_stack = {
        stack: {(item.seed, item.condition_id) for item in ordered if item.stack_id == stack}
        for stack in stacks
    }
    shared = keys_by_stack["P1"]
    if not shared or any(keys_by_stack[stack] != shared for stack in stacks):
        raise ValueError("plots require identical complete seed/condition domains across P1 and promoted stacks")
    ordered = tuple(item for item in ordered if item.stack_id in stacks)
    if len({(item.stack_id, item.seed, item.condition_id) for item in ordered}) != len(ordered):
        raise ValueError("plot rows duplicate a shared stack/seed/condition identity")
    plots: dict[str, bytes] = {}
    specs = (
        (_PLOT_NAMES[0], "Recovery vs latency", "latency (ms)", "recovery (s)", lambda item: (float(item.latency_ms), item.recovery_s)),
        (_PLOT_NAMES[1], "Tracking error vs rate", "policy rate (Hz)", "error (m)", lambda item: (float(item.policy_hz), item.error_m)),
        (_PLOT_NAMES[2], "Joint jerk", "seed", "jerk (rad/s^3)", lambda item: (float(item.seed), item.jerk_p95)),
        (_PLOT_NAMES[3], "Action age", "latency (ms)", "age (s)", lambda item: (float(item.latency_ms), item.age_p95_s)),
    )
    for filename, title, x_label, y_label, transform in specs:
        plots[filename] = _svg(title, x_label, y_label, tuple((stack, tuple(transform(item) for item in ordered if item.stack_id == stack)) for stack in stacks))
    timeline_candidates = [item for item in ordered if item.condition_id == "core-10-300-2" and item.policy_hz == 10 and item.latency_ms == 300 and item.move_count == 2 and item.fault == "NONE" and item.timeline]
    intended_keys = sorted({(item.seed, item.condition_id) for item in timeline_candidates})
    chosen = next((key for key in intended_keys if all(any(item.stack_id == stack and (item.seed, item.condition_id) == key for item in timeline_candidates) for stack in stacks)), None)
    if chosen is None:
        raise ValueError("timeline plot requires one shared exact intended condition")
    plots[_PLOT_NAMES[4]] = _svg("Timeline", "sample", "error (m)", tuple((stack, tuple((float(index), value) for item in timeline_candidates if item.stack_id == stack and (item.seed, item.condition_id) == chosen for index, value in enumerate(item.timeline))) for stack in stacks))
    return MappingProxyType(plots)


def write_svg_plots(output_dir: Path, rows: Sequence[PlotRow], promoted_stacks: Sequence[str]) -> tuple[Path, ...]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered = render_svg_plots(rows, promoted_stacks)
    paths = []
    for filename in _PLOT_NAMES:
        path = output_dir / filename
        payload = rendered[filename]
        if path.exists():
            if path.read_bytes() != payload:
                raise FileExistsError(f"plot already exists with different bytes: {filename}")
        else:
            with path.open("xb") as handle:
                handle.write(payload)
        paths.append(path)
    return tuple(paths)
