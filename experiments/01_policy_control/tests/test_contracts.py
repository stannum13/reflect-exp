from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "experiments/01_policy_control/configs/base.yaml"


def _contracts():
    return importlib.import_module("experiments.01_policy_control.src.contracts")


def test_exact_base_configuration() -> None:
    assert (ROOT / "experiments/__init__.py").is_file()
    cfg = _contracts().load_config(BASE)
    assert cfg.arm.link_lengths_m == (0.30, 0.25, 0.20)
    assert cfg.timing.episode_ticks == 3125
    assert cfg.controller.pd_candidates == ((80.0, 8.0), (60.0, 6.0), (100.0, 10.0))
    assert cfg.controller.ik_damping_candidates == (0.01, 0.001, 0.05)
    assert cfg.controller.mpc_smoothness_candidates == (0.02, 0.01, 0.04)
    assert cfg.resources.rollout_bytes == 2 * 1024 * 1024
    assert cfg.resources.phase_bytes == 14576 * 1024 * 1024


def test_arrays_are_copied_finite_and_read_only() -> None:
    contracts = _contracts()
    source = np.array([1.0, 2.0, 3.0])
    frozen = contracts.frozen_vector(source, "sample", shape=(3,))
    source[0] = 9.0
    assert frozen.tolist() == [1.0, 2.0, 3.0]
    assert not frozen.flags.writeable
    with pytest.raises(ValueError, match="finite"):
        contracts.frozen_vector([1.0, np.nan, 3.0], "sample", shape=(3,))


def test_strict_yaml_rejects_unknown_and_boolean_numeric(tmp_path: Path) -> None:
    raw = BASE.read_text(encoding="utf-8")
    extra = tmp_path / "extra.yaml"
    extra.write_text(raw + "unknown: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown"):
        _contracts().load_config(extra)

    bad = tmp_path / "bad.yaml"
    bad.write_text(raw.replace("episode_ticks: 3125", "episode_ticks: true"), encoding="utf-8")
    with pytest.raises(ValueError, match="episode_ticks"):
        _contracts().load_config(bad)


def test_strict_yaml_rejects_duplicate_nested_unknown_and_float_integer(tmp_path: Path) -> None:
    raw = BASE.read_text(encoding="utf-8")
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(raw + "study_id: duplicate\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        _contracts().load_config(duplicate)
    nested = tmp_path / "nested.yaml"
    nested.write_text(raw.replace("  episode_ticks: 3125", "  episode_ticks: 3125\n  surprise: 1"), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown"):
        _contracts().load_config(nested)
    float_rate = tmp_path / "float-rate.yaml"
    float_rate.write_text(raw.replace("policy_rates_hz: [5, 10, 20]", "policy_rates_hz: [5.0, 10, 20]"), encoding="utf-8")
    with pytest.raises(ValueError, match="policy_rates_hz"):
        _contracts().load_config(float_rate)


def test_complete_typed_protocol_and_array_copying() -> None:
    contracts = _contracts()
    cfg = contracts.load_config(BASE)
    assert cfg.conditions.move_counts == (1, 2)
    assert cfg.conditions.probe_ids == ("DROP", "OUT_OF_ORDER")
    assert cfg.conditions.control_id == "STATIONARY_CONTROL"
    assert tuple(item.representation for item in cfg.stacks) == (
        "JOINT_POSITION", "JOINT_POSITION", "EEF_TRAJECTORY", "EEF_TRAJECTORY", "MPC_GOAL", "BOUNDED_RESIDUAL"
    )
    assert cfg.kinematics.posture_q.tolist() == [0.35, -0.70, 0.35]
    assert cfg.mpc.candidate_count == 79 and cfg.mpc.magnitudes_rad_s == (0.25, 0.75, 1.50)
    assert (cfg.mpc.terminal_error_weight, cfg.mpc.stage_error_weight, cfg.mpc.smoothness_weight) == (1.0, 1.0, 0.02)
    assert cfg.mpc.candidate_order_revision == "MAGNITUDE_THEN_LEXICOGRAPHIC_V1"
    assert cfg.residual.nominal_revision == "MINIMUM_JERK_1S"
    assert cfg.residual.blend_coefficients == (10.0, -15.0, 6.0)
    assert cfg.conditions.probe_policy_hz == 10 and cfg.conditions.probe_latency_ms == 300
    assert cfg.conditions.probe_move_count == 2 and cfg.conditions.out_of_order_extra_ms == 102
    assert cfg.conditions.stationary_first_seed_count == 4
    assert cfg.metrics.primary == "RECOVERY_TIME_S"
    assert "COMMAND_DISCONTINUITY_MEAN" in cfg.metrics.secondary
    assert not cfg.kinematics.posture_q.flags.writeable

    source = np.array([0.35, -0.70, 0.35])
    state = contracts.ExecutorState(None, source, source, source, False)
    source[:] = 9.0
    assert state.latched_q_ref.tolist() == [0.35, -0.70, 0.35]
    assert state.latched_q_ref.flags.c_contiguous and not state.latched_q_ref.flags.writeable


@pytest.mark.parametrize(
    "old,new,match",
    [
        ("primary: RECOVERY_TIME_S", "primary: 7", "primary"),
        ("probe_ids: [DROP, OUT_OF_ORDER]", "probe_ids: DROP", "probe_ids"),
        ("representation: MPC_GOAL", "representation: UNKNOWN", "stack"),
        ("cardinality: HORIZON", "cardinality: UNKNOWN", "stack"),
        ("transition_revision: PREVIOUS_SELECTED_QDOT_V1", "transition_revision: ''", "transition_revision"),
        ("posture_q: [0.35, -0.70, 0.35]", "posture_q: ['0.35', -0.70, 0.35]", "posture_q"),
        ("posture_q: [0.35, -0.70, 0.35]", "posture_q: [true, -0.70, 0.35]", "posture_q"),
    ],
)
def test_closed_protocol_rejects_wrong_types_and_enums(tmp_path: Path, old: str, new: str, match: str) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(BASE.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        _contracts().load_config(path)
