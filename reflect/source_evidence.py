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
    symlink_policy: str = "REJECT_ALL"
    recursive_tree_sha: str | None = None
    contained_symlinks: tuple[tuple[tuple[str, object], ...], ...] = ()

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
        symlink_policy: str = "REJECT_ALL",
        recursive_tree_sha: str | None = None,
        contained_symlinks: Sequence[Mapping[str, object]] = (),
    ) -> "CheckoutEvidence":
        version = 3 if symlink_policy != "REJECT_ALL" else 1
        record = cls(
            schema_version=version,
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
            symlink_policy=symlink_policy,
            recursive_tree_sha=recursive_tree_sha,
            contained_symlinks=tuple(
                tuple(sorted(row.items())) for row in contained_symlinks
            ),
        )
        record._validate(include_hash=False)
        digest = canonical_sha256(record.to_dict(include_hash=False))
        return cls(**{**record.__dict__, "evidence_sha256": digest})

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CheckoutEvidence":
        required = {
            "schema_version", "evidence_type", "registry_sha256", "repository",
            "url", "locked_sha", "patterns", "commands", "statuses",
            "download_bytes", "disk_bytes", "outcome", "blocker",
            "content_hashes", "evidence_sha256",
        }
        if raw.get("schema_version") in {2, 3}:
            required |= {"symlink_policy", "recursive_tree_sha", "contained_symlinks"}
        if set(raw) != required:
            raise ValueError("checkout evidence has missing or extra keys")
        hashes: dict[str, str] = {}
        if not isinstance(raw["content_hashes"], list):
            raise ValueError("checkout content hashes must be a list")
        for item in raw["content_hashes"]:
            if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
                raise ValueError("checkout content hash row is invalid")
            if item["path"] in hashes:
                raise ValueError("checkout content hash path is duplicated")
            hashes[item["path"]] = item["sha256"]
        symlink_rows: list[tuple[tuple[str, object], ...]] = []
        if raw.get("schema_version") in {2, 3}:
            if not isinstance(raw["contained_symlinks"], list):
                raise ValueError("contained symlink evidence must be a list")
            for row in raw["contained_symlinks"]:
                if not isinstance(row, Mapping):
                    raise ValueError("contained symlink evidence row is invalid")
                symlink_rows.append(tuple(sorted(row.items())))
        record = cls(
            schema_version=raw["schema_version"], evidence_type=raw["evidence_type"],
            registry_sha256=raw["registry_sha256"], repository=raw["repository"],
            url=raw["url"], locked_sha=raw["locked_sha"],
            patterns=tuple(raw["patterns"]),
            commands=tuple(tuple(command) for command in raw["commands"]),
            statuses=tuple(raw["statuses"]), download_bytes=raw["download_bytes"],
            disk_bytes=raw["disk_bytes"], outcome=raw["outcome"],
            blocker=raw["blocker"], content_hashes=tuple(sorted(hashes.items())),
            evidence_sha256=raw["evidence_sha256"],
            symlink_policy=raw.get("symlink_policy", "REJECT_ALL"),
            recursive_tree_sha=raw.get("recursive_tree_sha"),
            contained_symlinks=tuple(symlink_rows),
        )
        record._validate()
        return record

    def _validate(self, *, include_hash: bool = True) -> None:
        if self.schema_version not in {1, 2, 3} or self.evidence_type != "CHECKOUT":
            raise ValueError("checkout evidence schema/type is invalid")
        if self.schema_version == 1:
            if self.symlink_policy != "REJECT_ALL" or self.recursive_tree_sha is not None or self.contained_symlinks:
                raise ValueError("checkout evidence v1 cannot carry symlink authority")
        else:
            if self.symlink_policy != "CONTAINED_GIT_SYMLINKS_V1":
                raise ValueError("checkout evidence symlink policy is invalid")
            _sha(self.recursive_tree_sha, "recursive_tree_sha", length=40)
            keys = {
                "path", "link_blob_sha1", "link_bytes", "link_sha256", "target",
                "target_path", "target_blob_sha1", "target_bytes", "target_sha256",
            }
            if self.schema_version == 3:
                keys |= {"link_mode", "target_mode"}
            rows = [dict(row) for row in self.contained_symlinks]
            if any(set(row) != keys for row in rows) or (self.outcome == "PASS" and not rows):
                raise ValueError("contained symlink evidence schema is invalid")
            if len({row["path"] for row in rows}) != len(rows):
                raise ValueError("contained symlink evidence paths must be unique")
            for row in rows:
                for field in ("path", "target", "target_path"):
                    _string(row[field], field)
                if self.schema_version == 3 and (row["link_mode"] != "120000" or row["target_mode"] not in {"100644", "100755"}):
                    raise ValueError("contained symlink evidence Git modes are invalid")
                for field in ("link_blob_sha1", "target_blob_sha1"):
                    _sha(row[field], field, length=40)
                for field in ("link_sha256", "target_sha256"):
                    _sha(row[field], field, length=64)
                for field in ("link_bytes", "target_bytes"):
                    if type(row[field]) is not int or row[field] < 0:
                        raise ValueError(f"{field} must be a nonnegative integer")
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
        if self.outcome not in {"PASS", "FAIL"}:
            raise ValueError("outcome must be PASS or FAIL")
        if self.outcome == "PASS":
            if not self.commands:
                raise ValueError("PASS outcome requires command receipts")
            if self.download_bytes > 512 * 1024 * 1024 or self.disk_bytes > 512 * 1024 * 1024:
                raise ValueError("PASS checkout evidence exceeds the program ceiling")
            if self.blocker is not None or any(self.statuses) or not self.content_hashes:
                raise ValueError("PASS outcome requires zero statuses, content, and no blocker")
        else:
            if type(self.blocker) is not str or not self.blocker or "\n" in self.blocker:
                raise ValueError("FAIL outcome requires a single-line blocker")
            if self.disk_bytes != 0 or self.content_hashes:
                raise ValueError("FAIL outcome cannot claim retained disk content")
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
        if self.schema_version in {2, 3}:
            result["symlink_policy"] = self.symlink_policy
            result["recursive_tree_sha"] = self.recursive_tree_sha
            result["contained_symlinks"] = [dict(row) for row in self.contained_symlinks]
        return result

    def canonical_bytes(self) -> bytes:
        self._validate()
        return canonical_json_bytes(self.to_dict())


def write_evidence_create_only(path: Path, evidence: CheckoutEvidence) -> None:
    """Atomically publish one mode-0600 evidence file without replacement."""
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
    temporary = f".{path.name}.partial-{os.urandom(8).hex()}"
    descriptor = -1
    temporary_identity: tuple[int, int] | None = None
    published = False
    completed = False
    try:
        descriptor = os.open(temporary, flags, 0o600, dir_fd=parent)
        value = os.fstat(descriptor)
        temporary_identity = (value.st_dev, value.st_ino)
        data = evidence.canonical_bytes()
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
        os.fsync(descriptor)
        value = os.fstat(descriptor)
        if not stat.S_ISREG(value.st_mode):
            raise ValueError("evidence destination is not a regular file")
        os.link(
            temporary,
            path.name,
            src_dir_fd=parent,
            dst_dir_fd=parent,
            follow_symlinks=False,
        )
        published = True
        os.fsync(parent)
        completed = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_identity is not None:
            try:
                current = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                current = None
            if current is not None and temporary_identity == (current.st_dev, current.st_ino):
                os.unlink(temporary, dir_fd=parent)
        if published and not completed and temporary_identity is not None:
            try:
                final = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                final = None
            if final is not None and temporary_identity == (final.st_dev, final.st_ino):
                os.unlink(path.name, dir_fd=parent)
        os.close(parent)


def ensure_evidence_target_available(path: Path) -> None:
    """Fail before checkout when an immutable evidence identity already exists."""
    parent = open_directory_chain(path.parent, create=True)
    try:
        try:
            os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise FileExistsError(os.fspath(path))
    finally:
        os.close(parent)
