from __future__ import annotations

import importlib
from dataclasses import replace

import numpy as np


kin = importlib.import_module("experiments.01_policy_control.src.kinematics")
from .helpers import config


def test_jacobian_matches_centered_finite_difference() -> None:
    q = np.array([0.3, -0.5, 0.4])
    links = (0.30, 0.25, 0.20)
    epsilon = 1e-7
    numeric = np.column_stack(
        [
            (kin.forward_kinematics(q + np.eye(3)[i] * epsilon, links) - kin.forward_kinematics(q - np.eye(3)[i] * epsilon, links)) / (2 * epsilon)
            for i in range(3)
        ]
    )
    assert np.allclose(kin.jacobian(q, links), numeric, atol=1e-8)


def test_absolute_ik_is_deterministic_and_interpolation_endpoints_closed() -> None:
    cfg = config()
    links = (0.30, 0.25, 0.20)
    q0 = np.array([0.35, -0.70, 0.35])
    target = kin.forward_kinematics(q0, links) + np.array([0.02, 0.01])
    first = kin.absolute_ik(target, q0, links, 0.01, cfg)
    second = kin.absolute_ik(target, q0, links, 0.01, cfg)
    assert first.tobytes() == second.tobytes()
    knots = np.array([[0.0, 0.0], [1.0, 2.0], [2.0, 4.0]])
    assert np.array_equal(kin.linear_knot_reference(knots, 0, 10), knots[0])
    assert np.array_equal(kin.linear_knot_reference(knots, 20, 10), knots[-1])


def test_kinematics_consumes_frozen_protocol_values() -> None:
    cfg = config()
    one_iteration = replace(cfg, controller=replace(cfg.controller, ik_iterations=1))
    q0 = np.array([0.35, -0.70, 0.35])
    target = np.array([0.60, 0.10])
    full = kin.absolute_ik(target, q0, cfg.arm.link_lengths_m, 0.01, cfg)
    short = kin.absolute_ik(target, q0, cfg.arm.link_lengths_m, 0.01, one_iteration)
    assert full.tobytes() != short.tobytes()


def test_interpolation_exact_interior() -> None:
    knots = np.array([[0.0, 0.0], [2.0, 4.0]])
    assert np.array_equal(kin.linear_knot_reference(knots, 5, 10), np.array([1.0, 2.0]))
