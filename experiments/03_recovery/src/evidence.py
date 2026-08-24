"""Create-only evidence publication, shard merge, and clean reconstruction."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Iterable, Mapping, Sequence

import mujoco
import numpy as np

from .cell import episode_specs, scenario_specs
from .contracts import Architecture, EpisodeSpec, ScenarioDomain, canonical_bytes
from .episode import EpisodeEvidence, run_episode


SHARD_IDS = ("anchors-control", "motion", "semantic")


class EvidenceError(ValueError):
    pass


_SOURCE_PATHS = (
    "experiments/03_recovery/run.py",
    "experiments/03_recovery/src/contracts.py",
    "experiments/03_recovery/src/recovery.py",
    "experiments/03_recovery/src/cell.py",
    "experiments/03_recovery/src/episode.py",
    "experiments/03_recovery/src/evidence.py",
    "experiments/03_recovery/src/analyze.py",
    "experiments/01_policy_control/configs/base.yaml",
    "experiments/01_policy_control/src/arm.py",
    "experiments/01_policy_control/src/contracts.py",
    "experiments/01_policy_control/src/kinematics.py",
    "experiments/01_policy_control/src/representations.py",
    "reflect/types.py",
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def source_ledger() -> list[dict[str, object]]:
    root = _repository_root()
    result = []
    for name in _SOURCE_PATHS:
        payload = (root / name).read_bytes()
        result.append({"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    return result


def frozen_configuration() -> dict[str, object]:
    specs = episode_specs()
    scenarios = scenario_specs()
    return {
        "study_id": "exp03-hierarchy-v1",
        "episode_ticks": 3125,
        "timestep_s": 0.002,
        "injection_tick": 750,
        "recovery_budgets": {"control": 2, "motion": 2, "semantic": 1},
        "controllers": {
            "P6-res0p5-slew48": {"stack": "P6", "residual_component_limit_rad": 0.5, "reference_slew_rad_s": 48.0, "pd": [5.0, 0.5]},
            "P4-lookahead1-dqon": {"stack": "P4", "lookahead_ticks": 1, "dq_feedforward": True, "reference_slew_rad_s": 48.0, "pd": [5.0, 0.5]},
        },
        "scenario_sha256s": {item.scenario_id: item.sha256 for item in scenarios},
        "episode_ids": [item.episode_id for item in specs],
        "primary_count": sum(not item.sensitivity for item in specs),
        "sensitivity_count": sum(item.sensitivity for item in specs),
        "bootstrap_draws": 10_000,
    }


def freeze(output: Path) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(output)
    root = _repository_root()
    source_commit = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True, stdout=subprocess.PIPE, text=True).stdout.strip()
    ledger = source_ledger()
    source_sha = hashlib.sha256(canonical_bytes(ledger)).hexdigest()
    configuration = frozen_configuration()
    config_sha = hashlib.sha256(canonical_bytes(configuration)).hexdigest()
    from .cell import precheck

    receipts = [
        {
            "scenario_id": scenario.scenario_id,
            "controller_id": controller,
            "receipt": json.loads(canonical_bytes(precheck(scenario, controller))),
        }
        for controller in ("P6-res0p5-slew48", "P4-lookahead1-dqon")
        for scenario in scenario_specs()
    ]
    ready = all(bool(item["receipt"]["feasible"]) for item in receipts)
    record = {
        "schema_version": 1,
        "disposition": "READY" if ready else "NOT_RUN",
        "source_commit": source_commit,
        "source_sha256": source_sha,
        "source_ledger": ledger,
        "config_sha256": config_sha,
        "configuration": configuration,
        "feasibility_receipts": receipts,
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "mujoco": mujoco.__version__,
            "os_arch": f"{platform.system()}-{platform.machine()}",
        },
    }
    output.mkdir(parents=True)
    _write_create(output / "freeze.json", canonical_bytes(record))
    return record


def verify_freeze(output: Path) -> dict[str, object]:
    record = json.loads((output / "freeze.json").read_text(encoding="ascii"))
    ledger = source_ledger()
    if ledger != record.get("source_ledger") or hashlib.sha256(canonical_bytes(ledger)).hexdigest() != record.get("source_sha256"):
        raise EvidenceError("frozen source drift")
    configuration = frozen_configuration()
    if configuration != record.get("configuration") or hashlib.sha256(canonical_bytes(configuration)).hexdigest() != record.get("config_sha256"):
        raise EvidenceError("frozen configuration drift")
    if record.get("disposition") != "READY":
        raise EvidenceError("feasibility gate returned NOT_RUN")
    return record


def run_shard(output: Path, shard_id: str) -> dict[str, object]:
    freeze_record = verify_freeze(output)
    specs = tuple(item for item in episode_specs() if shard_for_scenario(item.scenario_id) == shard_id)
    root = output / "shards" / shard_id
    binding = {key: str(freeze_record[key]) for key in ("source_sha256", "config_sha256", "source_commit")}
    manifest = run_specs_shard(root, shard_id, specs, binding)
    verify_freeze(output)
    return manifest


def _write_create(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _jsonl(rows: Iterable[object]) -> bytes:
    return b"".join(canonical_bytes(item) for item in rows)


def _trace_bytes(trace: Mapping[str, np.ndarray]) -> bytes:
    stream = io.BytesIO()
    np.savez_compressed(stream, **{name: trace[name] for name in sorted(trace)})
    return stream.getvalue()


def episode_payloads(evidence: EpisodeEvidence) -> dict[str, bytes]:
    return {
        "spec.json": canonical_bytes(evidence.spec),
        "controller.json": canonical_bytes(dict(evidence.controller_fingerprint)),
        "semantic.jsonl": _jsonl(evidence.semantic_plans),
        "memory.jsonl": _jsonl(evidence.memory_snapshots),
        "motion.jsonl": _jsonl(evidence.motion_commands),
        "recovery-observations.jsonl": _jsonl(evidence.recovery_observations),
        "recovery-decisions.jsonl": _jsonl(evidence.recovery_decisions),
        "scorer.json": canonical_bytes(dict(evidence.scorer)),
        "terminal.json": canonical_bytes({"terminal_disposition": evidence.terminal.value, "metrics": dict(evidence.metrics)}),
        "trace.npz": _trace_bytes(evidence.trace),
    }


def _file_rows(payloads: Mapping[str, bytes]) -> list[dict[str, object]]:
    return [
        {"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for name, payload in sorted(payloads.items())
    ]


def write_episode(parent: Path, evidence: EpisodeEvidence) -> Path:
    destination = parent / evidence.spec.episode_id
    if destination.exists():
        raise FileExistsError(destination)
    payloads = episode_payloads(evidence)
    destination.mkdir(parents=True)
    for name, payload in sorted(payloads.items()):
        _write_create(destination / name, payload)
    manifest = {
        "schema_version": 1,
        "episode_id": evidence.spec.episode_id,
        "scenario_sha256": evidence.scenario_sha256,
        "feasibility_sha256": evidence.feasibility_sha256,
        "files": _file_rows(payloads),
    }
    _write_create(destination / "manifest.json", canonical_bytes(manifest))
    return destination


def validate_episode(destination: Path) -> dict[str, object]:
    manifest_path = destination / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise EvidenceError("episode manifest missing")
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    actual = []
    for path in sorted(destination.iterdir()):
        if path.name == "manifest.json":
            continue
        if path.is_symlink() or not path.is_file():
            raise EvidenceError("episode contains non-regular member")
        payload = path.read_bytes()
        actual.append({"path": path.name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    if actual != manifest.get("files"):
        raise EvidenceError("episode inventory mismatch")
    if manifest.get("episode_id") != destination.name:
        raise EvidenceError("episode identity mismatch")
    return manifest


def validate_identity_set(actual: Sequence[str], expected: Sequence[str]) -> tuple[str, ...]:
    if len(actual) != len(set(actual)):
        raise EvidenceError("duplicate episode identity")
    if set(actual) != set(expected) or len(actual) != len(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise EvidenceError(f"episode identity mismatch missing={missing} extra={extra}")
    return tuple(sorted(actual))


def shard_for_scenario(scenario_id: str) -> str:
    scenario = next((item for item in scenario_specs() if item.scenario_id == scenario_id), None)
    if scenario is None:
        raise ValueError("unknown scenario")
    if scenario.domain in {ScenarioDomain.ANCHOR, ScenarioDomain.CONTROL}:
        return "anchors-control"
    return scenario.domain.value.lower()


def validate_shard_bindings(manifests: Sequence[Mapping[str, object]]) -> tuple[str, str]:
    sources = {str(item["source_sha256"]) for item in manifests}
    configs = {str(item["config_sha256"]) for item in manifests}
    if len(sources) != 1:
        raise EvidenceError("shard source drift")
    if len(configs) != 1:
        raise EvidenceError("shard config drift")
    return next(iter(sources)), next(iter(configs))


def run_specs_shard(root: Path, shard_id: str, specs: Sequence[EpisodeSpec], binding: Mapping[str, str]) -> dict[str, object]:
    if shard_id not in SHARD_IDS:
        raise ValueError("unknown shard")
    if root.exists():
        raise FileExistsError(root)
    if any(shard_for_scenario(item.scenario_id) != shard_id for item in specs):
        raise ValueError("episode assigned to wrong shard")
    root.mkdir(parents=True)
    episodes_root = root / "episodes"
    episodes_root.mkdir()
    valid_ids: list[str] = []
    invalid: list[dict[str, object]] = []
    episode_manifests: list[dict[str, object]] = []
    for spec in sorted(specs, key=lambda item: item.episode_id):
        try:
            destination = write_episode(episodes_root, run_episode(spec))
            manifest_payload = (destination / "manifest.json").read_bytes()
            validate_episode(destination)
            valid_ids.append(spec.episode_id)
            episode_manifests.append({"episode_id": spec.episode_id, "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest()})
        except Exception as exc:  # retained terminal invalid-attempt evidence
            invalid.append({
                "episode_id": spec.episode_id,
                "attempt_outcome": "INVALID_ATTEMPT",
                "terminal_disposition": "INVALID_EVIDENCE",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            })
    invalid_payload = _jsonl(invalid)
    _write_create(root / "invalid-attempts.jsonl", invalid_payload)
    manifest = {
        "schema_version": 1,
        "shard_id": shard_id,
        "source_sha256": binding["source_sha256"],
        "config_sha256": binding["config_sha256"],
        "source_commit": binding["source_commit"],
        "episode_ids": sorted(valid_ids),
        "expected_episode_ids": sorted(item.episode_id for item in specs),
        "episode_manifests": sorted(episode_manifests, key=lambda item: str(item["episode_id"])),
        "invalid_attempt_count": len(invalid),
        "invalid_attempts_sha256": hashlib.sha256(invalid_payload).hexdigest(),
        "disposition": "COMPLETE" if not invalid and len(valid_ids) == len(specs) else "INCOMPLETE",
    }
    _write_create(root / "manifest.json", canonical_bytes(manifest))
    return manifest


def _validate_shard(root: Path) -> dict[str, object]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="ascii"))
    if manifest.get("shard_id") != root.name:
        raise EvidenceError("shard identity mismatch")
    invalid_payload = (root / "invalid-attempts.jsonl").read_bytes()
    if hashlib.sha256(invalid_payload).hexdigest() != manifest.get("invalid_attempts_sha256"):
        raise EvidenceError("invalid-attempt inventory mismatch")
    episode_rows = []
    for item in manifest.get("episode_manifests", []):
        destination = root / "episodes" / str(item["episode_id"])
        validate_episode(destination)
        digest = hashlib.sha256((destination / "manifest.json").read_bytes()).hexdigest()
        if digest != item["manifest_sha256"]:
            raise EvidenceError("episode manifest hash mismatch")
        episode_rows.append(str(item["episode_id"]))
    if sorted(episode_rows) != manifest.get("episode_ids"):
        raise EvidenceError("shard episode inventory mismatch")
    return manifest


def _link_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    for path in sorted(source.iterdir()):
        target = destination / path.name
        if path.is_symlink() or not path.is_file():
            raise EvidenceError("episode member is not a regular file")
        try:
            os.link(path, target)
        except OSError:
            shutil.copy2(path, target)


def merge_shards(output: Path, shard_roots: Sequence[Path], *, expected_specs: Sequence[EpisodeSpec] | None = None) -> Path:
    expected_specs = tuple(episode_specs() if expected_specs is None else expected_specs)
    if len(shard_roots) != 3 or {path.name for path in shard_roots} != set(SHARD_IDS):
        raise EvidenceError("merge requires exact three shards")
    manifests = [_validate_shard(path) for path in sorted(shard_roots)]
    source_sha, config_sha = validate_shard_bindings(manifests)
    actual = [episode_id for manifest in manifests for episode_id in manifest["episode_ids"]]
    expected_ids = [item.episode_id for item in expected_specs]
    validate_identity_set(actual, expected_ids)
    if any(manifest["disposition"] != "COMPLETE" or manifest["invalid_attempt_count"] for manifest in manifests):
        raise EvidenceError("invalid or incomplete shard cannot merge")
    raw = output / "raw"
    if raw.exists():
        raise FileExistsError(raw)
    (raw / "episodes").mkdir(parents=True)
    episode_rows = []
    for shard_root, manifest in zip(sorted(shard_roots), manifests, strict=True):
        for episode_id in manifest["episode_ids"]:
            source = shard_root / "episodes" / episode_id
            destination = raw / "episodes" / episode_id
            _link_tree(source, destination)
            manifest_sha = hashlib.sha256((destination / "manifest.json").read_bytes()).hexdigest()
            episode_rows.append({"episode_id": episode_id, "shard_id": shard_root.name, "manifest_sha256": manifest_sha})
    invalid_payload = b"".join((path / "invalid-attempts.jsonl").read_bytes() for path in sorted(shard_roots))
    _write_create(raw / "invalid-attempts.jsonl", invalid_payload)
    freeze_path = output / "freeze.json"
    freeze_sha = hashlib.sha256(freeze_path.read_bytes()).hexdigest() if freeze_path.is_file() else None
    manifest = {
        "schema_version": 1,
        "source_sha256": source_sha,
        "config_sha256": config_sha,
        "source_commit": manifests[0]["source_commit"],
        "freeze_sha256": freeze_sha,
        "episode_count": len(episode_rows),
        "primary_episode_count": sum(not item.sensitivity for item in expected_specs),
        "sensitivity_episode_count": sum(item.sensitivity for item in expected_specs),
        "invalid_attempt_count": 0,
        "invalid_attempts_sha256": hashlib.sha256(invalid_payload).hexdigest(),
        "shard_manifests": [
            {"shard_id": path.name, "sha256": hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()}
            for path in sorted(shard_roots)
        ],
        "episodes": sorted(episode_rows, key=lambda item: str(item["episode_id"])),
    }
    _write_create(raw / "manifest.json", canonical_bytes(manifest))
    return raw


def _validate_raw(raw_root: Path) -> dict[str, object]:
    manifest = json.loads((raw_root / "manifest.json").read_text(encoding="ascii"))
    invalid = (raw_root / "invalid-attempts.jsonl").read_bytes()
    if hashlib.sha256(invalid).hexdigest() != manifest.get("invalid_attempts_sha256"):
        raise EvidenceError("merged invalid-attempt inventory mismatch")
    ids = []
    for row in manifest.get("episodes", []):
        episode_id = str(row["episode_id"])
        destination = raw_root / "episodes" / episode_id
        validate_episode(destination)
        if hashlib.sha256((destination / "manifest.json").read_bytes()).hexdigest() != row["manifest_sha256"]:
            raise EvidenceError("merged episode manifest mismatch")
        ids.append(episode_id)
    if len(ids) != manifest.get("episode_count") or len(ids) != len(set(ids)):
        raise EvidenceError("merged identity count mismatch")
    return manifest


def _spec_from_wire(wire: Mapping[str, object]) -> EpisodeSpec:
    return EpisodeSpec(
        str(wire["episode_id"]),
        Architecture(str(wire["architecture"])),
        str(wire["scenario_id"]),
        ScenarioDomain(str(wire["scenario_domain"])),
        int(wire["seed"]),
        str(wire["controller_id"]),
        bool(wire["sensitivity"]),
    )


def load_merged_rows(raw_root: Path) -> list[dict[str, object]]:
    manifest = _validate_raw(raw_root)
    rows: list[dict[str, object]] = []
    for record in sorted(manifest["episodes"], key=lambda item: str(item["episode_id"])):
        root = raw_root / "episodes" / str(record["episode_id"])
        spec = json.loads((root / "spec.json").read_text(encoding="ascii"))
        terminal = json.loads((root / "terminal.json").read_text(encoding="ascii"))
        scorer = json.loads((root / "scorer.json").read_text(encoding="ascii"))
        decisions = [json.loads(line) for line in (root / "recovery-decisions.jsonl").read_text(encoding="ascii").splitlines()]
        row = {
            **spec,
            **terminal["metrics"],
            "terminal_disposition": terminal["terminal_disposition"],
            "attempt_outcome": "VALID",
            "first_recovery_level": "NONE" if not decisions else decisions[0]["level"],
            "hidden_cause": scorer["hidden_cause"],
            "episode_manifest_sha256": record["manifest_sha256"],
        }
        rows.append(row)
    return rows


def eligible_episode_rows(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [item for item in rows if item.get("attempt_outcome") == "VALID" and item.get("terminal_disposition") != "INVALID_EVIDENCE"]


def reconstruct(
    raw_root: Path,
    clean_output: Path,
    *,
    expected_specs: Sequence[EpisodeSpec] | None = None,
    expected_primary_count: int = 256,
) -> dict[str, object]:
    manifest = _validate_raw(raw_root)
    expected_specs = tuple(episode_specs() if expected_specs is None else expected_specs)
    actual_ids = [str(item["episode_id"]) for item in manifest["episodes"]]
    validate_identity_set(actual_ids, [item.episode_id for item in expected_specs])
    for record in sorted(manifest["episodes"], key=lambda item: str(item["episode_id"])):
        root = raw_root / "episodes" / str(record["episode_id"])
        spec = _spec_from_wire(json.loads((root / "spec.json").read_text(encoding="ascii")))
        replay = run_episode(spec)
        replay_payloads = episode_payloads(replay)
        for name, payload in replay_payloads.items():
            if name == "trace.npz":
                with np.load(root / name, allow_pickle=False) as stored, np.load(io.BytesIO(payload), allow_pickle=False) as regenerated:
                    if set(stored.files) != set(regenerated.files) or any(not np.array_equal(stored[key], regenerated[key]) for key in stored.files):
                        raise EvidenceError(f"controller trace replay mismatch: {spec.episode_id}")
            elif (root / name).read_bytes() != payload:
                raise EvidenceError(f"decision/evidence replay mismatch: {spec.episode_id}:{name}")
    from .analyze import analyze

    decision = analyze(raw_root, clean_output, expected_primary_count=expected_primary_count)
    return {"episodes_replayed": len(actual_ids), "decision": decision["outcome"], "raw_manifest_sha256": hashlib.sha256((raw_root / "manifest.json").read_bytes()).hexdigest()}


__all__ = [
    "EvidenceError", "SHARD_IDS", "eligible_episode_rows", "episode_payloads",
    "freeze", "frozen_configuration", "load_merged_rows", "merge_shards", "reconstruct",
    "run_shard", "run_specs_shard", "shard_for_scenario", "source_ledger", "validate_episode", "validate_identity_set",
    "validate_shard_bindings", "write_episode",
]
