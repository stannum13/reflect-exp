"""Exact-wheel Core Metadata evidence for direct-dependency installation."""

from __future__ import annotations

import base64
from collections.abc import Mapping
import csv
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
import hashlib
import io
import json
import platform
from pathlib import PurePosixPath
import re
import sys
import sysconfig
import tomllib
from types import MappingProxyType
from urllib.parse import urlsplit
import zipfile

from reflect._source_cache import CacheStore
from reflect._source_http import Transport, _timestamp, _validate_response_status
from reflect.sources import RegistryEntry, ReuseMode, is_spdx_expression


class PackageLicenseError(ValueError):
    """Raised when locked distribution license evidence is not exact and complete."""


class PackageLicenseUnavailable(PackageLicenseError):
    """Raised when a package has no exact compatible locked wheel."""


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PYTHONHOSTED_WHEEL = re.compile(
    r"https://files\.pythonhosted\.org/packages/[0-9a-f]{2}/[0-9a-f]{2}/"
    r"[0-9a-f]{32,}/([^/?#]+\.whl)\Z"
)
_NORMALIZE_NAME = re.compile(r"[-_.]+")
_MAX_WHEEL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class LockedWheel:
    package_name: str
    package_version: str
    filename: str
    url: str
    sha256: str


def current_wheel_tags() -> tuple[str, ...]:
    """Return the bounded compatible tag order for the locked CPython host."""
    cache_tag = sys.implementation.cache_tag
    if type(cache_tag) is not str or re.fullmatch(r"cpython-[0-9]{3}", cache_tag) is None:
        raise PackageLicenseError("current interpreter has no supported CPython wheel tag")
    python_tag = "cp" + cache_tag.removeprefix("cpython-")
    abi_tag = python_tag
    value = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    platforms: list[str] = []
    mac = re.fullmatch(r"macosx_([0-9]+)_([0-9]+)_([A-Za-z0-9_]+)", value)
    if mac is not None:
        major, minor, architecture = int(mac.group(1)), int(mac.group(2)), mac.group(3)
        if major < 11:
            raise PackageLicenseError("current macOS platform is unsupported")
        platforms.extend(
            f"macosx_{candidate}_{minor if candidate == major else 0}_{architecture}"
            for candidate in range(major, 10, -1)
        )
    else:
        linux = re.fullmatch(r"linux_([A-Za-z0-9_]+)", value)
        windows = re.fullmatch(r"win(?:32|_([A-Za-z0-9_]+))", value)
        if linux is not None:
            architecture = linux.group(1)
            libc, version = platform.libc_ver()
            match = re.fullmatch(r"([0-9]+)\.([0-9]+)", version)
            if libc != "glibc" or match is None or int(match.group(1)) != 2:
                raise PackageLicenseError("current Linux libc has no supported wheel tag")
            platforms.extend(
                f"manylinux_2_{minor}_{architecture}"
                for minor in range(int(match.group(2)), 16, -1)
            )
            platforms.append(value)
        elif windows is not None:
            platforms.append(value)
        else:
            raise PackageLicenseError("current platform has no supported wheel tag")
    tags = [f"{python_tag}-{abi_tag}-{item}" for item in platforms]
    tags.extend((f"{python_tag}-abi3-{item}" for item in platforms))
    tags.append("py3-none-any")
    return tuple(tags)


class LockedWheelLicenseResolver:
    """Resolve exact-wheel license evidence using a checksummed resumable cache."""

    def __init__(
        self,
        *,
        uv_lock_bytes: bytes,
        transport: Transport,
        cache: CacheStore,
        clock: object,
        compatible_tags: tuple[str, ...] | None = None,
    ) -> None:
        if not callable(clock):
            raise PackageLicenseError("artifact clock must be callable")
        self._uv_lock_bytes = uv_lock_bytes
        self._transport = transport
        self._cache = cache
        self._clock = clock
        self._compatible_tags = compatible_tags or current_wheel_tags()

    def eligible(self, entry: RegistryEntry) -> bool:
        """Return whether this direct dependency has an exact compatible wheel."""
        if not isinstance(entry, RegistryEntry) or entry.mode is not ReuseMode.DIRECT_DEPENDENCY:
            return False
        try:
            select_locked_wheel(
                self._uv_lock_bytes,
                package_name=entry.name,
                compatible_tags=self._compatible_tags,
            )
        except PackageLicenseUnavailable:
            return False
        return True

    def __call__(self, entry: RegistryEntry) -> MappingProxyType[str, str]:
        if not isinstance(entry, RegistryEntry) or entry.mode is not ReuseMode.DIRECT_DEPENDENCY:
            raise PackageLicenseError("artifact license resolution requires a direct dependency")
        wheel = select_locked_wheel(
            self._uv_lock_bytes,
            package_name=entry.name,
            compatible_tags=self._compatible_tags,
        )
        key = f"wheel-{wheel.sha256}"
        cached = self._cache.load(entry.name, key, endpoint=wheel.url)
        if cached is None:
            response = self._transport.get(wheel.url)
            _validate_response_status(response, wheel.url)
            if response.url != wheel.url:
                raise PackageLicenseError("wheel response changed the exact locked URL")
            retrieved_at = _timestamp(self._clock)  # type: ignore[arg-type]
            self._cache.write(
                entry.name,
                key,
                endpoint=wheel.url,
                payload=response.body,
                retrieved_at=retrieved_at,
                etag=response.headers.get("etag"),
            )
            wheel_bytes = response.body
        else:
            wheel_bytes = cached.payload
        return verify_locked_wheel_license(
            package_name=wheel.package_name,
            package_version=wheel.package_version,
            wheel_filename=wheel.filename,
            wheel_url=wheel.url,
            wheel_sha256=wheel.sha256,
            wheel_bytes=wheel_bytes,
        )


def _normalized_name(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise PackageLicenseError(f"{label} must be a nonempty string")
    return _NORMALIZE_NAME.sub("-", value).lower()


def _safe_member(value: str, label: str) -> PurePosixPath:
    if "\\" in value:
        raise PackageLicenseError(f"{label} is unsafe")
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or value.endswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise PackageLicenseError(f"{label} is unsafe")
    return path


def _wheel_tag(filename: str, package_name: str, version: str) -> str:
    if not filename.endswith(".whl"):
        raise PackageLicenseError("locked artifact is not a wheel")
    parts = filename[:-4].rsplit("-", 3)
    expected_prefix = f"{package_name.replace('-', '_')}-{version.replace('-', '_')}"
    if len(parts) != 4 or parts[0].lower() != expected_prefix.lower():
        raise PackageLicenseError("locked wheel filename does not match package/version")
    return "-".join(parts[1:])


def select_locked_wheel(
    uv_lock_bytes: bytes,
    *,
    package_name: str,
    compatible_tags: tuple[str, ...],
) -> LockedWheel:
    """Select the highest-ranked compatible wheel sealed by exact uv.lock bytes."""
    if not isinstance(uv_lock_bytes, bytes):
        raise PackageLicenseError("uv.lock must be bytes")
    if (
        not isinstance(compatible_tags, tuple)
        or not compatible_tags
        or any(type(item) is not str or not item for item in compatible_tags)
        or len(set(compatible_tags)) != len(compatible_tags)
    ):
        raise PackageLicenseError("compatible wheel tags must be a distinct tuple")
    requested = _normalized_name(package_name, "package name")
    try:
        document = tomllib.loads(uv_lock_bytes.decode("utf-8", "strict"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PackageLicenseError("uv.lock is not valid UTF-8 TOML") from exc
    packages = document.get("package")
    if not isinstance(packages, list):
        raise PackageLicenseError("uv.lock has no package inventory")
    matches = [
        item
        for item in packages
        if isinstance(item, dict)
        and type(item.get("name")) is str
        and _normalized_name(item["name"], "locked package name") == requested
    ]
    if not matches:
        raise PackageLicenseUnavailable("uv.lock has no locked package")
    if len(matches) != 1:
        raise PackageLicenseError("uv.lock must contain exactly one locked package")
    package = matches[0]
    version = package.get("version")
    if type(version) is not str or not version:
        raise PackageLicenseError("locked package version must be a nonempty string")
    wheels = package.get("wheels")
    if not isinstance(wheels, list) or not wheels:
        raise PackageLicenseUnavailable("locked package has no wheels")
    ranks = {tag: index for index, tag in enumerate(compatible_tags)}
    candidates: list[tuple[int, LockedWheel]] = []
    for item in wheels:
        if not isinstance(item, dict) or set(item) - {"url", "hash", "size", "upload-time"}:
            raise PackageLicenseError("locked wheel entry has an invalid schema")
        url, digest = item.get("url"), item.get("hash")
        if type(url) is not str or type(digest) is not str or not digest.startswith("sha256:"):
            raise PackageLicenseError("locked wheel URL/hash is invalid")
        match = _PYTHONHOSTED_WHEEL.fullmatch(url)
        sha256 = digest.removeprefix("sha256:")
        if match is None or not _SHA256.fullmatch(sha256):
            raise PackageLicenseError("locked wheel URL/hash is invalid")
        filename = match.group(1)
        if urlsplit(url).path.rsplit("/", 1)[-1] != filename:
            raise PackageLicenseError("locked wheel URL filename is ambiguous")
        tag = _wheel_tag(filename, requested, version)
        expanded = (
            f"{python}-{abi}-{platform}"
            for python in tag.split("-")[0].split(".")
            for abi in tag.split("-")[1].split(".")
            for platform in tag.split("-")[2].split(".")
        )
        compatible = [ranks[value] for value in expanded if value in ranks]
        if compatible:
            candidates.append(
                (
                    min(compatible),
                    LockedWheel(requested, version, filename, url, sha256),
                )
            )
    if not candidates:
        raise PackageLicenseUnavailable("uv.lock has no compatible locked wheel")
    candidates.sort(key=lambda item: (item[0], item[1].filename, item[1].sha256))
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        raise PackageLicenseError("uv.lock has ambiguous compatible locked wheels")
    return candidates[0][1]


def validate_locked_install_evidence(
    *,
    package_name: str,
    metadata_evidence: Mapping[str, str],
    uv_lock_bytes: bytes,
    compatible_tags: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Rebind a structural artifact observation to the current exact uv.lock."""
    try:
        selected = select_locked_wheel(
            uv_lock_bytes,
            package_name=package_name,
            compatible_tags=compatible_tags or current_wheel_tags(),
        )
    except PackageLicenseError as exc:
        return (f"could not bind artifact evidence to uv.lock: {package_name}: {exc}",)
    expected = {
        "artifact_license.package_name": selected.package_name,
        "artifact_license.package_version": selected.package_version,
        "artifact_license.wheel_filename": selected.filename,
        "artifact_license.wheel_url": selected.url,
        "artifact_license.wheel_sha256": selected.sha256,
    }
    if any(metadata_evidence.get(key) != value for key, value in expected.items()):
        return (f"artifact evidence does not match the selected uv.lock wheel: {package_name}",)
    return ()


def _record_digest(data: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"sha256={encoded.decode('ascii')}"


def _verified_record(record: bytes, members: dict[str, bytes]) -> dict[str, tuple[str, int]]:
    try:
        rows = tuple(csv.reader(io.StringIO(record.decode("utf-8", "strict"))))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise PackageLicenseError("wheel RECORD is invalid") from exc
    parsed: dict[str, tuple[str, int]] = {}
    for row in rows:
        if len(row) != 3:
            raise PackageLicenseError("wheel RECORD is invalid")
        path, digest, size = row
        _safe_member(path, "RECORD path")
        if path in parsed:
            raise PackageLicenseError("wheel RECORD contains a duplicate path")
        if digest:
            if not digest.startswith("sha256="):
                raise PackageLicenseError("wheel RECORD digest is not SHA-256")
            try:
                parsed_size = int(size)
            except ValueError as exc:
                raise PackageLicenseError("wheel RECORD size is invalid") from exc
            if parsed_size < 0:
                raise PackageLicenseError("wheel RECORD size is invalid")
        else:
            if size:
                raise PackageLicenseError("wheel RECORD has size without digest")
            parsed_size = -1
        parsed[path] = (digest, parsed_size)
    for path, data in members.items():
        if path not in parsed:
            raise PackageLicenseError(f"wheel RECORD omits member: {path}")
        digest, size = parsed[path]
        if not digest:
            if not path.endswith(".dist-info/RECORD"):
                raise PackageLicenseError("wheel RECORD omits a member digest")
        elif digest != _record_digest(data) or size != len(data):
            raise PackageLicenseError(f"wheel RECORD does not match member: {path}")
    if set(parsed) != set(members):
        raise PackageLicenseError("wheel RECORD lists an absent member")
    return parsed


def verify_locked_wheel_license(
    *,
    package_name: str,
    package_version: str,
    wheel_filename: str,
    wheel_url: str,
    wheel_sha256: str,
    wheel_bytes: bytes,
) -> MappingProxyType[str, str]:
    """Verify a locked wheel and return closed install-only factual evidence."""
    normalized = _normalized_name(package_name, "package name")
    if type(package_version) is not str or not package_version:
        raise PackageLicenseError("package version must be a nonempty string")
    match = _PYTHONHOSTED_WHEEL.fullmatch(wheel_url)
    if match is None or match.group(1) != wheel_filename:
        raise PackageLicenseError("wheel URL does not match exact wheel filename")
    _wheel_tag(wheel_filename, normalized, package_version)
    if not _SHA256.fullmatch(wheel_sha256) or hashlib.sha256(wheel_bytes).hexdigest() != wheel_sha256:
        raise PackageLicenseError("wheel SHA-256 does not match locked digest")
    try:
        with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
            infos = archive.infolist()
            if sum(info.file_size for info in infos) > _MAX_WHEEL_UNCOMPRESSED_BYTES:
                raise PackageLicenseError("wheel uncompressed content exceeds size limit")
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise PackageLicenseError("wheel contains a duplicate member")
            members: dict[str, bytes] = {}
            for info in infos:
                if info.is_dir():
                    _safe_member(info.filename.removesuffix("/"), "wheel directory")
                    continue
                _safe_member(info.filename, "wheel member")
                members[info.filename] = archive.read(info)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise PackageLicenseError("wheel is not a valid ZIP archive") from exc
    normalized_dist = normalized.replace("-", "_")
    normalized_version = package_version.replace("-", "_")
    dist_info = f"{normalized_dist}-{normalized_version}.dist-info"
    metadata_path = f"{dist_info}/METADATA"
    record_path = f"{dist_info}/RECORD"
    if metadata_path not in members or record_path not in members:
        raise PackageLicenseError("wheel has no exact matching METADATA and RECORD")
    if len({name.split("/", 1)[0] for name in names if ".dist-info/" in name}) != 1:
        raise PackageLicenseError("wheel has an ambiguous dist-info directory")
    _verified_record(members[record_path], members)
    try:
        metadata = BytesParser(policy=compat32).parsebytes(members[metadata_path])
    except (TypeError, ValueError) as exc:
        raise PackageLicenseError("wheel METADATA is invalid") from exc
    names_found = metadata.get_all("Name", [])
    versions_found = metadata.get_all("Version", [])
    metadata_versions = metadata.get_all("Metadata-Version", [])
    expressions = metadata.get_all("License-Expression", [])
    declared = metadata.get_all("License-File", [])
    if len(names_found) != 1 or _normalized_name(names_found[0], "package name") != normalized:
        raise PackageLicenseError("wheel METADATA package name does not match")
    if len(versions_found) != 1 or versions_found[0] != package_version:
        raise PackageLicenseError("wheel METADATA package version does not match")
    if len(metadata_versions) != 1 or metadata_versions[0] != "2.4":
        raise PackageLicenseError("wheel METADATA must use Metadata-Version 2.4")
    if len(expressions) != 1 or type(expressions[0]) is not str or not expressions[0].strip():
        raise PackageLicenseError("wheel METADATA must contain exactly one License-Expression")
    if not is_spdx_expression(expressions[0].strip()):
        raise PackageLicenseError("wheel METADATA License-Expression is not an SPDX expression")
    if not declared:
        raise PackageLicenseError("wheel METADATA must declare License-File")
    if any(type(item) is not str for item in declared) or len(set(declared)) != len(declared):
        raise PackageLicenseError("wheel METADATA has duplicate License-File")
    inventory: list[dict[str, str]] = []
    for relative in declared:
        safe = _safe_member(relative, "License-File")
        path = f"{dist_info}/licenses/{safe.as_posix()}"
        if path not in members:
            raise PackageLicenseError(f"wheel omits declared license file: {relative}")
        inventory.append({"path": path, "sha256": hashlib.sha256(members[path]).hexdigest()})
    inventory.sort(key=lambda item: item["path"])
    actual_license_files = {
        path for path in members if path.startswith(f"{dist_info}/licenses/")
    }
    if actual_license_files != {item["path"] for item in inventory}:
        raise PackageLicenseError("wheel license inventory is not completely declared")
    evidence = {
        "artifact_license.authority": "EXACT_WHEEL_INSTALL_ONLY",
        "artifact_license.package_name": normalized,
        "artifact_license.package_version": package_version,
        "artifact_license.wheel_filename": wheel_filename,
        "artifact_license.wheel_url": wheel_url,
        "artifact_license.wheel_sha256": wheel_sha256,
        "artifact_license.metadata_path": metadata_path,
        "artifact_license.metadata_sha256": hashlib.sha256(members[metadata_path]).hexdigest(),
        "artifact_license.record_path": record_path,
        "artifact_license.record_sha256": hashlib.sha256(members[record_path]).hexdigest(),
        "artifact_license.license_expression": expressions[0].strip(),
        "artifact_license.license_files_json": json.dumps(
            inventory, sort_keys=True, separators=(",", ":")
        ),
    }
    return MappingProxyType(evidence)
