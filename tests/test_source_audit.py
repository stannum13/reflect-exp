from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest
import yaml

from scripts.audit_references import audit_repository, main


SHA = "0123456789abcdef0123456789abcdef01234567"
URL = "https://github.com/example/repo"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def complete_fixture(
    tmp_path: Path,
    *,
    mode: str = "SPARSE_REFERENCE",
    license_status: str = "DISCOVERED",
) -> Path:
    root = tmp_path / "repository"
    references = root / "references"
    reflect = root / "reflect"
    references.mkdir(parents=True)
    reflect.mkdir()
    registry = {
        "verified_at": "2026-08-22",
        "large_model_downloads_default": False,
        "physical_deployment_default": False,
        "repositories": [
            {
                "name": "example",
                "url": URL,
                "mode": mode,
                "experiments": ["00_source_audit"],
                "selected_paths": ["README.md"],
                "use": "A minimal reference.",
            }
        ],
    }
    registry_path = references / "repos.yaml"
    registry_path.write_text(
        yaml.safe_dump(registry, sort_keys=False), encoding="utf-8"
    )
    lock = {
        "registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        "generated_at": "2026-08-22T00:00:00Z",
        "entries": [
            {
                "name": "example",
                "url": URL,
                "default_branch": "main",
                "commit_sha": SHA,
                "retrieved_at": "2026-08-22T00:00:00Z",
                "metadata_evidence": {
                    "repository": "https://api.github.com/repos/example/repo",
                    "tree": f"https://api.github.com/repos/example/repo/git/trees/{SHA}?recursive=1",
                    "license": f"https://api.github.com/repos/example/repo/license?ref={SHA}",
                },
                "license_spdx": "MIT" if license_status == "DISCOVERED" else None,
                "license_status": license_status,
                "license_evidence_url": f"https://api.github.com/repos/example/repo/license?ref={SHA}",
                "path_statuses": {"README.md": "EXISTS"},
                "path_evidence_urls": {
                    "README.md": f"https://api.github.com/repos/example/repo/git/trees/{SHA}?recursive=1"
                },
                "metadata_status": "RESOLVED",
            }
        ],
    }
    (references / "repos.lock.yaml").write_text(
        yaml.safe_dump(lock, sort_keys=False), encoding="utf-8"
    )
    (reflect / "local.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(
        root,
        "add",
        "references/repos.yaml",
        "references/repos.lock.yaml",
        "reflect/local.py",
    )
    return root


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    _git(path.parents[1], "add", str(path.relative_to(path.parents[1])))


def test_complete_fixture_has_stable_summary(tmp_path: Path) -> None:
    root = complete_fixture(tmp_path)

    result = audit_repository(root, require_complete=True)

    assert result.to_dict() == {
        "registry_entries": 1,
        "lock_entries": 1,
        "selected_paths": 1,
        "discovered_licenses": 1,
        "tracked_files": 3,
        "errors": [],
        "ok": True,
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("digest", "registry SHA-256 does not match lock"),
        ("missing_entry", "missing lock entry: example"),
        ("extra_entry", "extra lock entry: extra"),
        ("dropped_path", "lock paths do not match registry: example"),
        ("substituted_path", "lock paths do not match registry: example"),
        ("incomplete", "metadata is not resolved: example"),
    ],
)
def test_audit_rejects_lock_mutations(
    tmp_path: Path, mutation: str, message: str
) -> None:
    root = complete_fixture(tmp_path)
    lock_path = root / "references" / "repos.lock.yaml"
    lock = _load_yaml(lock_path)
    entry = lock["entries"][0]
    if mutation == "digest":
        lock["registry_sha256"] = "f" * 64
    elif mutation == "missing_entry":
        lock["entries"] = []
    elif mutation == "extra_entry":
        extra = dict(entry)
        extra["name"] = "extra"
        extra["url"] = "https://github.com/example/extra"
        lock["entries"].append(extra)
    elif mutation == "dropped_path":
        entry["path_statuses"] = {}
        entry["path_evidence_urls"] = {}
    elif mutation == "substituted_path":
        entry["path_statuses"] = {"OTHER.md": "EXISTS"}
        entry["path_evidence_urls"] = {"OTHER.md": "https://example.invalid"}
    else:
        entry["metadata_status"] = "BLOCKED_NETWORK"
    _write_yaml(lock_path, lock)

    assert message in audit_repository(root, require_complete=True).errors


def test_audit_reports_schema_failure_for_short_sha(tmp_path: Path) -> None:
    root = complete_fixture(tmp_path)
    lock_path = root / "references" / "repos.lock.yaml"
    lock = _load_yaml(lock_path)
    lock["entries"][0]["commit_sha"] = "abc123"
    _write_yaml(lock_path, lock)

    result = audit_repository(root, require_complete=True)

    assert result.ok is False
    assert any("40-character lowercase SHA" in error for error in result.errors)


def test_require_complete_rejects_absent_license_observation(tmp_path: Path) -> None:
    root = complete_fixture(tmp_path)
    lock_path = root / "references" / "repos.lock.yaml"
    lock = _load_yaml(lock_path)
    lock["entries"][0]["license_spdx"] = None
    _write_yaml(lock_path, lock)

    result = audit_repository(root, require_complete=True)

    assert "discovered license has no SPDX observation: example" in result.errors


def test_require_complete_rejects_direct_dependency_without_license_evidence(
    tmp_path: Path,
) -> None:
    root = complete_fixture(tmp_path, mode="DIRECT_DEPENDENCY")
    lock_path = root / "references" / "repos.lock.yaml"
    lock = _load_yaml(lock_path)
    lock["entries"][0]["license_evidence_url"] = None
    _write_yaml(lock_path, lock)

    result = audit_repository(root, require_complete=True)

    assert "missing license observation: example" in result.errors


@pytest.mark.parametrize("mode", ["DIRECT_DEPENDENCY", "ADAPTER_DEPENDENCY"])
def test_require_complete_rejects_unknown_direct_or_adapter_license(
    tmp_path: Path, mode: str
) -> None:
    root = complete_fixture(tmp_path, mode=mode, license_status="UNKNOWN")
    result = audit_repository(root, require_complete=True)
    assert "direct/adapter license is not discovered: example" in result.errors


def _add_artifact_install_evidence(root: Path, *, locked_hash: str = "a" * 64) -> None:
    lock_path = root / "references" / "repos.lock.yaml"
    lock = _load_yaml(lock_path)
    entry = lock["entries"][0]
    entry["metadata_evidence"].update(
        {
            "artifact_license.authority": "EXACT_WHEEL_INSTALL_ONLY",
            "artifact_license.package_name": "example",
            "artifact_license.package_version": "1.2.3",
            "artifact_license.wheel_filename": "example-1.2.3-py3-none-any.whl",
            "artifact_license.wheel_url": "https://files.pythonhosted.org/packages/aa/bb/"
            + "c" * 64
            + "/example-1.2.3-py3-none-any.whl",
            "artifact_license.wheel_sha256": "a" * 64,
            "artifact_license.metadata_path": "example-1.2.3.dist-info/METADATA",
            "artifact_license.metadata_sha256": "b" * 64,
            "artifact_license.record_path": "example-1.2.3.dist-info/RECORD",
            "artifact_license.record_sha256": "c" * 64,
            "artifact_license.license_expression": "BSD-3-Clause AND MIT",
            "artifact_license.license_files_json": '[{"path":"example-1.2.3.dist-info/licenses/LICENSE","sha256":"'
            + "d" * 64
            + '"}]',
        }
    )
    _write_yaml(lock_path, lock)
    wheel_url = entry["metadata_evidence"]["artifact_license.wheel_url"]
    (root / "uv.lock").write_text(
        f'''version = 1
revision = 3
[[package]]
name = "example"
version = "1.2.3"
source = {{ registry = "https://pypi.org/simple" }}
wheels = [{{ url = "{wheel_url}", hash = "sha256:{locked_hash}" }}]
'''
    )
    _git(root, "add", "uv.lock")


def test_audit_rebinds_direct_install_evidence_to_exact_uv_lock(tmp_path: Path) -> None:
    root = complete_fixture(
        tmp_path, mode="DIRECT_DEPENDENCY", license_status="UNKNOWN"
    )
    _add_artifact_install_evidence(root)
    assert audit_repository(root, require_complete=True).errors == ()

    _add_artifact_install_evidence(root, locked_hash="e" * 64)
    assert (
        "artifact evidence does not match the selected uv.lock wheel: example"
        in audit_repository(root, require_complete=True).errors
    )


def test_artifact_install_evidence_does_not_authorize_source_attribution(
    tmp_path: Path,
) -> None:
    root = complete_fixture(
        tmp_path, mode="DIRECT_DEPENDENCY", license_status="UNKNOWN"
    )
    _add_artifact_install_evidence(root)
    path = root / "reflect" / "adapted.py"
    path.write_text(
        "# Upstream-Source: example\n"
        f"# Upstream-Revision: {SHA}\n"
        "# SPDX-License-Identifier: MIT\n",
        encoding="utf-8",
    )
    _git(root, "add", "reflect/adapted.py")
    assert "locked attribution license is not discovered: reflect/adapted.py" in (
        audit_repository(root, require_complete=True).errors
    )


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("external/repo/source.py", "tracked source checkout path"),
        ("vendor/repo/source.py", "tracked source checkout path"),
        ("third_party/repo/source.py", "tracked source checkout path"),
        ("models/policy.onnx", "tracked model/checkpoint artifact"),
        ("results/policy.PT", "tracked model/checkpoint artifact"),
        ("results/pytorch_model.bin", "tracked model/checkpoint artifact"),
        ("results/checkpoint", "tracked model/checkpoint artifact"),
    ],
)
def test_audit_rejects_tracked_checkout_and_model_paths(
    tmp_path: Path, path: str, message: str
) -> None:
    root = complete_fixture(tmp_path)
    tracked = root / path
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("fixture\n", encoding="utf-8")
    _git(root, "add", path)

    result = audit_repository(root, require_complete=True)

    assert any(message in error and path in error for error in result.errors)


def test_audit_allows_ordinary_experiment_artifacts(tmp_path: Path) -> None:
    root = complete_fixture(tmp_path)
    for path in ("results/metrics.npz", "results/actions.parquet"):
        tracked = root / path
        tracked.parent.mkdir(parents=True, exist_ok=True)
        tracked.write_bytes(b"fixture")
        _git(root, "add", path)

    assert audit_repository(root, require_complete=True).errors == ()


def test_audit_allows_source_files_in_model_named_directories(tmp_path: Path) -> None:
    root = complete_fixture(tmp_path)
    path = root / "reflect" / "models" / "policy.py"
    path.parent.mkdir()
    path.write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "reflect/models/policy.py")

    assert audit_repository(root, require_complete=True).errors == ()


def test_project_local_reflect_source_needs_no_upstream_marker(tmp_path: Path) -> None:
    root = complete_fixture(tmp_path)
    assert audit_repository(root, require_complete=True).ok is True


@pytest.mark.parametrize("source", ["example", URL])
def test_complete_adjacent_attribution_accepts_registry_name_or_url(
    tmp_path: Path, source: str
) -> None:
    root = complete_fixture(tmp_path)
    path = root / "reflect" / "adapted.py"
    path.write_text(
        f"# Upstream-Source: {source}\n"
        f"# Upstream-Revision: {SHA}\n"
        "# SPDX-License-Identifier: MIT\n"
        "VALUE = 2\n",
        encoding="utf-8",
    )
    _git(root, "add", "reflect/adapted.py")

    assert audit_repository(root, require_complete=True).errors == ()


@pytest.mark.parametrize(
    ("license_status", "locked_spdx", "marker_spdx", "message"),
    [
        ("UNKNOWN", None, "MIT", "locked attribution license is not discovered"),
        ("UNAVAILABLE", None, "MIT", "locked attribution license is not discovered"),
        ("DISCOVERED", "MIT", "Apache-2.0", "attribution SPDX does not match lock"),
        ("DISCOVERED", "MIT OR Apache-2.0", "MIT", "invalid locked attribution SPDX"),
        ("DISCOVERED", "MIT", "MIT OR Apache-2.0", "invalid or missing adjacent SPDX"),
    ],
)
def test_attribution_requires_exact_discovered_single_spdx_license(
    tmp_path: Path,
    license_status: str,
    locked_spdx: str | None,
    marker_spdx: str,
    message: str,
) -> None:
    root = complete_fixture(tmp_path, license_status=license_status)
    lock_path = root / "references" / "repos.lock.yaml"
    lock = _load_yaml(lock_path)
    lock["entries"][0]["license_spdx"] = locked_spdx
    _write_yaml(lock_path, lock)
    path = root / "reflect" / "adapted.py"
    path.write_text(
        f"# Upstream-Source: example\n"
        f"# Upstream-Revision: {SHA}\n"
        f"# SPDX-License-Identifier: {marker_spdx}\n",
        encoding="utf-8",
    )
    _git(root, "add", "reflect/adapted.py")

    assert any(
        message in error
        for error in audit_repository(root, require_complete=True).errors
    )


def test_attribution_rejects_duplicate_spdx_marker(tmp_path: Path) -> None:
    root = complete_fixture(tmp_path)
    path = root / "reflect" / "adapted.py"
    path.write_text(
        f"# Upstream-Source: example\n"
        f"# Upstream-Revision: {SHA}\n"
        "# SPDX-License-Identifier: MIT\n"
        "# SPDX-License-Identifier: MIT\n",
        encoding="utf-8",
    )
    _git(root, "add", "reflect/adapted.py")

    assert any(
        "exactly one SPDX-License-Identifier marker" in error
        for error in audit_repository(root, require_complete=True).errors
    )


def test_empty_and_valid_spdx_markers_count_as_duplicates(tmp_path: Path) -> None:
    root = complete_fixture(tmp_path)
    path = root / "reflect" / "adapted.py"
    path.write_text(
        f"# Upstream-Source: example\n"
        f"# Upstream-Revision: {SHA}\n"
        "# SPDX-License-Identifier:\n"
        "# SPDX-License-Identifier: MIT\n",
        encoding="utf-8",
    )
    _git(root, "add", "reflect/adapted.py")

    assert any(
        "exactly one SPDX-License-Identifier marker" in error
        for error in audit_repository(root, require_complete=True).errors
    )


def test_empty_and_valid_upstream_markers_count_as_duplicates(tmp_path: Path) -> None:
    root = complete_fixture(tmp_path)
    path = root / "reflect" / "adapted.py"
    path.write_text(
        "# Upstream-Source:\n"
        "# Upstream-Source: example\n"
        f"# Upstream-Revision: {SHA}\n"
        "# SPDX-License-Identifier: MIT\n",
        encoding="utf-8",
    )
    _git(root, "add", "reflect/adapted.py")

    assert any(
        "exactly one Upstream-Source marker" in error
        for error in audit_repository(root, require_complete=True).errors
    )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            f"# Upstream-Source: example\n# SPDX-License-Identifier: MIT\n# Upstream-Revision: {SHA[:12]}\n",
            "invalid or missing adjacent Upstream-Revision",
        ),
        (
            f"# Upstream-Source: example\n# Upstream-Revision: {SHA}\nVALUE = 2\n# SPDX-License-Identifier: MIT\n",
            "invalid or missing adjacent SPDX-License-Identifier",
        ),
        (
            f"# Upstream-Source: unknown\n# Upstream-Revision: {SHA}\n# SPDX-License-Identifier: MIT\n",
            "unknown Upstream-Source",
        ),
        (
            f"# Upstream-Source: example\n# Upstream-Revision: {'f' * 40}\n# SPDX-License-Identifier: MIT\n",
            "Upstream-Revision does not match lock",
        ),
    ],
)
def test_attribution_rejects_incomplete_unknown_or_unlocked_markers(
    tmp_path: Path, content: str, message: str
) -> None:
    root = complete_fixture(tmp_path)
    path = root / "reflect" / "adapted.py"
    path.write_text(content, encoding="utf-8")
    _git(root, "add", "reflect/adapted.py")

    assert any(
        message in error
        for error in audit_repository(root, require_complete=True).errors
    )


def test_audit_fails_closed_when_tracked_reflect_file_is_deleted(
    tmp_path: Path,
) -> None:
    root = complete_fixture(tmp_path)
    (root / "reflect" / "local.py").unlink()

    assert any(
        "cannot safely inspect tracked source reflect/local.py" in error
        for error in audit_repository(root, require_complete=True).errors
    )


def test_audit_fails_closed_when_tracked_reflect_file_becomes_symlink(
    tmp_path: Path,
) -> None:
    root = complete_fixture(tmp_path)
    path = root / "reflect" / "local.py"
    path.unlink()
    path.symlink_to("../outside.py")

    assert any(
        "tracked source is not a regular file: reflect/local.py" in error
        for error in audit_repository(root, require_complete=True).errors
    )


def test_audit_fails_closed_when_tracked_reflect_file_becomes_directory(
    tmp_path: Path,
) -> None:
    root = complete_fixture(tmp_path)
    path = root / "reflect" / "local.py"
    path.unlink()
    path.mkdir()

    assert any(
        "tracked source is not a regular file: reflect/local.py" in error
        for error in audit_repository(root, require_complete=True).errors
    )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO requires POSIX")
def test_audit_fails_closed_when_tracked_reflect_file_becomes_fifo(
    tmp_path: Path,
) -> None:
    root = complete_fixture(tmp_path)
    path = root / "reflect" / "local.py"
    path.unlink()
    os.mkfifo(path)

    assert any(
        "tracked source is not a regular file: reflect/local.py" in error
        for error in audit_repository(root, require_complete=True).errors
    )


def test_audit_fails_closed_when_tracked_reflect_file_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = complete_fixture(tmp_path)

    def unreadable(*args: object, **kwargs: object) -> int:
        raise PermissionError("fixture")

    monkeypatch.setattr("scripts.audit_references.os.open", unreadable)

    assert any(
        "cannot safely inspect tracked source reflect/local.py: PermissionError"
        in error
        for error in audit_repository(root, require_complete=True).errors
    )


def test_audit_fails_closed_on_invalid_utf8_or_oversized_reflect_source(
    tmp_path: Path,
) -> None:
    root = complete_fixture(tmp_path)
    invalid = root / "reflect" / "invalid.py"
    invalid.write_bytes(b"\xff\xfe")
    oversized = root / "reflect" / "oversized.py"
    oversized.write_bytes(b"x" * (1024 * 1024 + 1))
    _git(root, "add", "reflect/invalid.py", "reflect/oversized.py")

    errors = audit_repository(root, require_complete=True).errors
    assert any(
        "tracked source is not valid UTF-8: reflect/invalid.py" in error
        for error in errors
    )
    assert any(
        "tracked source exceeds inspection limit: reflect/oversized.py" in error
        for error in errors
    )


def test_git_inventory_uses_fixed_bounded_noninteractive_bytes_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = complete_fixture(tmp_path)
    captured: dict[str, Any] = {}

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured["args"] = args
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, b"reflect/local.py\0", b"")

    monkeypatch.setattr("scripts.audit_references.subprocess.run", fake_run)
    result = audit_repository(root, require_complete=True)

    assert result.ok is True
    assert captured["args"] == ["git", "ls-files", "-z", "--"]
    assert captured["cwd"] == root
    assert captured["capture_output"] is True
    assert captured["text"] is False
    assert captured["check"] is False
    assert captured["timeout"] == 10.0
    environment = captured["env"]
    assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
    assert environment["GIT_CONFIG_SYSTEM"] == os.devnull
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"


def test_git_inventory_fails_closed_on_nonzero_or_malformed_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = complete_fixture(tmp_path)

    def nonzero(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, 7, b"", b"failure")

    monkeypatch.setattr("scripts.audit_references.subprocess.run", nonzero)
    assert any(
        "git ls-files failed" in error
        for error in audit_repository(root, require_complete=True).errors
    )

    def malformed(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, 0, b"reflect/local.py", b"")

    monkeypatch.setattr("scripts.audit_references.subprocess.run", malformed)
    assert any(
        "malformed" in error
        for error in audit_repository(root, require_complete=True).errors
    )


def test_offline_command_prints_stable_json_and_exit_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = complete_fixture(tmp_path)

    assert main(["--require-complete"], root=root) == 0
    first = capsys.readouterr().out
    assert json.loads(first)["ok"] is True
    assert main(["--require-complete"], root=root) == 0
    assert capsys.readouterr().out == first

    tracked = root / "models" / "policy.ckpt"
    tracked.parent.mkdir()
    tracked.write_bytes(b"fixture")
    _git(root, "add", "models/policy.ckpt")
    assert main(["--require-complete"], root=root) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_makefile_exposes_live_then_offline_source_metadata_gate() -> None:
    makefile = (Path(__file__).parents[1] / "Makefile").read_text(encoding="utf-8")
    lines = makefile.splitlines()
    phony_members = [
        member
        for line in lines
        if line.startswith(".PHONY:")
        for member in line.split()[1:]
    ]
    assert phony_members.count("source-metadata-audit") == 1
    target_index = lines.index("source-metadata-audit:")
    recipe: list[str] = []
    for line in lines[target_index + 1 :]:
        if not line.startswith("\t"):
            break
        recipe.append(line)
    assert recipe == [
        "\t$(UV) run python scripts/fetch_reference.py --all-metadata-only",
        "\t$(UV) run python scripts/audit_references.py --require-complete",
    ]


def test_cli_help_does_not_access_network() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/audit_references.py", "--help"],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "--require-complete" in completed.stdout
