#!/usr/bin/env python3
"""Publish and validate immutable P2/P3 phase evidence records."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import subprocess
import sys
from typing import Any
import unicodedata

import yaml

from reflect._p2_report_io import HARDENED_GIT_PREFIX, hardened_environment
from reflect.p2_report import StrictYamlLoader


_SHA = re.compile(r"[0-9a-f]{40}\Z")
_REPORT_BINDING = re.compile(
    rb"^- Implementation/evidence-base Git SHA: `([0-9a-f]{40})`$", re.MULTILINE
)
_RECORD_KEYS = frozenset(
    {
        "phase_id",
        "lifecycle_state",
        "implementation_evidence_git_sha",
        "report_commit_git_sha",
        "report_path",
        "report_git_blob_id",
        "report_sha256",
        "bound_evidence_git_sha",
        "artifact_ledger_sha256",
    }
)
_P2_MEMBERS = (
    "references/repos.yaml",
    "references/repos.lock.yaml",
    "references/p2-live-attempts.yaml",
    "RUN_REPORT.md",
)
_P3_STATIC_MEMBERS = (
    "experiments/00_source_audit/configs/operation-manifest.yaml",
    "experiments/00_source_audit/results/compatibility.csv",
    "references/licenses.md",
    "docs/SOURCE_MAP.md",
    "docs/MATURITY_LEDGER.md",
    "experiments/00_source_audit/RESULTS.md",
    "experiments/00_source_audit/INTERFACE_FINDINGS.md",
)
_P3_SMOKE_PATH = (
    "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json"
)


def _validate_canonical_domain(value: Any, *, label: str = "record") -> None:
    if isinstance(value, bool):
        raise ValueError(f"{label} booleans are not permitted")
    if isinstance(value, float):
        raise ValueError(f"{label} floats are not permitted")
    if isinstance(value, str):
        if unicodedata.normalize("NFKC", value) != value:
            raise ValueError(f"{label} strings must already be NFKC normalized")
        return
    if isinstance(value, int) or value is None:
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_canonical_domain(item, label=f"{label}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{label} mappings require string keys")
            _validate_canonical_domain(key, label=f"{label} key")
            _validate_canonical_domain(item, label=f"{label}.{key}")
        return
    raise ValueError(f"{label} contains a non-JSON value")


def canonical_record_bytes(value: Any) -> bytes:
    """Return the closed-record canonical JSON representation."""

    _validate_canonical_domain(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _git(root: Path, *arguments: str) -> bytes:
    environment = hardened_environment()
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    completed = subprocess.run(
        [
            HARDENED_GIT_PREFIX[0],
            "--no-replace-objects",
            *HARDENED_GIT_PREFIX[1:],
            *arguments,
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"Git command failed ({' '.join(arguments)}): {stderr}")
    return completed.stdout


def _git_text(root: Path, *arguments: str) -> str:
    return _git(root, *arguments).decode("utf-8", "strict").strip()


def _require_sha(value: str, label: str) -> str:
    if _SHA.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase 40-character Git SHA")
    return value


def _resolve_commit(root: Path, value: str, label: str) -> str:
    _require_sha(value, label)
    resolved = _git_text(root, "rev-parse", "--verify", f"{value}^{{commit}}")
    if resolved != value:
        raise ValueError(f"{label} must name the exact commit, not an abbreviation")
    return resolved


def _parents(root: Path, commit: str) -> tuple[str, ...]:
    fields = _git_text(root, "rev-list", "--parents", "-n", "1", commit).split()
    if not fields or fields[0] != commit:
        raise RuntimeError("Git returned an inconsistent commit ancestry record")
    return tuple(fields[1:])


def _changed_paths(root: Path, commit: str) -> tuple[str, ...]:
    raw = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", commit)
    return tuple(item.decode("utf-8", "strict") for item in raw.split(b"\0") if item)


def _strict_yaml(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = yaml.load(content.decode("utf-8", "strict"), Loader=StrictYamlLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 YAML: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _git_blob(root: Path, commit: str, path: str) -> tuple[str, bytes]:
    listing = _git(root, "ls-tree", "-z", commit, "--", path)
    records = [record for record in listing.split(b"\0") if record]
    if len(records) != 1 or b"\t" not in records[0]:
        raise ValueError(f"{path} must resolve to exactly one regular Git blob")
    metadata, listed_path = records[0].split(b"\t", 1)
    fields = metadata.split()
    if (
        listed_path.decode("utf-8", "strict") != path
        or len(fields) != 3
        or fields[0] not in {b"100644", b"100755"}
        or fields[1] != b"blob"
    ):
        raise ValueError(f"{path} must be a regular Git blob")
    blob_id = _git_text(root, "rev-parse", "--verify", f"{commit}:{path}")
    if fields[2].decode("ascii") != blob_id:
        raise RuntimeError(f"{path} Git tree/blob identity mismatch")
    content = _git(root, "cat-file", "blob", blob_id)
    return blob_id, content


def _report_binding(report_bytes: bytes) -> str:
    matches = _REPORT_BINDING.findall(report_bytes)
    if len(matches) != 1:
        raise ValueError("RUN_REPORT.md must contain exactly one closed evidence SHA binding")
    return matches[0].decode("ascii")


def _members_for_phase(root: Path, phase: str, implementation_sha: str) -> tuple[str, ...]:
    if phase == "p2":
        return _P2_MEMBERS
    if phase != "p3":
        raise ValueError("phase must be p2 or p3")
    _, operation_bytes = _git_blob(
        root,
        implementation_sha,
        "experiments/00_source_audit/configs/operation-manifest.yaml",
    )
    operation_manifest = _strict_yaml(operation_bytes, "P3 operation manifest")
    smoke = operation_manifest.get("mujoco_smoke_output")
    if not isinstance(smoke, dict) or set(smoke) != {"operation_id", "relative_path"}:
        raise ValueError("P3 operation manifest has invalid mujoco_smoke_output schema")
    if smoke.get("operation_id") != "MUJOCO_PACKAGE_SMOKE":
        raise ValueError("P3 smoke operation_id must be MUJOCO_PACKAGE_SMOKE")
    if smoke.get("relative_path") != _P3_SMOKE_PATH:
        raise ValueError("P3 smoke relative_path must be the fixed normalized path")
    operations = operation_manifest.get("operations")
    if not isinstance(operations, list):
        raise ValueError("P3 operations must be a strict sequence")
    normalized_operations: list[dict[str, str]] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ValueError(f"P3 operations[{index}] must be a mapping")
        required = {"operation_id", "runtime_subject", "relative_path"}
        if not required.issubset(operation):
            raise ValueError(f"P3 operations[{index}] lacks its closed smoke identity")
        values = {key: operation[key] for key in required}
        if any(not isinstance(value, str) for value in values.values()):
            raise ValueError(f"P3 operations[{index}] identity fields must be strings")
        normalized_operations.append(values)
    matches = [
        operation
        for operation in normalized_operations
        if operation["operation_id"] == "MUJOCO_PACKAGE_SMOKE"
    ]
    if len(matches) != 1:
        raise ValueError("P3 requires exactly one MUJOCO_PACKAGE_SMOKE operation")
    match = matches[0]
    if match["runtime_subject"] != "package":
        raise ValueError("P3 smoke operation runtime_subject must be package")
    if match["relative_path"] != _P3_SMOKE_PATH:
        raise ValueError("P3 smoke operation output identity does not match the selector")
    if sum(
        operation["relative_path"] == _P3_SMOKE_PATH
        for operation in normalized_operations
    ) != 1:
        raise ValueError("P3 smoke output collision in operations")
    return (*_P3_STATIC_MEMBERS, _P3_SMOKE_PATH, "RUN_REPORT.md")


def _derive_record(
    root: Path, phase: str, implementation_sha: str, report_sha: str
) -> dict[str, str]:
    implementation_sha = _resolve_commit(root, implementation_sha, "implementation SHA")
    report_sha = _resolve_commit(root, report_sha, "report commit SHA")
    parents = _parents(root, report_sha)
    if parents != (implementation_sha,):
        raise ValueError("report commit must have the implementation SHA as its only parent")
    if _changed_paths(root, report_sha) != ("RUN_REPORT.md",):
        raise ValueError("report commit must change exactly RUN_REPORT.md")
    report_blob_id, report_bytes = _git_blob(root, report_sha, "RUN_REPORT.md")
    bound_sha = _report_binding(report_bytes)
    if bound_sha != implementation_sha:
        raise ValueError("report bound evidence SHA does not match implementation SHA")

    members: list[dict[str, str]] = []
    for path in sorted(
        _members_for_phase(root, phase, implementation_sha),
        key=lambda value: value.encode("utf-8"),
    ):
        source_sha = report_sha if path == "RUN_REPORT.md" else implementation_sha
        blob_id, content = _git_blob(root, source_sha, path)
        members.append(
            {
                "path": path,
                "source_commit_git_sha": source_sha,
                "git_blob_id": blob_id,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    ledger = {
        "schema_version": 1,
        "phase_id": phase,
        "implementation_evidence_git_sha": implementation_sha,
        "report_commit_git_sha": report_sha,
        "members": members,
    }
    return {
        "phase_id": phase,
        "lifecycle_state": "complete",
        "implementation_evidence_git_sha": implementation_sha,
        "report_commit_git_sha": report_sha,
        "report_path": "RUN_REPORT.md",
        "report_git_blob_id": report_blob_id,
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "bound_evidence_git_sha": bound_sha,
        "artifact_ledger_sha256": hashlib.sha256(
            canonical_record_bytes(ledger)
        ).hexdigest(),
    }


def _validate_prior_p2_record(root: Path, manifest: dict[str, Any]) -> None:
    phase_records = manifest.get("phase_records")
    stored = phase_records.get("p2") if isinstance(phase_records, dict) else None
    if not isinstance(stored, dict) or set(stored) != _RECORD_KEYS:
        raise ValueError("P3 publication requires a closed P2 phase record")
    reconstructed = _derive_record(
        root,
        "p2",
        str(stored["implementation_evidence_git_sha"]),
        str(stored["report_commit_git_sha"]),
    )
    if canonical_record_bytes(stored) != canonical_record_bytes(reconstructed):
        raise ValueError("P3 publication requires a valid preserved P2 phase record")


def _manifest_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path != PurePosixPath("docs/RUN_MANIFEST.yaml"):
        raise ValueError("run manifest path must be exactly docs/RUN_MANIFEST.yaml")
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("run manifest must be a normalized repository-relative path")
    return path


@dataclass(frozen=True)
class _ManifestSnapshot:
    directory_fd: int
    source_fd: int
    filename: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    content: bytes
    content_sha256: str


def _read_fd(descriptor: int, size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
    content = b"".join(chunks)
    if len(content) != size:
        raise ValueError("run manifest changed during snapshot")
    return content


@contextmanager
def _open_manifest_snapshot(root: Path, path: PurePosixPath):
    parent = root.joinpath(*path.parts[:-1])
    directory_fd = os.open(
        parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    source_fd: int | None = None
    try:
        source_fd = os.open(
            path.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("run manifest must be a no-follow regular file")
        if before.st_size > 8 * 1024 * 1024:
            raise ValueError("run manifest exceeds bounded size")
        content = _read_fd(source_fd, before.st_size)
        after = os.fstat(source_fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("run manifest changed during snapshot")
        yield _ManifestSnapshot(
            directory_fd=directory_fd,
            source_fd=source_fd,
            filename=path.name,
            device=before.st_dev,
            inode=before.st_ino,
            size=before.st_size,
            mtime_ns=before.st_mtime_ns,
            content=content,
            content_sha256=hashlib.sha256(content).hexdigest(),
        )
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("run manifest must be a no-follow regular file") from exc
    finally:
        if source_fd is not None:
            os.close(source_fd)
        os.close(directory_fd)


def _read_worktree_manifest(root: Path, path: PurePosixPath) -> tuple[bytes, dict[str, Any]]:
    with _open_manifest_snapshot(root, path) as snapshot:
        return snapshot.content, _strict_yaml(snapshot.content, "run manifest")


def _recheck_manifest_snapshot(snapshot: _ManifestSnapshot) -> None:
    descriptor_state = os.fstat(snapshot.source_fd)
    try:
        path_state = os.stat(
            snapshot.filename, dir_fd=snapshot.directory_fd, follow_symlinks=False
        )
    except FileNotFoundError as exc:
        raise ValueError("run manifest changed during publication") from exc
    identity = (
        descriptor_state.st_dev,
        descriptor_state.st_ino,
        descriptor_state.st_size,
        descriptor_state.st_mtime_ns,
    )
    expected = (snapshot.device, snapshot.inode, snapshot.size, snapshot.mtime_ns)
    if (
        identity != expected
        or not stat.S_ISREG(path_state.st_mode)
        or (path_state.st_dev, path_state.st_ino) != (snapshot.device, snapshot.inode)
        or hashlib.sha256(_read_fd(snapshot.source_fd, descriptor_state.st_size)).hexdigest()
        != snapshot.content_sha256
    ):
        raise ValueError("run manifest changed during publication")


def _worktree_status(
    root: Path, *, allowed_untracked: frozenset[str] = frozenset()
) -> bytes:
    raw = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    allowed_rows = {b"?? " + path.encode("utf-8") for path in allowed_untracked}
    unexpected = [row for row in raw.split(b"\0") if row and row not in allowed_rows]
    return b"\0".join(unexpected) + (b"\0" if unexpected else b"")


def _atomic_write_manifest(
    root: Path,
    snapshot: _ManifestSnapshot,
    content: bytes,
    manifest_path: PurePosixPath,
) -> None:
    directory_fd = snapshot.directory_fd
    temporary = f".{snapshot.filename}.phase-{secrets.token_hex(8)}"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        written = 0
        while written < len(content):
            count = os.write(descriptor, content[written:])
            if count <= 0:
                raise OSError("short write while publishing run manifest")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        _recheck_manifest_snapshot(snapshot)
        temporary_path = str(manifest_path.parent / temporary)
        if _worktree_status(root, allowed_untracked=frozenset({temporary_path})):
            raise ValueError("publish requires a clean worktree immediately before replacement")
        os.replace(
            temporary,
            snapshot.filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def publish(
    *, root: Path, phase: str, implementation_sha: str, report_sha: str, manifest_path: str
) -> None:
    if _git_text(root, "rev-parse", "HEAD") != report_sha:
        raise ValueError("publish requires HEAD to equal the supplied report commit")
    worktree_status = _worktree_status(root)
    path = _manifest_relative_path(manifest_path)
    with _open_manifest_snapshot(root, path) as snapshot:
        manifest = _strict_yaml(snapshot.content, "run manifest")
        stages = manifest.get("stages")
        if not isinstance(stages, dict) or stages.get(phase) != "complete":
            raise ValueError(f"stages.{phase} must be complete before publication")
        safety = manifest.get("safety")
        if not isinstance(safety, dict) or (
            safety.get("physical_deployment_allowed") is not False
            or safety.get("remote_enabled") is not False
        ):
            raise ValueError("physical and remote authority must remain false")
        if phase == "p3":
            _validate_prior_p2_record(root, manifest)
        record = _derive_record(root, phase, implementation_sha, report_sha)
        phase_records = manifest.get("phase_records")
        if phase_records is None:
            phase_records = {}
            manifest["phase_records"] = phase_records
        if not isinstance(phase_records, dict):
            raise ValueError("phase_records must be a mapping")
        if phase in phase_records:
            current = phase_records[phase]
            if canonical_record_bytes(current) != canonical_record_bytes(record):
                raise ValueError(f"phase_records.{phase} is immutable and differs")
            allowed_reissue_status = f" M {manifest_path}\0".encode("utf-8")
            if worktree_status not in {b"", allowed_reissue_status}:
                raise ValueError("publish reissue permits only the unstaged run manifest")
            _recheck_manifest_snapshot(snapshot)
            return
        if worktree_status:
            raise ValueError("publish requires a clean worktree")
        before_other = {key: value for key, value in phase_records.items() if key != phase}
        phase_records[phase] = record
        if {key: value for key, value in phase_records.items() if key != phase} != before_other:
            raise RuntimeError("publisher changed an unrelated phase record")
        rendered = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True).encode("utf-8")
        reparsed = _strict_yaml(rendered, "rendered run manifest")
        if reparsed != manifest:
            raise RuntimeError("rendered run manifest changed canonical data")
        _atomic_write_manifest(root, snapshot, rendered, path)


def validate(*, root: Path, phase: str, state_index_sha: str, manifest_path: str) -> None:
    state_index_sha = _resolve_commit(root, state_index_sha, "state-index commit SHA")
    parents = _parents(root, state_index_sha)
    if len(parents) != 1:
        raise ValueError("state-index commit must have exactly one parent")
    report_sha = parents[0]
    if _changed_paths(root, state_index_sha) != (manifest_path,):
        raise ValueError("state-index commit must change exactly the run manifest")
    _, indexed_bytes = _git_blob(root, state_index_sha, manifest_path)
    _, parent_bytes = _git_blob(root, report_sha, manifest_path)
    indexed = _strict_yaml(indexed_bytes, "state-index manifest")
    parent = _strict_yaml(parent_bytes, "report-parent manifest")
    indexed_records = indexed.get("phase_records", {})
    parent_records = parent.get("phase_records", {})
    if not isinstance(indexed_records, dict) or not isinstance(parent_records, dict):
        raise ValueError("phase_records must be mappings")
    if phase in parent_records or phase not in indexed_records:
        raise ValueError("state-index commit must create exactly the requested phase record")
    if phase == "p3":
        _validate_prior_p2_record(root, parent)
        if canonical_record_bytes(parent_records["p2"]) != canonical_record_bytes(
            indexed_records.get("p2")
        ):
            raise ValueError("P3 state-index commit changed the P2 phase record")
    stored = indexed_records[phase]
    if not isinstance(stored, dict) or set(stored) != _RECORD_KEYS:
        raise ValueError("stored phase record has an invalid closed schema")
    reconstructed = _derive_record(
        root,
        phase,
        str(stored["implementation_evidence_git_sha"]),
        report_sha,
    )
    if canonical_record_bytes(stored) != canonical_record_bytes(reconstructed):
        raise ValueError("stored phase record does not match reconstructed Git evidence")
    parent_without = dict(parent)
    indexed_without = dict(indexed)
    parent_without_records = dict(parent_records)
    indexed_without_records = dict(indexed_records)
    indexed_without_records.pop(phase)
    if parent_without_records:
        parent_without["phase_records"] = parent_without_records
    else:
        parent_without["phase_records"] = {}
    if indexed_without_records:
        indexed_without["phase_records"] = indexed_without_records
    else:
        indexed_without["phase_records"] = {}
    if parent_without != indexed_without:
        raise ValueError("state-index commit changed unrelated manifest data")
    path = _manifest_relative_path(manifest_path)
    _, current = _read_worktree_manifest(root, path)
    current_record = current.get("phase_records", {}).get(phase)
    if canonical_record_bytes(current_record) != canonical_record_bytes(stored):
        raise ValueError("current run manifest does not preserve the indexed record")
    current_stages = current.get("stages")
    current_safety = current.get("safety")
    if (
        not isinstance(current_stages, dict)
        or current_stages.get(phase) != "complete"
        or not isinstance(current_safety, dict)
        or current_safety.get("physical_deployment_allowed") is not False
        or current_safety.get("remote_enabled") is not False
    ):
        raise ValueError("current run manifest gate regressed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--phase", choices=("p2", "p3"), required=True)
    publish_parser.add_argument("--implementation-evidence-git-sha", required=True)
    publish_parser.add_argument("--report-commit-git-sha", required=True)
    publish_parser.add_argument("--run-manifest", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--phase", choices=("p2", "p3"), required=True)
    validate_parser.add_argument("--state-index-commit", required=True)
    validate_parser.add_argument("--run-manifest", required=True)
    return parser


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    arguments = _parser().parse_args(argv)
    project_root = Path.cwd() if root is None else Path(root)
    if arguments.command == "publish":
        publish(
            root=project_root,
            phase=arguments.phase,
            implementation_sha=arguments.implementation_evidence_git_sha,
            report_sha=arguments.report_commit_git_sha,
            manifest_path=arguments.run_manifest,
        )
    else:
        validate(
            root=project_root,
            phase=arguments.phase,
            state_index_sha=arguments.state_index_commit,
            manifest_path=arguments.run_manifest,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"phase record error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
