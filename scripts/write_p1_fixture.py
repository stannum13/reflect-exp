"""Write the deterministic, synthetic P1 rollout fixture."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

import numpy as np

from reflect.clock import VirtualClock
from reflect.events import ExecutionEvent, ExecutionEventType
from reflect.rollout import (
    SCHEMA_VERSION,
    RolloutMetadata,
    RolloutRecord,
    RolloutWriter,
)
from reflect.safety import SafetyConfig
from reflect.types import ActionChunk, ControlReference, Observation, RobotState


ROLLOUT_ID = "p1-fixture"
CONFIG = {"fixture": "p1", "task": "deterministic-rollout", "version": 1}
CONFIG_HASH = "0978bd7772089464e74be70a78c93e434216650e1737193d688485634df3224c"
SOURCE_LOCK_HASH = "1" * 64
MODEL_HASH = "2" * 64
GIT_SHA = "0" * 40
SEED = 17
MONOTONIC_START_NS = 1_000_000
WALL_START_NS = 2_000_000
ROLLOUT_DURATION_NS = 100
SKILL_ID = "p1-synthetic-skill"
CHUNK_ID = "p1-action-chunk"


def _event(
    clock: VirtualClock,
    event_type: ExecutionEventType,
    sequence_id: int,
    payload: dict[str, object],
) -> ExecutionEvent:
    return ExecutionEvent(
        event_type=event_type,
        monotonic_time_ns=clock.monotonic_ns(),
        wall_time_ns=clock.wall_time_ns(),
        rollout_id=ROLLOUT_ID,
        sequence_id=sequence_id,
        component="p1-fixture",
        config_hash=CONFIG_HASH,
        object_ids=(),
        skill_id=SKILL_ID,
        payload=payload,
    )


def fixture_record() -> RolloutRecord:
    """Construct the complete fixture from explicit synthetic constants."""
    clock = VirtualClock(
        start_ns=MONOTONIC_START_NS,
        wall_start_ns=WALL_START_NS,
    )
    observation_source_ns = clock.monotonic_ns()
    clock.advance_ns(10)
    observation = Observation(
        sequence_id=0,
        source_time_ns=observation_source_ns,
        received_time_ns=clock.monotonic_ns(),
        robot_state=RobotState(
            q=np.array([0.0, 0.25], dtype=np.float64),
            dq=np.array([0.0, 0.0], dtype=np.float64),
        ),
        object_beliefs=(),
        current_skill_id=SKILL_ID,
        current_phase="execute",
    )
    events = [
        _event(
            clock,
            ExecutionEventType.OBSERVATION_RECEIVED,
            0,
            {"observation_id": 0},
        )
    ]

    clock.advance_ns(10)
    events.append(_event(clock, ExecutionEventType.POLICY_REQUESTED, 1, {}))
    generated_time_ns = clock.monotonic_ns()
    clock.advance_ns(5)
    events.append(_event(clock, ExecutionEventType.POLICY_RESPONDED, 2, {}))

    valid_from_ns = clock.advance_ns(5)
    action = ActionChunk(
        chunk_id=CHUNK_ID,
        skill_id=SKILL_ID,
        source_observation_id=observation.sequence_id,
        source_observation_time_ns=observation.source_time_ns,
        generated_time_ns=generated_time_ns,
        valid_from_ns=valid_from_ns,
        expires_at_ns=MONOTONIC_START_NS + ROLLOUT_DURATION_NS,
        dt_s=0.01,
        actions=np.array([[0.1, 0.2], [0.2, 0.3]], dtype=np.float64),
        representation="JOINT_POSITION",
        expected_phase="execute",
        metadata={"generator": "p1-fixture", "seed": SEED},
    )
    events.append(
        _event(
            clock,
            ExecutionEventType.CHUNK_ACCEPTED,
            3,
            {"chunk_id": CHUNK_ID, "source_observation_id": 0},
        )
    )

    executed_time_ns = clock.advance_ns(10)
    control_reference = ControlReference(
        source_chunk_id=CHUNK_ID,
        time_ns=executed_time_ns,
        q_ref=np.array([0.1, 0.2], dtype=np.float64),
        dq_ref=np.array([0.0, 0.0], dtype=np.float64),
        eef_ref=None,
        feedforward=np.array([0.01, 0.02], dtype=np.float64),
        controller_mode="joint_position",
    )
    events.append(
        _event(
            clock,
            ExecutionEventType.ACTION_EXECUTED,
            4,
            {"source_chunk_id": CHUNK_ID, "time_ns": executed_time_ns},
        )
    )
    clock.advance_ns(10)
    events.append(_event(clock, ExecutionEventType.SKILL_SUCCEEDED, 5, {}))

    return RolloutRecord(
        metadata=RolloutMetadata(
            experiment_id="bootstrap",
            claim_revision=1,
            git_sha=GIT_SHA,
            working_tree_clean=True,
            dirty_diff_hash=None,
            source_lock_hash=SOURCE_LOCK_HASH,
            os_arch="synthetic-platform",
            cpu="synthetic-cpu",
            gpu=None,
            python_version="3.11.13",
            dependency_versions={"numpy": "2.3", "pyarrow": "21"},
            seed=SEED,
            simulator="none-synthetic-fixture",
            task_config_hash=CONFIG_HASH,
            model_hashes={"fixture-policy": MODEL_HASH},
            action_schema_version=SCHEMA_VERSION,
            observation_schema_version=SCHEMA_VERSION,
            wall_start_ns=WALL_START_NS,
            wall_end_ns=WALL_START_NS + ROLLOUT_DURATION_NS,
            monotonic_start_ns=MONOTONIC_START_NS,
            monotonic_end_ns=MONOTONIC_START_NS + ROLLOUT_DURATION_NS,
            status="pass",
            physical_deployment_allowed=False,
        ),
        config=CONFIG,
        metrics={
            "eventual_success": True,
            "first_attempt_success": True,
            "safety_rejection_count": 0,
        },
        events=tuple(events),
        observations=(observation,),
        actions=(action,),
        control_references=(control_reference,),
        summary=(
            "# P1 deterministic fixture\n\n"
            "Synthetic contract, artifact, and event-replay evidence only.\n"
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("results/bootstrap"))
    arguments = parser.parse_args(argv)
    SafetyConfig.from_mapping(os.environ).require_simulation_only()
    artifact_path = RolloutWriter(arguments.output_dir, ROLLOUT_ID).write(
        fixture_record()
    )
    print(artifact_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
