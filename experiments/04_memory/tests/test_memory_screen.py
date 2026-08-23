from __future__ import annotations

import importlib
import hashlib
import inspect
import json
from pathlib import Path

import pytest


def _screen() -> object:
    return importlib.import_module("experiments.04_memory.src.memory_screen")


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]


def test_screen_writes_exact_matrix_with_equal_information_and_real_comparators(tmp_path: Path) -> None:
    screen = _screen()
    output = tmp_path / "screen"
    screen.run_screen(output, seeds=screen.SEEDS, implementation_git_sha="0" * 40)

    root_manifest = json.loads((output / "raw" / "raw-manifest.json").read_text(encoding="ascii"))
    assert root_manifest["implementation_git_sha"] == "0" * 40
    assert len(root_manifest["implementation_source_sha256"]) == 64
    assert len(root_manifest["protocol_config_sha256"]) == 64

    bundles = sorted((output / "raw" / "bundles").iterdir())
    assert len(bundles) == 36
    assert {path.name.split(".")[0] for path in bundles} == set(screen.VARIANTS)
    for bundle in bundles:
        manifest = json.loads((bundle / "bundle-manifest.json").read_text(encoding="ascii"))
        assert manifest["disposition"] == "COMPLETE"
        assert manifest["claim_status"] == "ENGINEERING_NONCONFIRMATORY"
        assert manifest["implementation_git_sha"] == root_manifest["implementation_git_sha"]
        assert manifest["implementation_source_sha256"] == root_manifest["implementation_source_sha256"]
        assert manifest["protocol_config_sha256"] == root_manifest["protocol_config_sha256"]
        assert len(_rows(bundle / "observation-trace.jsonl")) == 10
        assert len(_rows(bundle / "compiled-facts.jsonl")) >= 1
        assert len(_rows(bundle / "query-decisions.jsonl")) == 10
        assert len(_rows(bundle / "scorer-truth.jsonl")) == 10

    for seed in screen.SEEDS:
        hashes = {
            json.loads((output / "raw" / "bundles" / f"{variant}.seed-{seed}" / "bundle-manifest.json").read_text())["observation_trace_sha256"]
            for variant in screen.VARIANTS
        }
        assert len(hashes) == 1

    aggregate = json.loads((output / "derived" / "aggregate.json").read_text(encoding="ascii"))
    by_variant = {row["variant_id"]: row for row in aggregate["variants"]}
    assert by_variant["M4"]["correct_rate"] > by_variant["M0"]["correct_rate"]
    assert by_variant["V0"]["correct_rate"] > 0.0
    assert by_variant["M4"]["correct_rate"] >= by_variant["H0"]["correct_rate"]
    assert by_variant["M5"]["stale_wrong_composite"] <= by_variant["M4"]["stale_wrong_composite"]
    assert by_variant["M6"]["ambiguous_retrieval_rate"] >= by_variant["M5"]["ambiguous_retrieval_rate"]
    assert by_variant["M6"]["fuzzy_vector_candidate_count"] == 32
    assert by_variant["M6"]["fuzzy_vector_candidate_hit_count"] + by_variant["M6"]["fuzzy_vector_candidate_miss_count"] == 32
    assert by_variant["M5"]["fuzzy_vector_candidate_hit_count"] is None


def test_runner_has_no_truth_input_and_reconstruction_is_byte_equal(tmp_path: Path) -> None:
    screen = _screen()
    assert tuple(inspect.signature(screen.run_variant).parameters) == ("variant_id", "seed", "observations")
    output = tmp_path / "screen"
    clean = tmp_path / "clean"
    screen.run_screen(output, seeds=screen.SEEDS, implementation_git_sha="0" * 40)
    screen.reconstruct_screen(output / "raw", clean)

    for name in ("aggregate.json", "annotations.json", "recipe.json", "RESULTS.md"):
        assert (output / "derived" / name).read_bytes() == (clean / name).read_bytes()

    annotations = json.loads((output / "derived" / "annotations.json").read_text(encoding="ascii"))
    assert annotations["selection_rule"] == "FIRST_CANONICAL_WORKING_AND_NONWORKING_PER_VARIANT_WHEN_OBSERVED"
    assert {row["class"] for row in annotations["samples"]} >= {"WORKING", "NONWORKING"}


def test_manifest_tamper_and_truth_leak_fail_closed(tmp_path: Path) -> None:
    screen = _screen()
    output = tmp_path / "screen"
    screen.run_screen(output, seeds=screen.SEEDS, implementation_git_sha="0" * 40)
    bundle = output / "raw" / "bundles" / f"M4.seed-{screen.SEEDS[0]}"
    decisions = bundle / "query-decisions.jsonl"
    decisions.write_bytes(decisions.read_bytes() + b"{}\n")
    try:
        screen.reconstruct_screen(output / "raw", tmp_path / "clean")
    except screen.ScreenError as error:
        assert "hash" in str(error) or "manifest" in str(error)
    else:
        raise AssertionError("tampered bundle reconstructed")


def test_m6_and_v0_use_real_deterministic_retrieval() -> None:
    screen = _screen()
    observations, _ = screen.generate_seed(screen.SEEDS[0])
    duplicate_ids = {
        row["fact_id"]
        for row in next(item for item in observations if item["query_id"] == "DUPLICATE_IDENTITY")["delivered_facts"]
    }
    for variant in ("M6", "V0"):
        _, decisions = screen.run_variant(variant, screen.SEEDS[0], observations)
        duplicate = next(row for row in decisions if row["query_id"] == "DUPLICATE_IDENTITY")
        assert duplicate["retrieval_channel"] in {"TYPED_LEXICAL_VECTOR_UNION_V3", "SIGNED_HASH_VECTOR_V3"}
        assert set(duplicate["retrieval_fact_ids"]) >= duplicate_ids


def test_v2_worlds_vary_identity_order_staleness_and_confidence() -> None:
    screen = _screen()
    generated = [screen.generate_seed(seed) for seed in screen.SEEDS]
    observations = [rows for rows, _ in generated]
    truths = [rows for _, rows in generated]

    reachable_answers = {
        next(row for row in rows if row["query_id"] == "REACHABLE_VALVE")["expected_answer"]
        for rows in truths
    }
    duplicate_orders = {
        tuple(fact["subject_id"] for fact in next(row for row in rows if row["query_id"] == "DUPLICATE_IDENTITY")["delivered_facts"])
        for rows in observations
    }
    pose_answers = {
        next(row for row in rows if row["query_id"] == "POSE_USABLE")["expected_answer"]
        for rows in truths
    }
    confidence_answers = {
        next(row for row in rows if row["query_id"] == "CONFLICTS_UNKNOWN")["expected_answer"]
        for rows in truths
    }
    assert all(len(values) > 1 for values in (reachable_answers, duplicate_orders, pose_answers, confidence_answers))


def test_h0_uses_independent_flat_log_query_path(monkeypatch: pytest.MonkeyPatch) -> None:
    screen = _screen()
    observations, _ = screen.generate_seed(screen.SEEDS[0])

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("H0 reused the graph/fact path")

    monkeypatch.setattr(screen, "_facts_for", forbidden)
    monkeypatch.setattr(screen, "_answer", forbidden)
    compiled, decisions = screen.run_variant("H0", screen.SEEDS[0], observations)
    assert len(decisions) == 10
    assert compiled and {row["record_kind"] for row in compiled} == {"FLAT_EVENT"}


def test_v0_answers_from_retrieved_snippets_and_m6_consumes_closed_union(monkeypatch: pytest.MonkeyPatch) -> None:
    screen = _screen()
    observations, _ = screen.generate_seed(screen.SEEDS[0])
    calls: list[str] = []
    for name in ("_typed_retrieve", "_lexical_retrieve", "_vector_retrieve"):
        original = getattr(screen, name)
        monkeypatch.setattr(screen, name, lambda *args, _name=name, _original=original, **kwargs: (calls.append(_name), _original(*args, **kwargs))[1])
    _, v0 = screen.run_variant("V0", screen.SEEDS[0], observations)
    _, m6 = screen.run_variant("M6", screen.SEEDS[0], observations)
    failure = next(row for row in v0 if row["query_id"] == "LAST_FAILURE_REASON")
    assert failure["answer"] != "UNKNOWN" and failure["cited_fact_ids"] == failure["retrieval_fact_ids"]
    assert all(tuple(row["retrieval_channels"]) == ("TYPED", "LEXICAL", "VECTOR") for row in m6)
    assert {"_typed_retrieve", "_lexical_retrieve", "_vector_retrieve"} <= set(calls)

    changed = [dict(row) for row in observations]
    target = next(row for row in changed if row["query_id"] == "LAST_FAILURE_REASON")
    target["delivered_facts"] = [dict(target["delivered_facts"][0], value="OPEN_DOOR:FAILED:JAMMED")]
    _, changed_m6 = screen.run_variant("M6", screen.SEEDS[0], changed)
    before = next(row for row in m6 if row["query_id"] == "LAST_FAILURE_REASON")
    after = next(row for row in changed_m6 if row["query_id"] == "LAST_FAILURE_REASON")
    assert before["answer"] != after["answer"]
    assert before["retrieval_fact_ids"] == after["retrieval_fact_ids"]


def test_v1_evidence_has_machine_readable_invalid_comparator_supersession() -> None:
    marker = Path("experiments/04_memory/ENGINEERING_FIRST_RUN_SUPERSESSION.json")
    value = json.loads(marker.read_text(encoding="ascii"))
    assert value["disposition"] == "SUPERSEDED_INVALID_COMPARATORS"
    assert value["preserved_evidence_tree_sha256"] == "254ce7d39da43dc2a34aee91f6af3e87e91fcfca38d8276aa28288600638e76e"
    assert value["replacement_evidence_root"] == "results/engineering-first-run-v2"


def test_correct_fresh_pose_action_is_not_scored_as_stale() -> None:
    screen = _screen()
    observations, truths = screen.generate_seed(screen.SEEDS[0])
    facts, decisions = screen.run_variant("M5", screen.SEEDS[0], observations)
    pose = next(row for row in decisions if row["query_id"] == "POSE_USABLE")
    truth = next(row for row in truths if row["query_id"] == "POSE_USABLE")
    assert (pose["answer"], pose["decision"]) == (truth["expected_answer"], truth["expected_decision"]) == ("USABLE", "ACT")
    assert screen._score(decisions, truths, facts)["stale_action_rate"] == 0.0


def test_v3_fuzzy_identity_tokens_are_preregistered_not_outcome_selected() -> None:
    screen = _screen()
    expected = tuple(
        hashlib.sha256(f"exp04-fuzzy-v3:{index}".encode("ascii")).hexdigest()[:12]
        for index in range(16)
    )
    assert screen.FUZZY_ALIAS_TOKENS == expected
    assert screen.FUZZY_SEED_SLOTS == (1, 3)

    for slot in screen.FUZZY_SEED_SLOTS:
        seed = screen.SEEDS[slot]
        observations, _ = screen.generate_seed(seed)
        duplicate = next(row for row in observations if row["query_id"] == "DUPLICATE_IDENTITY")
        facts = duplicate["delivered_facts"]
        world = screen._world_for_seed(seed)
        alternate = [row for row in facts if row["subject_id"] == world.alternate_valve_id]
        assert tuple(row["value"] for row in alternate) == expected
        assert len([row for row in facts if row["subject_id"] == world.primary_valve_id]) == 8


def test_v3_fuzzy_identity_measures_vector_membership_hits_and_misses() -> None:
    screen = _screen()
    total_hits = 0
    total_candidates = 0
    for slot in screen.FUZZY_SEED_SLOTS:
        seed = screen.SEEDS[slot]
        observations, _ = screen.generate_seed(seed)
        duplicate = next(row for row in observations if row["query_id"] == "DUPLICATE_IDENTITY")
        facts = duplicate["delivered_facts"]
        world = screen._world_for_seed(seed)
        alternate_ids = {row["fact_id"] for row in facts if row["subject_id"] == world.alternate_valve_id}
        typed_ids = {row["fact_id"] for row in screen._typed_retrieve("DUPLICATE_IDENTITY", facts)}
        lexical = screen._lexical_retrieve("DUPLICATE_IDENTITY", facts)
        vector_ids = {row["fact_id"] for row in screen._vector_retrieve("DUPLICATE_IDENTITY", facts)}
        assert typed_ids == set()
        assert {row["subject_id"] for row in lexical} == {world.primary_valve_id}
        total_hits += len(vector_ids & alternate_ids)
        total_candidates += len(alternate_ids)
    assert total_candidates == 32
    assert 0 <= total_hits < total_candidates

    exact_observations, _ = screen.generate_seed(screen.SEEDS[0])
    exact = next(row for row in exact_observations if row["query_id"] == "DUPLICATE_IDENTITY")
    exact_ids = {row["fact_id"] for row in exact["delivered_facts"]}
    exact_vector_ids = {row["fact_id"] for row in screen._vector_retrieve("DUPLICATE_IDENTITY", exact["delivered_facts"])}
    assert exact_ids <= exact_vector_ids


def test_v3_vector_channel_ablation_is_mechanical_without_changing_m5_nonidentity(monkeypatch: pytest.MonkeyPatch) -> None:
    screen = _screen()
    seed = screen.SEEDS[screen.FUZZY_SEED_SLOTS[0]]
    observations, _ = screen.generate_seed(seed)
    _, m5 = screen.run_variant("M5", seed, observations)
    _, m6 = screen.run_variant("M6", seed, observations)
    m5_duplicate = next(row for row in m5 if row["query_id"] == "DUPLICATE_IDENTITY")
    m6_duplicate = next(row for row in m6 if row["query_id"] == "DUPLICATE_IDENTITY")
    assert m5_duplicate["retrieval_channels"] == ("TYPED", "LEXICAL")
    assert m5_duplicate["answer"] == "UNKNOWN"
    vector_ids = {
        row["fact_id"]
        for row in screen._vector_retrieve(
            "DUPLICATE_IDENTITY",
            next(row for row in observations if row["query_id"] == "DUPLICATE_IDENTITY")["delivered_facts"],
        )
    }
    assert set(m6_duplicate["retrieval_fact_ids"]) == set(m5_duplicate["retrieval_fact_ids"]) | vector_ids

    monkeypatch.setattr(screen, "_vector_retrieve", lambda *_args, **_kwargs: ())
    _, ablated = screen.run_variant("M6", seed, observations)
    ablated_duplicate = next(row for row in ablated if row["query_id"] == "DUPLICATE_IDENTITY")
    assert ablated_duplicate["retrieval_fact_ids"] == m5_duplicate["retrieval_fact_ids"]
    assert [row for row in m5 if row["query_id"] != "DUPLICATE_IDENTITY"] == [
        row for row in screen.run_variant("M5", seed, observations)[1]
        if row["query_id"] != "DUPLICATE_IDENTITY"
    ]


def test_v3_metrics_retain_fuzzy_vector_candidate_membership() -> None:
    screen = _screen()
    seed = screen.SEEDS[screen.FUZZY_SEED_SLOTS[0]]
    observations, truths = screen.generate_seed(seed)
    facts, decisions = screen.run_variant("M6", seed, observations)
    metrics = screen._score(decisions, truths, facts)
    assert metrics["fuzzy_vector_candidate_count"] == 16
    assert 0 <= metrics["fuzzy_vector_candidate_hit_count"] <= 16
    assert metrics["fuzzy_vector_candidate_miss_count"] == 16 - metrics["fuzzy_vector_candidate_hit_count"]


def test_v2_embedding_claim_has_narrow_machine_supersession() -> None:
    marker = Path("experiments/04_memory/ENGINEERING_FIRST_RUN_V2_EMBEDDING_SUPERSESSION.json")
    value = json.loads(marker.read_text(encoding="ascii"))
    assert value["disposition"] == "SUPERSEDED_EMBEDDING_SPECIFIC_CLAIM_ONLY"
    assert value["preserved_v2_evidence_tree_sha256"] == "7d2cb8aa4dfc5b7781294d76b6152a9d49e8c5e7793fbdd40924d93d0e0c295a"
    assert value["preserved_claims"] == ["M5_CONFIDENCE_HANDLING", "M5_STALENESS_HANDLING"]
    assert value["replacement_evidence_root"] == "results/engineering-first-run-v3"
