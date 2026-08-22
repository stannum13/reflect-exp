"""Bounded, read-only source compatibility operations."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path, PurePosixPath
import platform
import stat

import yaml

from reflect.source_compat import CompatibilityEvidence
from reflect.source_evidence import write_evidence_create_only


class SourceOperation(str, Enum):
    AST_PARSE = "AST_PARSE"
    HEADER_LAYOUT = "HEADER_LAYOUT"
    MANIFEST_LAYOUT = "MANIFEST_LAYOUT"
    ASSET_LICENSE_INVENTORY = "ASSET_LICENSE_INVENTORY"


@dataclass(frozen=True)
class OperationSpec:
    registry_sha256: str
    repository: str
    commit_sha: str
    experiment: str
    selected_path: str
    operation: SourceOperation
    license_status: str
    license_spdx: str | None


_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_BYTES = 16 * 1024 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _safe_relative(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("source operation path escapes checkout")


def _selected_files(root: Path, selected: str, operation: SourceOperation) -> tuple[Path, ...]:
    _safe_relative(selected)
    if any(character in selected for character in "*?["):
        candidates = tuple(sorted(root.glob(selected)))
    else:
        target = root / selected
        if target.is_dir() and not target.is_symlink():
            suffixes = {
                SourceOperation.AST_PARSE: {".py"},
                SourceOperation.HEADER_LAYOUT: {".h", ".hh", ".hpp", ".hxx"},
                SourceOperation.MANIFEST_LAYOUT: {".json", ".yaml", ".yml", ".toml", ".xml"},
                SourceOperation.ASSET_LICENSE_INVENTORY: set(),
            }[operation]
            candidates = tuple(
                sorted(
                    child for child in target.rglob("*")
                    if child.is_file() and (not suffixes or child.suffix.lower() in suffixes or "license" in child.name.lower())
                )
            )
        else:
            candidates = (target,)
    if not candidates:
        raise ValueError("source operation selected no files")
    result = []
    for candidate in candidates:
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("source operation path escaped checkout") from exc
        value = candidate.lstat()
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
            raise ValueError("source operation requires a regular non-symlink file")
        result.append(candidate)
    return tuple(result)


def _read_descriptor_relative(root_descriptor: int, relative: str) -> bytes:
    parts = PurePosixPath(relative).parts
    descriptor = os.dup(root_descriptor)
    try:
        for part in parts[:-1]:
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=descriptor,
        )
        try:
            value = os.fstat(file_descriptor)
            if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
                raise ValueError("source operation requires an exact regular file")
            if value.st_size > _MAX_FILE_BYTES:
                raise ValueError("source operation input exceeds file byte limit")
            data = bytearray()
            while len(data) <= _MAX_FILE_BYTES:
                chunk = os.read(file_descriptor, min(64 * 1024, _MAX_FILE_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) > _MAX_FILE_BYTES:
                raise ValueError("source operation input exceeds file byte limit")
            return bytes(data)
        finally:
            os.close(file_descriptor)
    finally:
        os.close(descriptor)


def run_source_operation(spec: OperationSpec, checkout_root: Path) -> CompatibilityEvidence:
    if not checkout_root.is_dir() or checkout_root.is_symlink():
        raise ValueError("checkout root must be a non-symlink directory")
    root_descriptor = os.open(checkout_root, _DIRECTORY_FLAGS)
    root_value = os.fstat(root_descriptor)
    try:
        files = _selected_files(checkout_root, spec.selected_path, spec.operation)
    except BaseException:
        os.close(root_descriptor)
        raise
    hashes: dict[str, str] = {}
    total = 0
    parsed = 0
    blocker = None
    try:
        for path in files:
            relative = path.relative_to(checkout_root).as_posix()
            data = _read_descriptor_relative(root_descriptor, relative)
            total += len(data)
            if total > _MAX_TOTAL_BYTES:
                raise ValueError("source operation input exceeds total byte limit")
            hashes[relative] = hashlib.sha256(data).hexdigest()
            try:
                text = data.decode("utf-8", errors="strict")
                if spec.operation is SourceOperation.AST_PARSE:
                    ast.parse(text, filename=relative)
                elif spec.operation is SourceOperation.MANIFEST_LAYOUT and path.suffix.lower() in {".yaml", ".yml", ".json"}:
                    yaml.safe_load(text)
                parsed += 1
            except (UnicodeError, SyntaxError, yaml.YAMLError) as exc:
                blocker = f"{type(exc).__name__}: bounded static inspection failed"
                break
        current_root = os.stat(checkout_root, follow_symlinks=False)
        if (current_root.st_dev, current_root.st_ino) != (root_value.st_dev, root_value.st_ino):
            raise ValueError("checkout root changed during source operation")
    finally:
        os.close(root_descriptor)
    system = platform.system().lower()
    machine = platform.machine().lower()
    return CompatibilityEvidence.create(
        registry_sha256=spec.registry_sha256,
        repository=spec.repository,
        commit_sha=spec.commit_sha,
        experiment=spec.experiment,
        selected_path=spec.selected_path,
        operation=spec.operation.value,
        platform=f"{system}-{machine}",
        python_requirement=">=3.11,<3.12",
        compiler_or_runtime=platform.python_version(),
        command=(spec.operation.value.lower(), spec.selected_path),
        exit_status=0 if blocker is None else 1,
        disk_bytes=total,
        download_bytes=0,
        license_status=spec.license_status,
        license_spdx=spec.license_spdx,
        blocker=blocker,
        notes="bounded read-only static source inspection",
        runtime_subject="source_checkout",
        package_name=None,
        package_version=None,
        package_artifact_sha256=None,
        patch_artifact_sha256=None,
        findings={"parsed_files": parsed},
        content_hashes=hashes,
    )


def write_fragment_create_only(path: Path, evidence: CompatibilityEvidence) -> None:
    write_evidence_create_only(path, evidence)  # type: ignore[arg-type]
