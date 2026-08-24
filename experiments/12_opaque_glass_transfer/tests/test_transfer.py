from __future__ import annotations

import importlib
import json
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).parents[1]
mod = importlib.import_module("experiments.12_opaque_glass_transfer.src.experiment")


def test_frozen_matrix_and_seed_closure() -> None:
    config = json.loads((ROOT / "config.json").read_text())
    matrix = mod.heldout_matrix(config)
    assert len(matrix) == 108
    assert len({(r.seed, r.condition, r.controller) for r in matrix}) == 108
    assert set(config["calibration_seeds"]).isdisjoint(config["heldout_seeds"])


@pytest.mark.parametrize("condition", ["NO_OBSTACLE", "OPAQUE", "TRANSPARENT"])
def test_scene_renders_real_rgb_and_depth(condition: str) -> None:
    scene = mod.render_scene(seed=4101, condition=condition)
    assert scene.rgb.shape == (96, 96, 3)
    assert scene.depth.shape == (96, 96)
    assert scene.rgb.dtype == np.uint8
    assert scene.depth.dtype == np.float32
    assert np.isfinite(scene.depth).all()
    assert scene.model.ngeom >= (5 if condition != "NO_OBSTACLE" else 4)


def test_matched_opaque_transparent_geometry_differs_only_in_rgba() -> None:
    opaque = mod.scene_contract(4102, "OPAQUE")
    transparent = mod.scene_contract(4102, "TRANSPARENT")
    assert opaque["physics"] == transparent["physics"]
    assert opaque["camera"] == transparent["camera"]
    assert opaque["material_rgba"] != transparent["material_rgba"]


def test_opaque_calibrated_rgb_detector_loses_transparent_obstacle() -> None:
    empty = mod.render_scene(4103, "NO_OBSTACLE")
    opaque = mod.render_scene(4103, "OPAQUE")
    transparent = mod.render_scene(4103, "TRANSPARENT")
    assert mod.detect_rgb(opaque.rgb).present
    assert not mod.detect_rgb(empty.rgb).present
    assert not mod.detect_rgb(transparent.rgb).present


def test_depth_detector_transfers_to_transparent_geometry() -> None:
    empty = mod.render_scene(4104, "NO_OBSTACLE")
    for condition in ("OPAQUE", "TRANSPARENT"):
        rendered = mod.render_scene(4104, condition)
        detection = mod.detect_depth(rendered.rgb, rendered.depth, empty.depth)
        assert detection.present
        assert detection.center_xy is not None
        assert np.linalg.norm(
            np.asarray(detection.center_xy)
            - np.asarray(rendered.contract["physics"]["obstacle_xy"])
        ) <= 0.12


def test_calibration_episode_exposes_transfer_failure_and_geometric_recovery() -> None:
    weak_trace, _, _ = mod.run_episode(4101, "TRANSPARENT", "RGB_ONLY")
    strong_trace, _, _ = mod.run_episode(4101, "TRANSPARENT", "RGBD_MOTION")
    weak_score = mod.score_trace(weak_trace)
    strong_score = mod.score_trace(strong_trace)
    assert weak_trace["obstacle_contacts"] > 0
    assert not weak_score["safe_completion"]
    assert strong_trace["obstacle_contacts"] == 0
    assert strong_score["safe_completion"]


def test_no_obstacle_positive_control_completes_directly() -> None:
    trace, _, _ = mod.run_episode(4102, "NO_OBSTACLE", "RGB_ONLY")
    assert trace["detection"]["present"] is False
    assert mod.score_trace(trace)["safe_completion"]


def test_hierarchy_does_not_escalate_merely_on_waypoint_transition() -> None:
    trace, _, _ = mod.run_episode(4101, "TRANSPARENT", "HIERARCHICAL")
    assert trace["obstacle_contacts"] == 0
    assert trace["semantic_wakes"] == 0
    assert mod.score_trace(trace)["safe_completion"]


def test_calibration_run_serializes_missed_detection_as_strict_json(tmp_path: Path) -> None:
    trace, _, _ = mod.run_episode(4101, "TRANSPARENT", "RGB_ONLY")
    path = tmp_path / "trace.json"
    mod.write_strict_json(path, trace)
    loaded = json.loads(path.read_text())
    assert loaded["detection"]["localization_error_m"] is None


def test_independent_scorer_ignores_controller_claims() -> None:
    trace = mod.synthetic_trace_for_test(final_xy=(1.2, 0.0), obstacle_contacts=1)
    trace["controller_claimed_success"] = True
    scored = mod.score_trace(trace)
    assert scored["task_complete"]
    assert not scored["safe_completion"]


def test_reconstruction_rejects_extra_and_symlink(tmp_path: Path) -> None:
    root = mod.make_integrity_fixture(tmp_path)
    mod.verify_inventory(root)
    (root / "extra.bin").write_bytes(b"x")
    with pytest.raises(mod.IntegrityError):
        mod.verify_inventory(root)
    (root / "extra.bin").unlink()
    (root / "link").symlink_to(root / "manifest.json")
    with pytest.raises(mod.IntegrityError):
        mod.verify_inventory(root)
