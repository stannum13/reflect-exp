from __future__ import annotations

import csv
import hashlib
import importlib
import json
from pathlib import Path
import subprocess

import pytest


def _module():
    return importlib.import_module("experiments.10_storage_trigger.src.factorial_v2")


def _head() -> str:
    return subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()


def _rehash_member(module, raw: Path, name: str) -> None:
    manifest = json.loads((raw / "raw-manifest.json").read_text(encoding="ascii"))
    payload = (raw / name).read_bytes()
    member = next(item for item in manifest["members"] if item["path"] == name)
    member.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    (raw / "raw-manifest.json").write_bytes(module.canonical_bytes(manifest))


def test_v2_matrix_uses_exact_held_back_paired_namespace() -> None:
    module = _module()
    rows = module.frozen_matrix()
    assert len(rows) == len({row["episode_id"] for row in rows}) == 12_000
    assert {row["seed"] for row in rows} == set(range(20265201, 20265221))
    assert {row["planner_id"] for row in rows} == {"ORACLE_TYPED_SEMANTIC_V2"}
    assert {row["claim_scope"] for row in rows} == {"SYNTHETIC_WHITE_BOX_ENGINEERING_ORACLE_NOT_VLA"}


def test_v2_no_memory_periodic_replay_keeps_immutable_initial_world() -> None:
    module = _module()
    cell = next(
        row for row in module.fixture_matrix()
        if row["storage_variant"] == "NO_MEMORY"
        and row["trigger_variant"] == "PERIODIC_ONLY"
        and row["disturbance_family"] == "POSE_SHIFT"
        and row["horizon"] == 8
    )
    episode, _start, _steps = module.run_episode(cell)
    assert episode["episode_id"] == cell["episode_id"]


def test_v2_independent_scorer_ignores_diagnostics_and_rejects_action_forgery(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "fixture"
    module.run_fixture(output, implementation_git_sha=_head())
    raw = output / "raw"
    steps = [json.loads(line) for line in (raw / "steps.jsonl").read_text(encoding="ascii").splitlines()]
    assert all("completion_progress" not in row and "plan_valid" not in row and "stale_decision" not in row for row in steps)
    victim = next(row for row in steps if row["action"]["attempted"])
    victim["action"]["success"] = not victim["action"]["success"]
    (raw / "steps.jsonl").write_bytes(module.jsonl_bytes(steps))
    _rehash_member(module, raw, "steps.jsonl")
    with pytest.raises(module.FactorialV2Error, match="action|score|ledger"):
        module.reconstruct_fixture(raw, tmp_path / "forged")


def test_v2_reconstruction_enforces_exact_seed_config_matrix_and_source(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "fixture"
    module.run_fixture(output, implementation_git_sha=_head())
    raw = output / "raw"
    episodes = list(csv.DictReader((raw / "episodes.csv").read_text(encoding="ascii").splitlines()))
    episodes[0]["seed"] = "99999999"
    (raw / "episodes.csv").write_bytes(module.csv_bytes(episodes, module.EPISODE_FIELDS))
    _rehash_member(module, raw, "episodes.csv")
    with pytest.raises(module.FactorialV2Error, match="matrix|seed|identity"):
        module.reconstruct_fixture(raw, tmp_path / "bad-seed")

    output2 = tmp_path / "fixture-config"
    module.run_fixture(output2, implementation_git_sha=_head())
    raw2 = output2 / "raw"
    config = json.loads((raw2 / "config.json").read_text(encoding="ascii"))
    config["period_ticks"] = 99
    (raw2 / "config.json").write_bytes(module.canonical_bytes(config))
    _rehash_member(module, raw2, "config.json")
    with pytest.raises(module.FactorialV2Error, match="config|freeze"):
        module.reconstruct_fixture(raw2, tmp_path / "bad-config")

    output3 = tmp_path / "fixture-seeds"
    module.run_fixture(output3, implementation_git_sha=_head())
    raw3 = output3 / "raw"
    seeds = json.loads((raw3 / "seeds.json").read_text(encoding="ascii"))
    seeds["seeds"][0] = 99999999
    (raw3 / "seeds.json").write_bytes(module.canonical_bytes(seeds))
    _rehash_member(module, raw3, "seeds.json")
    with pytest.raises(module.FactorialV2Error, match="seed|freeze"):
        module.reconstruct_fixture(raw3, tmp_path / "bad-seeds")

    output4 = tmp_path / "fixture-source"
    module.run_fixture(output4, implementation_git_sha=_head())
    raw4 = output4 / "raw"
    freeze = json.loads((raw4 / "freeze.json").read_text(encoding="ascii"))
    freeze["source_closure"][0]["sha256"] = "f" * 64
    freeze["source_closure_sha256"] = hashlib.sha256(module.canonical_bytes(freeze["source_closure"])).hexdigest()
    (raw4 / "freeze.json").write_bytes(module.canonical_bytes(freeze))
    _rehash_member(module, raw4, "freeze.json")
    with pytest.raises(module.FactorialV2Error, match="source closure"):
        module.reconstruct_fixture(raw4, tmp_path / "bad-source")

    with pytest.raises(module.FactorialV2Error, match="implementation|commit"):
        module.run_fixture(tmp_path / "bad-commit", implementation_git_sha="0" * 40)


def test_v2_recursive_inventory_rejects_nested_extra_and_symlink(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "fixture"
    module.run_fixture(output, implementation_git_sha=_head())
    extra = output / "raw/unlisted/claim.json"
    extra.parent.mkdir()
    extra.write_text("forged\n", encoding="ascii")
    with pytest.raises(module.FactorialV2Error, match="inventory|unlisted|regular"):
        module.reconstruct_fixture(output / "raw", tmp_path / "extra")

    output2 = tmp_path / "fixture-link"
    module.run_fixture(output2, implementation_git_sha=_head())
    (output2 / "raw/link").symlink_to(output2 / "raw/config.json")
    with pytest.raises(module.FactorialV2Error, match="symlink|inventory|regular"):
        module.reconstruct_fixture(output2 / "raw", tmp_path / "link")


@pytest.mark.filterwarnings("error")
def test_v2_reconstruction_is_byte_exact_and_png_annotations_are_explicit(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "fixture"
    replay = tmp_path / "replay"
    module.run_fixture(output, implementation_git_sha=_head())
    with pytest.raises(module.FactorialV2Error, match="fixture evidence"):
        module.reconstruct(output / "raw", tmp_path / "unauthorized")
    module.reconstruct_fixture(output / "raw", replay)
    expected = {path.name: path.read_bytes() for path in (output / "derived").iterdir()}
    actual = {path.name: path.read_bytes() for path in replay.iterdir()}
    assert actual == expected
    style = json.loads((replay / "plot-style.json").read_text(encoding="ascii"))
    assert style["font"] == "BITMAP_5X7_V1"
    assert style["png_contains_labels"] is True
    annotations = json.loads((replay / "annotations.json").read_text(encoding="ascii"))["samples"]
    assert annotations
    assert all({"requested_class", "disposition", "episode_id"} <= row.keys() for row in annotations)
