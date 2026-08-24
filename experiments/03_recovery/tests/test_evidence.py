from __future__ import annotations

import importlib
import json
from pathlib import Path
import shutil

import pytest


c = importlib.import_module("experiments.03_recovery.src.contracts")
cell = importlib.import_module("experiments.03_recovery.src.cell")
episode = importlib.import_module("experiments.03_recovery.src.episode")
evidence = importlib.import_module("experiments.03_recovery.src.evidence")
analyze = importlib.import_module("experiments.03_recovery.src.analyze")


def one_episode() -> object:
    scenario = cell.scenario_specs()[0]
    spec = c.EpisodeSpec("test-R3-anchor-none-20261601", c.Architecture.LAYER_MATCHED, scenario.scenario_id, scenario.domain, 20261601, cell.PRIMARY_CONTROLLER, False)
    return episode.run_episode(spec)


def test_episode_publication_is_create_only_and_fully_hashed(tmp_path: Path) -> None:
    item = one_episode()
    destination = evidence.write_episode(tmp_path / "episodes", item)
    manifest = evidence.validate_episode(destination)
    assert manifest["episode_id"] == item.spec.episode_id
    assert {row["path"] for row in manifest["files"]} == {
        "controller.json", "memory.jsonl", "motion.jsonl", "recovery-decisions.jsonl",
        "recovery-observations.jsonl", "scorer.json", "semantic.jsonl", "spec.json",
        "terminal.json", "trace.npz",
    }
    with pytest.raises(FileExistsError):
        evidence.write_episode(tmp_path / "episodes", item)


def test_episode_validation_rejects_tampering(tmp_path: Path) -> None:
    destination = evidence.write_episode(tmp_path / "episodes", one_episode())
    path = destination / "spec.json"
    path.write_bytes(path.read_bytes().replace(b"anchor-none", b"anchor-tamper"))
    with pytest.raises(evidence.EvidenceError, match="inventory"):
        evidence.validate_episode(destination)


def test_exact_identity_validation_rejects_missing_duplicate_and_extra() -> None:
    expected = ("a", "b")
    for actual in (("a",), ("a", "a"), ("a", "b", "c")):
        with pytest.raises(evidence.EvidenceError):
            evidence.validate_identity_set(actual, expected)
    assert evidence.validate_identity_set(("b", "a"), expected) == ("a", "b")


def test_shard_validation_rejects_source_and_config_drift() -> None:
    base = {"shard_id": "anchors-control", "source_sha256": "1" * 64, "config_sha256": "2" * 64, "episode_ids": ["a"]}
    same = base | {"shard_id": "motion", "episode_ids": ["b"]}
    drift_source = base | {"shard_id": "semantic", "source_sha256": "3" * 64, "episode_ids": ["c"]}
    drift_config = base | {"shard_id": "semantic", "config_sha256": "4" * 64, "episode_ids": ["c"]}
    with pytest.raises(evidence.EvidenceError, match="source"):
        evidence.validate_shard_bindings((base, same, drift_source))
    with pytest.raises(evidence.EvidenceError, match="config"):
        evidence.validate_shard_bindings((base, same, drift_config))


def test_invalid_attempts_are_never_eligible() -> None:
    rows = [
        {"episode_id": "valid", "terminal_disposition": "SUCCESS", "attempt_outcome": "VALID"},
        {"episode_id": "invalid", "terminal_disposition": "INVALID_EVIDENCE", "attempt_outcome": "INVALID_ATTEMPT"},
    ]
    assert [item["episode_id"] for item in evidence.eligible_episode_rows(rows)] == ["valid"]


def test_one_seed_matrix_reconstructs_raw_and_derived_to_clean_output(tmp_path: Path) -> None:
    specs = tuple(item for item in cell.episode_specs() if not item.sensitivity and item.seed == 20261601)
    assert len(specs) == 32
    binding = {"source_sha256": "1" * 64, "config_sha256": "2" * 64, "source_commit": "test-source"}
    roots = []
    for shard_id in evidence.SHARD_IDS:
        root = tmp_path / "run" / "shards" / shard_id
        shard_specs = tuple(item for item in specs if evidence.shard_for_scenario(item.scenario_id) == shard_id)
        evidence.run_specs_shard(root, shard_id, shard_specs, binding)
        roots.append(root)
    raw = evidence.merge_shards(tmp_path / "run", tuple(roots), expected_specs=specs)
    derived = tmp_path / "run" / "derived"
    analyze.analyze(raw, derived)
    clean = tmp_path / "clean"
    evidence.reconstruct(raw, clean, expected_specs=specs)
    original_files = {path.relative_to(derived): path.read_bytes() for path in derived.rglob("*") if path.is_file()}
    clean_files = {path.relative_to(clean): path.read_bytes() for path in clean.rglob("*") if path.is_file()}
    assert clean_files == original_files
    assert json.loads((clean / "decision.json").read_text())["outcome"] == "INCONCLUSIVE"
