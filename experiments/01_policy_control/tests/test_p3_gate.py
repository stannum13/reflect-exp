from __future__ import annotations

import importlib
import importlib.util
import fcntl
import os
from pathlib import Path
import stat
import subprocess

import pytest
import yaml


gate = importlib.import_module("experiments.01_policy_control.src.p3_gate")
runner = importlib.import_module("experiments.01_policy_control.run")


def _closed_repository(tmp_path: Path) -> tuple[Path, Path, object]:
    fixture_path = Path(__file__).parents[3] / "tests/test_phase_record.py"
    spec = importlib.util.spec_from_file_location("_p4_phase_fixture", fixture_path)
    assert spec is not None and spec.loader is not None
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    repository, evidence_sha, report_sha = fixture._p3_report_repository(tmp_path)
    publisher = importlib.import_module("scripts.publish_phase_record")
    publisher.publish(
        root=repository,
        phase="p3",
        implementation_sha=evidence_sha,
        report_sha=report_sha,
        manifest_path="docs/RUN_MANIFEST.yaml",
    )
    state_index_sha = fixture._commit(repository, "p3 state index")
    publisher.validate(
        root=repository,
        phase="p3",
        state_index_sha=state_index_sha,
        manifest_path="docs/RUN_MANIFEST.yaml",
    )
    destination = repository / "p3-gate.yaml"
    gate.write_p3_gate(repository, destination)
    return repository, destination, gate.load_p3_gate(destination)


def test_remote_fails_before_import_or_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REFLECT_REMOTE_ENABLED", "1")
    output = tmp_path / "output"
    assert runner.main(
        [
            "--config", "missing", "--p3-gate", "missing", "--phase", "pilot",
            "--output-dir", str(output), "--headless", "--dry-run",
        ]
    ) == 2
    assert not output.exists()


def test_gate_round_trip_reconstructs_closed_historical_records(tmp_path: Path) -> None:
    repository, _, evidence = _closed_repository(tmp_path)
    gate.require_p3_gate(repository, evidence)
    assert evidence.schema_version == 2
    assert evidence.p2_state_index_git_sha != evidence.p2_report_commit_git_sha
    assert evidence.p3_state_index_git_sha != evidence.p3_report_commit_git_sha
    assert evidence.p3_implementation_evidence_git_sha == evidence.p3_bound_evidence_git_sha
    assert evidence.physical_deployment_allowed is False
    assert evidence.remote_execution_allowed is False
    assert evidence.runtime_network_allowed is False
    assert set(evidence.files) == set(gate.REQUIRED_ARTIFACTS)
    assert evidence.files["maturity_ledger"].path.as_posix() == "docs/MATURITY_LEDGER.md"
    assert evidence.files["mujoco_smoke"].path.as_posix().endswith("/mujoco-package-smoke.json")
    assert evidence.mujoco_package == "mujoco"
    assert evidence.mujoco_version == "3.12.0"


def test_current_artifact_edits_do_not_replace_historical_evidence(tmp_path: Path) -> None:
    repository, _, evidence = _closed_repository(tmp_path)
    (repository / "docs/SOURCE_MAP.md").write_text("later phase content\n")
    gate.require_p3_gate(repository, evidence)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("record_hash", "record"),
        ("state_index", "state-index"),
        ("manifest_blob", "capture|blob"),
        ("artifact_hash", "artifact|hash"),
        ("runtime_network", "network"),
    ],
)
def test_gate_rejects_caller_authored_or_tampered_provenance(
    tmp_path: Path, mutation: str, message: str
) -> None:
    repository, destination, _ = _closed_repository(tmp_path)
    raw = yaml.safe_load(destination.read_text(encoding="utf-8"))
    if mutation == "record_hash":
        raw["p3_phase_record_sha256"] = "0" * 64
    elif mutation == "state_index":
        raw["p3_state_index_git_sha"] = raw["p3_report_commit_git_sha"]
    elif mutation == "manifest_blob":
        raw["run_manifest_capture_git_blob_id"] = "0" * 40
    elif mutation == "artifact_hash":
        raw["files"]["source_map"]["sha256"] = "0" * 64
    else:
        raw["runtime_network_allowed"] = True
    destination.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
    with pytest.raises(gate.P3GateError, match=message):
        gate.require_p3_gate(repository, gate.load_p3_gate(destination))


@pytest.mark.parametrize("mutation", ["record", "stage", "physical", "remote"])
def test_current_manifest_non_regression_is_fail_closed(
    tmp_path: Path, mutation: str
) -> None:
    repository, _, evidence = _closed_repository(tmp_path)
    manifest_path = repository / "docs/RUN_MANIFEST.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if mutation == "record":
        raw["phase_records"]["p2"]["report_sha256"] = "0" * 64
    elif mutation == "stage":
        raw["stages"]["p3"] = "in_progress"
    elif mutation == "physical":
        raw["safety"]["physical_deployment_allowed"] = True
    else:
        raw["safety"]["remote_enabled"] = True
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(gate.P3GateError, match="current|safety|stage|record"):
        gate.require_p3_gate(repository, evidence)


def test_gate_uses_hardened_local_git_without_lazy_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def promised_blob_missing(*args: object, **kwargs: object):
        assert kwargs["env"]["GIT_NO_LAZY_FETCH"] == "1"
        assert kwargs["env"]["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert "fetch" not in args[0]
        return subprocess.CompletedProcess(args[0], 1, b"", b"missing promised blob")

    monkeypatch.setattr(gate.subprocess, "run", promised_blob_missing)
    with pytest.raises(gate.P3GateError, match="missing promised blob"):
        gate._git(tmp_path, "cat-file", "blob", "a" * 40)
    with pytest.raises(gate.P3GateError, match="non-allowlisted"):
        gate._git(tmp_path, "fetch", "origin")


def test_gate_publication_is_create_only_and_reissue_is_exact(tmp_path: Path) -> None:
    repository, destination, _ = _closed_repository(tmp_path)
    original = destination.read_bytes()
    gate.write_p3_gate(repository, destination)
    assert destination.read_bytes() == original
    destination.write_bytes(b"conflict\n")
    with pytest.raises(gate.P3GateError, match="conflict|existing"):
        gate.write_p3_gate(repository, destination)


def test_gate_rejects_duplicate_yaml_and_symlink_destination(tmp_path: Path) -> None:
    repository, destination, _ = _closed_repository(tmp_path)
    destination.write_text(destination.read_text() + "schema_version: 2\n")
    with pytest.raises(gate.P3GateError, match="YAML|duplicate|schema"):
        gate.load_p3_gate(destination)
    destination.unlink()
    destination.symlink_to("docs/RUN_MANIFEST.yaml")
    with pytest.raises(gate.P3GateError, match="regular|symlink|existing"):
        gate.write_p3_gate(repository, destination)


def test_create_only_publication_does_not_use_swappable_temporary_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_link(*args: object, **kwargs: object) -> None:
        raise AssertionError("direct create-only publication must not link a temp path")

    monkeypatch.setattr(gate.os, "link", forbidden_link)
    gate._publish_create_only(tmp_path, "gate.yaml", b"authentic\n")
    assert (tmp_path / "gate.yaml").read_bytes() == b"authentic\n"


def test_create_only_publication_lock_is_bounded_and_fail_closed(tmp_path: Path) -> None:
    directory_fd = gate._open_directory_path_no_follow(tmp_path)
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(gate.P3GateError, match="locked"):
            gate._publish_create_only(tmp_path, "gate.yaml", b"authentic\n")
        assert not (tmp_path / "gate.yaml").exists()
    finally:
        fcntl.flock(directory_fd, fcntl.LOCK_UN)
        gate.os.close(directory_fd)


def test_create_only_publication_rejects_post_create_destination_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = gate.os.open
    created = False
    attacked = False

    def swap_before_destination_open(
        path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        nonlocal attacked, created
        if created and not attacked and path == "gate.yaml" and dir_fd is not None:
            attacked = True
            gate.os.unlink(path, dir_fd=dir_fd)
            attacker = real_open(
                path,
                gate.os.O_WRONLY | gate.os.O_CREAT | gate.os.O_EXCL,
                0o600,
                dir_fd=dir_fd,
            )
            gate.os.write(attacker, b"attacker\n")
            gate.os.close(attacker)
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == "gate.yaml" and flags & gate.os.O_CREAT:
            created = True
        return descriptor

    monkeypatch.setattr(gate.os, "open", swap_before_destination_open)
    with pytest.raises(gate.P3GateError, match="publication|destination|inode"):
        gate._publish_create_only(tmp_path, "gate.yaml", b"authentic\n")
    assert attacked
    assert (tmp_path / "gate.yaml").read_bytes() == b"attacker\n"


def test_create_only_publication_preserves_unowned_post_verification_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fsync = gate.os.fsync
    attacked = False

    def swap_before_final_identity_check(descriptor: int) -> None:
        nonlocal attacked
        if not attacked and stat.S_ISDIR(gate.os.fstat(descriptor).st_mode):
            attacked = True
            gate.os.unlink("gate.yaml", dir_fd=descriptor)
            attacker = gate.os.open(
                "gate.yaml",
                gate.os.O_WRONLY | gate.os.O_CREAT | gate.os.O_EXCL,
                0o600,
                dir_fd=descriptor,
            )
            gate.os.write(attacker, b"unowned\n")
            gate.os.close(attacker)
        real_fsync(descriptor)

    monkeypatch.setattr(gate.os, "fsync", swap_before_final_identity_check)
    with pytest.raises(gate.P3GateError, match="publication|destination|inode"):
        gate._publish_create_only(tmp_path, "gate.yaml", b"authentic\n")
    assert attacked
    assert (tmp_path / "gate.yaml").read_bytes() == b"unowned\n"


def test_create_only_publication_has_no_final_stat_to_return_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_stat = gate.os.stat
    real_unlink = gate.os.unlink
    real_open = gate.os.open
    attacked = False

    def swap_after_path_stat(path: str, **kwargs: object) -> os.stat_result:
        nonlocal attacked
        result = real_stat(path, **kwargs)
        if not attacked and path == "gate.yaml" and kwargs.get("dir_fd") is not None:
            attacked = True
            directory_fd = kwargs["dir_fd"]
            real_unlink(path, dir_fd=directory_fd)
            attacker = real_open(
                path,
                gate.os.O_WRONLY | gate.os.O_CREAT | gate.os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            gate.os.write(attacker, b"after-stat\n")
            gate.os.close(attacker)
        return result

    monkeypatch.setattr(gate.os, "stat", swap_after_path_stat)
    gate._publish_create_only(tmp_path, "gate.yaml", b"authentic\n")
    assert not attacked
    assert (tmp_path / "gate.yaml").read_bytes() == b"authentic\n"


def test_create_only_failure_never_enters_cleanup_stat_unlink_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fsync = gate.os.fsync
    real_stat = gate.os.stat
    real_unlink = gate.os.unlink
    real_open = gate.os.open
    cleanup_started = False
    attacked = False

    def fail_directory_fsync(descriptor: int) -> None:
        nonlocal cleanup_started
        if stat.S_ISDIR(gate.os.fstat(descriptor).st_mode):
            cleanup_started = True
            raise OSError("forced directory fsync failure")
        real_fsync(descriptor)

    def swap_during_cleanup_stat(path: str, **kwargs: object) -> os.stat_result:
        nonlocal attacked
        result = real_stat(path, **kwargs)
        if (
            cleanup_started
            and not attacked
            and path == "gate.yaml"
            and kwargs.get("dir_fd") is not None
        ):
            attacked = True
            directory_fd = kwargs["dir_fd"]
            real_unlink(path, dir_fd=directory_fd)
            attacker = real_open(
                path,
                gate.os.O_WRONLY | gate.os.O_CREAT | gate.os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            gate.os.write(attacker, b"cleanup-race\n")
            gate.os.close(attacker)
        return result

    monkeypatch.setattr(gate.os, "fsync", fail_directory_fsync)
    monkeypatch.setattr(gate.os, "stat", swap_during_cleanup_stat)
    with pytest.raises(gate.P3GateError, match="fsync|publication"):
        gate._publish_create_only(tmp_path, "gate.yaml", b"authentic\n")
    assert not attacked
    assert (tmp_path / "gate.yaml").read_bytes() == b"authentic\n"


def test_state_index_search_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository, _, evidence = _closed_repository(tmp_path)
    monkeypatch.setattr(gate, "MAX_ANCESTRY_COMMITS", 1)
    with pytest.raises(gate.P3GateError, match="bound|ancestry|state-index"):
        gate.require_p3_gate(repository, evidence)


def test_sealed_capture_must_be_on_current_head_first_parent_ancestry(
    tmp_path: Path,
) -> None:
    repository, _, evidence = _closed_repository(tmp_path)
    tree = subprocess.run(
        ["git", "write-tree"], cwd=repository, capture_output=True, check=True, text=True
    ).stdout.strip()
    unrelated = subprocess.run(
        ["git", "commit-tree", tree],
        cwd=repository,
        input="unrelated root\n",
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "checkout", "--detach", unrelated], cwd=repository, check=True
    )
    with pytest.raises(gate.P3GateError, match="capture|ancestry|root|unrelated"):
        gate.require_p3_gate(repository, evidence)


def test_sealed_capture_to_current_head_walk_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, _, evidence = _closed_repository(tmp_path)
    for index in range(2):
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", f"later {index}"],
            cwd=repository,
            capture_output=True,
            check=True,
        )
    monkeypatch.setattr(gate, "MAX_ANCESTRY_COMMITS", 1)
    with pytest.raises(gate.P3GateError, match="capture|bound|ancestry"):
        gate.require_p3_gate(repository, evidence)


def test_sealed_capture_rejects_merge_in_current_head_ancestry(
    tmp_path: Path,
) -> None:
    repository, _, evidence = _closed_repository(tmp_path)
    capture = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "checkout", "-b", "side"],
        cwd=repository,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "side"],
        cwd=repository,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "checkout", "--detach", capture],
        cwd=repository,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "first parent"],
        cwd=repository,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "merge", "--no-ff", "side", "-m", "merge"],
        cwd=repository,
        capture_output=True,
        check=True,
    )
    with pytest.raises(gate.P3GateError, match="merge"):
        gate.require_p3_gate(repository, evidence)


def test_capture_requires_clean_head(tmp_path: Path) -> None:
    repository, _, _ = _closed_repository(tmp_path)
    destination = repository / "second-gate.yaml"
    (repository / "untracked.txt").write_text("dirty\n")
    with pytest.raises(gate.P3GateError, match="clean"):
        gate.write_p3_gate(repository, destination)
