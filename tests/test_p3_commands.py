from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess

import pytest
import yaml

from reflect.source_evidence import canonical_sha256


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _lock_digest(lock: dict[str, object]) -> str:
    entries = []
    for item in lock["entries"]:
        entries.append({
            "name": item["name"], "url": item["url"], "default_branch": item["default_branch"],
            "commit_sha": item["commit_sha"], "retrieved_at": item["retrieved_at"],
            "metadata_evidence": dict(sorted(item["metadata_evidence"].items())),
            "license_spdx": item["license_spdx"], "license_status": item["license_status"],
            "license_evidence_url": item["license_evidence_url"],
            "path_statuses": dict(sorted(item["path_statuses"].items())),
            "path_evidence_urls": dict(sorted(item["path_evidence_urls"].items())),
            "metadata_status": item["metadata_status"],
        })
    return hashlib.sha256(_canonical({
        "registry_sha256": lock["registry_sha256"], "generated_at": lock["generated_at"],
        "entries": entries,
    })).hexdigest()


def _commit(repository: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repository, check=True)
    environment = {**os.environ, "GIT_AUTHOR_DATE": "2026-08-23T00:00:00Z", "GIT_COMMITTER_DATE": "2026-08-23T00:00:00Z"}
    subprocess.run(
        ["git", "-c", "user.name=P3 Test", "-c", "user.email=p3@example.invalid", "commit", "-m", message],
        cwd=repository, env=environment, check=True, capture_output=True,
    )
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True).stdout.strip()


def _write_repository(root: Path) -> str:
    subprocess.run(["git", "init", "-b", "integration/autonomous-run"], cwd=root, check=True, capture_output=True)
    names = ["mujoco", *(f"repo-{index:02d}" for index in range(44))]
    selected_paths = {
        name: (["src", *(f"src/path-{index:03d}" for index in range(234))]
               if name == "mujoco" else ["src"])
        for name in names
    }
    registry = {
        "verified_at": "2026-08-22", "large_model_downloads_default": False,
        "physical_deployment_default": False,
        "repositories": [{
            "name": name, "url": f"https://github.com/example/{name}",
            "mode": "DIRECT_DEPENDENCY" if name == "mujoco" else "SPARSE_REFERENCE",
            "experiments": ["01_policy_control"], "selected_paths": selected_paths[name],
            "use": "bounded fixture", "caveat": "fixture only",
        } for name in names],
    }
    references = root / "references"
    references.mkdir()
    registry_path = references / "repos.yaml"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False))
    registry_sha = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    lock = {
        "registry_sha256": registry_sha, "generated_at": "2026-08-22T00:00:00Z",
        "entries": [{
            "name": name, "url": f"https://github.com/example/{name}", "default_branch": "main",
            "commit_sha": f"{index + 1:040x}", "retrieved_at": "2026-08-22T00:00:00Z",
            "metadata_evidence": {"tree": "https://api.github.com/example"},
            "license_spdx": "MIT", "license_status": "DISCOVERED",
            "license_evidence_url": "https://api.github.com/license",
            "path_statuses": {path: "EXISTS" for path in selected_paths[name]},
            "path_evidence_urls": {
                path: f"https://api.github.com/tree/{path}"
                for path in selected_paths[name]
            },
            "metadata_status": "RESOLVED",
        } for index, name in enumerate(names)],
    }
    (references / "repos.lock.yaml").write_text(yaml.safe_dump(lock, sort_keys=False))
    (references / "p2-live-attempts.yaml").write_text(yaml.safe_dump({
        "schema_version": 1, "registry_sha256": registry_sha,
        "attempts": [{"id": "complete", "published_lock": True, "exit_code": 0}],
    }, sort_keys=False))
    (references / "licenses.md").write_text("# Source licenses\n\n| repository | status |\n|---|---|\n| all | DISCOVERED |\n")
    output = "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json"
    operation = {
        "operation_id": "MUJOCO_PACKAGE_SMOKE", "repository": "mujoco",
        "operation": "PACKAGE_RUNTIME", "runtime_subject": "package",
        "experiment": "01_policy_control", "selected_path": "src",
        "command": ["mujoco", "headless-one-step"], "relative_output": output,
        "platform": "darwin-arm64", "python_requirement": ">=3.11,<3.12",
        "compiler_or_runtime": "mujoco-3.12.0;python-3.11.13", "timeout_seconds": 60,
        "download_ceiling_bytes": 0, "disk_ceiling_bytes": 536870912,
        "no_copy": True, "no_models": True, "package_name": "mujoco",
        "file_ceiling_bytes": 2097152, "file_count_ceiling": 512, "depth_ceiling": 8,
    }
    manifest = {
        "schema_version": 1, "registry_sha256": registry_sha, "lock_sha256": _lock_digest(lock),
        "repositories": [{"repository": item["name"], "commit_sha": item["commit_sha"],
                          "paths": [{"path": path, "status": status}
                                    for path, status in sorted(item["path_statuses"].items())]}
                         for item in lock["entries"]],
        "operations": [operation], "requirement_observations": [],
        "mujoco_smoke_output": {"operation_id": "MUJOCO_PACKAGE_SMOKE", "relative_path": output},
    }
    config = root / "experiments/00_source_audit/configs"
    config.mkdir(parents=True)
    (config / "operation-manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    source_compat = importlib.import_module("reflect.source_compat")
    sources = importlib.import_module("reflect.sources")
    qpos = [float(0.01 + index).hex() for index in range(8)]
    qvel = [float(0.02 + index).hex() for index in range(7)]
    xml_sha = "a" * 64
    installed_sha = "b" * 64
    lock_artifact_sha = "c" * 64
    smoke = source_compat.CompatibilityEvidence.create(
        registry_sha256=registry_sha, repository="mujoco", commit_sha=f"{1:040x}",
        experiment="01_policy_control", selected_path="src",
        operation_id="MUJOCO_PACKAGE_SMOKE", operation="PACKAGE_RUNTIME",
        platform="darwin-arm64", python_requirement=">=3.11,<3.12",
        compiler_or_runtime="mujoco-3.12.0;python-3.11.13",
        command=("mujoco", "headless-one-step"), exit_status=0,
        disk_bytes=4096, download_bytes=0, license_status="DISCOVERED",
        license_spdx="MIT", blocker=None, notes="bounded fixture smoke",
        runtime_subject="package", package_name="mujoco", package_version="3.12.0",
        package_artifact_sha256=installed_sha,
        package_lock_artifact_sha256=lock_artifact_sha,
        patch_artifact_sha256=None,
        findings={
            "duration_ns": 1,
            "artifact": {
                "wheel_filename": "mujoco-3.12.0.whl",
                "lock_artifact_sha256": lock_artifact_sha,
                "installed_tree_sha256": installed_sha,
                "record_entries": 3, "installed_files": 3, "installed_bytes": 4096,
                "executed_origins": [
                    {"module": "mujoco", "record_path": "mujoco/__init__.py",
                     "sha256": "d" * 64, "native_extension": False},
                    {"module": "mujoco._functions", "record_path": "mujoco/_functions.py",
                     "sha256": "e" * 64, "native_extension": False},
                    {"module": "mujoco._structs", "record_path": "mujoco/_structs.so",
                     "sha256": "f" * 64, "native_extension": True},
                ],
            },
            "dynamics": {
                "xml_sha256": xml_sha, "control": [float(0.125).hex()],
                "timestep": float(0.002).hex(), "nq": 8, "nv": 7, "nu": 1,
                "post_step": {
                    "time": float(0.002).hex(), "qpos": qpos, "qvel": qvel,
                    "qpos_sha256": canonical_sha256(qpos),
                    "qvel_sha256": canonical_sha256(qvel),
                },
            },
        },
        content_hashes={"inline-model.xml": xml_sha},
    )
    smoke_path = root / output
    smoke_path.parent.mkdir(parents=True)
    smoke_path.write_bytes(smoke.canonical_bytes())
    registry_model = sources.load_registry(registry_path)
    lock_model = sources.load_lock(references / "repos.lock.yaml")
    manifest_model = source_compat.load_operation_manifest(
        config / "operation-manifest.yaml", registry_model, lock_model, root
    )
    rows = source_compat.consolidate_compatibility(
        registry_model, lock_model, (smoke,), manifest_model.requirement_observations,
        manifest_model,
    )
    assert len(rows) == 279
    source_compat.write_compatibility_outputs(
        root, registry_model, lock_model, rows, manifest=manifest_model,
        seen_operation_ids=frozenset({"MUJOCO_PACKAGE_SMOKE"}),
        passed_operation_ids=frozenset({"MUJOCO_PACKAGE_SMOKE"}),
    )
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs/ASSUMPTIONS.md").write_text("# Assumptions\n\nP3 evidence is simulation-only.\n")
    (root / "docs/RUN_MANIFEST.yaml").write_text(yaml.safe_dump({
        "schema_version": 1, "safety": {"physical_deployment_allowed": False, "remote_enabled": False},
        "stages": {"p2": "complete", "p3": "complete"}, "phase_records": {},
    }, sort_keys=False))
    return _commit(root, "p3 evidence")


def test_reporter_renders_exact_section35_report_and_is_deterministic(tmp_path: Path) -> None:
    report = importlib.import_module("scripts.write_p3_report")
    outputs = []
    for name in ("a", "b"):
        repository = tmp_path / name
        repository.mkdir()
        sha = _write_repository(repository)
        assert report.main(["--evidence-base-sha", sha], root=repository) == 0
        output = (repository / "RUN_REPORT.md").read_bytes()
        assert (repository / "RUN_REPORT.md").stat().st_mode & 0o777 == 0o600
        outputs.append(output)
    assert outputs[0] == outputs[1]
    text = outputs[0].decode()
    assert text.startswith("# P3 Run Report\n")
    assert text.count("Implementation/evidence-base Git SHA") == 1
    for heading in report.SECTION_HEADINGS:
        assert f"## {heading}\n" in text
    assert "mujoco-package-smoke.json" in text and "3.12.0" in text
    with pytest.raises(ValueError, match="provenance"):
        report.validate_rendered_report(text + f"\n- Other Git SHA: `{sha}`\n", sha)


def test_reporter_replaces_only_prior_tracked_report_candidate(tmp_path: Path) -> None:
    report = importlib.import_module("scripts.write_p3_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    _write_repository(repository)
    (repository / "RUN_REPORT.md").write_text("# Prior phase report\n")
    sha = _commit(repository, "prior report candidate")
    assert report.main(["--evidence-base-sha", sha], root=repository) == 0
    assert (repository / "RUN_REPORT.md").read_text().startswith("# P3 Run Report\n")
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repository, check=True, capture_output=True, text=True).stdout
    assert status.strip() == "M RUN_REPORT.md"


@pytest.mark.parametrize("kind", ["tracked", "untracked"])
def test_reporter_requires_exact_clean_head(tmp_path: Path, kind: str) -> None:
    report = importlib.import_module("scripts.write_p3_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    sha = _write_repository(repository)
    target = repository / ("docs/ASSUMPTIONS.md" if kind == "tracked" else "untracked.txt")
    target.write_text("dirty\n")
    with pytest.raises(RuntimeError, match="clean"):
        report.main(["--evidence-base-sha", sha], root=repository)
    assert not (repository / "RUN_REPORT.md").exists()


@pytest.mark.parametrize("mutation", ["duplicate_yaml", "alternate", "escape", "future_hash", "duplicate_operation"])
def test_reporter_rejects_manifest_selector_mutations(tmp_path: Path, mutation: str) -> None:
    report = importlib.import_module("scripts.write_p3_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    _write_repository(repository)
    path = repository / "experiments/00_source_audit/configs/operation-manifest.yaml"
    if mutation == "duplicate_yaml":
        path.write_text(path.read_text() + "schema_version: 1\n")
    else:
        raw = yaml.safe_load(path.read_text())
        if mutation == "alternate":
            raw["mujoco_smoke_output"]["relative_path"] = "experiments/00_source_audit/results/fragments/other.json"
        elif mutation == "escape":
            raw["mujoco_smoke_output"]["relative_path"] = "../escape.json"
        elif mutation == "future_hash":
            raw["operations"][0]["evidence_sha256"] = "0" * 64
        else:
            raw["operations"].append(dict(raw["operations"][0]))
        path.write_text(yaml.safe_dump(raw, sort_keys=False))
    sha = _commit(repository, mutation)
    with pytest.raises(ValueError, match="manifest|selector|operation|duplicate"):
        report.main(["--evidence-base-sha", sha], root=repository)


def test_reporter_rejects_smoke_hash_tamper_and_forbidden_tracked_path(tmp_path: Path) -> None:
    report = importlib.import_module("scripts.write_p3_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    _write_repository(repository)
    smoke = repository / "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json"
    raw = json.loads(smoke.read_text())
    raw["package_version"] = "3.11.0"
    smoke.write_bytes(_canonical(raw))
    sha = _commit(repository, "tamper")
    with pytest.raises(ValueError, match="smoke|package runtime"):
        report.main(["--evidence-base-sha", sha], root=repository)
    (repository / "models").mkdir()
    (repository / "models/policy.safetensors").write_bytes(b"model")
    sha = _commit(repository, "model")
    with pytest.raises(ValueError, match="forbidden"):
        report.main(["--evidence-base-sha", sha], root=repository)


def test_reporter_rejects_minimal_hashed_smoke_scaffold(tmp_path: Path) -> None:
    report = importlib.import_module("scripts.write_p3_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    _write_repository(repository)
    smoke_path = repository / "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json"
    raw = {
        "schema_version": 1, "evidence_type": "COMPATIBILITY",
        "operation_id": "MUJOCO_PACKAGE_SMOKE", "repository": "mujoco",
        "runtime_subject": "package", "package_name": "mujoco",
        "package_version": "3.12.0",
        "registry_sha256": hashlib.sha256((repository / "references/repos.yaml").read_bytes()).hexdigest(),
    }
    raw["evidence_sha256"] = hashlib.sha256(_canonical(raw)).hexdigest()
    smoke_path.write_bytes(_canonical(raw))
    sha = _commit(repository, "minimal smoke scaffold")
    with pytest.raises(ValueError, match="compatibility fragment|missing|extra"):
        report.main(["--evidence-base-sha", sha], root=repository)


@pytest.mark.parametrize("mutation", ["no_models", "output_escape"])
def test_reporter_rejects_operation_safety_and_output_escape(
    tmp_path: Path, mutation: str
) -> None:
    report = importlib.import_module("scripts.write_p3_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    _write_repository(repository)
    path = repository / "experiments/00_source_audit/configs/operation-manifest.yaml"
    raw = yaml.safe_load(path.read_text())
    if mutation == "no_models":
        raw["operations"][0]["no_models"] = False
    else:
        raw["operations"][0]["relative_output"] = "../mujoco-package-smoke.json"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    sha = _commit(repository, "unsafe operation")
    with pytest.raises(ValueError, match="operation|unsafe|output|safety"):
        report.main(["--evidence-base-sha", sha], root=repository)


def test_reporter_rejects_safety_enablement(tmp_path: Path) -> None:
    report = importlib.import_module("scripts.write_p3_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    _write_repository(repository)
    path = repository / "docs/RUN_MANIFEST.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["safety"]["remote_enabled"] = True
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    sha = _commit(repository, "unsafe")
    with pytest.raises(ValueError, match="safety"):
        report.main(["--evidence-base-sha", sha], root=repository)


def test_reporter_installs_network_denial_before_evidence_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = importlib.import_module("scripts.write_p3_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    sha = _write_repository(repository)
    original = report._read_snapshot

    def probe(*args: object, **kwargs: object):
        with pytest.raises(RuntimeError, match="network"):
            socket.getaddrinfo("example.com", 443)
        return original(*args, **kwargs)

    monkeypatch.setattr(report, "_read_snapshot", probe)
    assert report.main(["--evidence-base-sha", sha], root=repository) == 0


def test_reporter_subprocess_allowlist_cannot_be_expanded_by_caller() -> None:
    report = importlib.import_module("scripts.write_p3_report")
    with pytest.raises(RuntimeError, match="non-allowlisted subprocess"):
        report._checked_git_shape(("fetch", "https://example.invalid/repository"))


def test_reporter_git_reads_disable_promisor_lazy_fetch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    report = importlib.import_module("scripts.write_p3_report")

    def refuse_without_offline_env(*args: object, **kwargs: object):
        assert kwargs["env"]["GIT_NO_LAZY_FETCH"] == "1"
        return subprocess.CompletedProcess(args[0], 1, b"", b"missing promised blob")

    monkeypatch.setattr(report.subprocess, "run", refuse_without_offline_env)
    with pytest.raises(RuntimeError, match="missing promised blob"):
        report._git(tmp_path, "cat-file", "blob", "a" * 40)


def test_reporter_atomic_failure_preserves_old_report_and_owned_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = importlib.import_module("scripts.write_p3_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "RUN_REPORT.md").write_text("old\n")
    original = (repository / "RUN_REPORT.md").read_bytes()
    monkeypatch.setattr(report.os, "replace", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        report._atomic_write_report(repository, "new\n")
    assert (repository / "RUN_REPORT.md").read_bytes() == original
    assert not tuple(repository.glob(".RUN_REPORT.md.p3-*"))


def test_reporter_rejects_temporary_inode_substitution(tmp_path: Path) -> None:
    report = importlib.import_module("scripts.write_p3_report")
    repository = tmp_path / "repository"
    repository.mkdir()

    def substitute(temporary: str) -> None:
        target = repository / temporary
        target.unlink()
        target.write_text("attacker bytes\n")

    with pytest.raises(ValueError, match="temporary|changed"):
        report._atomic_write_report(repository, "validated\n", substitute)
    assert not (repository / "RUN_REPORT.md").exists()


def test_reporter_restores_old_report_when_temp_is_swapped_at_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = importlib.import_module("scripts.write_p3_report")
    repository = tmp_path / "repository"
    repository.mkdir()
    target = repository / "RUN_REPORT.md"
    target.write_text("old report\n")
    original = target.read_bytes()
    real_replace = report.os.replace
    attacked = False

    def replace_with_swap(source: str, destination: str, **kwargs: object) -> None:
        nonlocal attacked
        if not attacked and source.startswith(".RUN_REPORT.md.p3-"):
            attacked = True
            directory_fd = kwargs["src_dir_fd"]
            report.os.unlink(source, dir_fd=directory_fd)
            descriptor = report.os.open(
                source, report.os.O_WRONLY | report.os.O_CREAT | report.os.O_EXCL,
                0o600, dir_fd=directory_fd,
            )
            report.os.write(descriptor, b"attacker bytes\n")
            report.os.close(descriptor)
        real_replace(source, destination, **kwargs)

    monkeypatch.setattr(report.os, "replace", replace_with_swap)
    with pytest.raises(ValueError, match="temporary|publication"):
        report._atomic_write_report(repository, "validated report\n")
    assert attacked and target.read_bytes() == original
