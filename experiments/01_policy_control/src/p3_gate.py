"""Authenticate the closed historical P2/P3 evidence before Experiment 01."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Any, Mapping, Sequence

import yaml

from reflect._p2_report_io import (
    HARDENED_GIT_PREFIX,
    _open_directory_path_no_follow,
    _read_file_at,
    hardened_environment,
)
from reflect.p2_report import StrictYamlLoader
from reflect.source_compat import CompatibilityEvidence


class P3GateError(ValueError):
    """The immutable P3 prerequisite chain is incomplete or inconsistent."""


MAX_ANCESTRY_COMMITS = 4096
RUN_MANIFEST_PATH = "docs/RUN_MANIFEST.yaml"
REQUIRED_ARTIFACTS: Mapping[str, str] = {
    "p2_lock": "references/repos.lock.yaml",
    "operation_manifest": "experiments/00_source_audit/configs/operation-manifest.yaml",
    "compatibility_csv": "experiments/00_source_audit/results/compatibility.csv",
    "licenses": "references/licenses.md",
    "source_map": "docs/SOURCE_MAP.md",
    "maturity_ledger": "docs/MATURITY_LEDGER.md",
    "p3_results": "experiments/00_source_audit/RESULTS.md",
    "interface_findings": "experiments/00_source_audit/INTERFACE_FINDINGS.md",
    "mujoco_smoke": "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json",
}
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_GATE_KEYS = frozenset(
    {
        "schema_version",
        "run_manifest_capture_git_sha",
        "run_manifest_capture_git_blob_id",
        "p2_state_index_git_sha",
        "p2_state_index_run_manifest_git_blob_id",
        "p3_state_index_git_sha",
        "p3_state_index_run_manifest_git_blob_id",
        "p2_phase_record_sha256",
        "p3_phase_record_sha256",
        "p2_implementation_evidence_git_sha",
        "p2_report_commit_git_sha",
        "p2_report_git_blob_id",
        "p2_report_sha256",
        "p2_bound_evidence_git_sha",
        "p3_implementation_evidence_git_sha",
        "p3_report_commit_git_sha",
        "p3_report_git_blob_id",
        "p3_report_sha256",
        "p3_bound_evidence_git_sha",
        "files",
        "mujoco",
        "physical_deployment_allowed",
        "remote_execution_allowed",
        "runtime_network_allowed",
    }
)


@dataclass(frozen=True)
class EvidenceFile:
    path: PurePosixPath
    git_blob_id: str
    sha256: str

    def __post_init__(self) -> None:
        if (
            self.path.is_absolute()
            or not self.path.parts
            or any(part in {"", ".", ".."} for part in self.path.parts)
            or _OID.fullmatch(self.git_blob_id) is None
            or _SHA256.fullmatch(self.sha256) is None
        ):
            raise P3GateError("invalid historical evidence artifact identity")


@dataclass(frozen=True)
class P3GateEvidence:
    schema_version: int
    run_manifest_capture_git_sha: str
    run_manifest_capture_git_blob_id: str
    p2_state_index_git_sha: str
    p2_state_index_run_manifest_git_blob_id: str
    p3_state_index_git_sha: str
    p3_state_index_run_manifest_git_blob_id: str
    p2_phase_record_sha256: str
    p3_phase_record_sha256: str
    p2_implementation_evidence_git_sha: str
    p2_report_commit_git_sha: str
    p2_report_git_blob_id: str
    p2_report_sha256: str
    p2_bound_evidence_git_sha: str
    p3_implementation_evidence_git_sha: str
    p3_report_commit_git_sha: str
    p3_report_git_blob_id: str
    p3_report_sha256: str
    p3_bound_evidence_git_sha: str
    files: Mapping[str, EvidenceFile]
    mujoco_package: str
    mujoco_version: str
    mujoco_artifact_sha256: str
    physical_deployment_allowed: bool
    remote_execution_allowed: bool
    runtime_network_allowed: bool

    def __post_init__(self) -> None:
        if self.schema_version != 2:
            raise P3GateError("invalid P3 gate schema version")
        sha_fields = (
            self.run_manifest_capture_git_sha,
            self.p2_state_index_git_sha,
            self.p3_state_index_git_sha,
            self.p2_implementation_evidence_git_sha,
            self.p2_report_commit_git_sha,
            self.p2_bound_evidence_git_sha,
            self.p3_implementation_evidence_git_sha,
            self.p3_report_commit_git_sha,
            self.p3_bound_evidence_git_sha,
        )
        oid_fields = (
            self.run_manifest_capture_git_blob_id,
            self.p2_state_index_run_manifest_git_blob_id,
            self.p3_state_index_run_manifest_git_blob_id,
            self.p2_report_git_blob_id,
            self.p3_report_git_blob_id,
        )
        digest_fields = (
            self.p2_phase_record_sha256,
            self.p3_phase_record_sha256,
            self.p2_report_sha256,
            self.p3_report_sha256,
            self.mujoco_artifact_sha256,
        )
        if any(_SHA40.fullmatch(value) is None for value in sha_fields):
            raise P3GateError("P3 gate contains an invalid Git commit identity")
        if any(_OID.fullmatch(value) is None for value in oid_fields):
            raise P3GateError("P3 gate contains an invalid Git blob identity")
        if any(_SHA256.fullmatch(value) is None for value in digest_fields):
            raise P3GateError("P3 gate contains an invalid evidence hash")
        if set(self.files) != set(REQUIRED_ARTIFACTS):
            raise P3GateError("P3 gate historical artifact inventory is incomplete")
        for key, expected in REQUIRED_ARTIFACTS.items():
            if self.files[key].path != PurePosixPath(expected):
                raise P3GateError(f"{key} historical artifact path mismatch")
        if (
            self.p2_bound_evidence_git_sha != self.p2_implementation_evidence_git_sha
            or self.p3_bound_evidence_git_sha
            != self.p3_implementation_evidence_git_sha
        ):
            raise P3GateError("phase record bound evidence identity mismatch")
        if (
            self.mujoco_package != "mujoco"
            or self.mujoco_version != "3.12.0"
            or self.physical_deployment_allowed is not False
            or self.remote_execution_allowed is not False
            or self.runtime_network_allowed is not False
        ):
            raise P3GateError("P3 gate safety or network authority is not closed")


def _git(root: Path, *arguments: str) -> bytes:
    allowed = (
        arguments == ("rev-parse", "HEAD")
        or (
            len(arguments) == 5
            and arguments[:2] == ("ls-tree", "-z")
            and _SHA40.fullmatch(arguments[2]) is not None
            and arguments[3] == "--"
            and arguments[4] in {*REQUIRED_ARTIFACTS.values(), RUN_MANIFEST_PATH}
        )
        or (
            len(arguments) == 3
            and arguments[:2] == ("rev-parse", "--verify")
            and ":" in arguments[2]
            and _SHA40.fullmatch(arguments[2].split(":", 1)[0]) is not None
            and arguments[2].split(":", 1)[1]
            in {*REQUIRED_ARTIFACTS.values(), RUN_MANIFEST_PATH}
        )
        or (
            len(arguments) == 3
            and arguments[:2] == ("cat-file", "blob")
            and _OID.fullmatch(arguments[2]) is not None
        )
        or (
            len(arguments) == 5
            and arguments[:4] == ("rev-list", "--parents", "-n", "1")
            and _SHA40.fullmatch(arguments[4]) is not None
        )
    )
    if not allowed:
        raise P3GateError(f"P3 gate rejected non-allowlisted Git read: {arguments!r}")
    environment = hardened_environment(
        {"GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1"}
    )
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
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise P3GateError(f"hardened local Git read failed: {detail}")
    return completed.stdout


def _git_text(root: Path, *arguments: str) -> str:
    return _git(root, *arguments).decode("utf-8", "strict").strip()


def _strict_yaml(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = yaml.load(content.decode("utf-8", "strict"), Loader=StrictYamlLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise P3GateError(f"{label} is not strict duplicate-free UTF-8 YAML") from exc
    if not isinstance(value, dict):
        raise P3GateError(f"{label} must be a mapping")
    return value


def _git_blob(root: Path, commit: str, path: str) -> tuple[str, bytes]:
    listing = _git(root, "ls-tree", "-z", commit, "--", path)
    rows = [row for row in listing.split(b"\0") if row]
    if len(rows) != 1 or b"\t" not in rows[0]:
        raise P3GateError(f"historical artifact is absent or ambiguous: {path}")
    metadata, encoded_path = rows[0].split(b"\t", 1)
    fields = metadata.split()
    if (
        encoded_path.decode("utf-8", "strict") != path
        or len(fields) != 3
        or fields[0] not in {b"100644", b"100755"}
        or fields[1] != b"blob"
    ):
        raise P3GateError(f"historical artifact is not a regular Git blob: {path}")
    blob_id = _git_text(root, "rev-parse", "--verify", f"{commit}:{path}")
    if fields[2].decode("ascii") != blob_id:
        raise P3GateError(f"historical artifact tree/blob identity mismatch: {path}")
    return blob_id, _git(root, "cat-file", "blob", blob_id)


def _parents(root: Path, commit: str) -> tuple[str, ...]:
    fields = _git_text(root, "rev-list", "--parents", "-n", "1", commit).split()
    if not fields or fields[0] != commit:
        raise P3GateError("Git returned an inconsistent ancestry row")
    return tuple(fields[1:])


def _require_capture_on_current_first_parent(
    root: Path, current_head: str, capture_sha: str
) -> None:
    """Require capture to be a bounded, merge-free first-parent ancestor of HEAD."""
    current = current_head
    if current == capture_sha:
        return
    for _ in range(MAX_ANCESTRY_COMMITS):
        parents = _parents(root, current)
        if len(parents) > 1:
            raise P3GateError(
                "current HEAD ancestry contains a merge before the sealed capture"
            )
        if not parents:
            raise P3GateError(
                "sealed capture is unrelated to the current HEAD first-parent root"
            )
        current = parents[0]
        if current == capture_sha:
            return
    raise P3GateError("bounded current HEAD ancestry did not reach the sealed capture")


def _derive_state_indexes(
    root: Path, capture_sha: str, reports: Mapping[str, str]
) -> dict[str, str]:
    found: dict[str, str] = {}
    current = capture_sha
    for _ in range(MAX_ANCESTRY_COMMITS):
        parents = _parents(root, current)
        if len(parents) > 1:
            raise P3GateError("capture ancestry contains a merge before both state-index commits")
        if not parents:
            break
        parent = parents[0]
        for phase, report_sha in reports.items():
            if parent == report_sha:
                if phase in found:
                    raise P3GateError(f"multiple {phase} state-index commits in capture ancestry")
                found[phase] = current
        current = parent
        if set(found) == set(reports):
            return found
    raise P3GateError("bounded capture ancestry did not contain both state-index commits")


def _phase_records(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    records = manifest.get("phase_records")
    if not isinstance(records, dict):
        raise P3GateError("capture phase_records must be a mapping")
    p2 = records.get("p2")
    p3 = records.get("p3")
    if not isinstance(p2, dict) or not isinstance(p3, dict):
        raise P3GateError("capture requires closed P2 and P3 phase records")
    return p2, p3


def _capture_gate(root: Path, capture_sha: str) -> P3GateEvidence:
    publisher = __import__("scripts.publish_phase_record", fromlist=["*"])
    capture_sha = publisher._resolve_commit(root, capture_sha, "capture SHA")
    capture_blob, capture_bytes = _git_blob(root, capture_sha, RUN_MANIFEST_PATH)
    capture = _strict_yaml(capture_bytes, "historical run-manifest capture")
    p2_record, p3_record = _phase_records(capture)
    try:
        reconstructed = {
            "p2": publisher._derive_record(
                root,
                "p2",
                str(p2_record["implementation_evidence_git_sha"]),
                str(p2_record["report_commit_git_sha"]),
            ),
            "p3": publisher._derive_record(
                root,
                "p3",
                str(p3_record["implementation_evidence_git_sha"]),
                str(p3_record["report_commit_git_sha"]),
            ),
        }
    except (KeyError, RuntimeError, ValueError) as exc:
        raise P3GateError(f"historical phase record reconstruction failed: {exc}") from exc
    for phase, stored in (("p2", p2_record), ("p3", p3_record)):
        if publisher.canonical_record_bytes(stored) != publisher.canonical_record_bytes(
            reconstructed[phase]
        ):
            raise P3GateError(f"historical {phase} phase record differs from Git evidence")
    indexes = _derive_state_indexes(
        root,
        capture_sha,
        {
            "p2": reconstructed["p2"]["report_commit_git_sha"],
            "p3": reconstructed["p3"]["report_commit_git_sha"],
        },
    )
    index_blobs: dict[str, str] = {}
    for phase in ("p2", "p3"):
        try:
            publisher.validate(
                root=root,
                phase=phase,
                state_index_sha=indexes[phase],
                manifest_path=RUN_MANIFEST_PATH,
            )
        except (RuntimeError, ValueError) as exc:
            raise P3GateError(f"{phase} state-index validation failed: {exc}") from exc
        index_blobs[phase], _ = _git_blob(root, indexes[phase], RUN_MANIFEST_PATH)

    stages = capture.get("stages")
    safety = capture.get("safety")
    if (
        not isinstance(stages, dict)
        or stages.get("p2") != "complete"
        or stages.get("p3") != "complete"
        or not isinstance(safety, dict)
        or safety.get("physical_deployment_allowed") is not False
        or safety.get("remote_enabled") is not False
    ):
        raise P3GateError("historical capture safety/stage gate is invalid")

    p2_implementation = reconstructed["p2"]["implementation_evidence_git_sha"]
    p3_implementation = reconstructed["p3"]["implementation_evidence_git_sha"]
    artifacts: dict[str, EvidenceFile] = {}
    for key, path in REQUIRED_ARTIFACTS.items():
        source = p2_implementation if key == "p2_lock" else p3_implementation
        blob_id, content = _git_blob(root, source, path)
        artifacts[key] = EvidenceFile(
            PurePosixPath(path), blob_id, hashlib.sha256(content).hexdigest()
        )
    smoke_bytes = _git_blob(
        root, p3_implementation, REQUIRED_ARTIFACTS["mujoco_smoke"]
    )[1]
    try:
        smoke_raw = json.loads(smoke_bytes.decode("utf-8", "strict"))
        smoke = CompatibilityEvidence.from_dict(smoke_raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise P3GateError(f"historical MuJoCo smoke evidence is invalid: {exc}") from exc
    if (
        smoke.runtime_subject != "package"
        or smoke.package_name != "mujoco"
        or smoke.package_version != "3.12.0"
        or smoke.package_artifact_sha256 is None
    ):
        raise P3GateError("historical MuJoCo package identity is invalid")

    return P3GateEvidence(
        schema_version=2,
        run_manifest_capture_git_sha=capture_sha,
        run_manifest_capture_git_blob_id=capture_blob,
        p2_state_index_git_sha=indexes["p2"],
        p2_state_index_run_manifest_git_blob_id=index_blobs["p2"],
        p3_state_index_git_sha=indexes["p3"],
        p3_state_index_run_manifest_git_blob_id=index_blobs["p3"],
        p2_phase_record_sha256=hashlib.sha256(
            publisher.canonical_record_bytes(reconstructed["p2"])
        ).hexdigest(),
        p3_phase_record_sha256=hashlib.sha256(
            publisher.canonical_record_bytes(reconstructed["p3"])
        ).hexdigest(),
        p2_implementation_evidence_git_sha=p2_implementation,
        p2_report_commit_git_sha=reconstructed["p2"]["report_commit_git_sha"],
        p2_report_git_blob_id=reconstructed["p2"]["report_git_blob_id"],
        p2_report_sha256=reconstructed["p2"]["report_sha256"],
        p2_bound_evidence_git_sha=reconstructed["p2"]["bound_evidence_git_sha"],
        p3_implementation_evidence_git_sha=p3_implementation,
        p3_report_commit_git_sha=reconstructed["p3"]["report_commit_git_sha"],
        p3_report_git_blob_id=reconstructed["p3"]["report_git_blob_id"],
        p3_report_sha256=reconstructed["p3"]["report_sha256"],
        p3_bound_evidence_git_sha=reconstructed["p3"]["bound_evidence_git_sha"],
        files=artifacts,
        mujoco_package=smoke.package_name,
        mujoco_version=smoke.package_version,
        mujoco_artifact_sha256=smoke.package_artifact_sha256,
        physical_deployment_allowed=False,
        remote_execution_allowed=False,
        runtime_network_allowed=False,
    )


def _wire(evidence: P3GateEvidence) -> dict[str, Any]:
    value = {
        key: getattr(evidence, key)
        for key in _GATE_KEYS
        if key not in {"files", "mujoco"}
    }
    value["files"] = {
        key: {
            "path": item.path.as_posix(),
            "git_blob_id": item.git_blob_id,
            "sha256": item.sha256,
        }
        for key, item in sorted(evidence.files.items())
    }
    value["mujoco"] = {
        "package": evidence.mujoco_package,
        "version": evidence.mujoco_version,
        "artifact_sha256": evidence.mujoco_artifact_sha256,
    }
    return value


def _gate_bytes(evidence: P3GateEvidence) -> bytes:
    return yaml.safe_dump(_wire(evidence), sort_keys=True, allow_unicode=False).encode(
        "utf-8"
    )


def _read_no_follow(path: Path) -> bytes:
    directory_fd = _open_directory_path_no_follow(path.parent)
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_SH)
        return _read_file_at(directory_fd, path.name)
    except ValueError as exc:
        raise P3GateError(f"P3 gate must be a bounded no-follow regular file: {exc}") from exc
    finally:
        fcntl.flock(directory_fd, fcntl.LOCK_UN)
        os.close(directory_fd)


def load_p3_gate(path: Path | str) -> P3GateEvidence:
    raw = _strict_yaml(_read_no_follow(Path(path)), "P3 gate")
    if set(raw) != _GATE_KEYS:
        raise P3GateError("invalid closed P3 gate schema")
    files = raw["files"]
    mujoco = raw["mujoco"]
    if not isinstance(files, dict) or set(files) != set(REQUIRED_ARTIFACTS):
        raise P3GateError("P3 gate historical artifact inventory is incomplete")
    if not isinstance(mujoco, dict) or set(mujoco) != {
        "package",
        "version",
        "artifact_sha256",
    }:
        raise P3GateError("invalid P3 gate MuJoCo schema")
    parsed: dict[str, EvidenceFile] = {}
    for key, item in files.items():
        if not isinstance(item, dict) or set(item) != {"path", "git_blob_id", "sha256"}:
            raise P3GateError("invalid P3 gate artifact row")
        if any(type(item[field]) is not str for field in item):
            raise P3GateError("P3 gate artifact identities must be strings")
        parsed[key] = EvidenceFile(
            PurePosixPath(item["path"]), item["git_blob_id"], item["sha256"]
        )
    scalar = {key: raw[key] for key in _GATE_KEYS - {"files", "mujoco"}}
    try:
        return P3GateEvidence(
            **scalar,
            files=parsed,
            mujoco_package=mujoco["package"],
            mujoco_version=mujoco["version"],
            mujoco_artifact_sha256=mujoco["artifact_sha256"],
        )
    except TypeError as exc:
        raise P3GateError("P3 gate scalar types are invalid") from exc


def _verify_exact_evidence(expected: P3GateEvidence, actual: P3GateEvidence) -> None:
    expected_wire = _wire(expected)
    actual_wire = _wire(actual)
    for key in sorted(_GATE_KEYS):
        if expected_wire[key] != actual_wire[key]:
            label = (
                "artifact inventory"
                if key == "files"
                else key.replace("state_index", "state-index")
            )
            raise P3GateError(
                f"sealed P3 gate {label} differs from reconstructed historical evidence"
            )


def require_p3_gate(repo_root: Path, evidence: P3GateEvidence) -> None:
    try:
        root = Path(repo_root)
        current_head = _git_text(root, "rev-parse", "HEAD")
        _require_capture_on_current_first_parent(
            root, current_head, evidence.run_manifest_capture_git_sha
        )
        reconstructed = _capture_gate(
            root, evidence.run_manifest_capture_git_sha
        )
        _verify_exact_evidence(evidence, reconstructed)
    except P3GateError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise P3GateError(f"P3 historical gate validation failed: {exc}") from exc
    if evidence.runtime_network_allowed is not False:
        raise P3GateError("P4 runtime network authority must remain false")


def _destination(root: Path, destination: Path) -> tuple[Path, str]:
    root_absolute = Path(os.path.abspath(root))
    candidate = destination if destination.is_absolute() else root_absolute / destination
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(root_absolute)
    except ValueError as exc:
        raise P3GateError("P3 gate destination escapes repository root") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise P3GateError("P3 gate destination is not normalized")
    return candidate.parent, relative.as_posix()


def _stage_name(name: str) -> str:
    if not name or "/" in name or name in {".", ".."}:
        raise P3GateError("P3 gate publication name is invalid")
    return f".{name}.p3-stage-v1"


def _descriptor_content(descriptor: int, size: int) -> bytes:
    content = b""
    while len(content) < size:
        chunk = os.pread(descriptor, size - len(content), len(content))
        if not chunk:
            break
        content += chunk
    return content


def _validated_publication_descriptor(
    descriptor: int, content: bytes, label: str
) -> tuple[int, int]:
    state = os.fstat(descriptor)
    if (
        not stat.S_ISREG(state.st_mode)
        or stat.S_IMODE(state.st_mode) != 0o600
        or state.st_size != len(content)
        or _descriptor_content(descriptor, state.st_size) != content
    ):
        raise P3GateError(f"P3 gate {label} is conflicting, partial, or invalid")
    return state.st_dev, state.st_ino


def _publish_create_only(parent: Path, name: str, content: bytes) -> None:
    """Crash-atomically publish within the cooperative repository lock boundary.

    Every gate reader and writer in this module locks the containing directory.
    A same-UID actor that ignores that lock and renames paths after lock release is
    explicitly outside the threat model: POSIX pathname APIs cannot prevent it.
    """
    directory_fd = _open_directory_path_no_follow(parent)
    stage = _stage_name(name)
    stage_descriptor = -1
    destination_descriptor = -1
    locked = False
    try:
        # The lock is the explicit repository concurrency boundary. A process
        # that mutates these paths without taking it is outside the POSIX path
        # publication threat model; all gate readers and writers below comply.
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise P3GateError("P3 gate publication directory is locked") from exc
        destination_exists = False
        try:
            existing = _read_file_at(directory_fd, name)
        except ValueError as exc:
            if not isinstance(exc.__cause__, FileNotFoundError):
                raise P3GateError(f"existing P3 gate is not a regular file: {exc}") from exc
        else:
            if existing != content:
                raise P3GateError("existing P3 gate conflicts with reconstructed evidence")
            destination_exists = True

        try:
            stage_descriptor = os.open(
                stage,
                os.O_RDWR
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory_fd,
            )
            stage_exists = True
        except FileNotFoundError:
            stage_exists = False
        except OSError as exc:
            raise P3GateError("existing P3 gate stage is unsafe") from exc

        if not stage_exists and destination_exists:
            try:
                os.fsync(directory_fd)
            except OSError as exc:
                raise P3GateError("existing P3 gate durability check failed") from exc
            return

        try:
            if not stage_exists:
                stage_descriptor = os.open(
                    stage,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
                offset = 0
                while offset < len(content):
                    count = os.write(stage_descriptor, content[offset:])
                    if count <= 0:
                        raise OSError("short P3 gate stage write")
                    offset += count
                os.fsync(stage_descriptor)
            stage_identity = _validated_publication_descriptor(
                stage_descriptor, content, "stage"
            )
            stage_state = os.fstat(stage_descriptor)
            if stage_state.st_nlink not in {1, 2}:
                raise P3GateError("P3 gate stage link ownership is invalid")

            if not destination_exists:
                os.link(
                    stage,
                    name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            destination_descriptor = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory_fd,
            )
            destination_identity = _validated_publication_descriptor(
                destination_descriptor, content, "destination"
            )
            if destination_identity != stage_identity:
                raise P3GateError(
                    "P3 gate destination and authenticated stage identities differ"
                )
            os.fsync(directory_fd)

            # Under the held exclusive cooperative lock, this identity check and
            # unlink cannot race another compliant repository actor.
            current_stage = os.stat(stage, dir_fd=directory_fd, follow_symlinks=False)
            if (current_stage.st_dev, current_stage.st_ino) != stage_identity:
                raise P3GateError("P3 gate stage identity changed under exclusive lock")
            os.unlink(stage, dir_fd=directory_fd)
            os.fsync(directory_fd)
        except (OSError, P3GateError) as exc:
            if isinstance(exc, P3GateError):
                raise
            raise P3GateError(f"P3 gate destination publication failed: {exc}") from exc
    finally:
        if destination_descriptor >= 0:
            os.close(destination_descriptor)
        if stage_descriptor >= 0:
            os.close(stage_descriptor)
        if locked:
            fcntl.flock(directory_fd, fcntl.LOCK_UN)
        os.close(directory_fd)


def _destination_exists(parent: Path, name: str) -> bool:
    directory_fd = _open_directory_path_no_follow(parent)
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_SH)
        try:
            state = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(state.st_mode):
            raise P3GateError("existing P3 gate destination is not a regular file")
        return True
    finally:
        fcntl.flock(directory_fd, fcntl.LOCK_UN)
        os.close(directory_fd)


def write_p3_gate(repo_root: Path, destination: Path) -> None:
    root = Path(repo_root)
    parent, relative = _destination(root, Path(destination))
    stage_relative = (
        PurePosixPath(relative).parent / _stage_name(Path(relative).name)
    ).as_posix()
    status = __import__("scripts.publish_phase_record", fromlist=["*"])._worktree_status(
        root, allowed_untracked=frozenset({relative, stage_relative})
    )
    if status:
        raise P3GateError("P3 gate capture requires a clean worktree")
    target = root / relative
    if _destination_exists(parent, target.name):
        try:
            existing = load_p3_gate(target)
            require_p3_gate(root, existing)
            _publish_create_only(parent, target.name, _gate_bytes(existing))
        except P3GateError as exc:
            raise P3GateError(f"existing P3 gate conflicts with historical evidence: {exc}") from exc
        return
    capture_sha = _git_text(root, "rev-parse", "HEAD")
    evidence = _capture_gate(root, capture_sha)
    _, worktree_manifest = __import__(
        "scripts.publish_phase_record", fromlist=["*"]
    )._read_worktree_manifest(root, PurePosixPath(RUN_MANIFEST_PATH))
    _, capture_manifest = _git_blob(root, capture_sha, RUN_MANIFEST_PATH)
    if worktree_manifest != _strict_yaml(capture_manifest, "capture manifest"):
        raise P3GateError("P3 gate capture requires current manifest bytes at clean HEAD")
    _publish_create_only(parent, target.name, _gate_bytes(evidence))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", type=Path, required=True)
    arguments = parser.parse_args(argv)
    write_p3_gate(Path.cwd(), arguments.write)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, P3GateError, RuntimeError, ValueError) as exc:
        print(f"P3 gate error: {exc}", file=__import__("sys").stderr)
        raise SystemExit(1) from exc
