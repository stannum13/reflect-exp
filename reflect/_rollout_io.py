"""Descriptor-bound filesystem primitives for rollout artifacts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from typing import BinaryIO


class ArtifactIOError(ValueError):
    """Raised when a rollout filesystem boundary changes or is unsafe."""


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int


@dataclass(frozen=True)
class ArtifactSnapshot:
    path: Path
    payloads: dict[str, bytes]
    optional_files: tuple[str, ...]


_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FLAGS = (
    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
)
_CREATE_FLAGS = (
    os.O_RDWR
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def identity_from_stat(value: os.stat_result) -> FileIdentity:
    return FileIdentity(device=value.st_dev, inode=value.st_ino)


def descriptor_identity(descriptor: int) -> FileIdentity:
    return identity_from_stat(os.fstat(descriptor))


def open_directory(path: Path) -> tuple[int, FileIdentity]:
    try:
        descriptor = os.open(path, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise ArtifactIOError(f"path is not a descriptor-safe directory: {path}") from exc
    identity = descriptor_identity(descriptor)
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ArtifactIOError(f"path is not a directory: {path}")
    return descriptor, identity


def open_directory_at(parent_descriptor: int, name: str) -> tuple[int, FileIdentity]:
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor)
    except OSError as exc:
        raise ArtifactIOError(f"directory entry is not descriptor-safe: {name}") from exc
    identity = descriptor_identity(descriptor)
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ArtifactIOError(f"directory entry is not a directory: {name}")
    return descriptor, identity


def path_matches_directory(path: Path, expected: FileIdentity) -> bool:
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(current.st_mode) and identity_from_stat(current) == expected


def entry_identity(parent_descriptor: int, name: str) -> FileIdentity | None:
    try:
        value = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return identity_from_stat(value)


def _read_regular_file(directory_descriptor: int, name: str) -> bytes:
    try:
        descriptor = os.open(name, _READ_FLAGS, dir_fd=directory_descriptor)
    except OSError as exc:
        raise ArtifactIOError(
            f"rollout entries must be regular files opened without following links: {name}"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ArtifactIOError(
                f"rollout entries must be regular files, not links/directories: {name}"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def read_artifact_snapshot(
    path: Path,
    required_files: frozenset[str],
    optional_files: frozenset[str],
) -> ArtifactSnapshot:
    absolute = Path(os.path.abspath(os.fspath(path)))
    directory_descriptor, _ = open_directory(absolute)
    try:
        names = set(os.listdir(directory_descriptor))
        missing = required_files - names
        if missing:
            raise ArtifactIOError(f"missing required rollout files: {sorted(missing)}")
        unexpected = names - required_files - optional_files
        if unexpected:
            raise ArtifactIOError(f"unexpected file in rollout: {sorted(unexpected)}")
        payloads = {
            name: _read_regular_file(directory_descriptor, name)
            for name in sorted(names)
        }
        return ArtifactSnapshot(
            path=absolute,
            payloads=payloads,
            optional_files=tuple(sorted(names & optional_files)),
        )
    finally:
        os.close(directory_descriptor)


def write_file(
    directory_descriptor: int,
    name: str,
    writer: Callable[[BinaryIO], None],
) -> str:
    if Path(name).name != name:
        raise ArtifactIOError(f"artifact filename must be one basename: {name}")
    descriptor = os.open(
        name,
        _CREATE_FLAGS,
        0o600,
        dir_fd=directory_descriptor,
    )
    try:
        with os.fdopen(descriptor, "w+b", closefd=False) as handle:
            writer(handle)
            handle.flush()
            os.fsync(descriptor)
            handle.seek(0)
            digest = hashlib.sha256()
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            return digest.hexdigest()
    finally:
        os.close(descriptor)


def write_bytes(directory_descriptor: int, name: str, data: bytes) -> str:
    return write_file(directory_descriptor, name, lambda handle: handle.write(data))


def fsync_directory(directory_descriptor: int) -> None:
    os.fsync(directory_descriptor)


def _clear_directory(directory_descriptor: int) -> None:
    for name in os.listdir(directory_descriptor):
        try:
            value = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(value.st_mode):
            try:
                child_descriptor = os.open(
                    name, _DIRECTORY_FLAGS, dir_fd=directory_descriptor
                )
            except OSError:
                continue
            child_identity = descriptor_identity(child_descriptor)
            try:
                _clear_directory(child_descriptor)
            finally:
                os.close(child_descriptor)
            if entry_identity(directory_descriptor, name) == child_identity:
                try:
                    os.rmdir(name, dir_fd=directory_descriptor)
                except OSError:
                    pass
        else:
            try:
                os.unlink(name, dir_fd=directory_descriptor)
            except OSError:
                pass


def cleanup_exact_directory(
    parent_descriptor: int,
    directory_descriptor: int,
    expected: FileIdentity,
    preferred_name: str,
) -> None:
    if descriptor_identity(directory_descriptor) != expected:
        return
    _clear_directory(directory_descriptor)
    candidates = [preferred_name]
    candidates.extend(
        name for name in os.listdir(parent_descriptor) if name != preferred_name
    )
    for name in candidates:
        if entry_identity(parent_descriptor, name) != expected:
            continue
        try:
            candidate_descriptor, candidate_identity = open_directory_at(
                parent_descriptor, name
            )
        except ArtifactIOError:
            continue
        os.close(candidate_descriptor)
        if candidate_identity != expected:
            continue
        try:
            os.rmdir(name, dir_fd=parent_descriptor)
        except OSError:
            pass
        return
