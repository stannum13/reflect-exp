import hashlib
import importlib

import numpy as np

v2 = importlib.import_module("experiments.03_recovery.src.v2")
command_content_hash = v2.command_content_hash
episode_specs = v2.episode_specs
positive_control_audit = v2.positive_control_audit
realization = v2.realization
run_episode = v2.run_episode


def test_exact_preregistered_matrix_and_real_seed_variation():
    specs = episode_specs()
    assert len(specs) == 360
    assert sum(s.slice_id == "primary" for s in specs) == 320
    assert sum(s.slice_id == "sensitivity" for s in specs) == 40
    hashes = {realization("motion-path-infeasible", seed).parameter_sha256 for seed in range(20261701, 20261711)}
    assert len(hashes) == 10


def test_command_hash_excludes_identity_and_time():
    trajectory = np.array([[0.1, 0.2, 0.3], [0.2, 0.3, 0.4]], dtype="<f8").tobytes()
    a = command_content_hash("a", 1, "object-a", trajectory)
    b = command_content_hash("b", 999, "object-a", trajectory)
    assert a == b == hashlib.sha256(b"object-a\0" + trajectory).hexdigest()


def test_grounded_retry_advances_and_reobserves_and_retains_bytes():
    spec = next(s for s in episode_specs() if s.architecture == "R3" and s.scenario_id == "control-impulse" and s.seed == 20261701)
    episode = run_episode(spec)
    assert episode["observations"][1]["tick"] - episode["observations"][0]["tick"] == 25
    assert episode["physics_steps"] >= 25
    assert episode["trajectory_bytes"]
    assert episode["action_bytes"]
    assert b'"event":"initial"' in episode["memory_event_bytes"]


def test_motion_obstacle_has_real_waypoint_and_semantic_executes_alternative():
    motion = run_episode(next(s for s in episode_specs() if s.architecture == "R3" and s.scenario_id == "motion-path-infeasible" and s.seed == 20261701))
    semantic = run_episode(next(s for s in episode_specs() if s.architecture == "R3" and s.scenario_id == "semantic-object-unavailable" and s.seed == 20261701))
    assert motion["waypoint_count"] >= 1 and motion["collision_count"] == 0
    assert semantic["authorized_object_id"] == "object-b"
    assert b'"object_id":"object-b"' in semantic["memory_event_bytes"]


def test_independent_scorer_positive_controls_all_nonzero():
    audit = positive_control_audit()
    for name in ("unsafe", "forbidden", "stale", "collision", "invalid_action", "loop"):
        assert audit[name] > 0
