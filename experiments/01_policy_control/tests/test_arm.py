from __future__ import annotations

import importlib

import numpy as np


arm = importlib.import_module("experiments.01_policy_control.src.arm")
contracts = importlib.import_module("experiments.01_policy_control.src.contracts")


def test_mjcf_and_bounded_pd_exact_limits() -> None:
    cfg = contracts.load_config(contracts.Path(__file__).resolve().parents[1] / "configs/base.yaml")
    assert b'timestep="0.002"' in arm.MJCF_BYTES
    q_ref, torque, report = arm.bounded_pd(
        np.zeros(3), np.zeros(3), np.ones(3), np.zeros(3), 80.0, 8.0, cfg
    )
    assert np.allclose(q_ref, 0.003)
    assert np.allclose(torque, 0.24)
    assert report.reference_clamped
    assert not report.torque_clamped


def test_equality_at_limits_is_not_a_clamp() -> None:
    cfg = contracts.load_config(contracts.Path(__file__).resolve().parents[1] / "configs/base.yaml")
    q = np.full(3, cfg.arm.joint_max_rad)
    q_ref, torque, report = arm.bounded_pd(q, np.zeros(3), q, q, 80.0, 8.0, cfg)
    assert np.array_equal(q_ref, q)
    assert np.array_equal(torque, np.zeros(3))
    assert not report.joint_clamped and not report.torque_clamped


def test_mujoco_runtime_matches_frozen_arm_and_analytic_fk() -> None:
    import mujoco
    cfg = contracts.load_config(contracts.Path(__file__).resolve().parents[1] / "configs/base.yaml")
    model = arm.PlanarArm(cfg)
    q = np.array([0.3, -0.5, 0.4])
    model.reset(q)
    kin = importlib.import_module("experiments.01_policy_control.src.kinematics")
    assert model.model.opt.timestep == cfg.arm.timestep_s
    assert np.array_equal(model.model.jnt_range[:3], np.array([[cfg.arm.joint_min_rad, cfg.arm.joint_max_rad]] * 3))
    assert np.array_equal(model.model.actuator_ctrlrange[:3], np.array([[cfg.arm.torque_min_nm, cfg.arm.torque_max_nm]] * 3))
    assert np.allclose(model.site_xy(), kin.forward_kinematics(q, cfg.arm.link_lengths_m), atol=1e-12)
    assert mujoco.__version__ == "3.12.0"
