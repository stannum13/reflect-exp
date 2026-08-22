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
    kinematics: "KinematicsConfig"
    mpc: "MPCConfig"
    residual: "ResidualConfig"
    conditions: "ConditionsConfig"
    stacks: tuple["StackConfig", ...]
    metrics: "MetricsConfig"
    pilot: "PilotConfig"
    confirmation: "ConfirmationConfig"
    resources: ResourceConfig
    thresholds: "ThresholdConfig"


@dataclass(frozen=True)
class KinematicsConfig:
    posture_q: np.ndarray
    absolute_solver_revision: str
    differential_solver_revision: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "posture_q", frozen_vector(self.posture_q, "posture_q", shape=(3,)))


@dataclass(frozen=True)
class MPCConfig:
    candidate_count: int
    raw_direction_values: tuple[int, int, int]
    magnitudes_rad_s: tuple[float, float, float]
    error_scale_m: float
    velocity_scale_rad_s: float
    soft_joint_margin_rad: float
    effort_weight: float
    barrier_weight: float
    terminal_error_weight: float
    stage_error_weight: float
    smoothness_weight: float
    cost_revision: str
    candidate_order_revision: str
    transition_revision: str


@dataclass(frozen=True)
class ResidualConfig:
    nominal_revision: str
    nominal_duration_s: float
    component_limit_rad: float
    blend_coefficients: tuple[float, float, float]


@dataclass(frozen=True)
class ConditionsConfig:
    move_counts: tuple[int, int]
    probe_ids: tuple[str, str]
    control_id: str
    core_fault_id: str
    probe_policy_hz: int
    probe_latency_ms: int
    probe_move_count: int
    drop_trigger: str
    out_of_order_extra_ms: int
    stationary_policy_hz: int
    stationary_latency_ms: int
    stationary_first_seed_count: int


@dataclass(frozen=True)
class StackConfig:
    stack_id: str
    representation: str
    action_columns: int
    cardinality: str


@dataclass(frozen=True)
class MetricsConfig:
    primary: str
    secondary: tuple[str, ...]
    percentile_revision: str


@dataclass(frozen=True)
class PilotConfig:
    seed_count: int
    tuning_seed_count: int
    evaluation_seed_count: int
    max_revisions: int
    tuning_conditions: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class ConfirmationConfig:
    scenario_count: int
    candidate_count: int
    bootstrap_resamples: int


@dataclass(frozen=True)
class ThresholdConfig:
    success_radius_m: float
    success_dwell_s: float
    recovery_censor_s: float
    pilot_easiest_recovery_s: float
    worthwhile_s: float
    noninferiority_s: float
    easiest_recovery_fraction: float
    core_recovery_fraction: float
    clamp_fraction: float
    saturation_fraction: float
    smoothness_multiplier: float

    def __getitem__(self, key: str) -> float:
        return float(getattr(self, key))


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "q0", frozen_vector(self.q0, "q0", shape=(3,)))
        object.__setattr__(self, "initial_target", frozen_vector(self.initial_target, "initial_target", shape=(2,)))
        for name in ("one_move_path", "two_move_path", "stationary_path"):
            value = np.array(getattr(self, name), dtype=np.float64, order="C", copy=True)
            if value.ndim != 2 or value.shape[1] != 2 or not np.isfinite(value).all():
                raise ValueError(f"{name} must be a finite Nx2 array")
            value.setflags(write=False)
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class PolicyInput:
    observation: Observation
    skill: SkillSpec
    response_time_ns: int
    policy_period_ns: int
    q_initial: np.ndarray
    q_initial_target: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "q_initial", frozen_vector(self.q_initial, "q_initial", shape=(3,)))
        object.__setattr__(self, "q_initial_target", frozen_vector(self.q_initial_target, "q_initial_target", shape=(3,)))


@dataclass(frozen=True)
class ExecutorState:
    active_chunk_id: str | None
    latched_q_ref: np.ndarray
    p5_qdot_previous: np.ndarray
    p5_planner_q_ref: np.ndarray
    p5_planner_enabled: bool

    def __post_init__(self) -> None:
        for name in ("latched_q_ref", "p5_qdot_previous", "p5_planner_q_ref"):
            object.__setattr__(self, name, frozen_vector(getattr(self, name), name, shape=(3,)))


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


_ROOT_KEYS = {"schema_version", "study_id", "arm", "controller", "kinematics", "mpc", "residual", "timing", "conditions", "stacks", "metrics", "pilot", "confirmation", "resources", "thresholds"}


def _require_keys(raw: dict[str, Any], expected: set[str], name: str) -> None:
    missing, unknown = expected - set(raw), set(raw) - expected
    if missing:
        raise ValueError(f"{name} missing keys: {sorted(missing)}")
    if unknown:
        raise ValueError(f"{name} unknown keys: {sorted(unknown)}")


class _UniqueLoader(yaml.SafeLoader):
    pass


def _construct_unique(loader: _UniqueLoader, node: yaml.MappingNode, deep: bool = False) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique)


def _integer_tuple(value: object, name: str, *, length: int | None = None) -> tuple[int, ...]:
    if not isinstance(value, list) or (length is not None and len(value) != length) or any(type(item) is not int for item in value):
        raise ValueError(f"{name} must contain exact integers")
    return tuple(value)


def _mapping(raw: dict[str, Any], key: str, expected: set[str]) -> dict[str, Any]:
    value = raw[key]
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping")
    _require_keys(value, expected, key)
    return value


def _string(value: object, name: str, *, allowed: set[str] | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty string")
    if allowed is not None and value not in allowed:
        raise ValueError(f"{name} has unsupported value {value}")
    return value


def _string_tuple(value: object, name: str, *, length: int | None = None) -> tuple[str, ...]:
    if not isinstance(value, list) or (length is not None and len(value) != length):
        raise ValueError(f"{name} must be a list of strings")
    return tuple(_string(item, name) for item in value)


def load_config(path: Path) -> ExperimentConfig:
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueLoader)
    if not isinstance(raw, dict):
        raise ValueError("configuration must be a mapping")
    _require_keys(raw, _ROOT_KEYS, "configuration")
    arm = _mapping(raw, "arm", set(ArmConfig.__dataclass_fields__))
    controller = _mapping(raw, "controller", set(ControllerConfig.__dataclass_fields__))
    timing = _mapping(raw, "timing", set(TimingConfig.__dataclass_fields__))
    resources = _mapping(raw, "resources", set(ResourceConfig.__dataclass_fields__))
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
    rates = _integer_tuple(timing["policy_rates_hz"], "policy_rates_hz")
    latencies = _integer_tuple(timing["latencies_ms"], "latencies_ms")
    timing_cfg = TimingConfig(
        episode_ticks=int(_number(timing, "episode_ticks", integer=True)),
        policy_rates_hz=rates,
        latencies_ms=latencies,
        chunk_horizon_s=float(_number(timing, "chunk_horizon_s")),
        expiry_periods=float(_number(timing, "expiry_periods")),
        telemetry_hz=int(_number(timing, "telemetry_hz", integer=True)),
    )
    resource_cfg = ResourceConfig(**{key: int(_number(resources, key, integer=True)) for key in ResourceConfig.__dataclass_fields__})
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("schema_version must be integer 1")
    if not isinstance(raw["study_id"], str) or not raw["study_id"]:
        raise ValueError("study_id must be non-empty")
    kinematics = _mapping(raw, "kinematics", set(KinematicsConfig.__dataclass_fields__))
    mpc = _mapping(raw, "mpc", set(MPCConfig.__dataclass_fields__))
    residual = _mapping(raw, "residual", set(ResidualConfig.__dataclass_fields__))
    conditions = _mapping(raw, "conditions", set(ConditionsConfig.__dataclass_fields__))
    metrics = _mapping(raw, "metrics", set(MetricsConfig.__dataclass_fields__))
    pilot = _mapping(raw, "pilot", set(PilotConfig.__dataclass_fields__))
    confirmation = _mapping(raw, "confirmation", set(ConfirmationConfig.__dataclass_fields__))
    thresholds = _mapping(raw, "thresholds", set(ThresholdConfig.__dataclass_fields__))
    stack_rows = raw["stacks"]
    if not isinstance(stack_rows, list) or len(stack_rows) != 6:
        raise ValueError("stacks must contain exactly six rows")
    stacks: list[StackConfig] = []
    for row in stack_rows:
        if not isinstance(row, dict):
            raise ValueError("stack row must be a mapping")
        _require_keys(row, set(StackConfig.__dataclass_fields__), "stack")
        if type(row["action_columns"]) is not int:
            raise ValueError("action_columns must be integer")
        stacks.append(StackConfig(
            _string(row["stack_id"], "stack_id"),
            _string(row["representation"], "stack representation", allowed={"JOINT_POSITION", "EEF_TRAJECTORY", "MPC_GOAL", "BOUNDED_RESIDUAL"}),
            row["action_columns"],
            _string(row["cardinality"], "stack cardinality", allowed={"TARGET", "HORIZON"}),
        ))
    exact_stacks = (
        ("P1", "JOINT_POSITION", 3, "TARGET"),
        ("P2", "JOINT_POSITION", 3, "HORIZON"),
        ("P3", "EEF_TRAJECTORY", 2, "TARGET"),
        ("P4", "EEF_TRAJECTORY", 2, "HORIZON"),
        ("P5", "MPC_GOAL", 2, "TARGET"),
        ("P6", "BOUNDED_RESIDUAL", 3, "TARGET"),
    )
    if tuple((row.stack_id, row.representation, row.action_columns, row.cardinality) for row in stacks) != exact_stacks:
        raise ValueError("stack rows must be the exact six protocols")
    result = ExperimentConfig(
        schema_version=1,
        study_id=_string(raw["study_id"], "study_id"),
        arm=arm_cfg,
        controller=controller_cfg,
        timing=timing_cfg,
        kinematics=KinematicsConfig(np.asarray(kinematics["posture_q"]), _string(kinematics["absolute_solver_revision"], "absolute_solver_revision", allowed={"ABSOLUTE_IK_12_DLS"}), _string(kinematics["differential_solver_revision"], "differential_solver_revision", allowed={"DIFFERENTIAL_IK_DLS"})),
        mpc=MPCConfig(
            int(_number(mpc, "candidate_count", integer=True)),
            _integer_tuple(mpc["raw_direction_values"], "raw_direction_values", length=3),
            _tuple_floats(mpc["magnitudes_rad_s"], "magnitudes_rad_s", 3),
            *[float(_number(mpc, key)) for key in ("error_scale_m", "velocity_scale_rad_s", "soft_joint_margin_rad", "effort_weight", "barrier_weight", "terminal_error_weight", "stage_error_weight", "smoothness_weight")],
            _string(mpc["cost_revision"], "cost_revision", allowed={"DIMENSIONLESS_INTEGRATED_V1"}),
            _string(mpc["candidate_order_revision"], "candidate_order_revision", allowed={"MAGNITUDE_THEN_LEXICOGRAPHIC_V1"}),
            _string(mpc["transition_revision"], "transition_revision", allowed={"PREVIOUS_SELECTED_QDOT_V1"}),
        ),
        residual=ResidualConfig(
            _string(residual["nominal_revision"], "nominal_revision", allowed={"MINIMUM_JERK_1S"}),
            float(_number(residual, "nominal_duration_s")),
            float(_number(residual, "component_limit_rad")),
            _tuple_floats(residual["blend_coefficients"], "blend_coefficients", 3),
        ),
        conditions=ConditionsConfig(
            _integer_tuple(conditions["move_counts"], "move_counts", length=2),
            _string_tuple(conditions["probe_ids"], "probe_ids", length=2),
            _string(conditions["control_id"], "control_id", allowed={"STATIONARY_CONTROL"}),
            _string(conditions["core_fault_id"], "core_fault_id", allowed={"NONE"}),
            *[int(_number(conditions, key, integer=True)) for key in ("probe_policy_hz", "probe_latency_ms", "probe_move_count")],
            _string(conditions["drop_trigger"], "drop_trigger", allowed={"FIRST_RESPONSE_AT_OR_AFTER_FIRST_DISPLACEMENT"}),
            *[int(_number(conditions, key, integer=True)) for key in ("out_of_order_extra_ms", "stationary_policy_hz", "stationary_latency_ms", "stationary_first_seed_count")],
        ),
        stacks=tuple(stacks),
        metrics=MetricsConfig(
            _string(metrics["primary"], "primary", allowed={"RECOVERY_TIME_S"}),
            _string_tuple(metrics["secondary"], "secondary"),
            _string(metrics["percentile_revision"], "percentile_revision", allowed={"NEAREST_RANK"}),
        ),
        pilot=PilotConfig(
            *[int(_number(pilot, key, integer=True)) for key in ("seed_count", "tuning_seed_count", "evaluation_seed_count", "max_revisions")],
            tuple(_integer_tuple(row, "tuning_conditions", length=3) for row in pilot["tuning_conditions"]),
        ),
        confirmation=ConfirmationConfig(**{key: int(_number(confirmation, key, integer=True)) for key in ConfirmationConfig.__dataclass_fields__}),
        resources=resource_cfg,
        thresholds=ThresholdConfig(**{key: float(_number(thresholds, key)) for key in ThresholdConfig.__dataclass_fields__}),
    )
    if result.conditions.probe_ids != ("DROP", "OUT_OF_ORDER"):
        raise ValueError("probe_ids must be exactly DROP, OUT_OF_ORDER")
    expected_secondary = (
        "FINAL_ERROR_M", "MEAN_ERROR_M", "P95_ERROR_M", "ACTION_AGE_P95_S",
        "JOINT_JERK_P95", "SATURATION_FRACTION", "COMMAND_DISCONTINUITY_MEAN",
        "COMMAND_DISCONTINUITY_P95", "UNSAFE_COUNT", "CLAMP_FRACTION",
        "COMPUTE_P50_NS", "COMPUTE_P95_NS",
    )
    if result.metrics.secondary != expected_secondary:
        raise ValueError("secondary metrics must match the exact frozen order")
    if result.mpc.candidate_count != 79 or result.mpc.raw_direction_values != (-1, 0, 1):
        raise ValueError("MPC candidate grid must be the exact 79-candidate grid")
    return result


__all__ = [
    "ActionChunk", "ArmConfig", "ClampReport", "CommandStack", "Condition",
    "ControllerConfig", "EpisodeMetrics", "ExecutorState", "ExperimentConfig",
    "FaultKind", "PolicyInput", "ResourceConfig", "Scenario", "SeedMetrics",
    "ShardSpec", "TimingConfig", "canonical_json_bytes", "frozen_vector",
    "load_config", "sha256_file",
]
