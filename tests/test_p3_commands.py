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
    registry = {
        "verified_at": "2026-08-22", "large_model_downloads_default": False,
        "physical_deployment_default": False,
        "repositories": [{
            "name": name, "url": f"https://github.com/example/{name}",
            "mode": "DIRECT_DEPENDENCY" if name == "mujoco" else "SPARSE_REFERENCE",
            "experiments": ["01_policy_control"], "selected_paths": ["src"],
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
            "path_statuses": {"src": "EXISTS"},
            "path_evidence_urls": {"src": "https://api.github.com/tree/src"},
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
                          "paths": [{"path": "src", "status": "EXISTS"}]} for item in lock["entries"]],
        "operations": [operation], "requirement_observations": [],
        "mujoco_smoke_output": {"operation_id": "MUJOCO_PACKAGE_SMOKE", "relative_path": output},
    }
    config = root / "experiments/00_source_audit/configs"
    config.mkdir(parents=True)
    (config / "operation-manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    smoke = {
        "schema_version": 1, "evidence_type": "COMPATIBILITY", "operation_id": "MUJOCO_PACKAGE_SMOKE",
        "repository": "mujoco", "runtime_subject": "package", "package_name": "mujoco",
        "package_version": "3.12.0", "registry_sha256": registry_sha,
    }
    smoke["evidence_sha256"] = hashlib.sha256(_canonical(smoke)).hexdigest()
    smoke_path = root / output
    smoke_path.parent.mkdir(parents=True)
    smoke_path.write_bytes(_canonical(smoke))
    results = root / "experiments/00_source_audit/results"
    csv_rows = ["repository,commit_sha,experiment,reuse_mode,selected_path,path_status,operation,platform,python_requirement,compiler_or_runtime,smoke_command,smoke_status,classification,license_status,license_spdx,disk_bytes,download_bytes,blocker,notes"]
    csv_rows.extend(f"repo-{index},{'1' * 40},01_policy_control,SPARSE_REFERENCE,src,EXISTS,,,,,,NOT_RUN,NOT_EVALUATED,DISCOVERED,MIT,0,0,," for index in range(279))
    (results / "compatibility.csv").write_text("\n".join(csv_rows) + "\n")
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs/SOURCE_MAP.md").write_text("# Source map\n\n| experiment | source |\n|---|---|\n| 01 | pinned |\n")
    maturity = ["# Maturity ledger", "", "| project_or_component | evidence_label | evidence_source | supported_embodiment_or_task | license | compute_requirements | local_reproduction_status | known_failure_modes | role_in_program | hardware_validation_status |", "|---|---|---|---|---|---|---|---|---|---|"]
    maturity.extend(f"| component-{index:02d} | UNVERIFIED | NONE | fixture | MIT | local | NOT_REPRODUCED | none | fixture | NOT_APPLICABLE |" for index in range(46))
    (root / "docs/MATURITY_LEDGER.md").write_text("\n".join(maturity) + "\n")
    (root / "docs/ASSUMPTIONS.md").write_text("# Assumptions\n\nP3 evidence is simulation-only.\n")
    (root / "experiments/00_source_audit/RESULTS.md").write_text("# Experiment 00 results\n\noperational_gate: PASS\n\ncomparative_implementation_time_claim: INCONCLUSIVE\n")
    (root / "experiments/00_source_audit/INTERFACE_FINDINGS.md").write_text("# Interface findings\n\ngate_status: PASS\n")
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
    with pytest.raises(ValueError, match="smoke"):
        report.main(["--evidence-base-sha", sha], root=repository)
    (repository / "models").mkdir()
    (repository / "models/policy.safetensors").write_bytes(b"model")
    sha = _commit(repository, "model")
    with pytest.raises(ValueError, match="forbidden"):
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
