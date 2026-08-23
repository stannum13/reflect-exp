from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pytest


adapter = importlib.import_module("experiments.02_action_chunks.src.adapter")
kinematics = importlib.import_module("experiments.01_policy_control.src.kinematics")


@pytest.mark.parametrize(("stack_id", "width", "representation"), (("P2", 3, "JOINT_POSITION"), ("P4", 2, "EEF_TRAJECTORY")))
def test_policy_raw_normalizes_with_frozen_interpolation(stack_id: str, width: int, representation: str) -> None:
    knots = np.arange(9 * width, dtype=np.float64).reshape(9, width) / 10.0
    raw = adapter.PolicyRaw("raw-1", stack_id, "skill", 17, 123_000_000, "track_target", knots)
    normalized = adapter.normalize_policy_raw(raw, actual_delivery_tick=300)
    assert normalized.source_observation_id == 17
    assert normalized.source_observation_time_ns == 123_000_000
    assert normalized.representation == representation
    assert normalized.coverage_ticks == (300, 425)
    assert normalized.actions.shape == (125, width)
    assert raw.dt_s == 0.100 and normalized.dt_s == 0.002
    assert normalized.actions.dtype == np.dtype("<f8")
    assert normalized.actions.flags.c_contiguous and not normalized.actions.flags.writeable
    expected = np.vstack([kinematics.linear_knot_reference(knots, row * 2_000_000, 100_000_000) for row in range(125)])
    assert normalized.actions.tobytes(order="C") == expected.astype("<f8").tobytes(order="C")
    assert adapter.verify_normalized_policy(raw, normalized)
    executable = adapter.dispatch_executable(normalized, tick=300)
    assert executable.actions.tobytes(order="C") == normalized.actions.tobytes(order="C")
    assert executable.valid_from_ns == 600_000_000 and executable.expires_at_ns == 850_000_000


def test_pause_cannot_materialize_before_actual_delivery() -> None:
    raw = adapter.PolicyRaw("raw-2", "P4", "skill", 1, 0, "track_target", np.zeros((9, 2), dtype=np.float64))
    with pytest.raises(adapter.AdapterError, match="actual delivery"):
        adapter.normalize_policy_raw(raw, actual_delivery_tick=None)


def test_direct_chunks_enter_unchanged_p4_executor_seam() -> None:
    contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
    representations = importlib.import_module("experiments.01_policy_control.src.representations")
    config = contracts.load_config(Path("experiments/01_policy_control/configs/base.yaml"))
    knots = np.column_stack((np.linspace(0.55, 0.60, 9), np.linspace(0.05, 0.10, 9))).astype(np.float64)
    raw = adapter.PolicyRaw("p4", "P4", "skill", 4, 500_000_000, "track_target", knots)
    normalized = adapter.normalize_policy_raw(raw, 300)
    chunk = adapter.dispatch_executable(normalized, tick=300)
    state = representations.initial_executor_state(np.zeros(3, dtype=np.float64))
    reference, _, _ = representations.reference_for_tick(
        contracts.CommandStack.P4,
        chunk,
        np.zeros(3, dtype=np.float64),
        np.zeros(3, dtype=np.float64),
        600_000_000,
        state,
        config,
    )
    assert reference.controller_mode == "JOINT_PD"
    assert reference.q_ref.shape == (3,) and np.isfinite(reference.q_ref).all()


def test_policy_raw_is_strict_immutable_nine_knot_little_endian() -> None:
    with pytest.raises(adapter.AdapterError, match="nine"):
        adapter.PolicyRaw("bad", "P2", "skill", 1, 0, "track_target", np.zeros((8, 3), dtype=np.float64))
    source = np.zeros((9, 3), dtype=np.float64)
    raw = adapter.PolicyRaw("raw", "P2", "skill", 1, 0, "track_target", source)
    source[0, 0] = 99
    assert raw.actions[0, 0] == 0 and not raw.actions.flags.writeable
