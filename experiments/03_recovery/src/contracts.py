"""Closed, immutable contracts for Experiment 03.

The recovery API intentionally has no field for injected cause or scorer truth.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any


_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class Architecture(str, Enum):
    LOCAL_ONLY = "R0"
    SEMANTIC_ALWAYS = "R1"
    MOTION_THEN_SEMANTIC = "R2"
    LAYER_MATCHED = "R3"


class RecoveryLevel(str, Enum):
    NONE = "NONE"
    CONTROL = "CONTROL"
    MOTION = "MOTION"
    SEMANTIC = "SEMANTIC"
    SAFE_ABORT = "SAFE_ABORT"


class ScenarioDomain(str, Enum):
    ANCHOR = "ANCHOR"
    CONTROL = "CONTROL"
    MOTION = "MOTION"
    SEMANTIC = "SEMANTIC"


class TerminalDisposition(str, Enum):
    SUCCESS = "SUCCESS"
    SAFE_ABORT = "SAFE_ABORT"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    NOT_RUN = "NOT_RUN"


def _ascii(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or not value.isascii():
        raise ValueError(f"{name} must be nonempty ASCII")
    return value


def _identity(value: str, name: str) -> str:
    _ascii(value, name)
    if _IDENTITY.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical identity")
    return value


def _sha(value: str, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _point(value: tuple[float, float], name: str) -> tuple[float, float]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ValueError(f"{name} must be a two-element tuple")
    return (_finite(value[0], name), _finite(value[1], name))


def _wire(value: object) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _wire(getattr(value, field.name)) for field in fields(value)}
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


@dataclass(frozen=True)
class MemoryFact:
    object_id: str
    semantic_label: str
    affordance: str
    restrictions: tuple[str, ...]
    pose_xy: tuple[float, float]
    available: bool
    observed_tick: int
    confidence: float
    provenance: str
    stale: bool
    unknown: bool

    def __post_init__(self) -> None:
        _identity(self.object_id, "object_id")
        _identity(self.semantic_label, "semantic_label")
        _identity(self.affordance, "affordance")
        if not isinstance(self.restrictions, tuple):
            raise ValueError("restrictions must be an immutable tuple")
        for item in self.restrictions:
            _identity(item, "restriction")
        object.__setattr__(self, "pose_xy", _point(self.pose_xy, "pose_xy"))
        if type(self.available) is not bool or type(self.stale) is not bool or type(self.unknown) is not bool:
            raise ValueError("memory dispositions must be booleans")
        if type(self.observed_tick) is not int or self.observed_tick < 0:
            raise ValueError("observed_tick must be a nonnegative integer")
        confidence = _finite(self.confidence, "confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        object.__setattr__(self, "confidence", confidence)
        _identity(self.provenance, "provenance")


@dataclass(frozen=True)
class MemorySnapshot:
    schema_id: str
    version: int
    facts: tuple[MemoryFact, ...]
    observation_tick: int
    evidence_ledger_sha256: str

    def __post_init__(self) -> None:
        if self.schema_id != "T3_LIVE_BELIEF_V1":
            raise ValueError("memory schema must be T3_LIVE_BELIEF_V1")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("memory version must be positive")
        if not isinstance(self.facts, tuple) or not self.facts or not all(isinstance(item, MemoryFact) for item in self.facts):
            raise ValueError("facts must be a nonempty immutable tuple")
        if type(self.observation_tick) is not int or self.observation_tick < 0:
            raise ValueError("observation_tick must be nonnegative")
        _sha(self.evidence_ledger_sha256, "evidence_ledger_sha256")

    def to_bytes(self) -> bytes:
        return canonical_bytes(self)

    @property
    def sha256(self) -> str:
        return sha256_bytes(self.to_bytes())


def base_memory_snapshot() -> MemorySnapshot:
    facts = (
        MemoryFact("object-a", "service-panel", "inspect", ("AUTHORIZED",), (0.55, 0.08), True, 0, 1.0, "scenario-record", False, False),
        MemoryFact("object-b", "service-panel", "inspect", ("AUTHORIZED",), (0.49, -0.14), True, 0, 1.0, "scenario-record", False, False),
    )
    ledger = sha256_bytes(canonical_bytes(tuple(_wire(item) for item in facts)))
    return MemorySnapshot("T3_LIVE_BELIEF_V1", 1, facts, 0, ledger)


@dataclass(frozen=True)
class SkillRequest:
    skill_id: str
    semantic_label: str
    affordance: str
    target_object_id: str
    admissible_region_xy: tuple[tuple[float, float], tuple[float, float]]
    restrictions: tuple[str, ...]
    memory_version: int
    success_predicate: str

    def __post_init__(self) -> None:
        for name in ("skill_id", "semantic_label", "affordance", "target_object_id", "success_predicate"):
            _identity(getattr(self, name), name)
        if not isinstance(self.admissible_region_xy, tuple) or len(self.admissible_region_xy) != 2:
            raise ValueError("admissible_region_xy must have lower and upper bounds")
        x_bounds = _point(self.admissible_region_xy[0], "x bounds")
        y_bounds = _point(self.admissible_region_xy[1], "y bounds")
        if x_bounds[0] > x_bounds[1] or y_bounds[0] > y_bounds[1]:
            raise ValueError("admissible region lower bound exceeds upper bound")
        object.__setattr__(self, "admissible_region_xy", (x_bounds, y_bounds))
        if not isinstance(self.restrictions, tuple):
            raise ValueError("restrictions must be a tuple")
        for item in self.restrictions:
            _identity(item, "restriction")
        if type(self.memory_version) is not int or self.memory_version < 1:
            raise ValueError("memory_version must be positive")


@dataclass(frozen=True)
class MotionCommand:
    command_id: str
    object_id: str
    target_xy: tuple[float, float]
    feasible: bool
    trajectory_sha256: str
    command_sha256: str
    generated_tick: int

    def __post_init__(self) -> None:
        _identity(self.command_id, "command_id")
        _identity(self.object_id, "object_id")
        object.__setattr__(self, "target_xy", _point(self.target_xy, "target_xy"))
        if type(self.feasible) is not bool:
            raise ValueError("feasible must be boolean")
        _sha(self.trajectory_sha256, "trajectory_sha256")
        _sha(self.command_sha256, "command_sha256")
        if type(self.generated_tick) is not int or self.generated_tick < 0:
            raise ValueError("generated_tick must be nonnegative")

    @classmethod
    def from_target(cls, command_id: str, object_id: str, target_xy: tuple[float, float], feasible: bool, generated_tick: int) -> "MotionCommand":
        trajectory_sha = sha256_bytes(canonical_bytes({"object_id": object_id, "target_xy": target_xy, "feasible": feasible}))
        command_sha = sha256_bytes(canonical_bytes({"command_id": command_id, "trajectory_sha256": trajectory_sha, "generated_tick": generated_tick}))
        return cls(command_id, object_id, target_xy, feasible, trajectory_sha, command_sha, generated_tick)


@dataclass(frozen=True)
class ObservableFailure:
    tracking_persistent: bool
    controller_safe: bool
    action_valid: bool
    geometry_feasible: bool
    semantic_preconditions_valid: bool
    previous_level: RecoveryLevel
    command_sha256: str
    new_command_generated: bool
    observed_tick: int

    def __post_init__(self) -> None:
        for name in ("tracking_persistent", "controller_safe", "action_valid", "geometry_feasible", "semantic_preconditions_valid", "new_command_generated"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        if not isinstance(self.previous_level, RecoveryLevel):
            raise ValueError("previous_level must be closed RecoveryLevel")
        _sha(self.command_sha256, "command_sha256")
        if type(self.observed_tick) is not int or self.observed_tick < 0:
            raise ValueError("observed_tick must be nonnegative")

    @property
    def detected(self) -> bool:
        return self.tracking_persistent or not self.controller_safe or not self.action_valid or not self.geometry_feasible or not self.semantic_preconditions_valid


@dataclass(frozen=True)
class RecoveryBudget:
    control_remaining: int
    motion_remaining: int
    semantic_remaining: int
    active_command_sha256: str

    def __post_init__(self) -> None:
        for name, maximum in (("control_remaining", 2), ("motion_remaining", 2), ("semantic_remaining", 1)):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError(f"{name} outside frozen budget")
        _sha(self.active_command_sha256, "active_command_sha256")

    @classmethod
    def initial(cls, command_sha256: str) -> "RecoveryBudget":
        return cls(2, 2, 1, command_sha256)


@dataclass(frozen=True)
class RecoveryDecision:
    level: RecoveryLevel
    reason: str
    budget: RecoveryBudget
    observed_tick: int
    command_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.level, RecoveryLevel):
            raise ValueError("level must be RecoveryLevel")
        _identity(self.reason, "reason")
        if not isinstance(self.budget, RecoveryBudget):
            raise ValueError("budget must be RecoveryBudget")
        if type(self.observed_tick) is not int or self.observed_tick < 0:
            raise ValueError("observed_tick must be nonnegative")
        _sha(self.command_sha256, "command_sha256")


@dataclass(frozen=True)
class EpisodeSpec:
    episode_id: str
    architecture: Architecture
    scenario_id: str
    scenario_domain: ScenarioDomain
    seed: int
    controller_id: str
    sensitivity: bool

    def __post_init__(self) -> None:
        _identity(self.episode_id, "episode_id")
        _identity(self.scenario_id, "scenario_id")
        if not isinstance(self.architecture, Architecture) or not isinstance(self.scenario_domain, ScenarioDomain):
            raise ValueError("episode uses open enum value")
        if type(self.seed) is not int or self.seed <= 0:
            raise ValueError("seed must be positive integer")
        _identity(self.controller_id, "controller_id")
        if type(self.sensitivity) is not bool:
            raise ValueError("sensitivity must be boolean")


__all__ = [
    "Architecture", "EpisodeSpec", "MemoryFact", "MemorySnapshot", "MotionCommand",
    "ObservableFailure", "RecoveryBudget", "RecoveryDecision", "RecoveryLevel",
    "ScenarioDomain", "SkillRequest", "TerminalDisposition", "base_memory_snapshot",
    "canonical_bytes", "sha256_bytes",
]
