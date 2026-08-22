from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


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


def test_p1_report_generator_uses_an_explicit_evidence_base() -> None:
    generator_path = ROOT / "scripts" / "write_p1_report.py"

    assert generator_path.is_file(), "scripts/write_p1_report.py must exist"
    generator = generator_path.read_text(encoding="utf-8")
    assert "--evidence-base-sha" in generator
    assert "P2 source auditing and empirical experiments have not run." in generator
    assert "tests/test_run_state.py" in generator
