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


def test_fault_payload_v1_is_exact_and_never_clamps() -> None:
    p2 = np.zeros((125, 3), dtype=np.float64)
    alternative = broker.apply_fault_payload(p2, stack_id="P2", fault_id="ALTERNATIVE", envelope=(-2.7, 2.7))
    assert alternative.revision == "exp02-fault-payload-v1"
    assert alternative.step_index is None
    np.testing.assert_array_equal(alternative.actions[[0, -1]], p2[[0, -1]])
    np.testing.assert_allclose(alternative.direction, np.array((1.0, -1.0, 1.0)) / np.sqrt(3), rtol=0, atol=0)
    assert alternative.amplitude == 0.05 and alternative.sign == 1

    p4 = np.column_stack((np.linspace(0.0, 1.0, 125), np.zeros(125))).astype(np.float64)
    discontinuity = broker.apply_fault_payload(p4, stack_id="P4", fault_id="DISCONTINUITY", envelope=(-2.0, 2.0))
    assert discontinuity.step_index == 2
    np.testing.assert_array_equal(discontinuity.actions[:2], p4[:2])
    np.testing.assert_array_equal(discontinuity.actions[2:] - p4[2:], np.tile(np.array((0.0, 0.03)), (123, 1)))
    assert discontinuity.pre_sha256 != discontinuity.post_sha256

    with np.testing.assert_raises_regex(broker.BrokerError, "neither sign"):
        broker.apply_fault_payload(p2, stack_id="P2", fault_id="DISCONTINUITY", envelope=(0.0, 0.01))
