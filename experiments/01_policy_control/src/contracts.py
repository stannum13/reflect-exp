"""Strict experiment-local contracts and configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from reflect.types import ActionChunk, Observation, SkillSpec


class CommandStack(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"
    P5 = "P5"
    P6 = "P6"


class FaultKind(str, Enum):
    NONE = "NONE"
    DROP = "DROP"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    STATIONARY_CONTROL = "STATIONARY_CONTROL"


def frozen_vector(value: object, name: str, *, shape: tuple[int, ...]) -> np.ndarray:
    try:
        result = np.array(value, dtype=np.float64, order="C", copy=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if result.shape != shape:
        raise ValueError(f"{name} must have shape {shape}")
    if not np.isfinite(result).all():
        raise ValueError(f"{name} must contain only finite values")
    result.setflags(write=False)
    return result


def _tuple_floats(value: object, name: str, length: int | None = None) -> tuple[float, ...]:
    if not isinstance(value, list) or (length is not None and len(value) != length):
        raise ValueError(f"{name} must be a list of length {length}")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise ValueError(f"{name} must contain finite numbers")
        result.append(float(item))
    return tuple(result)


def _number(raw: dict[str, Any], key: str, *, integer: bool = False) -> int | float:
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    if integer:
        if type(value) is not int:
            raise ValueError(f"{key} must be an integer")
        return value
    if not math.isfinite(float(value)):
        raise ValueError(f"{key} must be finite")
    return float(value)


@dataclass(frozen=True)
class ArmConfig:
    link_lengths_m: tuple[float, float, float]
    joint_min_rad: float
    joint_max_rad: float
    solver_joint_min_rad: float
    solver_joint_max_rad: float
    joint_damping: float
    torque_min_nm: float
    torque_max_nm: float
    timestep_s: float
    episode_duration_s: float


@dataclass(frozen=True)
class ControllerConfig:
    pd_candidates: tuple[tuple[float, float], ...]
    ik_damping_candidates: tuple[float, ...]
    mpc_smoothness_candidates: tuple[float, ...]
    reference_slew_rad_s: float
    ik_iterations: int
    ik_step_norm_rad: float
    ik_posture_gain: float
    differential_gain: float
    differential_speed_m_s: float
    null_gain: float
    qdot_limit_rad_s: float
    mpc_period_s: float
    mpc_horizon_steps: int
    residual_limit_rad: float


@dataclass(frozen=True)
class TimingConfig:
    episode_ticks: int
    policy_rates_hz: tuple[int, ...]
    latencies_ms: tuple[int, ...]
    chunk_horizon_s: float
    expiry_periods: float
    telemetry_hz: int


@dataclass(frozen=True)
class ResourceConfig:
    rollout_bytes: int
    shard_wall_seconds: int
    pilot_wall_seconds: int
    confirmation_wall_seconds: int
    pilot_cpu_seconds: int
    confirmation_cpu_seconds: int
    phase_bytes: int


@dataclass(frozen=True)
class ExperimentConfig:
    schema_version: int
    study_id: str
    arm: ArmConfig
    controller: ControllerConfig
    timing: TimingConfig
    pilot: dict[str, Any]
    confirmation: dict[str, Any]
    resources: ResourceConfig
    thresholds: dict[str, float]


@dataclass(frozen=True)
class Condition:
    condition_id: str
    policy_hz: int
    latency_ms: int
    move_count: int
    fault: FaultKind = FaultKind.NONE


@dataclass(frozen=True)
class Scenario:
    seed: int
    q0: np.ndarray
    initial_target: np.ndarray
    one_move_path: np.ndarray
    two_move_path: np.ndarray
    stationary_path: np.ndarray


@dataclass(frozen=True)
class PolicyInput:
    observation: Observation
    skill: SkillSpec
    response_time_ns: int
    policy_period_ns: int
    q_initial: np.ndarray
    q_initial_target: np.ndarray


@dataclass(frozen=True)
class ExecutorState:
    active_chunk_id: str | None
    latched_q_ref: np.ndarray
    p5_qdot_previous: np.ndarray
    p5_planner_q_ref: np.ndarray
    p5_planner_enabled: bool


@dataclass(frozen=True)
class ClampReport:
    reference_clamped: bool = False
    joint_clamped: bool = False
    torque_clamped: bool = False


@dataclass(frozen=True)
class EpisodeMetrics:
    recovery_s: float
    recovered_events: int
    displacement_events: int
    final_error_m: float
    mean_error_m: float
    p95_error_m: float
    age_p95_s: float
    jerk_p95: float
    saturation_fraction: float
    discontinuity_mean: float
    discontinuity_p95: float
    unsafe_count: int
    clamp_fraction: float
    compute_p50_ns: int
    compute_p95_ns: int
    valid: bool = True


@dataclass(frozen=True)
class SeedMetrics:
    stack_id: str
    seed: int
    recovery_s: float
    valid: bool
    bundle_hashes: tuple[str, ...]


@dataclass(frozen=True)
class ShardSpec:
    shard_id: str
    stack_id: str
    configuration_hash: str
    seed: int
    condition_ids: tuple[str, ...]
    output_identities: tuple[str, ...]


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_ROOT_KEYS = {"schema_version", "study_id", "arm", "controller", "timing", "pilot", "confirmation", "resources", "thresholds"}


def _require_keys(raw: dict[str, Any], expected: set[str], name: str) -> None:
    missing, unknown = expected - set(raw), set(raw) - expected
    if missing:
        raise ValueError(f"{name} missing keys: {sorted(missing)}")
    if unknown:
        raise ValueError(f"{name} unknown keys: {sorted(unknown)}")


def load_config(path: Path) -> ExperimentConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("configuration must be a mapping")
    _require_keys(raw, _ROOT_KEYS, "configuration")
    arm = raw["arm"]
    controller = raw["controller"]
    timing = raw["timing"]
    resources = raw["resources"]
    for name, value in (("arm", arm), ("controller", controller), ("timing", timing), ("resources", resources)):
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be a mapping")
    arm_cfg = ArmConfig(
        link_lengths_m=_tuple_floats(arm["link_lengths_m"], "link_lengths_m", 3),
        **{key: _number(arm, key) for key in ArmConfig.__dataclass_fields__ if key != "link_lengths_m"},
    )
    pd = controller["pd_candidates"]
    if not isinstance(pd, list):
        raise ValueError("pd_candidates must be a list")
    controller_cfg = ControllerConfig(
        pd_candidates=tuple(_tuple_floats(row, "pd_candidates", 2) for row in pd),
        ik_damping_candidates=_tuple_floats(controller["ik_damping_candidates"], "ik_damping_candidates"),
        mpc_smoothness_candidates=_tuple_floats(controller["mpc_smoothness_candidates"], "mpc_smoothness_candidates"),
        **{
            key: _number(controller, key, integer=key in {"ik_iterations", "mpc_horizon_steps"})
            for key in ControllerConfig.__dataclass_fields__
            if key not in {"pd_candidates", "ik_damping_candidates", "mpc_smoothness_candidates"}
        },
    )
    rates = _tuple_floats(timing["policy_rates_hz"], "policy_rates_hz")
    latencies = _tuple_floats(timing["latencies_ms"], "latencies_ms")
    timing_cfg = TimingConfig(
        episode_ticks=int(_number(timing, "episode_ticks", integer=True)),
        policy_rates_hz=tuple(int(x) for x in rates),
        latencies_ms=tuple(int(x) for x in latencies),
        chunk_horizon_s=float(_number(timing, "chunk_horizon_s")),
        expiry_periods=float(_number(timing, "expiry_periods")),
        telemetry_hz=int(_number(timing, "telemetry_hz", integer=True)),
    )
    resource_cfg = ResourceConfig(**{key: int(_number(resources, key, integer=True)) for key in ResourceConfig.__dataclass_fields__})
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("schema_version must be integer 1")
    if not isinstance(raw["study_id"], str) or not raw["study_id"]:
        raise ValueError("study_id must be non-empty")
    thresholds = raw["thresholds"]
    if not isinstance(thresholds, dict):
        raise ValueError("thresholds must be a mapping")
    parsed_thresholds = {key: float(_number(thresholds, key)) for key in thresholds}
    return ExperimentConfig(
        schema_version=1,
        study_id=raw["study_id"],
        arm=arm_cfg,
        controller=controller_cfg,
        timing=timing_cfg,
        pilot=dict(raw["pilot"]),
        confirmation=dict(raw["confirmation"]),
        resources=resource_cfg,
        thresholds=parsed_thresholds,
    )


__all__ = [
    "ActionChunk", "ArmConfig", "ClampReport", "CommandStack", "Condition",
    "ControllerConfig", "EpisodeMetrics", "ExecutorState", "ExperimentConfig",
    "FaultKind", "PolicyInput", "ResourceConfig", "Scenario", "SeedMetrics",
    "ShardSpec", "TimingConfig", "canonical_json_bytes", "frozen_vector",
    "load_config", "sha256_file",
]
