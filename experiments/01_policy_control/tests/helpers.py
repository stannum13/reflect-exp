from __future__ import annotations

import importlib
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np

from reflect.types import Constraint, ObjectBelief, Observation, Pose, Predicate, RobotState, SkillSpec


contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
artifacts = importlib.import_module("experiments.01_policy_control.src.artifacts")
BASE = Path(__file__).resolve().parents[1] / "configs/base.yaml"


def config():
    return contracts.load_config(BASE)


def resource_evidence(*, phase: str, complete: bool, predecessor: str | None = None):
    with tempfile.TemporaryDirectory(prefix="exp01-resource-") as temporary:
        root = Path(temporary)
        gate = root / "p3-gate.yaml"
        gate.write_text("schema_version: 1\n", encoding="utf-8")
        revision = root / "protocol" / "revision-manifest.json"
        base = revision.with_name("base-manifest.json")
        implementation = "3" * 40
        artifacts.prepare_manifest("revision", None, revision, BASE, gate, implementation_sha=implementation)
        artifacts.prepare_manifest("base", revision, base, BASE, gate, implementation_sha=implementation)
        protocol = base
        if phase == "confirmation":
            row = json.loads(base.read_text(encoding="utf-8"))
            row["phase"] = "confirmation"
            row["stage"] = "confirmation"
            row["predecessor_sha256"] = predecessor or "9" * 64
            protocol = revision.with_name("confirmation-manifest.json")
            protocol.write_bytes(artifacts.canonical_json_bytes(row))
        manifest = artifacts.load_protocol_manifest(protocol)
        results = root / "results"
        results.mkdir()
        if complete:
            protocol_sha = hashlib.sha256(protocol.read_bytes()).hexdigest()
            for shard in manifest["shards"]:
                directory = results / artifacts._shard_directory_name(shard["shard_id"])
                directory.mkdir()
                rollout_hashes = []
                retained = 0
                for identity in shard["output_identities"]:
                    payload = artifacts.canonical_json_bytes({"output_identity": identity})
                    (directory / f"{identity}.rollout.json").write_bytes(payload)
                    rollout_hashes.append(hashlib.sha256(payload).hexdigest())
                    retained += len(payload)
                ledger = {
                    "schema_version": 1, "study_id": artifacts.STUDY_ID,
                    "phase": phase, "revision": 1, "shard_id": shard["shard_id"],
                    "command_sha256": hashlib.sha256(shard["shard_id"].encode()).hexdigest(),
                    "started_at_utc": "2026-08-23T00:00:00Z",
                    "finished_at_utc": "2026-08-23T00:00:01Z",
                    "wall_ns": 1, "cpu_ns": 1, "retained_bytes": retained,
                    "temp_peak_bytes": 0, "quarantine_bytes": 0,
                    "free_bytes_after": 20 * 1024 * 1024 * 1024, "disposition": "COMPLETE",
                }
                ledger_bytes = artifacts.canonical_json_bytes(ledger)
                (directory / "resource-ledger.jsonl").write_bytes(ledger_bytes)
                completion = {
                    "schema_version": 1, "study_id": artifacts.STUDY_ID,
                    "phase": phase, "revision": 1, "shard_id": shard["shard_id"],
                    "implementation_sha": implementation,
                    "preregistration_git_sha": None if phase == "pilot" else "4" * 40,
                    "protocol_sha256": protocol_sha,
                    "configuration_hash": shard["configuration_hash"], "seed": shard["seed"],
                    "expected_output_identities": shard["output_identities"],
                    "completed_output_identities": shard["output_identities"],
                    "rollout_sha256s": rollout_hashes, "failure_disposition_sha256": None,
                    "resource_ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
                    "state": "COMPLETE",
                }
                (directory / "completion.json").write_bytes(artifacts.canonical_json_bytes(completion))
        return artifacts.load_resource_completion_evidence(protocol, results)


def policy_input(period_ns: int = 100_000_000, response_ns: int = 300_000_000):
    target = np.array([0.62, 0.08])
    observation = Observation(
        sequence_id=7,
        source_time_ns=0,
        received_time_ns=0,
        robot_state=RobotState(q=np.array([0.35, -0.70, 0.35]), dq=np.zeros(3)),
        object_beliefs=(ObjectBelief("target", "target", target, 1.0, {}, 1.0, 0, ("synthetic",)),),
        current_skill_id="track",
        current_phase="track_target",
    )
    skill = SkillSpec(
        skill_id="track",
        skill_type="track_target",
        target_entities=("target",),
        target_pose=Pose(np.array([target[0], target[1], 0.0]), np.array([1.0, 0.0, 0.0, 0.0])),
        constraints=(Constraint("workspace", {"radius_m": 0.7}),),
        success_predicate=Predicate("eef_error", {"max_m": 0.025}),
        timeout_s=6.25,
        retry_budget=0,
    )
    q0 = np.array([0.35, -0.70, 0.35])
    kin = importlib.import_module("experiments.01_policy_control.src.kinematics")
    cfg = config()
    q1 = kin.absolute_ik(target, q0, cfg.arm.link_lengths_m, cfg.controller.ik_damping_candidates[0], cfg)
    return contracts.PolicyInput(observation, skill, response_ns, period_ns, q0, q1)
