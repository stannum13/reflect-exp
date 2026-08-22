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
    load_manifest_fragments,
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
from reflect.source_evidence import CheckoutEvidence, canonical_sha256
from reflect.source_fetch import lock_yaml_bytes
from scripts.source_audit import main as source_audit_main
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
        "operation_id": "EXAMPLE_AST_PARSE",
        "operation": "AST_PARSE",
        "platform": "macos-arm64",
        "python_requirement": ">=3.11",
        "compiler_or_runtime": "python-3.11",
        "command": ("ast_parse", "src/example.py"),
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
        "package_lock_artifact_sha256": None,
        "patch_artifact_sha256": None,
        "findings": {
            "files": [{
                "path": "src/example.py",
                "sha256": hashlib.sha256(b"x = 1\n").hexdigest(),
                "bytes": 6, "disposition": "PASS", "node_count": 5,
                "failure_line": None, "failure_column": None,
            }],
            "summary": {"files_total": 1, "files_pass": 1, "files_fail": 0},
        },
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
            {
                "repository": item.name,
                "commit_sha": item.commit_sha,
                "paths": [
                    {"path": path, "status": status.value}
                    for path, status in sorted(item.path_statuses.items())
                ],
            }
            for item in lock.entries
        ],
        "operations": [
            {
                "operation_id": "MUJOCO_PACKAGE_SMOKE",
                "repository": "mujoco",
                "operation": "PACKAGE_RUNTIME",
                "runtime_subject": "package",
                "experiment": "01_policy_control",
                "selected_path": "python",
                "command": ["mujoco", "headless-one-step"],
                "relative_output": "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json",
                "platform": "macos-arm64",
                "python_requirement": ">=3.11",
                "compiler_or_runtime": "mujoco-3.12.0;python-3.11",
                "timeout_seconds": 60,
                "download_ceiling_bytes": 0,
                "disk_ceiling_bytes": 536870912,
                "no_copy": True,
                "no_models": True,
                "package_name": "mujoco",
                "file_ceiling_bytes": 2097152, "file_count_ceiling": 512,
                "depth_ceiling": 8,
            },
            {
                "operation_id": "MJCTRL_AST_PARSE",
                "repository": "mjctrl",
                "operation": "AST_PARSE",
                "runtime_subject": "source_checkout",
                "experiment": "01_policy_control",
                "selected_path": "*.py",
                "command": ["ast_parse", "*.py"],
                "relative_output": "experiments/00_source_audit/results/fragments/mjctrl-ast.json",
                "platform": "macos-arm64",
                "python_requirement": ">=3.11",
                "compiler_or_runtime": "python-3.11",
                "timeout_seconds": 60,
                "download_ceiling_bytes": 0,
                "disk_ceiling_bytes": 16777216,
                "no_copy": True,
                "no_models": True,
                "package_name": None,
                "file_ceiling_bytes": 2097152, "file_count_ceiling": 512,
                "depth_ceiling": 8,
            },
            {
                "operation_id": "MJCTRL_CHECKOUT",
                "repository": "mjctrl",
                "operation": "CHECKOUT",
                "runtime_subject": "source_checkout",
                "experiment": "01_policy_control",
                "selected_path": "",
                "command": ["fetch_reference", "--name", "mjctrl", "--sparse-checkout"],
                "relative_output": "experiments/00_source_audit/results/fragments/mjctrl-checkout.json",
                "platform": "macos-arm64",
                "python_requirement": ">=3.11",
                "compiler_or_runtime": "git",
                "timeout_seconds": 3600,
                "download_ceiling_bytes": 536870912,
                "disk_ceiling_bytes": 536870912,
                "no_copy": True,
                "no_models": True,
                "package_name": None,
                "file_ceiling_bytes": 2097152, "file_count_ceiling": 512,
                "depth_ceiling": 8,
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
        repository="mujoco", selected_path="python",
        operation_id="MUJOCO_PACKAGE_SMOKE", operation="PACKAGE_RUNTIME",
        runtime_subject="package", package_name="mujoco",
        package_version="3.12.0", package_artifact_sha256="b" * 64,
        package_lock_artifact_sha256="c" * 64,
        command=("mujoco", "headless-one-step"),
        findings={
            "duration_ns": 1,
            "artifact": {"wheel_filename": "mujoco.whl", "lock_artifact_sha256": "c" * 64,
                         "installed_tree_sha256": "b" * 64, "record_entries": 1,
                         "installed_files": 1, "installed_bytes": 1},
            "dynamics": {"xml_sha256": "8" * 64, "control": [float(0.125).hex()],
                         "timestep": float(0.002).hex(), "nq": 1, "nv": 1, "nu": 1,
                         "post_step": {"time": float(0.002).hex(), "qpos": [float(0).hex()],
                                       "qvel": [float(0).hex()],
                                       "qpos_sha256": canonical_sha256([float(0).hex()]),
                                       "qvel_sha256": canonical_sha256([float(0).hex()])}},
        },
        content_hashes={"inline-model.xml": "8" * 64},
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


def test_manifest_rejects_duplicate_keys_nested_extras_and_operation_collisions(
    tmp_path: Path,
) -> None:
    registry, lock = complete_lock()
    path = tmp_path / "manifest.yaml"
    payload = manifest_payload(registry, lock)
    path.write_text(yaml.safe_dump(payload, sort_keys=False) + "schema_version: 1\n")
    with pytest.raises(ValueError, match="duplicate YAML"):
        load_operation_manifest(path, registry, lock, tmp_path)
    payload["operations"][0]["future_hash"] = "0" * 64
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    with pytest.raises(ValueError, match="operation schema"):
        load_operation_manifest(path, registry, lock, tmp_path)
    payload = manifest_payload(registry, lock)
    payload["operations"][1]["operation_id"] = "MUJOCO_PACKAGE_SMOKE"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    with pytest.raises(ValueError, match="IDs.*unique"):
        load_operation_manifest(path, registry, lock, tmp_path)
    payload = manifest_payload(registry, lock)
    payload["operations"][1]["no_copy"] = False
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    with pytest.raises(ValueError, match="safety"):
        load_operation_manifest(path, registry, lock, tmp_path)
    payload = manifest_payload(registry, lock)
    statement = "requires remote GPU"
    payload["requirement_observations"] = [{
        "repository": "mjctrl", "kind": "REMOTE_GPU", "statement": statement,
        "provenance": "http://untrusted.invalid", "statement_sha256": hashlib.sha256(statement.encode()).hexdigest(),
    }]
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    with pytest.raises(ValueError, match="HTTPS"):
        load_operation_manifest(path, registry, lock, tmp_path)


def test_manifest_fragment_loader_rejects_unknown_paths_and_duplicate_json(
    tmp_path: Path,
) -> None:
    registry, lock = complete_lock()
    source = next(item for item in registry.repositories if item.name == "mjctrl")
    pin = next(item for item in lock.entries if item.name == "mjctrl")
    payload = manifest_payload(registry, lock)
    payload["operations"][1]["selected_path"] = source.selected_paths[0]
    payload["operations"][1]["command"] = ["ast_parse", source.selected_paths[0]]
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False))
    operation_manifest = load_operation_manifest(manifest_path, registry, lock, tmp_path)
    fragment_root = tmp_path / "experiments/00_source_audit/results/fragments"
    fragment_root.mkdir(parents=True)
    item = evidence(
        registry_sha256=registry.registry_sha256, repository="mjctrl",
        commit_sha=pin.commit_sha, experiment="01_policy_control",
        selected_path=source.selected_paths[0], operation_id="MJCTRL_AST_PARSE",
        command=("ast_parse", source.selected_paths[0]),
        findings={
            "files": [{"path": "example.py", "sha256": "8" * 64, "bytes": 1,
                       "disposition": "PASS", "node_count": 1,
                       "failure_line": None, "failure_column": None}],
            "summary": {"files_total": 1, "files_pass": 1, "files_fail": 0},
        },
        content_hashes={"example.py": "8" * 64},
    )
    (fragment_root / "mjctrl-ast.json").write_bytes(item.canonical_bytes())
    checkout = CheckoutEvidence.create(
        registry_sha256=registry.registry_sha256, repository="mjctrl", url=source.url,
        locked_sha=pin.commit_sha, patterns=source.selected_paths,
        commands=(("git", "fetch"),), statuses=(0,), download_bytes=1,
        disk_bytes=1, outcome="PASS", blocker=None,
        content_hashes={"example.py": "8" * 64},
    )
    (fragment_root / "mjctrl-checkout.json").write_bytes(checkout.canonical_bytes())
    fragments, checkouts, seen = load_manifest_fragments(tmp_path, operation_manifest, registry, lock)
    assert len(fragments) == len(checkouts) == 1
    assert seen == {"MJCTRL_AST_PARSE", "MJCTRL_CHECKOUT"}
    (fragment_root / "unknown.json").write_text("{}")
    with pytest.raises(ValueError, match="not declared|count"):
        load_manifest_fragments(tmp_path, operation_manifest, registry, lock)
    (fragment_root / "unknown.json").unlink()
    (fragment_root / "mujoco-package-smoke.json").write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError, match="duplicate JSON"):
        load_manifest_fragments(tmp_path, operation_manifest, registry, lock)
    (fragment_root / "mujoco-package-smoke.json").unlink()
    checkout_path = fragment_root / "mjctrl-checkout.json"
    checkout_path.unlink()
    mismatch = CheckoutEvidence.create(
        registry_sha256=registry.registry_sha256, repository="mjctrl", url=source.url,
        locked_sha=pin.commit_sha, patterns=source.selected_paths,
        commands=(("git", "fetch"),), statuses=(0,), download_bytes=1, disk_bytes=1,
        outcome="PASS", blocker=None, content_hashes={"example.py": "7" * 64},
    )
    checkout_path.write_bytes(mismatch.canonical_bytes())
    with pytest.raises(ValueError, match="content hashes"):
        load_manifest_fragments(tmp_path, operation_manifest, registry, lock)
    checkout_path.unlink()
    failed = CheckoutEvidence.create(
        registry_sha256=registry.registry_sha256, repository="mjctrl", url=source.url,
        locked_sha=pin.commit_sha, patterns=source.selected_paths,
        commands=(("git", "fetch"),), statuses=(1,), download_bytes=1, disk_bytes=0,
        outcome="FAIL", blocker="fetch failed", content_hashes={},
    )
    checkout_path.write_bytes(failed.canonical_bytes())
    with pytest.raises(ValueError, match="PASS checkout"):
        load_manifest_fragments(tmp_path, operation_manifest, registry, lock)
    checkout_path.unlink()
    wrong_url = CheckoutEvidence.create(
        registry_sha256=registry.registry_sha256, repository="mjctrl",
        url="https://github.com/example/wrong", locked_sha=pin.commit_sha,
        patterns=source.selected_paths, commands=(("git", "fetch"),), statuses=(0,),
        download_bytes=1, disk_bytes=1, outcome="PASS", blocker=None,
        content_hashes={"example.py": "8" * 64},
    )
    checkout_path.write_bytes(wrong_url.canonical_bytes())
    with pytest.raises(ValueError, match="manifest/lock"):
        load_manifest_fragments(tmp_path, operation_manifest, registry, lock)


def test_operate_uses_exact_manifest_id_checkout_and_output(tmp_path: Path) -> None:
    registry, lock = complete_lock()
    source = next(item for item in registry.repositories if item.name == "mjctrl")
    pin = next(item for item in lock.entries if item.name == "mjctrl")
    (tmp_path / "references").mkdir()
    (tmp_path / "references/repos.yaml").write_bytes(Path("references/repos.yaml").read_bytes())
    (tmp_path / "references/repos.lock.yaml").write_bytes(lock_yaml_bytes(lock))
    payload = manifest_payload(registry, lock)
    payload["operations"][1]["selected_path"] = source.selected_paths[0]
    payload["operations"][1]["command"] = ["ast_parse", source.selected_paths[0]]
    config = tmp_path / "experiments/00_source_audit/configs"
    config.mkdir(parents=True)
    (config / "operation-manifest.yaml").write_text(yaml.safe_dump(payload, sort_keys=False))
    checkout_root = tmp_path / "external/mjctrl"
    checkout_root.mkdir(parents=True)
    (checkout_root / "example.py").write_text("value = 1\n")
    fragments = tmp_path / "experiments/00_source_audit/results/fragments"
    fragments.mkdir(parents=True)
    checkout = CheckoutEvidence.create(
        registry_sha256=registry.registry_sha256, repository="mjctrl", url=source.url,
        locked_sha=pin.commit_sha, patterns=source.selected_paths,
        commands=(("git", "fetch"),), statuses=(0,), download_bytes=1,
        disk_bytes=1, outcome="PASS", blocker=None,
        content_hashes={"example.py": hashlib.sha256(b"value = 1\n").hexdigest()},
    )
    (fragments / "mjctrl-checkout.json").write_bytes(checkout.canonical_bytes())
    assert source_audit_main(["--operate", "MJCTRL_AST_PARSE", "--root", str(tmp_path)]) == 0
    output = fragments / "mjctrl-ast.json"
    assert output.is_file()
    assert json.loads(output.read_text())["operation_id"] == "MJCTRL_AST_PARSE"
    with pytest.raises(SystemExit):
        source_audit_main(["--operate", "MJCTRL_AST_PARSE", "--fragment", "elsewhere.json"])


def test_fragment_lock_binding_and_classification_precedence(tmp_path: Path) -> None:
    registry, lock = complete_lock()
    source = next(item for item in registry.repositories if item.name == "mjctrl")
    locked = next(item for item in lock.entries if item.name == "mjctrl")
    item = evidence(
        registry_sha256=registry.registry_sha256,
        repository="mjctrl",
        commit_sha=locked.commit_sha,
        experiment=source.experiments[0],
        selected_path=source.selected_paths[0],
        operation_id="MJCTRL_AST_PARSE",
        command=("ast_parse", source.selected_paths[0]),
        findings={
            "files": [{
                "path": "example.py", "sha256": "8" * 64, "bytes": 1,
                "disposition": "PASS", "node_count": 5,
                "failure_line": None, "failure_column": None,
            }],
            "summary": {"files_total": 1, "files_pass": 1, "files_fail": 0},
        },
        content_hashes={"example.py": "8" * 64},
    )
    payload = manifest_payload(registry, lock)
    payload["operations"][1]["selected_path"] = source.selected_paths[0]
    payload["operations"][1]["command"] = ["ast_parse", source.selected_paths[0]]
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False))
    operation_manifest = load_operation_manifest(manifest_path, registry, lock, Path.cwd())
    validate_fragment(item.to_dict(), registry, lock, operation_manifest, payload["operations"][1]["relative_output"])
    checkout = CheckoutEvidence.create(
        registry_sha256=registry.registry_sha256, repository="mjctrl", url=source.url,
        locked_sha=locked.commit_sha, patterns=tuple(source.selected_paths),
        commands=(("git", "fetch"),), statuses=(0,), download_bytes=1,
        disk_bytes=1, outcome="PASS", blocker=None,
        content_hashes={"example.py": "8" * 64},
    )
    rows = consolidate_compatibility(registry, lock, (item,), (), operation_manifest, (checkout,))
    assert len(rows) == 279
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
        operation_id="EXAMPLE_AST_PARSE",
        operation=SourceOperation.AST_PARSE, license_status="DISCOVERED", license_spdx="MIT",
        platform="test-platform", python_requirement=">=3.11",
        compiler_or_runtime="python-3.11",
        timeout_seconds=60, download_ceiling_bytes=0, disk_ceiling_bytes=16 * 1024 * 1024,
        file_ceiling_bytes=2 * 1024 * 1024, file_count_ceiling=512,
        depth_ceiling=8, no_copy=True, no_models=True,
    )
    item = run_source_operation(spec, checkout)
    assert dict(item.findings)["summary"] == {"files_total": 1, "files_pass": 1, "files_fail": 0}
    destination = tmp_path / "fragments" / "example.json"
    write_fragment_create_only(destination, item)
    with pytest.raises(FileExistsError):
        write_fragment_create_only(destination, item)
    (checkout / "linked.py").symlink_to(tmp_path / "outside.py")
    with pytest.raises(ValueError, match="symlink|regular"):
        run_source_operation(replace(spec, selected_path="linked.py"), checkout)
    with pytest.raises(ValueError, match="safety"):
        run_source_operation(replace(spec, no_copy=False), checkout)
    with pytest.raises(ValueError, match="file byte"):
        run_source_operation(replace(spec, file_ceiling_bytes=5, disk_ceiling_bytes=5), checkout)
    invalid = checkout / "invalid.py"
    invalid.write_bytes(b"\xff")
    failed = run_source_operation(replace(spec, selected_path="invalid.py"), checkout)
    assert failed.exit_status == 1
    assert dict(failed.findings)["files"][0]["failure_line"] == 1


def test_source_operation_enforces_count_depth_and_intermediate_nofollow(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    selected = checkout / "selected"
    selected.mkdir()
    (selected / "a.py").write_text("a = 1\n")
    (selected / "b.py").write_text("b = 1\n")
    spec = OperationSpec(
        registry_sha256="9" * 64, repository="example", commit_sha="a" * 40,
        experiment="01_policy_control", selected_path="selected",
        operation_id="EXAMPLE_AST_PARSE", operation=SourceOperation.AST_PARSE,
        license_status="DISCOVERED", license_spdx="MIT", platform="test-platform",
        python_requirement=">=3.11", compiler_or_runtime="python-3.11",
        timeout_seconds=60, download_ceiling_bytes=0, disk_ceiling_bytes=1024,
        file_ceiling_bytes=512, file_count_ceiling=1, depth_ceiling=8,
        no_copy=True, no_models=True,
    )
    with pytest.raises(ValueError, match="file-count"):
        run_source_operation(spec, checkout)
    nested = selected / "deep"
    nested.mkdir()
    (nested / "c.py").write_text("c = 1\n")
    (selected / "a.py").unlink()
    (selected / "b.py").unlink()
    with pytest.raises(ValueError, match="selected no files"):
        run_source_operation(replace(spec, file_count_ceiling=2, depth_ceiling=1), checkout)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "unsafe.py").write_text("unsafe = 1\n")
    (checkout / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        run_source_operation(replace(spec, selected_path="link/unsafe.py", file_count_ceiling=2), checkout)


def test_static_evidence_cannot_claim_arbitrary_patch_promotion() -> None:
    with pytest.raises(ValueError, match="patched-runtime"):
        evidence(patch_artifact_sha256="1" * 64)


def test_consolidation_rejects_stale_checkout_hash_join(tmp_path: Path) -> None:
    registry, lock = complete_lock()
    source = next(item for item in registry.repositories if item.name == "mjctrl")
    pin = next(item for item in lock.entries if item.name == "mjctrl")
    payload = manifest_payload(registry, lock)
    payload["operations"][1]["selected_path"] = source.selected_paths[0]
    payload["operations"][1]["command"] = ["ast_parse", source.selected_paths[0]]
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False))
    operation_manifest = load_operation_manifest(manifest_path, registry, lock, tmp_path)
    item = evidence(
        registry_sha256=registry.registry_sha256, repository="mjctrl",
        commit_sha=pin.commit_sha, experiment="01_policy_control",
        selected_path=source.selected_paths[0], operation_id="MJCTRL_AST_PARSE",
        command=("ast_parse", source.selected_paths[0]),
        findings={"files": [{"path": "example.py", "sha256": "8" * 64,
                              "bytes": 1, "disposition": "PASS", "node_count": 1,
                              "failure_line": None, "failure_column": None}],
                  "summary": {"files_total": 1, "files_pass": 1, "files_fail": 0}},
        content_hashes={"example.py": "8" * 64},
    )
    checkout = CheckoutEvidence.create(
        registry_sha256=registry.registry_sha256, repository="mjctrl", url=source.url,
        locked_sha=pin.commit_sha, patterns=source.selected_paths,
        commands=(("git", "fetch"),), statuses=(0,), download_bytes=1, disk_bytes=1,
        outcome="PASS", blocker=None, content_hashes={"example.py": "7" * 64},
    )
    with pytest.raises(ValueError, match="stale"):
        consolidate_compatibility(registry, lock, (item,), (), operation_manifest, (checkout,))


@pytest.mark.parametrize(
    ("operation", "name", "content", "expected"),
    [
        (SourceOperation.HEADER_LAYOUT, "safe.h", "#pragma once\nint value;\n", "pragma_once"),
        (SourceOperation.MANIFEST_LAYOUT, "safe.toml", "[project]\nname='x'\n", "top_level"),
        (SourceOperation.MANIFEST_LAYOUT, "safe.xml", "<model><body/></model>\n", "top_level"),
        (SourceOperation.ASSET_LICENSE_INVENTORY, "LICENSE", "SPDX-License-Identifier: MIT\n", "license_candidates"),
    ],
)
def test_operation_specific_raw_records_are_reconstructable(
    tmp_path: Path, operation: SourceOperation, name: str, content: str, expected: str,
) -> None:
    checkout = tmp_path / operation.value
    checkout.mkdir()
    (checkout / name).write_text(content)
    spec = OperationSpec(
        registry_sha256="9" * 64, repository="example", commit_sha="a" * 40,
        experiment="01_policy_control", selected_path=name,
        operation_id=f"EXAMPLE_{operation.value}", operation=operation,
        license_status="DISCOVERED", license_spdx="MIT", platform="test-platform",
        python_requirement=">=3.11", compiler_or_runtime="python-3.11",
        timeout_seconds=60, download_ceiling_bytes=0, disk_ceiling_bytes=16 * 1024 * 1024,
        file_ceiling_bytes=2 * 1024 * 1024, file_count_ceiling=512,
        depth_ceiling=8, no_copy=True, no_models=True,
    )
    item = run_source_operation(spec, checkout)
    reconstructed = CompatibilityEvidence.from_dict(json.loads(item.canonical_bytes()))
    assert reconstructed == item
    assert expected in dict(item.findings)["files"][0]


@pytest.mark.parametrize(("name", "content"), [("bad.json", '{"a":1,"a":2}'), ("bad.yaml", "a: 1\na: 2\n")])
def test_manifest_parser_rejects_duplicate_keys_with_failure_location(
    tmp_path: Path, name: str, content: str,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / name).write_text(content)
    spec = OperationSpec(
        registry_sha256="9" * 64, repository="example", commit_sha="a" * 40,
        experiment="01_policy_control", selected_path=name,
        operation_id="EXAMPLE_MANIFEST_LAYOUT", operation=SourceOperation.MANIFEST_LAYOUT,
        license_status="DISCOVERED", license_spdx="MIT", platform="test-platform",
        python_requirement=">=3.11", compiler_or_runtime="python-3.11",
        timeout_seconds=60, download_ceiling_bytes=0, disk_ceiling_bytes=16 * 1024 * 1024,
        file_ceiling_bytes=2 * 1024 * 1024, file_count_ceiling=512,
        depth_ceiling=8, no_copy=True, no_models=True,
    )
    item = run_source_operation(spec, checkout)
    finding = dict(item.findings)["files"][0]
    assert finding["disposition"] == "FAIL"
    assert finding["failure_line"] >= 1


def test_outputs_have_exact_csv_header_and_are_deterministic(tmp_path: Path) -> None:
    registry, lock = complete_lock()
    rows = consolidate_compatibility(registry, lock, (), ())
    first = write_compatibility_outputs(tmp_path, registry, lock, rows)
    second = write_compatibility_outputs(tmp_path, registry, lock, rows, check=True)
    assert first == second
    assert (tmp_path / "experiments/00_source_audit/results/compatibility.csv").read_text().splitlines()[0] == ",".join(CSV_HEADER)
    maturity = (tmp_path / "docs/MATURITY_LEDGER.md").read_text()
    assert "| project_or_component | evidence_label | evidence_source | supported_embodiment_or_task | license | compute_requirements | local_reproduction_status | known_failure_modes | role_in_program | hardware_validation_status |" in maturity
    assert sum(line.startswith("| ") for line in maturity.splitlines()) == 47
    licenses = (tmp_path / "references/licenses.md").read_text()
    assert "attribution requirement | decision/blocker | review date" in licenses
    source_map = (tmp_path / "docs/SOURCE_MAP.md").read_text()
    assert "local fallback | attribution record" in source_map
    assert "| Experiment 00 source compatibility | UNVERIFIED | NONE | source audit | project | local CPU | NOT_REPRODUCED |" in maturity


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
