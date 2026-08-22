#!/usr/bin/env python3
"""Render the deterministic, Git-bound P3 completion report without live work."""

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
import socket
import subprocess
from typing import Callable, Mapping, Sequence

import yaml

from reflect._p2_report_io import (
    HARDENED_GIT_PREFIX,
    _open_directory_path_no_follow,
    forbidden_tracked_paths,
    hardened_environment,
)
from reflect.p2_report import StrictYamlLoader


ROOT = Path(__file__).resolve().parents[1]
SECTION_HEADINGS = (
    "Executive result", "Environment", "Commands", "Tests", "Results",
    "Public-source use", "Interface findings", "Blockers",
    "Highest-value next action", "Safety",
)
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SMOKE_PATH = "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json"
_FIXED_ARTIFACTS = (
    "references/repos.yaml",
    "references/repos.lock.yaml",
    "references/p2-live-attempts.yaml",
    "experiments/00_source_audit/configs/operation-manifest.yaml",
    "experiments/00_source_audit/results/compatibility.csv",
    "references/licenses.md",
    "docs/SOURCE_MAP.md",
    "docs/MATURITY_LEDGER.md",
    "experiments/00_source_audit/RESULTS.md",
    "experiments/00_source_audit/INTERFACE_FINDINGS.md",
    "docs/ASSUMPTIONS.md",
    "docs/RUN_MANIFEST.yaml",
)
_OPERATION_KEYS = {
    "operation_id", "repository", "operation", "runtime_subject", "experiment",
    "selected_path", "command", "relative_output", "platform", "python_requirement",
    "compiler_or_runtime", "timeout_seconds", "download_ceiling_bytes",
    "disk_ceiling_bytes", "no_copy", "no_models", "package_name",
    "file_ceiling_bytes", "file_count_ceiling", "depth_ceiling",
}
_ALLOWED_GIT_SHAPES = {
    ("rev-parse", "HEAD"),
    ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
}


@dataclass(frozen=True)
class GitArtifact:
    path: str
    blob_id: str
    content: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class P3Snapshot:
    evidence_sha: str
    artifacts: Mapping[str, GitArtifact]
    smoke_path: str
    package_version: str
    platform: str
    runtime: str


def _checked_git_shape(arguments: tuple[str, ...]) -> None:
    if arguments in _ALLOWED_GIT_SHAPES:
        return
    if len(arguments) == 3 and arguments[:2] == ("rev-parse", "--verify") and arguments[2].endswith("^{commit}"):
        return
    if len(arguments) == 5 and arguments[:4] == ("ls-tree", "-r", "-z", "--name-only"):
        return
    if len(arguments) == 5 and arguments[:2] == ("ls-tree", "-z") and arguments[3] == "--":
        return
    if len(arguments) == 3 and arguments[:2] == ("cat-file", "blob") and _SHA40.fullmatch(arguments[2]):
        return
    raise RuntimeError(f"P3 reporter rejected non-allowlisted subprocess: {arguments!r}")


def _git(root: Path, *arguments: str) -> bytes:
    vector = tuple(arguments)
    _checked_git_shape(vector)
    environment = hardened_environment({"GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0"})
    completed = subprocess.run(
        [HARDENED_GIT_PREFIX[0], "--no-replace-objects", *HARDENED_GIT_PREFIX[1:], *vector],
        cwd=root, env=environment, capture_output=True, check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"P3 reporter Git read failed: {' '.join(vector)}: {completed.stderr.decode('utf-8', 'replace').strip()}")
    return completed.stdout


def _validate_head(root: Path, evidence_sha: str, *, allowed_untracked: frozenset[str] = frozenset()) -> None:
    if _SHA40.fullmatch(evidence_sha) is None:
        raise ValueError("--evidence-base-sha must be lowercase 40-hex")
    resolved = _git(root, "rev-parse", "--verify", f"{evidence_sha}^{{commit}}").decode("ascii").strip()
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if resolved != evidence_sha or head != evidence_sha:
        raise RuntimeError("evidence SHA must equal exact current HEAD")
    status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    allowed = {b"?? " + item.encode() for item in allowed_untracked}
    unexpected = [item for item in status.split(b"\0") if item and item not in allowed]
    if unexpected:
        raise RuntimeError("evidence worktree must be clean")


def _strict_yaml(content: bytes, label: str) -> dict[str, object]:
    try:
        raw = yaml.load(content.decode("utf-8", "strict"), Loader=StrictYamlLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} is not duplicate-free UTF-8 YAML") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a mapping")
    return raw


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate JSON key {key}")
            result[key] = value
        return result
    try:
        raw = json.loads(content.decode("utf-8", "strict"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a JSON object")
    return raw


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _lock_digest(lock: dict[str, object]) -> str:
    entries = lock.get("entries")
    if not isinstance(entries, list):
        raise ValueError("P2 lock entries must be a sequence")
    normalized = []
    keys = {
        "name", "url", "default_branch", "commit_sha", "retrieved_at",
        "metadata_evidence", "license_spdx", "license_status", "license_evidence_url",
        "path_statuses", "path_evidence_urls", "metadata_status",
    }
    for item in entries:
        if not isinstance(item, dict) or set(item) != keys:
            raise ValueError("P2 lock entry schema is incomplete")
        normalized.append({
            **item,
            "metadata_evidence": dict(sorted(item["metadata_evidence"].items())),
            "path_statuses": dict(sorted(item["path_statuses"].items())),
            "path_evidence_urls": dict(sorted(item["path_evidence_urls"].items())),
        })
    return hashlib.sha256(_canonical_bytes({
        "registry_sha256": lock.get("registry_sha256"),
        "generated_at": lock.get("generated_at"), "entries": normalized,
    })).hexdigest()


def _git_artifact(root: Path, commit: str, path: str) -> GitArtifact:
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("artifact path is not normalized beneath the repository")
    listing = _git(root, "ls-tree", "-z", commit, "--", path)
    rows = [row for row in listing.split(b"\0") if row]
    if len(rows) != 1 or b"\t" not in rows[0]:
        raise ValueError(f"required P3 artifact missing: {path}")
    metadata, listed = rows[0].split(b"\t", 1)
    fields = metadata.split()
    if listed.decode("utf-8", "strict") != path or len(fields) != 3 or fields[0] not in {b"100644", b"100755"} or fields[1] != b"blob":
        raise ValueError(f"required P3 artifact is not a regular Git blob: {path}")
    blob_id = fields[2].decode("ascii")
    content = _git(root, "cat-file", "blob", blob_id)
    if len(content) > 8 * 1024 * 1024:
        raise ValueError(f"required P3 artifact exceeds bounded size: {path}")
    return GitArtifact(path, blob_id, content)


def _validate_manifest(manifest: dict[str, object]) -> tuple[str, dict[str, object]]:
    expected = {"schema_version", "registry_sha256", "lock_sha256", "repositories", "operations", "requirement_observations", "mujoco_smoke_output"}
    if set(manifest) != expected or manifest.get("schema_version") != 1:
        raise ValueError("P3 operation manifest schema is invalid")
    selector = manifest.get("mujoco_smoke_output")
    if not isinstance(selector, dict) or set(selector) != {"operation_id", "relative_path"}:
        raise ValueError("P3 smoke selector schema is invalid")
    if selector != {"operation_id": "MUJOCO_PACKAGE_SMOKE", "relative_path": _SMOKE_PATH}:
        raise ValueError("P3 smoke selector must use the fixed path")
    operations = manifest.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("P3 operation manifest has no operations")
    matches = []
    outputs = []
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) != _OPERATION_KEYS:
            raise ValueError("P3 operation manifest operation schema/future identity is invalid")
        outputs.append(operation["relative_output"])
        if operation["operation_id"] == "MUJOCO_PACKAGE_SMOKE":
            matches.append(operation)
    if len(matches) != 1 or len(outputs) != len(set(outputs)):
        raise ValueError("P3 operation identity is duplicated or collides")
    match = matches[0]
    if match["runtime_subject"] != "package" or match["operation"] != "PACKAGE_RUNTIME" or match["relative_output"] != _SMOKE_PATH:
        raise ValueError("P3 smoke operation does not match its selector")
    return _SMOKE_PATH, match


def _validate_snapshot(artifacts: dict[str, GitArtifact], smoke_path: str, operation: dict[str, object]) -> tuple[str, str, str]:
    registry = _strict_yaml(artifacts["references/repos.yaml"].content, "P2 registry")
    lock = _strict_yaml(artifacts["references/repos.lock.yaml"].content, "P2 lock")
    attempts = _strict_yaml(artifacts["references/p2-live-attempts.yaml"].content, "P2 attempts")
    manifest = _strict_yaml(artifacts["experiments/00_source_audit/configs/operation-manifest.yaml"].content, "P3 operation manifest")
    repositories = registry.get("repositories")
    entries = lock.get("entries")
    identities = manifest.get("repositories")
    if not isinstance(repositories, list) or not isinstance(entries, list) or not isinstance(identities, list) or len(repositories) != len(entries) or len(entries) != len(identities) or len(entries) != 45:
        raise ValueError("P2/P3 inventory must contain exactly 45 aligned repositories")
    registry_sha = artifacts["references/repos.yaml"].sha256
    if lock.get("registry_sha256") != registry_sha or manifest.get("registry_sha256") != registry_sha or attempts.get("registry_sha256") != registry_sha:
        raise ValueError("P2/P3 registry hash binding is invalid")
    if manifest.get("lock_sha256") != _lock_digest(lock):
        raise ValueError("P3 manifest lock hash binding is invalid")
    for source, pin, identity in zip(repositories, entries, identities, strict=True):
        if not isinstance(source, dict) or not isinstance(pin, dict) or not isinstance(identity, dict):
            raise ValueError("P2/P3 repository identity row is invalid")
        expected_paths = [{"path": key, "status": value} for key, value in sorted(pin["path_statuses"].items())]
        if source.get("name") != pin.get("name") or identity != {"repository": pin.get("name"), "commit_sha": pin.get("commit_sha"), "paths": expected_paths}:
            raise ValueError("P2/P3 repository identities are not aligned")
    smoke = _strict_json(artifacts[smoke_path].content, "P3 MuJoCo smoke")
    evidence_hash = smoke.get("evidence_sha256")
    unhashed = {key: value for key, value in smoke.items() if key != "evidence_sha256"}
    if not isinstance(evidence_hash, str) or evidence_hash != hashlib.sha256(_canonical_bytes(unhashed)).hexdigest():
        raise ValueError("P3 smoke evidence hash is invalid")
    if smoke.get("operation_id") != "MUJOCO_PACKAGE_SMOKE" or smoke.get("runtime_subject") != "package" or smoke.get("package_name") != "mujoco" or smoke.get("package_version") != "3.12.0":
        raise ValueError("P3 smoke package identity is invalid")
    compatibility = artifacts["experiments/00_source_audit/results/compatibility.csv"].content.decode("utf-8", "strict").splitlines()
    if len(compatibility) != 280 or not compatibility[0].startswith("repository,commit_sha,experiment,"):
        raise ValueError("P3 compatibility inventory must contain exact 279 rows")
    maturity = artifacts["docs/MATURITY_LEDGER.md"].content.decode("utf-8", "strict")
    if maturity.count("| project_or_component | evidence_label |") != 1 or sum(line.startswith("| ") for line in maturity.splitlines()) != 47:
        raise ValueError("P3 maturity ledger is incomplete")
    results = artifacts["experiments/00_source_audit/RESULTS.md"].content.decode("utf-8", "strict")
    interfaces = artifacts["experiments/00_source_audit/INTERFACE_FINDINGS.md"].content.decode("utf-8", "strict")
    if "operational_gate: PASS" not in results or "comparative_implementation_time_claim: INCONCLUSIVE" not in results or "gate_status: PASS" not in interfaces:
        raise ValueError("P3 result/interface gate is not complete")
    run_manifest = _strict_yaml(artifacts["docs/RUN_MANIFEST.yaml"].content, "run manifest")
    safety = run_manifest.get("safety")
    stages = run_manifest.get("stages")
    if not isinstance(safety, dict) or safety.get("physical_deployment_allowed") is not False or safety.get("remote_enabled") is not False or not isinstance(stages, dict) or stages.get("p3") != "complete":
        raise ValueError("P3 run-manifest safety/stage gate is invalid")
    if not artifacts["references/licenses.md"].content.startswith(b"# Source licenses") or not artifacts["docs/SOURCE_MAP.md"].content.startswith(b"# Source map") or not artifacts["docs/ASSUMPTIONS.md"].content.startswith(b"# Assumptions"):
        raise ValueError("P3 provenance documents are incomplete")
    return str(smoke["package_version"]), str(operation["platform"]), str(operation["compiler_or_runtime"])


def _read_snapshot(root: Path, evidence_sha: str) -> P3Snapshot:
    manifest_artifact = _git_artifact(root, evidence_sha, "experiments/00_source_audit/configs/operation-manifest.yaml")
    manifest = _strict_yaml(manifest_artifact.content, "P3 operation manifest")
    smoke_path, operation = _validate_manifest(manifest)
    paths = (*_FIXED_ARTIFACTS, smoke_path)
    if len(paths) != len(set(paths)):
        raise ValueError("P3 artifact inventory contains a path collision")
    artifacts = {path: _git_artifact(root, evidence_sha, path) for path in paths}
    tracked = tuple(item.decode("utf-8", "strict") for item in _git(root, "ls-tree", "-r", "-z", "--name-only", evidence_sha).split(b"\0") if item)
    forbidden = forbidden_tracked_paths(tuple(path for path in tracked if path not in artifacts))
    if forbidden:
        raise ValueError(f"P3 evidence commit contains forbidden tracked paths: {forbidden}")
    package_version, platform_name, runtime = _validate_snapshot(artifacts, smoke_path, operation)
    return P3Snapshot(evidence_sha, artifacts, smoke_path, package_version, platform_name, runtime)


def _render(snapshot: P3Snapshot) -> str:
    ledger = "\n".join(
        f"- `{path}`: Git blob `{artifact.blob_id}`, SHA-256 `{artifact.sha256}`"
        for path, artifact in sorted(snapshot.artifacts.items())
    )
    return f"""# P3 Run Report

## Executive result

The bounded Experiment 00 source-compatibility gate passed locally. No comparative implementation-time claim was made.

## Environment

- Implementation/evidence-base Git SHA: `{snapshot.evidence_sha}`
- Workspace: repository root
- Branch: `integration/autonomous-run`
- Platform contract: `{snapshot.platform}`
- Runtime contract: `{snapshot.runtime}`
- MuJoCo package: `{snapshot.package_version}`

## Commands

Exact report command: `python scripts/write_p3_report.py --evidence-base-sha {snapshot.evidence_sha}`. The reporter executed only fixed local Git identity/blob reads; it ran no source operation, network request, or installation.

## Tests

P3 evidence validation: PASS. The report deterministically reconstructed the complete bounded artifact inventory at the evidence SHA.

## Results

{ledger}

Selected runtime artifact: `{snapshot.smoke_path}`. Operational gate: PASS. Comparative implementation-time claim: INCONCLUSIVE.

## Public-source use

The registry and lock bind 45 public sources. Only the locked MuJoCo 3.12.0 package runtime is promoted as locally reproduced; sparse source inspections remain study evidence with recorded license provenance.

## Interface findings

Promote only the manifest-bound package/runtime seam and deterministic compatibility outputs. Static source inspection does not establish runtime compatibility.

## Blockers

NONE for opening bounded local experiment lanes. Physical deployment, remote execution, and comparative adoption-speed claims remain outside this gate.

## Highest-value next action

Run the first preregistered Experiment 01 local policy-control pilot against the frozen P3 interfaces.

## Safety

- No physical motor messages were sent.
- No non-loopback deployment connection or public inference server was used.
- No secrets or checkout/model artifacts are tracked.
- No unreviewed large model was downloaded.
- Physical deployment and remote execution remain disabled.
"""


def validate_rendered_report(content: str, evidence_sha: str) -> None:
    if type(content) is not str or _SHA40.fullmatch(evidence_sha) is None:
        raise ValueError("P3 report validation requires text and a lowercase evidence SHA")
    headings = tuple(line.removeprefix("## ") for line in content.splitlines() if line.startswith("## "))
    if headings != SECTION_HEADINGS:
        raise ValueError("P3 report has unknown, missing, or repeated Section-35 headings")
    expected = f"- Implementation/evidence-base Git SHA: `{evidence_sha}`"
    provenance = [line for line in content.splitlines() if "Git SHA:" in line]
    if provenance != [expected] or content.count("Implementation/evidence-base Git SHA") != 1:
        raise ValueError("P3 report has unknown or repeated provenance fields")


@contextmanager
def _network_denied():
    original = (socket.socket, socket.create_connection, socket.getaddrinfo, socket.gethostbyname)
    def forbidden(*args: object, **kwargs: object):
        raise RuntimeError("network and DNS are disabled during P3 report publication")
    socket.socket = forbidden  # type: ignore[assignment]
    socket.create_connection = forbidden  # type: ignore[assignment]
    socket.getaddrinfo = forbidden  # type: ignore[assignment]
    socket.gethostbyname = forbidden  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket, socket.create_connection, socket.getaddrinfo, socket.gethostbyname = original  # type: ignore[assignment]


def _atomic_write_report(root: Path, content: str, final_check: Callable[[str], None] | None = None) -> None:
    root_fd = _open_directory_path_no_follow(root)
    temporary = f".RUN_REPORT.md.p3-{secrets.token_hex(12)}"
    descriptor = -1
    identity: tuple[int, int] | None = None
    replaced = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=root_fd)
        value = os.fstat(descriptor)
        identity = (value.st_dev, value.st_ino)
        os.fchmod(descriptor, 0o600)
        payload = content.encode("utf-8")
        offset = 0
        while offset < len(payload):
            count = os.write(descriptor, payload[offset:])
            if count <= 0:
                raise OSError("short P3 report write")
            offset += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if final_check is not None:
            final_check(temporary)
        os.replace(temporary, "RUN_REPORT.md", src_dir_fd=root_fd, dst_dir_fd=root_fd)
        replaced = True
        os.fsync(root_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not replaced and identity is not None:
            try:
                current = os.stat(temporary, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                current = None
            if current is not None and (current.st_dev, current.st_ino) == identity:
                os.unlink(temporary, dir_fd=root_fd)
        os.close(root_fd)


def main(argv: Sequence[str] | None = None, *, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-base-sha", required=True)
    arguments = parser.parse_args(argv)
    project_root = Path(root) if root is not None else ROOT
    with _network_denied():
        _validate_head(project_root, arguments.evidence_base_sha)
        snapshot = _read_snapshot(project_root, arguments.evidence_base_sha)
        report = _render(snapshot)
        validate_rendered_report(report, arguments.evidence_base_sha)
        _validate_head(project_root, arguments.evidence_base_sha)
        _atomic_write_report(
            project_root,
            report,
            lambda temporary: _validate_head(
                project_root, arguments.evidence_base_sha,
                allowed_untracked=frozenset({temporary}),
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
