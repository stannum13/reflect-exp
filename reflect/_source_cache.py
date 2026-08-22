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
    _LICENSE_ENDPOINT,
    _MAX_RESPONSE_BYTES,
    _timestamp,
)
from reflect.sources import LockedEntry, SourceLock


_CACHE_COMPONENT = re.compile(r"[A-Za-z0-9_.-]+\Z")
_CANONICAL_UTC_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z"
)


@dataclass(frozen=True)
class MetadataEvidence:
    endpoint: str
    retrieved_at: str
    etag: str | None
    sha256: str
    payload: bytes
    status: int


def _safe_component(value: str, label: str) -> str:
    if (
        type(value) is not str
        or value in {".", ".."}
        or not _CACHE_COMPONENT.fullmatch(value)
    ):
        raise SourceFetchError(f"cache {label} is not a safe path component")
    return value


def _canonical_retrieved_at(value: object) -> bool:
    if type(value) is not str or not _CANONICAL_UTC_TIMESTAMP.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return _timestamp(lambda: parsed) == value


_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _open_directory_chain(path: Path, *, create: bool) -> int:
    """Open a path one no-follow component at a time and retain the final anchor."""
    absolute = Path(os.path.abspath(os.fspath(path)))
    descriptor = os.open(absolute.anchor, _DIRECTORY_FLAGS)
    try:
        for component in absolute.parts[1:]:
            if create:
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError:
        os.close(descriptor)
        raise


def _open_child_directory(parent: int, name: str, *, create: bool) -> int:
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    return os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)


def _read_regular_at(directory: int, name: str, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise SourceFetchError(f"cache entry is not a readable regular file: {name}") from exc
    try:
        value = os.fstat(descriptor)
        if not stat.S_ISREG(value.st_mode) or value.st_size > limit:
            raise SourceFetchError(f"cache entry is not a bounded regular file: {name}")
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > limit:
            raise SourceFetchError(f"cache entry exceeds size limit: {name}")
        return bytes(data)
    finally:
        os.close(descriptor)


def _verify_child_directory(parent: int, name: str, child: int) -> None:
    try:
        bound = os.stat(name, dir_fd=parent, follow_symlinks=False)
        opened = os.fstat(child)
    except OSError as exc:
        raise SourceFetchError("cache directory changed during operation") from exc
    if (
        not stat.S_ISDIR(bound.st_mode)
        or (bound.st_dev, bound.st_ino) != (opened.st_dev, opened.st_ino)
    ):
        raise SourceFetchError("cache directory changed during operation")


def _atomic_cache_file_at(
    descriptor: int,
    name: str,
    data: bytes,
    *,
    validate_directory: Callable[[], None] | None = None,
) -> None:
    temporary = f".{name}.{secrets.token_hex(16)}"
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
        if validate_directory is not None:
            validate_directory()
        os.replace(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        os.fsync(descriptor)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        try:
            os.unlink(temporary, dir_fd=descriptor)
        except FileNotFoundError:
            pass


class CacheStore:
    """Repository-scoped raw payload cache whose metadata authenticates every read."""

    def __init__(self, root: Path, *, max_payload_bytes: int = _MAX_RESPONSE_BYTES) -> None:
        self.root = Path(root)
        self._max_payload_bytes = max_payload_bytes

    def _names(self, name: str, key: str) -> tuple[str, str, str]:
        safe_name = _safe_component(name, "repository name")
        safe_key = _safe_component(key, "record key")
        return safe_name, f"{safe_key}.payload", f"{safe_key}.json"

    def _root_descriptor(self, *, create: bool) -> int:
        try:
            return _open_directory_chain(self.root, create=create)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise SourceFetchError("cache directory ancestry is not safe") from exc

    def _repository_descriptor(self, name: str, *, create: bool) -> tuple[int, int]:
        root = self._root_descriptor(create=create)
        try:
            repository = _open_child_directory(root, name, create=create)
        except FileNotFoundError:
            os.close(root)
            raise
        except OSError as exc:
            os.close(root)
            raise SourceFetchError("cache directory ancestry is not safe") from exc
        return root, repository

    def write(
        self,
        name: str,
        key: str,
        *,
        endpoint: str,
        payload: bytes,
        retrieved_at: str,
        etag: str | None = None,
        status: int = 200,
    ) -> None:
        if not isinstance(payload, bytes) or len(payload) > self._max_payload_bytes:
            raise SourceFetchError("cache payload must be bounded bytes")
        if type(endpoint) is not str or not endpoint:
            raise SourceFetchError("cache endpoint must be a non-empty string")
        if type(retrieved_at) is not str or not retrieved_at:
            raise SourceFetchError("cache retrieval timestamp must be a non-empty string")
        if etag is not None and type(etag) is not str:
            raise SourceFetchError("cache ETag must be text or null")
        if type(status) is not int or status not in {200, 404}:
            raise SourceFetchError("cache response status must be 200 or 404")
        if status == 404 and _LICENSE_ENDPOINT.fullmatch(endpoint) is None:
            raise SourceFetchError("only an absent license response may be cached")
        safe_name, payload_name, metadata_name = self._names(name, key)
        digest = hashlib.sha256(payload).hexdigest()
        metadata = json.dumps(
            {
                "endpoint": endpoint,
                "etag": etag,
                "retrieved_at": retrieved_at,
                "sha256": digest,
                "status": status,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        root = repository = -1
        try:
            root, repository = self._repository_descriptor(safe_name, create=True)

            def validate() -> None:
                _verify_child_directory(root, safe_name, repository)

            _atomic_cache_file_at(
                repository, payload_name, payload, validate_directory=validate
            )
            _atomic_cache_file_at(
                repository, metadata_name, metadata, validate_directory=validate
            )
        except OSError as exc:
            raise SourceFetchError(f"could not write metadata cache for {name}") from exc
        finally:
            if repository >= 0:
                os.close(repository)
            if root >= 0:
                os.close(root)

    def load(self, name: str, key: str, *, endpoint: str) -> MetadataEvidence | None:
        safe_name, payload_name, metadata_name = self._names(name, key)
        root = repository = -1
        try:
            root, repository = self._repository_descriptor(safe_name, create=False)
            _verify_child_directory(root, safe_name, repository)
            metadata_bytes = _read_regular_at(repository, metadata_name, 64 * 1024)
            payload = _read_regular_at(repository, payload_name, self._max_payload_bytes)
            metadata = json.loads(metadata_bytes)
        except FileNotFoundError:
            return None
        except (UnicodeError, json.JSONDecodeError):
            return None
        finally:
            if repository >= 0:
                os.close(repository)
            if root >= 0:
                os.close(root)
        legacy_keys = {"endpoint", "etag", "retrieved_at", "sha256"}
        if not isinstance(metadata, dict):
            return None
        metadata_keys = frozenset(metadata)
        if metadata_keys not in {
            frozenset(legacy_keys),
            frozenset((*legacy_keys, "status")),
        }:
            return None
        etag = metadata["etag"]
        status = metadata.get("status", 200)
        if (
            metadata["endpoint"] != endpoint
            or not _canonical_retrieved_at(metadata["retrieved_at"])
            or (etag is not None and type(etag) is not str)
            or type(metadata["sha256"]) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", metadata["sha256"])
            or hashlib.sha256(payload).hexdigest() != metadata["sha256"]
            or type(status) is not int
            or status not in {200, 404}
            or (status == 404 and _LICENSE_ENDPOINT.fullmatch(endpoint) is None)
        ):
            return None
        return MetadataEvidence(
            endpoint=endpoint,
            retrieved_at=metadata["retrieved_at"],
            etag=etag,
            sha256=metadata["sha256"],
            payload=payload,
            status=status,
        )

    def record_rate_limit(self, reset: str) -> None:
        if type(reset) is not str or not reset.isdecimal():
            return
        marker = json.dumps(
            {"x-ratelimit-reset": reset},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        descriptor = -1
        try:
            descriptor = self._root_descriptor(create=True)
            _atomic_cache_file_at(descriptor, ".rate-limit.json", marker)
        except OSError as exc:
            raise SourceFetchError("could not write GitHub rate-limit cache marker") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def active_rate_limit(self, clock: Callable[[], datetime]) -> str | None:
        descriptor = -1
        try:
            descriptor = self._root_descriptor(create=False)
            raw = json.loads(_read_regular_at(descriptor, ".rate-limit.json", 4096))
            reset = raw["x-ratelimit-reset"]
            now = clock()
        except FileNotFoundError:
            return None
        except (
            KeyError,
            TypeError,
            UnicodeError,
            json.JSONDecodeError,
        ):
            return None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
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
    license_match = _LICENSE_ENDPOINT.fullmatch(url)
    if license_match is not None:
        return f"license-{license_match.group(3)}"
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
    raise SourceFetchError("cannot cache an unsupported GitHub endpoint")


class CachingTransport:
    """Try each live request once, then use at most one validated cached response."""

    def __init__(
        self,
        runner: Runner,
        http: Transport,
        cache: CacheStore,
        clock: Callable[[], datetime],
        name: str,
        _rate_limit_state: list[bool] | None = None,
    ) -> None:
        self._runner = runner
        self._http = http
        self._cache = cache
        self._clock = clock
        self._name = _safe_component(name, "repository name")
        self._rate_limit_state = _rate_limit_state or [False]

    def for_repository(self, name: str) -> "CachingTransport":
        return CachingTransport(
            self._runner,
            self._http,
            self._cache,
            self._clock,
            name,
            self._rate_limit_state,
        )

    def run_ls_remote(self, url: str) -> str:
        if self._rate_limit_state[0]:
            raise SourceFetchError("GitHub rate limit was reached during this invocation")
        command = f"git ls-remote --symref {url} HEAD"
        cached = self._cache.load(self._name, "ls-remote", endpoint=command)
        active_reset = self._cache.active_rate_limit(self._clock)
        if active_reset is not None and cached is None:
            raise SourceFetchError(
                f"GitHub rate limit remains active for {url}; reset {active_reset}"
            )
        if active_reset is not None:
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
        if self._rate_limit_state[0]:
            raise SourceFetchError("GitHub rate limit was reached during this invocation")
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
                status=cached.status,
                headers={"x-cache": "rate-limit-resume"},
                body=cached.payload,
            )
        try:
            response = self._http.get(url)
        except SourceFetchError:
            if cached is None:
                raise
            return HttpResponse(
                url=url,
                status=cached.status,
                headers={"x-cache": "fallback"},
                body=cached.payload,
            )
        if response.url != url:
            raise SourceFetchError(f"GitHub response URL does not match requested endpoint: {url}")
        remaining = response.headers.get("x-ratelimit-remaining")
        reset = response.headers.get("x-ratelimit-reset", "")
        valid_reset = reset if reset.isdecimal() else None
        if remaining == "0" or response.status == 429:
            if valid_reset is not None:
                self._cache.record_rate_limit(valid_reset)
            self._rate_limit_state[0] = True
            shown_reset = valid_reset or "unknown"
            raise SourceFetchError(
                f"GitHub rate limit exhausted for {url}; reset {shown_reset}"
            )
        if response.status >= 400:
            if cached is not None:
                return HttpResponse(
                    url=url,
                    status=cached.status,
                    headers={"x-cache": "fallback"},
                    body=cached.payload,
                )
            if response.status == 404 and _LICENSE_ENDPOINT.fullmatch(url) is not None:
                self._cache.write(
                    self._name,
                    key,
                    endpoint=url,
                    payload=response.body,
                    retrieved_at=_timestamp(self._clock),
                    etag=response.headers.get("etag"),
                    status=404,
                )
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
