from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path

import pytest
import yaml

from reflect.source_compat import (
    CSV_HEADER,
    CompatibilityClass,
    CompatibilityEvidence,
    SmokeStatus,
    consolidate_compatibility,
    load_operation_manifest,
    source_lock_sha256,
    validate_fragment,
    write_compatibility_outputs,
)
from reflect.source_ops import (
    OperationSpec,
    SourceOperation,
    run_source_operation,
    write_fragment_create_only,
)
from reflect.sources import (
    LicenseStatus,
    LockedEntry,
    MetadataStatus,
    PathStatus,
    SourceLock,
    load_registry,
)


def complete_lock() -> tuple[object, SourceLock]:
    registry = load_registry(Path("references/repos.yaml"))
    entries = []
    for index, source in enumerate(registry.repositories):
        entries.append(
            LockedEntry(
                name=source.name,
                url=source.url,
                default_branch="main",
                commit_sha=f"{index + 1:040x}",
                retrieved_at="2026-08-22T00:00:00Z",
                metadata_evidence={"tree": "https://api.github.com/example"},
                license_spdx="MIT",
                license_status=LicenseStatus.DISCOVERED.value,
                license_evidence_url="https://example.invalid/license",
                path_statuses={path: PathStatus.EXISTS.value for path in source.selected_paths},
                path_evidence_urls={path: "https://api.github.com/example" for path in source.selected_paths},
                metadata_status=MetadataStatus.RESOLVED.value,
            )
        )
    return registry, SourceLock(
        registry.registry_sha256,
        "2026-08-22T00:00:00Z",
        tuple(entries),
    )


def evidence(**changes: object) -> CompatibilityEvidence:
    values = {
        "registry_sha256": "9" * 64,
        "repository": "example",
        "commit_sha": "a" * 40,
        "experiment": "01_policy_control",
        "selected_path": "src/example.py",
        "operation": "AST_PARSE",
        "platform": "macos-arm64",
        "python_requirement": ">=3.11",
        "compiler_or_runtime": "python-3.11",
        "command": ("ast.parse", "src/example.py"),
        "exit_status": 0,
        "disk_bytes": 12,
        "download_bytes": 0,
        "license_status": "DISCOVERED",
        "license_spdx": "MIT",
        "blocker": None,
        "notes": "syntax parsed without import",
        "runtime_subject": "source_checkout",
        "package_name": None,
        "package_version": None,
        "package_artifact_sha256": None,
        "patch_artifact_sha256": None,
        "findings": {"parsed_files": 1},
        "content_hashes": {"src/example.py": hashlib.sha256(b"x = 1\n").hexdigest()},
    }
    values.update(changes)
    return CompatibilityEvidence.create(**values)


def manifest_payload(registry: object, lock: SourceLock) -> dict[str, object]:
    return {
        "schema_version": 1,
        "registry_sha256": registry.registry_sha256,
        "lock_sha256": source_lock_sha256(lock),
        "repositories": [
            {"repository": item.name, "commit_sha": item.commit_sha}
            for item in lock.entries
        ],
        "operations": [
            {
                "operation_id": "MUJOCO_PACKAGE_SMOKE",
                "repository": "mujoco",
                "operation": "PACKAGE_RUNTIME",
                "runtime_subject": "package",
                "relative_output": "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json",
            }
        ],
        "requirement_observations": [],
        "mujoco_smoke_output": {
            "operation_id": "MUJOCO_PACKAGE_SMOKE",
            "relative_path": "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json",
        },
    }


def test_exact_labels_and_smoke_states() -> None:
    assert {item.value for item in CompatibilityClass} == {
        "WORKS_LOCAL_M2", "WORKS_LOCAL_CPU_WITH_PATCH", "SOURCE_REFERENCE_ONLY",
        "REMOTE_GPU_REQUIRED", "REMOTE_LINUX_REQUIRED", "LICENSE_REVIEW_REQUIRED",
        "STALE_OR_ARCHIVED", "PATH_CHANGED", "NOT_EVALUATED",
    }
    assert {item.value for item in SmokeStatus} == {"NOT_RUN", "PASS", "FAIL", "BLOCKED"}


def test_evidence_is_canonical_strict_and_package_truthful() -> None:
    item = evidence()
    assert json.loads(item.canonical_bytes())["evidence_sha256"] == item.evidence_sha256
    with pytest.raises(ValueError, match="package"):
        evidence(runtime_subject="package")
    package = evidence(
        operation="PACKAGE_RUNTIME", runtime_subject="package", package_name="mujoco",
        package_version="3.3.5", package_artifact_sha256="b" * 64,
    )
    assert package.commit_sha == "a" * 40
    assert package.runtime_subject == "package"


def test_manifest_covers_lock_and_has_one_closed_mujoco_selector(tmp_path: Path) -> None:
    registry, lock = complete_lock()
    path = tmp_path / "manifest.yaml"
    payload = manifest_payload(registry, lock)
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    manifest = load_operation_manifest(path, registry, lock, tmp_path)
    assert len(manifest.repositories) == 45
    assert manifest.mujoco_smoke_output.relative_path.endswith("mujoco-package-smoke.json")
    payload["mujoco_smoke_output"]["relative_path"] = "../escape.json"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    with pytest.raises(ValueError, match="mujoco|path"):
        load_operation_manifest(path, registry, lock, tmp_path)


def test_fragment_lock_binding_and_classification_precedence() -> None:
    registry, lock = complete_lock()
    source = next(item for item in registry.repositories if item.name == "mjctrl")
    locked = next(item for item in lock.entries if item.name == "mjctrl")
    item = evidence(
        registry_sha256=registry.registry_sha256,
        repository="mjctrl",
        commit_sha=locked.commit_sha,
        experiment=source.experiments[0],
        selected_path=source.selected_paths[0],
    )
    validate_fragment(item.to_dict(), registry, lock)
    rows = consolidate_compatibility(registry, lock, (item,), ())
    assert len(rows) == sum(max(1, len(entry.selected_paths)) * len(entry.experiments) for entry in registry.repositories)
    row = next(row for row in rows if row.repository == "mjctrl" and row.selected_path == source.selected_paths[0])
    assert row.classification is CompatibilityClass.SOURCE_REFERENCE_ONLY
    missing = replace(locked, path_statuses={path: ("MISSING" if path == source.selected_paths[0] else "EXISTS") for path in source.selected_paths})
    missing_lock = replace(lock, entries=tuple(missing if entry.name == "mjctrl" else entry for entry in lock.entries))
    rows = consolidate_compatibility(registry, missing_lock, (), ())
    row = next(row for row in rows if row.repository == "mjctrl" and row.selected_path == source.selected_paths[0])
    assert row.classification is CompatibilityClass.PATH_CHANGED


def test_bounded_ast_operation_and_create_only_fragment(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "safe.py").write_text("x = 1\n")
    spec = OperationSpec(
        registry_sha256="9" * 64, repository="example", commit_sha="a" * 40,
        experiment="01_policy_control", selected_path="safe.py",
        operation=SourceOperation.AST_PARSE, license_status="DISCOVERED", license_spdx="MIT",
    )
    item = run_source_operation(spec, checkout)
    assert item.findings == (("parsed_files", 1),)
    destination = tmp_path / "fragments" / "example.json"
    write_fragment_create_only(destination, item)
    with pytest.raises(FileExistsError):
        write_fragment_create_only(destination, item)
    (checkout / "linked.py").symlink_to(tmp_path / "outside.py")
    with pytest.raises(ValueError, match="symlink|regular"):
        run_source_operation(replace(spec, selected_path="linked.py"), checkout)


def test_outputs_have_exact_csv_header_and_are_deterministic(tmp_path: Path) -> None:
    registry, lock = complete_lock()
    rows = consolidate_compatibility(registry, lock, (), ())
    first = write_compatibility_outputs(tmp_path, registry, lock, rows)
    second = write_compatibility_outputs(tmp_path, registry, lock, rows, check=True)
    assert first == second
    assert (tmp_path / "experiments/00_source_audit/results/compatibility.csv").read_text().splitlines()[0] == ",".join(CSV_HEADER)
    maturity = (tmp_path / "docs/MATURITY_LEDGER.md").read_text()
    assert "| project/component | evidence label | evidence source | supported embodiment/task | license | compute requirements | local reproduction status | hardware validation status | known failure modes | role in this program |" in maturity
    assert sum(line.startswith("| ") for line in maturity.splitlines()) == 47
    licenses = (tmp_path / "references/licenses.md").read_text()
    assert "attribution requirement | decision/blocker | review date" in licenses
    source_map = (tmp_path / "docs/SOURCE_MAP.md").read_text()
    assert "local fallback | attribution record" in source_map


def test_experiment_entrypoint_has_standard_dry_run_flags(
    capsys: pytest.CaptureFixture[str]
) -> None:
    module = importlib.import_module("experiments.00_source_audit.run")
    result = module.main(
        [
            "--config", "experiments/00_source_audit/configs/base.yaml",
            "--seed", "7", "--output-dir", "unused", "--dry-run",
            "--max-episodes", "3", "--headless",
        ]
    )
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["seed"] == 7
    assert payload["max_episodes"] == 3
    assert payload["headless"] is True
    assert payload["operations"].count("MUJOCO_PACKAGE_SMOKE") == 1


def test_make_source_audit_is_offline_and_requires_complete_lock() -> None:
    makefile = Path("Makefile").read_text()
    recipe = makefile.split("source-audit:", 1)[1]
    assert "audit_references.py --require-complete" in recipe
    assert "experiments.00_source_audit.run" in recipe
    assert "fetch_reference.py" not in recipe
