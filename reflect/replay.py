"""Deterministic state reconstruction from validated rollout artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, TypeAlias, cast

from reflect.events import ExecutionEvent, ExecutionEventType
from reflect.rollout import (
    RolloutArtifact,
    RolloutValidationError,
    canonical_json_bytes,
    validate_rollout,
)
from reflect.types import (
    ControlReference,
    Observation,
    RecoveryDecision,
    SkillState,
)


FrozenJSONValue: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | tuple["FrozenJSONValue", ...]
    | Mapping[str, "FrozenJSONValue"]
)
MissionState: TypeAlias = Mapping[str, FrozenJSONValue]


@dataclass(frozen=True)
class ReplayState:
    """One immutable reconstruction snapshot after an execution event."""

    current_observation_id: int | None = None
    current_observation: Observation | None = None
    current_skill_id: str | None = None
    current_phase: str | None = None
    mission_state: MissionState | None = None
    accepted_chunk_ids: tuple[str, ...] = ()
    rejected_chunk_ids: tuple[str, ...] = ()
    replaced_chunk_ids: tuple[str, ...] = ()
    skill_state: SkillState = SkillState.IDLE
    recovery_decision: RecoveryDecision = RecoveryDecision.CONTINUE
    memory_mutation_ids: tuple[str, ...] = ()
    predicted_world_model_candidate_ids: tuple[str, ...] = ()
    selected_world_model_candidate_id: str | None = None
    executed_control_reference: ControlReference | None = None

    @property
    def memory_mutation_count(self) -> int:
        return len(self.memory_mutation_ids)


@dataclass(frozen=True)
class ReplayFrame:
    """One complete ordered event, any resolved observation, and resulting state."""

    event: ExecutionEvent
    observation: Observation | None
    original_line_index: int
    state: ReplayState

    @property
    def event_type(self) -> ExecutionEventType:
        return self.event.event_type

    @property
    def monotonic_time_ns(self) -> int:
        return self.event.monotonic_time_ns

    @property
    def sequence_id(self) -> int:
        return self.event.sequence_id


@dataclass(frozen=True)
class ReplayResult:
    """The complete deterministic reconstruction of one saved rollout."""

    rollout_id: str
    events: tuple[ExecutionEvent, ...]
    observations: tuple[Observation, ...]
    frames: tuple[ReplayFrame, ...]
    final_state: ReplayState

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def frame_count(self) -> int:
        return len(self.frames)


def _required_identifier(
    payload: Mapping[str, Any], key: str, event_type: ExecutionEventType
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RolloutValidationError(
            f"{event_type.value} event payload requires {key} as a non-empty identifier"
        )
    return value


def _required_non_negative_int(
    payload: Mapping[str, Any], key: str, event_type: ExecutionEventType
) -> int:
    value = payload.get(key)
    if type(value) is not int or value < 0:
        raise RolloutValidationError(
            f"{event_type.value} event payload requires {key} as a non-negative integer"
        )
    return value


def _append_unique(
    values: tuple[str, ...], value: str, event_type: str
) -> tuple[str, ...]:
    if value in values:
        raise RolloutValidationError(f"{event_type} payload reference {value} is ambiguous")
    return (*values, value)


def _required_mission_state(
    payload: Mapping[str, Any], event_type: ExecutionEventType
) -> MissionState:
    value = payload.get("mission_state")
    if not isinstance(value, Mapping):
        raise RolloutValidationError(
            f"{event_type.value} event payload requires mission_state as a JSON object"
        )
    return cast(MissionState, value)


def _resolve_observation(
    artifact: RolloutArtifact, observation_id: int
) -> Observation:
    matches = tuple(
        observation
        for observation in artifact.observations
        if observation.sequence_id == observation_id
    )
    if len(matches) != 1:
        raise RolloutValidationError(
            "OBSERVATION_RECEIVED must resolve to exactly one saved Observation"
        )
    return matches[0]


def _skill_update(state: ReplayState, event: ExecutionEvent) -> dict[str, Any]:
    skill_id = event.skill_id
    if skill_id is None:
        raise RolloutValidationError(
            f"{event.event_type.value} requires an explicit skill_id"
        )
    return {
        "current_skill_id": skill_id,
        "current_phase": (
            state.current_phase if state.current_skill_id == skill_id else None
        ),
    }


def _resolve_control_reference(
    artifact: RolloutArtifact, event: ExecutionEvent, source_chunk_id: str
) -> ControlReference:
    matches = tuple(
        reference
        for reference in artifact.control_references
        if reference.source_chunk_id == source_chunk_id
        and reference.time_ns == event.monotonic_time_ns
    )
    if len(matches) != 1:
        raise RolloutValidationError(
            "ACTION_EXECUTED must resolve to exactly one saved ControlReference"
        )
    return matches[0]


def _reduce_event(
    state: ReplayState, event: ExecutionEvent, artifact: RolloutArtifact
) -> ReplayState:
    """Purely reduce one saved event without consulting a simulator or environment."""
    event_type = event.event_type

    if event_type is ExecutionEventType.OBSERVATION_RECEIVED:
        observation_id = _required_non_negative_int(
            event.payload, "observation_id", event_type
        )
        observation = _resolve_observation(artifact, observation_id)
        return replace(
            state,
            current_observation_id=observation_id,
            current_observation=observation,
            current_skill_id=observation.current_skill_id,
            current_phase=observation.current_phase,
        )

    if event_type is ExecutionEventType.CHUNK_ACCEPTED:
        chunk_id = _required_identifier(event.payload, "chunk_id", event_type)
        return replace(
            state,
            accepted_chunk_ids=_append_unique(
                state.accepted_chunk_ids, chunk_id, event_type.value
            ),
        )

    if event_type in {
        ExecutionEventType.CHUNK_REJECTED_EXPIRED,
        ExecutionEventType.CHUNK_REJECTED_OUT_OF_ORDER,
    }:
        chunk_id = _required_identifier(event.payload, "chunk_id", event_type)
        return replace(
            state,
            accepted_chunk_ids=tuple(
                accepted for accepted in state.accepted_chunk_ids if accepted != chunk_id
            ),
            rejected_chunk_ids=_append_unique(
                state.rejected_chunk_ids, chunk_id, event_type.value
            ),
        )

    if event_type is ExecutionEventType.CHUNK_REPLACED:
        chunk_id = _required_identifier(event.payload, "chunk_id", event_type)
        return replace(
            state,
            accepted_chunk_ids=tuple(
                accepted for accepted in state.accepted_chunk_ids if accepted != chunk_id
            ),
            replaced_chunk_ids=_append_unique(
                state.replaced_chunk_ids, chunk_id, event_type.value
            ),
        )

    if event_type is ExecutionEventType.ACTION_EXECUTED:
        source_chunk_id = _required_identifier(
            event.payload, "source_chunk_id", event_type
        )
        reference = _resolve_control_reference(artifact, event, source_chunk_id)
        return replace(state, executed_control_reference=reference)

    if event_type is ExecutionEventType.SKILL_RETRIGGERED:
        return replace(
            state,
            recovery_decision=RecoveryDecision.RETRIGGER,
            **_skill_update(state, event),
        )

    if event_type is ExecutionEventType.SKILL_ESCALATED:
        return replace(
            state,
            recovery_decision=RecoveryDecision.ESCALATE,
            **_skill_update(state, event),
        )

    if event_type is ExecutionEventType.SKILL_STALLED:
        return replace(
            state,
            **_skill_update(state, event),
        )

    if event_type is ExecutionEventType.SKILL_SUCCEEDED:
        return replace(
            state,
            skill_state=SkillState.SUCCEEDED,
            **_skill_update(state, event),
        )

    if event_type is ExecutionEventType.SKILL_FAILED:
        return replace(
            state,
            skill_state=SkillState.FAILED,
            **_skill_update(state, event),
        )

    if event_type is ExecutionEventType.SEMANTIC_REPLAN:
        return replace(
            state,
            mission_state=_required_mission_state(event.payload, event_type),
        )

    if event_type is ExecutionEventType.MEMORY_UPDATED:
        mutation_id = _required_identifier(event.payload, "mutation_id", event_type)
        return replace(
            state,
            memory_mutation_ids=_append_unique(
                state.memory_mutation_ids, mutation_id, event_type.value
            ),
        )

    if event_type is ExecutionEventType.WORLD_MODEL_PREDICTED:
        candidate_id = _required_identifier(event.payload, "candidate_id", event_type)
        return replace(
            state,
            predicted_world_model_candidate_ids=(
                *state.predicted_world_model_candidate_ids,
                candidate_id,
            ),
        )

    if event_type is ExecutionEventType.WORLD_MODEL_SELECTED:
        candidate_id = _required_identifier(event.payload, "candidate_id", event_type)
        match_count = state.predicted_world_model_candidate_ids.count(candidate_id)
        if match_count != 1:
            qualifier = "missing" if match_count == 0 else "ambiguous"
            raise RolloutValidationError(
                f"WORLD_MODEL_SELECTED candidate_id {candidate_id} is {qualifier}"
            )
        return replace(state, selected_world_model_candidate_id=candidate_id)

    return state


def replay_rollout(path: Path) -> ReplayResult:
    """Validate and deterministically fold one saved rollout into replay frames."""
    artifact = validate_rollout(Path(path))
    ordered_events = sorted(
        enumerate(artifact.events),
        key=lambda indexed: (
            indexed[1].monotonic_time_ns,
            indexed[1].sequence_id,
            indexed[0],
        ),
    )
    state = ReplayState()
    frames: list[ReplayFrame] = []
    observations: list[Observation] = []
    for original_line_index, event in ordered_events:
        state = _reduce_event(state, event, artifact)
        observation = (
            state.current_observation
            if event.event_type is ExecutionEventType.OBSERVATION_RECEIVED
            else None
        )
        if observation is not None:
            observations.append(observation)
        frames.append(
            ReplayFrame(
                event=event,
                observation=observation,
                original_line_index=original_line_index,
                state=state,
            )
        )
    return ReplayResult(
        rollout_id=artifact.path.name,
        events=tuple(event for _, event in ordered_events),
        observations=tuple(observations),
        frames=tuple(frames),
        final_state=state,
    )


def format_replay(result: ReplayResult) -> str:
    """Return a compact canonical JSON replay summary."""
    return canonical_json_bytes(
        {
            "rollout_id": result.rollout_id,
            "event_count": result.event_count,
            "frame_count": result.frame_count,
            "final_skill_state": result.final_state.skill_state.value,
        }
    ).decode("utf-8")
