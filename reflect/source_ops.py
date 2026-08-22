"""Bounded, read-only source compatibility operations."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import tomllib
import xml.etree.ElementTree as ET

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
    operation_id: str
    operation: SourceOperation
    license_status: str
    license_spdx: str | None
    platform: str
    python_requirement: str
    compiler_or_runtime: str
    timeout_seconds: int
    download_ceiling_bytes: int
    disk_ceiling_bytes: int
    file_ceiling_bytes: int
    file_count_ceiling: int
    depth_ceiling: int
    no_copy: bool
    no_models: bool


_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_yaml_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_yaml_mapping)


def _unique_json(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _safe_relative(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("source operation path escapes checkout")


def _selected_files(root: Path, selected: str, operation: SourceOperation, file_count_ceiling: int, depth_ceiling: int) -> tuple[Path, ...]:
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
            found = []
            for current, directories, filenames in os.walk(target, topdown=True, followlinks=False):
                current_path = Path(current)
                depth = len(current_path.relative_to(target).parts)
                if depth >= depth_ceiling:
                    directories[:] = []
                    filenames = []
                else:
                    directories[:] = sorted(
                        name for name in directories
                        if not (current_path / name).is_symlink()
                    )
                for name in sorted(filenames):
                    child = current_path / name
                    if not suffixes or child.suffix.lower() in suffixes or "license" in child.name.lower():
                        found.append(child)
                        if len(found) > file_count_ceiling:
                            raise ValueError("source operation exceeds file-count limit")
            candidates = tuple(found)
        else:
            candidates = (target,)
    if not candidates:
        raise ValueError("source operation selected no files")
    result = []
    if len(candidates) > file_count_ceiling:
        raise ValueError("source operation exceeds file-count limit")
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


def _read_descriptor_relative(root_descriptor: int, relative: str, file_ceiling_bytes: int) -> bytes:
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
            if value.st_size > file_ceiling_bytes:
                raise ValueError("source operation input exceeds file byte limit")
            data = bytearray()
            while len(data) <= file_ceiling_bytes:
                chunk = os.read(file_descriptor, min(64 * 1024, file_ceiling_bytes + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) > file_ceiling_bytes:
                raise ValueError("source operation input exceeds file byte limit")
            return bytes(data)
        finally:
            os.close(file_descriptor)
    finally:
        os.close(descriptor)


def run_source_operation(spec: OperationSpec, checkout_root: Path) -> CompatibilityEvidence:
    if (
        not spec.no_copy or not spec.no_models or spec.download_ceiling_bytes != 0
        or spec.timeout_seconds <= 0 or spec.disk_ceiling_bytes <= 0
        or not 0 < spec.file_ceiling_bytes <= spec.disk_ceiling_bytes
        or spec.file_count_ceiling <= 0 or spec.depth_ceiling <= 0
    ):
        raise ValueError("source operation safety/cap contract is invalid")
    started = time.monotonic()
    if not checkout_root.is_dir() or checkout_root.is_symlink():
        raise ValueError("checkout root must be a non-symlink directory")
    root_descriptor = os.open(checkout_root, _DIRECTORY_FLAGS)
    root_value = os.fstat(root_descriptor)
    try:
        files = _selected_files(checkout_root, spec.selected_path, spec.operation, spec.file_count_ceiling, spec.depth_ceiling)
    except BaseException:
        os.close(root_descriptor)
        raise
    hashes: dict[str, str] = {}
    total = 0
    file_findings = []
    blocker = None
    try:
        for path in files:
            relative = path.relative_to(checkout_root).as_posix()
            if time.monotonic() - started > spec.timeout_seconds:
                raise TimeoutError("source operation exceeded timeout")
            data = _read_descriptor_relative(root_descriptor, relative, spec.file_ceiling_bytes)
            total += len(data)
            if total > spec.disk_ceiling_bytes:
                raise ValueError("source operation input exceeds total byte limit")
            hashes[relative] = hashlib.sha256(data).hexdigest()
            digest = hashes[relative]
            disposition = "PASS"
            try:
                text = data.decode("utf-8", errors="strict")
                if spec.operation is SourceOperation.AST_PARSE:
                    tree = ast.parse(text, filename=relative)
                    finding = {
                        "path": relative, "sha256": digest, "bytes": len(data), "disposition": disposition,
                        "node_count": sum(1 for _ in ast.walk(tree)),
                        "failure_line": None, "failure_column": None,
                    }
                elif spec.operation is SourceOperation.HEADER_LAYOUT:
                    guard = re.search(r"^\s*#ifndef\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.MULTILINE)
                    finding = {
                        "path": relative, "sha256": digest, "bytes": len(data), "disposition": disposition,
                        "include_guard": guard.group(1) if guard else None,
                        "pragma_once": bool(re.search(r"^\s*#pragma\s+once\b", text, re.MULTILINE)),
                        "declaration_count": text.count(";"), "failure_line": None,
                    }
                elif spec.operation is SourceOperation.MANIFEST_LAYOUT:
                    suffix = path.suffix.lower()
                    if suffix == ".toml":
                        parsed_manifest = tomllib.loads(text)
                        top_level = sorted(parsed_manifest)
                        format_name = "TOML"
                    elif suffix == ".xml":
                        root_element = ET.fromstring(text)
                        top_level = [root_element.tag]
                        format_name = "XML"
                    elif suffix == ".json":
                        parsed_manifest = json.loads(text, object_pairs_hook=_unique_json)
                        top_level = sorted(parsed_manifest) if isinstance(parsed_manifest, dict) else [type(parsed_manifest).__name__]
                        format_name = "JSON"
                    elif suffix in {".yaml", ".yml"}:
                        parsed_manifest = yaml.load(text, Loader=_UniqueLoader)
                        top_level = sorted(parsed_manifest) if isinstance(parsed_manifest, dict) else [type(parsed_manifest).__name__]
                        format_name = "YAML"
                    else:
                        raise ValueError("unsupported manifest format")
                    finding = {
                        "path": relative, "sha256": digest, "bytes": len(data), "disposition": disposition,
                        "format": format_name, "top_level": top_level, "failure_line": None,
                    }
                else:
                    candidates = sorted(set(re.findall(r"SPDX-License-Identifier:\s*([A-Za-z0-9.+-]+)", text)))
                    if "license" in path.name.lower() and not candidates:
                        candidates = ["LICENSE_FILE_PRESENT"]
                    finding = {
                        "path": relative, "sha256": digest, "bytes": len(data), "disposition": disposition,
                        "license_candidates": candidates, "failure_line": None,
                    }
            except (UnicodeError, SyntaxError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError, ET.ParseError, yaml.YAMLError) as exc:
                blocker = f"{type(exc).__name__}: bounded static inspection failed"
                position = getattr(exc, "position", None)
                line = getattr(exc, "lineno", None) or (position[0] + 1 if position else 1)
                column = getattr(exc, "offset", None) or (position[1] + 1 if position else 1)
                if spec.operation is SourceOperation.AST_PARSE:
                    finding = {"path": relative, "sha256": digest, "bytes": len(data), "disposition": "FAIL", "node_count": 0, "failure_line": line, "failure_column": column}
                elif spec.operation is SourceOperation.HEADER_LAYOUT:
                    finding = {"path": relative, "sha256": digest, "bytes": len(data), "disposition": "FAIL", "include_guard": None, "pragma_once": False, "declaration_count": 0, "failure_line": line}
                elif spec.operation is SourceOperation.MANIFEST_LAYOUT:
                    finding = {"path": relative, "sha256": digest, "bytes": len(data), "disposition": "FAIL", "format": path.suffix.lstrip(".").upper(), "top_level": [], "failure_line": line}
                else:
                    finding = {"path": relative, "sha256": digest, "bytes": len(data), "disposition": "FAIL", "license_candidates": [], "failure_line": line}
            file_findings.append(finding)
        current_root = os.stat(checkout_root, follow_symlinks=False)
        if (current_root.st_dev, current_root.st_ino) != (root_value.st_dev, root_value.st_ino):
            raise ValueError("checkout root changed during source operation")
    finally:
        os.close(root_descriptor)
    return CompatibilityEvidence.create(
        registry_sha256=spec.registry_sha256,
        repository=spec.repository,
        commit_sha=spec.commit_sha,
        experiment=spec.experiment,
        selected_path=spec.selected_path,
        operation_id=spec.operation_id,
        operation=spec.operation.value,
        platform=spec.platform,
        python_requirement=spec.python_requirement,
        compiler_or_runtime=spec.compiler_or_runtime,
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
        package_lock_artifact_sha256=None,
        patch_artifact_sha256=None,
        findings={
            "files": file_findings,
            "summary": {
                "files_total": len(file_findings),
                "files_pass": sum(item["disposition"] == "PASS" for item in file_findings),
                "files_fail": sum(item["disposition"] == "FAIL" for item in file_findings),
            },
        },
        content_hashes=hashes,
    )


def write_fragment_create_only(path: Path, evidence: CompatibilityEvidence) -> None:
    write_evidence_create_only(path, evidence)  # type: ignore[arg-type]
