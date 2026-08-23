from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
from pathlib import Path

import pytest

from reflect.sources import (
    LicenseStatus,
    LockedEntry,
    MetadataStatus,
    PathStatus,
    RegistryEntry,
    ReuseMode,
    SourceLock,
    SourceRegistry,
    SourceValidationError,
    has_exact_wheel_install_authority,
    load_lock,
    load_registry,
    registry_sha256,
    validate_lock,
)


EXPECTED_NAMES = {
    "mujoco", "mujoco_mpc", "mujoco_menagerie", "mink", "mjctrl", "hydrax",
    "curobo", "moveit2", "ros2_control", "ros2_controllers", "mujoco_ros2_control",
    "act", "lerobot", "openpi", "diffusion_policy", "behaviortree_cpp", "navigation2",
    "spark_dsg", "hydra_scene_graph", "kimera", "conceptgraphs", "rerun", "openusd",
    "ifcopenshell", "ifcopenshell_test_files", "tdmpc2", "dino_wm", "vjepa2", "lawam",
    "libero", "unitree_rl_mjlab", "unitree_mujoco", "unitree_sdk2", "unifolm_vla",
    "unifolm_wma", "isaac_sim", "isaac_lab", "isaac_launchable", "isaac_lab_arena",
    "uv", "hatchling", "pyyaml", "numpy", "pyarrow", "pytest",
}


def write_registry(tmp_path: Path, *, url: str = "https://github.com/example/repo") -> Path:
    path = tmp_path / "repos.yaml"
    path.write_text(
        """verified_at: "2026-08-22"
large_model_downloads_default: false
physical_deployment_default: false
repositories:
  - name: example
    url: %s
    mode: SPARSE_REFERENCE
    experiments: [00_source_audit]
    selected_paths: [README.md]
    use: A minimal reference.
    caveat: Keep it isolated.
""" % url
    )
    return path


def test_complete_registry_has_canonical_and_bootstrap_entries() -> None:
    registry = load_registry(Path("references/repos.yaml"))
    assert len(registry.repositories) == 45
    assert {entry.name for entry in registry.repositories} == EXPECTED_NAMES


def test_complete_registry_preserves_representative_canonical_values() -> None:
    registry = load_registry(Path("references/repos.yaml"))
    entries = {entry.name: entry for entry in registry.repositories}

    assert entries["mujoco"].url == "https://github.com/google-deepmind/mujoco"
    assert entries["mujoco"].mode is ReuseMode.DIRECT_DEPENDENCY
    assert entries["mujoco"].selected_paths == ("python", "model", "sample", "test")
    assert entries["mjctrl"].selected_paths == ("*.py", "README.md")
    assert entries["unitree_rl_mjlab"].mode is ReuseMode.REMOTE_ONLY
    assert entries["isaac_lab_arena"].mode is ReuseMode.DEFERRED
    assert entries["uv"].justification == "The host already provides uv; no source clone is required."
    assert registry.large_model_downloads_default is False
    assert registry.physical_deployment_default is False


def test_registry_entries_are_frozen_and_sequences_are_tuples() -> None:
    entry = load_registry(Path("references/repos.yaml")).repositories[0]
    assert isinstance(entry.experiments, tuple)
    assert isinstance(entry.selected_paths, tuple)
    with pytest.raises(FrozenInstanceError):
        entry.name = "mutated"  # type: ignore[misc]


def test_registry_urls_are_exact_https_github_identities() -> None:
    registry = load_registry(Path("references/repos.yaml"))
    assert all(entry.url.startswith("https://github.com/") for entry in registry.repositories)
    assert all(entry.url.count("/") == 4 for entry in registry.repositories)


def test_registry_rejects_non_github_https_url(tmp_path: Path) -> None:
    path = write_registry(tmp_path, url="https://example.com/owner/repo")
    with pytest.raises(SourceValidationError, match="github.com"):
        load_registry(path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unexpected: value\n", "extra"),
        ("", "missing"),
    ],
)
def test_registry_rejects_extra_or_missing_top_level_keys(
    tmp_path: Path, mutation: str, message: str
) -> None:
    path = write_registry(tmp_path)
    content = path.read_text()
    if mutation:
        path.write_text(content + mutation)
    else:
        path.write_text(content.replace("physical_deployment_default: false\n", ""))
    with pytest.raises(SourceValidationError, match=message):
        load_registry(path)


def test_registry_rejects_duplicate_names_and_selected_paths(tmp_path: Path) -> None:
    path = write_registry(tmp_path)
    path.write_text(
        path.read_text().replace("selected_paths: [README.md]", "selected_paths: [README.md, README.md]")
    )
    with pytest.raises(SourceValidationError, match="duplicate"):
        load_registry(path)


def test_registry_rejects_boolean_where_a_string_is_required(tmp_path: Path) -> None:
    path = write_registry(tmp_path)
    path.write_text(path.read_text().replace("name: example", "name: true"))
    with pytest.raises(SourceValidationError, match="name"):
        load_registry(path)


def test_registry_sha256_hashes_exact_file_bytes(tmp_path: Path) -> None:
    path = write_registry(tmp_path)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert registry_sha256(path) == expected
    path.write_bytes(path.read_bytes() + b"\n")
    assert registry_sha256(path) != expected


def test_load_lock_and_validate_lock_accept_complete_fixture(tmp_path: Path) -> None:
    registry_path = Path("tests/fixtures/source_metadata/registry-minimal.yaml")
    registry = load_registry(registry_path)
    lock_path = tmp_path / "repos.lock.yaml"
    lock_path.write_text(
        f"""registry_sha256: {registry_sha256(registry_path)}
generated_at: "2026-08-22T00:00:00Z"
entries:
  - name: example
    url: https://github.com/example/repo
    default_branch: main
    commit_sha: 0123456789abcdef0123456789abcdef01234567
    retrieved_at: "2026-08-22T00:00:00Z"
    metadata_evidence:
      repository: https://api.github.com/repos/example/repo
      tree: https://api.github.com/repos/example/repo/git/trees/0123456789abcdef0123456789abcdef01234567?recursive=1
      license: https://raw.githubusercontent.com/example/repo/0123456789abcdef0123456789abcdef01234567/LICENSE
    license_spdx: MIT
    license_status: DISCOVERED
    license_evidence_url: https://raw.githubusercontent.com/example/repo/0123456789abcdef0123456789abcdef01234567/LICENSE
    path_statuses:
      README.md: EXISTS
    path_evidence_urls:
      README.md: https://api.github.com/repos/example/repo/git/trees/0123456789abcdef0123456789abcdef01234567?recursive=1
    metadata_status: RESOLVED
"""
    )
    lock = load_lock(lock_path)
    assert lock.entries[0].path_statuses == {"README.md": PathStatus.EXISTS}
    assert lock.entries[0].license_status is LicenseStatus.DISCOVERED
    assert lock.entries[0].metadata_status is MetadataStatus.RESOLVED
    assert validate_lock(registry, lock, require_complete=True) == []


def _artifact_evidence() -> dict[str, str]:
    return {
        "artifact_license.authority": "EXACT_WHEEL_INSTALL_ONLY",
        "artifact_license.package_name": "numpy",
        "artifact_license.package_version": "2.4.6",
        "artifact_license.wheel_filename": "numpy-2.4.6-cp311-cp311-macosx_14_0_arm64.whl",
        "artifact_license.wheel_url": "https://files.pythonhosted.org/packages/aa/bb/"
        + "c" * 64
        + "/numpy-2.4.6-cp311-cp311-macosx_14_0_arm64.whl",
        "artifact_license.wheel_sha256": "a" * 64,
        "artifact_license.metadata_path": "numpy-2.4.6.dist-info/METADATA",
        "artifact_license.metadata_sha256": "b" * 64,
        "artifact_license.record_path": "numpy-2.4.6.dist-info/RECORD",
        "artifact_license.record_sha256": "c" * 64,
        "artifact_license.license_expression": "BSD-3-Clause AND MIT",
        "artifact_license.license_files_json": '[{"path":"numpy-2.4.6.dist-info/licenses/LICENSE.txt","sha256":"'
        + "d" * 64
        + '"}]',
    }


def _unknown_license_lock(mode: ReuseMode, metadata: dict[str, str]) -> tuple[SourceRegistry, SourceLock]:
    entry = RegistryEntry(
        name="numpy",
        url="https://github.com/numpy/numpy",
        mode=mode,
        experiments=("bootstrap",),
        selected_paths=(),
        use="Typed arrays.",
    )
    registry = SourceRegistry(
        verified_at="2026-08-22",
        large_model_downloads_default=False,
        physical_deployment_default=False,
        repositories=(entry,),
        registry_sha256="9" * 64,
    )
    lock = SourceLock(
        registry_sha256="9" * 64,
        generated_at="2026-08-23T00:00:00Z",
        entries=(
            LockedEntry(
                name="numpy",
                url=entry.url,
                default_branch="main",
                commit_sha="1" * 40,
                retrieved_at="2026-08-23T00:00:00Z",
                metadata_evidence={
                    "commit": "https://api.github.com/repos/numpy/numpy/git/commits/" + "1" * 40,
                    "tree": "https://api.github.com/repos/numpy/numpy/git/trees/" + "2" * 40 + "?recursive=1",
                    **metadata,
                },
                license_spdx=None,
                license_status=LicenseStatus.UNKNOWN,
                license_evidence_url="https://api.github.com/repos/numpy/numpy/license?ref=" + "1" * 40,
                path_statuses={},
                path_evidence_urls={},
                metadata_status=MetadataStatus.RESOLVED,
            ),
        ),
    )
    return registry, lock


def test_exact_wheel_evidence_authorizes_only_unknown_direct_install() -> None:
    registry, lock = _unknown_license_lock(ReuseMode.DIRECT_DEPENDENCY, _artifact_evidence())
    assert has_exact_wheel_install_authority(lock.entries[0])
    assert validate_lock(registry, lock, require_complete=True) == []
    assert lock.entries[0].license_status is LicenseStatus.UNKNOWN
    assert lock.entries[0].license_spdx is None


def test_exact_wheel_evidence_never_authorizes_adapter_or_partial_record() -> None:
    registry, lock = _unknown_license_lock(ReuseMode.ADAPTER_DEPENDENCY, _artifact_evidence())
    assert validate_lock(registry, lock, require_complete=True) == [
        "artifact install authority is permitted only for a direct dependency: numpy",
        "direct/adapter license is not discovered: numpy",
    ]

    incomplete = _artifact_evidence()
    del incomplete["artifact_license.record_sha256"]
    registry, lock = _unknown_license_lock(ReuseMode.DIRECT_DEPENDENCY, incomplete)
    assert not has_exact_wheel_install_authority(lock.entries[0])
    assert validate_lock(registry, lock, require_complete=True) == [
        "artifact license evidence is incomplete: numpy",
        "direct/adapter license is not discovered: numpy",
    ]

    malformed = _artifact_evidence()
    malformed["artifact_license.license_expression"] = "not an SPDX expression"
    registry, lock = _unknown_license_lock(ReuseMode.DIRECT_DEPENDENCY, malformed)
    assert not has_exact_wheel_install_authority(lock.entries[0])
