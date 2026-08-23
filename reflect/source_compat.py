"""Immutable source-compatibility evidence and deterministic consolidation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
from dataclasses import dataclass
from enum import Enum
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

import yaml

from reflect.source_evidence import canonical_json_bytes, canonical_sha256, open_directory_chain
from reflect.source_evidence import CheckoutEvidence
from reflect.sources import (
    LicenseStatus,
    PathStatus,
    ReuseMode,
    SourceLock,
    SourceRegistry,
    validate_lock,
)


class CompatibilityClass(str, Enum):
    WORKS_LOCAL_M2 = "WORKS_LOCAL_M2"
    WORKS_LOCAL_CPU_WITH_PATCH = "WORKS_LOCAL_CPU_WITH_PATCH"
    SOURCE_REFERENCE_ONLY = "SOURCE_REFERENCE_ONLY"
    REMOTE_GPU_REQUIRED = "REMOTE_GPU_REQUIRED"
    REMOTE_LINUX_REQUIRED = "REMOTE_LINUX_REQUIRED"
    LICENSE_REVIEW_REQUIRED = "LICENSE_REVIEW_REQUIRED"
    STALE_OR_ARCHIVED = "STALE_OR_ARCHIVED"
    PATH_CHANGED = "PATH_CHANGED"
    NOT_EVALUATED = "NOT_EVALUATED"


class SmokeStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


CSV_HEADER = (
    "repository", "commit_sha", "experiment", "reuse_mode", "selected_path",
    "path_status", "operation", "platform", "python_requirement",
    "compiler_or_runtime", "smoke_command", "smoke_status", "classification",
    "license_status", "license_spdx", "disk_bytes", "download_bytes", "blocker",
    "notes",
)
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FIXED_SMOKE_PATH = "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json"
_LEROBOT_CONTRACT_PATH = "experiments/00_source_audit/configs/lerobot-contained-symlinks-v1.json"
_LEROBOT_R1_AMENDMENT_PATH = "experiments/00_source_audit/MANIFEST_AMENDMENT.yaml"
_LEROBOT_R2_AMENDMENT_PATH = "experiments/00_source_audit/MANIFEST_AMENDMENT_R2.yaml"
_LEROBOT_AMENDMENT_PATH = "experiments/00_source_audit/MANIFEST_AMENDMENT_R3.yaml"
_LEROBOT_V1_PATH = "experiments/00_source_audit/results/attempts/lerobot-checkout-v1-fail.json"
_LEROBOT_V2_PATH = "experiments/00_source_audit/results/attempts/lerobot-checkout-v2-pass.json"
_LEROBOT_RECEIPT_PATH = "experiments/00_source_audit/results/fragments/lerobot-checkout.json"
_LEROBOT_R1_AMENDMENT_SHA256 = "58a18736dbdee83081228a8ce3cc44c537c3c5bbbb56e2b9fe75c692ec95a67e"
_LEROBOT_R2_AMENDMENT_SHA256 = "7d998f508d069e66b8742210700e3d09ac006626f3e9bf42650c79c46bd74c06"
_LEROBOT_R3_REASON = (
    "Independent audit found that revision 2 validated each declared link but did not "
    "prove the absence of an undeclared fourth link. Revision 3 exhaustively inventories "
    "every Git object beneath the selected paths and records the link and target modes."
)
_EVIDENCE_KEYS = {
    "schema_version", "evidence_type", "registry_sha256", "repository",
    "commit_sha", "experiment", "selected_path", "operation_id", "operation", "platform",
    "python_requirement", "compiler_or_runtime", "command", "exit_status",
    "disk_bytes", "download_bytes", "license_status", "license_spdx", "blocker",
    "notes", "runtime_subject", "package_name", "package_version",
    "package_artifact_sha256", "package_lock_artifact_sha256",
    "patch_artifact_sha256", "findings",
    "content_hashes", "evidence_sha256",
}
_STATIC_FILE_KEYS = {
    "AST_PARSE": {"path", "sha256", "bytes", "disposition", "node_count", "failure_line", "failure_column"},
    "HEADER_LAYOUT": {"path", "sha256", "bytes", "disposition", "include_guard", "pragma_once", "declaration_count", "failure_line"},
    "MANIFEST_LAYOUT": {"path", "sha256", "bytes", "disposition", "format", "top_level", "failure_line"},
    "ASSET_LICENSE_INVENTORY": {"path", "sha256", "bytes", "disposition", "license_candidates", "failure_line"},
}


def _string(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is not str or not value or "\0" in value or "\n" in value:
        raise ValueError(f"{field} must be a non-empty single-line string")
    return value


def _sha(value: object, field: str, length: int) -> str:
    result = _string(value, field)
    pattern = _SHA40 if length == 40 else _SHA256
    if pattern.fullmatch(result or "") is None:
        raise ValueError(f"{field} has an invalid digest")
    return result  # type: ignore[return-value]


def _validate_raw_findings(
    operation: str,
    findings: tuple[tuple[str, Any], ...],
    content_hashes: tuple[tuple[str, str], ...],
) -> None:
    raw = dict(findings)
    if operation == "PACKAGE_RUNTIME":
        required = {"duration_ns", "artifact", "dynamics"}
        if set(raw) != required or type(raw["duration_ns"]) is not int or raw["duration_ns"] < 0:
            raise ValueError("package smoke findings schema is invalid")
        artifact = raw["artifact"]
        dynamics = raw["dynamics"]
        if not isinstance(artifact, Mapping) or set(artifact) != {
            "wheel_filename", "lock_artifact_sha256", "installed_tree_sha256",
            "record_entries", "installed_files", "installed_bytes", "executed_origins",
        }:
            raise ValueError("package artifact findings schema is invalid")
        _string(artifact["wheel_filename"], "wheel filename")
        _sha(artifact["lock_artifact_sha256"], "lock artifact sha256", 64)
        _sha(artifact["installed_tree_sha256"], "installed tree sha256", 64)
        if any(type(artifact[key]) is not int or artifact[key] <= 0 for key in ("record_entries", "installed_files", "installed_bytes")):
            raise ValueError("package artifact inventory counts are invalid")
        if artifact["record_entries"] != artifact["installed_files"]:
            raise ValueError("package RECORD does not cover the complete installed inventory")
        origins = artifact["executed_origins"]
        if not isinstance(origins, list) or not origins:
            raise ValueError("package executed-origin inventory is invalid")
        origin_modules = set()
        for origin in origins:
            if not isinstance(origin, Mapping) or set(origin) != {"module", "record_path", "sha256", "native_extension"}:
                raise ValueError("package executed-origin row is invalid")
            module = _string(origin["module"], "executed module")
            _safe_relative(origin["record_path"], "executed RECORD path")
            _sha(origin["sha256"], "executed module sha256", 64)
            if type(origin["native_extension"]) is not bool or module in origin_modules:
                raise ValueError("package executed-origin identity is invalid")
            origin_modules.add(module)
        if not {"mujoco", "mujoco._functions", "mujoco._structs"}.issubset(origin_modules) or not any(row["native_extension"] for row in origins):
            raise ValueError("package core/native execution origins are incomplete")
        if not isinstance(dynamics, Mapping) or set(dynamics) != {
            "xml_sha256", "control", "timestep", "nq", "nv", "nu", "post_step",
        }:
            raise ValueError("package dynamics findings schema is invalid")
        _sha(dynamics["xml_sha256"], "dynamics XML sha256", 64)
        if dict(content_hashes).get("inline-model.xml") != dynamics["xml_sha256"]:
            raise ValueError("package dynamics XML hash is not content-bound")
        for key in ("nq", "nv", "nu"):
            if type(dynamics[key]) is not int or dynamics[key] <= 0:
                raise ValueError("package dynamics dimensions are invalid")
        if not isinstance(dynamics["control"], list) or len(dynamics["control"]) != dynamics["nu"]:
            raise ValueError("package dynamics control shape is invalid")
        if any(type(value) is not str or not math.isfinite(float.fromhex(value)) for value in dynamics["control"]):
            raise ValueError("package dynamics control encoding is invalid")
        if dynamics["control"] != [float(0.125).hex()] or (dynamics["nq"], dynamics["nv"], dynamics["nu"]) != (8, 7, 1):
            raise ValueError("package dynamics frozen control/dimensions mismatch")
        if type(dynamics["timestep"]) is not str or not math.isfinite(float.fromhex(dynamics["timestep"])) or dynamics["timestep"] != float(0.002).hex():
            raise ValueError("package dynamics timestep encoding is invalid")
        post = dynamics["post_step"]
        if not isinstance(post, Mapping) or set(post) != {"time", "qpos", "qvel", "qpos_sha256", "qvel_sha256"}:
            raise ValueError("package post-step state schema is invalid")
        if type(post["time"]) is not str or not math.isfinite(float.fromhex(post["time"])) or post["time"] != dynamics["timestep"]:
            raise ValueError("package post-step time encoding is invalid")
        if not isinstance(post["qpos"], list) or not isinstance(post["qvel"], list) or len(post["qpos"]) != dynamics["nq"] or len(post["qvel"]) != dynamics["nv"]:
            raise ValueError("package post-step state shape is invalid")
        for key in ("qpos", "qvel"):
            if any(type(value) is not str or not math.isfinite(float.fromhex(value)) for value in post[key]):
                raise ValueError("package post-step state encoding is invalid")
            _sha(post[f"{key}_sha256"], f"{key} sha256", 64)
            if post[f"{key}_sha256"] != canonical_sha256(post[key]):
                raise ValueError("package post-step state hash mismatch")
        if float.fromhex(post["qpos"][0]) == 0.0 or float.fromhex(post["qvel"][0]) == 0.0:
            raise ValueError("package actuated hinge did not move")
        return
    if operation not in _STATIC_FILE_KEYS or set(raw) != {"files", "summary"}:
        raise ValueError("static operation findings schema is invalid")
    if not isinstance(raw["files"], list) or not isinstance(raw["summary"], Mapping):
        raise ValueError("static operation files/summary are invalid")
    if set(raw["summary"]) != {"files_total", "files_pass", "files_fail"} or any(type(raw["summary"][key]) is not int or raw["summary"][key] < 0 for key in raw["summary"]):
        raise ValueError("static operation summary schema is invalid")
    if raw["summary"]["files_total"] != len(raw["files"]) or raw["summary"]["files_pass"] + raw["summary"]["files_fail"] != len(raw["files"]):
        raise ValueError("static operation summary counts are inconsistent")
    expected_hashes = dict(content_hashes)
    seen = set()
    for item in raw["files"]:
        if not isinstance(item, Mapping) or set(item) != _STATIC_FILE_KEYS[operation]:
            raise ValueError("operation-specific file finding is invalid")
        path = _string(item["path"], "finding path")
        digest = _sha(item["sha256"], "finding sha256", 64)
        if path in seen or expected_hashes.get(path) != digest:
            raise ValueError("finding path/hash disposition is duplicated or inconsistent")
        seen.add(path)
        if type(item["bytes"]) is not int or item["bytes"] < 0:
            raise ValueError("finding byte count is invalid")
        if item["disposition"] not in {"PASS", "FAIL"}:
            raise ValueError("finding disposition is invalid")
        failed = item["disposition"] == "FAIL"
        if operation == "AST_PARSE" and (type(item["node_count"]) is not int or item["node_count"] < 0):
            raise ValueError("AST finding node count is invalid")
        if operation == "AST_PARSE" and ((item["failure_line"] is None) == failed or (item["failure_column"] is None) == failed):
            raise ValueError("AST finding failure location is invalid")
        if operation == "HEADER_LAYOUT" and (type(item["pragma_once"]) is not bool or type(item["declaration_count"]) is not int or item["declaration_count"] < 0):
            raise ValueError("header finding structure is invalid")
        if operation == "HEADER_LAYOUT" and ((item["failure_line"] is None) == failed):
            raise ValueError("header finding failure location is invalid")
        if operation == "MANIFEST_LAYOUT" and (item["format"] not in {"TOML", "XML", "JSON", "YAML"} or not isinstance(item["top_level"], list)):
            raise ValueError("manifest finding structure is invalid")
        if operation == "MANIFEST_LAYOUT" and ((item["failure_line"] is None) == failed):
            raise ValueError("manifest finding failure location is invalid")
        if operation == "ASSET_LICENSE_INVENTORY" and not isinstance(item["license_candidates"], list):
            raise ValueError("asset-license finding structure is invalid")
        if operation == "ASSET_LICENSE_INVENTORY" and ((item["failure_line"] is None) == failed):
            raise ValueError("asset-license finding failure location is invalid")
    if seen != set(expected_hashes):
        raise ValueError("every selected content hash requires one file disposition")
    dispositions = [item["disposition"] for item in raw["files"]]
    if raw["summary"]["files_pass"] != dispositions.count("PASS") or raw["summary"]["files_fail"] != dispositions.count("FAIL"):
        raise ValueError("static operation summary does not equal file dispositions")


def _lock_object(lock: SourceLock) -> dict[str, Any]:
    return {
        "registry_sha256": lock.registry_sha256,
        "generated_at": lock.generated_at,
        "entries": [
            {
                "name": item.name, "url": item.url,
                "default_branch": item.default_branch, "commit_sha": item.commit_sha,
                "retrieved_at": item.retrieved_at,
                "metadata_evidence": dict(sorted(item.metadata_evidence.items())),
                "license_spdx": item.license_spdx,
                "license_status": item.license_status.value,
                "license_evidence_url": item.license_evidence_url,
                "path_statuses": {key: value.value for key, value in sorted(item.path_statuses.items())},
                "path_evidence_urls": dict(sorted(item.path_evidence_urls.items())),
                "metadata_status": item.metadata_status.value,
            }
            for item in lock.entries
        ],
    }


def source_lock_sha256(lock: SourceLock) -> str:
    return canonical_sha256(_lock_object(lock))


@dataclass(frozen=True)
class CompatibilityEvidence:
    schema_version: int
    evidence_type: str
    registry_sha256: str
    repository: str
    commit_sha: str
    experiment: str
    selected_path: str
    operation_id: str
    operation: str
    platform: str
    python_requirement: str
    compiler_or_runtime: str
    command: tuple[str, ...]
    exit_status: int | None
    disk_bytes: int
    download_bytes: int
    license_status: str
    license_spdx: str | None
    blocker: str | None
    notes: str
    runtime_subject: str
    package_name: str | None
    package_version: str | None
    package_artifact_sha256: str | None
    package_lock_artifact_sha256: str | None
    patch_artifact_sha256: str | None
    findings: tuple[tuple[str, Any], ...]
    content_hashes: tuple[tuple[str, str], ...]
    evidence_sha256: str

    @classmethod
    def create(cls, **values: Any) -> "CompatibilityEvidence":
        findings = values.pop("findings")
        content_hashes = values.pop("content_hashes")
        record = cls(
            schema_version=1,
            evidence_type="COMPATIBILITY",
            findings=tuple(sorted(findings.items())),
            content_hashes=tuple(sorted(content_hashes.items())),
            evidence_sha256="0" * 64,
            **values,
        )
        record._validate(include_hash=False)
        return cls(**{**record.__dict__, "evidence_sha256": canonical_sha256(record.to_dict(False))})

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CompatibilityEvidence":
        if set(raw) != _EVIDENCE_KEYS:
            raise ValueError("compatibility fragment has missing or extra keys")
        findings = raw["findings"]
        hashes = raw["content_hashes"]
        if not isinstance(findings, Mapping) or not isinstance(hashes, list):
            raise ValueError("compatibility findings/content hashes are invalid")
        parsed_hashes: dict[str, str] = {}
        for item in hashes:
            if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
                raise ValueError("content hash row is invalid")
            if item["path"] in parsed_hashes:
                raise ValueError("duplicate content hash path")
            parsed_hashes[item["path"]] = item["sha256"]
        record = cls(
            **{key: raw[key] for key in _EVIDENCE_KEYS - {"findings", "content_hashes", "command"}},
            command=tuple(raw["command"]),
            findings=tuple(sorted(findings.items())),
            content_hashes=tuple(sorted(parsed_hashes.items())),
        )
        record._validate()
        return record

    def _validate(self, include_hash: bool = True) -> None:
        if self.schema_version != 1 or self.evidence_type != "COMPATIBILITY":
            raise ValueError("compatibility evidence schema/type is invalid")
        _sha(self.registry_sha256, "registry_sha256", 64)
        _sha(self.commit_sha, "commit_sha", 40)
        for field in ("repository", "experiment", "selected_path", "operation_id", "operation", "platform", "python_requirement", "compiler_or_runtime", "notes"):
            _string(getattr(self, field), field)
        if self.runtime_subject not in {"source_checkout", "package"}:
            raise ValueError("runtime_subject is invalid")
        if not self.command or any(type(item) is not str or not item for item in self.command):
            raise ValueError("command must be a nonempty relative vector")
        if any(Path(item).is_absolute() for item in self.command):
            raise ValueError("command contains an absolute path")
        if self.exit_status is not None and (type(self.exit_status) is not int or self.exit_status < 0):
            raise ValueError("exit_status is invalid")
        if any(type(value) is not int or value < 0 for value in (self.disk_bytes, self.download_bytes)):
            raise ValueError("byte counts must be nonnegative integers")
        LicenseStatus(self.license_status)
        if self.runtime_subject == "package":
            if (
                self.operation != "PACKAGE_RUNTIME"
                or self.operation_id != "MUJOCO_PACKAGE_SMOKE"
                or self.repository != "mujoco"
                or self.package_name != "mujoco"
                or self.command != ("mujoco", "headless-one-step")
                or not self.package_version
                or self.package_version != "3.12.0"
                or self.package_artifact_sha256 is None
                or self.package_lock_artifact_sha256 is None
            ):
                raise ValueError("package runtime requires package identity and artifact hash")
            _sha(self.package_artifact_sha256, "package_artifact_sha256", 64)
            _sha(self.package_lock_artifact_sha256, "package_lock_artifact_sha256", 64)
            if self.exit_status != 0 or self.blocker is not None:
                raise ValueError("package PASS requires exact zero status and no blocker")
            raw_artifact = dict(self.findings).get("artifact")
            if not isinstance(raw_artifact, Mapping) or raw_artifact.get("installed_tree_sha256") != self.package_artifact_sha256 or raw_artifact.get("lock_artifact_sha256") != self.package_lock_artifact_sha256:
                raise ValueError("package hashes are not bound to raw artifact findings")
            if raw_artifact.get("installed_bytes") != self.disk_bytes:
                raise ValueError("package installed bytes do not equal evidence disk_bytes")
        else:
            if self.operation not in _STATIC_FILE_KEYS:
                raise ValueError("source checkout operation is not in the closed matrix")
            if self.command != (self.operation.lower(), self.selected_path):
                raise ValueError("source checkout command does not match operation matrix")
            if any(value is not None for value in (self.package_name, self.package_version, self.package_artifact_sha256, self.package_lock_artifact_sha256)):
                raise ValueError("source checkout cannot claim package identity")
            raw_files = dict(self.findings).get("files", [])
            failed = any(item.get("disposition") == "FAIL" for item in raw_files)
            if (failed and (self.exit_status != 1 or self.blocker is None)) or (not failed and (self.exit_status != 0 or self.blocker is not None)):
                raise ValueError("static status/blocker must exactly equal file dispositions")
            if sum(item.get("bytes", -1) for item in raw_files) != self.disk_bytes:
                raise ValueError("static finding bytes must exactly equal evidence disk_bytes")
        if self.patch_artifact_sha256 is not None:
            raise ValueError("closed compatibility matrix has no patched-runtime operation")
        for path, digest in self.content_hashes:
            _string(path, "content path")
            _sha(digest, "content hash", 64)
        _validate_raw_findings(self.operation, self.findings, self.content_hashes)
        if include_hash:
            _sha(self.evidence_sha256, "evidence_sha256", 64)
            if self.evidence_sha256 != canonical_sha256(self.to_dict(False)):
                raise ValueError("compatibility evidence hash mismatch")

    def to_dict(self, include_hash: bool = True) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version, "evidence_type": self.evidence_type,
            "registry_sha256": self.registry_sha256, "repository": self.repository,
            "commit_sha": self.commit_sha, "experiment": self.experiment,
            "selected_path": self.selected_path, "operation_id": self.operation_id,
            "operation": self.operation,
            "platform": self.platform, "python_requirement": self.python_requirement,
            "compiler_or_runtime": self.compiler_or_runtime, "command": list(self.command),
            "exit_status": self.exit_status, "disk_bytes": self.disk_bytes,
            "download_bytes": self.download_bytes, "license_status": self.license_status,
            "license_spdx": self.license_spdx, "blocker": self.blocker, "notes": self.notes,
            "runtime_subject": self.runtime_subject, "package_name": self.package_name,
            "package_version": self.package_version,
            "package_artifact_sha256": self.package_artifact_sha256,
            "package_lock_artifact_sha256": self.package_lock_artifact_sha256,
            "patch_artifact_sha256": self.patch_artifact_sha256,
            "findings": dict(self.findings),
            "content_hashes": [{"path": path, "sha256": digest} for path, digest in self.content_hashes],
        }
        if include_hash:
            result["evidence_sha256"] = self.evidence_sha256
        return result

    def canonical_bytes(self) -> bytes:
        self._validate()
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True)
class RequirementObservation:
    repository: str
    kind: str
    statement: str
    provenance: str
    statement_sha256: str

    def __post_init__(self) -> None:
        if self.kind not in {"REMOTE_GPU", "REMOTE_LINUX", "ARCHIVED"}:
            raise ValueError("requirement observation kind is invalid")
        _string(self.repository, "observation repository")
        _string(self.statement, "observation statement")
        if not (self.provenance.startswith("https://") or self.provenance.startswith("canonical-program:")):
            raise ValueError("observation provenance must be official HTTPS or canonical-program")
        if self.statement_sha256 != hashlib.sha256(self.statement.encode()).hexdigest():
            raise ValueError("observation statement hash mismatch")


@dataclass(frozen=True)
class RepositoryIdentity:
    repository: str
    commit_sha: str
    paths: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ManifestOperation:
    operation_id: str
    repository: str
    operation: str
    runtime_subject: str
    experiment: str
    selected_path: str
    command: tuple[str, ...]
    relative_output: str
    platform: str
    python_requirement: str
    compiler_or_runtime: str
    timeout_seconds: int
    download_ceiling_bytes: int
    disk_ceiling_bytes: int
    no_copy: bool
    no_models: bool
    package_name: str | None
    file_ceiling_bytes: int
    file_count_ceiling: int
    depth_ceiling: int


@dataclass(frozen=True)
class OutputSelector:
    operation_id: str
    relative_path: str


@dataclass(frozen=True)
class OperationManifest:
    schema_version: int
    registry_sha256: str
    lock_sha256: str
    repositories: tuple[RepositoryIdentity, ...]
    operations: tuple[ManifestOperation, ...]
    requirement_observations: tuple[RequirementObservation, ...]
    mujoco_smoke_output: OutputSelector


def _safe_relative(value: object, field: str) -> str:
    result = _string(value, field)
    path = PurePosixPath(result or "")
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} is an unsafe path")
    return result  # type: ignore[return-value]


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _read_regular_artifact(root: Path, relative: str) -> bytes:
    path = PurePosixPath(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("P3 revision artifact path is unsafe")
    try:
        parent = open_directory_chain(root.joinpath(*path.parts[:-1]), create=False)
    except OSError as error:
        raise ValueError(f"P3 revision artifact is unavailable: {relative}") from error
    try:
        try:
            descriptor = os.open(
                path.parts[-1],
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent,
            )
        except OSError as error:
            raise ValueError(f"P3 revision artifact is unavailable: {relative}") from error
    finally:
        os.close(parent)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 2 * 1024 * 1024:
            raise ValueError("P3 revision artifact must be one bounded regular file")
        data = os.read(descriptor, before.st_size + 1)
        after = os.fstat(descriptor)
        if len(data) != before.st_size or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("P3 revision artifact changed during inspection")
        return data
    finally:
        os.close(descriptor)


def _validate_lerobot_revision_chain(
    project_root: Path,
    receipt: CheckoutEvidence,
    receipt_bytes: bytes,
    registry: SourceRegistry | None = None,
    lock: SourceLock | None = None,
) -> None:
    contract_bytes = _read_regular_artifact(project_root, _LEROBOT_CONTRACT_PATH)
    r1_amendment_bytes = _read_regular_artifact(project_root, _LEROBOT_R1_AMENDMENT_PATH)
    r2_amendment_bytes = _read_regular_artifact(project_root, _LEROBOT_R2_AMENDMENT_PATH)
    amendment_bytes = _read_regular_artifact(project_root, _LEROBOT_AMENDMENT_PATH)
    v1_bytes = _read_regular_artifact(project_root, _LEROBOT_V1_PATH)
    v2_bytes = _read_regular_artifact(project_root, _LEROBOT_V2_PATH)
    contract = _json_no_duplicates(contract_bytes)
    r1_amendment = yaml.load(r1_amendment_bytes, Loader=_UniqueLoader)
    r2_amendment = yaml.load(r2_amendment_bytes, Loader=_UniqueLoader)
    amendment = yaml.load(amendment_bytes, Loader=_UniqueLoader)
    v1 = CheckoutEvidence.from_dict(_json_no_duplicates(v1_bytes))
    v2 = CheckoutEvidence.from_dict(_json_no_duplicates(v2_bytes))
    if not all(isinstance(value, Mapping) for value in (r1_amendment, r2_amendment, amendment)):
        raise ValueError("LeRobot revision amendment must be a mapping")
    expected_top_keys = {
        "schema_version", "record_type", "revision", "classification", "operation_id",
        "reason", "implementation_commit", "registry_sha256", "lock_sha256",
        "locked_commit_sha", "locked_recursive_tree_sha", "policy", "contract",
        "prior_amendments", "scope", "validation", "revision_1_failure",
        "revision_2_receipt", "revision_3_receipt", "result",
    }
    contract_binding = amendment.get("contract")
    prior_amendments = amendment.get("prior_amendments")
    prior = amendment.get("revision_1_failure")
    prior_pass = amendment.get("revision_2_receipt")
    current = amendment.get("revision_3_receipt")
    validation = amendment.get("validation")
    scope = amendment.get("scope")
    result = amendment.get("result")
    expected_prior_amendments = [
        {"path": _LEROBOT_R1_AMENDMENT_PATH, "sha256": _LEROBOT_R1_AMENDMENT_SHA256},
        {"path": _LEROBOT_R2_AMENDMENT_PATH, "sha256": _LEROBOT_R2_AMENDMENT_SHA256},
    ]
    expected_scope = {
        "checkout": "EXACT_LOCKED_LEROBOT_ARTIFACT_ONLY",
        "source_copy_authority": False,
        "adapter_authority": False,
        "symlink_chain_following": False,
        "filesystem_symlink_output": False,
    }
    expected_result = {
        "prior_attempts_preserved": True,
        "operational_gate": "PASS",
        "confirmation_eligible": False,
        "limitation": (
            "This post-freeze engineering repair closes only the operational source gate; it "
            "does not convert the amended P3 evidence into confirmatory evidence."
        ),
    }
    expected_contract_keys = {
        "schema_version", "policy", "registry_sha256", "repository", "url",
        "commit_sha", "recursive_tree_sha", "symlinks",
    }
    if (
        set(amendment) != expected_top_keys
        or hashlib.sha256(r1_amendment_bytes).hexdigest() != _LEROBOT_R1_AMENDMENT_SHA256
        or hashlib.sha256(r2_amendment_bytes).hexdigest() != _LEROBOT_R2_AMENDMENT_SHA256
        or amendment.get("schema_version") != 1
        or amendment.get("record_type") != "P3_OPERATION_CONTRACT_REVISION"
        or amendment.get("revision") != 3
        or amendment.get("operation_id") != "LEROBOT_CHECKOUT"
        or amendment.get("classification") != "ENGINEERING_NONCONFIRMATORY"
        or amendment.get("reason") != _LEROBOT_R3_REASON
        or amendment.get("implementation_commit") != "3cc5d180dde9b2a4f2682a3c3c92daf3e9619d91"
        or amendment.get("registry_sha256") != receipt.registry_sha256
        or (registry is not None and amendment.get("registry_sha256") != registry.registry_sha256)
        or (lock is not None and amendment.get("lock_sha256") != source_lock_sha256(lock))
        or amendment.get("locked_commit_sha") != receipt.locked_sha
        or amendment.get("locked_recursive_tree_sha") != receipt.recursive_tree_sha
        or amendment.get("policy") != "CONTAINED_GIT_SYMLINKS_V1"
        or contract_binding != {
            "path": _LEROBOT_CONTRACT_PATH,
            "sha256": hashlib.sha256(contract_bytes).hexdigest(),
        }
        or prior_amendments != expected_prior_amendments
        or scope != expected_scope
        or prior != {
            "path": _LEROBOT_V1_PATH,
            "file_sha256": hashlib.sha256(v1_bytes).hexdigest(),
            "evidence_sha256": v1.evidence_sha256,
            "outcome": "FAIL",
        }
        or v1.schema_version != 1
        or v1.repository != "lerobot"
        or v1.registry_sha256 != receipt.registry_sha256
        or v1.locked_sha != receipt.locked_sha
        or v1.blocker != "checkout contains a nonregular or linked file"
        or v1.outcome != "FAIL"
        or prior_pass != {
            "path": _LEROBOT_V2_PATH,
            "file_sha256": hashlib.sha256(v2_bytes).hexdigest(),
            "evidence_sha256": v2.evidence_sha256,
            "outcome": "PASS",
            "limitation": "declared-link query did not establish absence of undeclared links",
        }
        or v2.schema_version != 2
        or v2.repository != receipt.repository
        or v2.registry_sha256 != receipt.registry_sha256
        or v2.locked_sha != receipt.locked_sha
        or v2.recursive_tree_sha != receipt.recursive_tree_sha
        or v2.symlink_policy != receipt.symlink_policy
        or len(v2.content_hashes) != 33
        or len(v2.contained_symlinks) != 3
        or v2.outcome != "PASS"
        or current != {
            "path": _LEROBOT_RECEIPT_PATH,
            "file_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "evidence_sha256": receipt.evidence_sha256,
            "outcome": "PASS",
            "download_bytes": receipt.download_bytes,
            "disk_bytes": receipt.disk_bytes,
            "retained_file_count": len(receipt.content_hashes),
        }
        or receipt.outcome != "PASS"
        or receipt.schema_version != 3
        or receipt.symlink_policy != "CONTAINED_GIT_SYMLINKS_V1"
        or not isinstance(validation, Mapping)
        or set(validation) != {
            "git_object_modes", "regular_target_modes", "materialization", "target_rule",
            "selected_tree_inventory", "declared_link_count", "observed_link_count",
        }
        or validation.get("git_object_modes") != ["120000", "120000", "120000"]
        or validation.get("regular_target_modes") != ["100644", "100644", "100644"]
        or validation.get("materialization") != "CORE_SYMLINKS_FALSE_REGULAR_DESCRIPTOR"
        or validation.get("target_rule") != "RELATIVE_CONTAINED_DECLARED_REGULAR_BLOB"
        or validation.get("selected_tree_inventory") != "EXHAUSTIVE_LS_TREE_RECURSIVE"
        or validation.get("declared_link_count") != 3
        or validation.get("observed_link_count") != 3
        or result != expected_result
    ):
        raise ValueError("LeRobot revision receipt/contract/amendment hash join is invalid")
    if (
        set(contract) != expected_contract_keys
        or contract.get("schema_version") != 1
        or contract.get("policy") != receipt.symlink_policy
        or contract.get("registry_sha256") != receipt.registry_sha256
        or contract.get("repository") != receipt.repository
        or contract.get("url") != receipt.url
        or contract.get("commit_sha") != receipt.locked_sha
        or contract.get("recursive_tree_sha") != receipt.recursive_tree_sha
    ):
        raise ValueError("LeRobot revision receipt does not match its exact contract identity")
    contract_rows = contract.get("symlinks")
    receipt_rows = [dict(row) for row in receipt.contained_symlinks]
    if not isinstance(contract_rows, list) or len(contract_rows) != len(receipt_rows):
        raise ValueError("LeRobot revision symlink inventory cardinality differs")
    expected_contract_row_keys = {
        "path", "link_blob_sha1", "target", "target_path", "target_blob_sha1",
    }
    if any(not isinstance(row, Mapping) or set(row) != expected_contract_row_keys for row in contract_rows):
        raise ValueError("LeRobot revision contract symlink row schema is not exact")
    for expected, row in zip(contract_rows, receipt_rows, strict=True):
        if (
            any(row[key] != expected[key] for key in expected_contract_row_keys)
            or row["link_mode"] != "120000"
            or row["target_mode"] != "100644"
        ):
            raise ValueError("LeRobot revision receipt object modes or identities differ")
    expected_exhaustive_command = (
        "git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
        "-c", "credential.helper=", "-C", "lerobot", "ls-tree", "-r", "-z",
        "HEAD", "--", *receipt.patterns,
        *(row["target_path"] for row in contract_rows),
    )
    exhaustive_indices = [
        index for index, command in enumerate(receipt.commands) if "ls-tree" in command
    ]
    if (
        len(exhaustive_indices) != 1
        or receipt.commands[exhaustive_indices[0]] != expected_exhaustive_command
        or receipt.statuses[exhaustive_indices[0]] != 0
    ):
        raise ValueError("LeRobot revision receipt lacks one exhaustive selected-tree inventory")


def load_operation_manifest(path: Path, registry: SourceRegistry, lock: SourceLock, root: Path) -> OperationManifest:
    raw = yaml.load(path.read_text(), Loader=_UniqueLoader)
    required = {"schema_version", "registry_sha256", "lock_sha256", "repositories", "operations", "requirement_observations", "mujoco_smoke_output"}
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise ValueError("operation manifest has missing or extra keys")
    if raw["schema_version"] != 1 or raw["registry_sha256"] != registry.registry_sha256 or raw["lock_sha256"] != source_lock_sha256(lock):
        raise ValueError("operation manifest digest binding is invalid")
    errors = validate_lock(registry, lock, require_complete=True)
    if errors:
        raise ValueError(f"operation manifest requires complete lock: {errors[0]}")
    identities_list = []
    for item in raw["repositories"]:
        if not isinstance(item, Mapping) or set(item) != {"repository", "commit_sha", "paths"} or not isinstance(item["paths"], list):
            raise ValueError("repository identity schema is invalid")
        paths = []
        for row in item["paths"]:
            if not isinstance(row, Mapping) or set(row) != {"path", "status"}:
                raise ValueError("repository path identity schema is invalid")
            PathStatus(row["status"])
            paths.append((row["path"], row["status"]))
        identities_list.append(RepositoryIdentity(item["repository"], item["commit_sha"], tuple(paths)))
    identities = tuple(identities_list)
    expected = tuple(
        (
            item.name,
            item.commit_sha,
            tuple((path, status.value) for path, status in sorted(item.path_statuses.items())),
        )
        for item in lock.entries
    )
    if tuple((item.repository, item.commit_sha, item.paths) for item in identities) != expected:
        raise ValueError("operation manifest must cover every locked repository in order")
    operation_keys = {
        "operation_id", "repository", "operation", "runtime_subject", "experiment",
        "selected_path", "command", "relative_output", "platform",
        "python_requirement", "compiler_or_runtime", "timeout_seconds",
        "download_ceiling_bytes", "disk_ceiling_bytes", "no_copy", "no_models",
        "package_name",
        "file_ceiling_bytes", "file_count_ceiling", "depth_ceiling",
    }
    operations_list = []
    for item in raw["operations"]:
        if not isinstance(item, Mapping) or set(item) != operation_keys:
            raise ValueError("manifest operation schema is invalid")
        if not isinstance(item["command"], list):
            raise ValueError("manifest operation command must be a list")
        operations_list.append(ManifestOperation(**{**item, "command": tuple(item["command"])}))
    operations = tuple(operations_list)
    if len({item.operation_id for item in operations}) != len(operations):
        raise ValueError("manifest operation IDs must be unique")
    sources = {item.name: item for item in registry.repositories}
    for item in operations:
        if item.repository not in sources or item.experiment not in sources[item.repository].experiments:
            raise ValueError("manifest operation repository/experiment is invalid")
        _safe_relative(item.relative_output, "operation output")
        if not item.relative_output.startswith("experiments/00_source_audit/results/fragments/"):
            raise ValueError("operation output must stay in the Experiment 00 fragment root")
        if not item.command or any(type(arg) is not str or not arg or "\n" in arg or Path(arg).is_absolute() for arg in item.command):
            raise ValueError("manifest operation argv is invalid")
        if type(item.timeout_seconds) is not int or not 0 < item.timeout_seconds <= 3600:
            raise ValueError("manifest operation timeout is invalid")
        if type(item.download_ceiling_bytes) is not int or type(item.disk_ceiling_bytes) is not int or item.download_ceiling_bytes < 0 or item.disk_ceiling_bytes < 0:
            raise ValueError("manifest operation byte ceilings are invalid")
        if any(type(value) is not int or value <= 0 for value in (item.file_ceiling_bytes, item.file_count_ceiling, item.depth_ceiling)) or item.file_ceiling_bytes > item.disk_ceiling_bytes:
            raise ValueError("manifest operation file/count/depth ceilings are invalid")
        if type(item.no_copy) is not bool or type(item.no_models) is not bool or not item.no_copy or not item.no_models:
            raise ValueError("manifest operation safety flags are invalid")
        if item.operation == "PACKAGE_RUNTIME":
            if item.operation_id != "MUJOCO_PACKAGE_SMOKE" or item.repository != "mujoco" or item.runtime_subject != "package" or item.package_name != "mujoco" or item.command != ("mujoco", "headless-one-step"):
                raise ValueError("package operation matrix is invalid")
        elif item.operation == "CHECKOUT":
            if item.runtime_subject != "source_checkout" or item.selected_path != "" or item.package_name is not None or item.command != ("fetch_reference", "--name", item.repository, "--sparse-checkout"):
                raise ValueError("checkout operation matrix is invalid")
        elif item.operation in _STATIC_FILE_KEYS:
            if item.runtime_subject != "source_checkout" or item.selected_path not in sources[item.repository].selected_paths or item.package_name is not None or item.command != (item.operation.lower(), item.selected_path) or item.download_ceiling_bytes != 0:
                raise ValueError("static operation matrix is invalid")
        else:
            raise ValueError("manifest operation kind is invalid")
    observations = tuple(RequirementObservation(**item) for item in raw["requirement_observations"])
    registry_names = {item.name for item in registry.repositories}
    if any(item.repository not in registry_names for item in observations) or len({item.repository for item in observations}) != len(observations):
        raise ValueError("requirement observations must uniquely bind registered repositories")
    selector_raw = raw["mujoco_smoke_output"]
    if not isinstance(selector_raw, Mapping) or set(selector_raw) != {"operation_id", "relative_path"}:
        raise ValueError("mujoco output selector is invalid")
    selector = OutputSelector(selector_raw["operation_id"], _safe_relative(selector_raw["relative_path"], "mujoco path"))
    if selector != OutputSelector("MUJOCO_PACKAGE_SMOKE", _FIXED_SMOKE_PATH):
        raise ValueError("mujoco output selector is not the closed fixed identity")
    matching = [item for item in operations if item.operation_id == selector.operation_id]
    if len(matching) != 1 or matching[0].runtime_subject != "package" or matching[0].relative_output != selector.relative_path:
        raise ValueError("manifest requires exactly one matching package-runtime operation")
    outputs = [_safe_relative(item.relative_output, "operation output") for item in operations]
    if len(set(outputs)) != len(outputs):
        raise ValueError("operation output paths collide")
    current = root
    for part in PurePosixPath(selector.relative_path).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("mujoco path has a symlinked parent")
    return OperationManifest(1, raw["registry_sha256"], raw["lock_sha256"], identities, operations, observations, selector)


def validate_fragment(
    raw: Mapping[str, Any],
    registry: SourceRegistry,
    lock: SourceLock,
    manifest: OperationManifest | None = None,
    relative_path: str | None = None,
) -> CompatibilityEvidence:
    item = CompatibilityEvidence.from_dict(raw)
    if item.registry_sha256 != registry.registry_sha256:
        raise ValueError("fragment registry digest mismatch")
    sources = {entry.name: entry for entry in registry.repositories}
    locked = {entry.name: entry for entry in lock.entries}
    if item.repository not in sources or locked[item.repository].commit_sha != item.commit_sha:
        raise ValueError("fragment repository/SHA does not match lock")
    source = sources[item.repository]
    lock_entry = locked[item.repository]
    if item.experiment not in source.experiments or item.selected_path not in source.selected_paths:
        raise ValueError("fragment experiment/path does not match registry")
    if item.license_status != lock_entry.license_status.value or item.license_spdx != lock_entry.license_spdx:
        raise ValueError("fragment license observation does not match lock")
    if manifest is not None:
        matches = tuple(operation for operation in manifest.operations if operation.operation_id == item.operation_id)
        if len(matches) != 1:
            raise ValueError("fragment operation ID is not exactly manifest-declared")
        operation = matches[0]
        if relative_path != operation.relative_output:
            raise ValueError("fragment path does not match its declared operation output")
        if (
            item.repository != operation.repository
            or item.experiment != operation.experiment
            or item.selected_path != operation.selected_path
            or item.operation != operation.operation
            or item.runtime_subject != operation.runtime_subject
            or item.command != operation.command
            or item.platform != operation.platform
            or item.python_requirement != operation.python_requirement
            or item.compiler_or_runtime != operation.compiler_or_runtime
            or item.package_name != operation.package_name
            or item.disk_bytes > operation.disk_ceiling_bytes
            or item.download_bytes > operation.download_ceiling_bytes
        ):
            raise ValueError("fragment facts do not match the frozen operation spec")
        if item.operation in _STATIC_FILE_KEYS:
            files = dict(item.findings)["files"]
            if len(files) > operation.file_count_ceiling or any(row["bytes"] > operation.file_ceiling_bytes for row in files):
                raise ValueError("fragment exceeds its manifest file/count ceilings")
    return item


def _json_no_duplicates(data: bytes) -> Mapping[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    raw = json.loads(data, object_pairs_hook=unique)
    if not isinstance(raw, Mapping):
        raise ValueError("fragment root must be a JSON object")
    return raw


def load_manifest_fragments(
    project_root: Path,
    manifest: OperationManifest,
    registry: SourceRegistry,
    lock: SourceLock,
) -> tuple[tuple[CompatibilityEvidence, ...], tuple[CheckoutEvidence, ...], frozenset[str]]:
    expected = {item.relative_output: item for item in manifest.operations}
    if len(expected) != len(manifest.operations):
        raise ValueError("manifest output paths collide")
    fragment_root = project_root / "experiments/00_source_audit/results/fragments"
    compatibility = []
    checkouts = []
    seen = set()
    if not fragment_root.exists():
        return (), (), frozenset()
    if fragment_root.is_symlink() or not fragment_root.is_dir():
        raise ValueError("fragment root must be a no-follow directory")
    entries = tuple(os.scandir(fragment_root))
    if len(entries) > len(expected):
        raise ValueError("fragment directory exceeds manifest-declared count")
    locked = {item.name: item for item in lock.entries}
    sources = {item.name: item for item in registry.repositories}
    for entry in sorted(entries, key=lambda item: item.name):
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            raise ValueError("fragment directory contains a nonregular entry")
        relative = f"experiments/00_source_audit/results/fragments/{entry.name}"
        operation = expected.get(relative)
        if operation is None:
            raise ValueError("fragment path is not declared by the operation manifest")
        parent_descriptor = os.open(fragment_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            descriptor = os.open(entry.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_descriptor)
        finally:
            os.close(parent_descriptor)
        try:
            value = os.fstat(descriptor)
            if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
                raise ValueError("fragment changed from an exact regular file")
            if value.st_size > 2 * 1024 * 1024:
                raise ValueError("fragment exceeds the bounded byte limit")
            data = os.read(descriptor, value.st_size + 1)
            if len(data) != value.st_size:
                raise ValueError("fragment changed during bounded read")
        finally:
            os.close(descriptor)
        raw = _json_no_duplicates(data)
        if operation.operation == "CHECKOUT":
            item = CheckoutEvidence.from_dict(raw)
            source = sources[operation.repository]
            pin = locked[operation.repository]
            existing = tuple(path for path in source.selected_paths if pin.path_statuses[path] is PathStatus.EXISTS)
            if item.repository != source.name or item.url != source.url or item.locked_sha != pin.commit_sha or item.registry_sha256 != registry.registry_sha256 or item.patterns != existing:
                raise ValueError("checkout receipt does not bind the manifest/lock")
            if item.download_bytes > operation.download_ceiling_bytes or item.disk_bytes > operation.disk_ceiling_bytes or len(item.content_hashes) > operation.file_count_ceiling:
                raise ValueError("checkout receipt exceeds manifest byte/inventory ceilings")
            if item.symlink_policy == "CONTAINED_GIT_SYMLINKS_V1" or item.schema_version != 1:
                if (
                    item.schema_version != 3
                    or operation.operation_id != "LEROBOT_CHECKOUT"
                    or operation.repository != "lerobot"
                ):
                    raise ValueError("contained-symlink authority is restricted to schema-3 LEROBOT_CHECKOUT")
                _validate_lerobot_revision_chain(project_root, item, data, registry, lock)
            checkouts.append(item)
        else:
            compatibility.append(validate_fragment(raw, registry, lock, manifest, relative))
        seen.add(operation.operation_id)
    checkout_by_repository = {item.repository: item for item in checkouts if item.outcome == "PASS"}
    for item in compatibility:
        if item.runtime_subject != "source_checkout":
            continue
        checkout = checkout_by_repository.get(item.repository)
        if checkout is None:
            raise ValueError("source operation requires a matching PASS checkout receipt")
        inventory = dict(checkout.content_hashes)
        if any(inventory.get(path) != digest for path, digest in item.content_hashes):
            raise ValueError("source operation content hashes do not match checkout inventory")
    return tuple(compatibility), tuple(checkouts), frozenset(seen)


@dataclass(frozen=True)
class CompatibilityRow:
    repository: str
    commit_sha: str
    experiment: str
    reuse_mode: str
    selected_path: str
    path_status: str
    operation: str
    platform: str
    python_requirement: str
    compiler_or_runtime: str
    smoke_command: str
    smoke_status: SmokeStatus
    classification: CompatibilityClass
    license_status: str
    license_spdx: str
    disk_bytes: int
    download_bytes: int
    blocker: str
    notes: str
    evidence_sha256: str = ""

    def csv_values(self) -> tuple[object, ...]:
        return tuple(getattr(self, key).value if isinstance(getattr(self, key), Enum) else getattr(self, key) for key in CSV_HEADER)


def consolidate_compatibility(
    registry: SourceRegistry,
    lock: SourceLock,
    fragments: Sequence[CompatibilityEvidence],
    observations: Sequence[RequirementObservation],
    manifest: OperationManifest | None = None,
    checkouts: Sequence[CheckoutEvidence] = (),
) -> tuple[CompatibilityRow, ...]:
    errors = validate_lock(registry, lock, require_complete=True)
    if errors:
        raise ValueError(f"complete source lock required: {errors[0]}")
    if manifest is not None:
        if manifest.registry_sha256 != registry.registry_sha256 or manifest.lock_sha256 != source_lock_sha256(lock):
            raise ValueError("consolidation manifest digest binding is invalid")
        if tuple(observations) != manifest.requirement_observations:
            raise ValueError("consolidation observations must come exactly from manifest")
    fragment_map: dict[tuple[str, str, str], CompatibilityEvidence] = {}
    for item in fragments:
        if manifest is None:
            raise ValueError("compatibility fragments require their frozen operation manifest")
        operation = next((entry for entry in manifest.operations if entry.operation_id == item.operation_id), None)
        if operation is None:
            raise ValueError("compatibility fragment operation is absent from manifest")
        validated = validate_fragment(item.to_dict(), registry, lock, manifest, operation.relative_output)
        key = (validated.repository, validated.experiment, validated.selected_path)
        if key in fragment_map:
            raise ValueError("duplicate/conflicting compatibility fragment")
        fragment_map[key] = validated
    observation_map = {item.repository: item for item in observations}
    if len(observation_map) != len(observations):
        raise ValueError("duplicate requirement observation")
    locked = {item.name: item for item in lock.entries}
    checkout_map = {item.repository: item for item in checkouts}
    if len(checkout_map) != len(checkouts):
        raise ValueError("duplicate checkout receipt")
    sources_by_name = {item.name: item for item in registry.repositories}
    for repository, checkout in checkout_map.items():
        source = sources_by_name.get(repository)
        pin = locked.get(repository)
        if source is None or pin is None:
            raise ValueError("checkout receipt repository is not registered")
        expected_patterns = tuple(path for path in source.selected_paths if pin.path_statuses[path] is PathStatus.EXISTS)
        if checkout.url != source.url or checkout.locked_sha != pin.commit_sha or checkout.registry_sha256 != registry.registry_sha256 or checkout.patterns != expected_patterns:
            raise ValueError("checkout receipt does not bind registry/lock")
    for item in fragments:
        if item.runtime_subject != "source_checkout":
            continue
        checkout = checkout_map.get(item.repository)
        if checkout is None or checkout.outcome != "PASS":
            raise ValueError("source compatibility requires a matching PASS checkout")
        inventory = dict(checkout.content_hashes)
        if any(inventory.get(path) != digest for path, digest in item.content_hashes):
            raise ValueError("source compatibility hashes are stale against checkout")
    rows = []
    for source in registry.repositories:
        pin = locked[source.name]
        for experiment in source.experiments:
            for selected_path in source.selected_paths or ("",):
                status = pin.path_statuses.get(selected_path, PathStatus.EXISTS)
                item = fragment_map.get((source.name, experiment, selected_path))
                observation = observation_map.get(source.name)
                classification = CompatibilityClass.NOT_EVALUATED
                if status is PathStatus.MISSING:
                    classification = CompatibilityClass.PATH_CHANGED
                elif pin.license_status is not LicenseStatus.DISCOVERED and source.mode is not ReuseMode.DEFERRED:
                    classification = CompatibilityClass.LICENSE_REVIEW_REQUIRED
                elif item is not None and item.operation == "PACKAGE_RUNTIME" and item.exit_status == 0 and source.mode not in {ReuseMode.REMOTE_ONLY, ReuseMode.DEFERRED}:
                    classification = CompatibilityClass.WORKS_LOCAL_M2
                elif item is not None and item.exit_status == 0 and checkout_map.get(source.name) is not None and checkout_map[source.name].outcome == "PASS" and source.mode in {ReuseMode.SPARSE_REFERENCE, ReuseMode.PAPER_AND_CODE_REFERENCE}:
                    classification = CompatibilityClass.SOURCE_REFERENCE_ONLY
                elif observation is not None and observation.kind == "REMOTE_GPU":
                    classification = CompatibilityClass.REMOTE_GPU_REQUIRED
                elif observation is not None and observation.kind == "REMOTE_LINUX":
                    classification = CompatibilityClass.REMOTE_LINUX_REQUIRED
                elif observation is not None and observation.kind == "ARCHIVED":
                    classification = CompatibilityClass.STALE_OR_ARCHIVED
                smoke = SmokeStatus.NOT_RUN if item is None else (SmokeStatus.PASS if item.exit_status == 0 else SmokeStatus.BLOCKED if item.exit_status is None else SmokeStatus.FAIL)
                rows.append(CompatibilityRow(
                    source.name, pin.commit_sha or "", experiment, source.mode.value,
                    selected_path, status.value, item.operation if item else "",
                    item.platform if item else "", item.python_requirement if item else "",
                    item.compiler_or_runtime if item else "", " ".join(item.command) if item else "",
                    smoke, classification, pin.license_status.value, pin.license_spdx or "",
                    item.disk_bytes if item else 0, item.download_bytes if item else 0,
                    item.blocker or "" if item else "", item.notes if item else "",
                    item.evidence_sha256 if item else "",
                ))
    return tuple(sorted(rows, key=lambda row: (row.repository, row.experiment, row.selected_path)))


def _atomic_bytes(path: Path, data: bytes, *, check: bool) -> str:
    digest = hashlib.sha256(data).hexdigest()
    if check:
        if not path.is_file() or path.read_bytes() != data:
            raise ValueError(f"generated output is stale or missing: {path}")
        return digest
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial-{os.urandom(8).hex()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(descriptor, data[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    parent = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return digest


def write_compatibility_outputs(
    root: Path,
    registry: SourceRegistry,
    lock: SourceLock,
    rows: Sequence[CompatibilityRow],
    *,
    check: bool = False,
    manifest: OperationManifest | None = None,
    seen_operation_ids: frozenset[str] = frozenset(),
    checkouts: Sequence[CheckoutEvidence] = (),
    passed_operation_ids: frozenset[str] = frozenset(),
) -> dict[str, str]:
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    writer.writerows(row.csv_values() for row in rows)
    licenses = ["# Source licenses", "", "Generated provenance; not legal advice.", "", "| repository@SHA | reuse mode | root/asset license evidence | allowed action | attribution requirement | decision/blocker | review date |", "|---|---|---|---|---|---|---|"]
    locked = {item.name: item for item in lock.entries}
    for source in registry.repositories:
        pin = locked[source.name]
        action = {ReuseMode.DIRECT_DEPENDENCY: "INSTALL", ReuseMode.ADAPTER_DEPENDENCY: "INSTALL", ReuseMode.SPARSE_REFERENCE: "SPARSE_STUDY"}.get(source.mode, "NO_COPY" if source.mode is ReuseMode.PAPER_AND_CODE_REFERENCE else "DEFER")
        attribution = "RETAIN_LICENSE" if pin.license_status is LicenseStatus.DISCOVERED else "REVIEW_REQUIRED"
        blocker = "" if pin.license_status is LicenseStatus.DISCOVERED else "LICENSE_REVIEW_REQUIRED"
        licenses.append(f"| {source.name}@{pin.commit_sha} | {source.mode.value} | {pin.license_spdx or pin.license_status.value} | {action} | {attribution} | {blocker} | {registry.verified_at} |")
    source_map = ["# Source map", "", "| experiment/local component | repository | selected path | intended use | copy/adaptation restriction | local fallback | attribution record |", "|---|---|---|---|---|---|---|"]
    for source in registry.repositories:
        for experiment in source.experiments:
            for selected in source.selected_paths or ("",):
                restriction = "STUDY_ONLY" if source.mode in {ReuseMode.SPARSE_REFERENCE, ReuseMode.PAPER_AND_CODE_REFERENCE} else "LOCKED_DEPENDENCY" if source.mode in {ReuseMode.DIRECT_DEPENDENCY, ReuseMode.ADAPTER_DEPENDENCY} else "NO_LOCAL_COPY"
                source_map.append(f"| {experiment} | {source.name} | {selected} | {source.use} | {restriction} | project-local baseline | licenses.md#{source.name} |")
    labels = {CompatibilityClass.WORKS_LOCAL_M2: "LOCALLY_REPRODUCED_M2", CompatibilityClass.WORKS_LOCAL_CPU_WITH_PATCH: "LOCALLY_INTEGRATED", CompatibilityClass.REMOTE_GPU_REQUIRED: "REMOTELY_REPRODUCED_GPU", CompatibilityClass.SOURCE_REFERENCE_ONLY: "PRODUCTION_SHAPED_REFERENCE"}
    maturity = ["# Maturity ledger", "", "| project_or_component | evidence_label | evidence_source | supported_embodiment_or_task | license | compute_requirements | local_reproduction_status | known_failure_modes | role_in_program | hardware_validation_status |", "|---|---|---|---|---|---|---|---|---|---|"]
    observation_hashes = {
        item.repository: item.statement_sha256
        for item in (manifest.requirement_observations if manifest else ())
    }
    unitree_rows = {"unitree_rl_mjlab", "unitree_mujoco", "unitree_sdk2", "unifolm_vla", "unifolm_wma"}
    for source in registry.repositories:
        classes = [row.classification for row in rows if row.repository == source.name]
        label = next(
            (labels[item] for item in (
                CompatibilityClass.WORKS_LOCAL_M2,
                CompatibilityClass.WORKS_LOCAL_CPU_WITH_PATCH,
                CompatibilityClass.REMOTE_GPU_REQUIRED,
                CompatibilityClass.SOURCE_REFERENCE_ONLY,
            ) if item in classes),
            "UNVERIFIED",
        )
        pin = locked[source.name]
        source_rows = [row for row in rows if row.repository == source.name]
        evidence_hashes = sorted({row.evidence_sha256 for row in source_rows if row.evidence_sha256})
        evidence_source = ",".join(f"sha256:{digest}" for digest in evidence_hashes) or (f"sha256:{observation_hashes[source.name]}" if source.name in observation_hashes else "NONE")
        local_status = "LOCALLY_REPRODUCED_M2" if label == "LOCALLY_REPRODUCED_M2" else "NOT_REPRODUCED"
        failures = sorted({row.blocker for row in source_rows if row.blocker})
        known_failures = "; ".join(failures) or source.caveat or "NOT_OBSERVED"
        hardware = "NOT_VALIDATED" if source.name in unitree_rows else "NOT_APPLICABLE"
        maturity.append(f"| {source.name} | {label} | {evidence_source} | {','.join(source.experiments)} | {pin.license_spdx or pin.license_status.value} | bounded by {source.mode.value} | {local_status} | {known_failures} | {source.use} | {hardware} |")
    expected_ids = frozenset(item.operation_id for item in manifest.operations) if manifest else frozenset()
    missing_ids = sorted(expected_ids - seen_operation_ids)
    nonpass_ids = sorted((expected_ids & seen_operation_ids) - passed_operation_ids)
    package_rows = [row for row in rows if row.repository == "mujoco" and row.operation == "PACKAGE_RUNTIME"]
    package_pass = len(package_rows) == 1 and package_rows[0].smoke_status is SmokeStatus.PASS and package_rows[0].classification is CompatibilityClass.WORKS_LOCAL_M2
    evidence_failures = sorted({row.blocker for row in rows if row.smoke_status in {SmokeStatus.FAIL, SmokeStatus.BLOCKED} and row.blocker})
    checkout_failures = sorted(item.blocker or "checkout failed" for item in checkouts if item.outcome != "PASS")
    gate_complete = bool(manifest) and not missing_ids and not nonpass_ids and package_pass and not evidence_failures and not checkout_failures
    result_label = "LOCALLY_REPRODUCED_M2" if gate_complete else "UNVERIFIED"
    result_local = "LOCALLY_REPRODUCED_M2" if gate_complete else "NOT_REPRODUCED"
    result_sources = ",".join(f"operation:{item}" for item in sorted(seen_operation_ids)) or "NONE"
    result_failure = "NONE" if gate_complete else "; ".join([*(f"missing:{item}" for item in missing_ids), *(f"nonpass:{item}" for item in nonpass_ids), *evidence_failures, *checkout_failures]) or "INCOMPLETE_EVIDENCE"
    maturity.append(f"| Experiment 00 source compatibility | {result_label} | {result_sources} | source audit | project | local CPU | {result_local} | {result_failure} | source gate | NOT_APPLICABLE |")
    results = (
        "# Experiment 00 results\n\n"
        "comparative_implementation_time_claim: INCONCLUSIVE\n\n"
        f"operational_gate: {'PASS' if gate_complete else 'BLOCKED'}\n\n"
        f"registry_sha256: {registry.registry_sha256}\n\n"
        f"lock_sha256: {source_lock_sha256(lock)}\n\n"
        f"expected_operation_ids: {','.join(sorted(expected_ids)) or 'NONE'}\n\n"
        f"seen_operation_ids: {','.join(sorted(seen_operation_ids)) or 'NONE'}\n\n"
        f"missing_operation_ids: {','.join(missing_ids) or 'NONE'}\n\n"
        f"nonpass_operation_ids: {','.join(nonpass_ids) or 'NONE'}\n\n"
        f"mujoco_package_smoke: {'PASS' if package_pass else 'NOT_PROVEN'}\n\n"
        f"blockers: {result_failure}\n"
    )
    interface = (
        "# Interface findings\n\n"
        f"gate_status: {'PASS' if gate_complete else 'BLOCKED'}\n\n"
        "promoted_claims: only exact manifest-bound PASS evidence\n\n"
        "cannot_claim: production readiness, physical validation, or comparative adoption speed\n\n"
        f"blockers: {result_failure}\n"
    )
    outputs = {
        "experiments/00_source_audit/results/compatibility.csv": csv_buffer.getvalue().encode(),
        "references/licenses.md": ("\n".join(licenses) + "\n").encode(),
        "docs/SOURCE_MAP.md": ("\n".join(source_map) + "\n").encode(),
        "docs/MATURITY_LEDGER.md": ("\n".join(maturity) + "\n").encode(),
        "experiments/00_source_audit/RESULTS.md": results.encode(),
        "experiments/00_source_audit/INTERFACE_FINDINGS.md": interface.encode(),
    }
    return {relative: _atomic_bytes(root / relative, data, check=check) for relative, data in outputs.items()}
