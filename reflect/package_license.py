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
import os
import platform
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import sysconfig
import tarfile
import tomllib
from types import MappingProxyType
from urllib.parse import urlsplit
import zipfile

import yaml

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
_MAX_SDIST_UNCOMPRESSED_BYTES = 256 * 1024 * 1024


_BOOTSTRAP_CONFIG_KEYS = frozenset(
    {
        "name", "version", "tag", "commit_sha", "repository_url",
        "sdist_filename", "sdist_url", "sdist_sha256", "sdist_size",
        "wheel_filename", "wheel_url", "wheel_sha256", "wheel_size",
        "workspace_manifest_path", "workspace_manifest_sha256",
        "package_manifest_path", "package_manifest_sha256",
        "license_apache_sha256", "license_mit_sha256",
        "embedded_executable_path", "embedded_executable_sha256",
        "embedded_executable_size",
    }
)


def _bootstrap_string(config: Mapping[str, object], key: str) -> str:
    value = config.get(key)
    if type(value) is not str or not value:
        raise PackageLicenseError(f"bootstrap {key} must be a nonempty string")
    return value


def _bootstrap_size(config: Mapping[str, object], key: str) -> int:
    value = config.get(key)
    if type(value) is not int or value <= 0:
        raise PackageLicenseError(f"bootstrap {key} must be a positive integer")
    return value


def _tar_members(data: bytes) -> dict[str, bytes]:
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            result: dict[str, bytes] = {}
            total = 0
            for member in archive.getmembers():
                path = _safe_member(member.name.removesuffix("/"), "sdist member")
                if member.isdir():
                    continue
                if not member.isfile() or member.issym() or member.islnk():
                    raise PackageLicenseError("sdist contains a non-regular member")
                if path.as_posix() in result:
                    raise PackageLicenseError("sdist contains a duplicate member")
                total += member.size
                if total > _MAX_SDIST_UNCOMPRESSED_BYTES:
                    raise PackageLicenseError("sdist uncompressed content exceeds size limit")
                stream = archive.extractfile(member)
                if stream is None:
                    raise PackageLicenseError("sdist member cannot be read")
                result[path.as_posix()] = stream.read()
            return result
    except (tarfile.TarError, OSError) as exc:
        raise PackageLicenseError("sdist is not a valid gzip tar archive") from exc


def _wheel_members(data: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if sum(info.file_size for info in infos) > _MAX_WHEEL_UNCOMPRESSED_BYTES:
                raise PackageLicenseError("wheel uncompressed content exceeds size limit")
            result: dict[str, bytes] = {}
            for info in infos:
                path = _safe_member(info.filename.removesuffix("/"), "wheel member")
                if info.is_dir():
                    continue
                if path.as_posix() in result:
                    raise PackageLicenseError("wheel contains a duplicate member")
                result[path.as_posix()] = archive.read(info)
            return result
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise PackageLicenseError("wheel is not a valid ZIP archive") from exc


def verify_bootstrap_artifact(
    *,
    config: Mapping[str, object],
    sdist_bytes: bytes,
    wheel_bytes: bytes,
    workspace_manifest_bytes: bytes,
    package_manifest_bytes: bytes,
    license_file_bytes: Mapping[str, bytes],
    host_executable_path: object,
    version_output: str,
    tag_commit: str,
) -> MappingProxyType[str, str]:
    """Verify uv's sealed release and exact invoked binary without license inference."""
    if not isinstance(config, Mapping) or set(config) != _BOOTSTRAP_CONFIG_KEYS:
        raise PackageLicenseError("bootstrap artifact config has an invalid schema")
    name = _bootstrap_string(config, "name")
    version = _bootstrap_string(config, "version")
    tag = _bootstrap_string(config, "tag")
    commit = _bootstrap_string(config, "commit_sha")
    repository_url = _bootstrap_string(config, "repository_url")
    if name != "uv" or tag != version or repository_url != "https://github.com/astral-sh/uv":
        raise PackageLicenseError("bootstrap package/version/tag identity is invalid")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None or tag_commit != commit:
        raise PackageLicenseError("bootstrap tag commit does not match")
    version_match = re.fullmatch(r"uv ([0-9]+\.[0-9]+\.[0-9]+) \(([0-9a-f]+) [^)]+\)", version_output)
    if (
        version_match is None
        or version_match.group(1) != version
        or len(version_match.group(2)) < 9
        or not commit.startswith(version_match.group(2))
    ):
        raise PackageLicenseError("bootstrap version output does not bind version and commit")
    for label, data in (("sdist", sdist_bytes), ("wheel", wheel_bytes)):
        if not isinstance(data, bytes):
            raise PackageLicenseError(f"bootstrap {label} must be bytes")
        if len(data) != _bootstrap_size(config, f"{label}_size"):
            raise PackageLicenseError(f"bootstrap {label} size does not match")
        digest = _bootstrap_string(config, f"{label}_sha256")
        if _SHA256.fullmatch(digest) is None or hashlib.sha256(data).hexdigest() != digest:
            raise PackageLicenseError(f"bootstrap {label} SHA-256 does not match")
    for label, suffix in (("sdist", ".tar.gz"), ("wheel", ".whl")):
        filename = _bootstrap_string(config, f"{label}_filename")
        url = _bootstrap_string(config, f"{label}_url")
        if not filename.endswith(suffix) or url.rsplit("/", 1)[-1] != filename or not url.startswith("https://files.pythonhosted.org/packages/"):
            raise PackageLicenseError(f"bootstrap {label} URL/filename is invalid")

    workspace_path = _bootstrap_string(config, "workspace_manifest_path")
    package_path = _bootstrap_string(config, "package_manifest_path")
    if workspace_path != "Cargo.toml" or package_path != "crates/uv/Cargo.toml":
        raise PackageLicenseError("bootstrap Cargo manifest paths are invalid")
    for label, data in (("workspace", workspace_manifest_bytes), ("package", package_manifest_bytes)):
        digest = _bootstrap_string(config, f"{label}_manifest_sha256")
        if _SHA256.fullmatch(digest) is None or hashlib.sha256(data).hexdigest() != digest:
            raise PackageLicenseError(f"bootstrap {label} manifest does not match exact commit")
    try:
        workspace_doc = tomllib.loads(workspace_manifest_bytes.decode("utf-8", "strict"))
        package_doc = tomllib.loads(package_manifest_bytes.decode("utf-8", "strict"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PackageLicenseError("bootstrap Cargo manifest is invalid") from exc
    workspace_package = workspace_doc.get("workspace", {}).get("package")
    package = package_doc.get("package")
    if not isinstance(workspace_package, dict):
        raise PackageLicenseError("bootstrap workspace license is absent")
    expression = workspace_package.get("license")
    if type(expression) is not str or not is_spdx_expression(expression):
        raise PackageLicenseError("bootstrap workspace license is not a valid SPDX expression")
    if (
        not isinstance(package, dict)
        or package.get("name") != name
        or package.get("version") != version
        or package.get("license") != {"workspace": True}
    ):
        raise PackageLicenseError("bootstrap package manifest does not inherit the workspace license")

    sdist = _tar_members(sdist_bytes)
    prefix = f"uv-{version}/"
    sdist_workspace = sdist.get(prefix + workspace_path)
    sdist_package = sdist.get(prefix + package_path)
    if sdist_workspace != workspace_manifest_bytes:
        raise PackageLicenseError("bootstrap sdist workspace manifest differs from exact commit")
    if sdist_package is None:
        raise PackageLicenseError("bootstrap sdist omits package manifest")
    try:
        sdist_package_doc = tomllib.loads(sdist_package.decode("utf-8", "strict"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PackageLicenseError("bootstrap sdist package manifest is invalid") from exc
    sdist_package_data = sdist_package_doc.get("package")
    if (
        not isinstance(sdist_package_data, dict)
        or any(sdist_package_data.get(key) != package.get(key) for key in ("name", "version", "license"))
    ):
        raise PackageLicenseError("bootstrap sdist package manifest disagrees with exact commit")

    wheel = _wheel_members(wheel_bytes)
    dist_info = f"uv-{version}.dist-info"
    metadata_path, record_path = f"{dist_info}/METADATA", f"{dist_info}/RECORD"
    if metadata_path not in wheel or record_path not in wheel:
        raise PackageLicenseError("bootstrap wheel omits METADATA or RECORD")
    _verified_record(wheel[record_path], wheel)
    metadata = BytesParser(policy=compat32).parsebytes(wheel[metadata_path])
    if metadata.get_all("Name", []) != [name] or metadata.get_all("Version", []) != [version]:
        raise PackageLicenseError("bootstrap wheel METADATA identity does not match")
    declared = metadata.get_all("License-File", [])
    if declared != ["LICENSE-APACHE", "LICENSE-MIT"]:
        raise PackageLicenseError("bootstrap wheel must declare the exact two-license inventory")
    if not isinstance(license_file_bytes, Mapping) or set(license_file_bytes) != {
        "LICENSE-APACHE", "LICENSE-MIT"
    }:
        raise PackageLicenseError("bootstrap exact-commit license inventory is invalid")
    license_inventory: list[dict[str, str]] = []
    for relative in declared:
        wheel_path = f"{dist_info}/licenses/{relative}"
        sdist_path = prefix + relative
        expected_key = "license_apache_sha256" if relative == "LICENSE-APACHE" else "license_mit_sha256"
        raw_license = license_file_bytes.get(relative)
        expected_license_sha = _bootstrap_string(config, expected_key)
        if (
            not isinstance(raw_license, bytes)
            or _SHA256.fullmatch(expected_license_sha) is None
            or hashlib.sha256(raw_license).hexdigest() != expected_license_sha
            or wheel.get(wheel_path) != raw_license
            or sdist.get(sdist_path) != raw_license
        ):
            raise PackageLicenseError("bootstrap wheel/sdist/exact-commit license inventory differs")
        license_inventory.append({"path": wheel_path, "sha256": hashlib.sha256(wheel[wheel_path]).hexdigest()})
    actual_licenses = {path for path in wheel if path.startswith(f"{dist_info}/licenses/")}
    if actual_licenses != {item["path"] for item in license_inventory}:
        raise PackageLicenseError("bootstrap wheel license inventory is not exact")

    embedded_path = _bootstrap_string(config, "embedded_executable_path")
    embedded = wheel.get(embedded_path)
    expected_binary_sha = _bootstrap_string(config, "embedded_executable_sha256")
    expected_binary_size = _bootstrap_size(config, "embedded_executable_size")
    if embedded is None or len(embedded) != expected_binary_size or hashlib.sha256(embedded).hexdigest() != expected_binary_sha:
        raise PackageLicenseError("bootstrap embedded executable identity does not match")
    executable = os.path.abspath(os.fspath(host_executable_path))
    host = _read_stable_executable(Path(executable), expected_binary_size)
    if host != embedded:
        raise PackageLicenseError("bootstrap host executable is not byte-identical to wheel")
    evidence = {
        "bootstrap_artifact.authority": "EXACT_BOOTSTRAP_BINARY_USE_ONLY",
        "bootstrap_artifact.package_name": name,
        "bootstrap_artifact.package_version": version,
        "bootstrap_artifact.tag": tag,
        "bootstrap_artifact.commit_sha": commit,
        "bootstrap_artifact.repository_url": repository_url,
        "bootstrap_artifact.sdist_filename": _bootstrap_string(config, "sdist_filename"),
        "bootstrap_artifact.sdist_url": _bootstrap_string(config, "sdist_url"),
        "bootstrap_artifact.sdist_sha256": _bootstrap_string(config, "sdist_sha256"),
        "bootstrap_artifact.sdist_size": str(_bootstrap_size(config, "sdist_size")),
        "bootstrap_artifact.wheel_filename": _bootstrap_string(config, "wheel_filename"),
        "bootstrap_artifact.wheel_url": _bootstrap_string(config, "wheel_url"),
        "bootstrap_artifact.wheel_sha256": _bootstrap_string(config, "wheel_sha256"),
        "bootstrap_artifact.wheel_size": str(_bootstrap_size(config, "wheel_size")),
        "bootstrap_artifact.workspace_manifest_path": workspace_path,
        "bootstrap_artifact.workspace_manifest_url": f"https://raw.githubusercontent.com/astral-sh/uv/{commit}/{workspace_path}",
        "bootstrap_artifact.workspace_manifest_sha256": hashlib.sha256(workspace_manifest_bytes).hexdigest(),
        "bootstrap_artifact.package_manifest_path": package_path,
        "bootstrap_artifact.package_manifest_url": f"https://raw.githubusercontent.com/astral-sh/uv/{commit}/{package_path}",
        "bootstrap_artifact.package_manifest_sha256": hashlib.sha256(package_manifest_bytes).hexdigest(),
        "bootstrap_artifact.license_expression": expression,
        "bootstrap_artifact.metadata_sha256": hashlib.sha256(wheel[metadata_path]).hexdigest(),
        "bootstrap_artifact.record_sha256": hashlib.sha256(wheel[record_path]).hexdigest(),
        "bootstrap_artifact.license_files_json": json.dumps(license_inventory, sort_keys=True, separators=(",", ":")),
        "bootstrap_artifact.embedded_executable_path": embedded_path,
        "bootstrap_artifact.executable_sha256": expected_binary_sha,
        "bootstrap_artifact.executable_size": str(expected_binary_size),
        "bootstrap_artifact.host_executable_path": executable,
        "bootstrap_artifact.version_output": version_output,
    }
    return MappingProxyType(evidence)


def _read_stable_executable(path: Path, expected_size: int) -> bytes:
    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or not stat.S_ISREG(opened.st_mode)
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
                or opened.st_size != expected_size
            ):
                raise PackageLicenseError("bootstrap host executable is not a stable regular file")
            chunks: list[bytes] = []
            retained = 0
            while retained <= expected_size:
                chunk = os.read(descriptor, min(1024 * 1024, expected_size + 1 - retained))
                if not chunk:
                    break
                chunks.append(chunk)
                retained += len(chunk)
            data = b"".join(chunks)
        finally:
            os.close(descriptor)
        after = path.lstat()
    except OSError as exc:
        raise PackageLicenseError("bootstrap host executable cannot be read") from exc
    if (
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        or len(data) != expected_size
    ):
        raise PackageLicenseError("bootstrap host executable changed during inspection")
    return data


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


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(
    loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise PackageLicenseError(f"bootstrap artifact YAML contains duplicate key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping
)


def load_bootstrap_artifact_config(path: Path) -> MappingProxyType[str, object]:
    """Load the one closed uv bootstrap artifact record."""
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PackageLicenseError(f"could not read bootstrap artifact config: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "artifacts"}:
        raise PackageLicenseError("bootstrap artifact document has an invalid schema")
    if raw["schema_version"] != 1 or type(raw["artifacts"]) is not list or len(raw["artifacts"]) != 1:
        raise PackageLicenseError("bootstrap artifact document must contain one version-1 record")
    record = raw["artifacts"][0]
    if not isinstance(record, dict) or set(record) != _BOOTSTRAP_CONFIG_KEYS:
        raise PackageLicenseError("bootstrap artifact config has an invalid schema")
    return MappingProxyType(dict(record))


def _default_tag_resolver(repository_url: str, tag: str) -> str:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    for key in tuple(environment):
        if key == "SSH_ASKPASS" or key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}:
            environment.pop(key, None)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    args = [
        "git", "-c", "credential.helper=", "-c", "http.followRedirects=false",
        "-c", "http.proxy=", "-c", "https.proxy=", "ls-remote",
        repository_url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}",
    ]
    try:
        completed = subprocess.run(
            args, capture_output=True, text=True, timeout=30, check=False,
            env=environment, cwd=os.path.abspath(os.sep),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PackageLicenseError("bootstrap tag resolution failed") from exc
    if completed.returncode != 0:
        raise PackageLicenseError("bootstrap tag resolution failed")
    rows = [line.split("\t", 1) for line in completed.stdout.splitlines() if "\t" in line]
    direct = [sha for sha, ref in rows if ref == f"refs/tags/{tag}"]
    peeled = [sha for sha, ref in rows if ref == f"refs/tags/{tag}^{{}}"]
    if len(direct) != 1 or len(peeled) > 1:
        raise PackageLicenseError("bootstrap tag resolution is ambiguous")
    commit = peeled[0] if peeled else direct[0]
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise PackageLicenseError("bootstrap tag commit is invalid")
    return commit


def _default_version_runner(executable: Path) -> str:
    try:
        completed = subprocess.run(
            [os.fspath(executable), "--version"], capture_output=True, text=True,
            timeout=10, check=False, env={"PATH": os.defpath}, cwd=os.path.abspath(os.sep),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PackageLicenseError("bootstrap version command failed") from exc
    if completed.returncode != 0 or completed.stderr or not completed.stdout.endswith("\n"):
        raise PackageLicenseError("bootstrap version command failed")
    return completed.stdout.removesuffix("\n")


class BootstrapArtifactResolver:
    """Resolve the separately sealed exact host uv execution authority."""

    def __init__(
        self,
        *,
        config_path: Path,
        transport: Transport,
        cache: CacheStore,
        clock: object,
        executable_path: Path | None = None,
        tag_resolver: object = _default_tag_resolver,
        version_runner: object = _default_version_runner,
    ) -> None:
        if not callable(clock) or not callable(tag_resolver) or not callable(version_runner):
            raise PackageLicenseError("bootstrap resolver callbacks must be callable")
        self._config = load_bootstrap_artifact_config(config_path)
        self._transport = transport
        self._cache = cache
        self._clock = clock
        selected = executable_path or (Path(found) if (found := shutil.which("uv")) else None)
        if selected is None or not selected.is_absolute():
            raise PackageLicenseError("bootstrap uv executable must have an absolute path")
        self._executable_path = selected
        self._tag_resolver = tag_resolver
        self._version_runner = version_runner

    def eligible(self, entry: RegistryEntry) -> bool:
        return (
            isinstance(entry, RegistryEntry)
            and entry.mode is ReuseMode.DIRECT_DEPENDENCY
            and entry.name == "uv"
        )

    def _payload(self, url: str, key: str) -> bytes:
        cached = self._cache.load("uv", key, endpoint=url)
        if cached is not None:
            return cached.payload
        response = self._transport.get(url)
        _validate_response_status(response, url)
        if response.url != url:
            raise PackageLicenseError("bootstrap artifact response changed exact URL")
        self._cache.write(
            "uv", key, endpoint=url, payload=response.body,
            retrieved_at=_timestamp(self._clock), etag=response.headers.get("etag"),
        )
        return response.body

    def __call__(self, entry: RegistryEntry) -> MappingProxyType[str, str]:
        if not self.eligible(entry):
            raise PackageLicenseError("bootstrap authority requires the uv direct dependency")
        config = self._config
        commit = _bootstrap_string(config, "commit_sha")
        repository = _bootstrap_string(config, "repository_url")
        workspace_path = _bootstrap_string(config, "workspace_manifest_path")
        package_path = _bootstrap_string(config, "package_manifest_path")
        workspace_url = f"https://raw.githubusercontent.com/astral-sh/uv/{commit}/{workspace_path}"
        package_url = f"https://raw.githubusercontent.com/astral-sh/uv/{commit}/{package_path}"
        apache_url = f"https://raw.githubusercontent.com/astral-sh/uv/{commit}/LICENSE-APACHE"
        mit_url = f"https://raw.githubusercontent.com/astral-sh/uv/{commit}/LICENSE-MIT"
        sdist = self._payload(_bootstrap_string(config, "sdist_url"), f"bootstrap-sdist-{config['sdist_sha256']}")
        wheel = self._payload(_bootstrap_string(config, "wheel_url"), f"bootstrap-wheel-{config['wheel_sha256']}")
        workspace = self._payload(workspace_url, f"bootstrap-workspace-{config['workspace_manifest_sha256']}")
        package = self._payload(package_url, f"bootstrap-package-{config['package_manifest_sha256']}")
        licenses = {
            "LICENSE-APACHE": self._payload(apache_url, f"bootstrap-license-apache-{config['license_apache_sha256']}"),
            "LICENSE-MIT": self._payload(mit_url, f"bootstrap-license-mit-{config['license_mit_sha256']}"),
        }
        return verify_bootstrap_artifact(
            config=config,
            sdist_bytes=sdist,
            wheel_bytes=wheel,
            workspace_manifest_bytes=workspace,
            package_manifest_bytes=package,
            license_file_bytes=licenses,
            host_executable_path=self._executable_path,
            version_output=self._version_runner(self._executable_path),  # type: ignore[operator]
            tag_commit=self._tag_resolver(  # type: ignore[operator]
                repository, _bootstrap_string(config, "tag")
            ),
        )


class CompositeLicenseResolver:
    """Choose exactly one eligible artifact-scoped license resolver."""

    def __init__(self, *resolvers: object) -> None:
        self._resolvers = resolvers

    def eligible(self, entry: RegistryEntry) -> bool:
        return any(callable(getattr(item, "eligible", None)) and item.eligible(entry) for item in self._resolvers)  # type: ignore[attr-defined]

    def __call__(self, entry: RegistryEntry) -> Mapping[str, str]:
        eligible = [item for item in self._resolvers if callable(getattr(item, "eligible", None)) and item.eligible(entry)]  # type: ignore[attr-defined]
        if len(eligible) != 1 or not callable(eligible[0]):
            raise PackageLicenseError("artifact resolver selection is not exact")
        return eligible[0](entry)  # type: ignore[operator]


def validate_bootstrap_binary_evidence(
    *,
    config_path: Path,
    metadata_evidence: Mapping[str, str],
    version_runner: object = _default_version_runner,
) -> tuple[str, ...]:
    """Rebind stored bootstrap authority to the sealed source and current host binary."""
    try:
        config = load_bootstrap_artifact_config(config_path)
    except PackageLicenseError as exc:
        return (f"could not load bootstrap artifact source: {exc}",)
    expected = {
        "bootstrap_artifact.authority": "EXACT_BOOTSTRAP_BINARY_USE_ONLY",
        "bootstrap_artifact.package_name": config["name"],
        "bootstrap_artifact.package_version": config["version"],
        "bootstrap_artifact.tag": config["tag"],
        "bootstrap_artifact.commit_sha": config["commit_sha"],
        "bootstrap_artifact.repository_url": config["repository_url"],
        "bootstrap_artifact.sdist_filename": config["sdist_filename"],
        "bootstrap_artifact.sdist_url": config["sdist_url"],
        "bootstrap_artifact.sdist_sha256": config["sdist_sha256"],
        "bootstrap_artifact.sdist_size": str(config["sdist_size"]),
        "bootstrap_artifact.wheel_filename": config["wheel_filename"],
        "bootstrap_artifact.wheel_url": config["wheel_url"],
        "bootstrap_artifact.wheel_sha256": config["wheel_sha256"],
        "bootstrap_artifact.wheel_size": str(config["wheel_size"]),
        "bootstrap_artifact.workspace_manifest_path": config["workspace_manifest_path"],
        "bootstrap_artifact.workspace_manifest_url": (
            f"https://raw.githubusercontent.com/astral-sh/uv/{config['commit_sha']}/"
            f"{config['workspace_manifest_path']}"
        ),
        "bootstrap_artifact.workspace_manifest_sha256": config["workspace_manifest_sha256"],
        "bootstrap_artifact.package_manifest_path": config["package_manifest_path"],
        "bootstrap_artifact.package_manifest_url": (
            f"https://raw.githubusercontent.com/astral-sh/uv/{config['commit_sha']}/"
            f"{config['package_manifest_path']}"
        ),
        "bootstrap_artifact.package_manifest_sha256": config["package_manifest_sha256"],
        "bootstrap_artifact.license_files_json": json.dumps(
            [
                {
                    "path": f"uv-{config['version']}.dist-info/licenses/LICENSE-APACHE",
                    "sha256": config["license_apache_sha256"],
                },
                {
                    "path": f"uv-{config['version']}.dist-info/licenses/LICENSE-MIT",
                    "sha256": config["license_mit_sha256"],
                },
            ],
            sort_keys=True,
            separators=(",", ":"),
        ),
        "bootstrap_artifact.embedded_executable_path": config["embedded_executable_path"],
        "bootstrap_artifact.executable_sha256": config["embedded_executable_sha256"],
        "bootstrap_artifact.executable_size": str(config["embedded_executable_size"]),
    }
    if any(metadata_evidence.get(key) != value for key, value in expected.items()):
        return ("bootstrap artifact evidence does not match sealed source: uv",)
    path_value = metadata_evidence.get("bootstrap_artifact.host_executable_path")
    if type(path_value) is not str or not path_value.startswith("/"):
        return ("bootstrap host executable path is invalid: uv",)
    executable = Path(path_value)
    try:
        data = _read_stable_executable(executable, config["embedded_executable_size"])
    except PackageLicenseError as exc:
        return (f"bootstrap host executable cannot be read: uv: {exc}",)
    if (
        len(data) != config["embedded_executable_size"]
        or hashlib.sha256(data).hexdigest() != config["embedded_executable_sha256"]
    ):
        return ("bootstrap host executable identity changed: uv",)
    if not callable(version_runner):
        return ("bootstrap version runner is invalid: uv",)
    try:
        output = version_runner(executable)
    except PackageLicenseError as exc:
        return (f"bootstrap version command failed: uv: {exc}",)
    if output != metadata_evidence.get("bootstrap_artifact.version_output"):
        return ("bootstrap version output changed: uv",)
    return ()


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
