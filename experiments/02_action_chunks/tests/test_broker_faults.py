from __future__ import annotations

import importlib

import numpy as np


broker = importlib.import_module("experiments.02_action_chunks.src.broker")
adapter = importlib.import_module("experiments.02_action_chunks.src.adapter")


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


def test_out_of_order_response_is_retained_rejection() -> None:
    machine = broker.TemporalBroker(protocol_id="D", capacity=2, terminal_tick=500, proposal_verifier=adapter.verify_normalized_policy)
    proposals = {}
    for sequence, actual in ((2, 100), (1, 101)):
        raw = adapter.PolicyRaw(f"p{sequence}", "P4", "skill", sequence, sequence * 2_000_000, "track_target", np.column_stack((np.linspace(0.5, 0.6, 9), np.linspace(0.0, 0.1, 9))).astype(np.float64))
        proposals[sequence] = adapter.normalize_policy_raw(raw, actual, request_id=f"r{sequence}", request_sequence=sequence)
    rejected = None
    for tick in range(102):
        machine.open_tick(tick)
        if tick == 0:
            machine.request("r1", 1, delivery_tick=101, stack_id="P4", skill_id="skill", expected_phase="track_target", source_observation_id=1, source_observation_time_ns=2_000_000)
        if tick == 1:
            machine.request("r2", 2, delivery_tick=100, stack_id="P4", skill_id="skill", expected_phase="track_target", source_observation_id=2, source_observation_time_ns=4_000_000)
        if tick == 100: assert machine.deliver(proposals[2]).event_type == "CHUNK_ACCEPTED"
        if tick == 101: rejected = machine.deliver(proposals[1])
        machine.issue(measured_q=np.zeros(3), source_observation_id=tick, source_observation_time_ns=tick * 2_000_000); machine.close_tick()
    assert rejected is not None
    assert (rejected.event_type, rejected.detail) == ("CHUNK_REJECTED", "OUT_OF_ORDER")


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
