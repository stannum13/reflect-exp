from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
import subprocess

import pytest


artifacts = importlib.import_module("experiments.01_policy_control.src.artifacts")
contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
evaluate = importlib.import_module("experiments.01_policy_control.src.evaluate")
timing = importlib.import_module("experiments.01_policy_control.src.timing")


H64 = "a" * 64
G40 = "b" * 40


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def _manifest() -> dict[str, object]:
    shards = [
        {"shard_id": "P2:base:001", "stack_id": "P2", "configuration_hash": H64,
         "seed": 1, "condition_ids": ["c2"], "episode_count": 1,
         "output_identities": ["P2-c2-1"]},
        {"shard_id": "P1:base:002", "stack_id": "P1", "configuration_hash": H64,
         "seed": 2, "condition_ids": ["c2"], "episode_count": 1,
         "output_identities": ["P1-c2-2"]},
        {"shard_id": "P1:base:001", "stack_id": "P1", "configuration_hash": H64,
         "seed": 1, "condition_ids": ["c1"], "episode_count": 1,
         "output_identities": ["P1-c1-1"]},
    ]
    return {
        "schema_version": 1, "study_id": "reflect-lite-policy-control", "phase": "pilot",
        "revision": 1, "stage": "base", "implementation_sha": G40,
        "predecessor_sha256": None, "config_sha256": H64, "p3_gate_sha256": H64,
        "seed_manifest_sha256": H64, "parameter_vector": {}, "parameter_hash": H64,
        "scenario_generator_hash": H64, "condition_hash": H64, "metric_hash": H64,
        "gate_hash": H64, "resource_limits": {}, "shards": shards, "state": "READY",
    }


def test_iter_manifest_is_closed_canonical_and_p1_first(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(_canonical(_manifest()))
    rows = tuple(artifacts.iter_manifest(path))
    assert tuple(row.shard_id for row in rows) == (
        "P1:base:001", "P1:base:002", "P2:base:001",
    )
    assert rows[0].episode_count == 1

    path.write_bytes(_canonical(_manifest()) + b" ")
    with pytest.raises(artifacts.ArtifactError, match="canonical"):
        tuple(artifacts.iter_manifest(path))

    duplicate = _canonical(_manifest()).replace(b'"state":"READY"', b'"state":"READY","state":"READY"')
    path.write_bytes(duplicate)
    with pytest.raises(artifacts.ArtifactError, match="duplicate"):
        tuple(artifacts.iter_manifest(path))

    unknown = _manifest() | {"unknown": 1}
    path.write_bytes(_canonical(unknown))
    with pytest.raises(artifacts.ArtifactError, match="unknown"):
        tuple(artifacts.iter_manifest(path))


def test_preflight_uses_exact_caps_and_never_accepts_bool() -> None:
    mib = 1024 * 1024
    allowed = artifacts.preflight_resources(
        "confirmation", 14_576 * mib - 2 * mib, 0, 0, 2 * mib,
        24 * 3600, 240 * 3600,
    )
    assert allowed.disposition == "ALLOW"
    assert allowed.reserved_bytes == 2 * mib
    assert allowed.reasons == ()
    refused = artifacts.preflight_resources(
        "confirmation", 14_576 * mib - 2 * mib + 1, 0, 0, 2 * mib,
        24 * 3600 + 1, 240 * 3600,
    )
    assert refused.disposition == "REFUSE"
    assert refused.reasons == ("PHASE_BYTES_EXCEEDED", "WALL_TIME_EXCEEDED")
    with pytest.raises(ValueError, match="integer"):
        artifacts.preflight_resources("pilot", True, 0, 0, 2 * mib, 0, 0)


def test_publish_rollout_is_create_only_and_replay_validated(tmp_path: Path) -> None:
    cfg = contracts.load_config(Path(__file__).parents[1] / "configs/base.yaml")
    scenario_record = evaluate.generate_scenario(17, cfg)
    scenario = scenario_record.scenario
    condition = evaluate.core_conditions(cfg)[0]
    configuration_hash = evaluate.sha256_json(timing.scheduler_config(cfg))
    identity = evaluate.EpisodeIdentity(
        G40, True, None, H64, "test", "cpu", None, "3.11", {"mujoco": "3.12.0"},
        configuration_hash, {"arm": H64},
    )
    record = evaluate.run_episode(contracts.CommandStack.P1, condition, scenario_record, cfg, identity)
    destination = tmp_path / record.events[0].rollout_id
    spec = artifacts.RolloutSpec(
        destination.name, "P1", scenario.seed, condition.condition_id,
        configuration_hash, H64, H64, 2 * 1024 * 1024,
    )
    assert artifacts.publish_or_validate_skip(record, destination, spec) == "published"
    assert artifacts.publish_or_validate_skip(record, destination, spec) == "validated-and-skipped"
    replay = artifacts.replay_rollout(destination)
    validated = artifacts.validate_rollout(destination)
    assert replay.rollout_id == destination.name
    assert replay.events == validated.events
    assert artifacts.canonical_state_bytes(replay.final_state) == artifacts.canonical_state_bytes(replay.frames[-1].state)
    (destination / "extra").write_bytes(b"x")
    with pytest.raises(Exception):
        artifacts.publish_or_validate_skip(record, destination, spec)


def test_implementation_snapshot_detects_tracked_and_untracked_drift(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / "code.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "owned/code.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    snap = artifacts.ImplementationSnapshot.capture(tmp_path, sha, (Path("owned"),))
    snap.validate_before()
    (owned / "new.py").write_text("x = 1\n")
    with pytest.raises(artifacts.ImplementationDriftError, match="untracked"):
        snap.validate_after()


def test_reconstruct_evidence_is_deterministic_and_manifest_last(tmp_path: Path) -> None:
    def make_raw(stack: str, seed: int, validity: str) -> dict[str, object]:
        disposition = "SUCCESS" if validity == "VALID" else "DECLARED_MISSING"
        return {
            "schema_version": 1, "revision": 1, "stack_id": stack, "condition_id": "c",
            "variant_id": "base", "scene_id": f"scene-{seed}", "episode_id": f"episode-{seed}",
            "anchor_id": "anchor", "candidate_id": "candidate", "seed": seed,
            "rng_namespace": "confirmation", "tick_start": 0, "tick_end": 3125,
            "units": {"time": "ns", "position": "m"}, "frames": {"target": "world"},
            "validity": validity, "missingness": None if validity == "VALID" else "ACCIDENTAL",
            "terminal_state": "COMPLETE", "config_sha256": H64, "code_sha256": H64,
            "dependency_sha256": H64, "input_sha256": H64, "output_sha256": H64,
            "replay_sha256": H64 if validity == "VALID" else None,
            "bundle_sha256": H64 if validity == "VALID" else None,
            "disposition": disposition, "reason": "NONE" if validity == "VALID" else "MISSING_OUTPUT",
            "analysis_included": validity == "VALID",
        }

    raw = (
        make_raw("P2", 2, "VALID"), make_raw("P1", 1, "DECLARED_INVALID"),
    )
    index = (
        {"schema_version": 1, "revision": 1, "stack_id": "P1", "variant_id": "base",
         "condition_id": "c", "target_class": "WORKING", "label": "CLASS_NOT_OBSERVED",
         "source_ranges": [], "command_output_sha256": H64, "raw_links": [], "denominator": 1},
        {"schema_version": 1, "revision": 1, "stack_id": "P1", "variant_id": "base",
         "condition_id": "c", "target_class": "NONWORKING", "label": "NONWORKING",
         "source_ranges": [{"start": 0, "end": 20}], "command_output_sha256": H64,
         "raw_links": ["episode-1"], "denominator": 1},
        {"schema_version": 1, "revision": 1, "stack_id": "P2", "variant_id": "base",
         "condition_id": "c", "target_class": "WORKING", "label": "WORKING",
         "source_ranges": [{"start": 0, "end": 20}], "command_output_sha256": H64,
         "raw_links": ["episode-2"], "denominator": 1},
        {"schema_version": 1, "revision": 1, "stack_id": "P2", "variant_id": "base",
         "condition_id": "c", "target_class": "NONWORKING", "label": "CLASS_NOT_OBSERVED",
         "source_ranges": [], "command_output_sha256": H64, "raw_links": [], "denominator": 1},
    )
    raw_source = b"".join(_canonical(row) for row in sorted(raw, key=lambda row: (row["stack_id"], row["seed"], row["condition_id"], row["episode_id"])))
    recipes = ({
        "schema_version": 1, "revision": 1, "plot": "recovery-vs-latency.svg",
        "source_sha256": hashlib.sha256(raw_source).hexdigest(), "filters": [], "transforms": [], "group_by": ["stack_id"],
        "order_by": ["stack_id", "seed"], "axes": {"x": "seed", "y": "validity"},
        "units": {"x": "count", "y": "category"}, "frames": {}, "binning": "NONE",
        "summary": "COUNT", "interval": "NONE", "palette": ["#000000"], "legend": True,
        "dimensions": {"width": 640, "height": 480}, "renderer_version": "SVG_V1", "seed": 0,
    },)
    first = artifacts.reconstruct_evidence(tmp_path / "first", raw, index, recipes, protocol_sha256=H64)
    second = artifacts.reconstruct_evidence(tmp_path / "second", tuple(reversed(raw)), tuple(reversed(index)), recipes, protocol_sha256=H64)
    assert first == second
    assert (tmp_path / "first" / "derived-table.json").read_bytes() == (tmp_path / "second" / "derived-table.json").read_bytes()
    assert (tmp_path / "first" / "recovery-vs-latency.svg").read_bytes() == (tmp_path / "second" / "recovery-vs-latency.svg").read_bytes()
    assert (tmp_path / "first" / "artifact-manifest.json").exists()
    assert [p.name for p in sorted((tmp_path / "first").iterdir())][-1] != "artifact-manifest.json"  # ordering is carried by manifest, not directory order
    manifest = artifacts.load_artifact_manifest(tmp_path / "first" / "artifact-manifest.json")
    assert "artifact-manifest.json" not in {row["path"] for row in manifest["files"]}
    assert artifacts.validate_evidence_publication(tmp_path / "first") == manifest
    (tmp_path / "first" / "extra.json").write_bytes(b"{}\n")
    with pytest.raises(artifacts.ArtifactError, match="extra"):
        artifacts.validate_evidence_publication(tmp_path / "first")
    (tmp_path / "first" / "extra.json").unlink()
    with pytest.raises((FileExistsError, artifacts.ArtifactError)):
        artifacts.reconstruct_evidence(tmp_path / "first", raw + (make_raw("P3", 3, "VALID"),), index, recipes, protocol_sha256=H64)

    contradictory = dict(raw[0]) | {"disposition": "TIMED_OUT", "analysis_included": True}
    with pytest.raises(artifacts.ArtifactError, match="disposition"):
        artifacts.reconstruct_evidence(tmp_path / "contradictory", (contradictory, raw[1]), index, recipes, protocol_sha256=H64)
    incomplete_index = tuple(row for row in index if not (row["stack_id"] == "P2" and row["target_class"] == "NONWORKING"))
    with pytest.raises(artifacts.ArtifactError, match="working/nonworking"):
        artifacts.reconstruct_evidence(tmp_path / "incomplete-index", raw, incomplete_index, recipes, protocol_sha256=H64)
