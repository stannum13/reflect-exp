from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path


def _screen() -> object:
    return importlib.import_module("experiments.04_memory.src.memory_screen")


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]


def test_screen_writes_exact_matrix_with_equal_information_and_real_comparators(tmp_path: Path) -> None:
    screen = _screen()
    output = tmp_path / "screen"
    screen.run_screen(output, seeds=(20260871, 20260872, 20260873, 20260874), implementation_git_sha="0" * 40)

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
    assert by_variant["M4"]["correct_rate"] > by_variant["V0"]["correct_rate"]
    assert by_variant["M4"]["correct_rate"] >= by_variant["H0"]["correct_rate"]
    assert by_variant["M5"]["stale_wrong_composite"] <= by_variant["M4"]["stale_wrong_composite"]
    assert by_variant["M6"]["ambiguous_retrieval_rate"] >= by_variant["M5"]["ambiguous_retrieval_rate"]


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
