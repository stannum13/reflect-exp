"""Closed contracts for the V3 calibration-only qualification stage.

The observable contract deliberately has no scenario taxonomy or scorer truth.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any

import numpy as np


CALIBRATION_SEEDS = (20261891, 20261892, 20261893, 20261894)
SCENARIO_IDS = (
    "anchor-nominal",
    "anchor-slow-policy",
    "control-impulse",
    "control-dropout",
    "motion-target-shift",
    "motion-path-infeasible",
    "semantic-object-unavailable",
    "semantic-restriction-change",
)
PRIMARY_CONTROLLER_ID = "P6-res0p5-slew48"
SENSITIVITY_CONTROLLER_ID = "P4-lookahead1-dqon"
TIMESTEP_S = 0.002
REOBSERVE_TICKS = 25
EPISODE_TICKS = 3125
_SHA256 = re.compile(r"[0-9a-f]{64}")


class Architecture(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class DecisionLevel(str, Enum):
    NONE = "NONE"
    CONTROL = "CONTROL"
    MOTION = "MOTION"
    SEMANTIC = "SEMANTIC"
    SAFE_ABORT = "SAFE_ABORT"


def _wire(value: object) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _wire(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, tuple):
        return [_wire(item) for item in value]
    if isinstance(value, list):
        return [_wire(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _wire(item) for key, item in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("canonical bytes reject nonfinite values")
    return value


def canonical_bytes(value: object) -> bytes:
    return json.dumps(_wire(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(value: str, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")


def _finite_tuple(value: tuple[float, ...], length: int, name: str) -> tuple[float, ...]:
    if not isinstance(value, tuple) or len(value) != length:
        raise ValueError(f"{name} must contain {length} values")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} must be finite")
    return result


@dataclass(frozen=True)
class V3Realization:
    scenario_id: str
    seed: int
    q0: tuple[float, float, float]
    target_a_xy: tuple[float, float]
    target_b_xy: tuple[float, float]
    injection_tick: int
    impulse_nm: float
    impulse_ticks: int
    dropout_ticks: int
    target_shift_xy: tuple[float, float]
    obstacle_xy: tuple[float, float]
    obstacle_radius_m: float
    damping_multiplier: float
    semantic_delay_ticks: int
    parameter_sha256: str

    def __post_init__(self) -> None:
        if self.scenario_id not in SCENARIO_IDS:
            raise ValueError("unknown V3 scenario")
        if self.seed not in CALIBRATION_SEEDS:
            raise ValueError("V3 qualification accepts calibration seeds only")
        object.__setattr__(self, "q0", _finite_tuple(self.q0, 3, "q0"))
        for name in ("target_a_xy", "target_b_xy", "target_shift_xy", "obstacle_xy"):
            object.__setattr__(self, name, _finite_tuple(getattr(self, name), 2, name))
        if not 600 <= self.injection_tick <= 900:
            raise ValueError("injection tick outside preregistered range")
        if not 0.12 <= self.impulse_nm <= 0.28:
            raise ValueError("impulse outside preregistered N.m range")
        if not 4 <= self.impulse_ticks <= 12 or not 20 <= self.dropout_ticks <= 55:
            raise ValueError("disturbance duration outside preregistered range")
        if not 0.035 <= math.hypot(*self.target_shift_xy) <= 0.070000000001:
            raise ValueError("target shift outside preregistered metre range")
        if not 0.035 <= self.obstacle_radius_m <= 0.05:
            raise ValueError("obstacle radius outside preregistered range")
        if not 0.9 <= self.damping_multiplier <= 1.1 or not 0 <= self.semantic_delay_ticks <= 12:
            raise ValueError("realization parameter outside preregistered range")
        _sha(self.parameter_sha256, "parameter_sha256")


def make_realization(scenario_id: str, seed: int) -> V3Realization:
    """Sample one calibration realization; outcome seeds are rejected at this API."""
    if scenario_id not in SCENARIO_IDS:
        raise ValueError("unknown V3 scenario")
    if seed not in CALIBRATION_SEEDS:
        raise ValueError("V3 qualification accepts calibration seeds only")
    namespace = int.from_bytes(hashlib.sha256(f"hierarchy-v3-qualification:{seed}".encode("ascii")).digest()[:8], "little")
    rng = np.random.Generator(np.random.PCG64(namespace))
    q0 = tuple(float(item) for item in np.array((0.35, -0.70, 0.35)) + rng.uniform(-0.025, 0.025, 3))
    target_a = np.array((0.55, 0.08)) + rng.uniform(-0.018, 0.018, 2)
    target_b = np.array((0.49, -0.14)) + rng.uniform(-0.018, 0.018, 2)
    shift_m = float(rng.uniform(0.035, 0.070))
    shift_angle = float(rng.uniform(-math.pi, math.pi))
    shift = shift_m * np.array((math.cos(shift_angle), math.sin(shift_angle)))
    angles = np.cumsum(np.asarray(q0))
    links = np.asarray((0.30, 0.25, 0.20))
    start = np.asarray((np.dot(links, np.cos(angles)), np.dot(links, np.sin(angles))))
    midpoint = (start + target_a) / 2.0
    obstacle = midpoint + rng.uniform(-0.006, 0.006, 2)
    sampled = {
        "q0": q0,
        "target_a_xy": tuple(float(item) for item in target_a),
        "target_b_xy": tuple(float(item) for item in target_b),
        "injection_tick": int(rng.integers(600, 901)),
        "impulse_nm": float(rng.uniform(0.12, 0.28)),
        "impulse_ticks": int(rng.integers(4, 13)),
        "dropout_ticks": int(rng.integers(20, 56)),
        "target_shift_xy": tuple(float(item) for item in shift),
        "obstacle_xy": tuple(float(item) for item in obstacle),
        "obstacle_radius_m": float(rng.uniform(0.035, 0.050)),
        "damping_multiplier": float(rng.uniform(0.90, 1.10)),
        "semantic_delay_ticks": int(rng.integers(0, 13)),
    }
    return V3Realization(scenario_id, seed, **sampled, parameter_sha256=sha256_bytes(canonical_bytes(sampled)))


@dataclass(frozen=True)
class ObservableState:
    tick: int
    history_start_tick: int
    tracking_error_mean_m: float
    tracking_error_slope_m_per_tick: float
    external_load_mean_nm: float
    command_gap_ticks: int
    controller_safe: bool
    action_valid: bool
    geometry_feasible: bool
    semantic_preconditions_valid: bool
    memory_version: int
    command_content_sha256: str
    successful_execution_content_sha256: str
    reobserve_index: int

    def __post_init__(self) -> None:
        if type(self.tick) is not int or type(self.history_start_tick) is not int or self.tick < 0 or not 0 <= self.history_start_tick <= self.tick:
            raise ValueError("observable tick interval is invalid")
        for name in ("tracking_error_mean_m", "tracking_error_slope_m_per_tick", "external_load_mean_nm"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        for name in ("controller_safe", "action_valid", "geometry_feasible", "semantic_preconditions_valid"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        if type(self.memory_version) is not int or self.memory_version < 1:
            raise ValueError("memory version must be positive")
        if type(self.command_gap_ticks) is not int or self.command_gap_ticks < 0:
            raise ValueError("command gap ticks must be nonnegative")
        _sha(self.command_content_sha256, "command_content_sha256")
        _sha(self.successful_execution_content_sha256, "successful_execution_content_sha256")
        if type(self.reobserve_index) is not int or self.reobserve_index < 0:
            raise ValueError("reobserve index must be nonnegative")

    @property
    def sha256(self) -> str:
        return sha256_bytes(canonical_bytes(self))

    @property
    def failure_detected(self) -> bool:
        return (
            (self.tracking_error_mean_m > 0.10 and self.tracking_error_slope_m_per_tick >= -1e-5)
            or self.external_load_mean_nm > 0.05
            or self.command_gap_ticks > 0
            or not self.controller_safe
            or not self.action_valid
            or not self.geometry_feasible
            or not self.semantic_preconditions_valid
        )


@dataclass(frozen=True)
class BudgetState:
    control_remaining: int
    motion_remaining: int
    semantic_remaining: int
    active_content_sha256: str
    last_observed_tick: int

    def __post_init__(self) -> None:
        for name, maximum in (("control_remaining", 2), ("motion_remaining", 2), ("semantic_remaining", 1)):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError(f"{name} outside frozen budget")
        _sha(self.active_content_sha256, "active_content_sha256")
        if type(self.last_observed_tick) is not int or self.last_observed_tick < -1:
            raise ValueError("last observed tick is invalid")


def initial_budget(content_sha256: str) -> BudgetState:
    return BudgetState(2, 2, 1, content_sha256, -1)


@dataclass(frozen=True)
class DecisionEvent:
    architecture: Architecture
    level: DecisionLevel
    reason: str
    observed_tick: int
    observable_sha256: str
    budget_before: BudgetState
    budget_after: BudgetState

    def __post_init__(self) -> None:
        if not isinstance(self.architecture, Architecture) or not isinstance(self.level, DecisionLevel):
            raise ValueError("decision enums must be closed")
        if not isinstance(self.reason, str) or not self.reason.isascii() or not self.reason:
            raise ValueError("reason must be nonempty ASCII")
        _sha(self.observable_sha256, "observable_sha256")


__all__ = [
    "Architecture",
    "BudgetState",
    "CALIBRATION_SEEDS",
    "DecisionEvent",
    "DecisionLevel",
    "EPISODE_TICKS",
    "ObservableState",
    "PRIMARY_CONTROLLER_ID",
    "REOBSERVE_TICKS",
    "SCENARIO_IDS",
    "SENSITIVITY_CONTROLLER_ID",
    "TIMESTEP_S",
    "V3Realization",
    "canonical_bytes",
    "initial_budget",
    "make_realization",
    "sha256_bytes",
]
