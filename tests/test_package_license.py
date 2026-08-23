from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from reflect.package_license import (
    LockedWheelLicenseResolver,
    PackageLicenseError,
    current_wheel_tags,
    select_locked_wheel,
    validate_locked_install_evidence,
    verify_locked_wheel_license,
)
from reflect.source_fetch import CacheStore, HttpResponse
from reflect.sources import RegistryEntry, ReuseMode


WHEEL_NAME = "numpy-2.4.6-cp311-cp311-macosx_14_0_arm64.whl"
WHEEL_URL = f"https://files.pythonhosted.org/packages/aa/bb/{'c' * 64}/{WHEEL_NAME}"
EXPRESSION = "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0"
DIST_INFO = "numpy-2.4.6.dist-info"


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
