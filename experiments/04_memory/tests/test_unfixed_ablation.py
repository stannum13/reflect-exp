from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import pytest


def _module() -> object:
    return importlib.import_module("experiments.04_memory.src.unfixed_ablation")


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]


def test_frozen_matrix_and_runner_truth_boundary() -> None:
    experiment = _module()
    assert experiment.SEEDS == tuple(range(20263001, 20263065))
    assert experiment.VARIANTS == (
        "FIXED_M5", "LIVE_SEMANTIC", "LIVE_EPISODIC", "LIVE_SEPARATE",
    )
    assert tuple(inspect.signature(experiment.run_variant).parameters) == (
        "variant_id", "seed", "observation_stream",
    )

    observations, truth = experiment.generate_seed(7001)
    assert len(observations) == 4
    assert [row["mutation_kind"] for row in observations[1:]] == sorted(
        ("POSE_MOVE", "AVAILABILITY_CHANGE", "RESTRICTION_CHANGE"),
        key=lambda kind: [row["mutation_kind"] for row in observations[1:]].index(kind),
    )
    assert {row["mutation_kind"] for row in observations[1:]} == {
        "POSE_MOVE", "AVAILABILITY_CHANGE", "RESTRICTION_CHANGE",
    }
    assert len(truth) == 16
    assert all("expected_answer" not in row for row in observations)


def test_semantic_and_episodic_update_interventions_are_distinct() -> None:
    experiment = _module()
    observations, _ = experiment.generate_seed(7002)
    runs = {
        variant: experiment.run_variant(variant, 7002, observations)
        for variant in experiment.VARIANTS
    }
    final = {variant: snapshots[-1] for variant, (snapshots, _decisions) in runs.items()}

    assert final["FIXED_M5"]["semantic_sha256"] == final["LIVE_EPISODIC"]["semantic_sha256"]
    assert final["LIVE_SEMANTIC"]["semantic_sha256"] == final["LIVE_SEPARATE"]["semantic_sha256"]
    assert final["FIXED_M5"]["semantic_sha256"] != final["LIVE_SEPARATE"]["semantic_sha256"]

    assert final["FIXED_M5"]["episode_count"] == final["LIVE_SEMANTIC"]["episode_count"] == 0
    assert final["LIVE_EPISODIC"]["episode_count"] == final["LIVE_SEPARATE"]["episode_count"] == 1
    assert final["LIVE_EPISODIC"]["episodic_sha256"] == final["LIVE_SEPARATE"]["episodic_sha256"]


def test_control_checkpoint_is_equal_and_primary_decisions_are_twelve() -> None:
    experiment = _module()
    observations, _ = experiment.generate_seed(7003)
    decisions = {
        variant: experiment.run_variant(variant, 7003, observations)[1]
        for variant in experiment.VARIANTS
    }
    controls = {
        json.dumps(
            [{key: row[key] for key in ("query_id", "answer")} for row in rows if row["checkpoint"] == "CONTROL"],
            sort_keys=True,
        )
        for rows in decisions.values()
    }
    assert len(controls) == 1
    assert all(len([row for row in rows if row["checkpoint"] != "CONTROL"]) == 12 for rows in decisions.values())


def test_actual_run_has_complete_raw_matrix_and_byte_equal_reconstruction(tmp_path: Path) -> None:
    experiment = _module()
    output = tmp_path / "out"
    reconstructed = tmp_path / "reconstructed"
    experiment.run_experiment(output, implementation_git_sha="0" * 40, seeds=(7004, 7005))

    assert len(_jsonl(output / "raw" / "observation-streams.jsonl")) == 8
    assert len(_jsonl(output / "raw" / "scorer-truth.jsonl")) == 32
    assert len(_jsonl(output / "raw" / "memory-snapshots.jsonl")) == 32
    assert len(_jsonl(output / "raw" / "decisions.jsonl")) == 128
    assert len(_jsonl(output / "raw" / "scores.jsonl")) == 128

    experiment.reconstruct(output / "raw", reconstructed)
    expected = {
        "RESULTS.md", "annotations.json", "endpoint-data.csv", "evidence-manifest.json",
        "paired-effects.csv", "paired-effects.svg", "per-seed.csv", "variant-endpoints.svg",
    }
    assert expected <= {path.name for path in (output / "derived").iterdir()}
    for name in expected:
        assert (output / "derived" / name).read_bytes() == (reconstructed / name).read_bytes()

    result = json.loads((output / "derived" / "evidence-manifest.json").read_text(encoding="ascii"))
    assert result["bootstrap_draws"] == 20_000
    assert len(result["gates"]) == 6
    assert result["claim_scope"] == "INDICATIVE_SYNTHETIC"


def test_raw_tampering_fails_closed(tmp_path: Path) -> None:
    experiment = _module()
    output = tmp_path / "out"
    experiment.run_experiment(output, implementation_git_sha="0" * 40, seeds=(7006, 7007))
    decisions = output / "raw" / "decisions.jsonl"
    decisions.write_bytes(decisions.read_bytes() + b"{}\n")
    with pytest.raises(experiment.AblationError, match="hash|manifest|replay"):
        experiment.reconstruct(output / "raw", tmp_path / "bad")


def test_annotations_include_raw_working_and_nonworking_samples(tmp_path: Path) -> None:
    experiment = _module()
    output = tmp_path / "out"
    experiment.run_experiment(output, implementation_git_sha="0" * 40, seeds=(7008, 7009))
    annotations = json.loads((output / "derived" / "annotations.json").read_text(encoding="ascii"))
    assert annotations["selection_rule"] == "FIRST_CANONICAL_WORKING_AND_NONWORKING_PER_VARIANT"
    assert {row["class"] for row in annotations["samples"]} >= {"WORKING", "NONWORKING"}
    assert all("decision" in row and "truth" in row and "observation_sha256" in row for row in annotations["samples"])


def test_canonical_result_has_real_frozen_sha_and_invalid_predecessor_is_marked() -> None:
    canonical = Path("results/exp04-unfixed-memory-indicative-v2")
    invalid = Path("results/exp04-unfixed-memory-indicative-v1")
    evidence = json.loads((canonical / "derived" / "evidence-manifest.json").read_text(encoding="ascii"))
    provenance = json.loads((canonical / "provenance.json").read_text(encoding="ascii"))
    assert evidence["implementation_git_sha"] == provenance["implementation_commit"] == "9369114fc5dffa32b00866526d2bf82b71ab7bd8"
    assert evidence["implementation_source_sha256"] == provenance["implementation_source_sha256"]
    assert provenance["preregistration_commit"] == "94d8b2e396094b747ae9872dc33a737dfbc371e2"
    assert (invalid / "INVALID_PROVENANCE.md").is_file()
    assert "INVALID_EVIDENCE" in (invalid / "INVALID_PROVENANCE.md").read_text(encoding="ascii")
    assert (invalid / "raw" / "decisions.jsonl").read_bytes() == (canonical / "raw" / "decisions.jsonl").read_bytes()
    assert (invalid / "derived" / "paired-effects.csv").read_bytes() == (canonical / "derived" / "paired-effects.csv").read_bytes()
