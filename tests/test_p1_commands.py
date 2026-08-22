from __future__ import annotations

import importlib
import importlib.metadata
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
ROLLOUT_ID = "p1-fixture"


def _copied_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    shutil.copytree(ROOT / "reflect", repository / "reflect")
    scripts = repository / "scripts"
    scripts.mkdir()
    fixture_source = ROOT / "scripts" / "write_p1_fixture.py"
    assert fixture_source.is_file(), "scripts/write_p1_fixture.py must exist"
    shutil.copy2(fixture_source, scripts / fixture_source.name)
    return repository


def _fixture_command(repository: Path, output_dir: Path) -> list[str]:
    return [
        sys.executable,
        "scripts/write_p1_fixture.py",
        "--output-dir",
        str(output_dir),
        "--fixture-sentinel-provenance",
    ]


def _safe_environment(repository: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "PHYSICAL_DEPLOYMENT_ALLOWED": "false",
            "REFLECT_REMOTE_ENABLED": "0",
            "PYTHONPATH": str(repository),
        }
    )
    return environment


def test_fixture_command_writes_replayable_deterministic_artifact(
    tmp_path: Path,
) -> None:
    repository = _copied_repository(tmp_path)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    environment = _safe_environment(repository)

    completed = subprocess.run(
        _fixture_command(repository, first_root),
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
    )
    artifact_path = first_root / ROLLOUT_ID
    assert completed.returncode == 0
    assert artifact_path.joinpath("actions.parquet").is_file()
    metadata = json.loads((artifact_path / "metadata.json").read_text())
    assert metadata["model_hashes"] == {}
    assert "fixture-sentinel" in (artifact_path / "summary.md").read_text()

    replay = subprocess.run(
        [sys.executable, "-m", "reflect.rollout", "replay", str(artifact_path)],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert replay.returncode == 0
    assert json.loads(replay.stdout)["rollout_id"] == ROLLOUT_ID

    repeated = subprocess.run(
        _fixture_command(repository, second_root),
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert repeated.returncode == 0
    for first_file in sorted(artifact_path.iterdir()):
        assert first_file.read_bytes() == (second_root / ROLLOUT_ID / first_file.name).read_bytes()


def test_fixture_policy_lifecycle_is_coherent() -> None:
    fixture_module = importlib.import_module("scripts.write_p1_fixture")
    events_module = importlib.import_module("reflect.events")
    provenance = fixture_module.fixture_sentinel_provenance()

    record = fixture_module.fixture_record(provenance)

    request = next(
        event
        for event in record.events
        if event.event_type is events_module.ExecutionEventType.POLICY_REQUESTED
    )
    response = next(
        event
        for event in record.events
        if event.event_type is events_module.ExecutionEventType.POLICY_RESPONDED
    )
    action = record.actions[0]
    acceptance = next(
        event
        for event in record.events
        if event.event_type is events_module.ExecutionEventType.CHUNK_ACCEPTED
    )

    assert request.payload == {"source_observation_id": 0}
    assert response.payload == {
        "chunk_id": "p1-action-chunk",
        "source_observation_id": 0,
    }
    assert request.monotonic_time_ns < response.monotonic_time_ns
    assert response.monotonic_time_ns == action.generated_time_ns
    assert response.payload["chunk_id"] == action.chunk_id
    assert response.payload["source_observation_id"] == action.source_observation_id
    assert response.sequence_id < acceptance.sequence_id


def test_fixture_command_refuses_to_overwrite_existing_rollout(tmp_path: Path) -> None:
    repository = _copied_repository(tmp_path)
    output_root = tmp_path / "output"
    environment = _safe_environment(repository)
    command = _fixture_command(repository, output_root)

    first = subprocess.run(command, cwd=repository, env=environment)
    before = {
        path.name: path.read_bytes()
        for path in (output_root / ROLLOUT_ID).iterdir()
    }
    second = subprocess.run(
        command,
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert first.returncode == 0
    assert second.returncode != 0
    assert "already exists" in second.stderr
    assert before == {
        path.name: path.read_bytes()
        for path in (output_root / ROLLOUT_ID).iterdir()
    }


def test_fixture_command_rejects_physical_enablement_before_artifact_creation(
    tmp_path: Path,
) -> None:
    repository = _copied_repository(tmp_path)
    output_root = tmp_path / "physical-output"
    environment = _safe_environment(repository)
    environment["PHYSICAL_DEPLOYMENT_ALLOWED"] = "true"

    completed = subprocess.run(
        _fixture_command(repository, output_root),
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "physical deployment is disabled for this program" in completed.stderr
    assert not (output_root / ROLLOUT_ID).exists()


def test_make_replay_requires_run() -> None:
    completed = subprocess.run(
        ["make", "replay"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "RUN is required" in completed.stderr


def test_makefile_exposes_p1_fixture_and_gate_targets() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "p1-fixture:" in makefile
    assert "p1-check: test p1-fixture" in makefile


def test_fixture_repository_metadata_matches_authoritative_runtime_and_files(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "repository-provenance"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/write_p1_fixture.py",
            "--output-dir",
            str(output_root),
        ],
        cwd=ROOT,
        env=_safe_environment(ROOT),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    metadata = json.loads(
        (output_root / ROLLOUT_ID / "metadata.json").read_text(encoding="utf-8")
    )
    config = json.loads(
        (output_root / ROLLOUT_ID / "config.json").read_text(encoding="utf-8")
    )
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    git_status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    registry = ROOT / "references" / "bootstrap-tools.yaml"

    assert metadata["git_sha"] == git_sha
    assert metadata["working_tree_clean"] is (not bool(git_status))
    assert (metadata["dirty_diff_hash"] is None) is (not bool(git_status))
    assert metadata["source_lock_hash"] == hashlib.sha256(
        registry.read_bytes()
    ).hexdigest()
    assert config["source_registry_artifact"] == "references/bootstrap-tools.yaml"
    assert config["provenance_mode"] == "repository"
    assert metadata["dependency_versions"] == {
        "numpy": importlib.metadata.version("numpy"),
        "pyarrow": importlib.metadata.version("pyarrow"),
        "PyYAML": importlib.metadata.version("PyYAML"),
    }
    assert metadata["os_arch"] == (
        f"{platform.system()}-{platform.release()}-{platform.machine()}"
    )
    assert metadata["cpu"] == (platform.processor() or platform.machine())
    assert metadata["python_version"] == platform.python_version()
    assert metadata["model_hashes"] == {}


def test_make_fixture_and_replay_gate_is_repeatable(tmp_path: Path) -> None:
    output_root = tmp_path / "make-output"
    environment = _safe_environment(ROOT)

    for _ in range(2):
        fixture = subprocess.run(
            ["make", "p1-fixture", f"P1_OUTPUT_DIR={output_root}"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        replay = subprocess.run(
            ["make", "replay", f"RUN={output_root / ROLLOUT_ID}"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert fixture.returncode == 0, fixture.stderr
        assert replay.returncode == 0, replay.stderr
        assert replay.stdout.count('"rollout_id":"p1-fixture"') == 1


def test_fixture_reuse_rejects_an_incomplete_existing_directory(tmp_path: Path) -> None:
    repository = _copied_repository(tmp_path)
    output_root = tmp_path / "incomplete"
    artifact_path = output_root / ROLLOUT_ID
    artifact_path.mkdir(parents=True)
    artifact_path.joinpath("metadata.json").write_text("{}")

    completed = subprocess.run(
        [*_fixture_command(repository, output_root), "--reuse-existing"],
        cwd=repository,
        env=_safe_environment(repository),
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "missing" in completed.stderr


def test_fixture_reuse_rejects_a_complete_conflicting_fixture(tmp_path: Path) -> None:
    fixture_module = importlib.import_module("scripts.write_p1_fixture")
    sentinel = fixture_module.fixture_sentinel_provenance()
    conflicting = fixture_module.FixtureProvenance(
        mode=sentinel.mode,
        git_sha="e" * 40,
        working_tree_clean=sentinel.working_tree_clean,
        dirty_diff_hash=sentinel.dirty_diff_hash,
        source_lock_hash=sentinel.source_lock_hash,
        source_registry_artifact=sentinel.source_registry_artifact,
    )
    output_root = tmp_path / "conflicting"
    artifact_path = fixture_module.write_fixture(
        output_root,
        conflicting,
        reuse_existing=False,
    )
    before = {path.name: path.read_bytes() for path in artifact_path.iterdir()}

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/write_p1_fixture.py",
            "--output-dir",
            str(output_root),
            "--fixture-sentinel-provenance",
            "--reuse-existing",
        ],
        cwd=ROOT,
        env=_safe_environment(ROOT),
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "conflicts" in completed.stderr
    assert before == {path.name: path.read_bytes() for path in artifact_path.iterdir()}


def test_p1_report_generator_uses_an_explicit_evidence_base() -> None:
    generator_path = ROOT / "scripts" / "write_p1_report.py"

    assert generator_path.is_file(), "scripts/write_p1_report.py must exist"
    generator = generator_path.read_text(encoding="utf-8")
    assert "--evidence-base-sha" in generator
    assert "P2 source auditing and empirical experiments have not run." in generator
    assert "tests/test_run_state.py" in generator


def test_p1_report_normalizes_resolved_temporary_fixture_paths() -> None:
    report_module = importlib.import_module("scripts.write_p1_report")

    assert hasattr(report_module, "_normalized_fixture_output")
    assert report_module._normalized_fixture_output(  # type: ignore[attr-defined]
        "/private/var/folders/example/first/p1-fixture\n",
        Path("/var/folders/example/first/p1-fixture"),
        "TEMP_ROOT_A",
    ) == "<TEMP_ROOT_A>/p1-fixture"

    with pytest.raises(RuntimeError, match="expected artifact path"):
        report_module._normalized_fixture_output(  # type: ignore[attr-defined]
            "/private/var/folders/example/wrong/p1-fixture\n",
            Path("/var/folders/example/first/p1-fixture"),
            "TEMP_ROOT_A",
        )


def test_p1_report_labels_lock_stdout_and_stderr() -> None:
    report_module = importlib.import_module("scripts.write_p1_report")
    completed = subprocess.CompletedProcess(
        args=["uv", "lock", "--check"],
        returncode=0,
        stdout="",
        stderr="Resolved 10 packages in 3ms\n",
    )

    output = report_module._labeled_output(completed)  # type: ignore[attr-defined]

    assert "stdout:\n(empty)" in output
    assert "stderr:\nResolved 10 packages in 3ms" in output
    assert "exit: 0" in output


def _git_commit(repository: Path, content: str) -> str:
    repository.joinpath("tracked.txt").write_text(content)
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Evidence Test",
            "-c",
            "user.email=evidence@example.invalid",
            "commit",
            "-m",
            content,
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_p1_report_evidence_base_requires_current_clean_head(tmp_path: Path) -> None:
    report_module = importlib.import_module("scripts.write_p1_report")
    repository = tmp_path / "evidence-repository"
    repository.mkdir()
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    old_sha = _git_commit(repository, "old")
    head_sha = _git_commit(repository, "head")

    assert report_module._validate_evidence_base(  # type: ignore[attr-defined]
        head_sha, repository
    ) == head_sha
    with pytest.raises(RuntimeError, match="current HEAD"):
        report_module._validate_evidence_base(old_sha, repository)  # type: ignore[attr-defined]

    repository.joinpath("tracked.txt").write_text("dirty")
    with pytest.raises(RuntimeError, match="worktree must be clean"):
        report_module._validate_evidence_base(head_sha, repository)  # type: ignore[attr-defined]
