from __future__ import annotations

from dataclasses import replace
import importlib
from importlib import metadata
import json
from pathlib import Path

import pytest

from reflect.source_compat import (
    ManifestOperation,
    OperationManifest,
    OutputSelector,
    source_lock_sha256,
)
from reflect.sources import (
    LicenseStatus,
    LockedEntry,
    MetadataStatus,
    PathStatus,
    SourceLock,
    load_registry,
)


_smoke = importlib.import_module("experiments.00_source_audit.src.smoke")
run_mujoco_smoke = _smoke.run_mujoco_smoke
write_mujoco_smoke = _smoke.write_mujoco_smoke


def test_locked_runtime_has_mujoco_3x() -> None:
    version = metadata.version("mujoco")
    assert version == "3.12.0"


def complete_lock() -> tuple[object, SourceLock]:
    registry = load_registry(Path("references/repos.yaml"))
    entries = tuple(
        LockedEntry(
            name=source.name, url=source.url, default_branch="main",
            commit_sha=f"{index + 1:040x}", retrieved_at="2026-08-22T00:00:00Z",
            metadata_evidence={"tree": "https://api.github.com/example"},
            license_spdx="MIT", license_status=LicenseStatus.DISCOVERED.value,
            license_evidence_url="https://example.invalid/license",
            path_statuses={path: PathStatus.EXISTS.value for path in source.selected_paths},
            path_evidence_urls={path: "https://api.github.com/example" for path in source.selected_paths},
            metadata_status=MetadataStatus.RESOLVED.value,
        )
        for index, source in enumerate(registry.repositories)
    )
    return registry, SourceLock(registry.registry_sha256, "2026-08-22T00:00:00Z", entries)


def manifest(registry: object, lock: SourceLock) -> OperationManifest:
    operation = ManifestOperation(
        "MUJOCO_PACKAGE_SMOKE", "mujoco", "PACKAGE_RUNTIME", "package",
        "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json",
    )
    return OperationManifest(
        1, registry.registry_sha256, source_lock_sha256(lock), (), (operation,), (),
        OutputSelector(
            "MUJOCO_PACKAGE_SMOKE",
            "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json",
        ),
    )


def test_headless_one_step_smoke_binds_package_not_git_execution() -> None:
    registry, lock = complete_lock()
    item = run_mujoco_smoke(registry, lock)
    findings = dict(item.findings)
    assert item.runtime_subject == "package"
    assert item.package_name == "mujoco"
    assert item.package_version == metadata.version("mujoco")
    assert item.package_artifact_sha256 is not None
    assert item.exit_status == 0
    assert findings["simulation_time"] > 0
    assert findings["finite_time"] is True
    assert findings["finite_qpos"] is True
    assert findings["finite_qvel"] is True
    assert item.commit_sha not in item.command
    assert "viewer" not in " ".join(item.command).lower()
    second = run_mujoco_smoke(registry, lock)
    first_semantics = item.to_dict(False)
    second_semantics = second.to_dict(False)
    first_semantics["findings"].pop("duration_ns")
    second_semantics["findings"].pop("duration_ns")
    assert first_semantics == second_semantics


def test_smoke_writer_uses_only_closed_manifest_output_and_refuses_overwrite(tmp_path: Path) -> None:
    registry, lock = complete_lock()
    operation_manifest = manifest(registry, lock)
    path = write_mujoco_smoke(operation_manifest, registry, lock, tmp_path)
    assert path.relative_to(tmp_path).as_posix() == operation_manifest.mujoco_smoke_output.relative_path
    payload = json.loads(path.read_text())
    assert payload["package_version"] == metadata.version("mujoco")
    with pytest.raises(FileExistsError):
        write_mujoco_smoke(operation_manifest, registry, lock, tmp_path)
    invalid = replace(
        operation_manifest,
        mujoco_smoke_output=OutputSelector("MUJOCO_PACKAGE_SMOKE", "elsewhere.json"),
    )
    with pytest.raises(ValueError, match="selector"):
        write_mujoco_smoke(invalid, registry, lock, tmp_path)


def test_smoke_writer_rejects_symlinked_output_parent(tmp_path: Path) -> None:
    registry, lock = complete_lock()
    outside = tmp_path / "outside"
    outside.mkdir()
    experiment = tmp_path / "experiments" / "00_source_audit"
    experiment.mkdir(parents=True)
    (experiment / "results").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        write_mujoco_smoke(manifest(registry, lock), registry, lock, tmp_path)
    assert tuple(outside.iterdir()) == ()
