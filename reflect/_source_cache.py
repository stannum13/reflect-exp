"""Checksummed metadata cache and deterministic atomic source-lock publication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any

import yaml

from reflect._source_git import Runner, parse_ls_remote
from reflect._source_http import (
    HttpResponse,
    SourceFetchError,
    Transport,
    _API_ENDPOINT,
    _MAX_RESPONSE_BYTES,
    _timestamp,
)
from reflect.sources import LockedEntry, SourceLock


_CACHE_COMPONENT = re.compile(r"[A-Za-z0-9_.-]+\Z")


@dataclass(frozen=True)
class MetadataEvidence:
    endpoint: str
    retrieved_at: str
    etag: str | None
    sha256: str
    payload: bytes


def _safe_component(value: str, label: str) -> str:
    if (
        type(value) is not str
        or value in {".", ".."}
        or not _CACHE_COMPONENT.fullmatch(value)
    ):
        raise SourceFetchError(f"cache {label} is not a safe path component")
    return value


def _read_regular(path: Path, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SourceFetchError(f"cache entry is not a readable regular file: {path.name}") from exc
    try:
        value = os.fstat(descriptor)
        if not stat.S_ISREG(value.st_mode) or value.st_size > limit:
            raise SourceFetchError(f"cache entry is not a bounded regular file: {path.name}")
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > limit:
            raise SourceFetchError(f"cache entry exceeds size limit: {path.name}")
        return bytes(data)
    finally:
        os.close(descriptor)


def _atomic_cache_file(path: Path, data: bytes) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        directory,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    temporary = f".{path.name}.{secrets.token_hex(16)}"
    file_descriptor = -1
    try:
        file_descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=descriptor,
        )
        view = memoryview(data)
        while view:
            written = os.write(file_descriptor, view)
            view = view[written:]
        os.fsync(file_descriptor)
        os.close(file_descriptor)
        file_descriptor = -1
        os.replace(temporary, path.name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        os.fsync(descriptor)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        try:
            os.unlink(temporary, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        finally:
            os.close(descriptor)


class CacheStore:
    """Repository-scoped raw payload cache whose metadata authenticates every read."""

    def __init__(self, root: Path, *, max_payload_bytes: int = _MAX_RESPONSE_BYTES) -> None:
        self.root = Path(root)
        self._max_payload_bytes = max_payload_bytes

    def _paths(self, name: str, key: str) -> tuple[Path, Path]:
        safe_name = _safe_component(name, "repository name")
        safe_key = _safe_component(key, "record key")
        directory = self.root / safe_name
        return directory / f"{safe_key}.payload", directory / f"{safe_key}.json"

    def write(
        self,
        name: str,
        key: str,
        *,
        endpoint: str,
        payload: bytes,
        retrieved_at: str,
        etag: str | None = None,
    ) -> None:
        if not isinstance(payload, bytes) or len(payload) > self._max_payload_bytes:
            raise SourceFetchError("cache payload must be bounded bytes")
        if type(endpoint) is not str or not endpoint:
            raise SourceFetchError("cache endpoint must be a non-empty string")
        if type(retrieved_at) is not str or not retrieved_at:
            raise SourceFetchError("cache retrieval timestamp must be a non-empty string")
        if etag is not None and type(etag) is not str:
            raise SourceFetchError("cache ETag must be text or null")
        payload_path, metadata_path = self._paths(name, key)
        digest = hashlib.sha256(payload).hexdigest()
        metadata = json.dumps(
            {
                "endpoint": endpoint,
                "etag": etag,
                "retrieved_at": retrieved_at,
                "sha256": digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        try:
            _atomic_cache_file(payload_path, payload)
            _atomic_cache_file(metadata_path, metadata)
        except OSError as exc:
            raise SourceFetchError(f"could not write metadata cache for {name}") from exc

    def load(self, name: str, key: str, *, endpoint: str) -> MetadataEvidence | None:
        payload_path, metadata_path = self._paths(name, key)
        if not payload_path.exists() or not metadata_path.exists():
            return None
        try:
            metadata_bytes = _read_regular(metadata_path, 64 * 1024)
            payload = _read_regular(payload_path, self._max_payload_bytes)
            metadata = json.loads(metadata_bytes)
        except (SourceFetchError, OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(metadata, dict) or set(metadata) != {
            "endpoint",
            "etag",
            "retrieved_at",
            "sha256",
        }:
            return None
        etag = metadata["etag"]
        if (
            metadata["endpoint"] != endpoint
            or type(metadata["retrieved_at"]) is not str
            or (etag is not None and type(etag) is not str)
            or type(metadata["sha256"]) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", metadata["sha256"])
            or hashlib.sha256(payload).hexdigest() != metadata["sha256"]
        ):
            return None
        return MetadataEvidence(
            endpoint=endpoint,
            retrieved_at=metadata["retrieved_at"],
            etag=etag,
            sha256=metadata["sha256"],
            payload=payload,
        )

    def record_rate_limit(self, reset: str) -> None:
        if type(reset) is not str or not reset.isdecimal():
            return
        marker = json.dumps(
            {"x-ratelimit-reset": reset},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        try:
            _atomic_cache_file(self.root / ".rate-limit.json", marker)
        except OSError as exc:
            raise SourceFetchError("could not write GitHub rate-limit cache marker") from exc

    def active_rate_limit(self, clock: Callable[[], datetime]) -> str | None:
        marker_path = self.root / ".rate-limit.json"
        if not marker_path.exists():
            return None
        try:
            raw = json.loads(_read_regular(marker_path, 4096))
            reset = raw["x-ratelimit-reset"]
            now = clock()
        except (
            KeyError,
            SourceFetchError,
            OSError,
            TypeError,
            UnicodeError,
            json.JSONDecodeError,
        ):
            return None
        if (
            not isinstance(raw, dict)
            or set(raw) != {"x-ratelimit-reset"}
            or type(reset) is not str
            or not reset.isdecimal()
            or not isinstance(now, datetime)
            or now.tzinfo is None
        ):
            return None
        return reset if int(reset) > int(now.timestamp()) else None


def _cache_key(url: str) -> str:
    match = _API_ENDPOINT.fullmatch(url)
    if match is None:
        raise SourceFetchError("cannot cache a non-derived GitHub endpoint")
    object_type = match.group(3)
    sha = match.group(4)
    recursive = match.group(5)
    if object_type == "commits":
        return "commit"
    if object_type == "trees" and recursive:
        return f"tree-recursive-{sha}"
    if object_type == "trees":
        return f"tree-{sha}"
    return f"blob-{sha}"


class CachingTransport:
    """Try each live request once, then use at most one validated cached response."""

    def __init__(
        self,
        runner: Runner,
        http: Transport,
        cache: CacheStore,
        clock: Callable[[], datetime],
        name: str,
    ) -> None:
        self._runner = runner
        self._http = http
        self._cache = cache
        self._clock = clock
        self._name = _safe_component(name, "repository name")

    def for_repository(self, name: str) -> "CachingTransport":
        return CachingTransport(self._runner, self._http, self._cache, self._clock, name)

    def run_ls_remote(self, url: str) -> str:
        command = f"git ls-remote --symref {url} HEAD"
        cached = self._cache.load(self._name, "ls-remote", endpoint=command)
        if self._cache.active_rate_limit(self._clock) is not None and cached is not None:
            try:
                output = cached.payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SourceFetchError("cached git ls-remote output is not UTF-8") from exc
            parse_ls_remote(output)
            return output
        try:
            output = self._runner.run_ls_remote(url)
        except SourceFetchError:
            if cached is None:
                raise
            try:
                return cached.payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SourceFetchError("cached git ls-remote output is not UTF-8") from exc
        parse_ls_remote(output)
        self._cache.write(
            self._name,
            "ls-remote",
            endpoint=command,
            payload=output.encode("utf-8"),
            retrieved_at=_timestamp(self._clock),
        )
        return output

    def get(self, url: str) -> HttpResponse:
        key = _cache_key(url)
        cached = self._cache.load(self._name, key, endpoint=url)
        active_reset = self._cache.active_rate_limit(self._clock)
        if active_reset is not None:
            if cached is None:
                raise SourceFetchError(
                    f"GitHub rate limit remains active for {url}; reset {active_reset}"
                )
            return HttpResponse(
                url=url,
                status=200,
                headers={"x-cache": "rate-limit-resume"},
                body=cached.payload,
            )
        try:
            response = self._http.get(url)
        except SourceFetchError:
            if cached is None:
                raise
            return HttpResponse(url=url, status=200, headers={"x-cache": "fallback"}, body=cached.payload)
        if response.url != url:
            raise SourceFetchError(f"GitHub response URL does not match requested endpoint: {url}")
        if response.headers.get("x-ratelimit-remaining") == "0":
            self._cache.record_rate_limit(
                response.headers.get("x-ratelimit-reset", "")
            )
        if response.status >= 400:
            if cached is not None:
                return HttpResponse(url=url, status=200, headers={"x-cache": "fallback"}, body=cached.payload)
            return response
        self._cache.write(
            self._name,
            key,
            endpoint=url,
            payload=response.body,
            retrieved_at=_timestamp(self._clock),
            etag=response.headers.get("etag"),
        )
        return response


def _entry_dict(entry: LockedEntry) -> dict[str, Any]:
    return {
        "name": entry.name,
        "url": entry.url,
        "default_branch": entry.default_branch,
        "commit_sha": entry.commit_sha,
        "retrieved_at": entry.retrieved_at,
        "metadata_evidence": dict(sorted(entry.metadata_evidence.items())),
        "license_spdx": entry.license_spdx,
        "license_status": entry.license_status.value,
        "license_evidence_url": entry.license_evidence_url,
        "path_statuses": {
            key: value.value for key, value in sorted(entry.path_statuses.items())
        },
        "path_evidence_urls": dict(sorted(entry.path_evidence_urls.items())),
        "metadata_status": entry.metadata_status.value,
    }


def lock_yaml_bytes(lock: SourceLock) -> bytes:
    if not isinstance(lock, SourceLock):
        raise SourceFetchError("lock must be a SourceLock")
    document = {
        "registry_sha256": lock.registry_sha256,
        "generated_at": lock.generated_at,
        "entries": [_entry_dict(entry) for entry in lock.entries],
    }
    try:
        encoded = yaml.safe_dump(
            document,
            sort_keys=False,
            allow_unicode=False,
            default_flow_style=False,
        ).encode("utf-8")
        decoded = yaml.safe_load(encoded)
        round_trip = SourceLock(
            registry_sha256=decoded["registry_sha256"],
            generated_at=decoded["generated_at"],
            entries=tuple(LockedEntry(**item) for item in decoded["entries"]),
        )
    except (KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise SourceFetchError("could not serialize a valid source lock") from exc
    if round_trip != lock:
        raise SourceFetchError("serialized source lock does not round-trip exactly")
    return encoded


def atomic_write_lock(path: Path, lock: SourceLock) -> None:
    """Publish a validated lock through one descriptor-bound sibling replacement."""
    target = Path(path)
    if target.name in {"", ".", ".."}:
        raise SourceFetchError("source lock path must name a file")
    data = lock_yaml_bytes(lock)
    try:
        parent = target.parent.resolve(strict=True)
    except OSError as exc:
        raise SourceFetchError(f"could not publish source lock: {target}") from exc
    directory_descriptor = -1
    temporary = f".{target.name}.{secrets.token_hex(16)}"
    file_descriptor = -1
    try:
        directory_descriptor = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        file_descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_descriptor,
        )
        view = memoryview(data)
        while view:
            written = os.write(file_descriptor, view)
            view = view[written:]
        os.fsync(file_descriptor)
        os.close(file_descriptor)
        file_descriptor = -1
        os.replace(
            temporary,
            target.name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        os.fsync(directory_descriptor)
    except (OSError, ValueError) as exc:
        raise SourceFetchError(f"could not publish source lock: {target}") from exc
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if directory_descriptor >= 0:
            try:
                os.unlink(temporary, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass
            finally:
                os.close(directory_descriptor)
