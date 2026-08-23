from __future__ import annotations

from dataclasses import replace
import importlib

import numpy as np
import pytest


adapter = importlib.import_module("experiments.02_action_chunks.src.adapter")
broker = importlib.import_module("experiments.02_action_chunks.src.broker")


def _proposal(sequence: int, actual: int, *, normal: int | None = None) -> object:
    knots = np.column_stack((np.linspace(0.50, 0.60, 9), np.linspace(0.0, 0.10, 9))).astype(np.float64)
    raw = adapter.PolicyRaw(f"p{sequence}", "P4", "skill", sequence, sequence * 2_000_000, "track_target", knots)
    return adapter.normalize_policy_raw(raw, actual_delivery_tick=actual, normal_delivery_tick=actual if normal is None else normal, request_id=f"r{sequence}", request_sequence=sequence)


def test_sealed_proposal_rejects_every_public_field_forgery() -> None:
    proposal = _proposal(0, 75)
    for field, value in (("representation", "JOINT_POSITION"), ("actual_delivery_tick", 76), ("normalized_actions_sha256", "0" * 64), ("actions", np.ones((125, 2), dtype=np.float64))):
        with pytest.raises(broker.BrokerError, match="seal|binding"):
            replace(proposal, **{field: value})


def test_capacity_is_measured_before_delivery_and_ticks_are_total() -> None:
    machine = broker.TemporalBroker(protocol_id="C", capacity=1, terminal_tick=3125, proposal_verifier=adapter.verify_normalized_policy)
    for tick in range(50):
        machine.open_tick(tick); machine.issue(measured_q=np.zeros(3)); machine.close_tick()
    machine.open_tick(50); machine.request("r0", 0, delivery_tick=75); machine.issue(measured_q=np.zeros(3)); machine.close_tick()
    for tick in range(51, 75):
        machine.open_tick(tick); machine.issue(measured_q=np.zeros(3)); machine.close_tick()
    machine.open_tick(75)
    with pytest.raises(broker.BrokerError, match="capacity"):
        machine.request("r1", 1, delivery_tick=100)
    machine.deliver(_proposal(0, 75)); machine.issue(measured_q=np.zeros(3)); machine.close_tick()
    machine.open_tick(76); machine.request("r1", 1, delivery_tick=101); machine.issue(measured_q=np.zeros(3)); machine.close_tick()
    with pytest.raises(broker.BrokerError, match="monotonic"):
        machine.open_tick(78)


def test_f_derivation_binds_positive_h_and_full_new_suffix() -> None:
    machine = broker.TemporalBroker(protocol_id="F", capacity=2, terminal_tick=3125, proposal_verifier=adapter.verify_normalized_policy, overlap_rows=2)
    for tick in range(0, 77):
        machine.open_tick(tick)
        if tick == 0: machine.request("r0", 0, delivery_tick=75)
        if tick == 50: machine.request("r1", 1, delivery_tick=76)
        if tick == 75: machine.deliver(_proposal(0, 75))
        if tick == 76: machine.deliver(_proposal(1, 76))
        machine.issue(measured_q=np.zeros(3)); machine.close_tick()
    active = machine.active
    assert active is not None and active.rule == "OVERLAP_BLEND" and active.h == 2
    assert active.coverage == (76, 201)
    assert len(active.parent_sha256s) == 2 and active.parent_sha256s == tuple(sorted(active.parent_sha256s))
    np.testing.assert_array_equal(active.actions[2:], _proposal(1, 76).actions[2:])


def test_c_orders_parents_and_recomputes_at_earliest_expiry() -> None:
    machine = broker.TemporalBroker(protocol_id="C", capacity=2, terminal_tick=200, proposal_verifier=adapter.verify_normalized_policy)
    for tick in range(136):
        machine.open_tick(tick)
        if tick == 0: machine.request("r0", 0, delivery_tick=10)
        if tick == 1: machine.request("r1", 1, delivery_tick=11)
        if tick == 10: machine.deliver(_proposal(0, 10))
        if tick == 11: machine.deliver(_proposal(1, 11))
        machine.issue(measured_q=np.zeros(3)); machine.close_tick()
    recomputed = [event for event in machine.events if event.event_type == "DERIVATION_RECOMPUTED"]
    assert len(recomputed) == 1 and recomputed[0].tick == 135
    assert tuple(row[0] for row in recomputed[0].sidecar["parent_coverages"]) == ("p1",)
    assert machine.active is not None and machine.active.coverage == (135, 136)


def test_terminal_rejects_unmatched_pending_request() -> None:
    machine = broker.TemporalBroker(protocol_id="A", capacity=1, terminal_tick=3, proposal_verifier=adapter.verify_normalized_policy)
    for tick in range(3):
        machine.open_tick(tick)
        if tick == 0: machine.request("r0", 0, delivery_tick=4)
        machine.issue(measured_q=np.zeros(3)); machine.close_tick()
    machine.open_tick(3)
    with pytest.raises(broker.BrokerError, match="pending|unmatched"):
        machine.finish()


def test_drop_has_no_pending_payload_and_pause_binds_late_generation() -> None:
    machine = broker.TemporalBroker(protocol_id="E", capacity=1, terminal_tick=400, proposal_verifier=adapter.verify_normalized_policy)
    machine.open_tick(0); machine.request("drop", 0, delivery_tick=150, drop=True); machine.issue(measured_q=np.zeros(3)); machine.close_tick()
    assert machine.pending_count == 0 and machine.events[-2].event_type == "REQUEST_DROPPED"
    for tick in range(1, 10):
        machine.open_tick(tick); machine.issue(measured_q=np.zeros(3)); machine.close_tick()
    machine.open_tick(10); machine.request("r1", 1, delivery_tick=310); machine.issue(measured_q=np.zeros(3)); machine.close_tick()
    for tick in range(11, 310):
        machine.open_tick(tick); machine.issue(measured_q=np.zeros(3)); machine.close_tick()
    machine.open_tick(310); paused = _proposal(1, 310, normal=160)
    assert paused.delivery_mode == "paused" and machine.deliver(paused).event_type == "CHUNK_ACCEPTED"
    machine.issue(measured_q=np.zeros(3)); machine.close_tick()


def test_missing_due_delivery_fails_before_tick_closes() -> None:
    machine = broker.TemporalBroker(protocol_id="A", capacity=1, terminal_tick=10, proposal_verifier=adapter.verify_normalized_policy)
    machine.open_tick(0); machine.request("r0", 0, delivery_tick=0); machine.issue(measured_q=np.zeros(3))
    with pytest.raises(broker.BrokerError, match="unmatched"):
        machine.close_tick()
