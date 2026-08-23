"""Immutable source-registry contracts and offline lock validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any

import yaml


class SourceValidationError(ValueError):
    """Raised when source registry or lock data violates its schema."""


class ReuseMode(str, Enum):
    DIRECT_DEPENDENCY = "DIRECT_DEPENDENCY"
    ADAPTER_DEPENDENCY = "ADAPTER_DEPENDENCY"
    SPARSE_REFERENCE = "SPARSE_REFERENCE"
    REMOTE_ONLY = "REMOTE_ONLY"
    PAPER_AND_CODE_REFERENCE = "PAPER_AND_CODE_REFERENCE"
    DEFERRED = "DEFERRED"


class PathStatus(str, Enum):
    EXISTS = "EXISTS"
    MISSING = "MISSING"


class LicenseStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class MetadataStatus(str, Enum):
    RESOLVED = "RESOLVED"
    BLOCKED_NETWORK = "BLOCKED_NETWORK"
    INVALID = "INVALID"


_GITHUB_URL = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SPDX_TOKEN = re.compile(r"\(|\)|AND|OR|WITH|[A-Za-z0-9][A-Za-z0-9.+-]*")
_ARTIFACT_LICENSE_KEYS = frozenset(
    {
        "artifact_license.authority",
        "artifact_license.package_name",
        "artifact_license.package_version",
        "artifact_license.wheel_filename",
        "artifact_license.wheel_url",
        "artifact_license.wheel_sha256",
        "artifact_license.metadata_path",
        "artifact_license.metadata_sha256",
        "artifact_license.record_path",
        "artifact_license.record_sha256",
        "artifact_license.license_expression",
        "artifact_license.license_files_json",
    }
)
_BOOTSTRAP_ARTIFACT_KEYS = frozenset(
    {
        "bootstrap_artifact.authority",
        "bootstrap_artifact.package_name",
        "bootstrap_artifact.package_version",
        "bootstrap_artifact.tag",
        "bootstrap_artifact.commit_sha",
        "bootstrap_artifact.repository_url",
        "bootstrap_artifact.sdist_filename",
        "bootstrap_artifact.sdist_url",
        "bootstrap_artifact.sdist_sha256",
        "bootstrap_artifact.sdist_size",
        "bootstrap_artifact.wheel_filename",
        "bootstrap_artifact.wheel_url",
        "bootstrap_artifact.wheel_sha256",
        "bootstrap_artifact.wheel_size",
        "bootstrap_artifact.workspace_manifest_path",
        "bootstrap_artifact.workspace_manifest_url",
        "bootstrap_artifact.workspace_manifest_sha256",
        "bootstrap_artifact.package_manifest_path",
        "bootstrap_artifact.package_manifest_url",
        "bootstrap_artifact.package_manifest_sha256",
        "bootstrap_artifact.license_expression",
        "bootstrap_artifact.metadata_sha256",
        "bootstrap_artifact.record_sha256",
        "bootstrap_artifact.license_files_json",
        "bootstrap_artifact.embedded_executable_path",
        "bootstrap_artifact.executable_sha256",
        "bootstrap_artifact.executable_size",
        "bootstrap_artifact.host_executable_path",
        "bootstrap_artifact.version_output",
    }
)


def is_spdx_expression(value: object) -> bool:
    """Validate SPDX expression syntax without classifying license text."""
    if type(value) is not str:
        return False
    tokens: list[str] = []
    position = 0
    for match in _SPDX_TOKEN.finditer(value):
        if value[position : match.start()].strip():
            return False
        tokens.append(match.group())
        position = match.end()
    if value[position:].strip() or not tokens or "NOASSERTION" in tokens:
        return False
    index = 0

    def primary() -> bool:
        nonlocal index
        if index >= len(tokens):
            return False
        token = tokens[index]
        if token == "(":
            index += 1
            if not expression() or index >= len(tokens) or tokens[index] != ")":
                return False
            index += 1
            return True
        if token in {"AND", "OR", "WITH", ")"}:
            return False
        index += 1
        return True

    def with_expression() -> bool:
        nonlocal index
        if not primary():
            return False
        if index < len(tokens) and tokens[index] == "WITH":
            index += 1
            if index >= len(tokens) or tokens[index] in {"AND", "OR", "WITH", "(", ")"}:
                return False
            index += 1
        return True

    def conjunction() -> bool:
        nonlocal index
        if not with_expression():
            return False
        while index < len(tokens) and tokens[index] == "AND":
            index += 1
            if not with_expression():
                return False
        return True

    def expression() -> bool:
        nonlocal index
        if not conjunction():
            return False
        while index < len(tokens) and tokens[index] == "OR":
            index += 1
            if not conjunction():
                return False
        return True

    return expression() and index == len(tokens)


def _string(value: object, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if type(value) is not str or not value.strip():
        raise SourceValidationError(f"{field} must be a non-empty string")
    return value


def _string_tuple(value: object, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise SourceValidationError(f"{field} must be a list of strings")
    result = tuple(_string(item, field) for item in value)
    if not allow_empty and not result:
        raise SourceValidationError(f"{field} must not be empty")
    if len(set(result)) != len(result):
        raise SourceValidationError(f"{field} contains duplicate values")
    return result  # type: ignore[return-value]


def _string_mapping(value: object, field: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise SourceValidationError(f"{field} must be a mapping")
    frozen: dict[str, str] = {}
    for key, item in value.items():
        frozen[_string(key, f"{field} key")] = _string(item, f"{field}[{key!r}]")  # type: ignore[index]
    return MappingProxyType(frozen)


def _status_mapping(value: object, field: str) -> Mapping[str, PathStatus]:
    if not isinstance(value, Mapping):
        raise SourceValidationError(f"{field} must be a mapping")
    frozen: dict[str, PathStatus] = {}
    for key, item in value.items():
        path = _string(key, f"{field} key")
        try:
            frozen[path] = PathStatus(_string(item, f"{field}[{key!r}]") or "")
        except ValueError as exc:
            raise SourceValidationError(f"{field}[{key!r}] has an invalid path status") from exc
    return MappingProxyType(frozen)


def _exact_mapping(
    value: object,
    field: str,
    *,
    required: set[str],
    optional: set[str] = frozenset(),
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceValidationError(f"{field} must be a mapping")
    keys = set(value)
    if not all(type(key) is str for key in keys):
        raise SourceValidationError(f"{field} keys must be strings")
    missing = required - keys
    extra = keys - required - optional
    if missing:
        raise SourceValidationError(f"{field} has missing keys: {sorted(missing)}")
    if extra:
        raise SourceValidationError(f"{field} has extra keys: {sorted(extra)}")
    return value


@dataclass(frozen=True)
class RegistryEntry:
    name: str
    url: str
    mode: ReuseMode
    experiments: tuple[str, ...]
    selected_paths: tuple[str, ...]
    use: str
    caveat: str | None = None
    justification: str | None = None

    def __post_init__(self) -> None:
        name = _string(self.name, "name")
        url = _string(self.url, "url")
        if not _GITHUB_URL.fullmatch(url or ""):
            raise SourceValidationError("url must be https://github.com/{owner}/{repo}")
        if not isinstance(self.mode, ReuseMode):
            try:
                mode = ReuseMode(_string(self.mode, "mode") or "")
            except ValueError as exc:
                raise SourceValidationError("mode is not recognized") from exc
        else:
            mode = self.mode
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "experiments", _string_tuple(self.experiments, "experiments", allow_empty=False))
        object.__setattr__(self, "selected_paths", _string_tuple(self.selected_paths, "selected_paths", allow_empty=True))
        object.__setattr__(self, "use", _string(self.use, "use"))
        object.__setattr__(self, "caveat", _string(self.caveat, "caveat", allow_none=True))
        object.__setattr__(self, "justification", _string(self.justification, "justification", allow_none=True))


@dataclass(frozen=True)
class SourceRegistry:
    verified_at: str
    large_model_downloads_default: bool
    physical_deployment_default: bool
    repositories: tuple[RegistryEntry, ...]
    registry_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "verified_at", _string(self.verified_at, "verified_at"))
        for field in ("large_model_downloads_default", "physical_deployment_default"):
            if type(getattr(self, field)) is not bool:
                raise SourceValidationError(f"{field} must be a boolean")
        if not isinstance(self.repositories, tuple) or not self.repositories:
            raise SourceValidationError("repositories must be a non-empty tuple")
        if not all(isinstance(entry, RegistryEntry) for entry in self.repositories):
            raise SourceValidationError("repositories contains an invalid entry")
        names = tuple(entry.name for entry in self.repositories)
        if len(set(names)) != len(names):
            raise SourceValidationError("repositories contains duplicate names")
        digest = _string(self.registry_sha256, "registry_sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
            raise SourceValidationError("registry_sha256 must be a lowercase SHA-256 string")
        object.__setattr__(self, "registry_sha256", digest)


@dataclass(frozen=True)
class LockedEntry:
    name: str
    url: str
    default_branch: str | None
    commit_sha: str | None
    retrieved_at: str | None
    metadata_evidence: Mapping[str, str]
    license_spdx: str | None
    license_status: LicenseStatus
    license_evidence_url: str | None
    path_statuses: Mapping[str, PathStatus]
    path_evidence_urls: Mapping[str, str]
    metadata_status: MetadataStatus

    def __post_init__(self) -> None:
        name = _string(self.name, "name")
        url = _string(self.url, "url")
        if not _GITHUB_URL.fullmatch(url or ""):
            raise SourceValidationError("url must be https://github.com/{owner}/{repo}")
        default_branch = _string(self.default_branch, "default_branch", allow_none=True)
        commit_sha = _string(self.commit_sha, "commit_sha", allow_none=True)
        if commit_sha is not None and not _SHA40.fullmatch(commit_sha):
            raise SourceValidationError("commit_sha must be a 40-character lowercase SHA")
        retrieved_at = _string(self.retrieved_at, "retrieved_at", allow_none=True)
        try:
            license_status = self.license_status if isinstance(self.license_status, LicenseStatus) else LicenseStatus(_string(self.license_status, "license_status") or "")
        except ValueError as exc:
            raise SourceValidationError("license_status is not recognized") from exc
        try:
            metadata_status = self.metadata_status if isinstance(self.metadata_status, MetadataStatus) else MetadataStatus(_string(self.metadata_status, "metadata_status") or "")
        except ValueError as exc:
            raise SourceValidationError("metadata_status is not recognized") from exc
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "default_branch", default_branch)
        object.__setattr__(self, "commit_sha", commit_sha)
        object.__setattr__(self, "retrieved_at", retrieved_at)
        object.__setattr__(self, "metadata_evidence", _string_mapping(self.metadata_evidence, "metadata_evidence"))
        object.__setattr__(self, "license_spdx", _string(self.license_spdx, "license_spdx", allow_none=True))
        object.__setattr__(self, "license_status", license_status)
        object.__setattr__(self, "license_evidence_url", _string(self.license_evidence_url, "license_evidence_url", allow_none=True))
        object.__setattr__(self, "path_statuses", _status_mapping(self.path_statuses, "path_statuses"))
        object.__setattr__(self, "path_evidence_urls", _string_mapping(self.path_evidence_urls, "path_evidence_urls"))
        object.__setattr__(self, "metadata_status", metadata_status)


@dataclass(frozen=True)
class SourceLock:
    registry_sha256: str
    generated_at: str
    entries: tuple[LockedEntry, ...]

    def __post_init__(self) -> None:
        digest = _string(self.registry_sha256, "registry_sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
            raise SourceValidationError("registry_sha256 must be a lowercase SHA-256 string")
        object.__setattr__(self, "registry_sha256", digest)
        object.__setattr__(self, "generated_at", _string(self.generated_at, "generated_at"))
        if not isinstance(self.entries, tuple):
            raise SourceValidationError("entries must be a tuple")
        if not all(isinstance(entry, LockedEntry) for entry in self.entries):
            raise SourceValidationError("entries contains an invalid entry")
        names = tuple(entry.name for entry in self.entries)
        if len(set(names)) != len(names):
            raise SourceValidationError("entries contains duplicate names")


def _artifact_license_state(entry: LockedEntry) -> tuple[bool, bool]:
    evidence = entry.metadata_evidence
    present = {key for key in evidence if key.startswith("artifact_license.")}
    if not present:
        return False, False
    if present != _ARTIFACT_LICENSE_KEYS:
        return True, False
    if evidence["artifact_license.authority"] != "EXACT_WHEEL_INSTALL_ONLY":
        return True, False
    package = evidence["artifact_license.package_name"]
    version = evidence["artifact_license.package_version"]
    filename = evidence["artifact_license.wheel_filename"]
    url = evidence["artifact_license.wheel_url"]
    if (
        not package
        or package != re.sub(r"[-_.]+", "-", entry.name).lower()
        or not version
        or filename != url.rsplit("/", 1)[-1]
        or not filename.endswith(".whl")
        or not url.startswith("https://files.pythonhosted.org/packages/")
    ):
        return True, False
    for key in (
        "artifact_license.wheel_sha256",
        "artifact_license.metadata_sha256",
        "artifact_license.record_sha256",
    ):
        if _SHA256.fullmatch(evidence[key]) is None:
            return True, False
    dist_info = f"{package.replace('-', '_')}-{version.replace('-', '_')}.dist-info"
    if (
        evidence["artifact_license.metadata_path"] != f"{dist_info}/METADATA"
        or evidence["artifact_license.record_path"] != f"{dist_info}/RECORD"
        or not is_spdx_expression(evidence["artifact_license.license_expression"])
    ):
        return True, False
    try:
        inventory = json.loads(evidence["artifact_license.license_files_json"])
    except json.JSONDecodeError:
        return True, False
    if (
        not isinstance(inventory, list)
        or not inventory
        or json.dumps(inventory, sort_keys=True, separators=(",", ":"))
        != evidence["artifact_license.license_files_json"]
    ):
        return True, False
    paths: list[str] = []
    for item in inventory:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or type(item["path"]) is not str
            or not item["path"].startswith(f"{dist_info}/licenses/")
            or ".." in PurePosixPath(item["path"]).parts
            or type(item["sha256"]) is not str
            or _SHA256.fullmatch(item["sha256"]) is None
        ):
            return True, False
        paths.append(item["path"])
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        return True, False
    if entry.license_status is not LicenseStatus.UNKNOWN or entry.license_spdx is not None:
        return True, False
    return True, True


def has_exact_wheel_install_authority(entry: LockedEntry) -> bool:
    """Return whether a lock entry carries closed exact-wheel install evidence."""
    return isinstance(entry, LockedEntry) and _artifact_license_state(entry)[1]


def _bootstrap_artifact_state(entry: LockedEntry) -> tuple[bool, bool]:
    evidence = entry.metadata_evidence
    present = {key for key in evidence if key.startswith("bootstrap_artifact.")}
    if not present:
        return False, False
    if present != _BOOTSTRAP_ARTIFACT_KEYS:
        return True, False
    if (
        entry.name != "uv"
        or evidence["bootstrap_artifact.authority"] != "EXACT_BOOTSTRAP_BINARY_USE_ONLY"
        or evidence["bootstrap_artifact.package_name"] != "uv"
        or evidence["bootstrap_artifact.package_version"] != evidence["bootstrap_artifact.tag"]
        or evidence["bootstrap_artifact.repository_url"] != "https://github.com/astral-sh/uv"
        or _SHA40.fullmatch(evidence["bootstrap_artifact.commit_sha"]) is None
        or not is_spdx_expression(evidence["bootstrap_artifact.license_expression"])
        or entry.license_status is not LicenseStatus.UNKNOWN
        or entry.license_spdx is not None
    ):
        return True, False
    for key in (
        "bootstrap_artifact.sdist_sha256",
        "bootstrap_artifact.wheel_sha256",
        "bootstrap_artifact.workspace_manifest_sha256",
        "bootstrap_artifact.package_manifest_sha256",
        "bootstrap_artifact.metadata_sha256",
        "bootstrap_artifact.record_sha256",
        "bootstrap_artifact.executable_sha256",
    ):
        if _SHA256.fullmatch(evidence[key]) is None:
            return True, False
    if (
        not evidence["bootstrap_artifact.sdist_url"].startswith("https://files.pythonhosted.org/packages/")
        or evidence["bootstrap_artifact.sdist_url"].rsplit("/", 1)[-1] != evidence["bootstrap_artifact.sdist_filename"]
        or not evidence["bootstrap_artifact.wheel_url"].startswith("https://files.pythonhosted.org/packages/")
        or evidence["bootstrap_artifact.wheel_url"].rsplit("/", 1)[-1] != evidence["bootstrap_artifact.wheel_filename"]
        or not evidence["bootstrap_artifact.host_executable_path"].startswith("/")
        or evidence["bootstrap_artifact.embedded_executable_path"] != f"uv-{evidence['bootstrap_artifact.package_version']}.data/scripts/uv"
        or evidence["bootstrap_artifact.workspace_manifest_path"] != "Cargo.toml"
        or evidence["bootstrap_artifact.package_manifest_path"] != "crates/uv/Cargo.toml"
        or evidence["bootstrap_artifact.workspace_manifest_url"] != f"https://raw.githubusercontent.com/astral-sh/uv/{evidence['bootstrap_artifact.commit_sha']}/Cargo.toml"
        or evidence["bootstrap_artifact.package_manifest_url"] != f"https://raw.githubusercontent.com/astral-sh/uv/{evidence['bootstrap_artifact.commit_sha']}/crates/uv/Cargo.toml"
    ):
        return True, False
    try:
        size = int(evidence["bootstrap_artifact.executable_size"])
        sdist_size = int(evidence["bootstrap_artifact.sdist_size"])
        wheel_size = int(evidence["bootstrap_artifact.wheel_size"])
        inventory = json.loads(evidence["bootstrap_artifact.license_files_json"])
    except (ValueError, json.JSONDecodeError):
        return True, False
    if min(size, sdist_size, wheel_size) <= 0 or not isinstance(inventory, list) or len(inventory) != 2:
        return True, False
    expected_paths = [
        f"uv-{evidence['bootstrap_artifact.package_version']}.dist-info/licenses/LICENSE-APACHE",
        f"uv-{evidence['bootstrap_artifact.package_version']}.dist-info/licenses/LICENSE-MIT",
    ]
    if [item.get("path") for item in inventory if isinstance(item, dict)] != expected_paths:
        return True, False
    if any(
        not isinstance(item, dict)
        or set(item) != {"path", "sha256"}
        or type(item.get("sha256")) is not str
        or _SHA256.fullmatch(item["sha256"]) is None
        for item in inventory
    ):
        return True, False
    canonical = json.dumps(inventory, sort_keys=True, separators=(",", ":"))
    if canonical != evidence["bootstrap_artifact.license_files_json"]:
        return True, False
    output = evidence["bootstrap_artifact.version_output"]
    match = re.fullmatch(r"uv ([0-9]+\.[0-9]+\.[0-9]+) \(([0-9a-f]+) [^)]+\)", output)
    if (
        match is None
        or match.group(1) != evidence["bootstrap_artifact.package_version"]
        or len(match.group(2)) < 9
        or not evidence["bootstrap_artifact.commit_sha"].startswith(match.group(2))
    ):
        return True, False
    return True, True


def has_exact_bootstrap_binary_authority(entry: LockedEntry) -> bool:
    """Return whether an entry carries closed uv binary-use-only evidence."""
    return isinstance(entry, LockedEntry) and _bootstrap_artifact_state(entry)[1]


def _read_yaml(path: Path, label: str) -> Mapping[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SourceValidationError(f"could not read {label}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise SourceValidationError(f"{label} must be a YAML mapping")
    return raw


def registry_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise SourceValidationError(f"could not read registry: {exc}") from exc


def load_registry(path: Path) -> SourceRegistry:
    raw = _exact_mapping(
        _read_yaml(path, "registry"),
        "registry",
        required={"verified_at", "large_model_downloads_default", "physical_deployment_default", "repositories"},
    )
    repositories = raw["repositories"]
    if not isinstance(repositories, list):
        raise SourceValidationError("repositories must be a list")
    entries: list[RegistryEntry] = []
    for index, item in enumerate(repositories):
        entry = _exact_mapping(
            item,
            f"repositories[{index}]",
            required={"name", "url", "mode", "experiments", "selected_paths", "use"},
            optional={"caveat", "justification"},
        )
        entries.append(
            RegistryEntry(
                name=entry["name"],
                url=entry["url"],
                mode=entry["mode"],
                experiments=entry["experiments"],
                selected_paths=entry["selected_paths"],
                use=entry["use"],
                caveat=entry.get("caveat"),
                justification=entry.get("justification"),
            )
        )
    return SourceRegistry(
        verified_at=raw["verified_at"],
        large_model_downloads_default=raw["large_model_downloads_default"],
        physical_deployment_default=raw["physical_deployment_default"],
        repositories=tuple(entries),
        registry_sha256=registry_sha256(path),
    )


_LOCK_ENTRY_KEYS = {
    "name", "url", "default_branch", "commit_sha", "retrieved_at", "metadata_evidence",
    "license_spdx", "license_status", "license_evidence_url", "path_statuses",
    "path_evidence_urls", "metadata_status",
}


def load_lock(path: Path) -> SourceLock:
    raw = _exact_mapping(
        _read_yaml(path, "lock"),
        "lock",
        required={"registry_sha256", "generated_at", "entries"},
    )
    entries = raw["entries"]
    if not isinstance(entries, list):
        raise SourceValidationError("entries must be a list")
    parsed: list[LockedEntry] = []
    for index, item in enumerate(entries):
        entry = _exact_mapping(item, f"entries[{index}]", required=_LOCK_ENTRY_KEYS)
        parsed.append(LockedEntry(**entry))
    return SourceLock(registry_sha256=raw["registry_sha256"], generated_at=raw["generated_at"], entries=tuple(parsed))


def validate_lock(registry: SourceRegistry, lock: SourceLock, *, require_complete: bool) -> list[str]:
    """Return deterministic structural errors without performing any I/O."""
    errors: list[str] = []
    if lock.registry_sha256 != registry.registry_sha256:
        errors.append("registry SHA-256 does not match lock")
    registry_entries = {entry.name: entry for entry in registry.repositories}
    locked_entries = {entry.name: entry for entry in lock.entries}
    for name in sorted(set(registry_entries) - set(locked_entries)):
        errors.append(f"missing lock entry: {name}")
    for name in sorted(set(locked_entries) - set(registry_entries)):
        errors.append(f"extra lock entry: {name}")
    for name in sorted(set(registry_entries) & set(locked_entries)):
        entry = registry_entries[name]
        locked = locked_entries[name]
        if locked.url != entry.url:
            errors.append(f"lock URL does not match registry: {name}")
        requested = set(entry.selected_paths)
        if set(locked.path_statuses) != requested:
            errors.append(f"lock paths do not match registry: {name}")
        if set(locked.path_evidence_urls) != requested:
            errors.append(f"lock path evidence does not match registry: {name}")
        artifact_present, artifact_valid = _artifact_license_state(locked)
        bootstrap_present, bootstrap_valid = _bootstrap_artifact_state(locked)
        if artifact_present and not artifact_valid:
            errors.append(f"artifact license evidence is incomplete: {name}")
        if bootstrap_present and not bootstrap_valid:
            errors.append(f"bootstrap artifact evidence is incomplete: {name}")
        if artifact_present and bootstrap_present:
            errors.append(f"multiple artifact authority namespaces are present: {name}")
        if artifact_valid and entry.mode is not ReuseMode.DIRECT_DEPENDENCY:
            errors.append(
                f"artifact install authority is permitted only for a direct dependency: {name}"
            )
        if bootstrap_valid and entry.mode is not ReuseMode.DIRECT_DEPENDENCY:
            errors.append(
                f"bootstrap binary authority is permitted only for a direct dependency: {name}"
            )
        if require_complete:
            if locked.metadata_status is not MetadataStatus.RESOLVED:
                errors.append(f"metadata is not resolved: {name}")
            if locked.default_branch is None:
                errors.append(f"missing default branch: {name}")
            if locked.commit_sha is None:
                errors.append(f"missing commit SHA: {name}")
            if locked.retrieved_at is None:
                errors.append(f"missing retrieval timestamp: {name}")
            if (
                entry.mode in {ReuseMode.DIRECT_DEPENDENCY, ReuseMode.ADAPTER_DEPENDENCY}
                and locked.license_status is not LicenseStatus.DISCOVERED
                and not (
                    entry.mode is ReuseMode.DIRECT_DEPENDENCY
                    and (artifact_valid or bootstrap_valid)
                )
            ):
                errors.append(f"direct/adapter license is not discovered: {name}")
            if locked.license_status is LicenseStatus.DISCOVERED and locked.license_spdx is None:
                errors.append(f"discovered license has no SPDX observation: {name}")
    return errors
