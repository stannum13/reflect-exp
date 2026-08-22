"""Analytic planar kinematics shared by every command stack."""

from __future__ import annotations

import numpy as np


def _readonly(value: np.ndarray) -> np.ndarray:
    result = np.array(value, dtype=np.float64, order="C", copy=True)
    if not np.isfinite(result).all():
        raise ValueError("kinematic result must be finite")
    result.setflags(write=False)
    return result


def forward_kinematics(q: np.ndarray, links: tuple[float, float, float]) -> np.ndarray:
    q = np.asarray(q, dtype=np.float64)
    angles = np.cumsum(q)
    return _readonly(np.array([np.dot(links, np.cos(angles)), np.dot(links, np.sin(angles))]))


def jacobian(q: np.ndarray, links: tuple[float, float, float]) -> np.ndarray:
    angles = np.cumsum(np.asarray(q, dtype=np.float64))
    result = np.empty((2, 3), dtype=np.float64)
    for column in range(3):
        result[0, column] = -sum(links[index] * np.sin(angles[index]) for index in range(column, 3))
        result[1, column] = sum(links[index] * np.cos(angles[index]) for index in range(column, 3))
    return _readonly(result)


def clip_norm(value: np.ndarray, maximum: float) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    norm = float(np.linalg.norm(result))
    if norm > maximum and norm > 0.0:
        result = result * (maximum / norm)
    return _readonly(result)


def damped_pseudoinverse(j: np.ndarray, damping: float) -> np.ndarray:
    matrix = np.asarray(j, dtype=np.float64)
    return _readonly(matrix.T @ np.linalg.inv(matrix @ matrix.T + damping * damping * np.eye(matrix.shape[0])))


def absolute_ik(target: np.ndarray, q0: np.ndarray, links: tuple[float, float, float], damping: float) -> np.ndarray:
    q = np.array(q0, dtype=np.float64, copy=True)
    posture = np.array([0.35, -0.70, 0.35])
    for _ in range(12):
        j = jacobian(q, links)
        jh = damped_pseudoinverse(j, damping)
        null = np.eye(3) - jh @ j
        update = jh @ (np.asarray(target) - forward_kinematics(q, links)) + 0.05 * null @ (posture - q)
        q = np.clip(q + clip_norm(update, 0.10), -2.55, 2.55)
    return _readonly(q)


def differential_ik_reference(
    target: np.ndarray,
    q: np.ndarray,
    links: tuple[float, float, float],
    damping: float,
    dt_s: float = 0.002,
) -> np.ndarray:
    error = np.asarray(target) - forward_kinematics(q, links)
    velocity = clip_norm(4.0 * error, 0.25)
    j = jacobian(q, links)
    jh = damped_pseudoinverse(j, damping)
    posture = np.array([0.35, -0.70, 0.35])
    qdot = jh @ velocity + 0.20 * (np.eye(3) - jh @ j) @ (posture - q)
    qdot = np.clip(qdot, -1.5, 1.5)
    return _readonly(np.asarray(q) + qdot * dt_s)


def linear_knot_reference(knots: np.ndarray, time_ns: int, knot_period_ns: int) -> np.ndarray:
    values = np.asarray(knots, dtype=np.float64)
    if time_ns <= 0:
        return _readonly(values[0])
    final_time = (len(values) - 1) * knot_period_ns
    if time_ns >= final_time:
        return _readonly(values[-1])
    lower = time_ns // knot_period_ns
    alpha = (time_ns - lower * knot_period_ns) / knot_period_ns
    return _readonly((1.0 - alpha) * values[lower] + alpha * values[lower + 1])
