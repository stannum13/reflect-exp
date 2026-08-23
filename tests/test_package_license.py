from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from reflect.package_license import (
    LockedWheelLicenseResolver,
    PackageLicenseError,
    current_wheel_tags,
    load_bootstrap_artifact_config,
    select_locked_wheel,
    validate_bootstrap_binary_evidence,
    validate_locked_install_evidence,
    verify_bootstrap_artifact,
    verify_locked_wheel_license,
)
from reflect.source_fetch import CacheStore, HttpResponse
from reflect.sources import RegistryEntry, ReuseMode


WHEEL_NAME = "numpy-2.4.6-cp311-cp311-macosx_14_0_arm64.whl"
WHEEL_URL = f"https://files.pythonhosted.org/packages/aa/bb/{'c' * 64}/{WHEEL_NAME}"
EXPRESSION = "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0"
DIST_INFO = "numpy-2.4.6.dist-info"


def _uv_bootstrap_fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    version = "0.9.17"
    commit = "2b5d65e61d829bc81ce116388f849174d56a84ca"
    binary = b"exact uv executable\n"
    workspace = b'[workspace.package]\nlicense = "MIT OR Apache-2.0"\n'
    package = b'[package]\nname = "uv"\nversion = "0.9.17"\nlicense = { workspace = true }\n'
    licenses = {"LICENSE-APACHE": b"apache\n", "LICENSE-MIT": b"mit\n"}
    sdist_members = {
        f"uv-{version}/Cargo.toml": workspace,
        f"uv-{version}/crates/uv/Cargo.toml": package,
        **{f"uv-{version}/{name}": data for name, data in licenses.items()},
    }
    sdist_io = io.BytesIO()
    with tarfile.open(fileobj=sdist_io, mode="w:gz") as archive:
        for name, data in sdist_members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    sdist = sdist_io.getvalue()

    dist_info = f"uv-{version}.dist-info"
    metadata = (
        "Metadata-Version: 2.4\nName: uv\nVersion: 0.9.17\n"
        "Classifier: License :: OSI Approved :: MIT License\n"
        "Classifier: License :: OSI Approved :: Apache Software License\n"
        "License-File: LICENSE-APACHE\nLicense-File: LICENSE-MIT\n\n"
    ).encode()
    members = {
        f"{dist_info}/METADATA": metadata,
        f"{dist_info}/licenses/LICENSE-APACHE": licenses["LICENSE-APACHE"],
        f"{dist_info}/licenses/LICENSE-MIT": licenses["LICENSE-MIT"],
        f"uv-{version}.data/scripts/uv": binary,
    }
    record_path = f"{dist_info}/RECORD"
    record = (
        "\n".join(
            [f"{path},{_record_digest(data)},{len(data)}" for path, data in sorted(members.items())]
            + [f"{record_path},,"]
        )
        + "\n"
    ).encode()
    members[record_path] = record
    wheel_io = io.BytesIO()
    with zipfile.ZipFile(wheel_io, "w", zipfile.ZIP_STORED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    wheel = wheel_io.getvalue()
    executable = tmp_path / "uv"
    executable.write_bytes(binary)
    executable.chmod(0o755)
    config: dict[str, object] = {
        "name": "uv", "version": version, "tag": version, "commit_sha": commit,
        "repository_url": "https://github.com/astral-sh/uv",
        "sdist_filename": f"uv-{version}.tar.gz",
        "sdist_url": f"https://files.pythonhosted.org/packages/aa/bb/{'1' * 64}/uv-{version}.tar.gz",
        "sdist_sha256": hashlib.sha256(sdist).hexdigest(), "sdist_size": len(sdist),
        "wheel_filename": f"uv-{version}-py3-none-macosx_11_0_arm64.whl",
        "wheel_url": f"https://files.pythonhosted.org/packages/aa/bb/{'2' * 64}/uv-{version}-py3-none-macosx_11_0_arm64.whl",
        "wheel_sha256": hashlib.sha256(wheel).hexdigest(), "wheel_size": len(wheel),
        "workspace_manifest_path": "Cargo.toml",
        "workspace_manifest_sha256": hashlib.sha256(workspace).hexdigest(),
        "package_manifest_path": "crates/uv/Cargo.toml",
        "package_manifest_sha256": hashlib.sha256(package).hexdigest(),
        "license_apache_sha256": hashlib.sha256(licenses["LICENSE-APACHE"]).hexdigest(),
        "license_mit_sha256": hashlib.sha256(licenses["LICENSE-MIT"]).hexdigest(),
        "embedded_executable_path": f"uv-{version}.data/scripts/uv",
        "embedded_executable_sha256": hashlib.sha256(binary).hexdigest(),
        "embedded_executable_size": len(binary),
    }
    inputs = {
        "sdist_bytes": sdist, "wheel_bytes": wheel,
        "workspace_manifest_bytes": workspace, "package_manifest_bytes": package,
        "license_file_bytes": licenses,
        "host_executable_path": executable,
        "version_output": "uv 0.9.17 (2b5d65e61 2025-12-09)", "tag_commit": commit,
    }
    return config, inputs


def test_exact_bootstrap_binary_authority_binds_release_and_host_bytes(tmp_path: Path) -> None:
    config, inputs = _uv_bootstrap_fixture(tmp_path)
    evidence = verify_bootstrap_artifact(config=config, **inputs)
    assert evidence["bootstrap_artifact.authority"] == "EXACT_BOOTSTRAP_BINARY_USE_ONLY"
    assert evidence["bootstrap_artifact.license_expression"] == "MIT OR Apache-2.0"
    assert evidence["bootstrap_artifact.host_executable_path"] == str((tmp_path / "uv").resolve())
    assert evidence["bootstrap_artifact.commit_sha"] == config["commit_sha"]


def test_production_bootstrap_source_is_closed_and_duplicate_rejecting(tmp_path: Path) -> None:
    config = load_bootstrap_artifact_config(Path("references/bootstrap-artifacts.yaml"))
    assert config["commit_sha"] == "2b5d65e61d829bc81ce116388f849174d56a84ca"
    assert config["embedded_executable_sha256"] == (
        "ee694042316fcb760b176ea8d3fb673790fd8d573ed06f28a4d52a01066c358d"
    )

    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("schema_version: 1\nschema_version: 1\nartifacts: []\n")
    with pytest.raises(PackageLicenseError, match="duplicate key"):
        load_bootstrap_artifact_config(duplicate)


def test_offline_bootstrap_rebinds_sealed_source_and_current_host(tmp_path: Path) -> None:
    config, inputs = _uv_bootstrap_fixture(tmp_path)
    config_path = tmp_path / "bootstrap-artifacts.yaml"
    config_path.write_text(yaml.safe_dump({"schema_version": 1, "artifacts": [config]}))
    evidence = verify_bootstrap_artifact(config=config, **inputs)

    def runner(path: Path) -> object:
        return inputs["version_output"]

    assert validate_bootstrap_binary_evidence(
        config_path=config_path, metadata_evidence=evidence, version_runner=runner
    ) == ()

    inputs["host_executable_path"].write_bytes(b"changed")
    assert validate_bootstrap_binary_evidence(
        config_path=config_path, metadata_evidence=evidence, version_runner=runner
    ) == (
        "bootstrap host executable cannot be read: uv: "
        "bootstrap host executable is not a stable regular file",
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("binary", "stable regular file"),
        ("version", "version output"),
        ("commit", "tag commit"),
        ("license", "workspace license"),
        ("manifest", "package manifest"),
    ],
)
def test_exact_bootstrap_binary_authority_fails_closed(
    tmp_path: Path, mutation: str, message: str
) -> None:
    config, inputs = _uv_bootstrap_fixture(tmp_path)
    if mutation == "binary":
        inputs["host_executable_path"].write_bytes(b"different")
    elif mutation == "version":
        inputs["version_output"] = "uv 0.9.18 (2b5d65e61 2025-12-09)"
    elif mutation == "commit":
        inputs["tag_commit"] = "f" * 40
    elif mutation == "license":
        inputs["workspace_manifest_bytes"] = b"[workspace.package]\n"
        config["workspace_manifest_sha256"] = hashlib.sha256(
            inputs["workspace_manifest_bytes"]
        ).hexdigest()
    else:
        inputs["package_manifest_bytes"] = b'[package]\nname = "uv"\nversion = "0.9.17"\n'
    with pytest.raises(PackageLicenseError, match=message):
        verify_bootstrap_artifact(config=config, **inputs)


def _record_digest(data: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"sha256={encoded.decode('ascii')}"


def _wheel(
    *,
    name: str = "numpy",
    version: str = "2.4.6",
    expression_headers: tuple[str, ...] = (EXPRESSION,),
    license_headers: tuple[str, ...] = ("LICENSE.txt", "numpy/ma/LICENSE"),
    omit_license: str | None = None,
    bad_record_path: str | None = None,
    unsafe_member: bool = False,
    metadata_version: str = "2.4",
    extra_license: bool = False,
    directory_entries: bool = False,
) -> bytes:
    metadata = (
        f"Metadata-Version: {metadata_version}\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
        + "".join(f"License-Expression: {value}\n" for value in expression_headers)
        + "".join(f"License-File: {value}\n" for value in license_headers)
        + "\n"
    ).encode()
    members: dict[str, bytes] = {f"{DIST_INFO}/METADATA": metadata}
    for value in license_headers:
        if value != omit_license:
            members[f"{DIST_INFO}/licenses/{value}"] = f"license:{value}\n".encode()
    if extra_license:
        members[f"{DIST_INFO}/licenses/UNDECLARED"] = b"undeclared\n"
    if unsafe_member:
        members["../escape"] = b"bad"
    rows = [
        f"{path},{_record_digest(data)},{len(data)}"
        for path, data in sorted(members.items())
    ]
    if bad_record_path is not None:
        rows = [
            row.replace(_record_digest(members[bad_record_path]), "sha256=AAAA")
            if row.startswith(f"{bad_record_path},")
            else row
            for row in rows
        ]
    record_path = f"{DIST_INFO}/RECORD"
    record = ("\n".join((*rows, f"{record_path},,")) + "\n").encode()
    members[record_path] = record
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
        if directory_entries:
            archive.writestr(f"{DIST_INFO}/", b"")
            archive.writestr(f"{DIST_INFO}/licenses/", b"")
        for path, data in members.items():
            archive.writestr(path, data)
    return output.getvalue()


def _lock(wheel_hash: str) -> bytes:
    return f'''version = 1
revision = 3

[[package]]
name = "numpy"
version = "2.4.6"
source = {{ registry = "https://pypi.org/simple" }}
wheels = [
  {{ url = "https://files.pythonhosted.org/packages/00/00/{'a' * 64}/numpy-2.4.6-cp311-cp311-macosx_11_0_arm64.whl", hash = "sha256:{'1' * 64}" }},
  {{ url = "{WHEEL_URL}", hash = "sha256:{wheel_hash}" }},
]
'''.encode()


def test_selects_highest_compatible_exact_locked_wheel() -> None:
    wheel = _wheel()
    selected = select_locked_wheel(
        _lock(hashlib.sha256(wheel).hexdigest()),
        package_name="numpy",
        compatible_tags=(
            "cp311-cp311-macosx_15_0_arm64",
            "cp311-cp311-macosx_14_0_arm64",
            "cp311-cp311-macosx_11_0_arm64",
        ),
    )
    assert selected.package_name == "numpy"
    assert selected.package_version == "2.4.6"
    assert selected.filename == WHEEL_NAME
    assert selected.url == WHEEL_URL
    assert selected.sha256 == hashlib.sha256(wheel).hexdigest()


def test_verifies_compound_expression_and_complete_license_inventory() -> None:
    wheel = _wheel()
    evidence = verify_locked_wheel_license(
        package_name="numpy",
        package_version="2.4.6",
        wheel_filename=WHEEL_NAME,
        wheel_url=WHEEL_URL,
        wheel_sha256=hashlib.sha256(wheel).hexdigest(),
        wheel_bytes=wheel,
    )
    assert evidence["artifact_license.authority"] == "EXACT_WHEEL_INSTALL_ONLY"
    assert evidence["artifact_license.license_expression"] == EXPRESSION
    assert evidence["artifact_license.wheel_sha256"] == hashlib.sha256(wheel).hexdigest()
    assert evidence["artifact_license.metadata_sha256"] == hashlib.sha256(
        zipfile.ZipFile(io.BytesIO(wheel)).read(f"{DIST_INFO}/METADATA")
    ).hexdigest()
    inventory = json.loads(evidence["artifact_license.license_files_json"])
    assert [item["path"] for item in inventory] == [
        f"{DIST_INFO}/licenses/LICENSE.txt",
        f"{DIST_INFO}/licenses/numpy/ma/LICENSE",
    ]


def test_accepts_safe_zip_directory_entries_without_treating_them_as_record_members() -> None:
    wheel = _wheel(directory_entries=True)
    evidence = verify_locked_wheel_license(
        package_name="numpy",
        package_version="2.4.6",
        wheel_filename=WHEEL_NAME,
        wheel_url=WHEEL_URL,
        wheel_sha256=hashlib.sha256(wheel).hexdigest(),
        wheel_bytes=wheel,
    )
    assert evidence["artifact_license.authority"] == "EXACT_WHEEL_INSTALL_ONLY"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": "other"}, "package name"),
        ({"version": "9.9"}, "package version"),
        ({"expression_headers": ()}, "License-Expression"),
        ({"expression_headers": (EXPRESSION, "MIT")}, "License-Expression"),
        ({"expression_headers": ("not an SPDX expression",)}, "SPDX expression"),
        ({"expression_headers": ("NOASSERTION",)}, "SPDX expression"),
        ({"metadata_version": "2.3"}, "Metadata-Version"),
        ({"license_headers": ()}, "License-File"),
        ({"license_headers": ("../LICENSE",)}, "unsafe"),
        ({"license_headers": ("LICENSE.txt", "LICENSE.txt")}, "License-File"),
        ({"omit_license": "LICENSE.txt"}, "declared license file"),
        ({"extra_license": True}, "license inventory"),
        ({"bad_record_path": f"{DIST_INFO}/METADATA"}, "RECORD"),
        ({"unsafe_member": True}, "unsafe"),
    ],
)
def test_rejects_incomplete_or_ambiguous_wheel_evidence(
    kwargs: dict[str, object], message: str
) -> None:
    wheel = _wheel(**kwargs)
    with pytest.raises(PackageLicenseError, match=message):
        verify_locked_wheel_license(
            package_name="numpy",
            package_version="2.4.6",
            wheel_filename=WHEEL_NAME,
            wheel_url=WHEEL_URL,
            wheel_sha256=hashlib.sha256(wheel).hexdigest(),
            wheel_bytes=wheel,
        )


def test_rejects_wheel_bytes_that_do_not_match_locked_digest() -> None:
    wheel = _wheel()
    with pytest.raises(PackageLicenseError, match="wheel SHA-256"):
        verify_locked_wheel_license(
            package_name="numpy",
            package_version="2.4.6",
            wheel_filename=WHEEL_NAME,
            wheel_url=WHEEL_URL,
            wheel_sha256="0" * 64,
            wheel_bytes=wheel,
        )


def test_rejects_absent_package_or_compatible_wheel() -> None:
    wheel = _wheel()
    lock = _lock(hashlib.sha256(wheel).hexdigest())
    with pytest.raises(PackageLicenseError, match="locked package"):
        select_locked_wheel(lock, package_name="missing", compatible_tags=("py3-none-any",))
    with pytest.raises(PackageLicenseError, match="compatible locked wheel"):
        select_locked_wheel(lock, package_name="numpy", compatible_tags=("cp311-cp311-win_amd64",))


class _WheelTransport:
    def __init__(self, wheel: bytes) -> None:
        self.wheel = wheel
        self.calls: list[str] = []

    def get(self, url: str) -> HttpResponse:
        self.calls.append(url)
        return HttpResponse(url=url, status=200, headers={}, body=self.wheel)


def test_locked_wheel_resolver_caches_exact_verified_artifact(tmp_path: Path) -> None:
    wheel = _wheel()
    transport = _WheelTransport(wheel)
    resolver = LockedWheelLicenseResolver(
        uv_lock_bytes=_lock(hashlib.sha256(wheel).hexdigest()),
        transport=transport,
        cache=CacheStore(tmp_path / "cache"),
        clock=lambda: datetime(2026, 8, 23, tzinfo=timezone.utc),
        compatible_tags=("cp311-cp311-macosx_14_0_arm64",),
    )
    entry = RegistryEntry(
        name="numpy",
        url="https://github.com/numpy/numpy",
        mode=ReuseMode.DIRECT_DEPENDENCY,
        experiments=("bootstrap",),
        selected_paths=(),
        use="Typed arrays.",
    )
    assert resolver(entry)["artifact_license.license_expression"] == EXPRESSION
    assert resolver(entry)["artifact_license.license_expression"] == EXPRESSION
    assert transport.calls == [WHEEL_URL]


def test_current_platform_tags_select_the_real_locked_numpy_wheel() -> None:
    selected = select_locked_wheel(
        Path("uv.lock").read_bytes(),
        package_name="numpy",
        compatible_tags=current_wheel_tags(),
    )
    assert selected.filename == WHEEL_NAME
    assert selected.sha256 == "4cfe66903cc32a9921a6733d96b19bb6abf310397581bbad89c228f5abaf0ee8"


def test_real_lock_eligibility_is_exact_for_mixed_direct_tools(tmp_path: Path) -> None:
    resolver = LockedWheelLicenseResolver(
        uv_lock_bytes=Path("uv.lock").read_bytes(),
        transport=_WheelTransport(b"not fetched"),
        cache=CacheStore(tmp_path / "cache"),
        clock=lambda: datetime(2026, 8, 23, tzinfo=timezone.utc),
    )

    def entry(name: str) -> RegistryEntry:
        return RegistryEntry(
            name=name,
            url=f"https://github.com/example/{name}",
            mode=ReuseMode.DIRECT_DEPENDENCY,
            experiments=("bootstrap",),
            selected_paths=(),
            use="Fixture.",
        )

    assert resolver.eligible(entry("numpy")) is True
    assert resolver.eligible(entry("uv")) is False
    assert resolver.eligible(entry("hatchling")) is False


def test_offline_validation_rebinds_evidence_to_uv_lock_selection() -> None:
    wheel = _wheel()
    evidence = dict(
        verify_locked_wheel_license(
            package_name="numpy",
            package_version="2.4.6",
            wheel_filename=WHEEL_NAME,
            wheel_url=WHEEL_URL,
            wheel_sha256=hashlib.sha256(wheel).hexdigest(),
            wheel_bytes=wheel,
        )
    )
    assert validate_locked_install_evidence(
        package_name="numpy",
        metadata_evidence=evidence,
        uv_lock_bytes=_lock(hashlib.sha256(wheel).hexdigest()),
        compatible_tags=("cp311-cp311-macosx_14_0_arm64",),
    ) == ()
    evidence["artifact_license.wheel_sha256"] = "0" * 64
    assert validate_locked_install_evidence(
        package_name="numpy",
        metadata_evidence=evidence,
        uv_lock_bytes=_lock(hashlib.sha256(wheel).hexdigest()),
        compatible_tags=("cp311-cp311-macosx_14_0_arm64",),
    ) == ("artifact evidence does not match the selected uv.lock wheel: numpy",)
