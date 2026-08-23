from __future__ import annotations

import importlib

import numpy as np


adapter = importlib.import_module("experiments.02_action_chunks.src.adapter")


def test_joint_hold_latches_current_q_with_zero_dq_and_terminal_extent() -> None:
    q = np.array((0.2, -0.4, 0.6), dtype=np.float64)
    hold = adapter.make_safe_hold(
        q,
        source_observation_id=9,
        source_observation_time_ns=640_000_000,
        skill_id="skill",
        expected_phase="track_target",
        start_tick=325,
        terminal_tick=3125,
    )
    q[:] = 8
    assert hold.actions.shape == (2800, 3)
    assert np.array_equal(hold.actions, np.tile((0.2, -0.4, 0.6), (2800, 1)))
    assert hold.metadata["origin"] == "broker_safe_hold"
    assert hold.metadata["hold_adapter"] == "p5_joint_pd_latch_v1"
    first = adapter.dispatch_executable(hold, tick=325)
    last = adapter.dispatch_executable(hold, tick=3124)
    assert first.controller_mode == last.controller_mode == "p5_joint_pd_hold"
    assert np.array_equal(first.q_ref, (0.2, -0.4, 0.6))
    assert np.array_equal(first.dq_ref, np.zeros(3))
    assert adapter.dispatch_executable(hold, tick=3125) is None


def test_replacement_clears_hold_without_mutating_prior_reference() -> None:
    hold = adapter.make_safe_hold(np.zeros(3), source_observation_id=1, source_observation_time_ns=0, skill_id="skill", expected_phase="track_target", start_tick=10, terminal_tick=3125)
    prior = adapter.dispatch_executable(hold, tick=10)
    replacement = adapter.make_safe_hold(np.ones(3), source_observation_id=2, source_observation_time_ns=2_000_000, skill_id="skill", expected_phase="track_target", start_tick=11, terminal_tick=3125)
    current = adapter.dispatch_executable(replacement, tick=11)
    assert np.array_equal(prior.q_ref, np.zeros(3)) and not prior.q_ref.flags.writeable
    assert np.array_equal(current.q_ref, np.ones(3))
