from __future__ import annotations

import math

import pytest

from reflect.events import (
    EventStream,
    EventValidationError,
    ExecutionEvent,
    ExecutionEventType,
    event_from_dict,
    event_to_dict,
)


def valid_event(**changes: object) -> ExecutionEvent:
    values: dict[str, object] = {
        "event_type": ExecutionEventType.OBSERVATION_RECEIVED,
        "monotonic_time_ns": 10,
        "wall_time_ns": 20,
        "rollout_id": "rollout-1",
        "sequence_id": 2,
        "component": "perception",
        "config_hash": "abc123",
    }
    values.update(changes)
    return ExecutionEvent(**values)  # type: ignore[arg-type]


def test_execution_event_types_match_the_minimum_canonical_schema() -> None:
    assert {event_type.value for event_type in ExecutionEventType} == {
        "OBSERVATION_RECEIVED",
        "POLICY_REQUESTED",
        "POLICY_RESPONDED",
        "CHUNK_ACCEPTED",
        "CHUNK_REJECTED_EXPIRED",
        "CHUNK_REJECTED_OUT_OF_ORDER",
        "CHUNK_REPLACED",
        "ACTION_EXECUTED",
        "PROGRESS_UPDATED",
        "SKILL_STALLED",
        "SKILL_RETRIGGERED",
        "SKILL_ESCALATED",
        "SKILL_SUCCEEDED",
        "SKILL_FAILED",
        "MEMORY_UPDATED",
        "SEMANTIC_REPLAN",
        "WORLD_MODEL_PREDICTED",
        "WORLD_MODEL_SELECTED",
        "SAFETY_REJECTED",
    }


def test_event_stream_rejects_time_or_sequence_regression() -> None:
    stream = EventStream("rollout-1")
    stream.append(valid_event(monotonic_time_ns=10, sequence_id=2))

    with pytest.raises(EventValidationError, match="monotonic"):
        stream.append(valid_event(monotonic_time_ns=9, sequence_id=3))
    with pytest.raises(EventValidationError, match="sequence"):
        stream.append(valid_event(monotonic_time_ns=11, sequence_id=1))


def test_event_stream_accepts_equal_ordering_keys_and_iterates_in_append_order() -> None:
    stream = EventStream("rollout-1")
    first = valid_event(sequence_id=2)
    second = valid_event(event_type=ExecutionEventType.POLICY_REQUESTED, sequence_id=2)

    stream.append(first)
    stream.append(second)

    assert tuple(stream) == (first, second)


def test_event_stream_rejects_a_different_rollout_id() -> None:
    stream = EventStream("rollout-1")

    with pytest.raises(EventValidationError, match="rollout"):
        stream.append(valid_event(rollout_id="rollout-2"))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("monotonic_time_ns", True, "non-negative"),
        ("wall_time_ns", -1, "non-negative"),
        ("sequence_id", True, "non-negative"),
        ("rollout_id", "", "non-empty"),
        ("component", " ", "non-empty"),
        ("config_hash", "", "non-empty"),
        ("object_ids", ("",), "non-empty"),
        ("skill_id", " ", "non-empty"),
        ("event_type", "NOT_A_EVENT", "event type"),
    ],
)
def test_execution_event_rejects_invalid_boundary_fields(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(EventValidationError, match=message):
        valid_event(**{field: value})


@pytest.mark.parametrize(
    "payload",
    [
        {"bad": object()},
        {"bad": ("not", "json")},
        {"bad": math.nan},
        {"bad": math.inf},
        {1: "not-a-string-key"},
        {"nested": [0, {"bad": -math.inf}]},
    ],
)
def test_execution_event_rejects_non_json_safe_payloads(payload: object) -> None:
    with pytest.raises(EventValidationError, match="payload"):
        valid_event(payload=payload)


def test_event_dictionary_round_trip_preserves_optional_ids_and_json_payload() -> None:
    event = valid_event(
        event_type=ExecutionEventType.SKILL_RETRIGGERED,
        object_ids=("mug-1", "table-2"),
        skill_id="pick-mug",
        payload={"attempt": 2, "metadata": {"safe": True}, "scores": [0.2, None]},
    )

    raw = event_to_dict(event)

    assert raw == {
        "event_type": "SKILL_RETRIGGERED",
        "monotonic_time_ns": 10,
        "wall_time_ns": 20,
        "rollout_id": "rollout-1",
        "sequence_id": 2,
        "component": "perception",
        "config_hash": "abc123",
        "object_ids": ["mug-1", "table-2"],
        "skill_id": "pick-mug",
        "payload": {"attempt": 2, "metadata": {"safe": True}, "scores": [0.2, None]},
    }
    assert event_from_dict(raw) == event


def test_event_from_dict_rejects_missing_or_extra_wire_keys() -> None:
    raw = event_to_dict(valid_event())
    missing = dict(raw)
    missing.pop("payload")
    extra = dict(raw)
    extra["unknown"] = "value"

    with pytest.raises(EventValidationError, match="missing"):
        event_from_dict(missing)
    with pytest.raises(EventValidationError, match="extra"):
        event_from_dict(extra)
