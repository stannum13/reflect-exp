from __future__ import annotations

from dataclasses import fields, replace
from enum import Enum
import hashlib
import io
import json
import os
from pathlib import Path
from types import MappingProxyType
import zipfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import reflect.rollout as rollout_module
from reflect.events import ExecutionEvent, ExecutionEventType
from reflect.rollout import (
    SCHEMA_VERSION,
    RolloutMetadata,
    RolloutRecord,
    RolloutValidationError,
    RolloutWriter,
    canonical_json_bytes,
    load_rollout,
    sha256_json,
    validate_rollout,
)
from reflect.safety import SafetyViolation
from reflect.types import ActionChunk, ControlReference, Observation, RobotState


REQUIRED_FILES = {
    "metadata.json",
    "config.json",
    "metrics.json",
    "events.jsonl",
    "observations.npz",
    "actions.parquet",
    "summary.md",
}
PAYLOAD_FILES = REQUIRED_FILES - {"metadata.json"}
CONFIG = {"task": "reach", "gains": {"kp": 2.0}, "targets": [0.1, 0.2]}
METRICS = {"success": True, "cycle_time_s": 0.4}


def valid_metadata(**changes: object) -> RolloutMetadata:
    values: dict[str, object] = {
        "experiment_id": "experiment-01",
        "claim_revision": 2,
        "git_sha": "1" * 40,
        "working_tree_clean": True,
        "dirty_diff_hash": None,
        "source_lock_hash": "2" * 64,
        "os_arch": "linux-x86_64",
        "cpu": "synthetic-cpu",
        "gpu": None,
        "python_version": "3.11.13",
        "dependency_versions": {"numpy": "2.3.2", "pyarrow": "21.0.0"},
        "seed": 7,
        "simulator": "deterministic-test-sim",
        "task_config_hash": sha256_json(CONFIG),
        "model_hashes": {"policy": "3" * 64},
        "action_schema_version": SCHEMA_VERSION,
        "observation_schema_version": SCHEMA_VERSION,
        "wall_start_ns": 10_000,
        "wall_end_ns": 10_190,
        "monotonic_start_ns": 100,
        "monotonic_end_ns": 290,
        "status": "pass",
        "physical_deployment_allowed": False,
    }
    values.update(changes)
    return RolloutMetadata(**values)  # type: ignore[arg-type]


def valid_observations() -> tuple[Observation, ...]:
    return (
        Observation(
            sequence_id=0,
            source_time_ns=100,
            received_time_ns=110,
            robot_state=RobotState(q=np.array([0.1, 0.2]), dq=np.array([0.0, 0.1])),
            object_beliefs=(),
            current_skill_id="reach-1",
            current_phase="approach",
        ),
        Observation(
            sequence_id=1,
            source_time_ns=200,
            received_time_ns=210,
            robot_state=RobotState(q=np.array([0.3, 0.4]), dq=np.array([0.1, 0.2])),
            object_beliefs=(),
            current_skill_id="reach-1",
            current_phase="contact",
        ),
    )


def valid_actions() -> tuple[ActionChunk, ...]:
    return (
        ActionChunk(
            chunk_id="chunk-0",
            skill_id="reach-1",
            source_observation_id=0,
            source_observation_time_ns=100,
            generated_time_ns=120,
            valid_from_ns=130,
            expires_at_ns=190,
            dt_s=0.01,
            actions=np.array([[0.1, 0.2], [0.3, 0.4]]),
            representation="JOINT_POSITION",
            expected_phase="approach",
            metadata={"policy": "baseline", "temperature": np.float64(0.0)},
        ),
        ActionChunk(
            chunk_id="chunk-1",
            skill_id="reach-1",
            source_observation_id=1,
            source_observation_time_ns=200,
            generated_time_ns=220,
            valid_from_ns=230,
            expires_at_ns=290,
            dt_s=0.02,
            actions=np.array([[0.5, 0.6], [0.7, 0.8]]),
            representation="JOINT_DELTA",
            expected_phase="contact",
            metadata={"policy": "baseline", "attempt": 2},
        ),
    )


def valid_control_references() -> tuple[ControlReference, ...]:
    return (
        ControlReference(
            source_chunk_id="chunk-0",
            time_ns=140,
            q_ref=np.array([0.1, 0.2]),
            dq_ref=np.array([0.0, 0.1]),
            eef_ref=None,
            feedforward=np.array([0.01, 0.02]),
            controller_mode="joint_position",
        ),
        ControlReference(
            source_chunk_id="chunk-1",
            time_ns=240,
            q_ref=np.array([0.3, 0.4]),
            dq_ref=None,
            eef_ref=np.array([0.5, 0.6, 0.7]),
            feedforward=None,
            controller_mode="joint_delta",
        ),
    )


def valid_events(rollout_id: str = "rollout-1") -> tuple[ExecutionEvent, ...]:
    config_hash = sha256_json(CONFIG)
    definitions = (
        (ExecutionEventType.OBSERVATION_RECEIVED, 110, 0, {"observation_id": 0}),
        (
            ExecutionEventType.CHUNK_ACCEPTED,
            130,
            1,
            {"chunk_id": "chunk-0", "source_observation_id": 0},
        ),
        (ExecutionEventType.ACTION_EXECUTED, 140, 2, {"source_chunk_id": "chunk-0"}),
        (ExecutionEventType.OBSERVATION_RECEIVED, 210, 3, {"observation_id": 1}),
        (
            ExecutionEventType.CHUNK_ACCEPTED,
            230,
            4,
            {"chunk_id": "chunk-1", "source_observation_id": 1},
        ),
        (ExecutionEventType.ACTION_EXECUTED, 240, 5, {"source_chunk_id": "chunk-1"}),
    )
    return tuple(
        ExecutionEvent(
            event_type=event_type,
            monotonic_time_ns=monotonic_time_ns,
            wall_time_ns=10_000 + (monotonic_time_ns - 100),
            rollout_id=rollout_id,
            sequence_id=sequence_id,
            component="rollout-test",
            config_hash=config_hash,
            skill_id="reach-1",
            payload=payload,
        )
        for event_type, monotonic_time_ns, sequence_id, payload in definitions
    )


def valid_record(rollout_id: str = "rollout-1", **changes: object) -> RolloutRecord:
    values: dict[str, object] = {
        "metadata": valid_metadata(),
        "config": CONFIG,
        "metrics": METRICS,
        "events": valid_events(rollout_id),
        "observations": valid_observations(),
        "actions": valid_actions(),
        "control_references": valid_control_references(),
        "summary": "# Synthetic rollout\n\nDeterministic fixture.\n",
    }
    values.update(changes)
    return RolloutRecord(**values)  # type: ignore[arg-type]


def write_valid_rollout(root: Path, rollout_id: str = "rollout-1") -> Path:
    return RolloutWriter(root, rollout_id).write(valid_record(rollout_id))


def rewrite_metadata(path: Path, mutate: object) -> None:
    metadata_path = path / "metadata.json"
    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    mutate(raw)  # type: ignore[operator]
    metadata_path.write_bytes(canonical_json_bytes(raw))


def refresh_artifact_hash(path: Path, filename: str) -> None:
    digest = hashlib.sha256((path / filename).read_bytes()).hexdigest()
    rewrite_metadata(path, lambda raw: raw["artifact_hashes"].__setitem__(filename, digest))


def rewrite_action_rows(path: Path, mutate: object) -> None:
    parquet_path = path / "actions.parquet"
    table = pq.read_table(parquet_path)
    rows = table.to_pylist()
    mutate(rows)  # type: ignore[operator]
    pq.write_table(
        pa.Table.from_pylist(rows, schema=table.schema),
        parquet_path,
        compression="zstd",
        use_dictionary=False,
        write_statistics=False,
    )
    refresh_artifact_hash(path, "actions.parquet")


def test_writer_creates_exact_canonical_artifact_and_round_trips(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path)

    assert {entry.name for entry in artifact_path.iterdir()} == REQUIRED_FILES
    raw_metadata = json.loads((artifact_path / "metadata.json").read_text(encoding="utf-8"))
    metadata_fields = {field.name for field in fields(RolloutMetadata)}
    assert set(raw_metadata) == metadata_fields | {"schema_version", "artifact_hashes"}
    assert raw_metadata["schema_version"] == SCHEMA_VERSION == 1
    assert set(raw_metadata["artifact_hashes"]) == PAYLOAD_FILES
    for filename, digest in raw_metadata["artifact_hashes"].items():
        assert digest == hashlib.sha256((artifact_path / filename).read_bytes()).hexdigest()

    with np.load(artifact_path / "observations.npz", allow_pickle=False) as observations:
        assert set(observations.files) == {
            "sequence_id",
            "source_time_ns",
            "received_time_ns",
            "robot_q",
            "robot_dq",
            "object_beliefs_json",
            "current_skill_id",
            "current_phase",
        }
        np.testing.assert_array_equal(observations["sequence_id"], [0, 1])
        np.testing.assert_array_equal(observations["source_time_ns"], [100, 200])
        np.testing.assert_array_equal(observations["received_time_ns"], [110, 210])
        np.testing.assert_allclose(observations["robot_q"], [[0.1, 0.2], [0.3, 0.4]])
        np.testing.assert_allclose(observations["robot_dq"], [[0.0, 0.1], [0.1, 0.2]])

    table = pq.read_table(artifact_path / "actions.parquet")
    rows = table.to_pylist()
    action_rows = [row for row in rows if row["record_type"] == "action"]
    assert [row["chunk_id"] for row in action_rows] == ["chunk-0", "chunk-1"]
    assert {key: action_rows[0][key] for key in (
        "source_observation_id",
        "source_observation_time_ns",
        "generated_time_ns",
        "valid_from_ns",
        "expires_at_ns",
        "dt_s",
        "representation",
        "action_shape",
        "action_values",
        "metadata_json",
    )} == {
        "source_observation_id": 0,
        "source_observation_time_ns": 100,
        "generated_time_ns": 120,
        "valid_from_ns": 130,
        "expires_at_ns": 190,
        "dt_s": 0.01,
        "representation": "JOINT_POSITION",
        "action_shape": [2, 2],
        "action_values": [0.1, 0.2, 0.3, 0.4],
        "metadata_json": '{"policy":"baseline","temperature":0.0}',
    }

    artifact = validate_rollout(artifact_path)
    loaded = load_rollout(artifact_path)
    assert artifact.schema_version == loaded.schema_version == SCHEMA_VERSION
    assert artifact.metadata == loaded.metadata == valid_metadata()
    assert [observation.sequence_id for observation in artifact.observations] == [0, 1]
    assert [action.chunk_id for action in artifact.actions] == ["chunk-0", "chunk-1"]
    assert [reference.source_chunk_id for reference in artifact.control_references] == [
        "chunk-0",
        "chunk-1",
    ]
    assert artifact.summary == "# Synthetic rollout\n\nDeterministic fixture.\n"


def test_identical_records_produce_identical_file_bytes(tmp_path: Path) -> None:
    first = RolloutWriter(tmp_path / "first", "rollout-1").write(valid_record())
    second = RolloutWriter(tmp_path / "second", "rollout-1").write(valid_record())

    assert {name: (first / name).read_bytes() for name in REQUIRED_FILES} == {
        name: (second / name).read_bytes() for name in REQUIRED_FILES
    }


def test_canonical_json_normalizes_supported_immutable_and_numpy_values() -> None:
    class WireValue(str, Enum):
        VALUE = "wire"

    value = MappingProxyType(
        {
            "tuple": (np.int64(2), np.array([3.0, 4.0])),
            "enum": WireValue.VALUE,
            "bool": np.bool_(True),
        }
    )

    assert canonical_json_bytes(value) == (
        b'{"bool":true,"enum":"wire","tuple":[2,[3.0,4.0]]}'
    )
    assert sha256_json(value) == hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf, np.array([0.0, np.nan])])
def test_canonical_json_rejects_nonfinite_numbers(value: object) -> None:
    with pytest.raises(RolloutValidationError, match="finite"):
        canonical_json_bytes(value)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"claim_revision": True}, "claim_revision"),
        ({"seed": True}, "seed"),
        ({"source_lock_hash": "not-a-hash"}, "source_lock_hash"),
        ({"dirty_diff_hash": ""}, "dirty_diff_hash"),
        ({"model_hashes": {"policy": "bad"}}, "model_hashes"),
        ({"wall_start_ns": 20, "wall_end_ns": 10}, "wall"),
        ({"monotonic_start_ns": 20, "monotonic_end_ns": 10}, "monotonic"),
        ({"status": "unknown"}, "status"),
        ({"physical_deployment_allowed": True}, "physical deployment"),
    ],
)
def test_metadata_rejects_invalid_or_unsafe_values(
    change: dict[str, object], message: str
) -> None:
    with pytest.raises(RolloutValidationError, match=message):
        valid_metadata(**change)


@pytest.mark.parametrize(
    "change",
    [
        {"working_tree_clean": "yes"},
        {"working_tree_clean": True, "dirty_diff_hash": "4" * 64},
        {"working_tree_clean": False, "dirty_diff_hash": None},
    ],
)
def test_metadata_requires_exactly_one_clean_status_or_dirty_diff_hash(
    change: dict[str, object],
) -> None:
    with pytest.raises(RolloutValidationError, match="working_tree_clean"):
        valid_metadata(**change)


def test_writer_rejects_a_target_outside_output_root(tmp_path: Path) -> None:
    root = tmp_path / "results"

    with pytest.raises(RolloutValidationError, match="output root"):
        RolloutWriter(root, "../escape")

    assert not (tmp_path / "escape").exists()


def test_writer_calls_simulation_guard_before_creating_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "results"
    monkeypatch.setenv("PHYSICAL_DEPLOYMENT_ALLOWED", "true")

    with pytest.raises(SafetyViolation, match="physical deployment"):
        RolloutWriter(root, "rollout-1").write(valid_record())

    assert not root.exists()


def test_writer_revalidates_mutated_metadata_before_creating_output(tmp_path: Path) -> None:
    root = tmp_path / "results"
    metadata = valid_metadata()
    object.__setattr__(metadata, "physical_deployment_allowed", True)

    with pytest.raises(RolloutValidationError, match="physical deployment"):
        RolloutWriter(root, "rollout-1").write(valid_record(metadata=metadata))

    assert not root.exists()


def test_writer_revalidates_mutated_events_before_creating_output(tmp_path: Path) -> None:
    root = tmp_path / "results"
    events = valid_events()
    object.__setattr__(events[0], "component", "")

    with pytest.raises(RolloutValidationError, match="invalid event"):
        RolloutWriter(root, "rollout-1").write(valid_record(events=events))

    assert not root.exists()


def test_writer_revalidates_mutated_record_mappings_before_output(tmp_path: Path) -> None:
    root = tmp_path / "results"
    record = valid_record()
    object.__setattr__(record, "metrics", [])

    with pytest.raises(RolloutValidationError, match="metrics"):
        RolloutWriter(root, "rollout-1").write(record)

    assert not root.exists()


def test_writer_preserves_a_chunk_rejected_after_expiry(tmp_path: Path) -> None:
    actions = valid_actions()
    actions = (actions[0], replace(actions[1], generated_time_ns=300))
    events = valid_events()
    events = (
        *events[:-2],
        replace(
            events[-2],
            event_type=ExecutionEventType.CHUNK_REJECTED_EXPIRED,
            monotonic_time_ns=300,
            wall_time_ns=10_200,
        ),
    )

    artifact_path = RolloutWriter(tmp_path, "rollout-1").write(
        valid_record(
            actions=actions,
            events=events,
            control_references=valid_control_references()[:1],
            metadata=valid_metadata(
                monotonic_end_ns=300,
                wall_end_ns=10_200,
            ),
        )
    )

    assert validate_rollout(artifact_path).actions[1].generated_time_ns == 300


def test_writer_rejects_chunk_acceptance_after_expiry(tmp_path: Path) -> None:
    events = list(valid_events())
    events[4] = replace(events[4], monotonic_time_ns=291, wall_time_ns=10_191)
    events[5] = replace(events[5], monotonic_time_ns=292, wall_time_ns=10_192)

    with pytest.raises(RolloutValidationError, match="expired"):
        RolloutWriter(tmp_path, "rollout-1").write(
            valid_record(
                events=tuple(events),
                metadata=valid_metadata(
                    monotonic_end_ns=292,
                    wall_end_ns=10_192,
                ),
            )
        )


def test_writer_rejects_expired_rejection_before_expiry(tmp_path: Path) -> None:
    events = list(valid_events())
    events[4] = replace(
        events[4], event_type=ExecutionEventType.CHUNK_REJECTED_EXPIRED
    )
    events.pop()

    with pytest.raises(RolloutValidationError, match="at or after expiry"):
        RolloutWriter(tmp_path, "rollout-1").write(
            valid_record(
                events=tuple(events),
                control_references=valid_control_references()[:1],
            )
        )


def test_writer_rejects_action_execution_outside_chunk_validity(tmp_path: Path) -> None:
    events = list(valid_events())
    events[5] = replace(events[5], monotonic_time_ns=291, wall_time_ns=10_191)

    with pytest.raises(RolloutValidationError, match="validity interval"):
        RolloutWriter(tmp_path, "rollout-1").write(
            valid_record(
                events=tuple(events),
                metadata=valid_metadata(
                    monotonic_end_ns=291,
                    wall_end_ns=10_191,
                ),
            )
        )


def test_writer_rejects_duplicate_observation_received_events(tmp_path: Path) -> None:
    events = list(valid_events())
    events.insert(1, replace(events[0], sequence_id=1))
    events = [replace(event, sequence_id=index) for index, event in enumerate(events)]

    with pytest.raises(RolloutValidationError, match="exactly one OBSERVATION_RECEIVED"):
        RolloutWriter(tmp_path, "rollout-1").write(valid_record(events=tuple(events)))


@pytest.mark.parametrize(
    "changed_event",
    [
        replace(valid_events()[1], skill_id="other-skill"),
        replace(
            valid_events()[1],
            payload={"chunk_id": "chunk-0", "source_observation_id": 1},
        ),
    ],
)
def test_writer_rejects_chunk_event_skill_or_observation_mismatch(
    tmp_path: Path, changed_event: ExecutionEvent
) -> None:
    events = list(valid_events())
    events[1] = changed_event

    with pytest.raises(RolloutValidationError, match="does not match"):
        RolloutWriter(tmp_path, "rollout-1").write(valid_record(events=tuple(events)))


def test_writer_rejects_contradictory_chunk_lifecycle(tmp_path: Path) -> None:
    events = list(valid_events())
    events.insert(
        2,
        replace(
            events[1],
            event_type=ExecutionEventType.CHUNK_REJECTED_OUT_OF_ORDER,
            sequence_id=2,
        ),
    )
    events = [replace(event, sequence_id=index) for index, event in enumerate(events)]

    with pytest.raises(RolloutValidationError, match="lifecycle"):
        RolloutWriter(tmp_path, "rollout-1").write(valid_record(events=tuple(events)))


def test_writer_accepts_one_coherent_chunk_replacement_transition(
    tmp_path: Path,
) -> None:
    events = list(valid_events())
    events.insert(
        3,
        replace(
            events[1],
            event_type=ExecutionEventType.CHUNK_REPLACED,
            monotonic_time_ns=150,
            wall_time_ns=10_050,
            sequence_id=3,
        ),
    )
    events = [replace(event, sequence_id=index) for index, event in enumerate(events)]

    artifact_path = RolloutWriter(tmp_path, "rollout-1").write(
        valid_record(events=tuple(events))
    )

    assert validate_rollout(artifact_path).events[3].event_type is (
        ExecutionEventType.CHUNK_REPLACED
    )


def test_writer_rejects_replacing_an_expired_chunk(tmp_path: Path) -> None:
    events = list(valid_events())
    events.insert(
        3,
        replace(
            events[1],
            event_type=ExecutionEventType.CHUNK_REPLACED,
            monotonic_time_ns=191,
            wall_time_ns=10_091,
            sequence_id=3,
        ),
    )
    events = [replace(event, sequence_id=index) for index, event in enumerate(events)]

    with pytest.raises(RolloutValidationError, match="expired"):
        RolloutWriter(tmp_path, "rollout-1").write(valid_record(events=tuple(events)))


def test_writer_rejects_action_execution_without_matching_control_reference(
    tmp_path: Path,
) -> None:
    references = (
        replace(valid_control_references()[0], time_ns=141),
        valid_control_references()[1],
    )

    with pytest.raises(RolloutValidationError, match="ControlReference"):
        RolloutWriter(tmp_path, "rollout-1").write(
            valid_record(control_references=references)
        )


def test_writer_rejects_action_execution_with_mismatched_reference_time_payload(
    tmp_path: Path,
) -> None:
    events = list(valid_events())
    events[2] = replace(
        events[2], payload={"source_chunk_id": "chunk-0", "time_ns": 141}
    )

    with pytest.raises(RolloutValidationError, match="ControlReference"):
        RolloutWriter(tmp_path, "rollout-1").write(valid_record(events=tuple(events)))


def test_writer_rejects_duplicate_execution_of_one_control_reference(
    tmp_path: Path,
) -> None:
    events = list(valid_events())
    events.insert(3, replace(events[2], sequence_id=3))
    events = [replace(event, sequence_id=index) for index, event in enumerate(events)]

    with pytest.raises(RolloutValidationError, match="executed more than once"):
        RolloutWriter(tmp_path, "rollout-1").write(valid_record(events=tuple(events)))


def test_writer_refuses_to_overwrite_existing_rollout(tmp_path: Path) -> None:
    writer = RolloutWriter(tmp_path, "rollout-1")
    writer.write(valid_record())

    with pytest.raises(RolloutValidationError, match="already exists"):
        writer.write(valid_record())


def test_writer_atomic_publication_does_not_replace_a_racing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = RolloutWriter(tmp_path, "rollout-1")
    writer.path.mkdir()
    original_exists = Path.exists

    def hide_final_path(path: Path) -> bool:
        if path == writer.path:
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", hide_final_path)

    with pytest.raises(RolloutValidationError, match="already exists"):
        writer.write(valid_record())


def test_writer_failure_cleanup_preserves_replacement_temp_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[Path] = []
    real_mkdtemp = rollout_module.tempfile.mkdtemp

    def tracked_mkdtemp(*args: object, **kwargs: object) -> str:
        path = real_mkdtemp(*args, **kwargs)  # type: ignore[arg-type]
        created.append(Path(path))
        return path

    def replace_temp_then_fail(observations: tuple[Observation, ...]) -> bytes:
        del observations
        temporary = created[0]
        original = temporary.with_name(f"{temporary.name}.original")
        temporary.rename(original)
        temporary.mkdir()
        (temporary / "sentinel.txt").write_text("replacement\n", encoding="utf-8")
        raise RuntimeError("injected artifact encoding failure")

    monkeypatch.setattr(rollout_module.tempfile, "mkdtemp", tracked_mkdtemp)
    monkeypatch.setattr(
        rollout_module, "_observations_npz_bytes", replace_temp_then_fail
    )

    with pytest.raises(RuntimeError, match="injected"):
        RolloutWriter(tmp_path, "rollout-1").write(valid_record())

    assert (created[0] / "sentinel.txt").read_text(encoding="utf-8") == "replacement\n"
    assert not created[0].with_name(f"{created[0].name}.original").exists()


def test_writer_detects_output_root_replacement_and_cleans_original_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "results"
    displaced_root = tmp_path / "displaced-results"
    real_encoder = rollout_module._observations_npz_bytes

    def replace_root(observations: tuple[Observation, ...]) -> bytes:
        root.rename(displaced_root)
        root.mkdir()
        (root / "sentinel.txt").write_text("replacement root\n", encoding="utf-8")
        return real_encoder(observations)

    monkeypatch.setattr(rollout_module, "_observations_npz_bytes", replace_root)

    with pytest.raises(RolloutValidationError, match="output root identity"):
        RolloutWriter(root, "rollout-1").write(valid_record())

    assert (root / "sentinel.txt").read_text(encoding="utf-8") == "replacement root\n"
    assert not any(entry.name.startswith(".rollout-1.") for entry in displaced_root.iterdir())


def test_writer_verifies_published_directory_is_created_temp_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def publish_impostor(*args: object) -> None:
        if len(args) == 2:
            destination = Path(args[1])
            destination.mkdir()
            (destination / "sentinel.txt").write_text("impostor\n", encoding="utf-8")
            return
        root_fd, _source_name, destination_name = args
        os.mkdir(destination_name, dir_fd=root_fd)  # type: ignore[arg-type]
        destination_fd = os.open(  # type: ignore[arg-type]
            destination_name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=root_fd
        )
        try:
            file_fd = os.open(
                "sentinel.txt",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=destination_fd,
            )
            try:
                os.write(file_fd, b"impostor\n")
            finally:
                os.close(file_fd)
        finally:
            os.close(destination_fd)

    monkeypatch.setattr(rollout_module, "_publish_directory", publish_impostor)

    with pytest.raises(RolloutValidationError, match="published directory identity"):
        RolloutWriter(tmp_path, "rollout-1").write(valid_record())

    assert (tmp_path / "rollout-1" / "sentinel.txt").read_text(encoding="utf-8") == (
        "impostor\n"
    )


def test_validate_rejects_a_missing_required_file(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path)
    (artifact_path / "actions.parquet").unlink()

    with pytest.raises(RolloutValidationError, match="missing required"):
        validate_rollout(artifact_path)


def test_validate_rejects_an_unknown_schema_version(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path)
    rewrite_metadata(artifact_path, lambda raw: raw.__setitem__("schema_version", 99))

    with pytest.raises(RolloutValidationError, match="schema version"):
        validate_rollout(artifact_path)


def test_validate_rejects_an_artifact_hash_mismatch(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path)
    (artifact_path / "summary.md").write_text("corrupted\n", encoding="utf-8")

    with pytest.raises(RolloutValidationError, match="hash mismatch"):
        validate_rollout(artifact_path)


def test_validate_parses_the_exact_payload_snapshot_that_was_hashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_path = write_valid_rollout(tmp_path)
    event_path = artifact_path / "events.jsonl"
    original = event_path.read_bytes()
    replacement_events = [
        replace(event, component="replacement-component") for event in valid_events()
    ]
    replacement_path = tmp_path / ".replacement-events"
    replacement_path.write_bytes(
        b"".join(
            canonical_json_bytes(rollout_module.event_to_dict(event)) + b"\n"
            for event in replacement_events
        )
    )
    real_sha256 = hashlib.sha256
    replaced = False

    def replace_after_hash(data: object = b"", *args: object, **kwargs: object) -> object:
        nonlocal replaced
        digest = real_sha256(data, *args, **kwargs)  # type: ignore[arg-type]
        if not replaced and bytes(data) == original:  # type: ignore[arg-type]
            replaced = True
            os.replace(replacement_path, event_path)
        return digest

    monkeypatch.setattr(hashlib, "sha256", replace_after_hash)

    try:
        artifact = validate_rollout(artifact_path)
    except RolloutValidationError:
        return
    assert {event.component for event in artifact.events} == {"rollout-test"}


def test_validate_rejects_duplicate_raw_npz_members(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path)
    observations_path = artifact_path / "observations.npz"
    original = observations_path.read_bytes()
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original), "r") as source:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as target:
            for info in source.infolist():
                target.writestr(info, source.read(info))
            with pytest.warns(UserWarning, match="Duplicate name"):
                target.writestr("sequence_id.npy", source.read("sequence_id.npy"))
    observations_path.write_bytes(output.getvalue())
    refresh_artifact_hash(artifact_path, "observations.npz")

    with pytest.raises(RolloutValidationError, match="duplicate.*NPZ|NPZ.*duplicate"):
        validate_rollout(artifact_path)


def test_validate_rejects_event_order_regression(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path)
    event_path = artifact_path / "events.jsonl"
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    events[1]["monotonic_time_ns"] = 999
    event_path.write_bytes(b"".join(canonical_json_bytes(event) + b"\n" for event in events))
    refresh_artifact_hash(artifact_path, "events.jsonl")

    with pytest.raises(RolloutValidationError, match="event monotonic"):
        validate_rollout(artifact_path)


def test_validate_rejects_action_with_unknown_observation(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path)

    def change(rows: list[dict[str, object]]) -> None:
        next(row for row in rows if row["record_type"] == "action")[
            "source_observation_id"
        ] = 999

    rewrite_action_rows(artifact_path, change)

    with pytest.raises(RolloutValidationError, match="source observation"):
        validate_rollout(artifact_path)


def test_validate_rejects_event_with_unknown_action_id(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path)
    event_path = artifact_path / "events.jsonl"
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    events[1]["payload"]["chunk_id"] = "unknown-chunk"
    event_path.write_bytes(b"".join(canonical_json_bytes(event) + b"\n" for event in events))
    refresh_artifact_hash(artifact_path, "events.jsonl")

    with pytest.raises(RolloutValidationError, match="chunk_id"):
        validate_rollout(artifact_path)


def test_validate_rejects_an_orphan_stored_action(tmp_path: Path) -> None:
    record = valid_record(events=valid_events()[:-2])

    with pytest.raises(RolloutValidationError, match="action event references"):
        RolloutWriter(tmp_path, "rollout-1").write(record)


def test_validate_rejects_nonfinite_stored_actions(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path)

    def change(rows: list[dict[str, object]]) -> None:
        next(row for row in rows if row["record_type"] == "action")["action_values"][0] = np.nan  # type: ignore[index]

    rewrite_action_rows(artifact_path, change)

    with pytest.raises(RolloutValidationError, match="finite"):
        validate_rollout(artifact_path)


def test_validate_rejects_action_fields_on_control_reference_rows(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path)

    def change(rows: list[dict[str, object]]) -> None:
        next(row for row in rows if row["record_type"] == "control_reference")[
            "expected_phase"
        ] = "must-not-be-here"

    rewrite_action_rows(artifact_path, change)

    with pytest.raises(RolloutValidationError, match="contains action fields"):
        validate_rollout(artifact_path)


def test_validate_rejects_unsafe_physical_flag(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path)
    rewrite_metadata(
        artifact_path,
        lambda raw: raw.__setitem__("physical_deployment_allowed", True),
    )

    with pytest.raises(RolloutValidationError, match="physical deployment"):
        validate_rollout(artifact_path)


def test_validate_rejects_unlisted_or_unknown_extra_files(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path)
    (artifact_path / "candidates.parquet").write_bytes(b"candidate-data")

    with pytest.raises(RolloutValidationError, match="listed and hashed"):
        validate_rollout(artifact_path)

    (artifact_path / "candidates.parquet").unlink()
    (artifact_path / "unexpected.bin").write_bytes(b"unexpected")
    with pytest.raises(RolloutValidationError, match="unexpected file"):
        validate_rollout(artifact_path)


def test_validate_rejects_symlinked_artifact_payloads(tmp_path: Path) -> None:
    artifact_path = write_valid_rollout(tmp_path / "results")
    outside = tmp_path / "outside-summary.md"
    outside.write_text("outside\n", encoding="utf-8")
    (artifact_path / "summary.md").unlink()
    (artifact_path / "summary.md").symlink_to(outside)
    refresh_artifact_hash(artifact_path, "summary.md")

    with pytest.raises(RolloutValidationError, match="regular files"):
        validate_rollout(artifact_path)


def test_record_snapshots_mutable_input_mappings() -> None:
    config = {"nested": {"value": 1}}
    record = valid_record(config=config, metadata=valid_metadata(task_config_hash=sha256_json(config)))
    config["nested"]["value"] = 99

    assert record.config["nested"]["value"] == 1  # type: ignore[index]
    with pytest.raises(TypeError):
        record.config["nested"]["value"] = 2  # type: ignore[index]


def test_writer_rejects_record_rollout_id_mismatch(tmp_path: Path) -> None:
    events = tuple(replace(event, rollout_id="different-rollout") for event in valid_events())

    with pytest.raises(RolloutValidationError, match="rollout_id"):
        RolloutWriter(tmp_path, "rollout-1").write(valid_record(events=events))

    assert not tmp_path.joinpath("rollout-1").exists()
