"""Canonical, create-only evidence records for source compatibility work."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def canonical_json_bytes(value: object) -> bytes:
    """Encode finite JSON deterministically with exactly one trailing LF."""
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def open_directory_chain(path: Path, *, create: bool) -> int:
    """Open a directory one no-follow component at a time, optionally creating it."""
    absolute = Path(os.path.abspath(os.fspath(path)))
    descriptor = os.open(os.sep, _DIRECTORY_FLAGS)
    try:
        for part in absolute.parts[1:]:
            if part in {"", ".", ".."}:
                raise ValueError("directory path contains an unsafe component")
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=descriptor)
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _string(value: object, field: str) -> str:
    if type(value) is not str or not value or "\0" in value or "\n" in value:
        raise ValueError(f"{field} must be a non-empty single-line string")
    return value


def _sha(value: object, field: str, *, length: int) -> str:
    result = _string(value, field)
    pattern = _SHA40 if length == 40 else _SHA256
    if pattern.fullmatch(result) is None:
        raise ValueError(f"{field} must be a lowercase SHA-{length * 4}")
    return result


@dataclass(frozen=True)
class CheckoutEvidence:
    schema_version: int
    evidence_type: str
    registry_sha256: str
    repository: str
    url: str
    locked_sha: str
    patterns: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]
    statuses: tuple[int, ...]
    download_bytes: int
    disk_bytes: int
    outcome: str
    blocker: str | None
    content_hashes: tuple[tuple[str, str], ...]
    evidence_sha256: str

    @classmethod
    def create(
        cls,
        *,
        registry_sha256: str,
        repository: str,
        url: str,
        locked_sha: str,
        patterns: Sequence[str],
        commands: Sequence[Sequence[str]],
        statuses: Sequence[int],
        download_bytes: int,
        disk_bytes: int,
        outcome: str,
        blocker: str | None,
        content_hashes: Mapping[str, str],
    ) -> "CheckoutEvidence":
        record = cls(
            schema_version=1,
            evidence_type="CHECKOUT",
            registry_sha256=_sha(registry_sha256, "registry_sha256", length=64),
            repository=_string(repository, "repository"),
            url=_string(url, "url"),
            locked_sha=_sha(locked_sha, "locked_sha", length=40),
            patterns=tuple(_string(item, "pattern") for item in patterns),
            commands=tuple(
                tuple(_string(item, "command argument") for item in command)
                for command in commands
            ),
            statuses=tuple(statuses),
            download_bytes=download_bytes,
            disk_bytes=disk_bytes,
            outcome=_string(outcome, "outcome"),
            blocker=blocker,
            content_hashes=tuple(sorted(content_hashes.items())),
            evidence_sha256="0" * 64,
        )
        record._validate(include_hash=False)
        digest = canonical_sha256(record.to_dict(include_hash=False))
        return cls(**{**record.__dict__, "evidence_sha256": digest})

    def _validate(self, *, include_hash: bool = True) -> None:
        if self.schema_version != 1 or self.evidence_type != "CHECKOUT":
            raise ValueError("checkout evidence schema/type is invalid")
        _sha(self.registry_sha256, "registry_sha256", length=64)
        _sha(self.locked_sha, "locked_sha", length=40)
        if not self.patterns or len(set(self.patterns)) != len(self.patterns):
            raise ValueError("patterns must be nonempty and unique")
        if len(self.commands) != len(self.statuses):
            raise ValueError("commands and statuses must have equal length")
        if any(type(status) is not int or status < 0 for status in self.statuses):
            raise ValueError("statuses must be nonnegative integers")
        if type(self.download_bytes) is not int or self.download_bytes < 0:
            raise ValueError("download_bytes must be nonnegative")
        if type(self.disk_bytes) is not int or self.disk_bytes < 0:
            raise ValueError("disk_bytes must be nonnegative")
        for path, digest in self.content_hashes:
            _string(path, "content path")
            _sha(digest, "content hash", length=64)
        if include_hash:
            _sha(self.evidence_sha256, "evidence_sha256", length=64)
            if self.evidence_sha256 != canonical_sha256(
                self.to_dict(include_hash=False)
            ):
                raise ValueError("checkout evidence hash does not match content")

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "blocker": self.blocker,
            "commands": [list(command) for command in self.commands],
            "content_hashes": [
                {"path": path, "sha256": digest}
                for path, digest in self.content_hashes
            ],
            "disk_bytes": self.disk_bytes,
            "download_bytes": self.download_bytes,
            "evidence_type": self.evidence_type,
            "locked_sha": self.locked_sha,
            "outcome": self.outcome,
            "patterns": list(self.patterns),
            "registry_sha256": self.registry_sha256,
            "repository": self.repository,
            "schema_version": self.schema_version,
            "statuses": list(self.statuses),
            "url": self.url,
        }
        if include_hash:
            result["evidence_sha256"] = self.evidence_sha256
        return result

    def canonical_bytes(self) -> bytes:
        self._validate()
        return canonical_json_bytes(self.to_dict())


def write_evidence_create_only(path: Path, evidence: CheckoutEvidence) -> None:
    """Publish one mode-0600 evidence file without following or replacing paths."""
    if path.name in {"", ".", ".."} or Path(path.name).name != path.name:
        raise ValueError("evidence path must end in one safe basename")
    parent = open_directory_chain(path.parent, create=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(path.name, flags, 0o600, dir_fd=parent)
        data = evidence.canonical_bytes()
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
        os.fsync(descriptor)
        value = os.fstat(descriptor)
        if not stat.S_ISREG(value.st_mode):
            raise ValueError("evidence destination is not a regular file")
        os.fsync(parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent)
