from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DIGEST = "a" * 64
REGISTRY_NAMES = ("alpha", "beta")


def _all_command() -> list[str]:
    return [
        "env",
        "UV_CACHE_DIR=.cache/uv",
        "uv",
        "run",
        "python",
        "scripts/fetch_reference.py",
        "--all-metadata-only",
    ]


def _name_command(name: str) -> list[str]:
    return [
        "env",
        "UV_CACHE_DIR=.cache/uv",
        "uv",
        "run",
        "python",
        "scripts/fetch_reference.py",
        "--name",
        name,
        "--metadata-only",
    ]


def _attempt_log(*, final: bool = False, completed: list[str] | None = None) -> str:
    entries = completed if completed is not None else ["beta", "alpha"]
    attempts: list[dict[str, object]] = [
        {
            "id": "failed-window",
            "command": _all_command(),
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
                "command": _all_command(),
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


def _commit_all(repository: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=P2 Test",
            "-c",
            "user.email=p2@example.invalid",
            "commit",
            "-m",
            message,
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


def _successful_results(report) -> dict[str, object]:
    return {
        name: report.CommandResult(command=command, returncode=0, stdout=output, stderr="")
        for name, command, output in (
            ("audit", report.REQUIRED_COMMANDS["audit"], '{"registry_entries":2,"lock_entries":2,"selected_paths":4,"discovered_licenses":1,"tracked_files":4,"errors":[],"ok":true}\n'),
            ("full_tests", report.REQUIRED_COMMANDS["full_tests"], "300 passed in 5.00s\n"),
            ("lock_check", report.REQUIRED_COMMANDS["lock_check"], "",),
            ("safety", report.REQUIRED_COMMANDS["safety"], '{"simulation_only": true, "remote_enabled": false}\n'),
            ("diff_check", report.REQUIRED_COMMANDS["diff_check"], ""),
            (
                "boundary_paths",
                report.REQUIRED_COMMANDS["boundary_paths"],
                "references/p2-live-attempts.yaml\0references/repos.lock.yaml\0references/repos.yaml\0tracked.txt\0",
            ),
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


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("incomplete", "metadata is not resolved"),
        ("registry-mismatch", "registry SHA-256"),
        ("lock-digest", "lock digest"),
        ("no-final", "exactly one successful publication"),
    ],
)
def test_report_rejects_incomplete_mismatched_and_unbound_evidence(
    tmp_path: Path, mutation: str, message: str
) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    _write_fixture_repository(repository)
    lock_path = repository / "references" / "repos.lock.yaml"
    attempts_path = repository / "references" / "p2-live-attempts.yaml"
    lock = yaml.safe_load(lock_path.read_text())
    attempts = yaml.safe_load(attempts_path.read_text())
    if mutation == "incomplete":
        lock["entries"][0]["metadata_status"] = "BLOCKED_NETWORK"
    elif mutation == "registry-mismatch":
        lock["registry_sha256"] = "f" * 64
    elif mutation == "lock-digest":
        attempts["attempts"][-1]["lock_sha256_after"] = "c" * 64
    else:
        attempts["attempts"].pop()
    if mutation in {"incomplete", "registry-mismatch"}:
        lock_path.write_text(yaml.safe_dump(lock, sort_keys=False))
        attempts["attempts"][-1]["lock_sha256_after"] = hashlib.sha256(
            lock_path.read_bytes()
        ).hexdigest()
    attempts_path.write_text(yaml.safe_dump(attempts, sort_keys=False))
    sha = _commit_all(repository, mutation)

    with pytest.raises(ValueError, match=message):
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

    monkeypatch.setattr(report, "_run_verification", forbidden_runner)

    with pytest.raises((RuntimeError, ValueError)):
        report.main(["--evidence-base-sha", "0" * 40], root=repository)

    assert run_report.read_bytes() == before
    assert runner_called is False


def test_attempt_yaml_rejects_duplicate_keys() -> None:
    report = importlib.import_module("reflect.p2_report")
    duplicated = _attempt_log().replace(
        "schema_version: 1", "schema_version: 1\nschema_version: 1", 1
    )

    with pytest.raises(ValueError, match="duplicate key"):
        report.parse_attempt_log(
            duplicated,
            expected_registry_sha256=REGISTRY_DIGEST,
            registry_names=REGISTRY_NAMES,
        )


@pytest.mark.parametrize(
    "command",
    [
        ["uv", "run", "python", "scripts/fetch_reference.py", "--all-metadata-only"],
        [*_all_command(), "--name", "alpha"],
        [*_name_command("alpha")[:-1], "--all-metadata-only"],
        _name_command("unknown"),
        ["sh", "-c", "echo fabricated"],
    ],
)
def test_attempt_commands_are_exactly_allowlisted(command: list[str]) -> None:
    report = importlib.import_module("reflect.p2_report")
    raw = yaml.safe_load(_attempt_log())
    raw["attempts"][0]["command"] = command

    with pytest.raises(ValueError, match="allowlisted"):
        report.parse_attempt_log(
            yaml.safe_dump(raw, sort_keys=False),
            expected_registry_sha256=REGISTRY_DIGEST,
            registry_names=REGISTRY_NAMES,
        )


def test_final_publication_requires_all_metadata_command() -> None:
    report = importlib.import_module("reflect.p2_report")
    raw = yaml.safe_load(_attempt_log(final=True))
    raw["attempts"][-1]["command"] = _name_command("alpha")

    with pytest.raises(ValueError, match="final publication.*all-metadata"):
        report.parse_attempt_log(
            yaml.safe_dump(raw, sort_keys=False),
            expected_registry_sha256=REGISTRY_DIGEST,
            registry_names=REGISTRY_NAMES,
        )


def test_attempt_history_requires_global_chronology_and_future_reset() -> None:
    report = importlib.import_module("reflect.p2_report")
    raw = yaml.safe_load(_attempt_log(final=True))
    raw["attempts"][-1]["started_at_utc"] = "2026-08-22T16:49:00Z"
    with pytest.raises(ValueError, match="global chronology"):
        report.parse_attempt_log(
            yaml.safe_dump(raw, sort_keys=False),
            expected_registry_sha256=REGISTRY_DIGEST,
            registry_names=REGISTRY_NAMES,
        )

    raw = yaml.safe_load(_attempt_log())
    raw["attempts"][0]["rate_limit_reset_utc"] = raw["attempts"][0]["finished_at_utc"]
    with pytest.raises(ValueError, match="rate-limit reset.*after"):
        report.parse_attempt_log(
            yaml.safe_dump(raw, sort_keys=False),
            expected_registry_sha256=REGISTRY_DIGEST,
            registry_names=REGISTRY_NAMES,
        )


def test_attempt_history_allows_only_one_final_publication_last() -> None:
    report = importlib.import_module("reflect.p2_report")
    raw = yaml.safe_load(_attempt_log(final=True))
    duplicate = dict(raw["attempts"][-1])
    duplicate["id"] = "second-publication"
    duplicate["started_at_utc"] = "2026-08-22T17:51:00Z"
    duplicate["finished_at_utc"] = "2026-08-22T17:52:00Z"
    raw["attempts"].append(duplicate)

    with pytest.raises(ValueError, match="exactly one.*publication"):
        report.parse_attempt_log(
            yaml.safe_dump(raw, sort_keys=False),
            expected_registry_sha256=REGISTRY_DIGEST,
            registry_names=REGISTRY_NAMES,
        )


@pytest.mark.parametrize("component", ["references", "repos.yaml"])
def test_evidence_snapshot_rejects_symlink_components(
    tmp_path: Path, component: str
) -> None:
    report_io = importlib.import_module("reflect._p2_report_io")
    repository = tmp_path / "repository"
    real = tmp_path / "real"
    real.mkdir()
    (real / "repos.yaml").write_text("registry")
    (real / "repos.lock.yaml").write_text("lock")
    (real / "p2-live-attempts.yaml").write_text("attempts")
    repository.mkdir()
    if component == "references":
        (repository / "references").symlink_to(real, target_is_directory=True)
    else:
        references = repository / "references"
        references.mkdir()
        (references / "repos.yaml").symlink_to(real / "repos.yaml")
        (references / "repos.lock.yaml").write_text("lock")
        (references / "p2-live-attempts.yaml").write_text("attempts")

    with pytest.raises(ValueError, match="symlink|no-follow|regular"):
        report_io.read_evidence_snapshot(repository)


def test_evidence_snapshot_rejects_symlink_in_parent_path(tmp_path: Path) -> None:
    report_io = importlib.import_module("reflect._p2_report_io")
    real_parent = tmp_path / "real-parent"
    repository = real_parent / "repository"
    references = repository / "references"
    references.mkdir(parents=True)
    for name in ("repos.yaml", "repos.lock.yaml", "p2-live-attempts.yaml"):
        (references / name).write_text(name)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="no-follow|symlink"):
        report_io.read_evidence_snapshot(linked_parent / "repository")


def test_git_runner_strips_redirects_and_fixes_hooks_and_fsmonitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_io = importlib.import_module("reflect._p2_report_io")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(report_io.subprocess, "run", fake_run)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/tmp/hostile")
    monkeypatch.setenv("GIT_SSH_COMMAND", "hostile")

    completed = report_io.run_git(tmp_path, ("status", "--short"))

    assert completed.returncode == 0
    assert captured["cwd"] == tmp_path
    environment = captured["env"]
    assert not any(key.startswith("GIT_") and key not in report_io.SAFE_GIT_ENV for key in environment)
    assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
    assert "core.fsmonitor=false" in captured["command"]
    assert "core.hooksPath=/dev/null" in captured["command"]


@pytest.mark.parametrize(
    "path",
    [
        "nested/.env",
        "nested/.env.local",
        "config/credentials.json",
        "config/secrets.yaml",
        "keys/id_rsa",
        "keys/private-key.pem",
        "vendor/source/file.py",
        "models/policy.safetensors",
    ],
)
def test_tracked_boundary_rejects_nested_secrets_checkouts_and_models(path: str) -> None:
    report_io = importlib.import_module("reflect._p2_report_io")
    assert report_io.forbidden_tracked_paths((path,)) == (path,)
    assert report_io.forbidden_tracked_paths(("nested/.env.example",)) == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("registry_entries", True),
        ("tracked_files", 4.0),
        ("ok", 1),
        ("errors", {}),
        ("extra", 0),
    ],
)
def test_audit_json_requires_exact_keys_and_exact_types(
    tmp_path: Path, field: str, value: object
) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    sha, _ = _write_fixture_repository(repository)
    results = _successful_results(report)
    audit = yaml.safe_load(results["audit"].stdout)
    audit[field] = value
    results["audit"] = report.CommandResult(
        report.REQUIRED_COMMANDS["audit"], 0, __import__("json").dumps(audit), ""
    )

    with pytest.raises(RuntimeError, match="audit"):
        report.build_report(
            project_root=repository,
            implementation_sha=sha,
            command_results=results,
            physical_deployment_allowed=False,
            remote_enabled=False,
        )


@pytest.mark.parametrize("name", ["audit", "full_tests", "lock_check", "safety", "diff_check", "boundary_paths", "boundary_large_files"])
def test_each_failed_verification_command_is_rejected(tmp_path: Path, name: str) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    sha, _ = _write_fixture_repository(repository)
    results = _successful_results(report)
    good = results[name]
    results[name] = report.CommandResult(good.command, 7, good.stdout, good.stderr)

    with pytest.raises(RuntimeError, match=name):
        report.build_report(
            project_root=repository,
            implementation_sha=sha,
            command_results=results,
            physical_deployment_allowed=False,
            remote_enabled=False,
        )


def test_safety_types_are_exact_and_checked_before_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    with pytest.raises(RuntimeError, match="boolean"):
        report.require_safe_state(physical_deployment_allowed=0, remote_enabled=False)

    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("command ran before safety rejection")

    monkeypatch.setattr(report, "_run_verification", forbidden)
    monkeypatch.setenv("PHYSICAL_DEPLOYMENT_ALLOWED", "true")
    monkeypatch.setenv("REFLECT_REMOTE_ENABLED", "0")
    with pytest.raises(RuntimeError, match="physical deployment"):
        report.main(["--evidence-base-sha", "0" * 40], root=tmp_path)
    assert called is False


def test_atomic_report_replace_is_fsynced_and_cleans_up_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_io = importlib.import_module("reflect._p2_report_io")
    target = tmp_path / "RUN_REPORT.md"
    target.write_text("old")

    report_io.atomic_write_report(tmp_path, "new")
    assert target.read_text() == "new"
    assert target.stat().st_mode & 0o777 == 0o600

    def failed_replace(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(report_io.os, "replace", failed_replace)
    with pytest.raises(OSError, match="replace failed"):
        report_io.atomic_write_report(tmp_path, "unpublished")
    assert target.read_text() == "new"
    assert not list(tmp_path.glob(".RUN_REPORT.md.*"))


def test_report_html_escapes_untrusted_command_output(tmp_path: Path) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    sha, _ = _write_fixture_repository(repository)
    results = _successful_results(report)
    current = results["full_tests"]
    results["full_tests"] = report.CommandResult(
        current.command, 0, "<script>alert('x')</script>", "a & b"
    )

    rendered = report.build_report(
        project_root=repository,
        implementation_sha=sha,
        command_results=results,
        physical_deployment_allowed=False,
        remote_enabled=False,
    )

    assert "<pre>" in rendered
    assert "&lt;script&gt;" in rendered
    assert "a &amp; b" in rendered
    assert "```text" not in rendered


def test_report_accepts_make_echo_before_safety_json(tmp_path: Path) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    sha, _ = _write_fixture_repository(repository)
    results = _successful_results(report)
    current = results["safety"]
    results["safety"] = report.CommandResult(
        current.command,
        0,
        "UV_CACHE_DIR=.cache/uv uv run python -m reflect.safety check\n"
        '{"simulation_only": true, "remote_enabled": false}\n',
        "",
    )

    rendered = report.build_report(
        project_root=repository,
        implementation_sha=sha,
        command_results=results,
        physical_deployment_allowed=False,
        remote_enabled=False,
    )

    assert "UV_CACHE_DIR=.cache/uv uv run python -m reflect.safety check" in rendered


def test_successful_cli_uses_only_allowlisted_verification_and_atomic_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    sha, _ = _write_fixture_repository(repository)
    expected = _successful_results(report)
    invoked: list[tuple[str, ...]] = []

    def local_result(command: tuple[str, ...], *, root: Path):
        assert root == repository
        invoked.append(command)
        return expected[next(name for name, required in report.REQUIRED_COMMANDS.items() if required == command)]

    monkeypatch.setattr(report, "_run_verification", local_result)
    monkeypatch.setenv("PHYSICAL_DEPLOYMENT_ALLOWED", "false")
    monkeypatch.setenv("REFLECT_REMOTE_ENABLED", "0")

    assert report.main(
        ["--evidence-base-sha", sha], root=repository, expected_registry_entries=2
    ) == 0

    output = (repository / "RUN_REPORT.md").read_text(encoding="utf-8")
    assert output.startswith("# P2 Run Report")
    assert (repository / "RUN_REPORT.md").stat().st_mode & 0o777 == 0o600
    assert invoked == list(report.REQUIRED_COMMANDS.values())
    assert all("scripts/fetch_reference.py" not in command for command in invoked)


@pytest.mark.parametrize("dirt_kind", ["tracked", "untracked"])
def test_cli_rechecks_clean_tree_immediately_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dirt_kind: str
) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    sha, _ = _write_fixture_repository(repository)
    expected = _successful_results(report)
    calls = 0

    def dirtying_result(command: tuple[str, ...], *, root: Path):
        nonlocal calls
        calls += 1
        if calls == len(report.REQUIRED_COMMANDS):
            if dirt_kind == "tracked":
                (root / "tracked.txt").write_text("dirty\n")
            else:
                (root / "small-untracked.txt").write_text("dirty\n")
        name = next(
            name
            for name, required in report.REQUIRED_COMMANDS.items()
            if required == command
        )
        return expected[name]

    monkeypatch.setattr(report, "_run_verification", dirtying_result)
    monkeypatch.setenv("PHYSICAL_DEPLOYMENT_ALLOWED", "false")
    monkeypatch.setenv("REFLECT_REMOTE_ENABLED", "0")

    with pytest.raises(RuntimeError, match="worktree must be clean"):
        report.main(
            ["--evidence-base-sha", sha],
            root=repository,
            expected_registry_entries=2,
        )

    assert not (repository / "RUN_REPORT.md").exists()


@pytest.mark.parametrize("result_name", ["audit", "safety"])
def test_verification_json_rejects_contradictory_duplicate_keys(
    tmp_path: Path, result_name: str
) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    sha, _ = _write_fixture_repository(repository)
    results = _successful_results(report)
    current = results[result_name]
    if result_name == "audit":
        output = (
            '{"ok":false,"registry_entries":2,"lock_entries":2,'
            '"selected_paths":4,"discovered_licenses":1,"tracked_files":4,'
            '"errors":[],"ok":true}'
        )
    else:
        output = (
            '{"simulation_only":true,"remote_enabled":true,'
            '"remote_enabled":false}'
        )
    results[result_name] = report.CommandResult(
        current.command, 0, output, current.stderr
    )

    with pytest.raises(RuntimeError, match=f"{result_name}.*duplicate"):
        report.build_report(
            project_root=repository,
            implementation_sha=sha,
            command_results=results,
            physical_deployment_allowed=False,
            remote_enabled=False,
        )


def test_every_attempt_requires_finished_at_utc() -> None:
    report = importlib.import_module("reflect.p2_report")
    raw = yaml.safe_load(_attempt_log(final=True))
    del raw["attempts"][0]["finished_at_utc"]

    with pytest.raises(ValueError, match="finished_at_utc.*required"):
        report.parse_attempt_log(
            yaml.safe_dump(raw, sort_keys=False),
            expected_registry_sha256=REGISTRY_DIGEST,
            registry_names=REGISTRY_NAMES,
        )


@pytest.mark.parametrize("implementation_sha", ["A" * 40, "a" * 64, "<script>"])
def test_pure_report_builder_requires_lowercase_40_hex_sha(
    tmp_path: Path, implementation_sha: str
) -> None:
    report = importlib.import_module("scripts.write_p2_report")
    core = importlib.import_module("reflect.p2_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    _write_fixture_repository(repository)

    with pytest.raises(ValueError, match="lowercase 40"):
        core.build_report(
            registry_bytes=(repository / "references" / "repos.yaml").read_bytes(),
            lock_bytes=(repository / "references" / "repos.lock.yaml").read_bytes(),
            attempt_bytes=(
                repository / "references" / "p2-live-attempts.yaml"
            ).read_bytes(),
            implementation_sha=implementation_sha,
            command_results=_successful_results(report),
            physical_deployment_allowed=False,
            remote_enabled=False,
        )
