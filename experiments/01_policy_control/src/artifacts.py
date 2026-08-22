"""Fail-closed, deterministic artifact boundaries for Experiment 01.

This module deliberately has no MuJoCo import.  Physics is kept behind the worker
boundary; manifest inspection, resource admission, replay, and reporting remain
usable in a minimal analysis process.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, fields, is_dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any

import numpy as np

from reflect.replay import ReplayResult, replay_rollout
from reflect.rollout import RolloutArtifact, RolloutRecord, RolloutWriter, validate_rollout


SCHEMA_VERSION = 1
STUDY_ID = "reflect-lite-policy-control"
MIB = 1024 * 1024
ROLLOUT_RESERVATION_BYTES = 2 * MIB
LIFECYCLE_LIMIT_BYTES = 14_576 * MIB
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_STACK_ORDER = {f"P{number}": number for number in range(1, 7)}


class ArtifactError(ValueError):
    """An artifact is malformed, ambiguous, or conflicts with immutable evidence."""


class ImplementationDriftError(ArtifactError):
    """Implementation-owned bytes no longer match the bound Git commit."""


def canonical_json_bytes(value: object, *, newline: bool = True) -> bytes:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArtifactError(f"value is not canonical JSON: {exc}") from exc
    return payload + (b"\n" if newline else b"")


def _duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ArtifactError(f"nonfinite JSON value: {value}")


def load_canonical_json(path: Path, expected_keys: frozenset[str] | set[str]) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_duplicates,
            parse_constant=_reject_constant,
        )
    except ArtifactError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactError("artifact root must be an object")
    missing = set(expected_keys) - set(value)
    unknown = set(value) - set(expected_keys)
    if missing:
        raise ArtifactError(f"artifact missing keys: {sorted(missing)}")
    if unknown:
        raise ArtifactError(f"artifact unknown keys: {sorted(unknown)}")
    if raw != canonical_json_bytes(value):
        raise ArtifactError("artifact bytes are not canonical JSON with one LF")
    return value


def _exact_int(value: object, name: str, *, nonnegative: bool = True) -> int:
    if type(value) is not int or (nonnegative and value < 0):
        raise ArtifactError(f"{name} must be a nonnegative exact integer")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactError(f"{name} must be a nonempty string")
    return value


def _hash(value: object, name: str, pattern: re.Pattern[str] = _SHA256) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ArtifactError(f"{name} has an invalid digest")
    return value


def _closed(row: object, keys: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ArtifactError(f"{name} must be an object")
    missing, unknown = set(keys) - set(row), set(row) - set(keys)
    if missing or unknown:
        raise ArtifactError(f"{name} keys differ: missing={sorted(missing)}, unknown={sorted(unknown)}")
    return row


def _sorted_unique_strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ArtifactError(f"{name} must be a string array")
    result = tuple(value)
    if result != tuple(sorted(set(result))):
        raise ArtifactError(f"{name} must be sorted and unique")
    return result


@dataclass(frozen=True)
class ShardSpec:
    shard_id: str
    stack_id: str
    configuration_hash: str
    seed: int
    condition_ids: tuple[str, ...]
    episode_count: int
    output_identities: tuple[str, ...]


_MANIFEST_KEYS = frozenset({
    "schema_version", "study_id", "phase", "revision", "stage",
    "implementation_sha", "predecessor_sha256", "config_sha256",
    "p3_gate_sha256", "seed_manifest_sha256", "parameter_vector",
    "parameter_hash", "scenario_generator_hash", "condition_hash",
    "metric_hash", "gate_hash", "resource_limits", "shards", "state",
})
_SHARD_KEYS = frozenset({
    "shard_id", "stack_id", "configuration_hash", "seed", "condition_ids",
    "episode_count", "output_identities",
})


def load_protocol_manifest(path: Path) -> dict[str, Any]:
    manifest = load_canonical_json(path, _MANIFEST_KEYS)
    if _exact_int(manifest["schema_version"], "schema_version") != 1:
        raise ArtifactError("unsupported manifest schema_version")
    _text(manifest["study_id"], "study_id")
    if manifest["phase"] not in {"pilot", "confirmation"}:
        raise ArtifactError("phase must be pilot or confirmation")
    _exact_int(manifest["revision"], "revision")
    _text(manifest["stage"], "stage")
    _hash(manifest["implementation_sha"], "implementation_sha", _GIT_SHA)
    if manifest["predecessor_sha256"] is not None:
        _hash(manifest["predecessor_sha256"], "predecessor_sha256")
    for key in (
        "config_sha256", "p3_gate_sha256", "seed_manifest_sha256",
        "parameter_hash", "scenario_generator_hash", "condition_hash",
        "metric_hash", "gate_hash",
    ):
        _hash(manifest[key], key)
    if not isinstance(manifest["parameter_vector"], dict) or not isinstance(manifest["resource_limits"], dict):
        raise ArtifactError("parameter_vector and resource_limits must be objects")
    if manifest["state"] != "READY" or not isinstance(manifest["shards"], list):
        raise ArtifactError("manifest must be READY with a shard array")
    seen: set[str] = set()
    for raw in manifest["shards"]:
        row = _closed(raw, _SHARD_KEYS, "shard")
        shard_id = _text(row["shard_id"], "shard_id")
        stack = _text(row["stack_id"], "stack_id")
        if stack not in _STACK_ORDER or not shard_id.startswith(f"{stack}:") or shard_id in seen:
            raise ArtifactError("shard identities must be unique and stack-prefixed")
        seen.add(shard_id)
        _hash(row["configuration_hash"], "configuration_hash")
        _exact_int(row["seed"], "seed")
        conditions = _sorted_unique_strings(row["condition_ids"], "condition_ids")
        outputs = _sorted_unique_strings(row["output_identities"], "output_identities")
        count = _exact_int(row["episode_count"], "episode_count")
        if count == 0 or count != len(outputs) or count != len(conditions):
            raise ArtifactError("episode_count must equal declared conditions and outputs")
    return manifest


def iter_manifest(path: Path) -> Iterator[ShardSpec]:
    manifest = load_protocol_manifest(Path(path))
    rows = sorted(manifest["shards"], key=lambda row: (_STACK_ORDER[row["stack_id"]], row["shard_id"]))
    for row in rows:
        yield ShardSpec(
            row["shard_id"], row["stack_id"], row["configuration_hash"], row["seed"],
            tuple(row["condition_ids"]), row["episode_count"], tuple(row["output_identities"]),
        )


_RESOURCE_REASONS = frozenset({
    "PHASE_BYTES_EXCEEDED", "TEMP_BYTES_EXCEEDED", "QUARANTINE_BYTES_EXCEEDED",
    "INSUFFICIENT_FREE_BYTES", "WALL_TIME_EXCEEDED", "CPU_TIME_EXCEEDED",
})


@dataclass(frozen=True)
class ResourceDisposition:
    schema_version: int
    study_id: str
    phase: str
    revision: int
    retained_bytes: int
    temp_bytes: int
    quarantine_bytes: int
    free_bytes: int
    reserved_bytes: int
    wall_seconds: int
    cpu_seconds: int
    shard_wall_limit_seconds: int
    disposition: str
    reasons: tuple[str, ...]

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(asdict(self) | {"reasons": list(self.reasons)})

    def to_json(self) -> str:
        """Return the one-line canonical CLI representation."""
        return self.canonical_bytes().decode("utf-8").removesuffix("\n")


def preflight_resources(
    stage: str,
    retained_bytes: int,
    temp_bytes: int,
    quarantine_bytes: int,
    free_bytes: int,
    wall_seconds: int,
    cpu_seconds: int,
    *,
    config: object | None = None,
) -> ResourceDisposition:
    values = {
        name: _exact_int(value, name)
        for name, value in {
            "retained_bytes": retained_bytes, "temp_bytes": temp_bytes,
            "quarantine_bytes": quarantine_bytes, "free_bytes": free_bytes,
            "wall_seconds": wall_seconds, "cpu_seconds": cpu_seconds,
        }.items()
    }
    if stage not in {"pilot", "confirmation"}:
        raise ArtifactError("stage must be pilot or confirmation")
    if config is not None:
        resources = getattr(config, "resources", None)
        if resources is None or getattr(resources, "rollout_bytes", None) != ROLLOUT_RESERVATION_BYTES or getattr(resources, "phase_bytes", None) != LIFECYCLE_LIMIT_BYTES:
            raise ArtifactError("configuration resource ceilings differ from the frozen 2 MiB/14,576 MiB contract")
    non_rollout_cap = (128 if stage == "pilot" else 256) * MIB
    wall_cap = (8 if stage == "pilot" else 24) * 3600
    cpu_cap = (80 if stage == "pilot" else 240) * 3600
    reasons: list[str] = []
    if values["retained_bytes"] + ROLLOUT_RESERVATION_BYTES > LIFECYCLE_LIMIT_BYTES:
        reasons.append("PHASE_BYTES_EXCEEDED")
    if values["temp_bytes"] > non_rollout_cap:
        reasons.append("TEMP_BYTES_EXCEEDED")
    if values["quarantine_bytes"] > non_rollout_cap:
        reasons.append("QUARANTINE_BYTES_EXCEEDED")
    if values["free_bytes"] < ROLLOUT_RESERVATION_BYTES:
        reasons.append("INSUFFICIENT_FREE_BYTES")
    if values["wall_seconds"] > wall_cap:
        reasons.append("WALL_TIME_EXCEEDED")
    if values["cpu_seconds"] > cpu_cap:
        reasons.append("CPU_TIME_EXCEEDED")
    closed = tuple(sorted(set(reasons)))
    assert set(closed) <= _RESOURCE_REASONS
    return ResourceDisposition(
        1, STUDY_ID, stage, 1, values["retained_bytes"], values["temp_bytes"],
        values["quarantine_bytes"], values["free_bytes"], ROLLOUT_RESERVATION_BYTES,
        values["wall_seconds"], values["cpu_seconds"], 3600,
        "ALLOW" if not closed else "REFUSE", closed,
    )


def _git(root: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *arguments], cwd=root, check=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise ImplementationDriftError(exc.stderr.decode("utf-8", "replace").strip()) from exc


@dataclass(frozen=True)
class ImplementationSnapshot:
    root: Path
    implementation_sha: str
    owned_paths: tuple[Path, ...]
    committed_files: tuple[tuple[str, str], ...]

    @classmethod
    def capture(cls, root: Path, implementation_sha: str, owned_paths: Sequence[Path]) -> "ImplementationSnapshot":
        root = Path(root).resolve()
        _hash(implementation_sha, "implementation_sha", _GIT_SHA)
        paths = tuple(Path(item) for item in owned_paths)
        if not paths or any(item.is_absolute() or ".." in item.parts for item in paths):
            raise ImplementationDriftError("owned paths must be nonempty root-relative paths")
        _git(root, "cat-file", "-e", f"{implementation_sha}^{{commit}}")
        names = _git(root, "ls-tree", "-r", "--name-only", implementation_sha, "--", *map(str, paths)).decode().splitlines()
        committed = tuple(
            (name, hashlib.sha256(_git(root, "show", f"{implementation_sha}:{name}")).hexdigest())
            for name in sorted(names)
        )
        if not committed:
            raise ImplementationDriftError("implementation commit contains no owned files")
        return cls(root, implementation_sha, paths, committed)

    def _current(self) -> tuple[tuple[str, str], ...]:
        current: list[tuple[str, str]] = []
        for name, _ in self.committed_files:
            path = self.root / name
            if path.is_symlink() or not path.is_file():
                raise ImplementationDriftError(f"tracked implementation path changed: {name}")
            current.append((name, hashlib.sha256(path.read_bytes()).hexdigest()))
        untracked = _git(
            self.root, "ls-files", "--others", "--exclude-standard", "--",
            *map(str, self.owned_paths),
        ).decode().splitlines()
        if untracked:
            raise ImplementationDriftError(f"untracked implementation path: {sorted(untracked)[0]}")
        return tuple(current)

    def validate_before(self) -> "ImplementationSnapshot":
        if self._current() != self.committed_files:
            raise ImplementationDriftError("tracked implementation bytes differ from bound commit")
        return self

    def validate_after(self, before: "ImplementationSnapshot | None" = None) -> "ImplementationSnapshot":
        self.validate_before()
        if before is not None and before.committed_files != self.committed_files:
            raise ImplementationDriftError("implementation snapshot changed during operation")
        return self


def _wire(value: object) -> object:
    if isinstance(value, np.ndarray):
        return {"dtype": value.dtype.str, "shape": list(value.shape), "bytes": value.tobytes(order="C").hex()}
    if is_dataclass(value):
        return {field.name: _wire(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _wire(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_wire(item) for item in value]
    if hasattr(value, "value") and isinstance(getattr(value, "value"), (str, int)):
        return getattr(value, "value")
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ArtifactError("nonfinite runtime value")
        return value
    raise ArtifactError(f"cannot canonically encode {type(value).__name__}")


def canonical_state_bytes(value: object) -> bytes:
    return canonical_json_bytes(_wire(value), newline=False)


@dataclass(frozen=True)
class RolloutSpec:
    rollout_id: str
    stack_id: str
    seed: int
    condition_id: str
    configuration_hash: str
    protocol_sha256: str
    source_sha256: str
    max_bytes: int = ROLLOUT_RESERVATION_BYTES

    def __post_init__(self) -> None:
        _text(self.rollout_id, "rollout_id")
        if self.stack_id not in _STACK_ORDER:
            raise ArtifactError("invalid stack_id")
        _exact_int(self.seed, "seed")
        _text(self.condition_id, "condition_id")
        for name in ("configuration_hash", "protocol_sha256", "source_sha256"):
            _hash(getattr(self, name), name)
        _exact_int(self.max_bytes, "max_bytes")


def _directory_bytes(path: Path) -> int:
    total = 0
    for entry in path.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise ArtifactError(f"unexpected rollout entry: {entry.name}")
        total += entry.stat().st_size
    return total


def _validate_record_binding(record: RolloutRecord, artifact: RolloutArtifact, spec: RolloutSpec) -> None:
    if artifact.path.name != spec.rollout_id or artifact.metadata.seed != spec.seed:
        raise ArtifactError("rollout identity/seed does not match its declaration")
    if artifact.metadata.task_config_hash != spec.configuration_hash:
        raise ArtifactError("rollout configuration hash differs from shard declaration")
    if artifact.metrics.get("stack_id") != spec.stack_id or artifact.metrics.get("condition_id") != spec.condition_id:
        raise ArtifactError("rollout stack/condition differs from shard declaration")
    for key, expected in (("protocol_sha256", spec.protocol_sha256), ("source_sha256", spec.source_sha256)):
        present = artifact.metrics.get(key)
        if present is not None and present != expected:
            raise ArtifactError(f"rollout {key} differs from shard declaration")
    expected_fields = (
        record.metadata, record.config, record.metrics, record.events, record.observations,
        record.actions, record.control_references, record.summary,
    )
    actual_fields = (
        artifact.metadata, artifact.config, artifact.metrics, artifact.events,
        artifact.observations, artifact.actions, artifact.control_references, artifact.summary,
    )
    if canonical_state_bytes(expected_fields) != canonical_state_bytes(actual_fields):
        raise ArtifactError("existing rollout bytes reconstruct different declared evidence")
    replay = replay_rollout(artifact.path)
    if not replay.frames or canonical_state_bytes(replay.frames[-1].state) != canonical_state_bytes(replay.final_state):
        raise ArtifactError("terminal replay is incomplete")


def publish_or_validate_skip(record: RolloutRecord, destination: Path, spec: RolloutSpec) -> str:
    destination = Path(destination)
    if destination.name != spec.rollout_id:
        raise ArtifactError("destination name differs from rollout specification")
    if destination.exists():
        artifact = validate_rollout(destination)
        if _directory_bytes(destination) > spec.max_bytes:
            raise ArtifactError("rollout exceeds its declared byte ceiling")
        _validate_record_binding(record, artifact, spec)
        return "validated-and-skipped"
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{destination.name}.publish-", dir=destination.parent))
    try:
        staged = RolloutWriter(staging_root, destination.name).write(record)
        artifact = validate_rollout(staged)
        if _directory_bytes(staged) > spec.max_bytes:
            raise ArtifactError("rollout exceeds its declared byte ceiling")
        _validate_record_binding(record, artifact, spec)
        try:
            os.rename(staged, destination)
        except FileExistsError as exc:
            raise ArtifactError("rollout appeared concurrently") from exc
        descriptor = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    return "published"


_ARTIFACT_MANIFEST_KEYS = frozenset({
    "schema_version", "study_id", "phase", "protocol_sha256", "files", "total_bytes",
})
_FILE_KEYS = frozenset({"path", "media_type", "bytes", "sha256"})


def _write_create_only(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _media_type(name: str) -> str:
    if name.endswith(".svg"):
        return "image/svg+xml"
    return "application/jsonl" if name.endswith(".jsonl") else "application/json"


def _publication_payloads(
    raw_rows: Sequence[Mapping[str, object]],
    annotated_index: Sequence[Mapping[str, object]],
    plot_recipes: Sequence[Mapping[str, object]],
) -> dict[str, bytes]:
    raw_keys = frozenset({
        "schema_version", "revision", "stack_id", "condition_id", "variant_id",
        "scene_id", "episode_id", "anchor_id", "candidate_id", "seed",
        "rng_namespace", "tick_start", "tick_end", "units", "frames", "validity",
        "missingness", "terminal_state", "config_sha256", "code_sha256",
        "dependency_sha256", "input_sha256", "output_sha256", "replay_sha256",
        "bundle_sha256", "disposition", "reason", "analysis_included",
    })
    index_keys = frozenset({
        "schema_version", "revision", "condition_id", "label", "source_ranges",
        "command_output_sha256", "raw_links", "denominator",
    })
    range_keys = frozenset({"start", "end"})
    recipe_keys = frozenset({
        "schema_version", "revision", "plot", "source_sha256", "filters",
        "transforms", "group_by", "order_by", "axes", "units", "frames",
        "binning", "summary", "interval", "palette", "legend", "dimensions",
        "renderer_version", "seed",
    })
    normalized_raw: list[dict[str, object]] = []
    for source in raw_rows:
        row = _closed(dict(source), raw_keys, "raw evidence row")
        if _exact_int(row["schema_version"], "schema_version") != 1:
            raise ArtifactError("raw evidence schema_version must be 1")
        _exact_int(row["revision"], "revision")
        if row["stack_id"] not in _STACK_ORDER or row["validity"] not in {"VALID", "DECLARED_INVALID"}:
            raise ArtifactError("raw evidence row has invalid closed enum")
        if row["disposition"] not in {"SUCCESS", "FAILED", "TIMED_OUT", "CRASHED", "EXCLUDED", "DECLARED_MISSING"}:
            raise ArtifactError("episode disposition has an invalid closed enum")
        _exact_int(row["seed"], "seed")
        start, end = _exact_int(row["tick_start"], "tick_start"), _exact_int(row["tick_end"], "tick_end")
        if end < start:
            raise ArtifactError("tick range regresses")
        for key in ("condition_id", "variant_id", "scene_id", "episode_id", "anchor_id", "candidate_id", "rng_namespace", "terminal_state", "reason"):
            _text(row[key], key)
        if not isinstance(row["units"], dict) or not isinstance(row["frames"], dict) or not all(isinstance(key, str) and isinstance(value, str) for mapping in (row["units"], row["frames"]) for key, value in mapping.items()):
            raise ArtifactError("units and frames must be string maps")
        if type(row["analysis_included"]) is not bool:
            raise ArtifactError("analysis_included must be boolean")
        if row["missingness"] is not None:
            _text(row["missingness"], "missingness")
        for key in ("config_sha256", "code_sha256", "dependency_sha256", "input_sha256", "output_sha256", "replay_sha256"):
            _hash(row[key], key)
        if row["bundle_sha256"] is not None:
            _hash(row["bundle_sha256"], "bundle_sha256")
        normalized_raw.append(row)
    normalized_index: list[dict[str, object]] = []
    for source in annotated_index:
        row = _closed(dict(source), index_keys, "annotated index row")
        if _exact_int(row["schema_version"], "schema_version") != 1:
            raise ArtifactError("annotated index schema_version must be 1")
        _exact_int(row["revision"], "revision")
        if row["label"] not in {"WORKING", "NONWORKING", "CLASS_NOT_OBSERVED"}:
            raise ArtifactError("annotated index row has invalid closed enum")
        _text(row["condition_id"], "condition_id")
        denominator = _exact_int(row["denominator"], "denominator")
        if denominator == 0:
            raise ArtifactError("annotated index denominator must be positive")
        _hash(row["command_output_sha256"], "command_output_sha256")
        if not isinstance(row["raw_links"], list) or row["raw_links"] != sorted(set(row["raw_links"])) or not all(isinstance(item, str) and item for item in row["raw_links"]):
            raise ArtifactError("raw_links must be sorted unique strings")
        if not isinstance(row["source_ranges"], list):
            raise ArtifactError("source_ranges must be an array")
        ranges: list[tuple[int, int]] = []
        for source_range in row["source_ranges"]:
            span = _closed(source_range, range_keys, "source range")
            first, last = _exact_int(span["start"], "start"), _exact_int(span["end"], "end")
            if last <= first:
                raise ArtifactError("source range must be nonempty")
            ranges.append((first, last))
        if ranges != sorted(set(ranges)):
            raise ArtifactError("source ranges must be sorted unique")
        if row["label"] == "CLASS_NOT_OBSERVED" and (row["source_ranges"] or row["raw_links"]):
            raise ArtifactError("CLASS_NOT_OBSERVED cannot cite raw examples")
        if row["label"] != "CLASS_NOT_OBSERVED" and (not row["source_ranges"] or not row["raw_links"]):
            raise ArtifactError("observed labels require source ranges and raw links")
        normalized_index.append(row)
    normalized_recipes: list[dict[str, object]] = []
    for source in plot_recipes:
        row = _closed(dict(source), recipe_keys, "plot recipe")
        if _exact_int(row["schema_version"], "schema_version") != 1:
            raise ArtifactError("plot recipe schema_version must be 1")
        _exact_int(row["revision"], "revision")
        _exact_int(row["seed"], "seed")
        for key in ("plot", "binning", "summary", "interval", "renderer_version"):
            _text(row[key], key)
        if not str(row["plot"]).endswith(".svg") or len(Path(str(row["plot"])).parts) != 1:
            raise ArtifactError("plot must be one root-relative SVG name")
        _hash(row["source_sha256"], "source_sha256")
        for key in ("filters", "transforms", "group_by", "order_by", "palette"):
            if not isinstance(row[key], list):
                raise ArtifactError(f"{key} must be an array")
        for key in ("axes", "units", "frames", "dimensions"):
            if not isinstance(row[key], dict):
                raise ArtifactError(f"{key} must be an object")
        if type(row["legend"]) is not bool:
            raise ArtifactError("legend must be boolean")
        normalized_recipes.append(row)
    def jsonl(rows: Sequence[dict[str, object]]) -> bytes:
        return b"".join(canonical_json_bytes(row) for row in rows)
    sorted_raw = sorted(normalized_raw, key=lambda row: (str(row["stack_id"]), int(row["seed"]), str(row["condition_id"]), str(row["episode_id"])))
    sorted_index = sorted(normalized_index, key=lambda row: (str(row["condition_id"]), str(row["label"])))
    sorted_recipes = sorted(normalized_recipes, key=lambda row: str(row["plot"]))
    raw_payload = jsonl(sorted_raw)
    payloads = {
        "raw-evidence.jsonl": raw_payload,
        "annotated-samples.jsonl": jsonl(sorted_index),
        "plot-recipes.json": canonical_json_bytes(sorted_recipes),
        "derived-table.json": canonical_json_bytes({"rows": sorted_raw}),
    }
    raw_digest = hashlib.sha256(raw_payload).hexdigest()
    for recipe in sorted_recipes:
        if recipe["source_sha256"] != raw_digest:
            raise ArtifactError("plot recipe source_sha256 does not bind raw evidence")
        recipe_digest = hashlib.sha256(canonical_json_bytes(recipe)).hexdigest()
        width, height = recipe["dimensions"].get("width"), recipe["dimensions"].get("height")
        if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
            raise ArtifactError("plot dimensions require positive exact integers")
        payloads[str(recipe["plot"])] = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'data-raw-sha256="{raw_digest}" data-recipe-sha256="{recipe_digest}"></svg>\n'
        ).encode("utf-8")
    return payloads


def _artifact_manifest(payloads: Mapping[str, bytes], protocol_sha256: str) -> dict[str, object]:
    files = [
        {"path": name, "media_type": _media_type(name), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for name, payload in sorted(payloads.items())
    ]
    return {
        "schema_version": 1, "study_id": STUDY_ID, "phase": "analysis",
        "protocol_sha256": _hash(protocol_sha256, "protocol_sha256"),
        "files": files, "total_bytes": sum(row["bytes"] for row in files),
    }


def reconstruct_evidence(
    output_dir: Path,
    raw_rows: Sequence[Mapping[str, object]],
    annotated_index: Sequence[Mapping[str, object]],
    plot_recipes: Sequence[Mapping[str, object]],
    *,
    protocol_sha256: str,
) -> dict[str, object]:
    output_dir = Path(output_dir)
    payloads = _publication_payloads(raw_rows, annotated_index, plot_recipes)
    manifest = _artifact_manifest(payloads, protocol_sha256)
    marker = canonical_json_bytes(manifest)
    if output_dir.exists():
        if (output_dir / "artifact-manifest.json").is_file():
            existing = validate_evidence_publication(output_dir)
            if existing != manifest or any((output_dir / name).read_bytes() != data for name, data in payloads.items()):
                raise FileExistsError("immutable evidence publication conflicts")
            return existing
        if any(output_dir.iterdir()):
            raise ArtifactError("ambiguous partial evidence publication")
    else:
        output_dir.mkdir(parents=True)
    for name, payload in sorted(payloads.items()):
        _write_create_only(output_dir / name, payload)
    _write_create_only(output_dir / "artifact-manifest.json", marker)
    descriptor = os.open(output_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return manifest


def load_artifact_manifest(path: Path) -> dict[str, Any]:
    manifest = load_canonical_json(path, _ARTIFACT_MANIFEST_KEYS)
    if _exact_int(manifest["schema_version"], "schema_version") != 1:
        raise ArtifactError("unsupported artifact manifest")
    _text(manifest["study_id"], "study_id")
    _text(manifest["phase"], "phase")
    _hash(manifest["protocol_sha256"], "protocol_sha256")
    _exact_int(manifest["total_bytes"], "total_bytes")
    if not isinstance(manifest["files"], list):
        raise ArtifactError("files must be an array")
    previous = ""
    total = 0
    for raw in manifest["files"]:
        row = _closed(raw, _FILE_KEYS, "file row")
        path = _text(row["path"], "path")
        if Path(path).is_absolute() or len(Path(path).parts) != 1 or path <= previous or path == Path(path).name == "artifact-manifest.json":
            raise ArtifactError("file paths must be unique sorted root-relative names excluding the marker")
        previous = path
        _text(row["media_type"], "media_type")
        total += _exact_int(row["bytes"], "bytes")
        _hash(row["sha256"], "sha256")
    if total != manifest["total_bytes"]:
        raise ArtifactError("total_bytes does not match file rows")
    return manifest


def validate_evidence_publication(output_dir: Path) -> dict[str, Any]:
    output_dir = Path(output_dir)
    manifest = load_artifact_manifest(output_dir / "artifact-manifest.json")
    expected = {"artifact-manifest.json"} | {row["path"] for row in manifest["files"]}
    actual = {entry.name for entry in output_dir.iterdir()}
    if actual != expected or any(entry.is_symlink() or not entry.is_file() for entry in output_dir.iterdir()):
        raise ArtifactError("publication contains missing, extra, or nonregular entries")
    for row in manifest["files"]:
        payload = (output_dir / row["path"]).read_bytes()
        if len(payload) != row["bytes"] or hashlib.sha256(payload).hexdigest() != row["sha256"]:
            raise ArtifactError(f"published file mismatch: {row['path']}")
    return manifest


def publish_failure_disposition(value: Mapping[str, object], destination: Path) -> str:
    payload = canonical_json_bytes(dict(value))
    destination = Path(destination)
    if destination.exists():
        if destination.is_file() and destination.read_bytes() == payload:
            return "validated-and-skipped"
        raise FileExistsError("failure disposition conflicts")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_create_only(destination, payload)
    return "published"


__all__ = [
    "ArtifactError", "ImplementationDriftError", "ImplementationSnapshot",
    "ResourceDisposition", "RolloutSpec", "ShardSpec", "canonical_json_bytes",
    "canonical_state_bytes", "iter_manifest", "load_artifact_manifest",
    "load_canonical_json", "load_protocol_manifest", "preflight_resources",
    "publish_failure_disposition", "publish_or_validate_skip", "reconstruct_evidence",
    "replay_rollout", "validate_evidence_publication", "validate_rollout",
]
