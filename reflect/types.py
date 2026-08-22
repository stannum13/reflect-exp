"""Validated, immutable shared contracts for Reflect-Lite boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, TypeAlias

import numpy as np


JSONValue: TypeAlias = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]


class ContractValidationError(ValueError):
    """Raised when a shared contract does not satisfy its boundary invariants."""


class ActionRepresentation(str, Enum):
    JOINT_POSITION = "JOINT_POSITION"
    JOINT_DELTA = "JOINT_DELTA"
    JOINT_VELOCITY = "JOINT_VELOCITY"
    EEF_DELTA = "EEF_DELTA"
    EEF_TRAJECTORY = "EEF_TRAJECTORY"
    MPC_GOAL = "MPC_GOAL"
    BOUNDED_RESIDUAL = "BOUNDED_RESIDUAL"


class SkillState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"


class RecoveryDecision(Enum):
    CONTINUE = "continue"
    REFRESH = "refresh"
    RETRIGGER = "retrigger"
    ESCALATE = "escalate"
    ABORT = "abort"


def _require_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} must be a non-empty identifier")
    return value


def _require_non_negative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ContractValidationError(f"{field} must be a non-negative integer")
    return value


def _require_finite(value: object, field: str, *, positive: bool = False, non_negative: bool = False) -> float:
    if isinstance(value, bool):
        raise ContractValidationError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise ContractValidationError(f"{field} must be finite")
    if positive and number <= 0:
        raise ContractValidationError(f"{field} must be positive")
    if non_negative and number < 0:
        raise ContractValidationError(f"{field} must be non-negative")
    return number


def _require_confidence(value: object, field: str) -> float:
    number = _require_finite(value, field)
    if not 0.0 <= number <= 1.0:
        raise ContractValidationError(f"{field} must be within [0, 1]")
    return number


def _freeze_array(
    value: object,
    field: str,
    *,
    ndim: int,
    shape: tuple[int, ...] | None = None,
) -> np.ndarray:
    try:
        result = np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"{field} must be a numeric array") from exc
    if result.ndim != ndim:
        raise ContractValidationError(f"{field} must have rank {ndim}")
    if shape is not None and result.shape != shape:
        raise ContractValidationError(f"{field} must have shape {shape}")
    if not np.isfinite(result).all():
        raise ContractValidationError(f"{field} must contain only finite values")
    result.setflags(write=False)
    return result


def _freeze_optional_vector(value: object | None, field: str) -> np.ndarray | None:
    return None if value is None else _freeze_array(value, field, ndim=1)


def _freeze_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise ContractValidationError(f"{field} keys must be strings")
    return MappingProxyType(dict(value))


def _freeze_string_tuple(value: object, field: str, *, non_empty: bool = False) -> tuple[str, ...]:
    if isinstance(value, str):
        raise ContractValidationError(f"{field} must be a tuple of identifiers")
    try:
        result = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ContractValidationError(f"{field} must be iterable") from exc
    if non_empty and not result:
        raise ContractValidationError(f"{field} must not be empty")
    return tuple(_require_identifier(item, field) for item in result)


def _freeze_contract_tuple(value: object, field: str, contract_type: type[object]) -> tuple[object, ...]:
    if isinstance(value, (str, bytes)):
        raise ContractValidationError(f"{field} must be a tuple")
    try:
        result = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ContractValidationError(f"{field} must be iterable") from exc
    if not all(isinstance(item, contract_type) for item in result):
        raise ContractValidationError(f"{field} contains an invalid contract")
    for item in result:
        validate_contract(item)
    return result


@dataclass(frozen=True)
class Pose:
    position: np.ndarray
    quaternion_wxyz: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "position", _freeze_array(self.position, "position", ndim=1, shape=(3,)))
        object.__setattr__(self, "quaternion_wxyz", _freeze_array(self.quaternion_wxyz, "quaternion_wxyz", ndim=1, shape=(4,)))


@dataclass(frozen=True)
class RobotState:
    q: np.ndarray
    dq: np.ndarray

    def __post_init__(self) -> None:
        q = _freeze_array(self.q, "q", ndim=1)
        dq = _freeze_array(self.dq, "dq", ndim=1)
        if q.shape != dq.shape:
            raise ContractValidationError("q and dq must have the same shape")
        object.__setattr__(self, "q", q)
        object.__setattr__(self, "dq", dq)


@dataclass(frozen=True)
class Constraint:
    kind: str
    parameters: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _require_identifier(self.kind, "kind"))
        object.__setattr__(self, "parameters", _freeze_mapping(self.parameters, "parameters"))


@dataclass(frozen=True)
class Predicate:
    kind: str
    parameters: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _require_identifier(self.kind, "kind"))
        object.__setattr__(self, "parameters", _freeze_mapping(self.parameters, "parameters"))


@dataclass(frozen=True)
class SemanticGoal:
    goal_id: str
    entity_ids: tuple[str, ...]
    objective: str
    constraints: tuple[Constraint, ...]
    success_predicate: Predicate

    def __post_init__(self) -> None:
        object.__setattr__(self, "goal_id", _require_identifier(self.goal_id, "goal_id"))
        object.__setattr__(self, "entity_ids", _freeze_string_tuple(self.entity_ids, "entity_ids", non_empty=True))
        object.__setattr__(self, "objective", _require_identifier(self.objective, "objective"))
        object.__setattr__(self, "constraints", _freeze_contract_tuple(self.constraints, "constraints", Constraint))
        if not isinstance(self.success_predicate, Predicate):
            raise ContractValidationError("success_predicate must be a Predicate")
        validate_contract(self.success_predicate)


@dataclass(frozen=True)
class SkillSpec:
    skill_id: str
    skill_type: str
    target_entities: tuple[str, ...]
    target_pose: Pose | None
    constraints: tuple[Constraint, ...]
    success_predicate: Predicate
    timeout_s: float
    retry_budget: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "skill_id", _require_identifier(self.skill_id, "skill_id"))
        object.__setattr__(self, "skill_type", _require_identifier(self.skill_type, "skill_type"))
        object.__setattr__(self, "target_entities", _freeze_string_tuple(self.target_entities, "target_entities", non_empty=True))
        if self.target_pose is not None:
            if not isinstance(self.target_pose, Pose):
                raise ContractValidationError("target_pose must be a Pose or None")
            validate_contract(self.target_pose)
        object.__setattr__(self, "constraints", _freeze_contract_tuple(self.constraints, "constraints", Constraint))
        if not isinstance(self.success_predicate, Predicate):
            raise ContractValidationError("success_predicate must be a Predicate")
        validate_contract(self.success_predicate)
        object.__setattr__(self, "timeout_s", _require_finite(self.timeout_s, "timeout_s", positive=True))
        object.__setattr__(self, "retry_budget", _require_non_negative_int(self.retry_budget, "retry_budget"))


@dataclass
class ObjectBelief:
    entity_id: str
    label: str
    pose: np.ndarray | None
    pose_confidence: float
    state: Mapping[str, Any]
    state_confidence: float
    last_seen_ns: int
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        self.entity_id = _require_identifier(self.entity_id, "entity_id")
        self.label = _require_identifier(self.label, "label")
        self.pose = _freeze_optional_vector(self.pose, "pose")
        self.pose_confidence = _require_confidence(self.pose_confidence, "pose_confidence")
        self.state = _freeze_mapping(self.state, "state")
        self.state_confidence = _require_confidence(self.state_confidence, "state_confidence")
        self.last_seen_ns = _require_non_negative_int(self.last_seen_ns, "last_seen_ns")
        self.provenance = _freeze_string_tuple(self.provenance, "provenance")


@dataclass(frozen=True)
class Observation:
    sequence_id: int
    source_time_ns: int
    received_time_ns: int
    robot_state: RobotState
    object_beliefs: tuple[ObjectBelief, ...]
    current_skill_id: str | None
    current_phase: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sequence_id", _require_non_negative_int(self.sequence_id, "sequence_id"))
        object.__setattr__(self, "source_time_ns", _require_non_negative_int(self.source_time_ns, "source_time_ns"))
        object.__setattr__(self, "received_time_ns", _require_non_negative_int(self.received_time_ns, "received_time_ns"))
        if not isinstance(self.robot_state, RobotState):
            raise ContractValidationError("robot_state must be a RobotState")
        validate_contract(self.robot_state)
        object.__setattr__(self, "object_beliefs", _freeze_contract_tuple(self.object_beliefs, "object_beliefs", ObjectBelief))
        if self.current_skill_id is not None:
            object.__setattr__(self, "current_skill_id", _require_identifier(self.current_skill_id, "current_skill_id"))
        if self.current_phase is not None:
            object.__setattr__(self, "current_phase", _require_identifier(self.current_phase, "current_phase"))


@dataclass(frozen=True)
class ActionChunk:
    chunk_id: str
    skill_id: str
    source_observation_id: int
    source_observation_time_ns: int
    generated_time_ns: int
    valid_from_ns: int
    expires_at_ns: int
    dt_s: float
    actions: np.ndarray
    representation: str
    expected_phase: str | None
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunk_id", _require_identifier(self.chunk_id, "chunk_id"))
        object.__setattr__(self, "skill_id", _require_identifier(self.skill_id, "skill_id"))
        for field in ("source_observation_id", "source_observation_time_ns", "generated_time_ns", "valid_from_ns", "expires_at_ns"):
            object.__setattr__(self, field, _require_non_negative_int(getattr(self, field), field))
        if self.expires_at_ns < self.valid_from_ns:
            raise ContractValidationError("expires_at_ns must be at or after valid_from_ns")
        object.__setattr__(self, "dt_s", _require_finite(self.dt_s, "dt_s", positive=True))
        object.__setattr__(self, "actions", _freeze_array(self.actions, "actions", ndim=2))
        try:
            representation = ActionRepresentation(self.representation).value
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("representation is not supported") from exc
        object.__setattr__(self, "representation", representation)
        if self.expected_phase is not None:
            object.__setattr__(self, "expected_phase", _require_identifier(self.expected_phase, "expected_phase"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))


@dataclass(frozen=True)
class ControlReference:
    source_chunk_id: str
    time_ns: int
    q_ref: np.ndarray | None
    dq_ref: np.ndarray | None
    eef_ref: np.ndarray | None
    feedforward: np.ndarray | None
    controller_mode: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_chunk_id", _require_identifier(self.source_chunk_id, "source_chunk_id"))
        object.__setattr__(self, "time_ns", _require_non_negative_int(self.time_ns, "time_ns"))
        for field in ("q_ref", "dq_ref", "eef_ref", "feedforward"):
            object.__setattr__(self, field, _freeze_optional_vector(getattr(self, field), field))
        object.__setattr__(self, "controller_mode", _require_identifier(self.controller_mode, "controller_mode"))


@dataclass(frozen=True)
class SceneRelation:
    subject_id: str
    predicate: str
    object_id: str
    confidence: float
    observed_at_ns: int
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _require_identifier(self.subject_id, "subject_id"))
        object.__setattr__(self, "predicate", _require_identifier(self.predicate, "predicate"))
        object.__setattr__(self, "object_id", _require_identifier(self.object_id, "object_id"))
        object.__setattr__(self, "confidence", _require_confidence(self.confidence, "confidence"))
        object.__setattr__(self, "observed_at_ns", _require_non_negative_int(self.observed_at_ns, "observed_at_ns"))
        object.__setattr__(self, "provenance", _freeze_string_tuple(self.provenance, "provenance"))


@dataclass(frozen=True)
class WorldModelPrediction:
    observation_id: int
    candidate_id: str
    horizon_s: float
    predicted_progress: float
    predicted_success_probability: float
    predicted_failure_probabilities: Mapping[str, float]
    predicted_state: np.ndarray | None
    predicted_latent: np.ndarray | None
    uncertainty: float | None
    inference_ms: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _require_non_negative_int(self.observation_id, "observation_id"))
        object.__setattr__(self, "candidate_id", _require_identifier(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "horizon_s", _require_finite(self.horizon_s, "horizon_s", positive=True))
        object.__setattr__(self, "predicted_progress", _require_finite(self.predicted_progress, "predicted_progress"))
        object.__setattr__(self, "predicted_success_probability", _require_confidence(self.predicted_success_probability, "predicted_success_probability"))
        probabilities = _freeze_mapping(self.predicted_failure_probabilities, "predicted_failure_probabilities")
        for name, probability in probabilities.items():
            _require_confidence(probability, f"predicted_failure_probabilities[{name}]")
        object.__setattr__(self, "predicted_failure_probabilities", probabilities)
        object.__setattr__(self, "predicted_state", _freeze_optional_vector(self.predicted_state, "predicted_state"))
        object.__setattr__(self, "predicted_latent", _freeze_optional_vector(self.predicted_latent, "predicted_latent"))
        if self.uncertainty is not None:
            object.__setattr__(self, "uncertainty", _require_finite(self.uncertainty, "uncertainty", non_negative=True))
        object.__setattr__(self, "inference_ms", _require_finite(self.inference_ms, "inference_ms", non_negative=True))


_CONTRACT_TYPES = (
    Pose,
    RobotState,
    Constraint,
    Predicate,
    SemanticGoal,
    SkillSpec,
    Observation,
    ActionChunk,
    ControlReference,
    ObjectBelief,
    SceneRelation,
    WorldModelPrediction,
)


def validate_contract(value: object) -> None:
    """Validate a supported contract, including values mutated after construction."""
    if type(value) not in _CONTRACT_TYPES:
        raise ContractValidationError(f"unsupported contract type: {type(value).__name__}")
    contract_type = type(value)
    values = {field.name: getattr(value, field.name) for field in fields(value)}
    contract_type(**values)
