"""Fail-closed binding to completed Experiment 00 evidence."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Mapping, Sequence

import yaml


class P3GateError(ValueError):
    pass


REQUIRED_PATHS = {
    "p2_lock": "references/repos.lock.yaml",
    "operation_manifest": "experiments/00_source_audit/configs/operation-manifest.yaml",
    "compatibility_csv": "experiments/00_source_audit/results/compatibility.csv",
    "licenses": "references/licenses.md",
    "source_map": "docs/SOURCE_MAP.md",
    "p3_results": "experiments/00_source_audit/RESULTS.md",
    "run_manifest": "docs/RUN_MANIFEST.yaml",
    "mujoco_smoke": "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json",
}
_SHA = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class EvidenceFile:
    path: Path
    sha256: str

    def __post_init__(self) -> None:
        pure = PurePosixPath(self.path.as_posix())
        if pure.is_absolute() or ".." in pure.parts or _SHA.fullmatch(self.sha256) is None:
            raise P3GateError("invalid evidence path or hash")


@dataclass(frozen=True)
class P3GateEvidence:
    files: Mapping[str, EvidenceFile]
    mujoco_package: str
    mujoco_version: str
    mujoco_artifact_sha256: str


def _wire(evidence: P3GateEvidence) -> dict[str, object]:
    return {
        "schema_version": 1,
        "files": {key: {"path": item.path.as_posix(), "sha256": item.sha256} for key, item in sorted(evidence.files.items())},
        "mujoco": {"package": evidence.mujoco_package, "version": evidence.mujoco_version, "artifact_sha256": evidence.mujoco_artifact_sha256},
    }


def dump_p3_gate(evidence: P3GateEvidence, destination: Path) -> None:
    data = yaml.safe_dump(_wire(evidence), sort_keys=True).encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(data)


def load_p3_gate(path: Path | str) -> P3GateEvidence:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "files", "mujoco"} or raw["schema_version"] != 1:
        raise P3GateError("invalid P3 gate schema")
    files = raw["files"]
    mujoco = raw["mujoco"]
    if not isinstance(files, dict) or set(files) != set(REQUIRED_PATHS):
        raise P3GateError("P3 gate evidence inventory is incomplete")
    if not isinstance(mujoco, dict) or set(mujoco) != {"package", "version", "artifact_sha256"}:
        raise P3GateError("invalid MuJoCo identity")
    parsed: dict[str, EvidenceFile] = {}
    for key, item in files.items():
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise P3GateError("invalid evidence file")
        parsed[key] = EvidenceFile(Path(item["path"]), item["sha256"])
    return P3GateEvidence(parsed, mujoco["package"], mujoco["version"], mujoco["artifact_sha256"])


def _regular_contained(root: Path, relative: Path) -> Path:
    candidate = root / relative
    if candidate.is_symlink() or not candidate.is_file() or not candidate.resolve().is_relative_to(root.resolve()):
        raise P3GateError(f"invalid evidence path: {relative}")
    return candidate


def require_p3_gate(repo_root: Path, evidence: P3GateEvidence) -> None:
    for key, expected_relative in REQUIRED_PATHS.items():
        item = evidence.files.get(key)
        if item is None or item.path.as_posix() != expected_relative:
            raise P3GateError(f"{key} path mismatch")
        actual = _regular_contained(repo_root, item.path)
        if sha256_file(actual) != item.sha256:
            raise P3GateError(f"{key} hash mismatch")
    run_manifest = yaml.safe_load((repo_root / REQUIRED_PATHS["run_manifest"]).read_text(encoding="utf-8"))
    if run_manifest.get("stages", {}).get("p3") != "complete":
        raise P3GateError("P3 is not complete")
    safety = run_manifest.get("safety", {})
    if safety.get("physical_deployment_allowed") is not False or safety.get("remote_enabled") is not False:
        raise P3GateError("P3 safety state is not simulation-only")
    import json
    smoke = json.loads((repo_root / REQUIRED_PATHS["mujoco_smoke"]).read_text(encoding="utf-8"))
    expected = (evidence.mujoco_package, evidence.mujoco_version, evidence.mujoco_artifact_sha256)
    observed = (smoke.get("package"), smoke.get("version"), smoke.get("artifact_sha256"))
    if smoke.get("status") != "PASS" or smoke.get("runtime_subject") != "package" or observed != expected:
        raise P3GateError("MuJoCo smoke identity mismatch")


def write_p3_gate(repo_root: Path, destination: Path) -> None:
    files = {key: EvidenceFile(Path(relative), sha256_file(_regular_contained(repo_root, Path(relative)))) for key, relative in REQUIRED_PATHS.items()}
    import json
    smoke = json.loads((repo_root / REQUIRED_PATHS["mujoco_smoke"]).read_text(encoding="utf-8"))
    evidence = P3GateEvidence(files, smoke["package"], smoke["version"], smoke["artifact_sha256"])
    require_p3_gate(repo_root, evidence)
    dump_p3_gate(evidence, destination)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", type=Path, required=True)
    args = parser.parse_args(argv)
    write_p3_gate(Path.cwd(), args.write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
