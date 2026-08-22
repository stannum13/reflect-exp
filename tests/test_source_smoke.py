from __future__ import annotations

import importlib
from importlib import metadata
import json
from pathlib import Path
import platform
import sys

import mujoco
import pytest
import yaml

from reflect.source_compat import (
    source_lock_sha256,
)
from reflect.source_evidence import canonical_sha256
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


def write_manifest(root: Path, registry: object, lock: SourceLock) -> Path:
    output = "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json"
    payload = {
        "schema_version": 1, "registry_sha256": registry.registry_sha256,
        "lock_sha256": source_lock_sha256(lock),
        "repositories": [
            {"repository": item.name, "commit_sha": item.commit_sha,
             "paths": [{"path": path, "status": status.value}
                       for path, status in sorted(item.path_statuses.items())]}
            for item in lock.entries
        ],
        "operations": [{
            "operation_id": "MUJOCO_PACKAGE_SMOKE", "repository": "mujoco",
            "operation": "PACKAGE_RUNTIME", "runtime_subject": "package",
            "experiment": "01_policy_control", "selected_path": "python",
            "command": ["mujoco", "headless-one-step"], "relative_output": output,
            "platform": f"{platform.system().lower()}-{platform.machine().lower()}",
            "python_requirement": ">=3.11,<3.12",
            "compiler_or_runtime": f"mujoco-{metadata.version('mujoco')};python-{platform.python_version()}",
            "timeout_seconds": 60, "download_ceiling_bytes": 0,
            "disk_ceiling_bytes": 536870912, "no_copy": True, "no_models": True,
            "package_name": "mujoco",
            "file_ceiling_bytes": 2097152, "file_count_ceiling": 512,
            "depth_ceiling": 8,
        }],
        "requirement_observations": [],
        "mujoco_smoke_output": {"operation_id": "MUJOCO_PACKAGE_SMOKE", "relative_path": output},
    }
    path = root / "manifest.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    return path


def test_headless_one_step_smoke_binds_package_not_git_execution() -> None:
    registry, lock = complete_lock()
    item = run_mujoco_smoke(registry, lock)
    findings = dict(item.findings)
    assert item.runtime_subject == "package"
    assert item.package_name == "mujoco"
    assert item.package_version == metadata.version("mujoco")
    assert item.package_artifact_sha256 is not None
    assert item.package_lock_artifact_sha256 == "6d6a18976ea2664ddc38816d50138083dbec95f2d9087d6a6d89a85a083e19b5"
    assert item.exit_status == 0
    artifact = findings["artifact"]
    dynamics = findings["dynamics"]
    assert artifact["installed_tree_sha256"] == item.package_artifact_sha256
    assert artifact["record_entries"] == artifact["installed_files"] > 0
    assert artifact["installed_bytes"] == item.disk_bytes > 0
    origins = {row["module"]: row for row in artifact["executed_origins"]}
    assert {"mujoco", "mujoco._functions", "mujoco._structs"} <= set(origins)
    assert origins["mujoco._functions"]["native_extension"] is True
    model = mujoco.MjModel.from_xml_string(_smoke._XML)
    data = mujoco.MjData(model)
    data.ctrl[:] = [float.fromhex(value) for value in dynamics["control"]]
    mujoco.mj_step(model, data)
    qpos = [float(value).hex() for value in data.qpos]
    qvel = [float(value).hex() for value in data.qvel]
    assert dynamics["xml_sha256"] == dict(item.content_hashes)["inline-model.xml"]
    assert dynamics["nq"] == model.nq and dynamics["nv"] == model.nv and dynamics["nu"] == model.nu
    assert float.fromhex(dynamics["timestep"]) == model.opt.timestep
    assert dynamics["post_step"]["time"] == float(data.time).hex()
    assert dynamics["post_step"]["qpos"] == qpos
    assert dynamics["post_step"]["qvel"] == qvel
    assert dynamics["post_step"]["qpos_sha256"] == canonical_sha256(qpos)
    assert dynamics["post_step"]["qvel_sha256"] == canonical_sha256(qvel)
    assert item.commit_sha not in item.command
    assert "viewer" not in " ".join(item.command).lower()
    second = run_mujoco_smoke(registry, lock)
    first_semantics = item.to_dict(False)
    second_semantics = second.to_dict(False)
    first_semantics["findings"].pop("duration_ns")
    second_semantics["findings"].pop("duration_ns")
    assert first_semantics == second_semantics


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timestep", float("inf").hex()),
        ("time", float("nan").hex()),
        ("control", [float(0.25).hex()]),
        ("nq", 7),
        ("qpos0", float(0).hex()),
    ],
)
def test_smoke_reload_rejects_nonfinite_mismatch_and_noop(field: str, value: object) -> None:
    registry, lock = complete_lock()
    raw = json.loads(run_mujoco_smoke(registry, lock).canonical_bytes())
    dynamics = raw["findings"]["dynamics"]
    if field == "time":
        dynamics["post_step"]["time"] = value
    elif field == "qpos0":
        dynamics["post_step"]["qpos"][0] = value
        dynamics["post_step"]["qpos_sha256"] = canonical_sha256(dynamics["post_step"]["qpos"])
    else:
        dynamics[field] = value
    raw["evidence_sha256"] = canonical_sha256({key: item for key, item in raw.items() if key != "evidence_sha256"})
    with pytest.raises(ValueError, match="dynamics|post-step|hinge"):
        _smoke.CompatibilityEvidence.from_dict(raw)


def test_smoke_rejects_shadowed_executed_native_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lock = complete_lock()
    shadow = tmp_path / "_functions.so"
    shadow.write_bytes(b"shadow")
    monkeypatch.setattr(sys.modules["mujoco._functions"], "__file__", str(shadow))
    with pytest.raises(ValueError, match="outside the verified RECORD"):
        run_mujoco_smoke(registry, lock)


def test_smoke_writer_uses_only_closed_manifest_output_and_refuses_overwrite(tmp_path: Path) -> None:
    registry, lock = complete_lock()
    (tmp_path / "uv.lock").write_bytes(Path("uv.lock").read_bytes())
    manifest_path = write_manifest(tmp_path, registry, lock)
    path = write_mujoco_smoke(manifest_path, registry, lock, tmp_path)
    assert path.relative_to(tmp_path).as_posix() == "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json"
    payload = json.loads(path.read_text())
    assert payload["package_version"] == metadata.version("mujoco")
    with pytest.raises(FileExistsError):
        write_mujoco_smoke(manifest_path, registry, lock, tmp_path)
    raw = yaml.safe_load(manifest_path.read_text())
    raw["repositories"] = []
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(ValueError, match="every locked repository"):
        write_mujoco_smoke(invalid, registry, lock, tmp_path)


def test_smoke_writer_rejects_symlinked_output_parent(tmp_path: Path) -> None:
    registry, lock = complete_lock()
    outside = tmp_path / "outside"
    outside.mkdir()
    experiment = tmp_path / "experiments" / "00_source_audit"
    experiment.mkdir(parents=True)
    (experiment / "results").symlink_to(outside, target_is_directory=True)
    (tmp_path / "uv.lock").write_bytes(Path("uv.lock").read_bytes())
    manifest_path = write_manifest(tmp_path, registry, lock)
    with pytest.raises((OSError, ValueError), match="symlink"):
        write_mujoco_smoke(manifest_path, registry, lock, tmp_path)
    assert tuple(outside.iterdir()) == ()
