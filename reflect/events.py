"""Canonical, validated execution events for rollout artifacts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum
import math
from types import MappingProxyType

from reflect.types import JSONValue


class EventValidationError(ValueError):
    """Raised when an execution event cannot cross the artifact boundary."""


class ExecutionEventType(str, Enum):
    OBSERVATION_RECEIVED = "OBSERVATION_RECEIVED"
    POLICY_REQUESTED = "POLICY_REQUESTED"
    POLICY_RESPONDED = "POLICY_RESPONDED"
    CHUNK_ACCEPTED = "CHUNK_ACCEPTED"
    CHUNK_REJECTED_EXPIRED = "CHUNK_REJECTED_EXPIRED"
    CHUNK_REJECTED_OUT_OF_ORDER = "CHUNK_REJECTED_OUT_OF_ORDER"
    CHUNK_REPLACED = "CHUNK_REPLACED"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    PROGRESS_UPDATED = "PROGRESS_UPDATED"
    SKILL_STALLED = "SKILL_STALLED"
    SKILL_RETRIGGERED = "SKILL_RETRIGGERED"
    SKILL_ESCALATED = "SKILL_ESCALATED"
    SKILL_SUCCEEDED = "SKILL_SUCCEEDED"
    SKILL_FAILED = "SKILL_FAILED"
    MEMORY_UPDATED = "MEMORY_UPDATED"
    SEMANTIC_REPLAN = "SEMANTIC_REPLAN"
    WORLD_MODEL_PREDICTED = "WORLD_MODEL_PREDICTED"
    WORLD_MODEL_SELECTED = "WORLD_MODEL_SELECTED"
    SAFETY_REJECTED = "SAFETY_REJECTED"


def _checked_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EventValidationError(f"{field} must be a non-empty identifier")
    return value


def _checked_non_negative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise EventValidationError(f"{field} must be a non-negative integer")
    return value


def _normalize_json_value(value: object, field: str = "payload") -> JSONValue:
    if value is None or isinstance(value, (bool, str)):
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise EventValidationError(f"{field} must contain only finite floats")
        return value
    if isinstance(value, list):
        return [_normalize_json_value(item, field) for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise EventValidationError(f"{field} object keys must be strings")
            normalized[key] = _normalize_json_value(item, field)
        return normalized
    raise EventValidationError(f"{field} must contain only JSON-safe values")


def _normalize_object_ids(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise EventValidationError("object_ids must be an iterable of identifiers")
    try:
        object_ids = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise EventValidationError("object_ids must be an iterable of identifiers") from exc
    return tuple(_checked_identifier(item, "object_ids") for item in object_ids)


@dataclass(frozen=True)
class ExecutionEvent:
    event_type: ExecutionEventType
    monotonic_time_ns: int
    wall_time_ns: int
    rollout_id: str
    sequence_id: int
    component: str
    config_hash: str
    object_ids: tuple[str, ...] = ()
    skill_id: str | None = None
    payload: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            event_type = ExecutionEventType(self.event_type)
        except (TypeError, ValueError) as exc:
            raise EventValidationError("event type is not supported") from exc
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(
            self,
            "monotonic_time_ns",
            _checked_non_negative_int(self.monotonic_time_ns, "monotonic_time_ns"),
        )
        object.__setattr__(
            self, "wall_time_ns", _checked_non_negative_int(self.wall_time_ns, "wall_time_ns")
        )
        object.__setattr__(self, "rollout_id", _checked_identifier(self.rollout_id, "rollout_id"))
        object.__setattr__(
            self, "sequence_id", _checked_non_negative_int(self.sequence_id, "sequence_id")
        )
        object.__setattr__(self, "component", _checked_identifier(self.component, "component"))
        object.__setattr__(self, "config_hash", _checked_identifier(self.config_hash, "config_hash"))
        object.__setattr__(self, "object_ids", _normalize_object_ids(self.object_ids))
        if self.skill_id is not None:
            object.__setattr__(self, "skill_id", _checked_identifier(self.skill_id, "skill_id"))
        normalized_payload = _normalize_json_value(self.payload)
        if not isinstance(normalized_payload, dict):
            raise EventValidationError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(normalized_payload))


class EventStream:
    """An append-only event stream ordered by monotonic time and sequence."""

    def __init__(self, rollout_id: str) -> None:
        self._rollout_id = _checked_identifier(rollout_id, "rollout_id")
        self._events: list[ExecutionEvent] = []

    def append(self, event: ExecutionEvent) -> None:
        if not isinstance(event, ExecutionEvent):
            raise EventValidationError("event must be an ExecutionEvent")
        if event.rollout_id != self._rollout_id:
            raise EventValidationError("event rollout_id must match the stream rollout_id")
        if self._events:
            previous = self._events[-1]
            if event.monotonic_time_ns < previous.monotonic_time_ns:
                raise EventValidationError("event monotonic time must not regress")
            if event.sequence_id < previous.sequence_id:
                raise EventValidationError("event sequence must not regress")
        self._events.append(event)

    def __iter__(self) -> Iterator[ExecutionEvent]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)


_EVENT_KEYS = frozenset(
    {
        "event_type",
        "monotonic_time_ns",
        "wall_time_ns",
        "rollout_id",
        "sequence_id",
        "component",
        "config_hash",
        "object_ids",
        "skill_id",
        "payload",
    }
)


def event_to_dict(event: ExecutionEvent) -> dict[str, JSONValue]:
    """Convert an event to its JSON-native wire representation."""
    if not isinstance(event, ExecutionEvent):
        raise EventValidationError("event must be an ExecutionEvent")
    return {
        "event_type": event.event_type.value,
        "monotonic_time_ns": event.monotonic_time_ns,
        "wall_time_ns": event.wall_time_ns,
        "rollout_id": event.rollout_id,
        "sequence_id": event.sequence_id,
        "component": event.component,
        "config_hash": event.config_hash,
        "object_ids": list(event.object_ids),
        "skill_id": event.skill_id,
        "payload": _normalize_json_value(event.payload),
    }


def event_from_dict(raw: object) -> ExecutionEvent:
    """Reconstruct a validated event, rejecting non-canonical wire objects."""
    if not isinstance(raw, Mapping):
        raise EventValidationError("event wire value must be a mapping")
    keys = set(raw)
    missing = _EVENT_KEYS - keys
    extra = keys - _EVENT_KEYS
    if missing:
        raise EventValidationError(f"event wire value has missing keys: {sorted(missing)}")
    if extra:
        raise EventValidationError(f"event wire value has extra keys: {sorted(extra)}")
    return ExecutionEvent(
        event_type=raw["event_type"],  # type: ignore[arg-type]
        monotonic_time_ns=raw["monotonic_time_ns"],  # type: ignore[arg-type]
        wall_time_ns=raw["wall_time_ns"],  # type: ignore[arg-type]
        rollout_id=raw["rollout_id"],  # type: ignore[arg-type]
        sequence_id=raw["sequence_id"],  # type: ignore[arg-type]
        component=raw["component"],  # type: ignore[arg-type]
        config_hash=raw["config_hash"],  # type: ignore[arg-type]
        object_ids=raw["object_ids"],  # type: ignore[arg-type]
        skill_id=raw["skill_id"],  # type: ignore[arg-type]
        payload=raw["payload"],  # type: ignore[arg-type]
    )
