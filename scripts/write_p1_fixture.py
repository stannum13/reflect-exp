"""Write the deterministic, synthetic P1 rollout fixture."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.metadata
import os
from pathlib import Path
import platform
import subprocess
import tempfile
from typing import Sequence

import numpy as np

from reflect.clock import VirtualClock
from reflect.events import ExecutionEvent, ExecutionEventType
from reflect.rollout import (
    SCHEMA_VERSION,
    RolloutMetadata,
    RolloutRecord,
    RolloutValidationError,
    RolloutWriter,
    sha256_json,
    validate_rollout,
)
from reflect.safety import SafetyConfig
from reflect.types import ActionChunk, ControlReference, Observation, RobotState


ROLLOUT_ID = "p1-fixture"
ROOT = Path(__file__).resolve().parents[1]
SOURCE_REGISTRY_PATH = Path("references/bootstrap-tools.yaml")
FIXTURE_SENTINEL_GIT_SHA = "f" * 40
FIXTURE_SENTINEL_SOURCE_HASH = hashlib.sha256(
    b"fixture-sentinel:no-source-registry"
).hexdigest()
SEED = 17
MONOTONIC_START_NS = 1_000_000
WALL_START_NS = 2_000_000
ROLLOUT_DURATION_NS = 100
SKILL_ID = "p1-synthetic-skill"
CHUNK_ID = "p1-action-chunk"


@dataclass(frozen=True)
class FixtureProvenance:
    mode: str
    git_sha: str
    working_tree_clean: bool
    dirty_diff_hash: str | None
    source_lock_hash: str
    source_registry_artifact: str


def _git_output(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"repository provenance requires Git metadata: {message}")
    return completed.stdout


def _dirty_diff_hash(root: Path, status: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(b"git-status-v1-z\0")
    digest.update(status)
    digest.update(b"\0git-diff-binary-head\0")
    digest.update(_git_output(root, "diff", "--binary", "HEAD"))
    untracked = _git_output(
        root, "ls-files", "--others", "--exclude-standard", "-z"
    ).split(b"\0")
    for raw_path in sorted(path for path in untracked if path):
        relative = Path(os.fsdecode(raw_path))
        candidate = root / relative
        digest.update(b"\0untracked\0")
        digest.update(raw_path)
        digest.update(b"\0")
        if candidate.is_symlink():
            digest.update(os.fsencode(os.readlink(candidate)))
        elif candidate.is_file():
            digest.update(candidate.read_bytes())
    return digest.hexdigest()


def repository_provenance(root: Path = ROOT) -> FixtureProvenance:
    root = root.resolve()
    repository_root = Path(
        os.fsdecode(_git_output(root, "rev-parse", "--show-toplevel")).strip()
    ).resolve()
    if repository_root != root:
        raise RuntimeError("fixture repository root does not match the script root")
    registry_path = root / SOURCE_REGISTRY_PATH
    if not registry_path.is_file():
        raise RuntimeError(f"source registry artifact is missing: {SOURCE_REGISTRY_PATH}")
    status = _git_output(
        root, "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )
    working_tree_clean = not status
    return FixtureProvenance(
        mode="repository",
        git_sha=os.fsdecode(_git_output(root, "rev-parse", "HEAD")).strip(),
        working_tree_clean=working_tree_clean,
        dirty_diff_hash=None if working_tree_clean else _dirty_diff_hash(root, status),
        source_lock_hash=hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        source_registry_artifact=SOURCE_REGISTRY_PATH.as_posix(),
    )


def fixture_sentinel_provenance() -> FixtureProvenance:
    return FixtureProvenance(
        mode="fixture-sentinel",
        git_sha=FIXTURE_SENTINEL_GIT_SHA,
        working_tree_clean=True,
        dirty_diff_hash=None,
        source_lock_hash=FIXTURE_SENTINEL_SOURCE_HASH,
        source_registry_artifact="fixture-sentinel:no-source-registry",
    )


def _dependency_versions() -> dict[str, str]:
    return {
        "numpy": importlib.metadata.version("numpy"),
        "pyarrow": importlib.metadata.version("pyarrow"),
        "PyYAML": importlib.metadata.version("PyYAML"),
    }


def _event(
    clock: VirtualClock,
    config_hash: str,
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
        config_hash=config_hash,
        object_ids=(),
        skill_id=SKILL_ID,
        payload=payload,
    )


def fixture_record(provenance: FixtureProvenance | None = None) -> RolloutRecord:
    """Construct the complete fixture from explicit synthetic constants."""
    provenance = repository_provenance() if provenance is None else provenance
    config = {
        "fixture": "p1",
        "provenance_mode": provenance.mode,
        "source_registry_artifact": provenance.source_registry_artifact,
        "task": "deterministic-rollout",
        "version": 1,
    }
    config_hash = sha256_json(config)
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
            config_hash,
            ExecutionEventType.OBSERVATION_RECEIVED,
            0,
            {"observation_id": 0},
        )
    ]

    clock.advance_ns(10)
    events.append(
        _event(
            clock,
            config_hash,
            ExecutionEventType.POLICY_REQUESTED,
            1,
            {"source_observation_id": observation.sequence_id},
        )
    )
    clock.advance_ns(5)
    generated_time_ns = clock.monotonic_ns()
    events.append(
        _event(
            clock,
            config_hash,
            ExecutionEventType.POLICY_RESPONDED,
            2,
            {
                "chunk_id": CHUNK_ID,
                "source_observation_id": observation.sequence_id,
            },
        )
    )

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
            config_hash,
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
            config_hash,
            ExecutionEventType.ACTION_EXECUTED,
            4,
            {"source_chunk_id": CHUNK_ID, "time_ns": executed_time_ns},
        )
    )
    clock.advance_ns(10)
    events.append(
        _event(clock, config_hash, ExecutionEventType.SKILL_SUCCEEDED, 5, {})
    )

    return RolloutRecord(
        metadata=RolloutMetadata(
            experiment_id="bootstrap",
            claim_revision=1,
            git_sha=provenance.git_sha,
            working_tree_clean=provenance.working_tree_clean,
            dirty_diff_hash=provenance.dirty_diff_hash,
            source_lock_hash=provenance.source_lock_hash,
            os_arch=f"{platform.system()}-{platform.release()}-{platform.machine()}",
            cpu=platform.processor() or platform.machine(),
            gpu=None,
            python_version=platform.python_version(),
            dependency_versions=_dependency_versions(),
            seed=SEED,
            simulator="none-synthetic-fixture",
            task_config_hash=config_hash,
            model_hashes={},
            action_schema_version=SCHEMA_VERSION,
            observation_schema_version=SCHEMA_VERSION,
            wall_start_ns=WALL_START_NS,
            wall_end_ns=WALL_START_NS + ROLLOUT_DURATION_NS,
            monotonic_start_ns=MONOTONIC_START_NS,
            monotonic_end_ns=MONOTONIC_START_NS + ROLLOUT_DURATION_NS,
            status="pass",
            physical_deployment_allowed=False,
        ),
        config=config,
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
            f"Provenance mode: {provenance.mode}.\n"
            f"Source registry artifact: {provenance.source_registry_artifact}.\n"
        ),
    )


def _same_artifact_bytes(first: Path, second: Path) -> bool:
    first_files = {path.name for path in first.iterdir() if path.is_file()}
    second_files = {path.name for path in second.iterdir() if path.is_file()}
    return first_files == second_files and all(
        (first / name).read_bytes() == (second / name).read_bytes()
        for name in first_files
    )


def write_fixture(
    output_dir: Path,
    provenance: FixtureProvenance,
    *,
    reuse_existing: bool,
) -> Path:
    record = fixture_record(provenance)
    writer = RolloutWriter(output_dir, ROLLOUT_ID)
    if not writer.path.exists() or not reuse_existing:
        return writer.write(record)
    validate_rollout(writer.path)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".p1-reuse-", dir=output_dir) as temporary:
        expected = RolloutWriter(Path(temporary), ROLLOUT_ID).write(record)
        if not _same_artifact_bytes(writer.path, expected):
            raise RolloutValidationError(
                "existing p1-fixture conflicts with the current deterministic fixture"
            )
    return writer.path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("results/bootstrap"))
    parser.add_argument("--fixture-sentinel-provenance", action="store_true")
    parser.add_argument("--reuse-existing", action="store_true")
    arguments = parser.parse_args(argv)
    SafetyConfig.from_mapping(os.environ).require_simulation_only()
    provenance = (
        fixture_sentinel_provenance()
        if arguments.fixture_sentinel_provenance
        else repository_provenance()
    )
    artifact_path = write_fixture(
        arguments.output_dir,
        provenance,
        reuse_existing=arguments.reuse_existing,
    )
    print(artifact_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
