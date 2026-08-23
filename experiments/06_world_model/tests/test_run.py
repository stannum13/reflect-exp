from __future__ import annotations

import importlib
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pytest

world = importlib.import_module("experiments.06_world_model.world")
runner = importlib.import_module("experiments.06_world_model.run")
model = importlib.import_module("experiments.06_world_model.model")


@pytest.fixture(autouse=True)
def _bind_git_source_reads_to_the_tested_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_git_file_bytes", lambda _head, path: Path(path).read_bytes(), raising=False)


def _rewrite_manifest_member(root: Path, relative: str) -> None:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    payload = (root / relative).read_bytes()
    member = next(row for row in manifest["files"] if row["path"] == relative)
    member["bytes"] = len(payload)
    member["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest_path.write_bytes(world.canonical(manifest))


def _small_specs() -> tuple[object, ...]:
    rows = world.scene_rows()
    return tuple([x for x in rows if x.partition == "train"][:4] + [x for x in rows if x.partition == "tuning"][:4] + [next(x for x in rows if x.partition == "evaluation")])


def test_small_matrix_is_create_only_complete_and_reconstructable(tmp_path: Path) -> None:
    specs = _small_specs()
    output = tmp_path / "evidence"
    result = runner.run_matrix(output, specs=specs, require_full=False)
    assert result == {"scenes": 9, "anchors": 18, "candidates": 144, "evaluation_candidates": 16}
    assert len((output / "raw/scenes.jsonl").read_text().splitlines()) == 9
    assert len((output / "raw/anchors.jsonl").read_text().splitlines()) == 18
    assert len((output / "raw/candidates.jsonl").read_text().splitlines()) == 144
    assert {"models.json", "calibration.json"} <= {path.name for path in (output / "raw").iterdir()}
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "ENGINEERING_NONCONFIRMATORY"
    assert len({row["path"] for row in manifest["files"]}) == len(manifest["files"])
    with pytest.raises(FileExistsError):
        runner.run_matrix(output, specs=specs, require_full=False)
    reconstructed = tmp_path / "reconstructed"
    runner.reconstruct(output / "raw", reconstructed)
    assert {
        path.name: path.read_bytes() for path in (output / "derived").iterdir()
    } == {
        path.name: path.read_bytes() for path in reconstructed.iterdir()
    }

    candidate = json.loads((output / "raw/candidates.jsonl").read_text().splitlines()[0])
    truth = json.loads((output / "raw/truth.jsonl").read_text().splitlines()[0])
    assert {"generation_counter", "perturbation_magnitude", "pre_perturbation_sha256"} <= candidate.keys()
    assert truth["action_sha256"] == candidate["action_sha256"]
    annotations = json.loads((output / "derived/annotations.json").read_text())
    assert {row["kind"] for row in annotations} >= {"MAX_REGRET"}
    assert json.loads((output / "derived/gate.json").read_text())["authority"] == "ENGINEERING_NONCONFIRMATORY"


def test_reconstruction_rejects_coherently_rehashed_action_tamper(tmp_path: Path) -> None:
    specs = _small_specs()
    original = tmp_path / "original"
    runner.run_matrix(original, specs=specs, require_full=False)
    tampered = tmp_path / "tampered"
    shutil.copytree(original, tampered)
    actions_path = tampered / "raw/actions.npy"
    actions = np.load(actions_path, allow_pickle=False)
    actions[0, 0, 0] += 1e-8
    with actions_path.open("wb") as stream:
        np.lib.format.write_array(stream, actions, allow_pickle=False)
    candidate_path = tampered / "raw/candidates.jsonl"
    candidates = [json.loads(line) for line in candidate_path.read_text().splitlines()]
    candidates[0]["action_sha256"] = hashlib.sha256(world.action_preimage(actions[0])).hexdigest()
    candidate_path.write_bytes(b"".join(world.canonical(row) for row in candidates))
    _rewrite_manifest_member(tampered, "raw/actions.npy")
    _rewrite_manifest_member(tampered, "raw/candidates.jsonl")

    with pytest.raises(ValueError, match="candidate replay"):
        runner.reconstruct(tampered / "raw", tmp_path / "reconstructed")


def test_reconstruction_rejects_coherently_rehashed_anchor_and_split_tamper(tmp_path: Path) -> None:
    specs = _small_specs()
    original = tmp_path / "original"
    runner.run_matrix(original, specs=specs, require_full=False)

    anchor_root = tmp_path / "anchor-tamper"
    shutil.copytree(original, anchor_root)
    anchor_path = anchor_root / "raw/anchors.jsonl"
    anchors = [json.loads(line) for line in anchor_path.read_text().splitlines()]
    anchors[0]["integration_state"][0] += 0.125
    anchors[0]["restore_sha256"] = "0" * 64
    anchor_path.write_bytes(b"".join(world.canonical(row) for row in anchors))
    _rewrite_manifest_member(anchor_root, "raw/anchors.jsonl")
    with pytest.raises(ValueError, match="anchor replay"):
        runner.reconstruct(anchor_root / "raw", tmp_path / "anchor-reconstructed")

    split_root = tmp_path / "split-tamper"
    shutil.copytree(original, split_root)
    scene_path = split_root / "raw/scenes.jsonl"
    scenes = [json.loads(line) for line in scene_path.read_text().splitlines()]
    scenes[0]["spec"]["seed"] += 1
    scene_path.write_bytes(b"".join(world.canonical(row) for row in scenes))
    _rewrite_manifest_member(split_root, "raw/scenes.jsonl")
    with pytest.raises(ValueError, match="scene replay"):
        runner.reconstruct(split_root / "raw", tmp_path / "split-reconstructed")


def test_reconstruction_rejects_source_ledger_not_bound_to_recorded_git_tree(tmp_path: Path) -> None:
    specs = _small_specs()
    original = tmp_path / "original"
    runner.run_matrix(original, specs=specs, require_full=False)
    source_path = original / "raw/source-ledger.json"
    source = json.loads(source_path.read_text())
    source["files"][0]["sha256"] = "f" * 64
    source_path.write_bytes(world.canonical(source))
    _rewrite_manifest_member(original, "raw/source-ledger.json")

    with pytest.raises(ValueError, match="source Git"):
        runner.reconstruct(original / "raw", tmp_path / "reconstructed")


def test_v6_reconstruction_consumes_sealed_models_and_calibration_without_refitting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "v6"
    runner.run_matrix(output, specs=_small_specs(), require_full=False)
    raw_models = (output / "raw/models.json").read_bytes()
    raw_calibration = (output / "raw/calibration.json").read_bytes()
    monkeypatch.setattr(model, "fit_models", lambda *_: (_ for _ in ()).throw(AssertionError("refit forbidden")))
    monkeypatch.setattr(model, "calibrate_w5", lambda *_: (_ for _ in ()).throw(AssertionError("retune forbidden")))
    reconstructed = tmp_path / "reconstructed-v6"
    runner.reconstruct(output / "raw", reconstructed)
    assert (reconstructed / "models.json").read_bytes() == raw_models
    assert (reconstructed / "calibration.json").read_bytes() == raw_calibration


def test_v6_reconstruction_rejects_coherently_rehashed_calibration_tamper(tmp_path: Path) -> None:
    original = tmp_path / "original-v6"
    runner.run_matrix(original, specs=_small_specs(), require_full=False)
    calibration_path = original / "raw/calibration.json"
    calibration = json.loads(calibration_path.read_text())
    calibration["selected_threshold"] += 1.0
    calibration_path.write_bytes(world.canonical(calibration))
    _rewrite_manifest_member(original, "raw/calibration.json")
    with pytest.raises(ValueError, match="calibration"):
        runner.reconstruct(original / "raw", tmp_path / "calibration-reconstructed")
