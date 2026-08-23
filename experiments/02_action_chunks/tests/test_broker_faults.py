from __future__ import annotations

import importlib

import numpy as np


broker = importlib.import_module("experiments.02_action_chunks.src.broker")


def _matrix(rows: tuple[tuple[float, float], ...]) -> np.ndarray:
    return np.array(rows, dtype=np.float64, order="C")


def test_c_f_g_exact_transforms() -> None:
    old = _matrix(((0.0, 2.0), (2.0, 4.0), (4.0, 6.0)))
    new = _matrix(((2.0, 4.0), (4.0, 6.0), (6.0, 8.0)))
    np.testing.assert_array_equal(broker.derive_ensemble((old, new)), _matrix(((1.0, 3.0), (3.0, 5.0), (5.0, 7.0))))
    expected_f = new.copy()
    for row in range(2):
        beta = (row + 1) / 3
        expected_f[row] = (1.0 - beta) * old[row] + beta * new[row]
    np.testing.assert_array_equal(broker.derive_overlap_blend(old, new, 2), expected_f)
    np.testing.assert_array_equal(broker.derive_rtc_approximation(old, new, 2), _matrix(((0.0, 2.0), (3.0, 5.0), (6.0, 8.0))))


def test_out_of_order_and_expired_responses_are_retained_rejections() -> None:
    machine = broker.TemporalBroker(terminal_tick=500)
    newest = broker.NormalizedProposal("new", 2, 100, np.zeros((125, 2), dtype=np.float64))
    old = broker.NormalizedProposal("old", 1, 101, np.ones((125, 2), dtype=np.float64))
    assert machine.deliver(newest, 100).event_type == "CHUNK_ACCEPTED"
    rejected = machine.deliver(old, 101)
    assert (rejected.event_type, rejected.detail) == ("CHUNK_REJECTED", "OUT_OF_ORDER")
    expired = broker.NormalizedProposal("expired", 3, 200, np.ones((1, 2), dtype=np.float64))
    stale = machine.deliver(expired, 201)
    assert (stale.event_type, stale.detail) == ("CHUNK_REJECTED", "EXPIRED")
