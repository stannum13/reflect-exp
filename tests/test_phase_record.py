from __future__ import annotations

import hashlib
import importlib
import importlib.util
from pathlib import Path
import shutil
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
    invalid_report: bool = False,
    report_replacement: tuple[str, str] | None = None,
    operations_yaml: str | None = None,
) -> tuple[Path, str, str]:
    publisher = importlib.import_module("scripts.publish_phase_record")
    fixture_spec = importlib.util.spec_from_file_location(
        "_phase_record_p3_fixture",
        Path(__file__).with_name("test_p3_commands.py"),
    )
    assert fixture_spec is not None and fixture_spec.loader is not None
    fixture_module = importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixture_module)
    complete = tmp_path / "complete-p3"
    complete.mkdir()
    fixture_module._write_repository(complete)
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

    for source in complete.rglob("*"):
        relative_path = source.relative_to(complete)
        if not source.is_file() or ".git" in relative_path.parts:
            continue
        relative = relative_path.as_posix()
        if relative in {"docs/RUN_MANIFEST.yaml", "RUN_REPORT.md"}:
            continue
        target = repository / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    operation_path = repository / "experiments/00_source_audit/configs/operation-manifest.yaml"
    if operations_yaml is not None:
        operation_manifest = yaml.safe_load(operation_path.read_text(encoding="utf-8"))
        operation_manifest["operations"] = yaml.safe_load(operations_yaml)["operations"]
        operation_path.write_text(
            yaml.safe_dump(operation_manifest, sort_keys=False), encoding="utf-8"
        )
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
    report_path = repository / "RUN_REPORT.md"
    if operations_yaml is None and not smoke_symlink:
        reporter = importlib.import_module("scripts.write_p3_report")
        reporter.main(["--evidence-base-sha", evidence_sha], root=repository)
        report = report_path.read_text(encoding="utf-8")
    else:
        headings = (
            "Executive result", "Environment", "Commands", "Tests", "Results",
            "Public-source use", "Interface findings", "Blockers",
            "Highest-value next action", "Safety",
        )
        report = "# P3 Run Report\n\n" + "\n\n".join(
            f"## {heading}\n\nfixture" for heading in headings
        )
        report += f"\n\n- Implementation/evidence-base Git SHA: `{evidence_sha}`\n"
    if report_replacement is not None:
        old, new = report_replacement
        assert old in report
        report = report.replace(old, new, 1)
    if invalid_report:
        report += f"- Other Git SHA: `{evidence_sha}`\n"
    report_path.write_text(report, encoding="utf-8")
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


def test_publish_refuses_temporary_manifest_inode_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(tmp_path)
    original_status = publisher._worktree_status
    calls = 0

    def substitute_on_final_status(root: Path, *, allowed_untracked: frozenset[str] = frozenset()):
        nonlocal calls
        calls += 1
        if allowed_untracked:
            temporary = repository / next(iter(allowed_untracked))
            temporary.unlink()
            temporary.write_text("attacker bytes\n", encoding="utf-8")
            return b""
        return original_status(root, allowed_untracked=allowed_untracked)

    monkeypatch.setattr(publisher, "_worktree_status", substitute_on_final_status)
    with pytest.raises(ValueError, match="temporary|changed"):
        publisher.publish(
            root=repository,
            phase="p2",
            implementation_sha=evidence_sha,
            report_sha=report_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )
    assert calls >= 2


def test_publish_restores_old_manifest_when_temp_is_swapped_at_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p2_report_repository(tmp_path)
    manifest_path = repository / "docs/RUN_MANIFEST.yaml"
    original = manifest_path.read_bytes()
    real_replace = publisher.os.replace
    attacked = False

    def replace_with_swap(source: str, target: str, **kwargs: object) -> None:
        nonlocal attacked
        if not attacked and source.startswith(".RUN_MANIFEST.yaml.phase-"):
            attacked = True
            directory_fd = kwargs["src_dir_fd"]
            publisher.os.unlink(source, dir_fd=directory_fd)
            descriptor = publisher.os.open(
                source, publisher.os.O_WRONLY | publisher.os.O_CREAT | publisher.os.O_EXCL,
                0o600, dir_fd=directory_fd,
            )
            publisher.os.write(descriptor, b"attacker bytes\n")
            publisher.os.close(descriptor)
        real_replace(source, target, **kwargs)

    monkeypatch.setattr(publisher.os, "replace", replace_with_swap)
    with pytest.raises(ValueError, match="temporary|publication"):
        publisher.publish(
            root=repository, phase="p2", implementation_sha=evidence_sha,
            report_sha=report_sha, manifest_path="docs/RUN_MANIFEST.yaml",
        )
    assert attacked and manifest_path.read_bytes() == original


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


def test_p3_publish_rejects_report_with_unknown_provenance(tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p3_report_repository(
        tmp_path, invalid_report=True
    )
    with pytest.raises(ValueError, match="provenance|report"):
        publisher.publish(
            root=repository,
            phase="p3",
            implementation_sha=evidence_sha,
            report_sha=report_sha,
            manifest_path="docs/RUN_MANIFEST.yaml",
        )


@pytest.mark.parametrize(
    "replacement",
    [
        ("gate passed locally", "gate blocked locally"),
        ("Git blob `", "Git blob `0"),
        ("MuJoCo 3.12.0", "MuJoCo 3.11.0"),
        ("No physical motor messages were sent.", "Physical motor messages were sent."),
    ],
)
def test_p3_publish_rejects_semantically_mutated_report(
    tmp_path: Path, replacement: tuple[str, str]
) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")
    repository, evidence_sha, report_sha = _p3_report_repository(
        tmp_path, report_replacement=replacement
    )
    with pytest.raises(ValueError, match="canonical|report"):
        publisher.publish(
            root=repository, phase="p3", implementation_sha=evidence_sha,
            report_sha=report_sha, manifest_path="docs/RUN_MANIFEST.yaml",
        )


def test_publisher_git_disables_lazy_fetch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    publisher = importlib.import_module("scripts.publish_phase_record")

    def missing_promised_blob(*args: object, **kwargs: object):
        assert kwargs["env"]["GIT_NO_LAZY_FETCH"] == "1"
        return subprocess.CompletedProcess(args[0], 1, b"", b"missing promised blob")

    monkeypatch.setattr(publisher.subprocess, "run", missing_promised_blob)
    with pytest.raises(RuntimeError, match="missing promised blob"):
        publisher._git(tmp_path, "cat-file", "blob", "a" * 40)


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
                "    relative_output: experiments/00_source_audit/results/fragments/mujoco-package-smoke.json\n"
                "  - operation_id: MUJOCO_PACKAGE_SMOKE\n"
                "    runtime_subject: package\n"
                "    relative_output: experiments/00_source_audit/results/fragments/mujoco-package-smoke.json\n",
            "exactly one MUJOCO_PACKAGE_SMOKE",
        ),
        (
                "operations:\n"
                "  - operation_id: MUJOCO_PACKAGE_SMOKE\n"
                "    runtime_subject: source_checkout\n"
                "    relative_output: experiments/00_source_audit/results/fragments/mujoco-package-smoke.json\n",
            "runtime_subject",
        ),
        (
                "operations:\n"
                "  - operation_id: MUJOCO_PACKAGE_SMOKE\n"
                "    runtime_subject: package\n"
                "    relative_output: experiments/00_source_audit/results/fragments/other.json\n",
            "output identity",
        ),
        (
                "operations:\n"
                "  - operation_id: MUJOCO_PACKAGE_SMOKE\n"
                "    runtime_subject: package\n"
                "    relative_output: experiments/00_source_audit/results/fragments/mujoco-package-smoke.json\n"
                "  - operation_id: OTHER\n"
                "    runtime_subject: source_checkout\n"
                "    relative_output: experiments/00_source_audit/results/fragments/mujoco-package-smoke.json\n",
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
