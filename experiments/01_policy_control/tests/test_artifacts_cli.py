from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest


artifacts = importlib.import_module("experiments.01_policy_control.src.artifacts")
contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
evaluate = importlib.import_module("experiments.01_policy_control.src.evaluate")
timing = importlib.import_module("experiments.01_policy_control.src.timing")


H64 = "a" * 64
G40 = "b" * 40


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def test_iter_manifest_is_closed_canonical_and_p1_first(tmp_path: Path) -> None:
    config = Path(__file__).parents[1] / "configs/base.yaml"
    gate = tmp_path / "p3-gate.yaml"
    gate.write_text("schema_version: 1\n", encoding="utf-8")
    revision = tmp_path / "protocol" / "pilot-r1" / "revision-manifest.json"
    artifacts.prepare_manifest("revision", None, revision, config, gate, implementation_sha=G40)
    path = revision.with_name("base-manifest.json")
    artifacts.prepare_manifest("base", revision, path, config, gate, implementation_sha=G40)
    rows = tuple(artifacts.iter_manifest(path))
    assert tuple(dict.fromkeys(row.stack_id for row in rows)) == ("P1", "P2", "P3", "P4", "P5", "P6")
    assert rows[0].shard_id == "P1:base:000" and rows[0].episode_count == 3
    original = path.read_bytes()

    path.write_bytes(original + b" ")
    with pytest.raises(artifacts.ArtifactError, match="canonical"):
        tuple(artifacts.iter_manifest(path))

    duplicate = original.replace(b'"state":"READY"', b'"state":"READY","state":"READY"')
    path.write_bytes(duplicate)
    with pytest.raises(artifacts.ArtifactError, match="duplicate"):
        tuple(artifacts.iter_manifest(path))

    unknown = json.loads(original) | {"unknown": 1}
    path.write_bytes(_canonical(unknown))
    with pytest.raises(artifacts.ArtifactError, match="unknown"):
        tuple(artifacts.iter_manifest(path))


def test_preflight_uses_exact_caps_and_never_accepts_bool() -> None:
    mib = 1024 * 1024
    confirmation_rollouts = 5_016 * mib
    confirmation_wave = confirmation_rollouts + 128 * mib
    allowed = artifacts.preflight_resources(
        "confirmation", 10_288 * mib - confirmation_wave, 0, 0,
        confirmation_wave,
        24 * 3600, 240 * 3600,
    )
    assert allowed.disposition == "ALLOW"
    assert allowed.reserved_bytes == confirmation_wave
    assert allowed.reasons == ()
    refused = artifacts.preflight_resources(
        "confirmation", 10_288 * mib - confirmation_wave + 1, 0, 0,
        confirmation_wave - 1,
        24 * 3600 + 1, 240 * 3600,
    )
    assert refused.disposition == "REFUSE"
    assert refused.reasons == (
        "INSUFFICIENT_FREE_BYTES", "PHASE_BYTES_EXCEEDED", "WALL_TIME_EXCEEDED",
    )
    with pytest.raises(ValueError, match="integer"):
        artifacts.preflight_resources("pilot", True, 0, 0, 2 * mib, 0, 0)
    pilot_buckets = artifacts.preflight_resources(
        "pilot", 0, 32 * mib + 1, 64 * mib + 1, 182 * mib, 0, 0,
    )
    assert pilot_buckets.reasons == ("QUARANTINE_BYTES_EXCEEDED", "TEMP_BYTES_EXCEEDED")
    confirmation_buckets = artifacts.preflight_resources(
        "confirmation", 0, 32 * mib + 1, 64 * mib + 1,
        confirmation_wave, 0, 0,
    )
    assert confirmation_buckets.reasons == ("QUARANTINE_BYTES_EXCEEDED", "TEMP_BYTES_EXCEEDED")

    exact_shard = artifacts.preflight_resources(
        "pilot", 0, 0, 0, 134 * mib, 0, 0, rollout_count=3,
    )
    assert exact_shard.disposition == "ALLOW" and exact_shard.reserved_bytes == 134 * mib
    one_byte_short = artifacts.preflight_resources(
        "pilot", 0, 0, 0, 134 * mib - 1, 0, 0, rollout_count=3,
    )
    assert one_byte_short.reasons == ("INSUFFICIENT_FREE_BYTES",)
    with pytest.raises(artifacts.ArtifactError, match="revision rollout"):
        artifacts.preflight_resources(
            "pilot", 0, 0, 0, 4096 * mib, 0, 0, rollout_count=1009,
        )
    with pytest.raises(artifacts.ArtifactError, match="wave rollout"):
        artifacts.preflight_resources(
            "confirmation", 0, 0, 0, 6000 * mib, 0, 0, rollout_count=2509,
        )


def test_prepare_revision_publishes_seed_partition_then_runnable_six_stack_base(
    tmp_path: Path,
) -> None:
    config = Path(__file__).parents[1] / "configs/base.yaml"
    gate = tmp_path / "p3-gate.yaml"
    gate.write_text("schema_version: 1\n", encoding="utf-8")
    destination = tmp_path / "protocol" / "pilot-r1" / "revision-manifest.json"
    assert artifacts.prepare_manifest(
        "revision", None, destination, config, gate, implementation_sha=G40,
    ) == destination
    seed_path = destination.with_name("pilot-seeds.json")
    seed = artifacts.load_seed_manifest(seed_path)
    assert seed["partition"] == {
        "evaluation_seed_ids": [4, 5, 6, 7], "tuning_seed_ids": [0, 1, 2, 3],
    }
    assert seed["accepted_count"] == 8 and len(seed["scenarios"]) == 8
    assert tuple(artifacts.iter_manifest(destination)) == ()
    base = destination.with_name("base-manifest.json")
    assert artifacts.prepare_manifest(
        "base", destination, base, config, gate, implementation_sha=G40,
    ) == base
    shards = tuple(artifacts.iter_manifest(base))
    assert len(shards) == 24
    assert tuple(dict.fromkeys(item.stack_id for item in shards)) == ("P1", "P2", "P3", "P4", "P5", "P6")
    assert {item.episode_count for item in shards} == {3}
    assert artifacts.prepare_manifest(
        "revision", None, destination, config, gate, implementation_sha=G40,
    ) == destination


def test_protocol_loader_rejects_unbound_stage_parameter_resource_and_seed_data(
    tmp_path: Path,
) -> None:
    config = Path(__file__).parents[1] / "configs/base.yaml"
    gate = tmp_path / "p3-gate.yaml"
    gate.write_text("schema_version: 1\n", encoding="utf-8")
    revision = tmp_path / "protocol" / "pilot-r1" / "revision-manifest.json"
    artifacts.prepare_manifest("revision", None, revision, config, gate, implementation_sha=G40)
    base = revision.with_name("base-manifest.json")
    artifacts.prepare_manifest("base", revision, base, config, gate, implementation_sha=G40)
    original = json.loads(base.read_text(encoding="utf-8"))

    arbitrary_vector = original | {
        "parameter_vector": {"pd": [77.0, 7.0], "ik": 0.01, "p5_smoothness": 0.02},
    }
    arbitrary_vector["parameter_hash"] = hashlib.sha256(
        json.dumps(arbitrary_vector["parameter_vector"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    arbitrary_conditions = json.loads(json.dumps(original))
    arbitrary_conditions["shards"][0]["condition_ids"] = ["a", "b", "c"]
    arbitrary_conditions["shards"][0]["output_identities"] = [
        f"P1-{condition}-00000000" for condition in ("a", "b", "c")
    ]
    arbitrary_configuration = json.loads(json.dumps(original))
    arbitrary_configuration["shards"][0]["configuration_hash"] = "f" * 64

    mutations = (
        ("null predecessor", original | {"predecessor_sha256": None}),
        ("predecessor chain", original | {"predecessor_sha256": "f" * 64}),
        ("parameter hash", original | {"parameter_hash": "f" * 64}),
        ("resource limits", original | {"resource_limits": {}}),
        ("stage", original | {"stage": "invented"}),
        ("seed manifest", original | {"seed_manifest_sha256": "f" * 64}),
        ("parameter vector", arbitrary_vector),
        ("condition domain", arbitrary_conditions),
        ("configuration hash", arbitrary_configuration),
    )
    for label, mutation in mutations:
        candidate = base.with_name(f"bad-{label.replace(' ', '-')}.json")
        candidate.write_bytes(_canonical(mutation))
        with pytest.raises(artifacts.ArtifactError, match=label):
            artifacts.load_protocol_manifest(candidate)

    seed_path = revision.with_name("pilot-seeds.json")
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    seed["scenarios"][0]["scenario_sha256"] = "f" * 64
    seed_path.write_bytes(_canonical(seed))
    with pytest.raises(artifacts.ArtifactError, match="scenario"):
        artifacts.load_protocol_manifest(base)


def test_protocol_loader_requires_p1_ordered_subset_then_preserves_survivors(
    tmp_path: Path,
) -> None:
    config = Path(__file__).parents[1] / "configs/base.yaml"
    gate = tmp_path / "p3-gate.yaml"
    gate.write_text("schema_version: 1\n", encoding="utf-8")
    revision = tmp_path / "protocol" / "pilot-r1" / "revision-manifest.json"
    artifacts.prepare_manifest("revision", None, revision, config, gate, implementation_sha=G40)
    base = revision.with_name("base-manifest.json")
    artifacts.prepare_manifest("base", revision, base, config, gate, implementation_sha=G40)
    base_row = json.loads(base.read_text(encoding="utf-8"))

    def stage_row(stage: str, predecessor: Path, stacks: tuple[str, ...], pd: list[float]) -> dict[str, object]:
        row = json.loads(json.dumps(base_row))
        row["stage"] = stage
        row["predecessor_sha256"] = hashlib.sha256(predecessor.read_bytes()).hexdigest()
        row["parameter_vector"]["pd"] = pd
        row["parameter_hash"] = hashlib.sha256(
            json.dumps(row["parameter_vector"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        row["shards"] = [item for item in row["shards"] if item["stack_id"] in stacks]
        return row

    no_anchor = base.with_name("pd-60-no-anchor-manifest.json")
    no_anchor.write_bytes(_canonical(stage_row("pd_60_6", base, ("P2", "P3"), [60.0, 6.0])))
    with pytest.raises(artifacts.ArtifactError, match="P1.*ordered subset|survivor domain"):
        artifacts.load_protocol_manifest(no_anchor)

    pd_60 = base.with_name("pd-60-manifest.json")
    pd_60.write_bytes(_canonical(stage_row("pd_60_6", base, ("P1", "P3", "P6"), [60.0, 6.0])))
    assert tuple(dict.fromkeys(row["stack_id"] for row in artifacts.load_protocol_manifest(pd_60)["shards"])) == (
        "P1", "P3", "P6",
    )

    changed = base.with_name("pd-100-changed-survivors.json")
    changed.write_bytes(_canonical(stage_row("pd_100_10", pd_60, ("P1", "P2", "P3", "P6"), [100.0, 10.0])))
    with pytest.raises(artifacts.ArtifactError, match="survivor domain"):
        artifacts.load_protocol_manifest(changed)


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
    record = replace(record, metrics=dict(record.metrics) | {
        "protocol_sha256": H64, "source_sha256": H64,
    })
    destination = tmp_path / record.events[0].rollout_id
    spec = artifacts.RolloutSpec(
        destination.name, "P1", scenario.seed, condition.condition_id,
        configuration_hash, H64, H64, scenario_record.identity_sha256,
        2 * 1024 * 1024,
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


def test_rollout_binding_is_mandatory_and_directory_publication_is_no_replace(
    tmp_path: Path,
) -> None:
    cfg = contracts.load_config(Path(__file__).parents[1] / "configs/base.yaml")
    scenario_record = evaluate.generate_scenario(19, cfg)
    condition = evaluate.core_conditions(cfg)[0]
    configuration_hash = evaluate.sha256_json(timing.scheduler_config(cfg))
    identity = evaluate.EpisodeIdentity(
        G40, True, None, H64, "test", "cpu", None, "3.11", {"mujoco": "3.12.0"},
        configuration_hash, {"arm": H64},
    )
    unbound = evaluate.run_episode(
        contracts.CommandStack.P1, condition, scenario_record, cfg, identity,
    )
    destination = tmp_path / unbound.events[0].rollout_id
    spec = artifacts.RolloutSpec(
        destination.name, "P1", scenario_record.seed, condition.condition_id,
        configuration_hash, H64, H64, scenario_record.identity_sha256,
    )
    with pytest.raises(artifacts.ArtifactError, match="protocol_sha256"):
        artifacts.publish_or_validate_skip(unbound, destination, spec)

    source = tmp_path / "source"
    source.mkdir()
    existing = tmp_path / "existing"
    existing.mkdir()
    inode = existing.stat().st_ino
    with pytest.raises(artifacts.ArtifactError, match="already exists"):
        artifacts._rename_directory_noreplace(source, existing)
    assert existing.stat().st_ino == inode and source.is_dir()

    link = tmp_path / "linked-rollout"
    link.symlink_to(existing, target_is_directory=True)
    bound = replace(unbound, metrics=dict(unbound.metrics) | {
        "protocol_sha256": H64, "source_sha256": H64,
    })
    with pytest.raises(artifacts.ArtifactError, match="symlink"):
        artifacts.publish_or_validate_skip(bound, link, replace(spec, rollout_id=link.name))


def test_failure_disposition_is_closed_sorted_create_only_and_fsynced(tmp_path: Path) -> None:
    destination = tmp_path / "P1:base:000" / "failure-disposition.jsonl"
    base = {
        "schema_version": 1, "study_id": "reflect-lite-policy-control", "phase": "pilot",
        "revision": 1, "shard_id": "P1:base:000", "stack_id": "P1", "seed": 0,
        "condition_id": "core-10-300-2", "reason": "MISSING_OUTPUT",
        "started_at_utc": "2026-08-23T00:00:00Z", "finished_at_utc": "2026-08-23T00:00:01Z",
        "command_sha256": H64, "readable_output_sha256": None, "details_sha256": H64,
    }
    assert artifacts.publish_failure_disposition((base,), destination) == "published"
    assert artifacts.publish_failure_disposition((base,), destination) == "validated-and-skipped"
    with pytest.raises(artifacts.ArtifactError, match="keys"):
        artifacts.publish_failure_disposition((base | {"extra": True},), tmp_path / "bad.jsonl")
    duplicate = (base, dict(base))
    with pytest.raises(artifacts.ArtifactError, match="sorted and unique"):
        artifacts.publish_failure_disposition(duplicate, tmp_path / "duplicate.jsonl")


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
    with pytest.raises(artifacts.ImplementationDriftError, match="inventory"):
        snap.validate_after()


def test_implementation_snapshot_rejects_replace_refs_staged_and_ignored_additions(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (owned / "code.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "owned"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    (owned / "code.py").write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "replacement", "-q"], cwd=tmp_path, check=True)
    replacement_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    subprocess.run(["git", "replace", base_sha, replacement_sha], cwd=tmp_path, check=True)
    replacement_guard = artifacts.ImplementationSnapshot.capture(tmp_path, base_sha, (Path("owned"),))
    with pytest.raises(artifacts.ImplementationDriftError, match="differ"):
        replacement_guard.validate_before()
    subprocess.run(["git", "replace", "-d", base_sha], cwd=tmp_path, check=True)

    current_guard = artifacts.ImplementationSnapshot.capture(tmp_path, replacement_sha, (Path("owned"),))
    (owned / "staged.py").write_text("STAGED = True\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "owned/staged.py"], cwd=tmp_path, check=True)
    with pytest.raises(artifacts.ImplementationDriftError, match="inventory"):
        current_guard.validate_before()
    subprocess.run(["git", "reset", "--", "owned/staged.py"], cwd=tmp_path, check=True)
    (owned / "staged.py").unlink()
    (owned / "ignored.py").write_text("IGNORED = True\n", encoding="utf-8")
    with pytest.raises(artifacts.ImplementationDriftError, match="inventory"):
        current_guard.validate_after()


def test_implementation_snapshot_rejects_identical_inode_swap_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    owned = tmp_path / "owned"
    owned.mkdir()
    target = owned / "code.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "owned/code.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    snapshot = artifacts.ImplementationSnapshot.capture(tmp_path, sha, (Path("owned"),))
    swapped = False

    def swap_before_read(path: Path) -> None:
        nonlocal swapped
        if path == target and not swapped:
            swapped = True
            payload = path.read_bytes()
            path.unlink()
            path.write_bytes(payload)

    monkeypatch.setattr(artifacts, "_implementation_read_boundary", swap_before_read)
    with pytest.raises(artifacts.ImplementationDriftError, match="changed|identity"):
        snapshot.validate_before()


def test_rollout_derived_reconstruction_joins_annotations_renders_task11_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = contracts.load_config(Path(__file__).parents[1] / "configs/base.yaml")
    condition = next(item for item in evaluate.core_conditions(cfg) if item.condition_id == "core-10-300-2")
    scenario_record = evaluate.generate_scenario(23, cfg)
    configuration_hash = evaluate.sha256_json(timing.scheduler_config(cfg))
    raw_rows = []
    expected_plot_rows = []
    for stack in (contracts.CommandStack.P1, contracts.CommandStack.P2):
        identity = evaluate.EpisodeIdentity(
            G40, True, None, H64, "test", "cpu", None, "3.11", {"mujoco": "3.12.0"},
            configuration_hash, {"arm": H64},
        )
        record = evaluate.run_episode(stack, condition, scenario_record, cfg, identity)
        status = "fail" if stack is contracts.CommandStack.P1 else "pass"
        record = replace(
            record, metadata=replace(record.metadata, status=status),
            metrics=dict(record.metrics) | {"protocol_sha256": H64, "source_sha256": H64},
        )
        destination = tmp_path / "rollouts" / record.events[0].rollout_id
        spec = artifacts.RolloutSpec(
            destination.name, stack.value, scenario_record.seed, condition.condition_id,
            configuration_hash, H64, H64, scenario_record.identity_sha256,
        )
        artifacts.publish_or_validate_skip(record, destination, spec)
        raw = artifacts.raw_evidence_from_rollout(
            destination, revision=1, variant_id="base", anchor_id="P1",
            candidate_id=stack.value, rng_namespace="confirmation",
            policy_hz=condition.policy_hz, latency_ms=condition.latency_ms,
            move_count=condition.move_count, fault=condition.fault.value,
        )
        raw_rows.append(raw)
        expected_plot_rows.append(evaluate.PlotRow(
            stack.value, scenario_record.seed, condition.condition_id,
            condition.policy_hz, condition.latency_ms, condition.move_count,
            condition.fault.value, float(record.metrics["recovery_s"]),
            float(record.metrics["final_error_m"]), float(record.metrics["jerk_p95"]),
            float(record.metrics["age_p95_s"]),
            tuple(float(item) for item in record.metrics["raw_500hz"]["error_m"]), True,
        ))

    with pytest.raises(artifacts.ArtifactError, match="condition metadata"):
        artifacts.raw_evidence_from_rollout(
            tmp_path / "rollouts" / str(raw_rows[0]["episode_id"]),
            revision=1, variant_id="base", anchor_id="P1", candidate_id="P1",
            rng_namespace="confirmation", policy_hz=20, latency_ms=300,
            move_count=2, fault="NONE",
        )
    asymmetric = [dict(row["plot"]) for row in raw_rows]
    asymmetric.append(dict(asymmetric[0]) | {"seed": 999})
    with pytest.raises(artifacts.ArtifactError, match="exact.*domain|asymmetric"):
        artifacts._render_task11_plots(asymmetric, ("P2",))

    invalid_rows = []
    for stack, reason in (("P1", "PROCESS_TIMEOUT"), ("P2", "MISSING_OUTPUT")):
        invalid_rows.append(artifacts.raw_evidence_from_failure_disposition({
            "schema_version": 1, "study_id": "reflect-lite-policy-control",
            "phase": "pilot", "revision": 1, "shard_id": f"{stack}:base:023",
            "stack_id": stack, "seed": 23, "condition_id": condition.condition_id,
            "reason": reason, "started_at_utc": "2026-08-23T00:00:00Z",
            "finished_at_utc": "2026-08-23T00:00:01Z", "command_sha256": H64,
            "readable_output_sha256": None, "details_sha256": H64,
        }, variant_id="base", anchor_id="P1", candidate_id=stack,
            rng_namespace="confirmation", protocol_sha256=H64,
            source_sha256="b" * 64, scenario_sha256=scenario_record.identity_sha256,
            config_sha256="c" * 64, code_sha256="d" * 64,
            dependency_sha256="e" * 64))
    assert all(
        all(row[name] is not None for name in (
            "protocol_sha256", "source_sha256", "scenario_sha256",
            "config_sha256", "code_sha256", "dependency_sha256", "input_sha256",
        ))
        for row in invalid_rows
    )
    changed_attempt = artifacts.raw_evidence_from_failure_disposition(
        invalid_rows[0]["failure"], variant_id="base", anchor_id="P1", candidate_id="P1",
        rng_namespace="confirmation", protocol_sha256="f" * 64,
        source_sha256="b" * 64, scenario_sha256=scenario_record.identity_sha256,
        config_sha256="c" * 64, code_sha256="d" * 64, dependency_sha256="e" * 64,
    )
    assert changed_attempt["input_sha256"] != invalid_rows[0]["input_sha256"]
    mixed_rows = (*raw_rows, *invalid_rows)
    mixed_annotations = artifacts.build_annotated_samples(mixed_rows)
    mixed_recipes = artifacts.build_plot_recipes(mixed_rows, ("P2",))
    null_attempt = json.loads(json.dumps(invalid_rows[0]))
    null_attempt["config_sha256"] = None
    null_rows = (raw_rows[0], null_attempt)
    with pytest.raises(artifacts.ArtifactError, match="retained evidence|invalid episode"):
        artifacts.reconstruct_evidence(
            tmp_path / "null-attempt-input", null_rows,
            artifacts.build_annotated_samples(null_rows),
            artifacts.build_plot_recipes(null_rows, ()), protocol_sha256=H64,
        )
    with pytest.raises(artifacts.ArtifactError, match="protocol"):
        artifacts.reconstruct_evidence(
            tmp_path / "wrong-protocol", mixed_rows, mixed_annotations, mixed_recipes,
            protocol_sha256="f" * 64,
        )
    mixed = tmp_path / "mixed-valid-invalid"
    artifacts.reconstruct_evidence(
        mixed, mixed_rows, mixed_annotations, mixed_recipes, protocol_sha256=H64,
    )
    retained_invalid = [
        json.loads(line) for line in (mixed / "raw-evidence.jsonl").read_bytes().splitlines()
        if json.loads(line)["validity"] == "DECLARED_INVALID"
    ]
    assert len(retained_invalid) == 2
    assert all(row["rollout"] is None and row["plot"] is None and row["failure"] for row in retained_invalid)

    annotations = artifacts.build_annotated_samples(raw_rows)
    recipes = artifacts.build_plot_recipes(raw_rows, ("P2",))
    clean = tmp_path / "clean"
    manifest = artifacts.reconstruct_evidence(
        clean, raw_rows, annotations, recipes, protocol_sha256=H64,
    )
    assert artifacts.validate_evidence_publication(clean) == manifest
    raw_payload = (clean / "raw-evidence.jsonl").read_bytes()
    annotation_rows = [json.loads(line) for line in (clean / "annotated-samples.jsonl").read_bytes().splitlines()]
    for annotation in (row for row in annotation_rows if row["label"] != "CLASS_NOT_OBSERVED"):
        span = annotation["source_ranges"][0]
        linked = json.loads(raw_payload[span["start"]:span["end"]])
        assert linked["episode_id"] == annotation["raw_links"][0]
        assert linked["rollout"]["observations"]
    expected_svgs = evaluate.render_svg_plots(expected_plot_rows, ("P2",))
    assert {name: (clean / name).read_bytes() for name in expected_svgs} == dict(expected_svgs)
    reordered = tmp_path / "reordered"
    reordered_manifest = artifacts.reconstruct_evidence(
        reordered, tuple(reversed(raw_rows)), tuple(reversed(annotations)), recipes,
        protocol_sha256=H64,
    )
    assert reordered_manifest == manifest
    for row in manifest["files"]:
        assert (reordered / row["path"]).read_bytes() == (clean / row["path"]).read_bytes()

    concurrent = tmp_path / "concurrent"
    entered, release = threading.Event(), threading.Event()
    original_boundary = artifacts._publication_boundary
    paused = False

    def pause_first_writer(name: str) -> None:
        nonlocal paused
        if not paused and name.startswith("file:"):
            paused = True
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(artifacts, "_publication_boundary", pause_first_writer)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            artifacts.reconstruct_evidence, concurrent, raw_rows, annotations, recipes,
            protocol_sha256=H64,
        )
        assert entered.wait(5)
        second = pool.submit(
            artifacts.reconstruct_evidence, concurrent, raw_rows, annotations, recipes,
            protocol_sha256=H64,
        )
        release.set()
        assert first.result(timeout=10) == manifest
        assert second.result(timeout=10) == manifest
    monkeypatch.setattr(artifacts, "_publication_boundary", original_boundary)
    assert not tuple(tmp_path.glob(".concurrent.analysis-stage-*"))
    assert artifacts.validate_evidence_publication(concurrent) == manifest

    tampered = json.loads(json.dumps(raw_rows[0]))
    tampered["rollout"]["metrics"]["recovery_s"] += 1.0
    with pytest.raises(artifacts.ArtifactError, match="plot row|digest"):
        artifacts.reconstruct_evidence(
            tmp_path / "tampered", (tampered, raw_rows[1]), annotations, recipes,
            protocol_sha256=H64,
        )
    with pytest.raises(artifacts.ArtifactError, match="working/nonworking"):
        artifacts.reconstruct_evidence(
            tmp_path / "incomplete-index", raw_rows, annotations[:-1], recipes,
            protocol_sha256=H64,
        )
    changed_recipe = list(recipes)
    changed_recipe[0] = dict(changed_recipe[0]) | {"transforms": ["CALLER_DEFINED"]}
    with pytest.raises(artifacts.ArtifactError, match="closed Task11"):
        artifacts.reconstruct_evidence(
            tmp_path / "changed-recipe", raw_rows, annotations, changed_recipe,
            protocol_sha256=H64,
        )

    interrupted = tmp_path / "interrupted"
    count = 0

    def crash_after_second_boundary(name: str) -> None:
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError(f"injected crash at {name}")

    monkeypatch.setattr(artifacts, "_publication_boundary", crash_after_second_boundary)
    with pytest.raises(RuntimeError, match="injected crash"):
        artifacts.reconstruct_evidence(
            interrupted, raw_rows, annotations, recipes, protocol_sha256=H64,
        )
    assert not interrupted.exists()
    assert not tuple(tmp_path.glob(".interrupted.analysis-stage-*"))
    monkeypatch.setattr(artifacts, "_publication_boundary", lambda _name: None)
    resumed = artifacts.reconstruct_evidence(
        interrupted, raw_rows, annotations, recipes, protocol_sha256=H64,
    )
    assert resumed == manifest
    assert artifacts.validate_evidence_publication(interrupted) == manifest
    for row in manifest["files"]:
        assert (interrupted / row["path"]).read_bytes() == (clean / row["path"]).read_bytes()

    process_interrupted = tmp_path / "interrupted-process"
    child_inputs = tmp_path / "child-inputs.json"
    child_inputs.write_bytes(_canonical({
        "raw": raw_rows, "annotations": annotations, "recipes": recipes,
    }))
    child = subprocess.run(
        [
            sys.executable, "-c",
            "import importlib,json,os,sys; "
            "a=importlib.import_module('experiments.01_policy_control.src.artifacts'); "
            "v=json.loads(open(sys.argv[1],encoding='utf-8').read()); "
            "a._publication_boundary=lambda name: os._exit(91) if name.startswith('file:') else None; "
            "a.reconstruct_evidence(sys.argv[2],v['raw'],v['annotations'],v['recipes'],protocol_sha256=sys.argv[3])",
            str(child_inputs), str(process_interrupted), H64,
        ],
        cwd=Path(__file__).parents[3], check=False,
    )
    assert child.returncode == 91
    assert len(tuple(tmp_path.glob(".interrupted-process.analysis-stage-*"))) == 1
    resumed_after_process_death = artifacts.reconstruct_evidence(
        process_interrupted, raw_rows, annotations, recipes, protocol_sha256=H64,
    )
    assert resumed_after_process_death == manifest
    stale_quarantine = tmp_path / ".interrupted-process.analysis-quarantine"
    quarantined_stages = tuple(stale_quarantine.iterdir())
    assert len(quarantined_stages) == 1 and quarantined_stages[0].is_dir()
    quarantined_bytes = sum(
        entry.stat().st_size for stage in quarantined_stages for entry in stage.iterdir()
    )
    assert 0 < quarantined_bytes <= 64 * 1024 * 1024
    assert not tuple(tmp_path.glob(".interrupted-process.analysis-stage-*"))
    assert artifacts.validate_evidence_publication(process_interrupted) == manifest
