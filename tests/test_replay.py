from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from reflect.events import ExecutionEvent, ExecutionEventType
from reflect.replay import replay_rollout
from reflect.rollout import (
    SCHEMA_VERSION,
    RolloutMetadata,
    RolloutRecord,
    RolloutValidationError,
    RolloutWriter,
    sha256_json,
)
from reflect.types import (
    ActionChunk,
    ControlReference,
    Observation,
    RecoveryDecision,
    RobotState,
    SkillState,
)


CONFIG = {"task": "replay-test"}


def _metadata() -> RolloutMetadata:
    return RolloutMetadata(
        experiment_id="replay-experiment",
        claim_revision=1,
        git_sha="1" * 40,
        working_tree_clean=True,
        dirty_diff_hash=None,
        source_lock_hash="2" * 64,
        os_arch="test-os",
        cpu="test-cpu",
        gpu=None,
        python_version="3.11.13",
        dependency_versions={"numpy": "test"},
        seed=7,
        simulator="deterministic-test-sim",
        task_config_hash=sha256_json(CONFIG),
        model_hashes={"policy": "3" * 64},
        action_schema_version=SCHEMA_VERSION,
        observation_schema_version=SCHEMA_VERSION,
        wall_start_ns=1_000,
        wall_end_ns=1_200,
        monotonic_start_ns=100,
        monotonic_end_ns=300,
        status="pass",
        physical_deployment_allowed=False,
    )


def _observation() -> Observation:
    return Observation(
        sequence_id=0,
        source_time_ns=100,
        received_time_ns=110,
        robot_state=RobotState(q=np.array([0.0, 0.1]), dq=np.array([0.0, 0.0])),
        object_beliefs=(),
        current_skill_id="skill-1",
        current_phase="approach",
    )


def _action(chunk_id: str, *, expires_at_ns: int = 250) -> ActionChunk:
    return ActionChunk(
        chunk_id=chunk_id,
        skill_id="skill-1",
        source_observation_id=0,
        source_observation_time_ns=100,
        generated_time_ns=120,
        valid_from_ns=125,
        expires_at_ns=expires_at_ns,
        dt_s=0.01,
        actions=np.array([[0.1, 0.2]]),
        representation="JOINT_POSITION",
        expected_phase="approach",
        metadata={},
    )


def _event(
    event_type: ExecutionEventType,
    monotonic_time_ns: int,
    sequence_id: int,
    payload: dict[str, object],
    *,
    skill_id: str | None = "skill-1",
) -> ExecutionEvent:
    return ExecutionEvent(
        event_type=event_type,
        monotonic_time_ns=monotonic_time_ns,
        wall_time_ns=1_000 + monotonic_time_ns - 100,
        rollout_id="replay-1",
        sequence_id=sequence_id,
        component="replay-test",
        config_hash=sha256_json(CONFIG),
        skill_id=skill_id,
        payload=payload,
    )


def _events() -> tuple[ExecutionEvent, ...]:
    definitions = (
        (ExecutionEventType.OBSERVATION_RECEIVED, 110, 0, {"observation_id": 0}),
        (ExecutionEventType.CHUNK_ACCEPTED, 130, 1, {"chunk_id": "chunk-old"}),
        (ExecutionEventType.CHUNK_ACCEPTED, 135, 2, {"chunk_id": "chunk-active"}),
        (
            ExecutionEventType.ACTION_EXECUTED,
            140,
            3,
            {"source_chunk_id": "chunk-active"},
        ),
        (ExecutionEventType.CHUNK_REPLACED, 150, 4, {"chunk_id": "chunk-old"}),
        (
            ExecutionEventType.CHUNK_REJECTED_EXPIRED,
            160,
            5,
            {"chunk_id": "chunk-expired"},
        ),
        (ExecutionEventType.SKILL_RETRIGGERED, 170, 6, {}),
        (ExecutionEventType.MEMORY_UPDATED, 180, 7, {"mutation_id": "memory-1"}),
        (
            ExecutionEventType.WORLD_MODEL_PREDICTED,
            180,
            7,
            {"candidate_id": "candidate-1"},
        ),
        (
            ExecutionEventType.WORLD_MODEL_SELECTED,
            190,
            8,
            {"candidate_id": "candidate-1"},
        ),
        (ExecutionEventType.SKILL_SUCCEEDED, 200, 9, {}),
    )
    return tuple(_event(*definition) for definition in definitions)  # type: ignore[arg-type]


def _record(*, events: tuple[ExecutionEvent, ...] | None = None) -> RolloutRecord:
    return RolloutRecord(
        metadata=_metadata(),
        config=CONFIG,
        metrics={"success": True},
        events=_events() if events is None else events,
        observations=(_observation(),),
        actions=(
            _action("chunk-old"),
            _action("chunk-active"),
            _action("chunk-expired", expires_at_ns=160),
        ),
        control_references=(
            ControlReference(
                source_chunk_id="chunk-active",
                time_ns=140,
                q_ref=np.array([0.1, 0.2]),
                dq_ref=np.array([0.0, 0.0]),
                eef_ref=None,
                feedforward=np.array([0.01, 0.02]),
                controller_mode="joint_position",
            ),
        ),
        summary="# Replay fixture\n",
    )


def _write_rollout(
    tmp_path: Path, *, events: tuple[ExecutionEvent, ...] | None = None
) -> Path:
    return RolloutWriter(tmp_path, "replay-1").write(_record(events=events))


def test_replay_reconstructs_deterministic_state(tmp_path: Path) -> None:
    result = replay_rollout(_write_rollout(tmp_path))

    frame_keys = [
        (frame.monotonic_time_ns, frame.sequence_id, frame.original_line_index)
        for frame in result.frames
    ]
    assert frame_keys == sorted(frame_keys)
    assert frame_keys[7:9] == [(180, 7, 7), (180, 7, 8)]
    assert result.rollout_id == "replay-1"
    assert result.event_count == 11
    assert result.final_state.accepted_chunk_ids == ("chunk-active",)
    assert result.final_state.rejected_chunk_ids == ("chunk-expired",)
    assert result.final_state.replaced_chunk_ids == ("chunk-old",)
    assert result.final_state.skill_state is SkillState.SUCCEEDED
    assert result.final_state.recovery_decision is RecoveryDecision.RETRIGGER
    assert result.final_state.memory_mutation_count == 1
    assert result.final_state.selected_world_model_candidate_id == "candidate-1"

    reference = result.final_state.executed_control_reference
    assert reference is not None
    assert reference.source_chunk_id == "chunk-active"
    assert reference.time_ns == 140
    assert reference.controller_mode == "joint_position"
    np.testing.assert_array_equal(reference.q_ref, np.array([0.1, 0.2]))
    np.testing.assert_array_equal(reference.dq_ref, np.array([0.0, 0.0]))
    assert reference.eef_ref is None
    np.testing.assert_array_equal(reference.feedforward, np.array([0.01, 0.02]))


def test_replay_preserves_full_events_observations_and_mission_state(
    tmp_path: Path,
) -> None:
    observations = (
        _observation(),
        Observation(
            sequence_id=1,
            source_time_ns=200,
            received_time_ns=210,
            robot_state=RobotState(
                q=np.array([0.4, 0.5]),
                dq=np.array([0.2, 0.3]),
            ),
            object_beliefs=(),
            current_skill_id="skill-2",
            current_phase="execute",
        ),
    )
    events = (
        _event(
            ExecutionEventType.OBSERVATION_RECEIVED,
            110,
            0,
            {"observation_id": 0},
        ),
        _event(
            ExecutionEventType.SEMANTIC_REPLAN,
            120,
            1,
            {
                "mission_state": {
                    "mission_id": "mission-1",
                    "revision": 1,
                    "remaining_skills": ["skill-1", "skill-2"],
                }
            },
        ),
        _event(
            ExecutionEventType.SKILL_RETRIGGERED,
            120,
            1,
            {"reason": "stalled"},
        ),
        _event(
            ExecutionEventType.OBSERVATION_RECEIVED,
            210,
            2,
            {"observation_id": 1},
            skill_id="skill-2",
        ),
        _event(
            ExecutionEventType.SEMANTIC_REPLAN,
            220,
            3,
            {
                "mission_state": {
                    "mission_id": "mission-1",
                    "revision": 2,
                    "remaining_skills": [],
                }
            },
            skill_id="skill-2",
        ),
        _event(
            ExecutionEventType.SKILL_SUCCEEDED,
            230,
            4,
            {"outcome": "complete"},
            skill_id="skill-2",
        ),
    )
    path = RolloutWriter(tmp_path, "replay-1").write(
        RolloutRecord(
            metadata=_metadata(),
            config=CONFIG,
            metrics={"success": True},
            events=events,
            observations=observations,
            actions=(),
            control_references=(),
            summary="# Complete replay fixture\n",
        )
    )

    result = replay_rollout(path)

    assert result.events == tuple(frame.event for frame in result.frames)
    assert [event.event_type for event in result.events] == [
        ExecutionEventType.OBSERVATION_RECEIVED,
        ExecutionEventType.SEMANTIC_REPLAN,
        ExecutionEventType.SKILL_RETRIGGERED,
        ExecutionEventType.OBSERVATION_RECEIVED,
        ExecutionEventType.SEMANTIC_REPLAN,
        ExecutionEventType.SKILL_SUCCEEDED,
    ]
    assert result.events[1].payload["mission_state"]["revision"] == 1
    assert result.events[-1].wall_time_ns == 1_130
    assert result.events[-1].skill_id == "skill-2"
    assert result.events[-1].payload == {"outcome": "complete"}

    assert [observation.sequence_id for observation in result.observations] == [0, 1]
    assert result.frames[0].observation is result.observations[0]
    assert result.frames[3].observation is result.observations[1]
    assert result.frames[1].observation is None
    np.testing.assert_array_equal(
        result.observations[1].robot_state.q,
        np.array([0.4, 0.5]),
    )
    assert result.observations[1].current_skill_id == "skill-2"
    assert result.observations[1].current_phase == "execute"

    assert result.frames[0].state.current_observation is result.observations[0]
    assert result.frames[0].state.current_skill_id == "skill-1"
    assert result.frames[0].state.current_phase == "approach"
    assert result.frames[1].state.mission_state == {
        "mission_id": "mission-1",
        "revision": 1,
        "remaining_skills": ("skill-1", "skill-2"),
    }
    assert result.frames[2].state.recovery_decision is RecoveryDecision.RETRIGGER
    assert result.frames[2].state.current_skill_id == "skill-1"
    assert result.final_state.current_observation is result.observations[1]
    assert result.final_state.current_observation_id == 1
    assert result.final_state.current_skill_id == "skill-2"
    assert result.final_state.current_phase == "execute"
    assert result.final_state.mission_state == {
        "mission_id": "mission-1",
        "revision": 2,
        "remaining_skills": (),
    }
    assert result.final_state.skill_state is SkillState.SUCCEEDED


def test_replay_rejects_semantic_replan_without_explicit_mission_state(
    tmp_path: Path,
) -> None:
    events = (
        _event(
            ExecutionEventType.OBSERVATION_RECEIVED,
            110,
            0,
            {"observation_id": 0},
        ),
        _event(
            ExecutionEventType.SEMANTIC_REPLAN,
            120,
            1,
            {"state": {"mission_id": "ambiguous-legacy-field"}},
        ),
    )
    path = RolloutWriter(tmp_path, "replay-1").write(
        RolloutRecord(
            metadata=_metadata(),
            config=CONFIG,
            metrics={"success": False},
            events=events,
            observations=(_observation(),),
            actions=(),
            control_references=(),
            summary="# Missing mission state\n",
        )
    )

    with pytest.raises(RolloutValidationError, match="SEMANTIC_REPLAN.*mission_state"):
        replay_rollout(path)


def test_replay_rejects_missing_state_payload(tmp_path: Path) -> None:
    events = list(_events())
    events[7] = replace(events[7], payload={})
    path = _write_rollout(tmp_path, events=tuple(events))

    with pytest.raises(RolloutValidationError, match="MEMORY_UPDATED.*mutation_id"):
        replay_rollout(path)


def test_replay_rejects_ambiguous_world_model_candidate(tmp_path: Path) -> None:
    events = list(_events())
    events.insert(9, replace(events[8], monotonic_time_ns=185, wall_time_ns=1_085))
    events = [replace(event, sequence_id=index) for index, event in enumerate(events)]
    path = _write_rollout(tmp_path, events=tuple(events))

    with pytest.raises(RolloutValidationError, match="candidate-1.*ambiguous"):
        replay_rollout(path)


def test_rollout_cli_emits_canonical_summary(tmp_path: Path) -> None:
    path = _write_rollout(tmp_path)

    completed = subprocess.run(
        [sys.executable, "-m", "reflect.rollout", "replay", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert completed.stdout == (
        '{"event_count":11,"final_skill_state":"succeeded",'
        '"frame_count":11,"rollout_id":"replay-1"}\n'
    )
    assert json.loads(completed.stdout)["rollout_id"] == "replay-1"


def test_rollout_cli_reports_corruption_concisely(tmp_path: Path) -> None:
    path = _write_rollout(tmp_path)
    with (path / "events.jsonl").open("ab") as stream:
        stream.write(b"corrupt\n")

    completed = subprocess.run(
        [sys.executable, "-m", "reflect.rollout", "replay", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == "artifact hash mismatch for events.jsonl\n"


def test_makefile_exposes_replay_target() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "replay:" in makefile
    assert 'test -n "$(RUN)"' in makefile
    assert 'python -m reflect.rollout replay "$(RUN)"' in makefile
