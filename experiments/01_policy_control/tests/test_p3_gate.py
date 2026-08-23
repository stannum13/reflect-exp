from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
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


def test_create_only_publication_rejects_temporary_inode_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_link = gate.os.link
    attacked = False

    def swap_before_link(source: str, target: str, **kwargs: object) -> None:
        nonlocal attacked
        attacked = True
        directory_fd = kwargs["src_dir_fd"]
        gate.os.unlink(source, dir_fd=directory_fd)
        descriptor = gate.os.open(
            source,
            gate.os.O_WRONLY | gate.os.O_CREAT | gate.os.O_EXCL,
            0o600,
            dir_fd=directory_fd,
        )
        gate.os.write(descriptor, b"attacker\n")
        gate.os.close(descriptor)
        real_link(source, target, **kwargs)

    monkeypatch.setattr(gate.os, "link", swap_before_link)
    with pytest.raises(gate.P3GateError, match="inode|publication|temporary"):
        gate._publish_create_only(tmp_path, "gate.yaml", b"authentic\n")
    assert attacked
    assert not (tmp_path / "gate.yaml").exists()


def test_state_index_search_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository, _, evidence = _closed_repository(tmp_path)
    monkeypatch.setattr(gate, "MAX_ANCESTRY_COMMITS", 1)
    with pytest.raises(gate.P3GateError, match="bound|ancestry|state-index"):
        gate.require_p3_gate(repository, evidence)


def test_capture_requires_clean_head(tmp_path: Path) -> None:
    repository, _, _ = _closed_repository(tmp_path)
    destination = repository / "second-gate.yaml"
    (repository / "untracked.txt").write_text("dirty\n")
    with pytest.raises(gate.P3GateError, match="clean"):
        gate.write_p3_gate(repository, destination)
