from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

import pytest


v3 = importlib.import_module("experiments.12_opaque_glass_transfer.src.v3")


def test_v3_pre_freeze_guard_and_fresh_exact_matrix() -> None:
    cfg = v3.load_config()
    v3.assert_pre_freeze_guard(Path(__file__).read_text(), cfg)
    assert cfg["calibration_conditions"] == ["NO_OBSTACLE", "OPAQUE"]
    assert len(v3.heldout_matrix(cfg)) == 108
    prior = json.loads((v3.ROOT / "config.json").read_text())["heldout_seeds"]
    prior += json.loads((v3.ROOT / "config-v2.json").read_text())["heldout_seeds"]
    assert set(cfg["heldout_seeds"]).isdisjoint(cfg["calibration_seeds"] + prior)


@pytest.mark.parametrize("condition", ["NO_OBSTACLE", "OPAQUE"])
def test_v3_calibration_renders_only_allowed_scenes(condition: str) -> None:
    scene = v3.render_scene(4301, condition)
    v3.authenticate_scene(scene)
    assert scene.rgb.shape == (96, 96, 3)


def test_authoritative_replay_ignores_stored_state_for_outcome(tmp_path: Path) -> None:
    root = v3.write_calibration_fixture(tmp_path, 4302, "RGB_ONLY")
    episode = root / "raw/episodes/seed-4302-opaque-rgb_only"
    baseline = v3.score_episode(root, episode)
    ledger = episode / "ticks.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    rows[-1]["qpos_world"] = [99.0, 99.0]
    ledger.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))
    assert v3.score_episode(root, episode) == baseline
    with pytest.raises(v3.IntegrityError, match="stored state receipt"):
        v3.validate_raw(root, verify_manifest=False, root_identity=v3.PRIVATE_CALIBRATION)


def test_controller_label_and_path_swap_is_rejected(tmp_path: Path) -> None:
    root = v3.write_calibration_fixture(tmp_path, 4303, "RGB_ONLY")
    episode = root / "raw/episodes/seed-4303-opaque-rgb_only/episode.json"
    meta = json.loads(episode.read_text())
    meta["controller"] = "RGBD_MOTION"
    meta["controller_contract"] = v3.controller_contract("RGBD_MOTION")
    episode.write_text(json.dumps(meta, sort_keys=True, indent=2) + "\n")
    with pytest.raises(v3.IntegrityError, match="episode identity"):
        v3.validate_raw(root, verify_manifest=False, root_identity=v3.PRIVATE_CALIBRATION)


def test_rerender_rejects_coherent_pixel_and_scene_substitution(tmp_path: Path) -> None:
    root = v3.write_calibration_fixture(tmp_path, 4304, "RGBD_MOTION")
    opaque = root / "raw/scenes/seed-4304-opaque"
    absent = root / "raw/scenes/seed-4304-no_obstacle"
    for name in ("rgb.npy", "depth.npy", "rgb.png", "scene.xml", "scene.json"):
        shutil.copy2(absent / name, opaque / name)
    with pytest.raises(v3.IntegrityError, match="scene identity"):
        v3.validate_raw(root, verify_manifest=False, root_identity=v3.PRIVATE_CALIBRATION)


def test_rerender_rejects_png_or_numeric_render_tamper(tmp_path: Path) -> None:
    root = v3.write_calibration_fixture(tmp_path, 4301, "RGB_ONLY")
    png = root / "raw/scenes/seed-4301-opaque/rgb.png"
    png.write_bytes(png.read_bytes()[:-1] + b"x")
    with pytest.raises(v3.IntegrityError, match="rerender"):
        v3.validate_raw(root, verify_manifest=False, root_identity=v3.PRIVATE_CALIBRATION)


def test_qualification_rejects_derived_tamper_even_after_rehash(tmp_path: Path) -> None:
    root = v3.write_calibration_fixture(tmp_path, 4302, "RGB_ONLY", derive=True)
    analysis = root / "derived/analysis.json"
    value = json.loads(analysis.read_text())
    value["scores"][0]["safe_completion"] = not value["scores"][0]["safe_completion"]
    analysis.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    v3.write_manifest(root)
    with pytest.raises(v3.IntegrityError, match="derived byte mismatch"):
        v3.validate_private_calibration_qualification(root)


def test_exact_recursive_manifest_rejects_extra_and_symlink(tmp_path: Path) -> None:
    root = v3.write_calibration_fixture(tmp_path, 4303, "RGB_ONLY", derive=True)
    v3.write_manifest(root)
    v3.verify_manifest(root)
    (root / "extra").write_text("x")
    with pytest.raises(v3.IntegrityError):
        v3.verify_manifest(root)
    (root / "extra").unlink()
    (root / "link").symlink_to(root / "closure.json")
    with pytest.raises(v3.IntegrityError):
        v3.verify_manifest(root)


def test_closure_schema_and_exact_prior_receipts() -> None:
    receipts = json.loads((v3.ROOT / "V1_V2_INVALID_REJECTED.json").read_text())
    assert receipts["v1"]["evidence_commit"] == "781097a0e8c18bd0b8439f2c1b154020ded58562"
    assert receipts["v2"]["evidence_commit"] == "34f063e26d992594ebf77e2066802be96a1c017d"
    assert v3.CLOSURE_KEYS == {
        "schema", "status", "mode", "source_commit", "source_parent_commit",
        "evidence_commit", "evidence_parent_commit", "chronology_receipt_commit",
        "config_sha256", "source_hashes", "matrix", "seed_namespace",
        "material_namespace", "environment", "attestation_hashes"
    }


def test_lifecycle_rejects_coherent_fake_commits_namespace_and_run_receipt(tmp_path: Path) -> None:
    source = v3.ROOT / "results/qualification-v3"
    root = tmp_path / "qualification"
    shutil.copytree(source, root)
    closure = json.loads((root / "closure.json").read_text())
    closure["source_commit"] = "0" * 40
    closure["source_parent_commit"] = "1" * 40
    closure["mode"] = "CAL" + "IBRATION"
    closure["seed_namespace"] = list(reversed(closure["seed_namespace"]))
    (root / "closure.json").write_text(json.dumps(closure, sort_keys=True, indent=2) + "\n")
    run = json.loads((root / "raw/run.json").read_text())
    run["mode"] = "CAL" + "IBRATION"
    run["episodes"][0]["tick_count"] += 1
    (root / "raw/run.json").write_text(json.dumps(run, sort_keys=True, indent=2) + "\n")
    v3.write_manifest(root)
    with pytest.raises(v3.IntegrityError, match="lifecycle"):
        v3.validate_lifecycle(root)


def test_published_v3_lifecycle_is_exactly_authenticated() -> None:
    v3.validate_lifecycle(v3.ROOT / "results/qualification-v3")
    v3.validate_lifecycle(v3.ROOT / "results/reconstruction-v3")


def test_canonical_v3_rejects_legacy_schema_downgrade(tmp_path: Path) -> None:
    source = v3.ROOT / "results/qualification-v3"
    root = tmp_path / "qualification"
    shutil.copytree(source, root)
    legacy = v3._git_blob(
        v3.EVIDENCE_COMMIT,
        "experiments/12_opaque_glass_transfer/results/qualification-v3/closure.json",
    )
    (root / "closure.json").write_bytes(legacy)
    shutil.rmtree(root / "attestations")
    v3.write_manifest(root)
    with pytest.raises(v3.IntegrityError, match="lifecycle"):
        v3.validate_qualification(root)


@pytest.mark.parametrize("attack", ["missing", "extra"])
def test_canonical_v3_requires_exact_attestation_root(tmp_path: Path, attack: str) -> None:
    source = v3.ROOT / "results/qualification-v3"
    root = tmp_path / "qualification"
    shutil.copytree(source, root)
    attestations = root / "attestations"
    if attack == "missing":
        (attestations / "V3_EVIDENCE_RECEIPT.json").unlink()
    else:
        (attestations / "extra.json").write_text("{}\n")
    v3.write_manifest(root)
    with pytest.raises(v3.IntegrityError, match="lifecycle"):
        v3.validate_qualification(root)
