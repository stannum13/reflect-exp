from __future__ import annotations

import hashlib
import importlib

import numpy as np
import pytest

from .helpers import config


evaluate = importlib.import_module("experiments.01_policy_control.src.evaluate")


def _seed_rows(delta_by_stack):
    rows = []
    for stack, delta in (("P1", 0.0), *delta_by_stack.items()):
        for seed in range(32):
            rows.append(evaluate.SeedPrimary(stack, seed, 1.0 + 0.01 * seed + delta, f"{1000 + 100 * int(stack[1]) + seed:064x}"))
    return rows


def _baseline(value=2.0):
    return evaluate.P1SmoothnessBaseline((0, 1, 2, 3), ("a",), ("1" * 64,), (value,), (value,), value, value)


def _gate(stack, *, jerk=3.0, discontinuity=3.0):
    return evaluate.GateMetrics(stack, 95, 100, 90, 100, 0, 0, 1, 5, 100, (jerk,), (discontinuity,))


PILOT_PROTOCOL_SHA256 = "9" * 64


def _resource(*, phase="confirmation", complete=True):
    expected = ("shard-000",)
    completed = expected if complete else ()
    return evaluate.ResourceCompletionEvidence(
        phase, 1, PILOT_PROTOCOL_SHA256 if phase == "pilot" else "8" * 64,
        None if phase == "pilot" else PILOT_PROTOCOL_SHA256, "f" * 64,
        expected, completed, ("e" * 64,) if complete else (),
    )


def _pilot_reproduction():
    conditions = ("tune-05-700-2", "tune-10-300-2", "tune-20-000-1")
    episodes = tuple(
        evaluate.PilotEpisodeScore(
            "P1", seed, condition, f"{1000 + seed * 3 + index:064x}", 0.2, True,
        )
        for seed in range(4) for index, condition in enumerate(conditions)
    )
    vector = {"pd": [80.0, 8.0], "ik": 0.01, "p5_smoothness": 0.02}
    candidate = evaluate.evaluate_candidate(evaluate.PilotStage.BASE, vector, ("P1",), episodes)
    raw = evaluate.CandidateReproductionInput(
        evaluate.PilotStage.BASE, vector, ("P1",), episodes,
    )
    core = tuple(
        f"core-{rate:02d}-{latency:03d}-{moves}"
        for rate in (5, 10, 20) for latency in (0, 100, 300, 700) for moves in (1, 2)
    )
    smoothness = tuple(
        evaluate.SmoothnessEpisodeScore(
            "P1", evaluate.PilotStage.FINAL_FOUR, seed, condition,
            f"P1:{seed}:{condition}", f"{3000 + seed * 24 + index:064x}", 1.0, 1.0,
        )
        for seed in range(4) for index, condition in enumerate(core)
    )
    baseline = evaluate.compute_p1_smoothness_baseline(smoothness)
    return evaluate.verify_pilot_reproduction(
        (raw,), evaluate.candidate_evaluations_bytes((candidate,)), smoothness,
        baseline, resource_evidence=_resource(phase="pilot"),
    )


def test_paired_bootstrap_uses_exact_sha_pcg64_and_bonferroni_endpoints() -> None:
    frozen = "a" * 64
    rows = _seed_rows({"P2": -0.1, "P3": 0.02})
    decision = evaluate.paired_bootstrap(tuple(reversed(rows)), frozen)
    assert decision.resamples == 10_000 and decision.family_size == 5 and decision.confidence == 0.99
    p2 = decision.contrasts[0]
    assert p2.estimate_s == pytest.approx(-0.1) and p2.lower_s == pytest.approx(-0.1) and p2.upper_s == pytest.approx(-0.1)

    p3_values = np.asarray([item.recovery_s for item in sorted((item for item in rows if item.stack_id == "P3"), key=lambda item: item.seed)])
    p1_values = np.asarray([item.recovery_s for item in sorted((item for item in rows if item.stack_id == "P1"), key=lambda item: item.seed)])
    p3_deltas = p3_values - p1_values
    digest = hashlib.sha256((frozen + "bootstrap" + "P3").encode("ascii")).digest()
    rng = np.random.Generator(np.random.PCG64(int.from_bytes(digest[:16], "big")))
    samples = np.mean(p3_deltas[rng.integers(0, 32, size=(10_000, 32))], axis=1)
    assert decision.contrasts[1].lower_s == evaluate.nearest_rank(samples, 0.001)
    assert decision.contrasts[1].upper_s == evaluate.nearest_rank(samples, 0.999)


def test_gate_equality_passes_and_smoothness_above_multiplier_fails() -> None:
    cfg = config()
    passed = evaluate.apply_gate(_gate("P1"), _baseline(), cfg)
    assert passed.passes and not passed.reasons
    failed = evaluate.apply_gate(_gate("P2", jerk=np.nextafter(3.0, np.inf)), _baseline(), cfg)
    assert not failed.passes and failed.reasons == ("JERK",)


def test_promotion_is_bounded_ranked_and_deduplicates_wire_values() -> None:
    bootstrap = evaluate.BootstrapDecision(10_000, 5, 0.99, (
        evaluate.BootstrapContrast("P2", tuple(range(32)), -0.2, -0.3, -0.10),
        evaluate.BootstrapContrast("P3", tuple(range(32)), 0.0, -0.05, 0.05),
    ))
    gates = tuple(evaluate.apply_gate(_gate(stack), _baseline(), config()) for stack in ("P1", "P2", "P3"))
    decision = evaluate.promotion_decision(bootstrap, gates, p1_valid=True, negative_control_valid=True, resource_evidence=_resource(), pilot_reproduction=_pilot_reproduction())
    assert decision.scientific_result == "SUPPORTED"
    assert decision.promoted_stacks == ("P2", "P1") and len(decision.promoted_stacks) == 2

    only_p2 = evaluate.BootstrapDecision(10_000, 5, 0.99, (bootstrap.contrasts[0],))
    deduplicated = evaluate.promotion_decision(only_p2, gates[:2], p1_valid=True, negative_control_valid=True, resource_evidence=_resource(), pilot_reproduction=_pilot_reproduction())
    assert deduplicated.promoted_stacks == ("P2", "P1")
    assert deduplicated.promoted_wire_representations == ("JOINT_POSITION",)


def test_anchor_control_or_resource_failure_is_inconclusive() -> None:
    bootstrap = evaluate.BootstrapDecision(10_000, 5, 0.99, ())
    p1_gate = (evaluate.apply_gate(_gate("P1"), _baseline(), config()),)
    for kwargs in (
        {"p1_valid": False, "negative_control_valid": True, "resource_evidence": _resource(), "pilot_reproduction": _pilot_reproduction()},
        {"p1_valid": True, "negative_control_valid": False, "resource_evidence": _resource(), "pilot_reproduction": _pilot_reproduction()},
        {"p1_valid": True, "negative_control_valid": True, "resource_evidence": _resource(complete=False), "pilot_reproduction": _pilot_reproduction()},
    ):
        decision = evaluate.promotion_decision(bootstrap, p1_gate, **kwargs)
        assert decision.scientific_result == "INCONCLUSIVE" and decision.lifecycle_state == "STOPPED"


def test_not_supported_requires_every_valid_interval_to_exclude_benefit() -> None:
    bootstrap = evaluate.BootstrapDecision(10_000, 5, 0.99, (
        evaluate.BootstrapContrast("P2", tuple(range(32)), 0.0, -0.09, 0.05),
        evaluate.BootstrapContrast("P3", tuple(range(32)), 0.01, -0.08, 0.06),
    ))
    gates = tuple(evaluate.apply_gate(_gate(stack), _baseline(), config()) for stack in ("P1", "P2", "P3"))
    decision = evaluate.promotion_decision(bootstrap, gates, p1_valid=True, negative_control_valid=True, resource_evidence=_resource(), pilot_reproduction=_pilot_reproduction())
    assert decision.scientific_result == "NOT_SUPPORTED" and decision.lifecycle_state == "COMPLETE"


def test_frozen_candidate_and_baseline_evidence_must_reproduce_exactly() -> None:
    conditions = ("tune-05-700-2", "tune-10-300-2", "tune-20-000-1")
    episodes = tuple(
        evaluate.PilotEpisodeScore("P1", seed, condition, f"{2000 + seed * 3 + index:064x}", 0.2 + index, True)
        for seed in range(4) for index, condition in enumerate(conditions)
    )
    vector = {"pd": [80.0, 8.0], "ik": 0.01, "p5_smoothness": 0.02}
    candidate = evaluate.evaluate_candidate(evaluate.PilotStage.BASE, vector, ("P1",), episodes)
    reproduction = evaluate.CandidateReproductionInput(
        evaluate.PilotStage.BASE, vector, ("P1",), tuple(reversed(episodes)),
    )
    conditions_core = tuple(f"core-{rate:02d}-{latency:03d}-{moves}" for rate in (5, 10, 20) for latency in (0, 100, 300, 700) for moves in (1, 2))
    smoothness = tuple(
        evaluate.SmoothnessEpisodeScore("P1", evaluate.PilotStage.FINAL_FOUR, seed, condition, f"P1:{seed}:{condition}", f"{3000 + seed * 24 + episode:064x}", seed + episode, seed + episode / 2)
        for seed in range(4) for episode, condition in enumerate(conditions_core)
    )
    baseline = evaluate.compute_p1_smoothness_baseline(tuple(reversed(smoothness)))
    frozen = evaluate.candidate_evaluations_bytes((candidate,))
    resource = _resource(phase="pilot")
    proof = evaluate.verify_pilot_reproduction((reproduction,), frozen, smoothness, baseline, resource_evidence=resource)
    assert proof.resource_disposition_sha256 == resource.disposition_sha256
    changed = list(smoothness)
    item = changed[0]
    changed[0] = evaluate.SmoothnessEpisodeScore(item.stack_id, item.stage, item.seed, item.condition_id, item.episode_id, "f" * 64, item.jerk_p95, item.discontinuity_p95)
    with pytest.raises(ValueError, match="baseline"):
        evaluate.verify_pilot_reproduction((reproduction,), frozen, changed, baseline, resource_evidence=resource)
