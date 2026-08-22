from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DIGEST = "a" * 64
REGISTRY_NAMES = ("alpha", "beta")


def _attempt_log(*, final: bool = False, completed: list[str] | None = None) -> str:
    entries = completed if completed is not None else ["beta", "alpha"]
    attempts: list[dict[str, object]] = [
        {
            "id": "failed-window",
            "command": ["uv", "run", "python", "scripts/fetch_reference.py", "--all-metadata-only"],
            "started_at_utc": "2026-08-22T16:48:58Z",
            "finished_at_utc": "2026-08-22T16:49:36Z",
            "exit_code": 1,
            "published_lock": False,
            "completed_entries": ["alpha"],
            "incomplete_entry": "beta",
            "error": "rate limited",
            "rate_limit_reset_utc": "2026-08-22T17:48:39Z",
            "lock_absence_verified": True,
        }
    ]
    if final:
        attempts.append(
            {
                "id": "final-window",
                "command": ["uv", "run", "python", "scripts/fetch_reference.py", "--all-metadata-only"],
                "started_at_utc": "2026-08-22T17:49:00Z",
                "finished_at_utc": "2026-08-22T17:50:00Z",
                "exit_code": 0,
                "published_lock": True,
                "completed_entries": entries,
                "lock_sha256_after": "b" * 64,
                "summary": "published complete lock",
            }
        )
    return yaml.safe_dump(
        {
            "schema_version": 1,
            "registry_sha256": REGISTRY_DIGEST,
            "attempts": attempts,
        },
        sort_keys=False,
    )


def test_attempt_log_parser_is_strict_and_normalizes_completed_names() -> None:
    report = importlib.import_module("scripts.write_p2_report")

    parsed = report.parse_attempt_log(
        _attempt_log(final=True),
        expected_registry_sha256=REGISTRY_DIGEST,
        registry_names=REGISTRY_NAMES,
    )

    assert parsed.attempts[-1].completed_entries == ("alpha", "beta")
    assert parsed.attempts[-1].published_lock is True

    malformed = yaml.safe_load(_attempt_log(final=True))
    malformed["attempts"][0]["unexpected"] = "not allowed"
    with pytest.raises(ValueError, match="extra keys"):
        report.parse_attempt_log(
            yaml.safe_dump(malformed),
            expected_registry_sha256=REGISTRY_DIGEST,
            registry_names=REGISTRY_NAMES,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda raw: raw["attempts"][0].update(started_at_utc="2026-08-22 16:48:58+00:00"), "canonical UTC"),
        (lambda raw: raw["attempts"][0].update(command="uv run"), "command"),
        (lambda raw: raw["attempts"][0].update(completed_entries=["alpha", "alpha"]), "duplicate"),
        (lambda raw: raw.update(registry_sha256="c" * 64), "registry SHA-256"),
    ],
)
def test_attempt_log_parser_rejects_malformed_evidence(mutation, message: str) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    raw = yaml.safe_load(_attempt_log())
    mutation(raw)

    with pytest.raises(ValueError, match=message):
        report.parse_attempt_log(
            yaml.safe_dump(raw),
            expected_registry_sha256=REGISTRY_DIGEST,
            registry_names=REGISTRY_NAMES,
        )


def test_failed_window_requires_proof_that_lock_bytes_were_preserved() -> None:
    report = importlib.import_module("scripts.write_p2_report")
    raw = yaml.safe_load(_attempt_log())
    del raw["attempts"][0]["lock_absence_verified"]

    with pytest.raises(ValueError, match="lock preservation"):
        report.parse_attempt_log(
            yaml.safe_dump(raw),
            expected_registry_sha256=REGISTRY_DIGEST,
            registry_names=REGISTRY_NAMES,
        )

    raw["attempts"][0]["lock_sha256_before"] = "d" * 64
    raw["attempts"][0]["lock_sha256_after"] = "e" * 64
    with pytest.raises(ValueError, match="lock preservation"):
        report.parse_attempt_log(
            yaml.safe_dump(raw),
            expected_registry_sha256=REGISTRY_DIGEST,
            registry_names=REGISTRY_NAMES,
        )


def _write_fixture_repository(path: Path) -> tuple[str, str]:
    references = path / "references"
    references.mkdir(parents=True)
    registry = {
        "verified_at": "2026-08-22",
        "large_model_downloads_default": False,
        "physical_deployment_default": False,
        "repositories": [
            {
                "name": name,
                "url": f"https://github.com/example/{name}",
                "mode": "DIRECT_DEPENDENCY" if name == "alpha" else "SPARSE_REFERENCE",
                "experiments": ["fixture"],
                "selected_paths": ["src", "missing"],
                "use": "fixture",
            }
            for name in REGISTRY_NAMES
        ],
    }
    registry_path = references / "repos.yaml"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False))
    registry_digest = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    lock = {
        "registry_sha256": registry_digest,
        "generated_at": "2026-08-22T17:50:00Z",
        "entries": [
            {
                "name": name,
                "url": f"https://github.com/example/{name}",
                "default_branch": "main",
                "commit_sha": ("1" if name == "alpha" else "2") * 40,
                "retrieved_at": f"2026-08-22T17:4{index}:00Z",
                "metadata_evidence": {"repository": f"https://api.github.test/{name}"},
                "license_spdx": "MIT" if name == "alpha" else None,
                "license_status": "DISCOVERED" if name == "alpha" else "UNKNOWN",
                "license_evidence_url": f"https://api.github.test/{name}/license" if name == "alpha" else None,
                "path_statuses": {"src": "EXISTS", "missing": "MISSING"},
                "path_evidence_urls": {
                    "src": f"https://api.github.test/{name}/tree/src",
                    "missing": f"https://api.github.test/{name}/tree/missing",
                },
                "metadata_status": "RESOLVED",
            }
            for index, name in enumerate(REGISTRY_NAMES)
        ],
    }
    lock_path = references / "repos.lock.yaml"
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=False))
    lock_digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    attempt_text = _attempt_log(final=True).replace(REGISTRY_DIGEST, registry_digest).replace("b" * 64, lock_digest)
    (references / "p2-live-attempts.yaml").write_text(attempt_text)
    (path / "tracked.txt").write_text("fixture\n")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=P2 Test", "-c", "user.email=p2@example.invalid", "commit", "-m", "fixture"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()
    return sha, lock_digest


def _successful_results(report) -> dict[str, object]:
    return {
        name: report.CommandResult(command=command, returncode=0, stdout=output, stderr="")
        for name, command, output in (
            ("audit", report.REQUIRED_COMMANDS["audit"], '{"registry_entries":2,"lock_entries":2,"selected_paths":4,"discovered_licenses":1,"tracked_files":4,"errors":[],"ok":true}\n'),
            ("full_tests", report.REQUIRED_COMMANDS["full_tests"], "300 passed in 5.00s\n"),
            ("lock_check", report.REQUIRED_COMMANDS["lock_check"], "",),
            ("safety", report.REQUIRED_COMMANDS["safety"], '{"simulation_only": true, "remote_enabled": false}\n'),
            ("diff_check", report.REQUIRED_COMMANDS["diff_check"], ""),
            ("boundary_paths", report.REQUIRED_COMMANDS["boundary_paths"], ""),
            ("boundary_large_files", report.REQUIRED_COMMANDS["boundary_large_files"], ""),
        )
    }


def test_report_builder_binds_lock_attempts_counts_and_offline_evidence(tmp_path: Path) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    sha, lock_digest = _write_fixture_repository(repository)

    rendered = report.build_report(
        project_root=repository,
        implementation_sha=sha,
        command_results=_successful_results(report),
        physical_deployment_allowed=False,
        remote_enabled=False,
    )

    assert sha in rendered
    assert lock_digest in rendered
    assert "Registry entries: `2`" in rendered
    assert "Selected paths: `4` (`2` EXISTS, `2` MISSING)" in rendered
    assert "Licenses: `1` DISCOVERED, `1` UNKNOWN, `0` UNAVAILABLE" in rendered
    assert "failed-window" in rendered and "final-window" in rendered
    assert "rate limited" in rendered
    assert "300 passed in 5.00s" in rendered
    assert "No network or live resolver command was run by this report generator." in rendered
    assert "Run the P3 source compatibility audit" in rendered


def test_report_builder_fails_closed_on_bad_evidence(tmp_path: Path) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    sha, _ = _write_fixture_repository(repository)
    results = _successful_results(report)
    results["full_tests"] = report.CommandResult(
        command=report.REQUIRED_COMMANDS["full_tests"], returncode=1, stdout="1 failed", stderr=""
    )
    with pytest.raises(RuntimeError, match="full_tests"):
        report.build_report(
            project_root=repository,
            implementation_sha=sha,
            command_results=results,
            physical_deployment_allowed=False,
            remote_enabled=False,
        )
    with pytest.raises(RuntimeError, match="physical deployment"):
        report.build_report(
            project_root=repository,
            implementation_sha=sha,
            command_results=_successful_results(report),
            physical_deployment_allowed=True,
            remote_enabled=False,
        )
    repository.joinpath("tracked.txt").write_text("dirty\n")
    with pytest.raises(RuntimeError, match="worktree must be clean"):
        report.build_report(
            project_root=repository,
            implementation_sha=sha,
            command_results=_successful_results(report),
            physical_deployment_allowed=False,
            remote_enabled=False,
        )


def test_report_builder_rejects_absent_incomplete_or_mismatched_lock(tmp_path: Path) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    sha, _ = _write_fixture_repository(repository)
    lock_path = repository / "references" / "repos.lock.yaml"
    lock_path.unlink()
    with pytest.raises(ValueError, match="lock"):
        report.build_report(
            project_root=repository,
            implementation_sha=sha,
            command_results=_successful_results(report),
            physical_deployment_allowed=False,
            remote_enabled=False,
        )


def test_cli_refuses_incomplete_production_state_without_touching_run_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    repository = tmp_path / "incomplete-production"
    references = repository / "references"
    references.mkdir(parents=True)
    shutil_registry = ROOT / "references" / "repos.yaml"
    (references / "repos.yaml").write_bytes(shutil_registry.read_bytes())
    (references / "p2-live-attempts.yaml").write_bytes(
        (ROOT / "references" / "p2-live-attempts.yaml").read_bytes()
    )
    run_report = repository / "RUN_REPORT.md"
    run_report.write_text("unchanged report\n", encoding="utf-8")
    before = run_report.read_bytes()
    monkeypatch.setenv("PHYSICAL_DEPLOYMENT_ALLOWED", "false")
    monkeypatch.setenv("REFLECT_REMOTE_ENABLED", "0")
    runner_called = False

    def forbidden_runner(*args, **kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("verification runner must not execute with no complete lock")

    monkeypatch.setattr(report, "_run", forbidden_runner)

    with pytest.raises((RuntimeError, ValueError)):
        report.main(["--evidence-base-sha", "0" * 40], root=repository)

    assert run_report.read_bytes() == before
    assert runner_called is False
    assert "fetch_reference.py" not in Path(report.__file__).read_text(encoding="utf-8")
