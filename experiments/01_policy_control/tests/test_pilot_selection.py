from __future__ import annotations

import importlib

import pytest
from reflect.rollout import sha256_json


evaluate = importlib.import_module("experiments.01_policy_control.src.evaluate")
PilotStage = evaluate.PilotStage


def _scores(survivors, score):
    return tuple(
        evaluate.StackSeedScore(stack, seed, tuple(f"{1000 + stack_index * 20 + seed * 3 + condition:064x}" for condition in range(3)), score)
        for stack_index, stack in enumerate(survivors)
        for seed in range(4)
    )


def _candidate(stage, survivors, score, tie_rank, *, feasible=True, reuse=()):
    vector = dict(next(item.parameter_vector for item in evaluate.pilot_candidates() if item.stage is stage))
    return evaluate.PilotCandidate(
        stage,
        vector,
        sha256_json(vector),
        tuple(survivors),
        feasible,
        tuple(reuse),
        _scores(survivors, score) if feasible else (),
        score if feasible else None,
        evaluate.pilot_stage_order().index(stage) + 1,
        () if feasible else ("MISSING_BUNDLE",),
    )


def _selection_evidence(*, p5_all_infeasible=False):
    survivors = ("P1", "P2", "P3", "P4", "P5", "P6")
    outcomes = tuple(evaluate.BaseStackOutcome(stack, 12, False) for stack in survivors)
    pd = (
        _candidate(PilotStage.BASE, survivors, 0.5, 1),
        _candidate(PilotStage.PD_60_6, survivors, 0.6, 2),
        _candidate(PilotStage.PD_100_10, survivors, 0.7, 3),
    )
    ik = (
        _candidate(PilotStage.IK_0_001, survivors, 0.6, 4),
        _candidate(PilotStage.IK_0_05, survivors, 0.7, 5),
    )
    reused_p5_hashes = tuple(
        digest for score in pd[0].stack_seed_scores if score.stack_id == "P5"
        for digest in score.condition_bundle_sha256s
    )
    p5 = (
        _candidate(PilotStage.BASE, ("P5",), 0.5, 1, feasible=not p5_all_infeasible, reuse=reused_p5_hashes),
        _candidate(PilotStage.P5_0_01, ("P5",), 0.6, 6, feasible=not p5_all_infeasible),
        _candidate(PilotStage.P5_0_04, ("P5",), 0.7, 7, feasible=not p5_all_infeasible),
    )
    return evaluate.derive_pilot_selection(outcomes, pd, ik, p5)


def _p1_manifest(stage, shard_count, episodes_per_shard, predecessor_sha="1" * 64):
    assert shard_count == 4
    expected_count = 26 if stage is PilotStage.FINAL_FOUR else 3
    assert episodes_per_shard == expected_count
    return evaluate.build_pilot_manifest(
        stage, revision=1, predecessor_sha256=predecessor_sha,
        config_sha256="2" * 64, implementation_sha="3" * 40,
        parameter_sha256="4" * 64,
        survivors=("P1", "P2", "P3", "P4", "P5", "P6"),
        seeds=(20, 21, 22, 23) if stage is PilotStage.FINAL_FOUR else (10, 11, 12, 13),
    )


def _completions(manifests, *, final_count=None, terminal_failure=False):
    shards = [(manifest.stage, shard) for manifest in manifests for shard in manifest.shards]
    if final_count is not None:
        shards = shards[:final_count]
    result = []
    for index, (stage, shard) in enumerate(shards):
        failure = terminal_failure and index == len(shards) - 1
        result.append(evaluate.PilotShardCompletion(
            stage, shard.shard_id, shard.episode_ids, f"{8000 + index:064x}",
            failure, ("EASIEST_RECOVERY_FAILURE",) if failure else (), (),
        ))
    return tuple(result)


def _complete_tuning_prefix():
    survivors = ("P1", "P2", "P3", "P4", "P5", "P6")
    result = []
    predecessor = "1" * 64
    for stage in evaluate.pilot_stage_order()[:-1]:
        manifest = evaluate.build_pilot_manifest(
            stage,
            revision=1,
            predecessor_sha256=predecessor,
            config_sha256="2" * 64,
            implementation_sha="3" * 40,
            parameter_sha256=f"{10 + len(result):064x}",
            survivors=survivors,
            seeds=(10, 11, 12, 13),
        )
        result.append(manifest)
        predecessor = __import__("hashlib").sha256(evaluate.pilot_manifest_bytes(manifest)).hexdigest()
    return tuple(result), predecessor


def test_pilot_stage_order_and_frozen_candidates() -> None:
    assert evaluate.pilot_stage_order() == (
        PilotStage.BASE, PilotStage.PD_60_6, PilotStage.PD_100_10,
        PilotStage.IK_0_001, PilotStage.IK_0_05,
        PilotStage.P5_0_01, PilotStage.P5_0_04, PilotStage.FINAL_FOUR,
    )
    assert [dict(candidate.parameter_vector) for candidate in evaluate.pilot_candidates()[:3]] == [
        {"pd": [80.0, 8.0], "ik": 0.01, "p5_smoothness": 0.02},
        {"pd": [60.0, 6.0], "ik": 0.01, "p5_smoothness": 0.02},
        {"pd": [100.0, 10.0], "ik": 0.01, "p5_smoothness": 0.02},
    ]


def test_all_survivor_episode_upper_bound_and_kill_counts() -> None:
    all_survivors = tuple(f"P{index}" for index in range(1, 7))
    counts = evaluate.expected_pilot_episode_counts(all_survivors)
    assert counts["by_stack"] == {"P1": 164, "P2": 164, "P3": 164, "P4": 164, "P5": 188, "P6": 164}
    assert counts["total"] == 1008
    assert evaluate.expected_pilot_episode_counts(("P1", "P3", "P4", "P5", "P6"), base_killed=("P2",))["by_stack"]["P2"] == 12
    assert evaluate.expected_pilot_episode_counts(("P1", "P2", "P3", "P4", "P6"), p5_all_smoothness_infeasible=True)["by_stack"]["P5"] == 84


def test_base_qualification_fixes_survivors_and_anchor_failure_stops() -> None:
    outcomes = tuple(evaluate.BaseStackOutcome(f"P{index}", 12, index == 4, ("DIVERGED",) if index == 4 else ()) for index in range(1, 7))
    result = evaluate.qualify_base(outcomes)
    assert result.survivors == ("P1", "P2", "P3", "P5", "P6") and result.killed_stacks == ("P4",)
    stopped = evaluate.qualify_base((evaluate.BaseStackOutcome("P1", 12, True),) + outcomes[1:])
    assert stopped.scientific_result == "INCONCLUSIVE" and stopped.lifecycle_state == "STOPPED"


def test_p1_shard_failure_stops_without_later_commands() -> None:
    manifest = _p1_manifest(PilotStage.BASE, 4, 3)
    for completed_shards, expected_count in enumerate((3, 6, 9, 12), start=1):
        completions = _completions((manifest,), final_count=completed_shards, terminal_failure=True)
        terminal = evaluate.StageTerminalDisposition(PilotStage.BASE, completions[-1].shard_id, "EASIEST_RECOVERY_FAILURE", completions[-1].completion_sha256)
        disposition = evaluate.pilot_disposition(manifest, completions=completions, terminal_disposition=terminal)
        assert disposition.scientific_result == "INCONCLUSIVE"
        assert disposition.lifecycle_state == "STOPPED"
        assert disposition.total_episode_count == expected_count
        assert disposition.later_stage_commands == () and not disposition.requires_final_four


def test_final_four_p1_failure_stops_before_other_stack_shards() -> None:
    prefix, predecessor = _complete_tuning_prefix()
    manifest = _p1_manifest(PilotStage.FINAL_FOUR, 4, 26, predecessor)
    prefix_completions = _completions(prefix)
    for completed_shards, final_four_count in enumerate((26, 52, 78, 104), start=1):
        final_completions = _completions((manifest,), final_count=completed_shards, terminal_failure=True)
        completions = prefix_completions + tuple(
            evaluate.PilotShardCompletion(item.stage, item.shard_id, item.completed_episode_ids, f"{9000 + index:064x}", item.scientific_failure, item.reasons, item.reuse_hashes)
            for index, item in enumerate(final_completions)
        )
        terminal = evaluate.StageTerminalDisposition(PilotStage.FINAL_FOUR, completions[-1].shard_id, "EASIEST_RECOVERY_FAILURE", completions[-1].completion_sha256)
        disposition = evaluate.pilot_disposition(
            manifest, prior_manifests=prefix, completions=completions,
            terminal_disposition=terminal, selection_evidence=_selection_evidence(),
        )
        assert disposition.scientific_result == "INCONCLUSIVE" and disposition.lifecycle_state == "STOPPED"
        assert disposition.final_four_episode_count == final_four_count
        assert disposition.remaining_final_four_stacks == ()


def test_selection_ties_use_frozen_order_and_shared_vector() -> None:
    survivors = ("P1", "P2", "P3", "P4", "P5", "P6")
    pd = evaluate.select_global_candidate((
        _candidate(PilotStage.BASE, survivors, 0.5, 1),
        _candidate(PilotStage.PD_60_6, survivors, 0.0, 2, feasible=False),
        _candidate(PilotStage.PD_100_10, survivors, 0.5, 3),
    ), survivors)
    ik = evaluate.select_global_candidate((
        _candidate(PilotStage.BASE, survivors, 0.5, 1),
        _candidate(PilotStage.IK_0_001, survivors, 0.5, 2),
        _candidate(PilotStage.IK_0_05, survivors, 0.5, 3),
    ), survivors)
    p5 = evaluate.select_p5_smoothness((
        _candidate(PilotStage.BASE, ("P5",), 0.5, 1),
        _candidate(PilotStage.P5_0_01, ("P5",), 0.5, 2),
        _candidate(PilotStage.P5_0_04, ("P5",), 0.5, 3),
    ))
    assert pd.parameter_vector["pd"] == [80.0, 8.0]
    assert ik.parameter_vector["ik"] == 0.01
    assert p5.parameter_vector["p5_smoothness"] == 0.02
    propagated = evaluate.pilot_candidates(selected_pd=(60.0, 6.0), selected_ik=0.001, selected_p5_smoothness=0.04)
    assert all(candidate.parameter_vector["pd"] == [60.0, 6.0] for candidate in propagated[3:])
    assert all(candidate.parameter_vector["ik"] == 0.001 for candidate in propagated[5:])
    assert propagated[-1].parameter_vector["p5_smoothness"] == 0.04


def test_candidate_evaluator_uses_three_condition_then_seed_then_stack_means() -> None:
    survivors = ("P1", "P2")
    conditions = ("tune-05-700-2", "tune-10-300-2", "tune-20-000-1")
    episodes = tuple(
        evaluate.PilotEpisodeScore(stack, seed, condition, f"{100 + stack_index * 20 + seed * 3 + condition_index:064x}", float(stack_index + seed + condition_index), True)
        for stack_index, stack in enumerate(survivors)
        for seed in range(4)
        for condition_index, condition in enumerate(conditions)
    )
    vector = {"pd": [80.0, 8.0], "ik": 0.01, "p5_smoothness": 0.02}
    candidate = evaluate.evaluate_candidate(PilotStage.BASE, vector, survivors, episodes)
    assert candidate.global_score == pytest.approx(3.0)
    invalid = list(episodes)
    invalid[-1] = evaluate.PilotEpisodeScore("P2", 3, conditions[-1], "9" * 64, None, False, "NONFINITE")
    pd_vector = dict(next(item.parameter_vector for item in evaluate.pilot_candidates() if item.stage is PilotStage.PD_60_6))
    rejected = evaluate.evaluate_candidate(PilotStage.PD_60_6, pd_vector, survivors, invalid)
    assert not rejected.feasible and rejected.global_score is None and "NONFINITE" in rejected.reasons[0]


def test_candidate_evaluations_are_complete_canonical_bytes() -> None:
    survivors = ("P1", "P2")
    candidates = (
        _candidate(PilotStage.BASE, survivors, 0.5, 1, reuse=("5" * 64,)),
        _candidate(PilotStage.PD_60_6, survivors, 0.0, 2, feasible=False),
    )
    payload = evaluate.candidate_evaluations_bytes(candidates)
    assert payload == evaluate.candidate_evaluations_bytes(candidates)
    for token in (
        b'"parameter_vector"', b'"parameter_hash"', b'"feasible"', b'"reuse_hashes"',
        b'"stack_seed_scores"', b'"global_score"', b'"tie_rank"', b'"reasons"',
    ):
        assert token in payload
    assert b'"global_score":null' in payload and b'"condition_bundle_sha256s"' in payload


def test_manifest_rejects_unbound_or_unsorted_episode_inventory() -> None:
    with pytest.raises(ValueError, match="sorted"):
        evaluate.PilotShard("P1:base:000", "P1", 0, ("b", "a"))
    with pytest.raises(ValueError, match="revision"):
        evaluate.PilotManifest(3, PilotStage.BASE, "1" * 64, "2" * 64, "3" * 40, "4" * 64, ())


def test_stage_builders_bind_hashes_sort_episodes_and_final_four_runs_once() -> None:
    survivors = ("P1", "P2", "P3", "P4", "P5", "P6")
    prefix, predecessor = _complete_tuning_prefix()
    tuning = prefix[0]
    assert len(tuning.shards) == 24 and sum(len(item.episode_ids) for item in tuning.shards) == 72
    final = evaluate.build_pilot_manifest(
        PilotStage.FINAL_FOUR,
        revision=1,
        predecessor_sha256=predecessor,
        config_sha256="2" * 64,
        implementation_sha="3" * 40,
        parameter_sha256="5" * 64,
        survivors=survivors,
        seeds=(20, 21, 22, 23),
    )
    assert len(final.shards) == 24 and sum(len(item.episode_ids) for item in final.shards) == 624
    disposition = evaluate.pilot_disposition(
        final, prior_manifests=prefix, completions=_completions((*prefix, final)),
        selection_evidence=_selection_evidence(),
    )
    assert disposition.total_episode_count == 1008 and disposition.final_four_episode_count == 624


def test_final_four_inventory_is_derived_from_all_p5_candidates() -> None:
    prefix, predecessor = _complete_tuning_prefix()
    selection = _selection_evidence(p5_all_infeasible=True)
    assert selection.survivors == ("P1", "P2", "P3", "P4", "P6")
    invalid = evaluate.build_pilot_manifest(
        PilotStage.FINAL_FOUR, revision=1, predecessor_sha256=predecessor,
        config_sha256="2" * 64, implementation_sha="3" * 40,
        parameter_sha256="5" * 64,
        survivors=("P1", "P2", "P3", "P4", "P5", "P6"), seeds=(20, 21, 22, 23),
    )
    with pytest.raises(ValueError, match="selection-derived"):
        evaluate.pilot_disposition(
            invalid, prior_manifests=prefix,
            completions=_completions((*prefix, invalid)), selection_evidence=selection,
        )


def test_p1_final_four_smoothness_baseline_is_two_stage_and_order_independent() -> None:
    conditions = tuple(f"core-{rate:02d}-{latency:03d}-{moves}" for rate in (5, 10, 20) for latency in (0, 100, 300, 700) for moves in (1, 2))
    rows = [
        evaluate.SmoothnessEpisodeScore("P1", PilotStage.FINAL_FOUR, seed, condition, f"P1:{seed}:{condition}", f"{5000 + seed * 24 + episode:064x}", seed + episode, 2 * seed + episode)
        for seed in range(4)
        for episode, condition in enumerate(conditions)
    ]
    first = evaluate.compute_p1_smoothness_baseline(rows)
    second = evaluate.compute_p1_smoothness_baseline(tuple(reversed(rows)))
    assert first == second
    assert first.seed_ids == (0, 1, 2, 3)
    assert first.jerk_p95 == evaluate.nearest_rank((item.jerk_p95 for item in rows), 0.95)
    assert first.discontinuity_p95 == evaluate.nearest_rank((item.discontinuity_p95 for item in rows), 0.95)
    assert len(first.episode_bundle_sha256s) == 96
