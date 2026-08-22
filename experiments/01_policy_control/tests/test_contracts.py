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
    assert cfg.resources.rollout_bytes == 1024 * 1024
    assert cfg.resources.phase_bytes == 7544 * 1024 * 1024


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
