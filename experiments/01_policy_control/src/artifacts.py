"""Fail-closed, deterministic artifact boundaries for Experiment 01.

This module deliberately has no MuJoCo import.  Physics is kept behind the worker
boundary; manifest inspection, resource admission, replay, and reporting remain
usable in a minimal analysis process.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
import ctypes
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any

import numpy as np

from reflect.replay import ReplayResult, replay_rollout
from reflect.rollout import RolloutArtifact, RolloutRecord, RolloutWriter, validate_rollout
from reflect._rollout_io import (
    cleanup_exact_directory, create_temporary_directory, path_matches_directory,
)
from reflect.source_evidence import open_directory_chain


SCHEMA_VERSION = 1
STUDY_ID = "reflect-lite-policy-control"
MIB = 1024 * 1024
ROLLOUT_RESERVATION_BYTES = 2 * MIB
LIFECYCLE_LIMIT_BYTES = 14_576 * MIB
PILOT_MAX_SHARD_ROLLOUTS = 27
PILOT_REVISION_ROLLOUTS = 1_008
CONFIRMATION_WAVE_ROLLOUTS = 2_508
PHASE_ALLOWANCE_BYTES = 128 * MIB
PILOT_REVISION_LIMIT_BYTES = 2_016 * MIB + PHASE_ALLOWANCE_BYTES
CONFIRMATION_LIMIT_BYTES = 10_032 * MIB + 2 * PHASE_ALLOWANCE_BYTES
PASS_LIMIT_BYTES = 10 * 1024 * MIB
_RESOURCE_LIMITS = {
    "rollout_bytes": ROLLOUT_RESERVATION_BYTES,
    "shard_wall_seconds": 3_600,
    "pilot_wall_seconds": 28_800,
    "confirmation_wall_seconds": 86_400,
    "pilot_cpu_seconds": 288_000,
    "confirmation_cpu_seconds": 864_000,
    "phase_bytes": LIFECYCLE_LIMIT_BYTES,
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_STACK_ORDER = {f"P{number}": number for number in range(1, 7)}
_FAILURE_KEYS = frozenset({
    "schema_version", "study_id", "phase", "revision", "shard_id", "stack_id",
    "seed", "condition_id", "reason", "started_at_utc", "finished_at_utc",
    "command_sha256", "readable_output_sha256", "details_sha256",
})
_FAILURE_REASONS = frozenset({
    "PROCESS_TIMEOUT", "RESOURCE_EXHAUSTION", "MISSING_OUTPUT", "CORRUPT_OUTPUT",
})
_UTC_SECONDS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


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
_PILOT_STAGES = (
    "revision", "base", "pd_60_6", "pd_100_10", "ik_0_001", "ik_0_05",
    "p5_0_01", "p5_0_04", "final_four",
)
_TUNING_CONDITIONS = ("tune-05-700-2", "tune-10-300-2", "tune-20-000-1")
_CORE_CONDITIONS = tuple(
    f"core-{rate:02d}-{latency:03d}-{moves}"
    for rate in (5, 10, 20) for latency in (0, 100, 300, 700) for moves in (1, 2)
)
_FINAL_CONDITIONS = tuple(sorted((*_CORE_CONDITIONS, "probe-drop", "probe-out-of-order")))
_PD_VALUES = ([80.0, 8.0], [60.0, 6.0], [100.0, 10.0])
_IK_VALUES = (0.01, 0.001, 0.05)
_P5_VALUES = (0.02, 0.01, 0.04)


def _parameter_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value, newline=False)).hexdigest()


def _validate_parameter_vector(value: object, digest: str) -> None:
    row = _closed(value, frozenset({"pd", "ik", "p5_smoothness"}), "parameter vector")
    pd = row["pd"]
    scalars = (*pd, row["ik"], row["p5_smoothness"]) if isinstance(pd, list) and len(pd) == 2 else ()
    if not scalars or any(type(item) not in {int, float} or not math.isfinite(float(item)) for item in scalars):
        raise ArtifactError("parameter vector has invalid finite scalar fields")
    if _parameter_hash(row) != digest:
        raise ArtifactError("parameter hash does not bind parameter vector")


def _validate_stage_parameter(stage: str, value: object) -> None:
    assert isinstance(value, dict)
    pd, ik, smoothness = value["pd"], value["ik"], value["p5_smoothness"]
    exact = {
        "revision": ([80.0, 8.0], 0.01, 0.02),
        "base": ([80.0, 8.0], 0.01, 0.02),
        "pd_60_6": ([60.0, 6.0], 0.01, 0.02),
        "pd_100_10": ([100.0, 10.0], 0.01, 0.02),
    }
    if stage in exact and (pd, ik, smoothness) != exact[stage]:
        raise ArtifactError("parameter vector differs from the frozen stage")
    if stage == "ik_0_001" and (pd not in _PD_VALUES or ik != 0.001 or smoothness != 0.02):
        raise ArtifactError("parameter vector differs from the frozen stage")
    if stage == "ik_0_05" and (pd not in _PD_VALUES or ik != 0.05 or smoothness != 0.02):
        raise ArtifactError("parameter vector differs from the frozen stage")
    if stage == "p5_0_01" and (pd not in _PD_VALUES or ik not in _IK_VALUES or smoothness != 0.01):
        raise ArtifactError("parameter vector differs from the frozen stage")
    if stage == "p5_0_04" and (pd not in _PD_VALUES or ik not in _IK_VALUES or smoothness != 0.04):
        raise ArtifactError("parameter vector differs from the frozen stage")
    if stage == "final_four" and (pd not in _PD_VALUES or ik not in _IK_VALUES or smoothness not in _P5_VALUES):
        raise ArtifactError("parameter vector differs from the frozen stage")


def _configuration_hash(config_sha256: str, parameter_hash: str) -> str:
    """Recompute the scheduler configuration from the exact experiment config bytes."""
    del parameter_hash  # Controller selection is bound independently by parameter_hash.
    from . import evaluate, timing
    from .contracts import load_config

    config_root = Path(__file__).resolve().parents[1] / "configs"
    matches = [
        candidate for candidate in (config_root / "base.yaml", config_root / "frozen.yaml")
        if candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == config_sha256
    ]
    if len(matches) != 1:
        raise ArtifactError("config_sha256 does not resolve to one exact experiment config")
    return evaluate.sha256_json(timing.scheduler_config(load_config(matches[0])))


def _validate_resource_limits(value: object) -> None:
    row = _closed(value, frozenset(_RESOURCE_LIMITS), "resource limits")
    if row != _RESOURCE_LIMITS:
        raise ArtifactError("resource limits differ from the frozen contract")


def load_protocol_manifest(path: Path) -> dict[str, Any]:
    path = Path(path)
    manifest = load_canonical_json(path, _MANIFEST_KEYS)
    if _exact_int(manifest["schema_version"], "schema_version") != 1:
        raise ArtifactError("unsupported manifest schema_version")
    if manifest["study_id"] != STUDY_ID:
        raise ArtifactError("manifest study_id is invalid")
    if manifest["phase"] not in {"pilot", "confirmation"}:
        raise ArtifactError("phase must be pilot or confirmation")
    revision = _exact_int(manifest["revision"], "revision")
    if revision not in (1, 2):
        raise ArtifactError("manifest revision must be 1 or 2")
    stage = _text(manifest["stage"], "stage")
    if manifest["phase"] == "pilot" and stage not in _PILOT_STAGES:
        raise ArtifactError("stage is outside the frozen pilot order")
    if manifest["phase"] == "confirmation" and stage != "confirmation":
        raise ArtifactError("stage is invalid for confirmation")
    _hash(manifest["implementation_sha"], "implementation_sha", _GIT_SHA)
    if stage == "revision":
        if manifest["predecessor_sha256"] is not None:
            raise ArtifactError("revision is the sole null predecessor stage")
    elif manifest["predecessor_sha256"] is None:
        raise ArtifactError("null predecessor is accepted only for revision")
    else:
        _hash(manifest["predecessor_sha256"], "predecessor_sha256")
    for key in (
        "config_sha256", "p3_gate_sha256", "seed_manifest_sha256",
        "parameter_hash", "scenario_generator_hash", "condition_hash",
        "metric_hash", "gate_hash",
    ):
        _hash(manifest[key], key)
    _validate_parameter_vector(manifest["parameter_vector"], manifest["parameter_hash"])
    _validate_stage_parameter(stage, manifest["parameter_vector"])
    _validate_resource_limits(manifest["resource_limits"])
    if manifest["state"] != "READY" or not isinstance(manifest["shards"], list):
        raise ArtifactError("manifest must be READY with a shard array")
    predecessor: dict[str, Any] | None = None
    if manifest["phase"] == "pilot":
        seed_path = path.with_name("pilot-seeds.json")
        seed_manifest = load_seed_manifest(seed_path)
        if seed_manifest["revision"] != revision or hashlib.sha256(seed_path.read_bytes()).hexdigest() != manifest["seed_manifest_sha256"]:
            raise ArtifactError("seed manifest hash/revision binding is invalid")
        if stage != "revision":
            predecessor_matches = []
            for candidate in path.parent.iterdir():
                if candidate == path or candidate.suffix != ".json" or "manifest" not in candidate.name:
                    continue
                if candidate.is_symlink() or not candidate.is_file():
                    raise ArtifactError("predecessor chain contains a nonregular candidate")
                if hashlib.sha256(candidate.read_bytes()).hexdigest() == manifest["predecessor_sha256"]:
                    predecessor_matches.append(candidate)
            if len(predecessor_matches) != 1:
                raise ArtifactError("predecessor chain does not resolve to exactly one sibling manifest")
            predecessor = load_protocol_manifest(predecessor_matches[0])
            expected_stage = _PILOT_STAGES[_PILOT_STAGES.index(stage) - 1]
            if (
                predecessor["stage"] != expected_stage
                or predecessor["revision"] != revision
                or predecessor["implementation_sha"] != manifest["implementation_sha"]
                or predecessor["config_sha256"] != manifest["config_sha256"]
                or predecessor["p3_gate_sha256"] != manifest["p3_gate_sha256"]
                or predecessor["seed_manifest_sha256"] != manifest["seed_manifest_sha256"]
            ):
                raise ArtifactError("predecessor chain identity differs from the current stage")
    else:
        seed_manifest = None
    seen: set[str] = set()
    ordered_keys: list[tuple[int, str]] = []
    for raw in manifest["shards"]:
        row = _closed(raw, _SHARD_KEYS, "shard")
        shard_id = _text(row["shard_id"], "shard_id")
        stack = _text(row["stack_id"], "stack_id")
        if stack not in _STACK_ORDER or not shard_id.startswith(f"{stack}:") or shard_id in seen:
            raise ArtifactError("shard identities must be unique and stack-prefixed")
        seen.add(shard_id)
        ordered_keys.append((_STACK_ORDER[stack], shard_id))
        if row["configuration_hash"] != _configuration_hash(
            manifest["config_sha256"], manifest["parameter_hash"],
        ):
            raise ArtifactError("configuration hash does not bind config and parameter hashes")
        _exact_int(row["seed"], "seed")
        conditions = _sorted_unique_strings(row["condition_ids"], "condition_ids")
        outputs = _sorted_unique_strings(row["output_identities"], "output_identities")
        count = _exact_int(row["episode_count"], "episode_count")
        if count == 0 or count != len(outputs) or count != len(conditions):
            raise ArtifactError("episode_count must equal declared conditions and outputs")
        if not all(output == f"{stack}-{condition}-{row['seed']:08d}" for output, condition in zip(outputs, conditions)):
            raise ArtifactError("shard outputs do not bind stack/condition/seed identities")
    if ordered_keys != sorted(ordered_keys):
        raise ArtifactError("manifest shards are not in canonical P1-P6 order")
    if stage == "revision" and manifest["shards"]:
        raise ArtifactError("revision manifest cannot declare runnable shards")
    if manifest["phase"] == "pilot" and stage != "revision":
        assert seed_manifest is not None
        partition_key = "evaluation_seed_ids" if stage == "final_four" else "tuning_seed_ids"
        expected_seeds = tuple(seed_manifest["partition"][partition_key])
        expected_condition_ids = _FINAL_CONDITIONS if stage == "final_four" else _TUNING_CONDITIONS
        expected_conditions = len(expected_condition_ids)
        by_stack: dict[str, list[dict[str, Any]]] = {}
        for row in manifest["shards"]:
            by_stack.setdefault(row["stack_id"], []).append(row)
        empty_killed_p5 = stage in {"p5_0_01", "p5_0_04"} and not by_stack
        if (not by_stack and not empty_killed_p5) or any(
            tuple(item["seed"] for item in rows) != expected_seeds
            or any(
                item["episode_count"] != expected_conditions
                or tuple(item["condition_ids"]) != expected_condition_ids
                for item in rows
            )
            for rows in by_stack.values()
        ):
            raise ArtifactError("pilot stage shard/condition domain does not match its frozen protocol")
        if stage == "base" and tuple(by_stack) != tuple(_STACK_ORDER):
            raise ArtifactError("base stage must contain all six stacks")
        if stage in {"p5_0_01", "p5_0_04"} and tuple(by_stack) not in {(), ("P5",)}:
            raise ArtifactError("P5 smoothness stage must contain only surviving P5 or be empty")
        expected_hash = hashlib.sha256(canonical_json_bytes(list(expected_condition_ids))).hexdigest()
        if manifest["condition_hash"] != expected_hash:
            raise ArtifactError("condition domain hash differs from the frozen stage")
        if predecessor is not None:
            predecessor_stacks = tuple(dict.fromkeys(
                row["stack_id"] for row in predecessor["shards"]
            ))
            current_stacks = tuple(by_stack)
            if stage == "pd_60_6" and (
                not current_stacks or current_stacks[0] != "P1"
                or any(stack not in predecessor_stacks for stack in current_stacks)
                or current_stacks != tuple(
                    stack for stack in predecessor_stacks if stack in current_stacks
                )
            ):
                raise ArtifactError("PD survivor domain must be a P1-led ordered subset of base")
            if stage in {"pd_100_10", "ik_0_001", "ik_0_05"} and current_stacks != predecessor_stacks:
                raise ArtifactError("adaptive survivor domain changed after base qualification")
            if stage == "p5_0_01" and current_stacks != (("P5",) if "P5" in predecessor_stacks else ()):
                raise ArtifactError("P5 stage does not match the frozen base-survivor domain")
            if stage == "p5_0_04" and current_stacks != predecessor_stacks:
                raise ArtifactError("P5 stage domain changed between scalar candidates")
            previous_vector = predecessor["parameter_vector"]
            if stage == "ik_0_05" and manifest["parameter_vector"]["pd"] != previous_vector["pd"]:
                raise ArtifactError("selected PD changed between IK candidates")
            if stage == "p5_0_04" and (
                manifest["parameter_vector"]["pd"] != previous_vector["pd"]
                or manifest["parameter_vector"]["ik"] != previous_vector["ik"]
            ):
                raise ArtifactError("selected PD/IK changed between P5 candidates")
    elif manifest["phase"] == "pilot":
        expected_hash = hashlib.sha256(canonical_json_bytes(list(_TUNING_CONDITIONS))).hexdigest()
        if manifest["condition_hash"] != expected_hash:
            raise ArtifactError("condition domain hash differs from the frozen revision")
    return manifest


def iter_manifest(path: Path) -> Iterator[ShardSpec]:
    manifest = load_protocol_manifest(Path(path))
    rows = sorted(manifest["shards"], key=lambda row: (_STACK_ORDER[row["stack_id"]], row["shard_id"]))
    for row in rows:
        yield ShardSpec(
            row["shard_id"], row["stack_id"], row["configuration_hash"], row["seed"],
            tuple(row["condition_ids"]), row["episode_count"], tuple(row["output_identities"]),
        )


_SEED_MANIFEST_KEYS = frozenset({
    "schema_version", "study_id", "phase", "revision", "rng_algorithm",
    "rng_root", "partition", "candidate_count", "accepted_count",
    "rejections", "scenarios",
})
_SEED_SCENARIO_KEYS = frozenset({
    "seed", "proposal_index", "q0", "initial_target", "one_move_path",
    "two_move_path", "stationary_path", "scenario_sha256",
})
_SEED_REJECTION_KEYS = frozenset({"candidate_seed", "proposal_index", "reason"})


def load_seed_manifest(path: Path) -> dict[str, Any]:
    value = load_canonical_json(path, _SEED_MANIFEST_KEYS)
    if _exact_int(value["schema_version"], "schema_version") != 1 or value["study_id"] != STUDY_ID or value["phase"] != "pilot":
        raise ArtifactError("seed manifest identity is invalid")
    _exact_int(value["revision"], "revision")
    if value["rng_algorithm"] != "PCG64_SHA256_NAMESPACED_V1":
        raise ArtifactError("seed manifest RNG contract is invalid")
    _hash(value["rng_root"], "rng_root")
    partition = _closed(value["partition"], frozenset({"tuning_seed_ids", "evaluation_seed_ids"}), "pilot partition")
    tuning = tuple(_exact_int(item, "tuning seed") for item in partition["tuning_seed_ids"])
    evaluation = tuple(_exact_int(item, "evaluation seed") for item in partition["evaluation_seed_ids"])
    if tuning != tuple(sorted(set(tuning))) or evaluation != tuple(sorted(set(evaluation))) or len(tuning) != 4 or len(evaluation) != 4 or set(tuning) & set(evaluation):
        raise ArtifactError("pilot seed partition must contain two disjoint sorted four-seed sets")
    candidate_count = _exact_int(value["candidate_count"], "candidate_count")
    accepted_count = _exact_int(value["accepted_count"], "accepted_count")
    if not isinstance(value["rejections"], list) or not isinstance(value["scenarios"], list):
        raise ArtifactError("seed manifest rows must be arrays")
    rejection_keys: list[tuple[int, int]] = []
    for raw in value["rejections"]:
        row = _closed(raw, _SEED_REJECTION_KEYS, "seed rejection")
        key = (_exact_int(row["candidate_seed"], "candidate_seed"), _exact_int(row["proposal_index"], "proposal_index"))
        _text(row["reason"], "rejection reason")
        rejection_keys.append(key)
    if rejection_keys != sorted(set(rejection_keys)):
        raise ArtifactError("seed rejections must be sorted and unique")
    scenario_seeds: list[int] = []
    for raw in value["scenarios"]:
        row = _closed(raw, _SEED_SCENARIO_KEYS, "seed scenario")
        scenario_seeds.append(_exact_int(row["seed"], "scenario seed"))
        _exact_int(row["proposal_index"], "proposal_index")
        for key in ("q0", "initial_target", "one_move_path", "two_move_path", "stationary_path"):
            if not isinstance(row[key], list):
                raise ArtifactError(f"scenario {key} must be an array")
        digest = _hash(row["scenario_sha256"], "scenario_sha256")
        if hashlib.sha256(canonical_json_bytes({key: item for key, item in row.items() if key != "scenario_sha256"}, newline=False)).hexdigest() != digest:
            raise ArtifactError("scenario hash does not bind its exact scenario fields")
    if scenario_seeds != sorted(set(scenario_seeds)) or set(scenario_seeds) != set(tuning) | set(evaluation):
        raise ArtifactError("seed scenarios do not exactly cover the pilot partition")
    if accepted_count != len(scenario_seeds) or candidate_count != accepted_count + len(rejection_keys):
        raise ArtifactError("seed candidate accounting is inconsistent")
    return value


def _publish_identical_or_create(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise FileExistsError(f"immutable artifact conflicts: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_create_only(path, payload)
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare_manifest(
    stage: str,
    predecessor: Path | None,
    destination: Path,
    config_path: Path,
    gate_path: Path,
    *,
    implementation_sha: str | None = None,
) -> Path:
    """Publish the first runnable pilot manifest without executing physics.

    Later adaptive stages deliberately remain unavailable until their predecessor
    evidence can mechanically determine survivors and selected parameters.
    """
    if stage not in {"revision", "base"} or (stage == "revision") != (predecessor is None):
        raise ArtifactError("revision is the sole no-predecessor preparation")
    destination = Path(destination)
    config_path, gate_path = Path(config_path), Path(gate_path)
    if not config_path.is_file() or not gate_path.is_file():
        raise ArtifactError("manifest preparation requires regular config and P3-gate files")
    if implementation_sha is None:
        implementation_sha = _git(Path(__file__).resolve().parents[3], "rev-parse", "HEAD").decode().strip()
    _hash(implementation_sha, "implementation_sha", _GIT_SHA)
    from dataclasses import asdict as dataclass_dict
    from . import evaluate, timing
    from .contracts import load_config

    config = load_config(config_path)
    seed_path = destination.with_name("pilot-seeds.json")
    if stage == "revision":
        scenarios = [evaluate.generate_scenario(seed, config) for seed in range(config.pilot.seed_count)]
        rejections = []
        scenario_rows = []
        for record in scenarios:
            accepted = next(item for item in record.proposals if item.disposition.value == "ACCEPTED")
            for proposal in record.proposals:
                if proposal.disposition.value != "ACCEPTED":
                    rejections.append({
                        "candidate_seed": record.scenario.seed,
                        "proposal_index": proposal.proposal_index,
                        "reason": proposal.disposition.value,
                    })
            scenario = record.scenario
            scenario_row = {
                "seed": scenario.seed, "proposal_index": accepted.proposal_index,
                "q0": scenario.q0.tolist(), "initial_target": scenario.initial_target.tolist(),
                "one_move_path": scenario.one_move_path.tolist(),
                "two_move_path": scenario.two_move_path.tolist(),
                "stationary_path": scenario.stationary_path.tolist(),
            }
            scenario_rows.append(scenario_row | {
                "scenario_sha256": hashlib.sha256(canonical_json_bytes(scenario_row, newline=False)).hexdigest(),
            })
        seed_manifest = {
            "schema_version": 1, "study_id": STUDY_ID, "phase": "pilot", "revision": 1,
            "rng_algorithm": "PCG64_SHA256_NAMESPACED_V1",
            "rng_root": hashlib.sha256(f"{STUDY_ID}:pilot:r1".encode()).hexdigest(),
            "partition": {"tuning_seed_ids": [0, 1, 2, 3], "evaluation_seed_ids": [4, 5, 6, 7]},
            "candidate_count": len(scenario_rows) + len(rejections),
            "accepted_count": len(scenario_rows),
            "rejections": sorted(rejections, key=lambda row: (row["candidate_seed"], row["proposal_index"])),
            "scenarios": sorted(scenario_rows, key=lambda row: row["seed"]),
        }
        seed_payload = canonical_json_bytes(seed_manifest)
        predecessor_sha256 = None
        manifest_stage = "revision"
    else:
        assert predecessor is not None
        predecessor = Path(predecessor)
        prior = load_protocol_manifest(predecessor)
        if prior["stage"] != "revision" or prior["shards"] or prior["implementation_sha"] != implementation_sha:
            raise ArtifactError("base preparation requires the exact empty revision predecessor")
        seed_path = predecessor.with_name("pilot-seeds.json")
        seed_payload = seed_path.read_bytes()
        seed_manifest = load_seed_manifest(seed_path)
        predecessor_sha256 = hashlib.sha256(predecessor.read_bytes()).hexdigest()
        manifest_stage = "base"
    condition_ids = tuple(sorted(
        f"tune-{rate:02d}-{latency:03d}-{moves}"
        for rate, latency, moves in config.pilot.tuning_conditions
    ))
    configuration_hash = evaluate.sha256_json(timing.scheduler_config(config))
    parameter = evaluate.pilot_candidates()[0]
    shards = []
    if stage == "base":
        for stack in ("P1", "P2", "P3", "P4", "P5", "P6"):
            for index, seed in enumerate(seed_manifest["partition"]["tuning_seed_ids"]):
                outputs = sorted(f"{stack}-{condition_id}-{seed:08d}" for condition_id in condition_ids)
                shards.append({
                    "shard_id": f"{stack}:base:{index:03d}", "stack_id": stack,
                    "configuration_hash": configuration_hash, "seed": seed,
                    "condition_ids": list(condition_ids), "episode_count": len(condition_ids),
                    "output_identities": outputs,
                })
    config_digest = hashlib.sha256(config_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1, "study_id": STUDY_ID, "phase": "pilot", "revision": 1,
        "stage": manifest_stage, "implementation_sha": implementation_sha,
        "predecessor_sha256": predecessor_sha256, "config_sha256": config_digest,
        "p3_gate_sha256": hashlib.sha256(gate_path.read_bytes()).hexdigest(),
        "seed_manifest_sha256": hashlib.sha256(seed_payload).hexdigest(),
        "parameter_vector": dict(parameter.parameter_vector), "parameter_hash": parameter.parameter_hash,
        "scenario_generator_hash": hashlib.sha256(Path(evaluate.__file__).read_bytes()).hexdigest(),
        "condition_hash": hashlib.sha256(canonical_json_bytes(list(condition_ids))).hexdigest(),
        "metric_hash": hashlib.sha256(canonical_json_bytes(dataclass_dict(config.metrics))).hexdigest(),
        "gate_hash": hashlib.sha256(canonical_json_bytes(dataclass_dict(config.thresholds))).hexdigest(),
        "resource_limits": dataclass_dict(config.resources), "shards": shards, "state": "READY",
    }
    manifest_payload = canonical_json_bytes(manifest)
    if stage == "revision":
        _publish_identical_or_create(seed_path, seed_payload)
        load_seed_manifest(seed_path)
    _publish_identical_or_create(destination, manifest_payload)
    load_protocol_manifest(destination)
    return destination


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
    rollout_count: int | None = None,
    revision: int = 1,
    confirmation_wave: int = 1,
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
    if revision not in (1, 2):
        raise ArtifactError("resource revision must be 1 or 2")
    if confirmation_wave not in (1, 2):
        raise ArtifactError("confirmation wave must be 1 or 2")
    if rollout_count is None:
        rollout_count = PILOT_MAX_SHARD_ROLLOUTS if stage == "pilot" else CONFIRMATION_WAVE_ROLLOUTS
    rollout_count = _exact_int(rollout_count, "rollout_count")
    if rollout_count == 0:
        raise ArtifactError("rollout_count must be positive")
    if stage == "pilot" and rollout_count > PILOT_REVISION_ROLLOUTS:
        raise ArtifactError("rollout_count exceeds the pilot revision rollout ceiling")
    if stage == "confirmation" and rollout_count > CONFIRMATION_WAVE_ROLLOUTS:
        raise ArtifactError("rollout_count exceeds the confirmation wave rollout ceiling")
    reserved_bytes = rollout_count * ROLLOUT_RESERVATION_BYTES + PHASE_ALLOWANCE_BYTES
    if reserved_bytes > PASS_LIMIT_BYTES:
        raise ArtifactError("next autonomous pass exceeds 10 GiB")
    if config is not None:
        resources = getattr(config, "resources", None)
        if resources is None or asdict(resources) != _RESOURCE_LIMITS:
            raise ArtifactError("configuration resource ceilings differ from the frozen contract")
    temp_cap = 32 * MIB
    quarantine_cap = 64 * MIB
    wall_cap = (8 if stage == "pilot" else 24) * 3600
    cpu_cap = (80 if stage == "pilot" else 240) * 3600
    reasons: list[str] = []
    phase_cap = PILOT_REVISION_LIMIT_BYTES if stage == "pilot" else CONFIRMATION_LIMIT_BYTES
    if values["retained_bytes"] + reserved_bytes > phase_cap:
        reasons.append("PHASE_BYTES_EXCEEDED")
    if values["temp_bytes"] > temp_cap:
        reasons.append("TEMP_BYTES_EXCEEDED")
    if values["quarantine_bytes"] > quarantine_cap:
        reasons.append("QUARANTINE_BYTES_EXCEEDED")
    if values["free_bytes"] < reserved_bytes:
        reasons.append("INSUFFICIENT_FREE_BYTES")
    if values["wall_seconds"] > wall_cap:
        reasons.append("WALL_TIME_EXCEEDED")
    if values["cpu_seconds"] > cpu_cap:
        reasons.append("CPU_TIME_EXCEEDED")
    closed = tuple(sorted(set(reasons)))
    assert set(closed) <= _RESOURCE_REASONS
    return ResourceDisposition(
        1, STUDY_ID, stage, revision, values["retained_bytes"], values["temp_bytes"],
        values["quarantine_bytes"], values["free_bytes"], reserved_bytes,
        values["wall_seconds"], values["cpu_seconds"], 3600,
        "ALLOW" if not closed else "REFUSE", closed,
    )


def _git(root: Path, *arguments: str) -> bytes:
    environment = {
        "PATH": os.environ.get("PATH", ""), "LANG": "C", "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    try:
        return subprocess.run(
            [
                "git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null",
                "-c", "core.fsmonitor=false", *arguments,
            ],
            cwd=root, env=environment, check=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise ImplementationDriftError(exc.stderr.decode("utf-8", "replace").strip()) from exc


@dataclass(frozen=True)
class ImplementationSnapshot:
    root: Path
    implementation_sha: str
    owned_paths: tuple[Path, ...]
    committed_files: tuple[tuple[str, str, str], ...]

    @classmethod
    def capture(cls, root: Path, implementation_sha: str, owned_paths: Sequence[Path]) -> "ImplementationSnapshot":
        root = Path(root).resolve()
        _hash(implementation_sha, "implementation_sha", _GIT_SHA)
        paths = tuple(Path(item) for item in owned_paths)
        if not paths or any(item.is_absolute() or ".." in item.parts for item in paths):
            raise ImplementationDriftError("owned paths must be nonempty root-relative paths")
        _git(root, "cat-file", "-e", f"{implementation_sha}^{{commit}}")
        tree = _git(root, "ls-tree", "-r", "-z", implementation_sha, "--", *map(str, paths))
        committed_rows: list[tuple[str, str, str]] = []
        for encoded in tree.split(b"\0"):
            if not encoded:
                continue
            metadata, encoded_name = encoded.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split(" ")
            name = encoded_name.decode("utf-8")
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ImplementationDriftError(f"implementation tree contains a nonregular entry: {name}")
            payload = _git(root, "cat-file", "blob", object_id)
            committed_rows.append((name, mode, hashlib.sha256(payload).hexdigest()))
        committed = tuple(sorted(committed_rows))
        if not committed:
            raise ImplementationDriftError("implementation commit contains no owned files")
        return cls(root, implementation_sha, paths, committed)

    def _current(self) -> tuple[tuple[str, str, str], ...]:
        expected_names = tuple(row[0] for row in self.committed_files)
        indexed = tuple(sorted(filter(None, _git(
            self.root, "ls-files", "--cached", "-z", "--", *map(str, self.owned_paths),
        ).decode("utf-8").split("\0"))))
        if indexed != expected_names:
            raise ImplementationDriftError("tracked implementation inventory differs from bound commit")
        current = _descriptor_implementation_inventory(self.root, self.owned_paths)
        if tuple(row[0] for row in current) != expected_names:
            raise ImplementationDriftError("filesystem implementation inventory differs from bound commit")
        return current

    def validate_before(self) -> "ImplementationSnapshot":
        if self._current() != self.committed_files:
            raise ImplementationDriftError("tracked implementation bytes differ from bound commit")
        return self

    def validate_after(self, before: "ImplementationSnapshot | None" = None) -> "ImplementationSnapshot":
        self.validate_before()
        if before is not None and before != self:
            raise ImplementationDriftError("implementation snapshot changed during operation")
        return self


def _implementation_read_boundary(_path: Path) -> None:
    """Fault-injection seam after path identity capture and before descriptor open."""


def _read_implementation_file(
    directory_descriptor: int, name: str, display_path: Path,
) -> tuple[str, str]:
    before = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise ImplementationDriftError(f"implementation inventory contains nonregular entry: {display_path}")
    _implementation_read_boundary(display_path)
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        dir_fd=directory_descriptor,
    )
    try:
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ImplementationDriftError(f"implementation file identity changed: {display_path}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after_fd = os.fstat(descriptor)
        after_path = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if (
            (after_fd.st_dev, after_fd.st_ino) != (opened.st_dev, opened.st_ino)
            or (after_path.st_dev, after_path.st_ino) != (opened.st_dev, opened.st_ino)
            or after_fd.st_size != opened.st_size
        ):
            raise ImplementationDriftError(f"implementation file changed during read: {display_path}")
        return "100755" if opened.st_mode & stat.S_IXUSR else "100644", digest.hexdigest()
    finally:
        os.close(descriptor)


def _descriptor_implementation_inventory(
    root: Path, owned_paths: Sequence[Path],
) -> tuple[tuple[str, str, str], ...]:
    result: dict[str, tuple[str, str]] = {}

    def walk(directory_descriptor: int, relative: Path) -> None:
        for name in sorted(os.listdir(directory_descriptor)):
            display = relative / name
            value = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            if stat.S_ISDIR(value.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_descriptor,
                )
                try:
                    opened = os.fstat(child)
                    if (value.st_dev, value.st_ino) != (opened.st_dev, opened.st_ino):
                        raise ImplementationDriftError(f"implementation directory identity changed: {display}")
                    walk(child, display)
                    after = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
                    if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
                        raise ImplementationDriftError(f"implementation directory changed during walk: {display}")
                finally:
                    os.close(child)
            elif stat.S_ISREG(value.st_mode):
                key = display.as_posix()
                if key in result:
                    raise ImplementationDriftError(f"implementation path overlaps another owned path: {display}")
                result[key] = _read_implementation_file(directory_descriptor, name, root / display)
            else:
                raise ImplementationDriftError(f"implementation inventory contains nonregular entry: {display}")

    for relative in owned_paths:
        parent = open_directory_chain(root / relative.parent, create=False)
        try:
            value = os.stat(relative.name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISDIR(value.st_mode):
                child = os.open(
                    relative.name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent,
                )
                try:
                    opened = os.fstat(child)
                    if (value.st_dev, value.st_ino) != (opened.st_dev, opened.st_ino):
                        raise ImplementationDriftError(f"implementation root identity changed: {relative}")
                    walk(child, relative)
                    after = os.stat(relative.name, dir_fd=parent, follow_symlinks=False)
                    if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
                        raise ImplementationDriftError(f"implementation root changed during walk: {relative}")
                finally:
                    os.close(child)
            elif stat.S_ISREG(value.st_mode):
                result[relative.as_posix()] = _read_implementation_file(parent, relative.name, root / relative)
            else:
                raise ImplementationDriftError(f"implementation inventory contains nonregular entry: {relative}")
        except FileNotFoundError as exc:
            raise ImplementationDriftError(f"implementation inventory entry is absent: {relative}") from exc
        finally:
            os.close(parent)
    return tuple((name, *result[name]) for name in sorted(result))


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
    scenario_sha256: str
    max_bytes: int = ROLLOUT_RESERVATION_BYTES

    def __post_init__(self) -> None:
        _text(self.rollout_id, "rollout_id")
        if self.stack_id not in _STACK_ORDER:
            raise ArtifactError("invalid stack_id")
        _exact_int(self.seed, "seed")
        _text(self.condition_id, "condition_id")
        for name in ("configuration_hash", "protocol_sha256", "source_sha256", "scenario_sha256"):
            _hash(getattr(self, name), name)
        _exact_int(self.max_bytes, "max_bytes")


def _directory_bytes(path: Path) -> int:
    total = 0
    for entry in path.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise ArtifactError(f"unexpected rollout entry: {entry.name}")
        total += entry.stat().st_size
    return total


def _validate_declared_metrics(metrics: Mapping[str, object], spec: RolloutSpec) -> None:
    bindings = (
        ("stack_id", spec.stack_id), ("condition_id", spec.condition_id),
        ("seed", spec.seed), ("protocol_sha256", spec.protocol_sha256),
        ("source_sha256", spec.source_sha256),
        ("scenario_identity_sha256", spec.scenario_sha256),
    )
    for key, expected in bindings:
        if metrics.get(key) != expected:
            raise ArtifactError(f"rollout {key} differs from its mandatory declaration")


def _validate_record_binding(record: RolloutRecord, artifact: RolloutArtifact, spec: RolloutSpec) -> None:
    if artifact.path.name != spec.rollout_id or artifact.metadata.seed != spec.seed:
        raise ArtifactError("rollout identity/seed does not match its declaration")
    if artifact.metadata.task_config_hash != spec.configuration_hash:
        raise ArtifactError("rollout configuration hash differs from shard declaration")
    _validate_declared_metrics(record.metrics, spec)
    _validate_declared_metrics(artifact.metrics, spec)
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


def _renameat_directory_noreplace(
    source_descriptor: int, source_name: str,
    destination_descriptor: int, destination_name: str,
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    encoded_source, encoded_destination = os.fsencode(source_name), os.fsencode(destination_name)
    if hasattr(library, "renameatx_np"):
        result = library.renameatx_np(
            source_descriptor, ctypes.c_char_p(encoded_source),
            destination_descriptor, ctypes.c_char_p(encoded_destination), 0x00000004,
        )
    elif hasattr(library, "renameat2"):
        result = library.renameat2(
            source_descriptor, ctypes.c_char_p(encoded_source),
            destination_descriptor, ctypes.c_char_p(encoded_destination), 0x00000001,
        )
    else:
        raise ArtifactError("platform lacks a directory no-replace rename primitive")
    if result != 0:
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise ArtifactError("rollout destination already exists")
        raise ArtifactError(f"no-replace rollout publication failed: {os.strerror(error)}")


def _rename_directory_noreplace(source: Path, destination: Path) -> None:
    source, destination = Path(source), Path(destination)
    source_parent = open_directory_chain(source.parent, create=False)
    destination_parent = open_directory_chain(destination.parent, create=False)
    try:
        _renameat_directory_noreplace(
            source_parent, source.name, destination_parent, destination.name,
        )
    finally:
        os.close(destination_parent)
        os.close(source_parent)


def publish_or_validate_skip(record: RolloutRecord, destination: Path, spec: RolloutSpec) -> str:
    destination = Path(destination)
    if destination.name != spec.rollout_id:
        raise ArtifactError("destination name differs from rollout specification")
    _validate_declared_metrics(record.metrics, spec)
    parent_descriptor = open_directory_chain(destination.parent, create=True)
    held = None
    try:
        try:
            existing = os.stat(destination.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode):
                raise ArtifactError("rollout destination is a symlink")
            if not stat.S_ISDIR(existing.st_mode):
                raise ArtifactError("rollout destination is not a directory")
            existing_path = destination
            artifact = validate_rollout(existing_path)
            if _directory_bytes(existing_path) > spec.max_bytes:
                raise ArtifactError("rollout exceeds its declared byte ceiling")
            _validate_record_binding(record, artifact, spec)
            return "validated-and-skipped"
        held = create_temporary_directory(parent_descriptor, f".{destination.name}.publish-")
        staging_root = destination.parent / held.name
        if not path_matches_directory(staging_root, held.identity):
            raise ArtifactError("rollout staging directory identity drifted")
        staged = RolloutWriter(staging_root, destination.name).write(record)
        if not path_matches_directory(staging_root, held.identity):
            raise ArtifactError("rollout staging directory identity drifted during write")
        artifact = validate_rollout(staged)
        if _directory_bytes(staged) > spec.max_bytes:
            raise ArtifactError("rollout exceeds its declared byte ceiling")
        _validate_record_binding(record, artifact, spec)
        _renameat_directory_noreplace(
            held.descriptor, destination.name, parent_descriptor, destination.name,
        )
        os.fsync(parent_descriptor)
    finally:
        if held is not None:
            cleanup_exact_directory(
                parent_descriptor, held.descriptor, held.identity, held.name,
            )
            os.close(held.descriptor)
        os.close(parent_descriptor)
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


_ROLLOUT_WIRE_KEYS = frozenset({
    "metadata", "config", "metrics", "events", "observations", "actions",
    "control_references", "summary", "replay",
})
_PLOT_ROW_KEYS = frozenset({
    "stack_id", "seed", "condition_id", "policy_hz", "latency_ms", "move_count",
    "fault", "recovery_s", "error_m", "jerk_p95", "age_p95_s", "timeline", "valid",
})
_PLOT_NAMES = (
    "recovery-vs-latency.svg", "tracking-error-vs-rate.svg", "joint-jerk.svg",
    "action-age.svg", "timeline.svg",
)


def _digest_state(value: object) -> str:
    return hashlib.sha256(canonical_state_bytes(value)).hexdigest()


def _rollout_wire(artifact: RolloutArtifact, replay: ReplayResult) -> dict[str, object]:
    return _wire({
        "metadata": artifact.metadata, "config": artifact.config,
        "metrics": artifact.metrics, "events": artifact.events,
        "observations": artifact.observations, "actions": artifact.actions,
        "control_references": artifact.control_references,
        "summary": artifact.summary, "replay": replay,
    })  # type: ignore[return-value]


def _condition_metadata(condition_id: str) -> tuple[int, int, int, str]:
    match = re.fullmatch(r"core-(05|10|20)-(000|100|300|700)-([12])", condition_id)
    if match is not None:
        return int(match.group(1)), int(match.group(2)), int(match.group(3)), "NONE"
    special = {
        "probe-drop": (10, 300, 2, "DROP"),
        "probe-out-of-order": (10, 300, 2, "OUT_OF_ORDER"),
        "control-stationary": (10, 300, 0, "STATIONARY_CONTROL"),
    }
    try:
        return special[condition_id]
    except KeyError as exc:
        raise ArtifactError("condition identity is outside the frozen domain") from exc


def raw_evidence_from_rollout(
    rollout_path: Path,
    *,
    revision: int,
    variant_id: str,
    anchor_id: str,
    candidate_id: str,
    rng_namespace: str,
    policy_hz: int,
    latency_ms: int,
    move_count: int,
    fault: str,
) -> dict[str, object]:
    """Derive one lossless raw row only from a validated immutable rollout."""
    artifact = validate_rollout(Path(rollout_path))
    replay = replay_rollout(Path(rollout_path))
    if not replay.frames or canonical_state_bytes(replay.frames[-1].state) != canonical_state_bytes(replay.final_state):
        raise ArtifactError("rollout replay does not reconstruct its terminal state")
    metrics = artifact.metrics
    stack_id = metrics.get("stack_id")
    condition_id = metrics.get("condition_id")
    seed = artifact.metadata.seed
    if stack_id not in _STACK_ORDER or not isinstance(condition_id, str):
        raise ArtifactError("rollout lacks its exact stack/condition identity")
    derived_condition = _condition_metadata(condition_id)
    if derived_condition != (
        policy_hz, latency_ms, move_count, fault,
    ):
        raise ArtifactError("caller condition metadata differs from the retained condition identity")
    for value, name in (
        (revision, "revision"), (policy_hz, "policy_hz"), (latency_ms, "latency_ms"),
        (move_count, "move_count"),
    ):
        _exact_int(value, name)
    for value, name in (
        (variant_id, "variant_id"), (anchor_id, "anchor_id"),
        (candidate_id, "candidate_id"), (rng_namespace, "rng_namespace"),
        (fault, "fault"),
    ):
        _text(value, name)
    raw_tick = metrics.get("raw_500hz")
    if not isinstance(raw_tick, Mapping) or not isinstance(raw_tick.get("tick"), tuple) or not raw_tick["tick"]:
        raise ArtifactError("rollout lacks lossless ordered raw tick evidence")
    ticks = tuple(raw_tick["tick"])
    if any(type(item) is not int for item in ticks) or ticks != tuple(range(ticks[0], ticks[-1] + 1)):
        raise ArtifactError("raw rollout ticks are not one complete ordered domain")
    required_metrics = ("recovery_s", "final_error_m", "jerk_p95", "age_p95_s", "valid")
    if any(key not in metrics for key in required_metrics):
        raise ArtifactError("rollout lacks plot-ready metric inputs")
    rollout = _rollout_wire(artifact, replay)
    scenario_record = metrics.get("scenario_record")
    scenario_hash = metrics.get("scenario_identity_sha256")
    _hash(scenario_hash, "scenario_identity_sha256")
    protocol_hash = _hash(metrics.get("protocol_sha256"), "protocol_sha256")
    source_hash = _hash(metrics.get("source_sha256"), "source_sha256")
    output_value = {
        key: rollout[key]
        for key in ("metrics", "events", "observations", "actions", "control_references", "summary")
    }
    status = artifact.metadata.status
    disposition = "SUCCESS" if status == "pass" else "FAILED"
    row = {
        "schema_version": 1, "revision": revision, "stack_id": stack_id,
        "condition_id": condition_id, "variant_id": variant_id,
        "scene_id": f"scene-{seed:08d}", "episode_id": artifact.path.name,
        "anchor_id": anchor_id, "candidate_id": candidate_id, "seed": seed,
        "rng_namespace": rng_namespace, "tick_start": ticks[0], "tick_end": ticks[-1],
        "units": {"position": "m", "time": "ns"},
        "frames": {"target": "world"}, "validity": "VALID", "missingness": None,
        "terminal_state": "COMPLETE",
        "protocol_sha256": protocol_hash, "source_sha256": source_hash,
        "scenario_sha256": scenario_hash,
        "config_sha256": _digest_state(artifact.config),
        "code_sha256": hashlib.sha256(artifact.metadata.git_sha.encode("ascii")).hexdigest(),
        "dependency_sha256": _digest_state(artifact.metadata.dependency_versions),
        "input_sha256": _digest_state((artifact.config, scenario_record, scenario_hash)),
        "output_sha256": _digest_state(output_value),
        "replay_sha256": _digest_state(rollout["replay"]),
        "bundle_sha256": _digest_state(rollout), "disposition": disposition,
        "reason": "NONE" if disposition == "SUCCESS" else "SCIENTIFIC_FAILURE",
        "analysis_included": True, "failure": None, "rollout": rollout,
        "plot": {
            "stack_id": stack_id, "seed": seed, "condition_id": condition_id,
            "policy_hz": derived_condition[0], "latency_ms": derived_condition[1],
            "move_count": derived_condition[2], "fault": derived_condition[3],
            "recovery_s": float(metrics["recovery_s"]),
            "error_m": float(metrics["final_error_m"]),
            "jerk_p95": float(metrics["jerk_p95"]),
            "age_p95_s": float(metrics["age_p95_s"]),
            "timeline": [float(item) for item in raw_tick["error_m"]],
            "valid": bool(metrics["valid"]),
        },
    }
    return row


def _failed_attempt_input_sha256(
    failure: Mapping[str, object], *, protocol_sha256: str, source_sha256: str,
    scenario_sha256: str, config_sha256: str, code_sha256: str,
    dependency_sha256: str,
) -> str:
    return _digest_state({
        "protocol_sha256": protocol_sha256, "source_sha256": source_sha256,
        "scenario_sha256": scenario_sha256, "config_sha256": config_sha256,
        "code_sha256": code_sha256, "dependency_sha256": dependency_sha256,
        "command_sha256": failure["command_sha256"],
        "details_sha256": failure["details_sha256"],
    })


def raw_evidence_from_failure_disposition(
    value: Mapping[str, object], *, variant_id: str, anchor_id: str,
    candidate_id: str, rng_namespace: str, protocol_sha256: str,
    source_sha256: str, scenario_sha256: str, config_sha256: str,
    code_sha256: str, dependency_sha256: str,
) -> dict[str, object]:
    """Retain one typed absent-output disposition without fabricating a rollout."""
    failure = _failure_row(dict(value))
    condition_id = str(failure["condition_id"])
    _condition_metadata(condition_id)
    for item, name in (
        (variant_id, "variant_id"), (anchor_id, "anchor_id"),
        (candidate_id, "candidate_id"), (rng_namespace, "rng_namespace"),
    ):
        _text(item, name)
    identities = {
        name: _hash(item, name) for name, item in (
            ("protocol_sha256", protocol_sha256), ("source_sha256", source_sha256),
            ("scenario_sha256", scenario_sha256), ("config_sha256", config_sha256),
            ("code_sha256", code_sha256), ("dependency_sha256", dependency_sha256),
        )
    }
    input_sha256 = _failed_attempt_input_sha256(failure, **identities)
    disposition = {
        "PROCESS_TIMEOUT": "TIMED_OUT", "CORRUPT_OUTPUT": "CRASHED",
        "MISSING_OUTPUT": "DECLARED_MISSING", "RESOURCE_EXHAUSTION": "EXCLUDED",
    }[str(failure["reason"])]
    seed, stack_id = int(failure["seed"]), str(failure["stack_id"])
    return {
        "schema_version": 1, "revision": int(failure["revision"]),
        "stack_id": stack_id, "condition_id": condition_id,
        "variant_id": variant_id, "scene_id": f"scene-{seed:08d}",
        "episode_id": f"{failure['shard_id']}:{condition_id}:declared-invalid",
        "anchor_id": anchor_id, "candidate_id": candidate_id, "seed": seed,
        "rng_namespace": rng_namespace, "tick_start": 0, "tick_end": 0,
        "units": {"position": "m", "time": "ns"}, "frames": {"target": "world"},
        "validity": "DECLARED_INVALID", "missingness": str(failure["reason"]),
        "terminal_state": disposition, **identities,
        "input_sha256": input_sha256, "output_sha256": None,
        "replay_sha256": None, "bundle_sha256": None, "disposition": disposition,
        "reason": str(failure["reason"]), "analysis_included": False,
        "failure": failure, "rollout": None, "plot": None,
    }


def _sorted_raw_rows(raw_rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return sorted(
        (dict(row) for row in raw_rows),
        key=lambda row: (
            _STACK_ORDER.get(str(row.get("stack_id")), 99), int(row.get("seed", -1)),
            str(row.get("condition_id")), str(row.get("episode_id")),
        ),
    )


def _raw_payload_offsets(
    raw_rows: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], bytes, dict[str, tuple[int, int]]]:
    ordered = _sorted_raw_rows(raw_rows)
    parts: list[bytes] = []
    offsets: dict[str, tuple[int, int]] = {}
    cursor = 0
    for row in ordered:
        episode_id = str(row.get("episode_id"))
        if episode_id in offsets:
            raise ArtifactError("raw episode identities must be unique")
        payload = canonical_json_bytes(row)
        parts.append(payload)
        offsets[episode_id] = (cursor, cursor + len(payload))
        cursor += len(payload)
    return ordered, b"".join(parts), offsets


def _command_output_bytes(row: Mapping[str, object]) -> bytes:
    rollout = row.get("rollout")
    if rollout is None and isinstance(row.get("failure"), Mapping):
        return canonical_state_bytes(row["failure"])
    if not isinstance(rollout, Mapping):
        raise ArtifactError("raw row lacks retained rollout command output")
    return canonical_state_bytes({
        "actions": rollout.get("actions"),
        "control_references": rollout.get("control_references"),
    })


def build_annotated_samples(
    raw_rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    ordered, _, offsets = _raw_payload_offsets(raw_rows)
    groups: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in ordered:
        groups.setdefault(
            (str(row["stack_id"]), str(row["variant_id"]), str(row["condition_id"])), [],
        ).append(row)
    result = []
    for (stack, variant, condition), rows in sorted(groups.items(), key=lambda item: (_STACK_ORDER[item[0][0]], item[0][1:])):
        classes = {
            "WORKING": [row for row in rows if row["disposition"] == "SUCCESS"],
            "NONWORKING": [row for row in rows if row["disposition"] in {"FAILED", "TIMED_OUT", "CRASHED", "DECLARED_MISSING"}],
        }
        for target in ("WORKING", "NONWORKING"):
            eligible = classes[target]
            selected = eligible[0] if eligible else None
            episode_id = str(selected["episode_id"]) if selected else None
            span = offsets[episode_id] if episode_id else None
            result.append({
                "schema_version": 1, "revision": int(rows[0]["revision"]),
                "stack_id": stack, "variant_id": variant, "condition_id": condition,
                "target_class": target, "label": target if selected else "CLASS_NOT_OBSERVED",
                "source_ranges": ([{"start": span[0], "end": span[1]}] if span else []),
                "command_output_sha256": hashlib.sha256(
                    _command_output_bytes(selected) if selected else b"",
                ).hexdigest(),
                "raw_links": ([episode_id] if episode_id else []),
                "denominator": len(rows),
            })
    return tuple(result)


def build_plot_recipes(
    raw_rows: Sequence[Mapping[str, object]], promoted_stacks: Sequence[str],
) -> tuple[dict[str, object], ...]:
    _, raw_payload, _ = _raw_payload_offsets(raw_rows)
    promoted = tuple(dict.fromkeys(promoted_stacks))
    if any(stack not in _STACK_ORDER or stack == "P1" for stack in promoted):
        raise ArtifactError("plot recipes contain an invalid promoted stack")
    stacks = ("P1", *promoted)
    digest = hashlib.sha256(raw_payload).hexdigest()
    axes = {
        "recovery-vs-latency.svg": {"x": "latency_ms", "y": "recovery_s"},
        "tracking-error-vs-rate.svg": {"x": "policy_hz", "y": "error_m"},
        "joint-jerk.svg": {"x": "seed", "y": "jerk_p95"},
        "action-age.svg": {"x": "latency_ms", "y": "age_p95_s"},
        "timeline.svg": {"x": "sample", "y": "error_m"},
    }
    revision_values = {int(row["revision"]) for row in raw_rows}
    if len(revision_values) != 1:
        raise ArtifactError("plot recipe inputs span revisions")
    revision = next(iter(revision_values))
    return tuple({
        "schema_version": 1, "revision": revision, "plot": name,
        "source_sha256": digest,
        "filters": [{"field": "stack_id", "operator": "IN", "values": list(stacks)}],
        "transforms": ["ROLLOUT_METRICS_TO_TASK11_PLOT_ROW"],
        "group_by": ["stack_id"], "order_by": ["stack_id", "seed", "condition_id"],
        "axes": axes[name], "units": {"x": "DECLARED", "y": "DECLARED"},
        "frames": {"target": "world"}, "binning": "NONE", "summary": "RAW",
        "interval": "NONE", "palette": ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"],
        "legend": True, "dimensions": {"width": 640, "height": 400},
        "renderer_version": "TASK11_SVG_V1", "seed": 0,
    } for name in _PLOT_NAMES)


def _task11_svg(
    title: str, x_label: str, y_label: str,
    series: Sequence[tuple[str, Sequence[tuple[float, float]]]],
) -> bytes:
    colors = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf")
    all_points = tuple(point for _, points in series for point in points)
    xs, ys = [item[0] for item in all_points] or [0.0], [item[1] for item in all_points] or [0.0]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400" viewBox="0 0 640 400">', '<rect width="640" height="400" fill="white"/>', f'<text x="20" y="28" font-family="sans-serif" font-size="16">{title}</text>', '<path d="M50 350H620M50 50V350" stroke="#222" fill="none"/>', f'<text x="300" y="390" font-family="sans-serif" font-size="12">{x_label}</text>', f'<text x="8" y="45" font-family="sans-serif" font-size="12">{y_label}</text>']
    for index, (label, points) in enumerate(series):
        ordered = tuple(points)
        if not ordered:
            continue
        coords = " ".join(f"{50 + 550 * ((x - xmin) / (xmax - xmin) if xmax != xmin else 0.5):.3f},{350 - 280 * ((y - ymin) / (ymax - ymin) if ymax != ymin else 0.5):.3f}" for x, y in ordered)
        lines.append(f'<polyline points="{coords}" fill="none" stroke="{colors[index % len(colors)]}" stroke-width="2"/>')
        lines.append(f'<text x="500" y="{60 + 18 * index}" font-family="sans-serif" font-size="12" fill="{colors[index % len(colors)]}">{label}</text>')
    lines.append("</svg>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _render_task11_plots(
    plot_rows: Sequence[Mapping[str, object]], promoted_stacks: Sequence[str],
) -> dict[str, bytes]:
    stacks = tuple(dict.fromkeys(("P1", *promoted_stacks)))
    ordered = tuple(sorted((dict(row) for row in plot_rows if row["valid"]), key=lambda row: (_STACK_ORDER[str(row["stack_id"])], int(row["seed"]), str(row["condition_id"]))))
    keys_by_stack = {stack: {(row["seed"], row["condition_id"]) for row in ordered if row["stack_id"] == stack} for stack in stacks}
    domains = tuple(keys_by_stack[stack] for stack in stacks)
    if not domains[0] or any(domain != domains[0] for domain in domains[1:]):
        raise ArtifactError("plots require one symmetric exact P1/promoted stack domain")
    ordered = tuple(row for row in ordered if row["stack_id"] in stacks)
    specs = (
        (_PLOT_NAMES[0], "Recovery vs latency", "latency (ms)", "recovery (s)", lambda row: (float(row["latency_ms"]), float(row["recovery_s"]))),
        (_PLOT_NAMES[1], "Tracking error vs rate", "policy rate (Hz)", "error (m)", lambda row: (float(row["policy_hz"]), float(row["error_m"]))),
        (_PLOT_NAMES[2], "Joint jerk", "seed", "jerk (rad/s^3)", lambda row: (float(row["seed"]), float(row["jerk_p95"]))),
        (_PLOT_NAMES[3], "Action age", "latency (ms)", "age (s)", lambda row: (float(row["latency_ms"]), float(row["age_p95_s"]))),
    )
    rendered = {name: _task11_svg(title, x_label, y_label, tuple((stack, tuple(transform(row) for row in ordered if row["stack_id"] == stack)) for stack in stacks)) for name, title, x_label, y_label, transform in specs}
    timeline = [row for row in ordered if row["condition_id"] == "core-10-300-2" and row["policy_hz"] == 10 and row["latency_ms"] == 300 and row["move_count"] == 2 and row["fault"] == "NONE" and row["timeline"]]
    keys = sorted({(row["seed"], row["condition_id"]) for row in timeline})
    chosen = next((key for key in keys if all(any(row["stack_id"] == stack and (row["seed"], row["condition_id"]) == key for row in timeline) for stack in stacks)), None)
    if chosen is None:
        raise ArtifactError("timeline requires one shared exact intended condition")
    rendered[_PLOT_NAMES[4]] = _task11_svg("Timeline", "sample", "error (m)", tuple((stack, tuple((float(index), float(value)) for row in timeline if row["stack_id"] == stack and (row["seed"], row["condition_id"]) == chosen for index, value in enumerate(row["timeline"]))) for stack in stacks))
    return rendered


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
        "dependency_sha256", "protocol_sha256", "source_sha256", "scenario_sha256",
        "input_sha256", "output_sha256", "replay_sha256",
        "bundle_sha256", "disposition", "reason", "analysis_included",
        "failure", "rollout", "plot",
    })
    index_keys = frozenset({
        "schema_version", "revision", "stack_id", "variant_id", "condition_id",
        "target_class", "label", "source_ranges", "command_output_sha256",
        "raw_links", "denominator",
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
        disposition = row["disposition"]
        if disposition not in {"SUCCESS", "FAILED", "TIMED_OUT", "CRASHED", "EXCLUDED", "DECLARED_MISSING"}:
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
        for key in ("protocol_sha256", "source_sha256", "scenario_sha256"):
            _hash(row[key], key)
        for key in (
            "config_sha256", "code_sha256", "dependency_sha256", "input_sha256",
            "output_sha256", "replay_sha256", "bundle_sha256",
        ):
            if row[key] is not None:
                _hash(row[key], key)
        complete = disposition in {"SUCCESS", "FAILED"}
        if complete and (
            row["validity"] != "VALID" or row["missingness"] is not None
            or row["terminal_state"] != "COMPLETE" or not row["analysis_included"]
            or any(row[key] is None for key in (
                "config_sha256", "code_sha256", "dependency_sha256", "input_sha256",
                "output_sha256", "replay_sha256", "bundle_sha256",
            ))
        ):
            raise ArtifactError("complete episode disposition contradicts validity or retained evidence")
        if disposition in {"TIMED_OUT", "CRASHED", "DECLARED_MISSING"} and (
            row["validity"] != "DECLARED_INVALID" or row["missingness"] is None
            or row["analysis_included"]
            or any(row[key] is None for key in (
                "config_sha256", "code_sha256", "dependency_sha256", "input_sha256",
            ))
            or any(row[key] is not None for key in (
                "output_sha256", "replay_sha256", "bundle_sha256",
            ))
        ):
            raise ArtifactError("invalid episode disposition contradicts missingness or analysis inclusion")
        if disposition == "EXCLUDED" and (row["analysis_included"] or row["missingness"] is None):
            raise ArtifactError("excluded episode disposition requires a reason and analysis exclusion")
        if (disposition == "SUCCESS") != (row["reason"] == "NONE"):
            raise ArtifactError("episode disposition and reason are inconsistent")
        if not complete:
            failure = _failure_row(row["failure"])
            expected_disposition = {
                "PROCESS_TIMEOUT": "TIMED_OUT", "CORRUPT_OUTPUT": "CRASHED",
                "MISSING_OUTPUT": "DECLARED_MISSING", "RESOURCE_EXHAUSTION": "EXCLUDED",
            }[str(failure["reason"])]
            if (
                row["rollout"] is not None or row["plot"] is not None
                or failure["stack_id"] != row["stack_id"]
                or failure["seed"] != row["seed"]
                or failure["condition_id"] != row["condition_id"]
                or disposition != expected_disposition
                or row["input_sha256"] != _failed_attempt_input_sha256(
                    failure,
                    protocol_sha256=row["protocol_sha256"],
                    source_sha256=row["source_sha256"],
                    scenario_sha256=row["scenario_sha256"],
                    config_sha256=row["config_sha256"],
                    code_sha256=row["code_sha256"],
                    dependency_sha256=row["dependency_sha256"],
                )
            ):
                raise ArtifactError("declared-invalid raw row differs from its retained failure")
            normalized_raw.append(row)
            continue
        if row["failure"] is not None:
            raise ArtifactError("complete raw row cannot retain a failure disposition")
        rollout = _closed(row["rollout"], _ROLLOUT_WIRE_KEYS, "retained rollout")
        plot = _closed(row["plot"], _PLOT_ROW_KEYS, "plot row")
        metadata = rollout["metadata"]
        metrics = rollout["metrics"]
        if not isinstance(metadata, dict) or not isinstance(metrics, dict):
            raise ArtifactError("retained rollout metadata/metrics must be objects")
        raw_tick = metrics.get("raw_500hz")
        if not isinstance(raw_tick, dict) or raw_tick.get("tick") != list(range(start, end + 1)):
            raise ArtifactError("retained raw tick evidence differs from declared range")
        if (
            metadata.get("seed") != row["seed"]
            or metrics.get("stack_id") != row["stack_id"]
            or metrics.get("condition_id") != row["condition_id"]
            or plot["stack_id"] != row["stack_id"]
            or plot["seed"] != row["seed"]
            or plot["condition_id"] != row["condition_id"]
        ):
            raise ArtifactError("retained rollout identity differs from raw evidence row")
        expected_plot = {
            "stack_id": row["stack_id"], "seed": row["seed"],
            "condition_id": row["condition_id"], "policy_hz": plot["policy_hz"],
            "latency_ms": plot["latency_ms"], "move_count": plot["move_count"],
            "fault": plot["fault"], "recovery_s": metrics.get("recovery_s"),
            "error_m": metrics.get("final_error_m"), "jerk_p95": metrics.get("jerk_p95"),
            "age_p95_s": metrics.get("age_p95_s"),
            "timeline": raw_tick.get("error_m"), "valid": metrics.get("valid"),
        }
        if plot != expected_plot:
            raise ArtifactError("plot row does not reconstruct from retained rollout metrics")
        if any(type(plot[key]) is not int for key in ("policy_hz", "latency_ms", "move_count")) or type(plot["valid"]) is not bool:
            raise ArtifactError("plot row integer/boolean fields are not exact")
        if any(not math.isfinite(float(plot[key])) for key in ("recovery_s", "error_m", "jerk_p95", "age_p95_s")) or not isinstance(plot["timeline"], list) or any(not math.isfinite(float(item)) for item in plot["timeline"]):
            raise ArtifactError("plot row numeric fields are not finite")
        output_value = {key: rollout[key] for key in ("metrics", "events", "observations", "actions", "control_references", "summary")}
        expected_hashes = {
            "protocol_sha256": metrics.get("protocol_sha256"),
            "source_sha256": metrics.get("source_sha256"),
            "scenario_sha256": metrics.get("scenario_identity_sha256"),
            "config_sha256": _digest_state(rollout["config"]),
            "code_sha256": hashlib.sha256(str(metadata.get("git_sha", "")).encode("ascii")).hexdigest(),
            "dependency_sha256": _digest_state(metadata.get("dependency_versions")),
            "input_sha256": _digest_state((rollout["config"], metrics.get("scenario_record"), metrics.get("scenario_identity_sha256"))),
            "output_sha256": _digest_state(output_value),
            "replay_sha256": _digest_state(rollout["replay"]),
            "bundle_sha256": _digest_state(rollout),
        }
        if any(row[key] != expected for key, expected in expected_hashes.items()):
            raise ArtifactError("raw evidence digest does not reconstruct from retained rollout")
        replay = rollout["replay"]
        if not isinstance(replay, dict) or not replay.get("frames") or replay["frames"][-1].get("state") != replay.get("final_state"):
            raise ArtifactError("retained replay does not reconstruct its terminal state")
        normalized_raw.append(row)
    normalized_index: list[dict[str, object]] = []
    for source in annotated_index:
        row = _closed(dict(source), index_keys, "annotated index row")
        if _exact_int(row["schema_version"], "schema_version") != 1:
            raise ArtifactError("annotated index schema_version must be 1")
        _exact_int(row["revision"], "revision")
        if row["target_class"] not in {"WORKING", "NONWORKING"} or row["label"] not in {"WORKING", "NONWORKING", "CLASS_NOT_OBSERVED"}:
            raise ArtifactError("annotated index row has invalid closed enum")
        if row["stack_id"] not in _STACK_ORDER:
            raise ArtifactError("annotated index stack_id is invalid")
        _text(row["variant_id"], "variant_id")
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
        if row["label"] != "CLASS_NOT_OBSERVED" and row["label"] != row["target_class"]:
            raise ArtifactError("observed annotation label must equal its target class")
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
    sorted_raw, raw_payload, raw_offsets = _raw_payload_offsets(normalized_raw)
    raw_groups: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in normalized_raw:
        raw_groups.setdefault((str(row["stack_id"]), str(row["variant_id"]), str(row["condition_id"])), []).append(row)
    index_groups: dict[tuple[str, str, str], dict[str, dict[str, object]]] = {}
    for row in normalized_index:
        group = (str(row["stack_id"]), str(row["variant_id"]), str(row["condition_id"]))
        target = str(row["target_class"])
        if target in index_groups.setdefault(group, {}):
            raise ArtifactError("annotated working/nonworking class is duplicated")
        index_groups[group][target] = row
    if set(index_groups) != set(raw_groups) or any(set(rows) != {"WORKING", "NONWORKING"} for rows in index_groups.values()):
        raise ArtifactError("annotated working/nonworking coverage is incomplete")
    for group, rows in raw_groups.items():
        ordered = sorted(rows, key=lambda row: (int(row["seed"]), str(row["episode_id"])))
        classes = {
            "WORKING": [row for row in ordered if row["disposition"] == "SUCCESS"],
            "NONWORKING": [row for row in ordered if row["disposition"] in {"FAILED", "TIMED_OUT", "CRASHED", "DECLARED_MISSING"}],
        }
        for target, eligible in classes.items():
            annotation = index_groups[group][target]
            if annotation["denominator"] != len(ordered):
                raise ArtifactError("annotated sample denominator differs from eligible raw rows")
            if eligible:
                expected_link = [eligible[0]["episode_id"]]
                expected_span = raw_offsets[str(expected_link[0])]
                expected_ranges = [{"start": expected_span[0], "end": expected_span[1]}]
                expected_command = hashlib.sha256(_command_output_bytes(eligible[0])).hexdigest()
                if (
                    annotation["label"] != target
                    or annotation["raw_links"] != expected_link
                    or annotation["source_ranges"] != expected_ranges
                    or annotation["command_output_sha256"] != expected_command
                ):
                    raise ArtifactError("annotated sample does not use the deterministic first eligible raw case")
            elif (
                annotation["label"] != "CLASS_NOT_OBSERVED"
                or annotation["raw_links"] or annotation["source_ranges"]
                or annotation["command_output_sha256"] != hashlib.sha256(b"").hexdigest()
            ):
                raise ArtifactError("absent working/nonworking class must be CLASS_NOT_OBSERVED")
    sorted_index = sorted(normalized_index, key=lambda row: (str(row["stack_id"]), str(row["variant_id"]), str(row["condition_id"]), str(row["target_class"])))
    if tuple(row["plot"] for row in normalized_recipes) != _PLOT_NAMES:
        raise ArtifactError("plot recipes must cover the exact Task11 outputs in order")
    first_filter = normalized_recipes[0]["filters"]
    if not isinstance(first_filter, list) or len(first_filter) != 1 or not isinstance(first_filter[0], dict):
        raise ArtifactError("plot recipe has no closed stack filter")
    stack_values = first_filter[0].get("values")
    if not isinstance(stack_values, list) or not stack_values or stack_values[0] != "P1":
        raise ArtifactError("plot recipe stack filter must begin with P1")
    promoted = tuple(stack_values[1:])
    expected_recipes = build_plot_recipes(sorted_raw, promoted)
    if tuple(normalized_recipes) != expected_recipes:
        raise ArtifactError("plot recipe differs from the closed Task11 reconstruction contract")
    sorted_recipes = list(normalized_recipes)
    plot_rows = [dict(row["plot"]) for row in sorted_raw if row["plot"] is not None]
    payloads = {
        "raw-evidence.jsonl": raw_payload,
        "annotated-samples.jsonl": jsonl(sorted_index),
        "plot-recipes.json": canonical_json_bytes(sorted_recipes),
        "derived-table.json": canonical_json_bytes({"rows": plot_rows}),
    }
    payloads.update(_render_task11_plots(plot_rows, promoted))
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


def _publication_boundary(_name: str) -> None:
    """Fault-injection seam immediately after one durable publication boundary."""


def _read_regular_at(directory_descriptor: int, name: str) -> bytes:
    try:
        value = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise ArtifactError(f"publication entry is unreadable: {name}") from exc
    if not stat.S_ISREG(value.st_mode):
        raise ArtifactError(f"publication entry is not regular: {name}")
    descriptor = os.open(
        name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        dir_fd=directory_descriptor,
    )
    try:
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        if os.fstat(descriptor).st_size != sum(map(len, chunks)):
            raise ArtifactError(f"publication entry changed while reading: {name}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _write_at_create_only(directory_descriptor: int, name: str, payload: bytes) -> None:
    if Path(name).name != name:
        raise ArtifactError("publication filename must be one basename")
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=directory_descriptor,
    )
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _quarantine_partial_publication(
    directory_descriptor: int, payloads: Mapping[str, bytes],
) -> None:
    names = sorted(name for name in os.listdir(directory_descriptor) if name != ".quarantine")
    if not names:
        return
    for name in names:
        if name not in payloads or _read_regular_at(directory_descriptor, name) != payloads[name]:
            raise ArtifactError("ambiguous partial evidence publication")
    try:
        os.mkdir(".quarantine", 0o700, dir_fd=directory_descriptor)
    except FileExistsError:
        pass
    quarantine_descriptor = os.open(
        ".quarantine",
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_descriptor,
    )
    try:
        for name in names:
            digest = hashlib.sha256(payloads[name]).hexdigest()
            suffix = 0
            while True:
                candidate = f"{digest}-{suffix:04d}-{name}"
                try:
                    os.stat(candidate, dir_fd=quarantine_descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    break
                suffix += 1
            _renameat_directory_noreplace(
                directory_descriptor, name, quarantine_descriptor, candidate,
            )
        os.fsync(quarantine_descriptor)
        os.fsync(directory_descriptor)
        total = sum(
            os.stat(name, dir_fd=quarantine_descriptor, follow_symlinks=False).st_size
            for name in os.listdir(quarantine_descriptor)
        )
        if total > 64 * MIB:
            raise ArtifactError("evidence quarantine exceeds its frozen byte ceiling")
    finally:
        os.close(quarantine_descriptor)


def _flat_directory_inventory(
    directory_descriptor: int, expected_payloads: Mapping[str, bytes] | None,
) -> tuple[int, tuple[str, ...]]:
    names = tuple(sorted(os.listdir(directory_descriptor)))
    total = 0
    for name in names:
        if Path(name).name != name:
            raise ArtifactError("stale analysis stage contains an invalid name")
        payload = _read_regular_at(directory_descriptor, name)
        if expected_payloads is not None and (
            name not in expected_payloads or payload != expected_payloads[name]
        ):
            raise ArtifactError("stale analysis stage contains ambiguous bytes")
        total += len(payload)
    return total, names


def _quarantine_stale_analysis_stages(
    parent_descriptor: int, output_name: str, expected_payloads: Mapping[str, bytes],
) -> None:
    prefix = f".{output_name}.analysis-stage-"
    quarantine_name = f".{output_name}.analysis-quarantine"
    stale_names = tuple(sorted(
        name for name in os.listdir(parent_descriptor) if name.startswith(prefix)
    ))
    try:
        quarantine_state = os.stat(
            quarantine_name, dir_fd=parent_descriptor, follow_symlinks=False,
        )
    except FileNotFoundError:
        quarantine_state = None
    if quarantine_state is not None and not stat.S_ISDIR(quarantine_state.st_mode):
        raise ArtifactError("analysis-stage quarantine is not a directory")
    if not stale_names and quarantine_state is None:
        return
    if quarantine_state is None:
        os.mkdir(quarantine_name, 0o700, dir_fd=parent_descriptor)
    quarantine_descriptor = os.open(
        quarantine_name,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_descriptor,
    )
    staged_descriptors: list[tuple[str, int, tuple[int, int], int]] = []
    try:
        quarantine_total = 0
        for name in sorted(os.listdir(quarantine_descriptor)):
            if not name.startswith(prefix):
                raise ArtifactError("analysis-stage quarantine contains an unknown entry")
            state = os.stat(name, dir_fd=quarantine_descriptor, follow_symlinks=False)
            if not stat.S_ISDIR(state.st_mode):
                raise ArtifactError("analysis-stage quarantine contains a non-directory")
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=quarantine_descriptor,
            )
            try:
                size, _ = _flat_directory_inventory(descriptor, expected_payloads)
                quarantine_total += size
            finally:
                os.close(descriptor)
        for name in stale_names:
            before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            if not stat.S_ISDIR(before.st_mode):
                raise ArtifactError("stale analysis stage is not a directory")
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_descriptor,
            )
            held = os.fstat(descriptor)
            identity = (held.st_dev, held.st_ino)
            if identity != (before.st_dev, before.st_ino):
                os.close(descriptor)
                raise ArtifactError("stale analysis stage identity changed during inventory")
            try:
                size, _ = _flat_directory_inventory(descriptor, expected_payloads)
            except BaseException:
                os.close(descriptor)
                raise
            if size > 32 * MIB:
                os.close(descriptor)
                raise ArtifactError("stale analysis stage exceeds its frozen temp ceiling")
            staged_descriptors.append((name, descriptor, identity, size))
            quarantine_total += size
        if quarantine_total > 64 * MIB:
            raise ArtifactError("analysis-stage quarantine exceeds its frozen byte ceiling")
        for name, descriptor, identity, _ in staged_descriptors:
            _renameat_directory_noreplace(
                parent_descriptor, name, quarantine_descriptor, name,
            )
            after = os.stat(name, dir_fd=quarantine_descriptor, follow_symlinks=False)
            held = os.fstat(descriptor)
            if (
                (after.st_dev, after.st_ino) != identity
                or (held.st_dev, held.st_ino) != identity
            ):
                raise ArtifactError("quarantined analysis stage identity differs")
        os.fsync(quarantine_descriptor)
        os.fsync(parent_descriptor)
    finally:
        for _, descriptor, _, _ in staged_descriptors:
            os.close(descriptor)
        os.close(quarantine_descriptor)


def reconstruct_evidence(
    output_dir: Path,
    raw_rows: Sequence[Mapping[str, object]],
    annotated_index: Sequence[Mapping[str, object]],
    plot_recipes: Sequence[Mapping[str, object]],
    *,
    protocol_sha256: str,
) -> dict[str, object]:
    output_dir = Path(output_dir)
    protocol_sha256 = _hash(protocol_sha256, "protocol_sha256")
    if any(row.get("protocol_sha256") != protocol_sha256 for row in raw_rows):
        raise ArtifactError("raw evidence protocol identity differs from the publication")
    payloads = _publication_payloads(raw_rows, annotated_index, plot_recipes)
    manifest = _artifact_manifest(payloads, protocol_sha256)
    marker = canonical_json_bytes(manifest)
    if output_dir.name in {"", ".", ".."}:
        raise ArtifactError("evidence output must name one final directory")
    parent_descriptor = open_directory_chain(output_dir.parent, create=True)
    staged = None
    published = False
    try:
        fcntl.flock(parent_descriptor, fcntl.LOCK_EX)
        _quarantine_stale_analysis_stages(
            parent_descriptor, output_dir.name,
            dict(payloads) | {"artifact-manifest.json": marker},
        )
        try:
            final_state = os.stat(
                output_dir.name, dir_fd=parent_descriptor, follow_symlinks=False,
            )
        except FileNotFoundError:
            final_state = None
        if final_state is not None:
            if not stat.S_ISDIR(final_state.st_mode):
                raise ArtifactError("evidence destination is not a regular directory")
            existing = validate_evidence_publication(output_dir)
            final_descriptor = os.open(
                output_dir.name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_descriptor,
            )
            try:
                if existing != manifest or any(
                    _read_regular_at(final_descriptor, name) != data
                    for name, data in payloads.items()
                ) or _read_regular_at(final_descriptor, "artifact-manifest.json") != marker:
                    raise FileExistsError("immutable evidence publication conflicts")
            finally:
                os.close(final_descriptor)
            after_final = os.stat(
                output_dir.name, dir_fd=parent_descriptor, follow_symlinks=False,
            )
            if (final_state.st_dev, final_state.st_ino) != (after_final.st_dev, after_final.st_ino):
                raise ArtifactError("evidence destination changed during validation")
            return existing
        staged = create_temporary_directory(
            parent_descriptor, f".{output_dir.name}.analysis-stage-",
        )
        for name, payload in sorted(payloads.items()):
            _write_at_create_only(staged.descriptor, name, payload)
            _publication_boundary(f"file:{name}")
        _write_at_create_only(staged.descriptor, "artifact-manifest.json", marker)
        _publication_boundary("marker:artifact-manifest.json")
        os.fsync(staged.descriptor)
        _publication_boundary("directory-fsync:artifact-manifest.json")
        staged_state = os.fstat(staged.descriptor)
        _renameat_directory_noreplace(
            parent_descriptor, staged.name, parent_descriptor, output_dir.name,
        )
        published = True
        _publication_boundary("rename:analysis-directory")
        final_state = os.stat(
            output_dir.name, dir_fd=parent_descriptor, follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(final_state.st_mode)
            or (final_state.st_dev, final_state.st_ino)
            != (staged_state.st_dev, staged_state.st_ino)
        ):
            raise ArtifactError("published evidence directory identity differs from staged bytes")
        os.fsync(parent_descriptor)
        _publication_boundary("directory-fsync:analysis-directory")
    finally:
        if staged is not None:
            if not published:
                cleanup_exact_directory(
                    parent_descriptor, staged.descriptor, staged.identity, staged.name,
                )
            os.close(staged.descriptor)
        try:
            fcntl.flock(parent_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(parent_descriptor)
    return manifest


def load_artifact_manifest(path: Path) -> dict[str, Any]:
    manifest = load_canonical_json(path, _ARTIFACT_MANIFEST_KEYS)
    if _exact_int(manifest["schema_version"], "schema_version") != 1:
        raise ArtifactError("unsupported artifact manifest")
    if manifest["study_id"] != STUDY_ID or manifest["phase"] != "analysis":
        raise ArtifactError("artifact manifest study_id/phase differs")
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
    allowed = expected | ({".quarantine"} if ".quarantine" in actual else set())
    if actual != allowed or any(entry.is_symlink() or (entry.name != ".quarantine" and not entry.is_file()) for entry in output_dir.iterdir()):
        raise ArtifactError("publication contains missing, extra, or nonregular entries")
    quarantine = output_dir / ".quarantine"
    if quarantine.exists():
        if quarantine.is_symlink() or not quarantine.is_dir():
            raise ArtifactError("publication quarantine is not a regular directory")
        entries = tuple(quarantine.iterdir())
        if any(entry.is_symlink() or not entry.is_file() for entry in entries) or sum(entry.stat().st_size for entry in entries) > 64 * MIB:
            raise ArtifactError("publication quarantine is invalid or oversized")
    for row in manifest["files"]:
        payload = (output_dir / row["path"]).read_bytes()
        if len(payload) != row["bytes"] or hashlib.sha256(payload).hexdigest() != row["sha256"]:
            raise ArtifactError(f"published file mismatch: {row['path']}")
    return manifest


def _failure_time(value: object, name: str) -> datetime:
    text = _text(value, name)
    if _UTC_SECONDS.fullmatch(text) is None:
        raise ArtifactError(f"{name} must be canonical UTC whole seconds")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ArtifactError(f"{name} is not a real UTC timestamp") from exc
    return parsed


def _failure_row(value: object) -> dict[str, Any]:
    row = _closed(value, _FAILURE_KEYS, "failure disposition")
    if row["schema_version"] != SCHEMA_VERSION or row["study_id"] != STUDY_ID:
        raise ArtifactError("failure disposition schema/study differs")
    if row["phase"] not in {"pilot", "confirmation"}:
        raise ArtifactError("failure disposition phase differs")
    revision = _exact_int(row["revision"], "revision")
    stack_id = _text(row["stack_id"], "stack_id")
    if stack_id not in _STACK_ORDER:
        raise ArtifactError("failure disposition stack_id differs")
    seed = _exact_int(row["seed"], "seed")
    expected_shard = f"{stack_id}:base:{seed:03d}"
    if revision != 1 or row["shard_id"] != expected_shard:
        raise ArtifactError("failure disposition revision/shard differs")
    _text(row["condition_id"], "condition_id")
    if row["reason"] not in _FAILURE_REASONS:
        raise ArtifactError("failure disposition reason differs")
    started = _failure_time(row["started_at_utc"], "started_at_utc")
    finished = _failure_time(row["finished_at_utc"], "finished_at_utc")
    if finished < started:
        raise ArtifactError("failure disposition finishes before it starts")
    _hash(row["command_sha256"], "command_sha256")
    if row["readable_output_sha256"] is not None:
        _hash(row["readable_output_sha256"], "readable_output_sha256")
    _hash(row["details_sha256"], "details_sha256")
    return row


def publish_failure_disposition(
    value: Mapping[str, object] | Sequence[Mapping[str, object]], destination: Path,
) -> str:
    values = (value,) if isinstance(value, Mapping) else tuple(value)
    if not values:
        raise ArtifactError("failure dispositions must not be empty")
    rows = tuple(_failure_row(dict(item)) for item in values)
    identities = tuple((row["condition_id"], row["reason"]) for row in rows)
    if identities != tuple(sorted(set(identities))):
        raise ArtifactError("failure dispositions must be sorted and unique")
    shard_identity = {
        (row["phase"], row["revision"], row["shard_id"], row["stack_id"], row["seed"])
        for row in rows
    }
    if len(shard_identity) != 1:
        raise ArtifactError("failure dispositions must describe one shard")
    payload = b"".join(canonical_json_bytes(row) for row in rows)
    destination = Path(destination)
    if destination.name != "failure-disposition.jsonl":
        raise ArtifactError("failure disposition destination differs")
    descriptor = open_directory_chain(destination.parent, create=True)
    try:
        try:
            os.stat(destination.name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        else:
            existing = _read_regular_at(descriptor, destination.name)
        if existing is not None:
            if existing == payload:
                return "validated-and-skipped"
            raise FileExistsError("failure disposition conflicts")
        _write_at_create_only(descriptor, destination.name, payload)
        os.fsync(descriptor)
        return "published"
    finally:
        os.close(descriptor)


__all__ = [
    "ArtifactError", "ImplementationDriftError", "ImplementationSnapshot",
    "ResourceDisposition", "RolloutSpec", "ShardSpec", "canonical_json_bytes",
    "canonical_state_bytes", "iter_manifest", "load_artifact_manifest",
    "load_canonical_json", "load_protocol_manifest", "load_seed_manifest",
    "prepare_manifest", "preflight_resources", "raw_evidence_from_rollout",
    "raw_evidence_from_failure_disposition",
    "build_annotated_samples", "build_plot_recipes",
    "publish_failure_disposition", "publish_or_validate_skip", "reconstruct_evidence",
    "replay_rollout", "validate_evidence_publication", "validate_rollout",
]
