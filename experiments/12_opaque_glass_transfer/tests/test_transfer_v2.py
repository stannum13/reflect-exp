from __future__ import annotations

import importlib
import json
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).parents[1]
v2 = importlib.import_module("experiments.12_opaque_glass_transfer.src.v2")


def test_v2_exact_matrix_and_fresh_namespaces() -> None:
    cfg = v2.load_config()
    matrix = v2.heldout_matrix(cfg)
    assert len(matrix) == 108
    assert len({tuple(row.values()) for row in matrix}) == 108
    assert set(cfg["calibration_seeds"]).isdisjoint(cfg["heldout_seeds"])
    assert set(cfg["heldout_seeds"]).isdisjoint(range(5101, 5113))


def test_pre_freeze_tests_and_calibration_cannot_construct_eval_scenes() -> None:
    cfg = v2.load_config()
    assert cfg["calibration_conditions"] == ["NO_OBSTACLE", "OPAQUE"]
    this_source = Path(__file__).read_text()
    v2.assert_pre_freeze_source_guard(this_source, cfg)


@pytest.mark.parametrize("condition", ["NO_OBSTACLE", "OPAQUE"])
def test_calibration_render_is_actual_rgb_depth(condition: str) -> None:
    scene = v2.render_scene_v2(4201, condition)
    assert scene.rgb.shape == (96, 96, 3)
    assert scene.depth.shape == (96, 96)
    assert scene.rgb.dtype == np.uint8
    assert scene.depth.dtype == np.float32


def test_tick_domain_is_post_step_and_physically_replayable() -> None:
    scene = v2.render_scene_v2(4202, "OPAQUE")
    empty = v2.render_scene_v2(4202, "NO_OBSTACLE")
    episode = v2.run_episode_v2(scene, empty.depth, "RGBD_MOTION")
    assert episode.ticks[0]["time_s"] == pytest.approx(0.02)
    assert episode.ticks[0]["qpos_model"] != [0.0, 0.0]
    v2.validate_physical_replay(scene.xml, episode.ticks)
    for row in episode.ticks:
        assert {"xml_sha256", "rgb_sha256", "depth_sha256", "world_sha256", "material_sha256"} <= row.keys()
        assert all({"geom1", "geom2", "normal_force"} <= c.keys() for c in row["contacts"])


def test_independent_scorer_uses_arrays_xml_and_ledger(tmp_path: Path) -> None:
    root = v2.write_calibration_raw_fixture(tmp_path, seed=4203, controller="RGB_ONLY")
    score = v2.score_raw_episode(root, root / "raw" / "episodes" / "episode")
    assert score["task_complete"]
    assert score["collision_free"]
    (root / "raw" / "episodes" / "episode" / "controller-decoy.json").write_text(
        json.dumps({"success": False, "collisions": 999})
    )
    assert v2.score_raw_episode(root, root / "raw" / "episodes" / "episode") == score


def test_coherent_rehash_cannot_hide_ledger_tamper(tmp_path: Path) -> None:
    root = v2.write_calibration_raw_fixture(tmp_path, seed=4204, controller="RGBD_MOTION")
    ledger = root / "raw" / "episodes" / "episode" / "ticks.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    rows[3]["qpos_model"][0] += 0.2
    ledger.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    v2.write_inventory(root)
    with pytest.raises(v2.IntegrityError, match="physical replay"):
        v2.validate_raw(root)


def test_inventory_covers_dirs_and_rejects_extra_symlink(tmp_path: Path) -> None:
    root = v2.write_calibration_raw_fixture(tmp_path, seed=4201, controller="RGB_ONLY")
    v2.write_inventory(root)
    inventory = json.loads((root / "inventory.json").read_text())
    assert any(row["type"] == "directory" for row in inventory["entries"])
    v2.verify_inventory(root)
    (root / "extra").write_text("x")
    with pytest.raises(v2.IntegrityError):
        v2.verify_inventory(root)
    (root / "extra").unlink()
    (root / "link").symlink_to(root / "closure.json")
    with pytest.raises(v2.IntegrityError):
        v2.verify_inventory(root)
