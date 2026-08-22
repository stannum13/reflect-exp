"""Canonical, bounded rollout artifact writing and validation."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import ctypes
from dataclasses import dataclass, fields
from enum import Enum
import errno
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
from types import MappingProxyType
from typing import Any, BinaryIO
import zipfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from reflect._rollout_io import (
    ArtifactIOError,
    ArtifactSnapshot,
    cleanup_exact_directory,
    create_temporary_directory,
    entry_identity,
    fsync_directory,
    open_directory,
    path_matches_directory,
    read_artifact_snapshot,
    verify_regular_entries,
    write_bytes as write_descriptor_bytes,
    write_file as write_descriptor_file,
)
from reflect.events import (
    EventValidationError,
    ExecutionEvent,
    ExecutionEventType,
    event_from_dict,
    event_to_dict,
)
from reflect.safety import SafetyConfig
from reflect.types import (
    ActionChunk,
    ContractValidationError,
    ControlReference,
    ObjectBelief,
    Observation,
    RobotState,
    validate_contract,
)


SCHEMA_VERSION = 1

_REQUIRED_FILES = frozenset(
    {
        "metadata.json",
        "config.json",
        "metrics.json",
        "events.jsonl",
        "observations.npz",
        "actions.parquet",
        "summary.md",
    }
)
_OPTIONAL_FILES = frozenset(
    {"candidates.parquet", "memory_snapshots.jsonl", "video.mp4"}
)
_PAYLOAD_FILES = _REQUIRED_FILES - {"metadata.json"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
_STATUSES = frozenset({"pass", "fail", "blocked", "interrupted"})
_OBSERVATION_ARRAYS = (
    "sequence_id",
    "source_time_ns",
    "received_time_ns",
    "robot_q",
    "robot_dq",
    "object_beliefs_json",
    "current_skill_id",
    "current_phase",
)


class RolloutValidationError(ValueError):
    """Raised when a rollout cannot cross the canonical artifact boundary."""


def _non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RolloutValidationError(f"{name} must be a non-empty string")
    return value


def _non_negative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise RolloutValidationError(f"{name} must be a non-negative integer")
    return value


def _schema_version(value: object, name: str) -> int:
    version = _non_negative_int(value, name)
    if version != SCHEMA_VERSION:
        raise RolloutValidationError(
            f"{name} schema version {version} is unsupported; expected {SCHEMA_VERSION}"
        )
    return version


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise RolloutValidationError(f"{name} must be a lowercase SHA-256 string")
    return value


def _normalize_json(value: object, location: str = "value") -> Any:
    if isinstance(value, Enum):
        return _normalize_json(value.value, location)
    if isinstance(value, np.ndarray):
        if value.dtype.kind in {"f", "c"} and not np.isfinite(value).all():
            raise RolloutValidationError(f"{location} must contain only finite numbers")
        return _normalize_json(value.tolist(), location)
    if isinstance(value, np.generic):
        return _normalize_json(value.item(), location)
    if value is None or isinstance(value, (bool, str)):
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise RolloutValidationError(f"{location} must contain only finite numbers")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RolloutValidationError(f"{location} keys must be strings")
            normalized[key] = _normalize_json(item, f"{location}.{key}")
        return normalized
    if isinstance(value, (tuple, list)):
        return [
            _normalize_json(item, f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
    raise RolloutValidationError(
        f"{location} contains unsupported value type {type(value).__name__}"
    )


def canonical_json_bytes(value: object) -> bytes:
    """Return the compact canonical JSON encoding used by rollout artifacts."""
    normalized = _normalize_json(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: object) -> str:
    """Hash a value after canonical JSON normalization."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _freeze_json(value: object, location: str) -> Any:
    normalized = _normalize_json(value, location)

    def freeze(item: Any) -> Any:
        if isinstance(item, dict):
            return MappingProxyType({key: freeze(child) for key, child in item.items()})
        if isinstance(item, list):
            return tuple(freeze(child) for child in item)
        return item

    return freeze(normalized)


def _freeze_string_mapping(value: object, name: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise RolloutValidationError(f"{name} must be a mapping")
    copied: dict[str, str] = {}
    for key, item in value.items():
        copied[_non_empty_string(key, f"{name} key")] = _non_empty_string(
            item, f"{name}[{key}]"
        )
    return MappingProxyType(copied)


def _freeze_hash_mapping(value: object, name: str) -> Mapping[str, str]:
    frozen = _freeze_string_mapping(value, name)
    return MappingProxyType(
        {key: _sha256(item, f"{name}[{key}]") for key, item in frozen.items()}
    )


@dataclass(frozen=True)
class RolloutMetadata:
    experiment_id: str
    claim_revision: int
    git_sha: str
    working_tree_clean: bool
    dirty_diff_hash: str | None
    source_lock_hash: str
    os_arch: str
    cpu: str
    gpu: str | None
    python_version: str
    dependency_versions: Mapping[str, str]
    seed: int
    simulator: str
    task_config_hash: str
    model_hashes: Mapping[str, str]
    action_schema_version: int
    observation_schema_version: int
    wall_start_ns: int
    wall_end_ns: int
    monotonic_start_ns: int
    monotonic_end_ns: int
    status: str
    physical_deployment_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "experiment_id", _non_empty_string(self.experiment_id, "experiment_id")
        )
        object.__setattr__(
            self, "claim_revision", _non_negative_int(self.claim_revision, "claim_revision")
        )
        if not isinstance(self.git_sha, str) or _GIT_SHA_RE.fullmatch(self.git_sha) is None:
            raise RolloutValidationError("git_sha must be a 40- or 64-digit hexadecimal Git SHA")
        object.__setattr__(self, "git_sha", self.git_sha.lower())
        if type(self.working_tree_clean) is not bool:
            raise RolloutValidationError("working_tree_clean must be a boolean")
        if self.dirty_diff_hash is not None:
            object.__setattr__(
                self,
                "dirty_diff_hash",
                _sha256(self.dirty_diff_hash, "dirty_diff_hash"),
            )
        if self.working_tree_clean != (self.dirty_diff_hash is None):
            raise RolloutValidationError(
                "working_tree_clean requires no dirty_diff_hash when true and a "
                "valid dirty_diff_hash when false"
            )
        object.__setattr__(
            self, "source_lock_hash", _sha256(self.source_lock_hash, "source_lock_hash")
        )
        for name in ("os_arch", "cpu", "python_version", "simulator"):
            object.__setattr__(self, name, _non_empty_string(getattr(self, name), name))
        if self.gpu is not None:
            object.__setattr__(self, "gpu", _non_empty_string(self.gpu, "gpu"))
        object.__setattr__(
            self,
            "dependency_versions",
            _freeze_string_mapping(self.dependency_versions, "dependency_versions"),
        )
        object.__setattr__(self, "seed", _non_negative_int(self.seed, "seed"))
        object.__setattr__(
            self, "task_config_hash", _sha256(self.task_config_hash, "task_config_hash")
        )
        object.__setattr__(
            self, "model_hashes", _freeze_hash_mapping(self.model_hashes, "model_hashes")
        )
        object.__setattr__(
            self,
            "action_schema_version",
            _schema_version(self.action_schema_version, "action_schema_version"),
        )
        object.__setattr__(
            self,
            "observation_schema_version",
            _schema_version(self.observation_schema_version, "observation_schema_version"),
        )
        for name in (
            "wall_start_ns",
            "wall_end_ns",
            "monotonic_start_ns",
            "monotonic_end_ns",
        ):
            object.__setattr__(self, name, _non_negative_int(getattr(self, name), name))
        if self.wall_end_ns < self.wall_start_ns:
            raise RolloutValidationError("wall time must not regress")
        if self.monotonic_end_ns < self.monotonic_start_ns:
            raise RolloutValidationError("monotonic time must not regress")
        if self.status not in _STATUSES:
            raise RolloutValidationError(
                f"status must be one of {sorted(_STATUSES)}"
            )
        if type(self.physical_deployment_allowed) is not bool:
            raise RolloutValidationError("physical_deployment_allowed must be a boolean")
        if self.physical_deployment_allowed:
            raise RolloutValidationError("physical deployment must remain disabled")


def _tuple_input(value: object, name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)):
        raise RolloutValidationError(f"{name} must be an iterable")
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise RolloutValidationError(f"{name} must be an iterable") from exc


@dataclass(frozen=True)
class RolloutRecord:
    metadata: RolloutMetadata
    config: Mapping[str, Any]
    metrics: Mapping[str, Any]
    events: tuple[ExecutionEvent, ...]
    observations: tuple[Observation, ...]
    actions: tuple[ActionChunk, ...]
    control_references: tuple[ControlReference, ...] = ()
    summary: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, RolloutMetadata):
            raise RolloutValidationError("metadata must be RolloutMetadata")
        config = _freeze_json(self.config, "config")
        metrics = _freeze_json(self.metrics, "metrics")
        if not isinstance(config, Mapping) or not isinstance(metrics, Mapping):
            raise RolloutValidationError("config and metrics must be mappings")
        object.__setattr__(self, "config", config)
        object.__setattr__(self, "metrics", metrics)
        events = _tuple_input(self.events, "events")
        if not all(isinstance(event, ExecutionEvent) for event in events):
            raise RolloutValidationError("events must contain only ExecutionEvent values")
        object.__setattr__(self, "events", events)
        for name, contract_type in (
            ("observations", Observation),
            ("actions", ActionChunk),
            ("control_references", ControlReference),
        ):
            values = _tuple_input(getattr(self, name), name)
            if not all(isinstance(item, contract_type) for item in values):
                raise RolloutValidationError(
                    f"{name} must contain only {contract_type.__name__} values"
                )
            object.__setattr__(self, name, values)
        if not isinstance(self.summary, str):
            raise RolloutValidationError("summary must be a string")


@dataclass(frozen=True)
class RolloutArtifact:
    path: Path
    schema_version: int
    metadata: RolloutMetadata
    artifact_hashes: Mapping[str, str]
    config: Mapping[str, Any]
    metrics: Mapping[str, Any]
    events: tuple[ExecutionEvent, ...]
    observations: tuple[Observation, ...]
    actions: tuple[ActionChunk, ...]
    control_references: tuple[ControlReference, ...]
    summary: str
    optional_files: tuple[str, ...] = ()


def _metadata_dict(
    metadata: RolloutMetadata, artifact_hashes: Mapping[str, str]
) -> dict[str, Any]:
    result = {field.name: getattr(metadata, field.name) for field in fields(metadata)}
    result["schema_version"] = SCHEMA_VERSION
    result["artifact_hashes"] = artifact_hashes
    return result


def _object_belief_dict(value: ObjectBelief) -> dict[str, Any]:
    return {
        "entity_id": value.entity_id,
        "label": value.label,
        "pose": value.pose,
        "pose_confidence": value.pose_confidence,
        "state": value.state,
        "state_confidence": value.state_confidence,
        "last_seen_ns": value.last_seen_ns,
        "provenance": value.provenance,
    }


def _npy_bytes(value: np.ndarray) -> bytes:
    output = io.BytesIO()
    np.lib.format.write_array(output, value, version=(1, 0), allow_pickle=False)
    return output.getvalue()


def _observations_npz_bytes(observations: tuple[Observation, ...]) -> bytes:
    if observations:
        robot_q = np.stack([item.robot_state.q for item in observations]).astype(
            np.float64, copy=False
        )
        robot_dq = np.stack([item.robot_state.dq for item in observations]).astype(
            np.float64, copy=False
        )
    else:
        robot_q = np.empty((0, 0), dtype=np.float64)
        robot_dq = np.empty((0, 0), dtype=np.float64)
    arrays = {
        "sequence_id": np.asarray(
            [item.sequence_id for item in observations], dtype=np.int64
        ),
        "source_time_ns": np.asarray(
            [item.source_time_ns for item in observations], dtype=np.int64
        ),
        "received_time_ns": np.asarray(
            [item.received_time_ns for item in observations], dtype=np.int64
        ),
        "robot_q": robot_q,
        "robot_dq": robot_dq,
        "object_beliefs_json": np.asarray(
            [
                canonical_json_bytes(
                    [_object_belief_dict(belief) for belief in item.object_beliefs]
                ).decode("utf-8")
                for item in observations
            ],
            dtype=np.str_,
        ),
        "current_skill_id": np.asarray(
            [item.current_skill_id or "" for item in observations], dtype=np.str_
        ),
        "current_phase": np.asarray(
            [item.current_phase or "" for item in observations], dtype=np.str_
        ),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for name in _OBSERVATION_ARRAYS:
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, _npy_bytes(arrays[name]))
    return output.getvalue()


_ACTION_SCHEMA = pa.schema(
    [
        pa.field("record_type", pa.string(), nullable=False),
        pa.field("chunk_id", pa.string()),
        pa.field("skill_id", pa.string()),
        pa.field("source_observation_id", pa.int64()),
        pa.field("source_observation_time_ns", pa.int64()),
        pa.field("generated_time_ns", pa.int64()),
        pa.field("valid_from_ns", pa.int64()),
        pa.field("expires_at_ns", pa.int64()),
        pa.field("dt_s", pa.float64()),
        pa.field("representation", pa.string()),
        pa.field("expected_phase", pa.string()),
        pa.field("action_shape", pa.list_(pa.int64())),
        pa.field("action_values", pa.list_(pa.float64())),
        pa.field("metadata_json", pa.string()),
        pa.field("source_chunk_id", pa.string()),
        pa.field("time_ns", pa.int64()),
        pa.field("q_ref", pa.list_(pa.float64())),
        pa.field("dq_ref", pa.list_(pa.float64())),
        pa.field("eef_ref", pa.list_(pa.float64())),
        pa.field("feedforward", pa.list_(pa.float64())),
        pa.field("controller_mode", pa.string()),
    ]
)


def _action_rows(record: RolloutRecord) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for action in record.actions:
        rows.append(
            {
                "record_type": "action",
                "chunk_id": action.chunk_id,
                "skill_id": action.skill_id,
                "source_observation_id": action.source_observation_id,
                "source_observation_time_ns": action.source_observation_time_ns,
                "generated_time_ns": action.generated_time_ns,
                "valid_from_ns": action.valid_from_ns,
                "expires_at_ns": action.expires_at_ns,
                "dt_s": action.dt_s,
                "representation": action.representation,
                "expected_phase": action.expected_phase,
                "action_shape": list(action.actions.shape),
                "action_values": action.actions.reshape(-1).tolist(),
                "metadata_json": canonical_json_bytes(action.metadata).decode("utf-8"),
            }
        )
    for reference in record.control_references:
        rows.append(
            {
                "record_type": "control_reference",
                "source_chunk_id": reference.source_chunk_id,
                "time_ns": reference.time_ns,
                "q_ref": None if reference.q_ref is None else reference.q_ref.tolist(),
                "dq_ref": None if reference.dq_ref is None else reference.dq_ref.tolist(),
                "eef_ref": None if reference.eef_ref is None else reference.eef_ref.tolist(),
                "feedforward": (
                    None if reference.feedforward is None else reference.feedforward.tolist()
                ),
                "controller_mode": reference.controller_mode,
            }
        )
    return rows


def _write_bytes(directory_descriptor: int, name: str, data: bytes) -> str:
    return write_descriptor_bytes(directory_descriptor, name, data)


def _publish_directory(
    output_root_descriptor: int, source_name: str, destination_name: str
) -> None:
    """Atomically rename a directory while failing if the destination exists."""
    if sys.platform == "darwin":
        function_name, no_replace = "renameatx_np", 0x00000004
    elif sys.platform.startswith("linux"):
        function_name, no_replace = "renameat2", 0x00000001
    else:
        raise RolloutValidationError(
            "atomic no-replace publication is unavailable on this platform"
        )
    function = getattr(ctypes.CDLL(None, use_errno=True), function_name, None)
    if function is None:
        raise RolloutValidationError(
            "atomic no-replace publication is unavailable on this platform"
        )
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    if function(
        output_root_descriptor,
        os.fsencode(source_name),
        output_root_descriptor,
        os.fsencode(destination_name),
        no_replace,
    ) == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise RolloutValidationError(f"rollout already exists: {destination_name}")
    raise OSError(error, os.strerror(error), destination_name)


_CHUNK_EVENT_TYPES = frozenset(
    {
        ExecutionEventType.CHUNK_ACCEPTED,
        ExecutionEventType.CHUNK_REJECTED_EXPIRED,
        ExecutionEventType.CHUNK_REJECTED_OUT_OF_ORDER,
        ExecutionEventType.CHUNK_REPLACED,
    }
)


def _reference_id(
    payload: Mapping[str, Any], key: str, expected_type: type[Any], event_type: str
) -> Any:
    if key not in payload or type(payload[key]) is not expected_type:
        raise RolloutValidationError(
            f"{event_type} event payload requires {key} as {expected_type.__name__}"
        )
    return payload[key]


def _chunk_time_is_valid(action: ActionChunk, time_ns: int) -> bool:
    """Return whether time_ns is in the chunk's half-open validity interval."""
    return action.valid_from_ns <= time_ns < action.expires_at_ns


def _validate_contents(
    *,
    rollout_id: str,
    metadata: RolloutMetadata,
    config: Mapping[str, Any],
    events: tuple[ExecutionEvent, ...],
    observations: tuple[Observation, ...],
    actions: tuple[ActionChunk, ...],
    control_references: tuple[ControlReference, ...],
) -> None:
    RolloutMetadata(**{field.name: getattr(metadata, field.name) for field in fields(metadata)})
    if sha256_json(config) != metadata.task_config_hash:
        raise RolloutValidationError("task_config_hash does not match config.json")

    def require_monotonic_bound(value: int, name: str) -> None:
        if not metadata.monotonic_start_ns <= value <= metadata.monotonic_end_ns:
            raise RolloutValidationError(f"{name} falls outside rollout monotonic bounds")

    observation_by_id: dict[int, Observation] = {}
    previous_observation: Observation | None = None
    robot_width: int | None = None
    for observation in observations:
        try:
            validate_contract(observation)
        except ContractValidationError as exc:
            raise RolloutValidationError(f"invalid observation: {exc}") from exc
        if observation.sequence_id in observation_by_id:
            raise RolloutValidationError("observation sequence IDs must be unique")
        if observation.received_time_ns < observation.source_time_ns:
            raise RolloutValidationError("observation received time precedes source time")
        require_monotonic_bound(observation.source_time_ns, "observation source time")
        require_monotonic_bound(observation.received_time_ns, "observation received time")
        if previous_observation is not None:
            if observation.sequence_id <= previous_observation.sequence_id:
                raise RolloutValidationError("observation sequence IDs must increase")
            if observation.source_time_ns < previous_observation.source_time_ns:
                raise RolloutValidationError("observation source time must not regress")
            if observation.received_time_ns < previous_observation.received_time_ns:
                raise RolloutValidationError("observation received time must not regress")
        width = observation.robot_state.q.shape[0]
        if robot_width is not None and width != robot_width:
            raise RolloutValidationError("robot arrays must have one consistent shape")
        robot_width = width
        observation_by_id[observation.sequence_id] = observation
        previous_observation = observation

    action_by_id: dict[str, ActionChunk] = {}
    for action in actions:
        try:
            validate_contract(action)
        except ContractValidationError as exc:
            raise RolloutValidationError(f"invalid action: {exc}") from exc
        if action.chunk_id in action_by_id:
            raise RolloutValidationError("action chunk IDs must be unique")
        source = observation_by_id.get(action.source_observation_id)
        if source is None:
            raise RolloutValidationError(
                f"action {action.chunk_id} references an unknown source observation"
            )
        if source.source_time_ns != action.source_observation_time_ns:
            raise RolloutValidationError(
                f"action {action.chunk_id} source observation time does not match"
            )
        if source.current_skill_id is not None and source.current_skill_id != action.skill_id:
            raise RolloutValidationError(
                f"action {action.chunk_id} skill_id does not match its source observation"
            )
        if action.generated_time_ns < source.received_time_ns:
            raise RolloutValidationError(
                f"action {action.chunk_id} was generated before its source observation was received"
            )
        for value, name in (
            (action.source_observation_time_ns, "source observation time"),
            (action.generated_time_ns, "generated time"),
            (action.valid_from_ns, "valid-from time"),
            (action.expires_at_ns, "expiry time"),
        ):
            require_monotonic_bound(value, f"action {action.chunk_id} {name}")
        if action.actions.ndim != 2 or not np.isfinite(action.actions).all():
            raise RolloutValidationError("stored action arrays must be rank 2 and finite")
        canonical_json_bytes(action.metadata)
        action_by_id[action.chunk_id] = action

    for reference in control_references:
        try:
            validate_contract(reference)
        except ContractValidationError as exc:
            raise RolloutValidationError(f"invalid control reference: {exc}") from exc
        action = action_by_id.get(reference.source_chunk_id)
        if action is None:
            raise RolloutValidationError("control reference has an unknown source_chunk_id")
        require_monotonic_bound(reference.time_ns, "control reference time")
        if not _chunk_time_is_valid(action, reference.time_ns):
            raise RolloutValidationError(
                "control reference time must fall within its source chunk validity interval"
            )

    previous_event: ExecutionEvent | None = None
    observation_event_counts = {observation_id: 0 for observation_id in observation_by_id}
    chunk_lifecycle = {chunk_id: "unseen" for chunk_id in action_by_id}
    executed_reference_keys: set[tuple[str, int]] = set()

    def referenced_action(event: ExecutionEvent, key: str) -> ActionChunk:
        chunk_id = _reference_id(event.payload, key, str, event.event_type.value)
        action = action_by_id.get(chunk_id)
        if action is None:
            raise RolloutValidationError(f"event {key} is not stored")
        if event.skill_id != action.skill_id:
            raise RolloutValidationError(
                f"{event.event_type.value} skill_id does not match action {chunk_id}"
            )
        for observation_key in ("observation_id", "source_observation_id"):
            if observation_key in event.payload:
                observation_id = _reference_id(
                    event.payload, observation_key, int, event.event_type.value
                )
                if observation_id != action.source_observation_id:
                    raise RolloutValidationError(
                        f"{event.event_type.value} {observation_key} does not match "
                        f"action {chunk_id}"
                    )
        return action

    for event in events:
        try:
            event_from_dict(event_to_dict(event))
        except (EventValidationError, TypeError, ValueError) as exc:
            raise RolloutValidationError(f"invalid event: {exc}") from exc
        if event.rollout_id != rollout_id:
            raise RolloutValidationError("event rollout_id does not match artifact rollout ID")
        if event.config_hash != metadata.task_config_hash:
            raise RolloutValidationError("event config_hash does not match task_config_hash")
        if not metadata.monotonic_start_ns <= event.monotonic_time_ns <= metadata.monotonic_end_ns:
            raise RolloutValidationError("event monotonic time falls outside rollout bounds")
        if not metadata.wall_start_ns <= event.wall_time_ns <= metadata.wall_end_ns:
            raise RolloutValidationError("event wall time falls outside rollout bounds")
        if previous_event is not None:
            if event.monotonic_time_ns < previous_event.monotonic_time_ns:
                raise RolloutValidationError("event monotonic time must not regress")
            if event.sequence_id < previous_event.sequence_id:
                raise RolloutValidationError("event sequence must not regress")
        if "replaced_chunk_id" in event.payload:
            raise RolloutValidationError(
                "replaced_chunk_id is unsupported; CHUNK_REPLACED.chunk_id identifies "
                "the accepted chunk becoming replaced"
            )
        if event.event_type is ExecutionEventType.OBSERVATION_RECEIVED:
            observation_id = _reference_id(
                event.payload, "observation_id", int, event.event_type.value
            )
            if observation_id not in observation_by_id:
                raise RolloutValidationError(
                    "OBSERVATION_RECEIVED observation_id is not stored"
                )
            observation = observation_by_id[observation_id]
            if event.monotonic_time_ns != observation.received_time_ns:
                raise RolloutValidationError(
                    "OBSERVATION_RECEIVED time does not match observation received_time_ns"
                )
            if event.skill_id != observation.current_skill_id:
                raise RolloutValidationError(
                    "OBSERVATION_RECEIVED skill_id does not match observation"
                )
            observation_event_counts[observation_id] += 1
        if event.event_type in _CHUNK_EVENT_TYPES:
            action = referenced_action(event, "chunk_id")
            chunk_id = action.chunk_id
            if event.monotonic_time_ns < action.generated_time_ns:
                raise RolloutValidationError(
                    f"{event.event_type.value} occurs before chunk generation"
                )
            if event.event_type is ExecutionEventType.CHUNK_REPLACED:
                if chunk_lifecycle[chunk_id] != "accepted":
                    raise RolloutValidationError(
                        "CHUNK_REPLACED requires one previously accepted chunk lifecycle"
                    )
                if not _chunk_time_is_valid(action, event.monotonic_time_ns):
                    raise RolloutValidationError(
                        "CHUNK_REPLACED cannot replace an expired or not-yet-valid chunk "
                        "outside its validity interval"
                    )
                chunk_lifecycle[chunk_id] = "replaced"
            elif chunk_lifecycle[chunk_id] != "unseen":
                raise RolloutValidationError(
                    f"chunk {chunk_id} has a contradictory lifecycle transition"
                )
            elif event.event_type is ExecutionEventType.CHUNK_ACCEPTED:
                if not _chunk_time_is_valid(action, event.monotonic_time_ns):
                    raise RolloutValidationError(
                        f"{event.event_type.value} accepted an expired or not-yet-valid chunk"
                    )
                chunk_lifecycle[chunk_id] = "accepted"
            elif event.event_type is ExecutionEventType.CHUNK_REJECTED_EXPIRED:
                if event.monotonic_time_ns < action.expires_at_ns:
                    raise RolloutValidationError(
                        "CHUNK_REJECTED_EXPIRED must occur at or after expiry"
                    )
                chunk_lifecycle[chunk_id] = "rejected"
            else:
                chunk_lifecycle[chunk_id] = "rejected"
        if event.event_type is ExecutionEventType.ACTION_EXECUTED:
            action = referenced_action(event, "source_chunk_id")
            if "time_ns" in event.payload:
                reference_time = _reference_id(
                    event.payload, "time_ns", int, event.event_type.value
                )
                if reference_time != event.monotonic_time_ns:
                    raise RolloutValidationError(
                        "ACTION_EXECUTED time_ns does not match its saved ControlReference"
                    )
            if not _chunk_time_is_valid(action, event.monotonic_time_ns):
                raise RolloutValidationError(
                    "ACTION_EXECUTED time must fall within its source chunk validity interval"
                )
            if chunk_lifecycle[action.chunk_id] != "accepted":
                raise RolloutValidationError(
                    "ACTION_EXECUTED requires a currently accepted source chunk"
                )
            matches = [
                reference
                for reference in control_references
                if reference.source_chunk_id == action.chunk_id
                and reference.time_ns == event.monotonic_time_ns
            ]
            if len(matches) != 1:
                raise RolloutValidationError(
                    "ACTION_EXECUTED must resolve to exactly one saved ControlReference"
                )
            reference_key = (action.chunk_id, event.monotonic_time_ns)
            if reference_key in executed_reference_keys:
                raise RolloutValidationError(
                    "one saved ControlReference cannot be executed more than once"
                )
            executed_reference_keys.add(reference_key)
        for key in ("observation_id", "source_observation_id"):
            if key in event.payload:
                observation_id = _reference_id(event.payload, key, int, event.event_type.value)
                if observation_id not in observation_by_id:
                    raise RolloutValidationError(f"event {key} is not stored")
        for key in ("chunk_id", "source_chunk_id"):
            if key in event.payload:
                chunk_id = _reference_id(event.payload, key, str, event.event_type.value)
                if chunk_id not in action_by_id:
                    raise RolloutValidationError(f"event {key} is not stored")
        previous_event = event
    if any(count != 1 for count in observation_event_counts.values()):
        raise RolloutValidationError(
            "each stored observation requires exactly one OBSERVATION_RECEIVED event"
        )
    if any(state == "unseen" for state in chunk_lifecycle.values()):
        raise RolloutValidationError(
            "action event references must cover exactly the stored actions"
        )


class RolloutWriter:
    """Write one absent rollout directory through a sibling temporary directory."""

    def __init__(self, output_root: Path, rollout_id: str) -> None:
        if not isinstance(output_root, Path):
            output_root = Path(output_root)
        _non_empty_string(rollout_id, "rollout_id")
        self._output_root = output_root.resolve(strict=False)
        self._path = (self._output_root / rollout_id).resolve(strict=False)
        if not self._path.is_relative_to(self._output_root):
            raise RolloutValidationError("rollout target must remain within the output root")
        if self._path.parent != self._output_root:
            raise RolloutValidationError("rollout_id must name one directory in the output root")
        self._rollout_id = rollout_id

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: RolloutRecord) -> Path:
        SafetyConfig.from_mapping(os.environ).require_simulation_only()
        if not isinstance(record, RolloutRecord):
            raise RolloutValidationError("record must be RolloutRecord")
        record = RolloutRecord(
            **{field.name: getattr(record, field.name) for field in fields(record)}
        )
        _validate_contents(
            rollout_id=self._rollout_id,
            metadata=record.metadata,
            config=record.config,
            events=record.events,
            observations=record.observations,
            actions=record.actions,
            control_references=record.control_references,
        )
        self._output_root.mkdir(parents=True, exist_ok=True)
        try:
            output_root_descriptor, output_root_identity = open_directory(
                self._output_root
            )
        except ArtifactIOError as exc:
            raise RolloutValidationError(str(exc)) from exc
        try:
            if entry_identity(output_root_descriptor, self._rollout_id) is not None:
                raise RolloutValidationError(f"rollout already exists: {self._path}")
            try:
                temporary = create_temporary_directory(
                    output_root_descriptor, f".{self._rollout_id}."
                )
                published = False
                try:
                    payloads = {
                        "config.json": canonical_json_bytes(record.config),
                        "metrics.json": canonical_json_bytes(record.metrics),
                        "events.jsonl": b"".join(
                            canonical_json_bytes(event_to_dict(event)) + b"\n"
                            for event in record.events
                        ),
                        "observations.npz": _observations_npz_bytes(
                            record.observations
                        ),
                        "summary.md": record.summary.encode("utf-8"),
                    }
                    artifact_hashes = {
                        filename: _write_bytes(
                            temporary.descriptor, filename, data
                        )
                        for filename, data in payloads.items()
                    }

                    table = pa.Table.from_pylist(
                        _action_rows(record), schema=_ACTION_SCHEMA
                    )

                    def write_parquet(handle: Any) -> None:
                        pq.write_table(
                            table,
                            handle,
                            compression="zstd",
                            use_dictionary=False,
                            write_statistics=False,
                            version="2.6",
                            data_page_version="1.0",
                        )

                    artifact_hashes["actions.parquet"] = write_descriptor_file(
                        temporary.descriptor,
                        "actions.parquet",
                        write_parquet,
                    )
                    _write_bytes(
                        temporary.descriptor,
                        "metadata.json",
                        canonical_json_bytes(
                            _metadata_dict(record.metadata, artifact_hashes)
                        ),
                    )
                    fsync_directory(temporary.descriptor)
                    verify_regular_entries(temporary.descriptor, _REQUIRED_FILES)
                    if not path_matches_directory(
                        self._output_root, output_root_identity
                    ):
                        raise RolloutValidationError(
                            "output root identity changed during rollout write"
                        )
                    if (
                        entry_identity(output_root_descriptor, temporary.name)
                        != temporary.identity
                    ):
                        raise RolloutValidationError(
                            "temporary directory identity changed during rollout write"
                        )
                    _publish_directory(
                        output_root_descriptor,
                        temporary.name,
                        self._rollout_id,
                    )
                    if (
                        entry_identity(output_root_descriptor, self._rollout_id)
                        != temporary.identity
                    ):
                        raise RolloutValidationError(
                            "published directory identity does not match created temp inode"
                        )
                    fsync_directory(output_root_descriptor)
                    if not path_matches_directory(
                        self._output_root, output_root_identity
                    ):
                        raise RolloutValidationError(
                            "output root identity changed during rollout publication"
                        )
                    published = True
                    return self._path
                finally:
                    if not published:
                        cleanup_exact_directory(
                            output_root_descriptor,
                            temporary.descriptor,
                            temporary.identity,
                            temporary.name,
                        )
                    os.close(temporary.descriptor)
            except ArtifactIOError as exc:
                raise RolloutValidationError(str(exc)) from exc
        finally:
            os.close(output_root_descriptor)


def _reject_json_constant(value: str) -> None:
    raise RolloutValidationError(f"JSON contains nonfinite constant {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RolloutValidationError(f"JSON contains duplicate key {key}")
        result[key] = value
    return result


def _parse_json(data: bytes, name: str, *, require_canonical: bool = True) -> Any:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RolloutValidationError(f"{name} must be UTF-8") from exc
    try:
        value = json.loads(
            text,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_object,
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise RolloutValidationError(f"{name} is not valid JSON: {exc}") from exc
    if require_canonical and canonical_json_bytes(value) != data:
        raise RolloutValidationError(f"{name} is not canonical JSON")
    return value


def _read_metadata(
    data: bytes, optional_files: tuple[str, ...]
) -> tuple[RolloutMetadata, Mapping[str, str]]:
    raw = _parse_json(data, "metadata.json")
    if not isinstance(raw, dict):
        raise RolloutValidationError("metadata.json must contain an object")
    metadata_names = {field.name for field in fields(RolloutMetadata)}
    expected = metadata_names | {"schema_version", "artifact_hashes"}
    missing = expected - set(raw)
    extra = set(raw) - expected
    if missing:
        raise RolloutValidationError(f"metadata.json has missing fields: {sorted(missing)}")
    if extra:
        raise RolloutValidationError(f"metadata.json has extra fields: {sorted(extra)}")
    _schema_version(raw["schema_version"], "artifact")
    hashes = raw["artifact_hashes"]
    if not isinstance(hashes, dict):
        raise RolloutValidationError("artifact_hashes must be an object")
    expected_hashes = _PAYLOAD_FILES | set(optional_files)
    if set(hashes) != expected_hashes:
        raise RolloutValidationError(
            "every payload and optional file must be listed and hashed in artifact_hashes"
        )
    artifact_hashes = MappingProxyType(
        {
            _non_empty_string(name, "artifact hash filename"): _sha256(
                digest, f"artifact_hashes[{name}]"
            )
            for name, digest in hashes.items()
        }
    )
    values = {name: raw[name] for name in metadata_names}
    try:
        metadata = RolloutMetadata(**values)
    except TypeError as exc:
        raise RolloutValidationError(f"metadata.json is invalid: {exc}") from exc
    return metadata, artifact_hashes


def _load_events(stream: BinaryIO) -> tuple[ExecutionEvent, ...]:
    events: list[ExecutionEvent] = []
    for index, line in enumerate(stream, start=1):
        if not line.endswith(b"\n") or line == b"\n":
            raise RolloutValidationError(
                f"events.jsonl line {index} must be one non-empty newline-terminated event"
            )
        raw = _parse_json(
            line[:-1], f"events.jsonl line {index}", require_canonical=True
        )
        try:
            events.append(event_from_dict(raw))
        except (EventValidationError, TypeError) as exc:
            raise RolloutValidationError(
                f"events.jsonl line {index} is invalid: {exc}"
            ) from exc
    return tuple(events)


def _require_observation_arrays(arrays: Mapping[str, np.ndarray]) -> None:
    if set(arrays) != set(_OBSERVATION_ARRAYS):
        raise RolloutValidationError(
            "observations.npz must contain exactly the declared named arrays"
        )
    for name in ("sequence_id", "source_time_ns", "received_time_ns"):
        if arrays[name].dtype != np.dtype(np.int64) or arrays[name].ndim != 1:
            raise RolloutValidationError(f"observations.npz {name} must be an int64 vector")
    for name in ("robot_q", "robot_dq"):
        if arrays[name].dtype != np.dtype(np.float64) or arrays[name].ndim != 2:
            raise RolloutValidationError(f"observations.npz {name} must be a float64 matrix")
        if not np.isfinite(arrays[name]).all():
            raise RolloutValidationError(f"observations.npz {name} must be finite")
    for name in ("object_beliefs_json", "current_skill_id", "current_phase"):
        if arrays[name].ndim != 1 or arrays[name].dtype.kind != "U":
            raise RolloutValidationError(f"observations.npz {name} must be a Unicode vector")
    row_count = arrays["sequence_id"].shape[0]
    if any(array.shape[0] != row_count for array in arrays.values()):
        raise RolloutValidationError("observations.npz arrays must have equal row counts")
    if arrays["robot_q"].shape != arrays["robot_dq"].shape:
        raise RolloutValidationError("observations.npz robot arrays must have equal shapes")


def _load_object_beliefs(text: str, row: int) -> tuple[ObjectBelief, ...]:
    raw = _parse_json(
        text.encode("utf-8"), f"observations.npz object beliefs row {row}"
    )
    if not isinstance(raw, list):
        raise RolloutValidationError("stored object beliefs must be a list")
    expected = {
        "entity_id",
        "label",
        "pose",
        "pose_confidence",
        "state",
        "state_confidence",
        "last_seen_ns",
        "provenance",
    }
    beliefs: list[ObjectBelief] = []
    for value in raw:
        if not isinstance(value, dict) or set(value) != expected:
            raise RolloutValidationError("stored object belief has invalid fields")
        try:
            beliefs.append(ObjectBelief(**value))
        except (ContractValidationError, TypeError) as exc:
            raise RolloutValidationError(f"stored object belief is invalid: {exc}") from exc
    return tuple(beliefs)


def _load_observations(stream: BinaryIO) -> tuple[Observation, ...]:
    try:
        stream.seek(0)
        with zipfile.ZipFile(stream, "r") as raw_archive:
            member_names = [info.filename for info in raw_archive.infolist()]
        expected_members = {f"{name}.npy" for name in _OBSERVATION_ARRAYS}
        if len(member_names) != len(set(member_names)):
            raise RolloutValidationError(
                "observations.npz contains duplicate raw NPZ members"
            )
        if set(member_names) != expected_members:
            raise RolloutValidationError(
                "observations.npz must contain exactly one canonical <name>.npy "
                "member per declared key"
            )
        stream.seek(0)
        with np.load(stream, allow_pickle=False) as archive:
            arrays = {name: np.array(archive[name], copy=True) for name in archive.files}
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise RolloutValidationError(f"observations.npz is invalid: {exc}") from exc
    _require_observation_arrays(arrays)
    observations: list[Observation] = []
    for row in range(arrays["sequence_id"].shape[0]):
        skill_id = str(arrays["current_skill_id"][row])
        phase = str(arrays["current_phase"][row])
        try:
            observations.append(
                Observation(
                    sequence_id=int(arrays["sequence_id"][row]),
                    source_time_ns=int(arrays["source_time_ns"][row]),
                    received_time_ns=int(arrays["received_time_ns"][row]),
                    robot_state=RobotState(
                        q=arrays["robot_q"][row], dq=arrays["robot_dq"][row]
                    ),
                    object_beliefs=_load_object_beliefs(
                        str(arrays["object_beliefs_json"][row]), row
                    ),
                    current_skill_id=skill_id or None,
                    current_phase=phase or None,
                )
            )
        except (ContractValidationError, TypeError) as exc:
            raise RolloutValidationError(f"stored observation row {row} is invalid: {exc}") from exc
    return tuple(observations)


_ACTION_FIELDS = frozenset(
    {
        "chunk_id",
        "skill_id",
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
    }
)
_ACTION_ROW_FIELDS = _ACTION_FIELDS | {"expected_phase"}
_CONTROL_FIELDS = frozenset(
    {"source_chunk_id", "time_ns", "q_ref", "dq_ref", "eef_ref", "feedforward", "controller_mode"}
)


def _required_row_values(row: Mapping[str, Any], names: frozenset[str], kind: str) -> None:
    missing = sorted(name for name in names if row[name] is None)
    if missing:
        raise RolloutValidationError(f"stored {kind} row has null required fields: {missing}")


def _load_actions(
    stream: BinaryIO,
) -> tuple[tuple[ActionChunk, ...], tuple[ControlReference, ...]]:
    try:
        stream.seek(0)
        table = pq.read_table(stream, use_threads=False)
    except (OSError, pa.ArrowException) as exc:
        raise RolloutValidationError(f"actions.parquet is invalid: {exc}") from exc
    if table.schema != _ACTION_SCHEMA:
        raise RolloutValidationError("actions.parquet does not use the canonical fixed schema")
    actions: list[ActionChunk] = []
    references: list[ControlReference] = []
    for index, row in enumerate(table.to_pylist()):
        record_type = row["record_type"]
        try:
            if record_type == "action":
                _required_row_values(row, _ACTION_FIELDS, "action")
                if any(row[name] is not None for name in _CONTROL_FIELDS):
                    raise RolloutValidationError("stored action row contains control fields")
                shape = row["action_shape"]
                values = row["action_values"]
                if (
                    not isinstance(shape, list)
                    or len(shape) != 2
                    or any(type(size) is not int or size < 0 for size in shape)
                    or math.prod(shape) != len(values)
                ):
                    raise RolloutValidationError("stored action shape is invalid")
                metadata = _parse_json(
                    row["metadata_json"].encode("utf-8"),
                    f"actions.parquet metadata row {index}",
                )
                if not isinstance(metadata, dict):
                    raise RolloutValidationError("stored action metadata must be an object")
                actions.append(
                    ActionChunk(
                        chunk_id=row["chunk_id"],
                        skill_id=row["skill_id"],
                        source_observation_id=row["source_observation_id"],
                        source_observation_time_ns=row["source_observation_time_ns"],
                        generated_time_ns=row["generated_time_ns"],
                        valid_from_ns=row["valid_from_ns"],
                        expires_at_ns=row["expires_at_ns"],
                        dt_s=row["dt_s"],
                        actions=np.asarray(values, dtype=np.float64).reshape(tuple(shape)),
                        representation=row["representation"],
                        expected_phase=row["expected_phase"],
                        metadata=metadata,
                    )
                )
            elif record_type == "control_reference":
                _required_row_values(
                    row,
                    frozenset({"source_chunk_id", "time_ns", "controller_mode"}),
                    "control reference",
                )
                if any(row[name] is not None for name in _ACTION_ROW_FIELDS):
                    raise RolloutValidationError(
                        "stored control reference row contains action fields"
                    )
                references.append(
                    ControlReference(
                        source_chunk_id=row["source_chunk_id"],
                        time_ns=row["time_ns"],
                        q_ref=row["q_ref"],
                        dq_ref=row["dq_ref"],
                        eef_ref=row["eef_ref"],
                        feedforward=row["feedforward"],
                        controller_mode=row["controller_mode"],
                    )
                )
            else:
                raise RolloutValidationError(
                    f"actions.parquet row {index} has unknown record_type"
                )
        except (ContractValidationError, TypeError, ValueError) as exc:
            if isinstance(exc, RolloutValidationError):
                raise
            raise RolloutValidationError(
                f"actions.parquet row {index} is invalid: {exc}"
            ) from exc
    return tuple(actions), tuple(references)


def _snapshot_rollout(path: Path) -> ArtifactSnapshot:
    try:
        return read_artifact_snapshot(
            path, _REQUIRED_FILES, _OPTIONAL_FILES, _REQUIRED_FILES
        )
    except ArtifactIOError as exc:
        raise RolloutValidationError(str(exc)) from exc


def _load_rollout(snapshot: ArtifactSnapshot, *, verify_hashes: bool) -> RolloutArtifact:
    optional_files = snapshot.optional_files
    try:
        metadata, artifact_hashes = _read_metadata(
            snapshot.stream("metadata.json").read(), optional_files
        )
        if verify_hashes:
            for filename, expected in artifact_hashes.items():
                actual = snapshot.digest(filename)
                if actual != expected:
                    raise RolloutValidationError(
                        f"artifact hash mismatch for {filename}"
                    )
        config = _parse_json(snapshot.stream("config.json").read(), "config.json")
        metrics = _parse_json(snapshot.stream("metrics.json").read(), "metrics.json")
        if not isinstance(config, dict) or not isinstance(metrics, dict):
            raise RolloutValidationError("config.json and metrics.json must contain objects")
        events = _load_events(snapshot.stream("events.jsonl"))
        observations = _load_observations(snapshot.stream("observations.npz"))
        actions, references = _load_actions(snapshot.stream("actions.parquet"))
        summary = snapshot.stream("summary.md").read().decode("utf-8")
    except (ArtifactIOError, OSError, UnicodeDecodeError, KeyError) as exc:
        raise RolloutValidationError(f"could not load rollout: {exc}") from exc
    frozen_config = _freeze_json(config, "config")
    frozen_metrics = _freeze_json(metrics, "metrics")
    artifact = RolloutArtifact(
        path=snapshot.path,
        schema_version=SCHEMA_VERSION,
        metadata=metadata,
        artifact_hashes=artifact_hashes,
        config=frozen_config,
        metrics=frozen_metrics,
        events=events,
        observations=observations,
        actions=actions,
        control_references=references,
        summary=summary,
        optional_files=optional_files,
    )
    _validate_contents(
        rollout_id=snapshot.path.name,
        metadata=metadata,
        config=frozen_config,
        events=events,
        observations=observations,
        actions=actions,
        control_references=references,
    )
    return artifact


def load_rollout(path: Path) -> RolloutArtifact:
    """Parse and reconstruct the declared rollout files without trusting pickles."""
    with _snapshot_rollout(Path(path)) as snapshot:
        return _load_rollout(snapshot, verify_hashes=False)


def validate_rollout(path: Path) -> RolloutArtifact:
    """Strictly verify hashes, schemas, safety, ordering, and cross-references."""
    with _snapshot_rollout(Path(path)) as snapshot:
        return _load_rollout(snapshot, verify_hashes=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate and replay exactly one saved simulation rollout."""
    parser = argparse.ArgumentParser(prog="python -m reflect.rollout")
    subcommands = parser.add_subparsers(dest="command", required=True)
    replay_parser = subcommands.add_parser("replay")
    replay_parser.add_argument("path", type=Path)
    arguments = parser.parse_args(argv)
    SafetyConfig.from_mapping(os.environ).require_simulation_only()
    from reflect.replay import format_replay, replay_rollout

    try:
        result = replay_rollout(arguments.path)
    except RolloutValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(format_replay(result))
    return 0


if __name__ == "__main__":
    sys.modules["reflect.rollout"] = sys.modules[__name__]
    raise SystemExit(main())
