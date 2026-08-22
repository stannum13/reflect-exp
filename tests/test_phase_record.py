from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import subprocess

import pytest
import yaml


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_bytes(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
    ).stdout


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _p2_report_repository(
    tmp_path: Path,
    *,
    p2_state: str = "complete",
    physical_allowed: bool = False,
    remote_enabled: bool = False,
    report_extra_path: bool = False,
    intervening_commit: bool = False,
    p2_member_symlink: bool = False,
    p2_record_null: bool = False,
) -> tuple[Path, str, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-b", "integration/autonomous-run")
    _git(repository, "config", "user.name", "Phase Test")
    _git(repository, "config", "user.email", "phase@example.invalid")
    (repository / "references").mkdir()
    for name, content in {
        "repos.yaml": "repositories: []\n",
        "repos.lock.yaml": "repositories: []\n",
        "p2-live-attempts.yaml": "attempts: []\n",
    }.items():
        (repository / "references" / name).write_text(content, encoding="utf-8")
    if p2_member_symlink:
        member = repository / "references" / "p2-live-attempts.yaml"
        member.unlink()
        member.symlink_to("repos.yaml")
    (repository / "docs").mkdir()
    phase_records_text = (
        "phase_records:\n  p2: null\n" if p2_record_null else "phase_records: {}\n"
    )
    (repository / "docs" / "RUN_MANIFEST.yaml").write_text(
        "schema_version: 1\n"
        "safety:\n"
        f"  physical_deployment_allowed: {str(physical_allowed).lower()}\n"
        f"  remote_enabled: {str(remote_enabled).lower()}\n"
        "stages:\n"
        f"  p2: {p2_state}\n"
        + phase_records_text,
        encoding="utf-8",
    )
    evidence_sha = _commit(repository, "evidence")
    if intervening_commit:
        (repository / "intervening.txt").write_text("intervening\n", encoding="utf-8")
        _commit(repository, "intervening")
    (repository / "RUN_REPORT.md").write_text(
        "# P2 Run Report\n\n"
        f"- Implementation/evidence-base Git SHA: `{evidence_sha}`\n",
        encoding="utf-8",
    )
    if report_extra_path:
        (repository / "extra-report-path.txt").write_text("extra\n", encoding="utf-8")
    report_sha = _commit(repository, "report")
    return repository, evidence_sha, report_sha


def _p3_report_repository(
    tmp_path: Path,
    *,
    smoke_symlink: bool = False,
    operations_yaml: str = (
        "operations:\n"
        "  - operation_id: MUJOCO_PACKAGE_SMOKE\n"
        "    runtime_subject: package\n"
        "    relative_path: experiments/00_source_audit/results/fragments/mujoco-package-smoke.json\n"
    ),
) -> tuple[Path, str, str]:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, p2_evidence_sha, p2_report_sha = _p2_report_repository(tmp_path)
    publisher.publish(
        root=repository,
        phase="p2",
        implementation_sha=p2_evidence_sha,
        report_sha=p2_report_sha,
        manifest_path="docs/RUN_MANIFEST.yaml",
    )
    _commit(repository, "p2 state index")
    p2_record = yaml.safe_load(
        (repository / "docs" / "RUN_MANIFEST.yaml").read_text(encoding="utf-8")
    )["phase_records"]["p2"]

    operation_path = (
        repository
        / "experiments"
        / "00_source_audit"
        / "configs"
        / "operation-manifest.yaml"
    )
    operation_path.parent.mkdir(parents=True)
    operation_path.write_text(
        "mujoco_smoke_output:\n"
        "  operation_id: MUJOCO_PACKAGE_SMOKE\n"
        "  relative_path: experiments/00_source_audit/results/fragments/mujoco-package-smoke.json\n"
        + operations_yaml,
        encoding="utf-8",
    )
    contents = {
        "experiments/00_source_audit/results/compatibility.csv": "name,status\nmujoco,SUPPORTED\n",
        "references/licenses.md": "# Licenses\n",
        "docs/SOURCE_MAP.md": "# Source map\n",
        "docs/MATURITY_LEDGER.md": "# Maturity ledger\n",
        "experiments/00_source_audit/RESULTS.md": "# Results\n",
        "experiments/00_source_audit/INTERFACE_FINDINGS.md": "# Interfaces\n",
        "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json": '{"ok":true}\n',
    }
    for relative, content in contents.items():
        target = repository / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if smoke_symlink:
        smoke_path = repository / (
            "experiments/00_source_audit/results/fragments/"
            "mujoco-package-smoke.json"
        )
        smoke_path.unlink()
        smoke_path.symlink_to("../../../../docs/SOURCE_MAP.md")
    manifest_path = repository / "docs" / "RUN_MANIFEST.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["stages"]["p3"] = "complete"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    evidence_sha = _commit(repository, "p3 evidence")
    (repository / "RUN_REPORT.md").write_text(
        "# P3 Run Report\n\n"
        f"- Implementation/evidence-base Git SHA: `{evidence_sha}`\n",
        encoding="utf-8",
    )
    report_sha = _commit(repository, "p3 report")
    assert yaml.safe_load(manifest_path.read_text(encoding="utf-8"))[
        "phase_records"
    ]["p2"] == p2_record
    return repository, evidence_sha, report_sha


def test_canonical_record_bytes_are_compact_sorted_utf8_without_newline() -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")

    assert publisher.canonical_record_bytes({"z": "é", "a": 1}) == (
        b'{"a":1,"z":"\xc3\xa9"}'
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"value": 1.0}, "floats"),
        ({"value": True}, "booleans"),
        ({"value": "e\u0301"}, "NFKC"),
        ({1: "value"}, "string keys"),
    ],
)
def test_canonical_record_bytes_reject_noncanonical_domain(
    value: object, message: str
) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")

    with pytest.raises(ValueError, match=message):
        publisher.canonical_record_bytes(value)


def test_strict_yaml_rejects_duplicate_keys() -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")

    with pytest.raises(ValueError, match="strict UTF-8 YAML"):
        publisher._strict_yaml(b"phase_records: {}\nphase_records: {}\n", "fixture")


def test_publish_and_validate_p2_record_from_git_objects(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(tmp_path)

    assert publisher.main(
        [
            "publish",
            "--phase",
            "p2",
            "--implementation-evidence-git-sha",
            evidence_sha,
            "--report-commit-git-sha",
            report_sha,
            "--run-manifest",
            "docs/RUN_MANIFEST.yaml",
        ],
        root=repository,
    ) == 0
    manifest = yaml.safe_load(
        (repository / "docs" / "RUN_MANIFEST.yaml").read_text(encoding="utf-8")
    )
    record = manifest["phase_records"]["p2"]
    assert set(record) == {
        "phase_id",
        "lifecycle_state",
        "implementation_evidence_git_sha",
        "report_commit_git_sha",
        "report_path",
        "report_git_blob_id",
        "report_sha256",
        "bound_evidence_git_sha",
        "artifact_ledger_sha256",
    }
    assert record["implementation_evidence_git_sha"] == evidence_sha
    assert record["bound_evidence_git_sha"] == evidence_sha
    assert record["report_commit_git_sha"] == report_sha
    assert record["report_path"] == "RUN_REPORT.md"
    report_bytes = _git_bytes(repository, "show", f"{report_sha}:RUN_REPORT.md")
    assert record["report_sha256"] == hashlib.sha256(report_bytes).hexdigest()
    assert len(record["artifact_ledger_sha256"]) == 64

    members = []
    for path in sorted(
        [
            "references/repos.yaml",
            "references/repos.lock.yaml",
            "references/p2-live-attempts.yaml",
            "RUN_REPORT.md",
        ],
        key=lambda value: value.encode("utf-8"),
    ):
        source = report_sha if path == "RUN_REPORT.md" else evidence_sha
        blob = _git(repository, "rev-parse", f"{source}:{path}")
        content = _git_bytes(repository, "cat-file", "blob", blob)
        members.append(
            {
                "path": path,
                "source_commit_git_sha": source,
                "git_blob_id": blob,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    ledger = {
        "schema_version": 1,
        "phase_id": "p2",
        "implementation_evidence_git_sha": evidence_sha,
        "report_commit_git_sha": report_sha,
        "members": members,
    }
    assert record["artifact_ledger_sha256"] == hashlib.sha256(
        publisher.canonical_record_bytes(ledger)
    ).hexdigest()

    state_index_sha = _commit(repository, "state index")
    assert publisher.main(
        [
            "validate",
            "--phase",
            "p2",
            "--state-index-commit",
            state_index_sha,
            "--run-manifest",
            "docs/RUN_MANIFEST.yaml",
        ],
        root=repository,
    ) == 0


def test_publisher_accepts_only_the_canonical_run_manifest_path() -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")

    with pytest.raises(ValueError, match="exactly docs/RUN_MANIFEST.yaml"):
        publisher._manifest_relative_path("other.yaml")


def test_publish_refuses_concurrent_manifest_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(tmp_path)
    original = publisher._atomic_write_manifest

    def drift_then_write(*args: object, **kwargs: object) -> None:
        path = repository / "docs/RUN_MANIFEST.yaml"
        path.write_bytes(path.read_bytes() + b"concurrent_key: true\n")
        original(*args, **kwargs)

    monkeypatch.setattr(publisher, "_atomic_write_manifest", drift_then_write)
    with pytest.raises(ValueError, match="changed during publication"):
        publisher.publish(
            root=repository,
            phase="p2",
            implementation_sha=evidence_sha,
            report_sha=report_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )
    assert b"concurrent_key: true" in (repository / "docs/RUN_MANIFEST.yaml").read_bytes()


def test_publish_refuses_concurrent_unrelated_worktree_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(tmp_path)
    original = publisher._atomic_write_manifest

    def drift_then_write(*args: object, **kwargs: object) -> None:
        (repository / "unrelated.txt").write_text("concurrent\n", encoding="utf-8")
        original(*args, **kwargs)

    monkeypatch.setattr(publisher, "_atomic_write_manifest", drift_then_write)
    with pytest.raises(ValueError, match="clean worktree immediately before replacement"):
        publisher.publish(
            root=repository,
            phase="p2",
            implementation_sha=evidence_sha,
            report_sha=report_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )


def test_publish_refuses_present_null_phase_record(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(
        tmp_path, p2_record_null=True
    )

    with pytest.raises(ValueError, match="immutable and differs"):
        publisher.publish(
            root=repository,
            phase="p2",
            implementation_sha=evidence_sha,
            report_sha=report_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )


def test_publish_forces_all_untracked_files_visible(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(tmp_path)
    _git(repository, "config", "status.showUntrackedFiles", "no")
    (repository / "hidden-by-local-config.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(ValueError, match="clean worktree"):
        publisher.publish(
            root=repository,
            phase="p2",
            implementation_sha=evidence_sha,
            report_sha=report_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )


def test_publish_ignores_blob_and_commit_replace_refs(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(tmp_path)
    original_blob = _git(repository, "rev-parse", f"{evidence_sha}:references/repos.yaml")
    replacement = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repository,
        input=b"replacement: true\n",
        check=True,
        capture_output=True,
    ).stdout.decode("ascii").strip()
    _git(repository, "replace", original_blob, replacement)
    _git(repository, "replace", report_sha, evidence_sha)

    publisher.publish(
        root=repository,
        phase="p2",
        implementation_sha=evidence_sha,
        report_sha=report_sha,
        manifest_path="docs/RUN_MANIFEST.yaml",
    )
    record = yaml.safe_load(
        (repository / "docs/RUN_MANIFEST.yaml").read_text(encoding="utf-8")
    )["phase_records"]["p2"]
    true_bytes = _git_bytes(
        repository, "--no-replace-objects", "cat-file", "blob", original_blob
    )
    assert true_bytes == b"repositories: []\n"
    assert record["bound_evidence_git_sha"] == evidence_sha


def test_publish_reissue_validates_equal_record_and_refuses_conflict(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(tmp_path)
    arguments = {
        "root": repository,
        "phase": "p2",
        "implementation_sha": evidence_sha,
        "report_sha": report_sha,
        "manifest_path": "docs/RUN_MANIFEST.yaml",
    }
    publisher.publish(**arguments)
    manifest_path = repository / "docs/RUN_MANIFEST.yaml"
    exact = manifest_path.read_bytes()
    publisher.publish(**arguments)
    assert manifest_path.read_bytes() == exact

    manifest = yaml.safe_load(exact)
    manifest["phase_records"]["p2"]["artifact_ledger_sha256"] = "0" * 64
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="immutable and differs"):
        publisher.publish(**arguments)


def test_cli_rejects_caller_supplied_record_identity() -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    with pytest.raises(SystemExit):
        publisher.main(
            [
                "publish",
                "--phase",
                "p2",
                "--implementation-evidence-git-sha",
                "0" * 40,
                "--report-commit-git-sha",
                "1" * 40,
                "--run-manifest",
                "docs/RUN_MANIFEST.yaml",
                "--artifact-ledger-sha256",
                "2" * 64,
            ]
        )


@pytest.mark.parametrize(
    ("fixture_options", "message"),
    [
        ({"intervening_commit": True}, "only parent"),
        ({"report_extra_path": True}, "change exactly RUN_REPORT.md"),
        ({"p2_member_symlink": True}, "regular Git blob"),
    ],
)
def test_publish_rejects_invalid_report_history_or_p2_member(
    tmp_path: Path, fixture_options: dict[str, bool], message: str
) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(
        tmp_path, **fixture_options
    )
    with pytest.raises(ValueError, match=message):
        publisher.publish(
            root=repository,
            phase="p2",
            implementation_sha=evidence_sha,
            report_sha=report_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )


def test_validate_rejects_state_index_extra_path(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(tmp_path)
    publisher.publish(
        root=repository,
        phase="p2",
        implementation_sha=evidence_sha,
        report_sha=report_sha,
        manifest_path="docs/RUN_MANIFEST.yaml",
    )
    (repository / "extra-index-path.txt").write_text("extra\n", encoding="utf-8")
    state_index_sha = _commit(repository, "bad state index")
    with pytest.raises(ValueError, match="change exactly the run manifest"):
        publisher.validate(
            root=repository,
            phase="p2",
            state_index_sha=state_index_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )


def test_publish_rejects_phase_that_is_not_complete(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(
        tmp_path, p2_state="in_progress"
    )

    with pytest.raises(ValueError, match="stages.p2 must be complete"):
        publisher.publish(
            root=repository,
            phase="p2",
            implementation_sha=evidence_sha,
            report_sha=report_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )


@pytest.mark.parametrize("authority", ["physical", "remote"])
def test_publish_rejects_enabled_execution_authority(
    tmp_path: Path, authority: str
) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(
        tmp_path,
        physical_allowed=authority == "physical",
        remote_enabled=authority == "remote",
    )

    with pytest.raises(ValueError, match="physical and remote authority must remain false"):
        publisher.publish(
            root=repository,
            phase="p2",
            implementation_sha=evidence_sha,
            report_sha=report_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )


@pytest.mark.parametrize("drift", ["stage", "safety"])
def test_validate_rejects_current_gate_regression(tmp_path: Path, drift: str) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(tmp_path)
    publisher.publish(
        root=repository,
        phase="p2",
        implementation_sha=evidence_sha,
        report_sha=report_sha,
        manifest_path="docs/RUN_MANIFEST.yaml",
    )
    state_index_sha = _commit(repository, "state index")
    manifest_path = repository / "docs" / "RUN_MANIFEST.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if drift == "stage":
        manifest["stages"]["p2"] = "in_progress"
    else:
        manifest["safety"]["remote_enabled"] = True
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="current run manifest gate regressed"):
        publisher.validate(
            root=repository,
            phase="p2",
            state_index_sha=state_index_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )


def test_publish_and_validate_p3_record_with_manifest_selected_smoke(
    tmp_path: Path,
) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p3_report_repository(tmp_path)
    manifest_path = repository / "docs" / "RUN_MANIFEST.yaml"
    p2_before = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))[
        "phase_records"
    ]["p2"]

    publisher.publish(
        root=repository,
        phase="p3",
        implementation_sha=evidence_sha,
        report_sha=report_sha,
        manifest_path="docs/RUN_MANIFEST.yaml",
    )

    records = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))["phase_records"]
    assert records["p2"] == p2_before
    assert records["p3"]["phase_id"] == "p3"
    expected_members = [
        "experiments/00_source_audit/configs/operation-manifest.yaml",
        "experiments/00_source_audit/results/compatibility.csv",
        "references/licenses.md",
        "docs/SOURCE_MAP.md",
        "docs/MATURITY_LEDGER.md",
        "experiments/00_source_audit/RESULTS.md",
        "experiments/00_source_audit/INTERFACE_FINDINGS.md",
        "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json",
        "RUN_REPORT.md",
    ]
    members = []
    for path in sorted(expected_members, key=lambda value: value.encode("utf-8")):
        source = report_sha if path == "RUN_REPORT.md" else evidence_sha
        blob = _git(repository, "rev-parse", f"{source}:{path}")
        members.append(
            {
                "path": path,
                "source_commit_git_sha": source,
                "git_blob_id": blob,
                "sha256": hashlib.sha256(
                    _git_bytes(repository, "cat-file", "blob", blob)
                ).hexdigest(),
            }
        )
    ledger = {
        "schema_version": 1,
        "phase_id": "p3",
        "implementation_evidence_git_sha": evidence_sha,
        "report_commit_git_sha": report_sha,
        "members": members,
    }
    assert records["p3"]["artifact_ledger_sha256"] == hashlib.sha256(
        publisher.canonical_record_bytes(ledger)
    ).hexdigest()
    state_index_sha = _commit(repository, "p3 state index")
    publisher.validate(
        root=repository,
        phase="p3",
        state_index_sha=state_index_sha,
        manifest_path="docs/RUN_MANIFEST.yaml",
    )


def test_p3_publisher_rejects_symlink_smoke_artifact(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p3_report_repository(
        tmp_path, smoke_symlink=True
    )

    with pytest.raises(ValueError, match="regular Git blob"):
        publisher.publish(
            root=repository,
            phase="p3",
            implementation_sha=evidence_sha,
            report_sha=report_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )


@pytest.mark.parametrize(
    ("operations_yaml", "message"),
    [
        ("operations: []\n", "exactly one MUJOCO_PACKAGE_SMOKE"),
        (
            "operations:\n"
            "  - operation_id: MUJOCO_PACKAGE_SMOKE\n"
            "    runtime_subject: package\n"
            "    relative_path: experiments/00_source_audit/results/fragments/mujoco-package-smoke.json\n"
            "  - operation_id: MUJOCO_PACKAGE_SMOKE\n"
            "    runtime_subject: package\n"
            "    relative_path: experiments/00_source_audit/results/fragments/mujoco-package-smoke.json\n",
            "exactly one MUJOCO_PACKAGE_SMOKE",
        ),
        (
            "operations:\n"
            "  - operation_id: MUJOCO_PACKAGE_SMOKE\n"
            "    runtime_subject: source_checkout\n"
            "    relative_path: experiments/00_source_audit/results/fragments/mujoco-package-smoke.json\n",
            "runtime_subject",
        ),
        (
            "operations:\n"
            "  - operation_id: MUJOCO_PACKAGE_SMOKE\n"
            "    runtime_subject: package\n"
            "    relative_path: experiments/00_source_audit/results/fragments/other.json\n",
            "output identity",
        ),
        (
            "operations:\n"
            "  - operation_id: MUJOCO_PACKAGE_SMOKE\n"
            "    runtime_subject: package\n"
            "    relative_path: experiments/00_source_audit/results/fragments/mujoco-package-smoke.json\n"
            "  - operation_id: OTHER\n"
            "    runtime_subject: source_checkout\n"
            "    relative_path: experiments/00_source_audit/results/fragments/mujoco-package-smoke.json\n",
            "output collision",
        ),
    ],
)
def test_p3_publisher_rejects_invalid_smoke_operation_inventory(
    tmp_path: Path, operations_yaml: str, message: str
) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p3_report_repository(
        tmp_path, operations_yaml=operations_yaml
    )

    with pytest.raises(ValueError, match=message):
        publisher.publish(
            root=repository,
            phase="p3",
            implementation_sha=evidence_sha,
            report_sha=report_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )
