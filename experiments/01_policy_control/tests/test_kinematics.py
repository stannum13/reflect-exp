from __future__ import annotations

import importlib

import numpy as np


kin = importlib.import_module("experiments.01_policy_control.src.kinematics")


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
    links = (0.30, 0.25, 0.20)
    q0 = np.array([0.35, -0.70, 0.35])
    target = kin.forward_kinematics(q0, links) + np.array([0.02, 0.01])
    first = kin.absolute_ik(target, q0, links, 0.01)
    second = kin.absolute_ik(target, q0, links, 0.01)
    assert first.tobytes() == second.tobytes()
    knots = np.array([[0.0, 0.0], [1.0, 2.0], [2.0, 4.0]])
    assert np.array_equal(kin.linear_knot_reference(knots, 0, 10), knots[0])
    assert np.array_equal(kin.linear_knot_reference(knots, 20, 10), knots[-1])
