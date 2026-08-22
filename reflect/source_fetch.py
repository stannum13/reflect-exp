"""No-clone GitHub metadata resolution and stable public fetch interfaces."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
import base64
import binascii
import fnmatch
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Protocol

from reflect._source_cache import (
    CacheStore,
    CachingTransport,
    MetadataEvidence,
    atomic_write_lock,
    lock_yaml_bytes,
)
from reflect._source_git import GitRunner, Runner, parse_ls_remote
from reflect._source_http import (
    GitHubIdentity,
    HttpResponse,
    SourceFetchError,
    Transport,
    UrllibTransport,
    _json_object,
    _require_sha,
    _timestamp,
)
from reflect.sources import (
    LicenseStatus,
    LockedEntry,
    MetadataStatus,
    PathStatus,
    RegistryEntry,
    SourceLock,
    SourceRegistry,
    validate_lock,
)


_LICENSE_NAMES = (
    "license",
    "license.md",
    "license.txt",
    "copying",
    "copying.md",
    "copying.txt",
    "copyright",
)


class ResolutionTransport(Runner, Transport, Protocol):
    pass


@dataclass(frozen=True)
class _TreeEntry:
    path: str
    kind: str
    sha: str


def _tree_response(
    transport: Transport,
    endpoint: str,
    expected_sha: str,
    *,
    allow_truncated: bool,
) -> tuple[tuple[_TreeEntry, ...], bool]:
    raw = _json_object(transport.get(endpoint), endpoint)
    if raw.get("sha") != expected_sha:
        raise SourceFetchError(f"tree response SHA does not match requested tree: {endpoint}")
    truncated = raw.get("truncated")
    if type(truncated) is not bool:
        raise SourceFetchError(f"tree response has invalid truncated marker: {endpoint}")
    if truncated and not allow_truncated:
        raise SourceFetchError(f"targeted tree response is truncated: {endpoint}")
    items = raw.get("tree")
    if not isinstance(items, list):
        raise SourceFetchError(f"tree response has no tree entries: {endpoint}")
    entries: list[_TreeEntry] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise SourceFetchError(f"tree response contains an invalid entry: {endpoint}")
        path = item.get("path")
        kind = item.get("type")
        sha = item.get("sha")
        if (
            type(path) is not str
            or not path
            or path.startswith("/")
            or "//" in path
            or kind not in {"blob", "tree"}
        ):
            raise SourceFetchError(f"tree response contains an invalid entry: {endpoint}")
        _require_sha(sha, "tree entry")
        if path in seen:
            raise SourceFetchError(f"tree response contains a duplicate path: {endpoint}")
        seen.add(path)
        entries.append(_TreeEntry(path, kind, sha))
    return tuple(entries), truncated


def _root_license(entries: Sequence[_TreeEntry]) -> _TreeEntry | None:
    blobs: dict[str, list[_TreeEntry]] = {}
    for entry in entries:
        if entry.kind == "blob" and "/" not in entry.path:
            blobs.setdefault(entry.path.casefold(), []).append(entry)
    for candidate in _LICENSE_NAMES:
        if candidate in blobs:
            return sorted(blobs[candidate], key=lambda item: item.path)[0]
    return None


def _literal_status(path: str, entries: Sequence[_TreeEntry]) -> PathStatus:
    if any(entry.path == path or entry.path.startswith(f"{path}/") for entry in entries):
        return PathStatus.EXISTS
    return PathStatus.MISSING


def _root_glob_status(pattern: str, entries: Sequence[_TreeEntry]) -> PathStatus:
    matched = any(
        "/" not in entry.path and fnmatch.fnmatchcase(entry.path, pattern)
        for entry in entries
    )
    return PathStatus.EXISTS if matched else PathStatus.MISSING


def _walk_literal(
    identity: GitHubIdentity,
    transport: Transport,
    root_entries: Sequence[_TreeEntry],
    root_endpoint: str,
    requested: str,
    fetched: dict[str, tuple[tuple[_TreeEntry, ...], str]],
) -> tuple[PathStatus, str]:
    parts = PurePosixPath(requested).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise SourceFetchError(
            f"requested path is not a safe repository-relative path: {requested}"
        )
    entries = tuple(root_entries)
    evidence = root_endpoint
    for index, part in enumerate(parts):
        found = next((entry for entry in entries if entry.path == part), None)
        if found is None:
            return PathStatus.MISSING, evidence
        if index == len(parts) - 1:
            return PathStatus.EXISTS, evidence
        if found.kind != "tree":
            return PathStatus.MISSING, evidence
        if found.sha in fetched:
            entries, evidence = fetched[found.sha]
        else:
            evidence = identity.tree_url(found.sha, recursive=False)
            entries, _ = _tree_response(
                transport,
                evidence,
                found.sha,
                allow_truncated=False,
            )
            fetched[found.sha] = (entries, evidence)
    raise SourceFetchError(f"could not resolve requested path: {requested}")


def _classify_license(text: str) -> str | None:
    lowered = " ".join(text.casefold().split())
    if (
        "permission is hereby granted, free of charge" in lowered
        and 'the software is provided "as is"' in lowered
    ):
        return "MIT"
    if "apache license" in lowered and "version 2.0" in lowered:
        return "Apache-2.0"
    if "mozilla public license version 2.0" in lowered:
        return "MPL-2.0"
    if "redistribution and use in source and binary forms" in lowered:
        if "neither the name" in lowered:
            return "BSD-3-Clause"
        return "BSD-2-Clause"
    if "gnu general public license" in lowered:
        if "version 3" in lowered:
            return "GPL-3.0-only"
        if "version 2" in lowered:
            return "GPL-2.0-only"
    return None


def _license_observation(
    identity: GitHubIdentity,
    transport: Transport,
    entry: _TreeEntry | None,
    tree_evidence: str,
) -> tuple[str | None, LicenseStatus, str]:
    if entry is None:
        return None, LicenseStatus.UNAVAILABLE, tree_evidence
    endpoint = identity.blob_url(entry.sha)
    raw = _json_object(transport.get(endpoint), endpoint)
    if (
        raw.get("sha") != entry.sha
        or raw.get("encoding") != "base64"
        or type(raw.get("content")) is not str
    ):
        return None, LicenseStatus.UNKNOWN, endpoint
    try:
        decoded = base64.b64decode(raw["content"], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None, LicenseStatus.UNKNOWN, endpoint
    spdx = _classify_license(decoded)
    if spdx is None:
        return None, LicenseStatus.UNKNOWN, endpoint
    return spdx, LicenseStatus.DISCOVERED, endpoint


def resolve_entry(
    entry: RegistryEntry,
    transport: ResolutionTransport,
    clock: Callable[[], datetime],
) -> LockedEntry:
    """Resolve one registry entry without creating a checkout."""
    if not isinstance(entry, RegistryEntry):
        raise SourceFetchError("entry must be a RegistryEntry")
    identity = GitHubIdentity.from_url(entry.url)
    if not hasattr(transport, "run_ls_remote") or not hasattr(transport, "get"):
        raise SourceFetchError("transport must provide Git and HTTP metadata methods")
    branch, commit_sha = parse_ls_remote(transport.run_ls_remote(entry.url))
    commit_endpoint = identity.commit_url(commit_sha)
    commit = _json_object(transport.get(commit_endpoint), commit_endpoint)
    if commit.get("sha") != commit_sha:
        raise SourceFetchError("GitHub commit SHA does not match git ls-remote HEAD")
    tree = commit.get("tree")
    if not isinstance(tree, dict):
        raise SourceFetchError("GitHub commit response has no tree object")
    tree_sha = _require_sha(tree.get("sha"), "commit tree")
    recursive_endpoint = identity.tree_url(tree_sha, recursive=True)
    recursive_entries, truncated = _tree_response(
        transport,
        recursive_endpoint,
        tree_sha,
        allow_truncated=True,
    )
    metadata_evidence: dict[str, str] = {
        "commit": commit_endpoint,
        "ls_remote": f"git ls-remote --symref {entry.url} HEAD",
        "tree": recursive_endpoint,
    }
    path_statuses: dict[str, PathStatus] = {}
    path_evidence: dict[str, str] = {}
    license_entries = recursive_entries
    license_tree_evidence = recursive_endpoint
    if not truncated:
        for requested in entry.selected_paths:
            if "/" not in requested and any(character in requested for character in "*?["):
                status = _root_glob_status(requested, recursive_entries)
            elif any(character in requested for character in "*?["):
                status = PathStatus.MISSING
            else:
                status = _literal_status(requested, recursive_entries)
            path_statuses[requested] = status
            path_evidence[requested] = recursive_endpoint
    else:
        root_endpoint = identity.tree_url(tree_sha, recursive=False)
        root_entries, _ = _tree_response(
            transport,
            root_endpoint,
            tree_sha,
            allow_truncated=False,
        )
        metadata_evidence["tree_fallback_root"] = root_endpoint
        license_entries = root_entries
        license_tree_evidence = root_endpoint
        fetched: dict[str, tuple[tuple[_TreeEntry, ...], str]] = {}
        for requested in entry.selected_paths:
            if "/" not in requested and any(character in requested for character in "*?["):
                status, evidence = _root_glob_status(requested, root_entries), root_endpoint
            elif any(character in requested for character in "*?["):
                status, evidence = PathStatus.MISSING, root_endpoint
            else:
                status, evidence = _walk_literal(
                    identity,
                    transport,
                    root_entries,
                    root_endpoint,
                    requested,
                    fetched,
                )
            path_statuses[requested] = status
            path_evidence[requested] = evidence
    license_entry = _root_license(license_entries)
    license_spdx, license_status, license_evidence = _license_observation(
        identity,
        transport,
        license_entry,
        license_tree_evidence,
    )
    return LockedEntry(
        name=entry.name,
        url=entry.url,
        default_branch=branch,
        commit_sha=commit_sha,
        retrieved_at=_timestamp(clock),
        metadata_evidence=MappingProxyType(metadata_evidence),
        license_spdx=license_spdx,
        license_status=license_status,
        license_evidence_url=license_evidence,
        # LockedEntry's reviewed constructor normalizes serialized status strings.
        path_statuses=MappingProxyType(
            {path: status.value for path, status in path_statuses.items()}
        ),
        path_evidence_urls=MappingProxyType(path_evidence),
        metadata_status=MetadataStatus.RESOLVED,
    )


def resolve_registry(
    registry: SourceRegistry,
    names: Sequence[str],
    transport: ResolutionTransport,
    clock: Callable[[], datetime],
) -> SourceLock:
    if not isinstance(registry, SourceRegistry):
        raise SourceFetchError("registry must be a SourceRegistry")
    if not names:
        raise SourceFetchError("source selector must not be empty")
    if len(set(names)) != len(names):
        raise SourceFetchError("duplicate source selector")
    requested = set(names)
    known = {entry.name for entry in registry.repositories}
    unknown = requested - known
    if unknown:
        raise SourceFetchError(f"unknown source selector: {sorted(unknown)[0]}")
    selected = [entry for entry in registry.repositories if entry.name in requested]
    locked: list[LockedEntry] = []
    for entry in selected:
        entry_transport = transport
        factory = getattr(transport, "for_repository", None)
        if callable(factory):
            entry_transport = factory(entry.name)
        locked.append(resolve_entry(entry, entry_transport, clock))
    result = SourceLock(
        registry_sha256=registry.registry_sha256,
        generated_at=_timestamp(clock),
        entries=tuple(locked),
    )
    if requested == known:
        errors = validate_lock(registry, result, require_complete=True)
        if errors:
            raise SourceFetchError(f"resolved source lock is invalid: {errors[0]}")
    return result
