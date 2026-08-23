from __future__ import annotations

import importlib

import pytest

from reflect.rollout import sha256_json

from .helpers import config


evaluate = importlib.import_module("experiments.01_policy_control.src.evaluate")
PILOT_PROTOCOL_SHA256 = "8" * 64


def _resource(*, phase="pilot", complete=True):
    expected = ("shard-000",)
    completed = expected if complete else ()
    return evaluate.ResourceCompletionEvidence(
        phase, 1, PILOT_PROTOCOL_SHA256 if phase == "pilot" else "7" * 64,
        None if phase == "pilot" else PILOT_PROTOCOL_SHA256, "f" * 64,
        expected, completed, ("e" * 64,) if complete else (),
    )


def _base_manifest(predecessor="1" * 64):
    return evaluate.build_pilot_manifest(
        evaluate.PilotStage.BASE, revision=1, predecessor_sha256=predecessor,
        config_sha256="2" * 64, implementation_sha="3" * 40,
        parameter_sha256="4" * 64,
        survivors=("P1", "P2", "P3", "P4", "P5", "P6"), seeds=(10, 11, 12, 13),
    )


def _completion(stage, shard, *, failure=False):
    stack_offset = int(shard.stack_id[1:]) * 100
    return evaluate.PilotShardCompletion(
        stage, shard.shard_id, shard.episode_ids,
        f"{7000 + stack_offset + shard.seed:064x}", failure,
        ("EASIEST_RECOVERY_FAILURE",) if failure else (), (),
    )


def test_pilot_disposition_counts_only_strict_completed_prefix_and_seals_trigger() -> None:
    manifest = _base_manifest()
    shards = manifest.shards[:4]
    prefix = tuple(_completion(evaluate.PilotStage.BASE, shard, failure=index == 1) for index, shard in enumerate(shards[:2]))
    terminal = evaluate.StageTerminalDisposition(
        evaluate.PilotStage.BASE, shards[1].shard_id, "EASIEST_RECOVERY_FAILURE", prefix[-1].completion_sha256,
    )
    stopped = evaluate.pilot_disposition(manifest, completions=prefix, terminal_disposition=terminal)
    assert stopped.total_episode_count == 6
    assert stopped.completed_shard_ids == tuple(item.shard_id for item in shards[:2])
    with pytest.raises(ValueError, match="after|prefix|trigger"):
        evaluate.pilot_disposition(
            manifest,
            completions=prefix + (_completion(evaluate.PilotStage.BASE, shards[2]),),
            terminal_disposition=terminal,
        )
    with pytest.raises(ValueError, match="inventory"):
        bad = evaluate.PilotShardCompletion(
            evaluate.PilotStage.BASE, shards[0].shard_id, shards[0].episode_ids[:-1],
            "b" * 64, False, (), (),
        )
        evaluate.pilot_disposition(manifest, completions=(bad,))
    reuse_manifest = evaluate.PilotManifest(
        1, evaluate.PilotStage.BASE, "1" * 64, "2" * 64, "3" * 40,
        "4" * 64, manifest.shards, ("c" * 64,),
    )
    with pytest.raises(ValueError, match="reuse"):
        evaluate.pilot_disposition(
            reuse_manifest,
            completions=tuple(_completion(evaluate.PilotStage.BASE, shard) for shard in manifest.shards),
        )


def test_pilot_disposition_rejects_a_truncated_full_stage_manifest() -> None:
    manifest = _base_manifest()
    truncated = evaluate.PilotManifest(
        manifest.revision, manifest.stage, manifest.predecessor_sha256,
        manifest.config_sha256, manifest.implementation_sha, manifest.parameter_sha256,
        manifest.shards[:1], manifest.reuse_hashes,
    )
    with pytest.raises(ValueError, match="base manifest|full canonical"):
        evaluate.pilot_disposition(
            truncated, completions=(_completion(evaluate.PilotStage.BASE, truncated.shards[0]),),
        )


def _episodes(stage, survivors=("P1",)):
    conditions = ("tune-05-700-2", "tune-10-300-2", "tune-20-000-1")
    return tuple(
        evaluate.PilotEpisodeScore(stack, seed, condition, f"{1000 + seed * 20 + index:064x}", 0.2 + index, True)
        for stack in survivors for seed in range(4) for index, condition in enumerate(conditions)
    )


def _smoothness_rows():
    conditions = tuple(
        f"core-{rate:02d}-{latency:03d}-{moves}"
        for rate in (5, 10, 20) for latency in (0, 100, 300, 700) for moves in (1, 2)
    )
    return tuple(
        evaluate.SmoothnessEpisodeScore(
            "P1", evaluate.PilotStage.FINAL_FOUR, seed, condition,
            f"P1:{seed}:{condition}", f"{4000 + seed * 24 + index:064x}", 1.0, 1.0,
        )
        for seed in range(4) for index, condition in enumerate(conditions)
    )


def test_reproduction_requires_raw_inputs_frozen_rank_reuse_and_resource_evidence() -> None:
    vector = {"pd": [80.0, 8.0], "ik": 0.01, "p5_smoothness": 0.02}
    episodes = _episodes(evaluate.PilotStage.BASE)
    candidate = evaluate.evaluate_candidate(evaluate.PilotStage.BASE, vector, ("P1",), episodes)
    raw = evaluate.CandidateReproductionInput(
        evaluate.PilotStage.BASE, vector, ("P1",), episodes,
    )
    smoothness = _smoothness_rows()
    baseline = evaluate.compute_p1_smoothness_baseline(smoothness)
    resource = _resource()
    evaluate.verify_pilot_reproduction(
        (raw,), evaluate.candidate_evaluations_bytes((candidate,)), smoothness,
        baseline, resource_evidence=resource,
    )
    with pytest.raises((TypeError, ValueError), match="raw|evidence"):
        evaluate.verify_pilot_reproduction(
            (candidate,), evaluate.candidate_evaluations_bytes((candidate,)), smoothness,
            baseline, resource_evidence=resource,
        )
    forged_predecessor = evaluate.evaluate_candidate(
        evaluate.PilotStage.BASE, vector, ("P1",), tuple(reversed(episodes)),
    )
    ik_vector = {"pd": [80.0, 8.0], "ik": 0.001, "p5_smoothness": 0.02}
    wrong_reuse = evaluate.CandidateReproductionInput(
        evaluate.PilotStage.IK_0_001, ik_vector, ("P1",), episodes,
        forged_predecessor,
    )
    with pytest.raises(ValueError, match="predecessor"):
        evaluate.verify_pilot_reproduction(
            (wrong_reuse,), evaluate.candidate_evaluations_bytes((candidate,)), smoothness,
            baseline, resource_evidence=resource,
        )
    with pytest.raises(ValueError, match="resource"):
        evaluate.verify_pilot_reproduction(
            (raw,), evaluate.candidate_evaluations_bytes((candidate,)), smoothness,
            baseline, resource_evidence=_resource(complete=False),
        )
    with pytest.raises(ValueError, match="tie.rank"):
        evaluate.PilotCandidate(
            evaluate.PilotStage.IK_0_001,
            {"pd": [80.0, 8.0], "ik": 0.001, "p5_smoothness": 0.02},
            sha256_json({"pd": [80.0, 8.0], "ik": 0.001, "p5_smoothness": 0.02}),
            ("P1",), True, (), (), 0.0, 2, (),
        )


def test_smoothness_rejects_duplicate_seed_condition_even_with_unique_identity() -> None:
    rows = _smoothness_rows()
    item = rows[0]
    duplicate = evaluate.SmoothnessEpisodeScore(
        item.stack_id, item.stage, item.seed, item.condition_id,
        f"{item.episode_id}:duplicate", "9" * 64, item.jerk_p95,
        item.discontinuity_p95,
    )
    with pytest.raises(ValueError, match="24 core episodes"):
        evaluate.compute_p1_smoothness_baseline(rows + (duplicate,))


def test_anchor_is_always_ranked_with_zero_upper_before_take_two() -> None:
    bootstrap = evaluate.BootstrapDecision(10_000, 5, 0.99, (
        evaluate.BootstrapContrast("P2", tuple(range(32)), -0.2, -0.3, -0.10),
        evaluate.BootstrapContrast("P3", tuple(range(32)), 0.0, -0.05, 0.05),
    ))
    baseline = evaluate.P1SmoothnessBaseline((0, 1, 2, 3), ("x",), ("1" * 64,), (2.0,), (2.0,), 2.0, 2.0)
    def metrics(stack):
        return evaluate.GateMetrics(stack, 95, 100, 90, 100, 0, 0, 1, 5, 100, (3.0,), (3.0,))
    gates = tuple(evaluate.apply_gate(metrics(stack), baseline, config()) for stack in ("P1", "P2", "P3"))
    vector = {"pd": [80.0, 8.0], "ik": 0.01, "p5_smoothness": 0.02}
    episodes = _episodes(evaluate.PilotStage.BASE)
    candidate = evaluate.evaluate_candidate(evaluate.PilotStage.BASE, vector, ("P1",), episodes)
    raw = evaluate.CandidateReproductionInput(
        evaluate.PilotStage.BASE, vector, ("P1",), episodes,
    )
    smoothness = _smoothness_rows()
    pilot_proof = evaluate.verify_pilot_reproduction(
        (raw,), evaluate.candidate_evaluations_bytes((candidate,)), smoothness,
        evaluate.compute_p1_smoothness_baseline(smoothness),
        resource_evidence=_resource(),
    )
    with pytest.raises(TypeError):
        evaluate.PilotReproductionEvidence(1, "1" * 64, "2" * 64, "3" * 64, "4" * 64)
    result = evaluate.promotion_decision(
        bootstrap, gates, p1_valid=True, negative_control_valid=True,
        resource_evidence=_resource(phase="confirmation"),
        pilot_reproduction=pilot_proof,
    )
    assert result.promoted_stacks == ("P2", "P1")
    unbound_confirmation = evaluate.ResourceCompletionEvidence(
        "confirmation", 1, "7" * 64, "6" * 64, "f" * 64,
        ("shard-000",), ("shard-000",), ("e" * 64,),
    )
    with pytest.raises(ValueError, match="revision/protocol"):
        evaluate.promotion_decision(
            bootstrap, gates, p1_valid=True, negative_control_valid=True,
            resource_evidence=unbound_confirmation, pilot_reproduction=pilot_proof,
        )


def test_plots_require_shared_exact_condition_seed_domain() -> None:
    def row(stack, seed, condition="core-10-300-2"):
        return evaluate.PlotRow(stack, seed, condition, 10, 300, 2, "NONE", 0.2, 0.01, 1.0, 0.1, (0.1, 0.2))
    rendered = evaluate.render_svg_plots((row("P1", 7), row("P2", 7)), ("P2",))
    assert set(rendered) == set(evaluate._PLOT_NAMES)
    with pytest.raises(ValueError, match="identical complete"):
        evaluate.render_svg_plots((row("P1", 7), row("P2", 8)), ("P2",))
    with pytest.raises(ValueError, match="identical complete"):
        evaluate.render_svg_plots(
            (row("P1", 7), row("P1", 8, "core-05-000-1"), row("P2", 7)),
            ("P2",),
        )
    with pytest.raises(ValueError, match="intended condition"):
        evaluate.render_svg_plots((row("P1", 7, "core-10-100-2"), row("P2", 7, "core-10-100-2")), ("P2",))
