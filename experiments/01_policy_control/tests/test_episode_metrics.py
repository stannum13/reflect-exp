from __future__ import annotations

import importlib

import numpy as np
import pytest
from reflect.rollout import RolloutRecord

from .helpers import config


evaluate = importlib.import_module("experiments.01_policy_control.src.evaluate")


def test_scenario_and_condition_grid_are_deterministic() -> None:
    cfg = config()
    first = evaluate.generate_scenario(17, cfg)
    second = evaluate.generate_scenario(17, cfg)
    assert first.q0.tobytes() == second.q0.tobytes()
    assert first.two_move_path.tobytes() == second.two_move_path.tobytes()
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


def test_run_episode_wires_one_complete_bounded_rollout(monkeypatch: pytest.MonkeyPatch) -> None:
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
    record = evaluate.run_episode(evaluate.CommandStack.P1, evaluate.core_conditions(cfg)[0], 11, cfg)
    assert isinstance(record, RolloutRecord)
    assert record.metadata.monotonic_end_ns == 6_250_000_000
    assert record.metrics["condition_id"] == "core-05-000-1"
    assert record.actions and record.control_references and record.observations
