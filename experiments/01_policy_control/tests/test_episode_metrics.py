from __future__ import annotations

import importlib

import numpy as np
import pytest
from reflect.rollout import RolloutRecord, RolloutWriter, load_rollout, sha256_json, validate_rollout

from .helpers import config


evaluate = importlib.import_module("experiments.01_policy_control.src.evaluate")


def _identity(cfg):
    timing = importlib.import_module("experiments.01_policy_control.src.timing")
    return evaluate.EpisodeIdentity(
        implementation_sha="1" * 40,
        working_tree_clean=True,
        dirty_diff_hash=None,
        source_lock_hash="2" * 64,
        os_arch="test-os",
        cpu="test-cpu",
        gpu=None,
        python_version="3.11.13",
        dependency_versions={"numpy": np.__version__},
        task_config_hash=sha256_json(timing.scheduler_config(cfg)),
        model_hashes={"arm.xml": "3" * 64},
    )


def test_scenario_and_condition_grid_are_deterministic() -> None:
    cfg = config()
    first = evaluate.generate_scenario(17, cfg)
    second = evaluate.generate_scenario(17, cfg)
    assert first.q0.tobytes() == second.q0.tobytes()
    assert first.two_move_path.tobytes() == second.two_move_path.tobytes()
    assert first.identity_sha256 == second.identity_sha256
    assert first.rng_streams == ("q0", "directions")
    assert first.proposals[-1].disposition is evaluate.ProposalDisposition.ACCEPTED
    assert all(item.disposition is not evaluate.ProposalDisposition.ACCEPTED for item in first.proposals[:-1])
    assert len(evaluate.core_conditions(cfg)) == 24
    assert len(evaluate.probe_conditions(cfg)) == 2


def test_nearest_rank_metrics_censor_and_domains() -> None:
    cfg = config()
    assert evaluate.nearest_rank([1, 2, 3, 4, 5], 0.95) == 5
    metrics = evaluate.compute_episode_metrics(
        recovery_times=[0.4, None],
        errors=np.array([0.10, 0.05, 0.02]),
        action_ages_s=np.array([0.1, 0.2]),
        q_references=np.array([[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [0.03, 0.0, 0.0], [0.06, 0.0, 0.0]]),
        saturation_ticks=1,
        total_ticks=10,
        unsafe_count=0,
        clamp_ticks=0,
        compute_ns=[10, 20],
        config=cfg,
    )
    assert metrics.recovery_s == 1.2
    assert metrics.recovered_events == 1 and metrics.displacement_events == 2
    assert metrics.p95_error_m == 0.10 and metrics.age_p95_s == 0.2


def test_missing_action_age_or_discontinuity_invalidates() -> None:
    cfg = config()
    with pytest.raises(ValueError, match="action age"):
        evaluate.compute_episode_metrics([0.2], np.array([0.1]), np.array([]), np.ones((4, 3)), 0, 4, 0, 0, [1], cfg)
    with pytest.raises(ValueError, match="reference"):
        evaluate.compute_episode_metrics([0.2], np.array([0.1]), np.array([0.1]), np.ones((1, 3)), 0, 1, 0, 0, [1], cfg)


def test_negative_control_boundary_is_inclusive() -> None:
    assert evaluate.negative_control_passes(np.array([0.025, 0.025]), recovery_event=False)
    assert not evaluate.negative_control_passes(np.array([0.0251]), recovery_event=False)


def test_run_episode_wires_one_complete_bounded_rollout(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cfg = config()
    kin = importlib.import_module("experiments.01_policy_control.src.kinematics")
    class FakeArm:
        def __init__(self, config): self.config = config
        def reset(self, q): self.q = np.array(q, copy=True); self.dq = np.zeros(3)
        def state(self): return self.q.copy(), self.dq.copy()
        def site_xy(self): return kin.forward_kinematics(self.q, self.config.arm.link_lengths_m)
        def step(self, torque):
            self.dq = 0.98 * self.dq + 0.0002 * np.asarray(torque)
            self.q = np.clip(self.q + self.config.arm.timestep_s * self.dq, self.config.arm.joint_min_rad, self.config.arm.joint_max_rad)
    monkeypatch.setattr(evaluate, "PlanarArm", FakeArm)
    original_pd = evaluate.bounded_pd
    pd_calls = []

    def capture_pd(*args, **kwargs):
        pd_calls.append((args, kwargs))
        return original_pd(*args, **kwargs)

    monkeypatch.setattr(evaluate, "bounded_pd", capture_pd)
    scenario = evaluate.generate_scenario(11, cfg)
    record = evaluate.run_episode(evaluate.CommandStack.P1, evaluate.core_conditions(cfg)[0], scenario, cfg, _identity(cfg))
    assert isinstance(record, RolloutRecord)
    assert record.metadata.monotonic_end_ns == 6_250_000_000
    assert record.metrics["condition_id"] == "core-05-000-1"
    assert record.actions and record.control_references and record.observations
    assert len(pd_calls) == cfg.timing.episode_ticks
    assert any(record.metrics["raw_500hz"]["safe_hold"])
    assert len(record.metrics["raw_500hz"]["tick"]) == cfg.timing.episode_ticks
    assert len([event for event in record.events if event.event_type.value == "ACTION_EXECUTED"]) <= 625
    path = RolloutWriter(tmp_path, "P1-core-05-000-1-00000011").write(record)
    assert validate_rollout(path).metadata.source_lock_hash == "2" * 64
    assert load_rollout(path).metrics["scenario_identity_sha256"] == scenario.identity_sha256


def test_reference_metrics_do_not_bridge_safe_hold_gaps() -> None:
    cfg = config()
    first = np.array([[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [0.02, 0.0, 0.0], [0.03, 0.0, 0.0]])
    second = first + 2.0
    metrics = evaluate.compute_episode_metrics(
        [0.2], np.array([0.1, 0.05]), np.array([0.1]), (first, second),
        0, 10, 0, 0, [1], cfg,
    )
    assert metrics.discontinuity_mean == pytest.approx(0.01)


@pytest.mark.parametrize(
    ("fault", "expected_event"),
    ((evaluate.FaultKind.DROP, None), (evaluate.FaultKind.OUT_OF_ORDER, "CHUNK_REJECTED_OUT_OF_ORDER")),
)
def test_episode_fault_schedule_is_exact_and_terminal(monkeypatch, fault, expected_event) -> None:
    cfg = config()
    kin = importlib.import_module("experiments.01_policy_control.src.kinematics")

    class FakeArm:
        def __init__(self, config): self.config = config
        def reset(self, q): self.q = np.array(q, copy=True); self.dq = np.zeros(3)
        def state(self): return self.q.copy(), self.dq.copy()
        def site_xy(self): return kin.forward_kinematics(self.q, self.config.arm.link_lengths_m)
        def step(self, torque):
            self.dq = 0.98 * self.dq + 0.0002 * np.asarray(torque)
            self.q = np.clip(self.q + self.config.arm.timestep_s * self.dq, self.config.arm.joint_min_rad, self.config.arm.joint_max_rad)

    monkeypatch.setattr(evaluate, "PlanarArm", FakeArm)
    condition = evaluate.Condition(f"fault-{fault.value.lower()}", 10, 300, 2, fault)
    record = evaluate.run_episode(evaluate.CommandStack.P1, condition, evaluate.generate_scenario(23, cfg), cfg, _identity(cfg))
    kinds = [event.event_type.value for event in record.events]
    assert record.metrics["terminal_queue_count"] == 0
    assert max(event.monotonic_time_ns // 2_000_000 for event in record.events if event.event_type.value == "POLICY_REQUESTED") <= record.metrics["request_cutoff_tick"]
    if fault is evaluate.FaultKind.DROP:
        assert len(record.metrics["declared_dropped_request_ids"]) == 1
        assert record.metrics["terminal_unmatched_request_ids"] == record.metrics["declared_dropped_request_ids"]
        assert sum(bool(event.payload.get("drop_injection")) for event in record.events if event.event_type.value == "POLICY_REQUESTED") == 1
    else:
        assert expected_event in kinds
        assert record.metrics["terminal_unmatched_request_ids"] == ()


def test_real_headless_all_stacks_share_scenario_and_validate(monkeypatch, tmp_path) -> None:
    cfg = config()
    scenario = evaluate.generate_scenario(29, cfg)
    condition = evaluate.Condition("real-headless", 20, 0, 1)
    identity = _identity(cfg)
    original_emit = evaluate.emit_chunk
    original_reference = evaluate.timing.reference_for_tick
    emit_calls = []
    reference_calls = []

    def capture_emit(*args, **kwargs):
        emit_calls.append((args, kwargs))
        return original_emit(*args, **kwargs)

    def capture_reference(*args, **kwargs):
        reference_calls.append((args, kwargs))
        return original_reference(*args, **kwargs)

    monkeypatch.setattr(evaluate, "emit_chunk", capture_emit)
    monkeypatch.setattr(evaluate.timing, "reference_for_tick", capture_reference)
    scenario_hashes = set()
    for stack in evaluate.CommandStack:
        record = evaluate.run_episode(stack, condition, scenario, cfg, identity)
        scenario_hashes.add(record.metrics["scenario_identity_sha256"])
        path = RolloutWriter(tmp_path, record.events[0].rollout_id).write(record)
        artifact = validate_rollout(path)
        assert [item.chunk_id for item in load_rollout(path).actions] == [item.chunk_id for item in artifact.actions]
        assert sum(item.stat().st_size for item in path.iterdir()) <= cfg.resources.rollout_bytes
    assert scenario_hashes == {scenario.identity_sha256}
    assert emit_calls and reference_calls
    for args, kwargs in emit_calls:
        assert not kwargs and len(args) == 3
        captured = args[1]
        belief = captured.observation.object_beliefs[0].pose
        assert belief.tobytes() == captured.skill.target_pose.position[:2].tobytes()
    assert all(not kwargs and len(args) == 7 for args, kwargs in reference_calls)


def test_stationary_control_has_zero_displacements_and_binds_validity(monkeypatch) -> None:
    cfg = config()
    kin = importlib.import_module("experiments.01_policy_control.src.kinematics")

    class StationaryArm:
        def __init__(self, config): self.config = config
        def reset(self, q): self.q = np.array(q, copy=True); self.dq = np.zeros(3)
        def state(self): return self.q.copy(), self.dq.copy()
        def site_xy(self): return kin.forward_kinematics(self.q, self.config.arm.link_lengths_m)
        def step(self, torque): pass

    monkeypatch.setattr(evaluate, "PlanarArm", StationaryArm)
    record = evaluate.run_episode(
        evaluate.CommandStack.P1,
        evaluate.negative_control_condition(cfg),
        evaluate.generate_scenario(31, cfg),
        cfg,
        _identity(cfg),
    )
    assert record.metrics["displacement_events"] == 0
    assert record.metrics["recovered_events"] == 0
    assert record.metrics["recovery_s"] == 0.0
    assert not record.metrics["valid"] and record.metadata.status == "fail"
