"""Immutable source-compatibility evidence and deterministic consolidation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import csv
from dataclasses import dataclass
from enum import Enum
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any

import yaml

from reflect.source_evidence import canonical_json_bytes, canonical_sha256
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
_EVIDENCE_KEYS = {
    "schema_version", "evidence_type", "registry_sha256", "repository",
    "commit_sha", "experiment", "selected_path", "operation", "platform",
    "python_requirement", "compiler_or_runtime", "command", "exit_status",
    "disk_bytes", "download_bytes", "license_status", "license_spdx", "blocker",
    "notes", "runtime_subject", "package_name", "package_version",
    "package_artifact_sha256", "patch_artifact_sha256", "findings",
    "content_hashes", "evidence_sha256",
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
        for field in ("repository", "experiment", "selected_path", "operation", "platform", "python_requirement", "compiler_or_runtime", "notes"):
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
            if not self.package_name or not self.package_version or self.package_artifact_sha256 is None:
                raise ValueError("package runtime requires package identity and artifact hash")
            _sha(self.package_artifact_sha256, "package_artifact_sha256", 64)
        elif any(value is not None for value in (self.package_name, self.package_version, self.package_artifact_sha256)):
            raise ValueError("source checkout cannot claim package identity")
        if self.patch_artifact_sha256 is not None:
            _sha(self.patch_artifact_sha256, "patch_artifact_sha256", 64)
        for path, digest in self.content_hashes:
            _string(path, "content path")
            _sha(digest, "content hash", 64)
        if include_hash:
            _sha(self.evidence_sha256, "evidence_sha256", 64)
            if self.evidence_sha256 != canonical_sha256(self.to_dict(False)):
                raise ValueError("compatibility evidence hash mismatch")

    def to_dict(self, include_hash: bool = True) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version, "evidence_type": self.evidence_type,
            "registry_sha256": self.registry_sha256, "repository": self.repository,
            "commit_sha": self.commit_sha, "experiment": self.experiment,
            "selected_path": self.selected_path, "operation": self.operation,
            "platform": self.platform, "python_requirement": self.python_requirement,
            "compiler_or_runtime": self.compiler_or_runtime, "command": list(self.command),
            "exit_status": self.exit_status, "disk_bytes": self.disk_bytes,
            "download_bytes": self.download_bytes, "license_status": self.license_status,
            "license_spdx": self.license_spdx, "blocker": self.blocker, "notes": self.notes,
            "runtime_subject": self.runtime_subject, "package_name": self.package_name,
            "package_version": self.package_version,
            "package_artifact_sha256": self.package_artifact_sha256,
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


@dataclass(frozen=True)
class ManifestOperation:
    operation_id: str
    repository: str
    operation: str
    runtime_subject: str
    relative_output: str


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


def load_operation_manifest(path: Path, registry: SourceRegistry, lock: SourceLock, root: Path) -> OperationManifest:
    raw = yaml.safe_load(path.read_text())
    required = {"schema_version", "registry_sha256", "lock_sha256", "repositories", "operations", "requirement_observations", "mujoco_smoke_output"}
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise ValueError("operation manifest has missing or extra keys")
    if raw["schema_version"] != 1 or raw["registry_sha256"] != registry.registry_sha256 or raw["lock_sha256"] != source_lock_sha256(lock):
        raise ValueError("operation manifest digest binding is invalid")
    errors = validate_lock(registry, lock, require_complete=True)
    if errors:
        raise ValueError(f"operation manifest requires complete lock: {errors[0]}")
    identities = tuple(RepositoryIdentity(**item) for item in raw["repositories"])
    expected = tuple((item.name, item.commit_sha) for item in lock.entries)
    if tuple((item.repository, item.commit_sha) for item in identities) != expected:
        raise ValueError("operation manifest must cover every locked repository in order")
    operations = tuple(ManifestOperation(**item) for item in raw["operations"])
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
    destination = root / selector.relative_path
    current = root
    for part in PurePosixPath(selector.relative_path).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("mujoco path has a symlinked parent")
    return OperationManifest(1, raw["registry_sha256"], raw["lock_sha256"], identities, operations, observations, selector)


def validate_fragment(raw: Mapping[str, Any], registry: SourceRegistry, lock: SourceLock) -> CompatibilityEvidence:
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
    return item


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

    def csv_values(self) -> tuple[object, ...]:
        return tuple(getattr(self, key).value if isinstance(getattr(self, key), Enum) else getattr(self, key) for key in CSV_HEADER)


def consolidate_compatibility(
    registry: SourceRegistry,
    lock: SourceLock,
    fragments: Sequence[CompatibilityEvidence],
    observations: Sequence[RequirementObservation],
) -> tuple[CompatibilityRow, ...]:
    errors = validate_lock(registry, lock, require_complete=True)
    if errors:
        raise ValueError(f"complete source lock required: {errors[0]}")
    fragment_map: dict[tuple[str, str, str], CompatibilityEvidence] = {}
    for item in fragments:
        validated = validate_fragment(item.to_dict(), registry, lock)
        key = (validated.repository, validated.experiment, validated.selected_path)
        if key in fragment_map:
            raise ValueError("duplicate/conflicting compatibility fragment")
        fragment_map[key] = validated
    observation_map = {item.repository: item for item in observations}
    if len(observation_map) != len(observations):
        raise ValueError("duplicate requirement observation")
    locked = {item.name: item for item in lock.entries}
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
                elif item is not None and item.exit_status == 0 and item.patch_artifact_sha256 and source.mode not in {ReuseMode.REMOTE_ONLY, ReuseMode.DEFERRED}:
                    classification = CompatibilityClass.WORKS_LOCAL_CPU_WITH_PATCH
                elif item is not None and item.exit_status == 0 and source.mode in {ReuseMode.SPARSE_REFERENCE, ReuseMode.PAPER_AND_CODE_REFERENCE}:
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
    maturity = ["# Maturity ledger", "", "| project/component | evidence label | evidence source | supported embodiment/task | license | compute requirements | local reproduction status | hardware validation status | known failure modes | role in this program |", "|---|---|---|---|---|---|---|---|---|---|"]
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
        maturity.append(f"| {source.name} | {label} | compatibility.csv | {','.join(source.experiments)} | {pin.license_spdx or pin.license_status.value} | bounded by reuse mode | {'REPRODUCED' if label == 'LOCALLY_REPRODUCED_M2' else 'NOT_REPRODUCED'} | NOT_VALIDATED | {source.caveat or 'not yet observed'} | {source.use} |")
    maturity.append("| Experiment 00 source compatibility | LOCALLY_REPRODUCED_M2 | compatibility.csv | source audit | project | local CPU | REPRODUCED | NOT_APPLICABLE | incomplete evidence blocks gate | source gate |")
    results = "# Experiment 00 results\n\nGenerated from immutable compatibility fragments.\n"
    interface = "# Interface findings\n\nOnly bounded, evidence-backed source reuse is promoted.\n"
    outputs = {
        "experiments/00_source_audit/results/compatibility.csv": csv_buffer.getvalue().encode(),
        "references/licenses.md": ("\n".join(licenses) + "\n").encode(),
        "docs/SOURCE_MAP.md": ("\n".join(source_map) + "\n").encode(),
        "docs/MATURITY_LEDGER.md": ("\n".join(maturity) + "\n").encode(),
        "experiments/00_source_audit/RESULTS.md": results.encode(),
        "experiments/00_source_audit/INTERFACE_FINDINGS.md": interface.encode(),
    }
    return {relative: _atomic_bytes(root / relative, data, check=check) for relative, data in outputs.items()}
