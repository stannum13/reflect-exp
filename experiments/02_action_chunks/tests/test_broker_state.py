from __future__ import annotations

from dataclasses import replace
import importlib

import numpy as np
import pytest
from reflect.types import ActionChunk


adapter = importlib.import_module("experiments.02_action_chunks.src.adapter")
broker = importlib.import_module("experiments.02_action_chunks.src.broker")


def _proposal(sequence: int, actual: int, *, normal: int | None = None) -> object:
    knots = np.column_stack((np.linspace(0.50, 0.60, 9), np.linspace(0.0, 0.10, 9))).astype(np.float64)
    raw = adapter.PolicyRaw(f"p{sequence}", "P4", "skill", sequence, sequence * 2_000_000, "track_target", knots)
    return adapter.normalize_policy_raw(raw, actual_delivery_tick=actual, normal_delivery_tick=actual if normal is None else normal, request_id=f"r{sequence}", request_sequence=sequence)


def _request(machine: object, request_id: str, sequence: int, delivery_tick: int, *, drop: bool = False) -> object:
    return machine.request(
        request_id, sequence, delivery_tick=delivery_tick, stack_id="P4", skill_id="skill",
        expected_phase="track_target", source_observation_id=sequence,
        source_observation_time_ns=sequence * 2_000_000, drop=drop,
    )


def _issue(machine: object, tick: int, q: np.ndarray | None = None, *, observation_id: int | None = None) -> object:
    return machine.issue(
        measured_q=np.zeros(3, dtype=np.float64) if q is None else q,
        source_observation_id=tick if observation_id is None else observation_id,
        source_observation_time_ns=tick * 2_000_000,
    )


def test_sealed_proposal_rejects_every_public_field_forgery() -> None:
    proposal = _proposal(0, 75)
    for field, value in (("representation", "JOINT_POSITION"), ("actual_delivery_tick", 76), ("normalized_actions_sha256", "0" * 64), ("actions", np.ones((125, 2), dtype=np.float64))):
        with pytest.raises(broker.BrokerError, match="seal|binding"):
            replace(proposal, **{field: value})


def test_capacity_is_measured_before_delivery_and_ticks_are_total() -> None:
    machine = broker.TemporalBroker(protocol_id="C", capacity=1, terminal_tick=3125, proposal_verifier=adapter.verify_normalized_policy)
    for tick in range(50):
        machine.open_tick(tick); _issue(machine, tick); machine.close_tick()
    machine.open_tick(50); _request(machine, "r0", 0, 75); _issue(machine, 50); machine.close_tick()
    for tick in range(51, 75):
        machine.open_tick(tick); _issue(machine, tick); machine.close_tick()
    machine.open_tick(75)
    with pytest.raises(broker.BrokerError, match="capacity"):
        _request(machine, "r1", 1, 100)
    machine.deliver(_proposal(0, 75)); _issue(machine, 75); machine.close_tick()
    machine.open_tick(76); _request(machine, "r1", 1, 101); _issue(machine, 76); machine.close_tick()
    with pytest.raises(broker.BrokerError, match="monotonic"):
        machine.open_tick(78)


def test_f_derivation_binds_positive_h_and_full_new_suffix() -> None:
    machine = broker.TemporalBroker(protocol_id="F", capacity=2, terminal_tick=3125, proposal_verifier=adapter.verify_normalized_policy, overlap_rows=2)
    for tick in range(0, 77):
        machine.open_tick(tick)
        if tick == 0: _request(machine, "r0", 0, 75)
        if tick == 50: _request(machine, "r1", 1, 76)
        if tick == 75: machine.deliver(_proposal(0, 75))
        if tick == 76: machine.deliver(_proposal(1, 76))
        _issue(machine, tick); machine.close_tick()
    active = machine.active
    assert active is not None and active.rule == "OVERLAP_BLEND" and active.h == 2
    accepted = [event for event in machine.events if event.event_type == "CHUNK_ACCEPTED"][-1]
    assert accepted.sidecar["derivation_revision"] == "exp02-overlap-blend-v1"
    assert accepted.sidecar["derivation_parameter"] == {"M": 2}
    assert active.coverage == (76, 201)
    assert len(active.parent_sha256s) == 2 and active.parent_sha256s == tuple(sorted(active.parent_sha256s))
    np.testing.assert_array_equal(active.actions[2:], _proposal(1, 76).actions[2:])


def test_c_orders_parents_and_recomputes_at_earliest_expiry() -> None:
    machine = broker.TemporalBroker(protocol_id="C", capacity=2, terminal_tick=200, proposal_verifier=adapter.verify_normalized_policy)
    for tick in range(136):
        machine.open_tick(tick)
        if tick == 0: _request(machine, "r0", 0, 10)
        if tick == 1: _request(machine, "r1", 1, 11)
        if tick == 10: machine.deliver(_proposal(0, 10))
        if tick == 11: machine.deliver(_proposal(1, 11))
        _issue(machine, tick); machine.close_tick()
    recomputed = [event for event in machine.events if event.event_type == "DERIVATION_RECOMPUTED"]
    assert len(recomputed) == 1 and recomputed[0].tick == 135
    assert tuple(row[0] for row in recomputed[0].sidecar["parent_coverages"]) == ("p1",)
    assert recomputed[0].sidecar["derivation_revision"] == "exp02-temporal-ensemble-v1"
    assert recomputed[0].sidecar["derivation_parameter"] == {"lambda": 0.0}
    assert machine.active is not None and machine.active.coverage == (135, 136)


def test_terminal_rejects_unmatched_pending_request() -> None:
    machine = broker.TemporalBroker(protocol_id="A", capacity=1, terminal_tick=3, proposal_verifier=adapter.verify_normalized_policy)
    for tick in range(3):
        machine.open_tick(tick)
        if tick == 0: _request(machine, "r0", 0, 4)
        _issue(machine, tick); machine.close_tick()
    machine.open_tick(3)
    with pytest.raises(broker.BrokerError, match="pending|unmatched"):
        machine.finish()


def test_drop_has_no_pending_payload_and_pause_binds_late_generation() -> None:
    machine = broker.TemporalBroker(protocol_id="E", capacity=1, terminal_tick=400, proposal_verifier=adapter.verify_normalized_policy)
    machine.open_tick(0); _request(machine, "drop", 0, 150, drop=True); _issue(machine, 0); machine.close_tick()
    assert machine.pending_count == 0 and any(event.event_type == "REQUEST_DROPPED" for event in machine.events)
    for tick in range(1, 10):
        machine.open_tick(tick); _issue(machine, tick); machine.close_tick()
    machine.open_tick(10); _request(machine, "r1", 1, 310); _issue(machine, 10); machine.close_tick()
    for tick in range(11, 310):
        machine.open_tick(tick); _issue(machine, tick); machine.close_tick()
    machine.open_tick(310); paused = _proposal(1, 310, normal=160)
    assert paused.delivery_mode == "paused" and machine.deliver(paused).event_type == "CHUNK_ACCEPTED"
    _issue(machine, 310); machine.close_tick()


def test_missing_due_delivery_fails_before_tick_closes() -> None:
    machine = broker.TemporalBroker(protocol_id="A", capacity=1, terminal_tick=10, proposal_verifier=adapter.verify_normalized_policy)
    machine.open_tick(0); _request(machine, "r0", 0, 0); _issue(machine, 0)
    with pytest.raises(broker.BrokerError, match="unmatched"):
        machine.close_tick()


def test_request_owns_source_context_and_requires_fresh_observation() -> None:
    machine = broker.TemporalBroker(protocol_id="A", capacity=2, terminal_tick=200, proposal_verifier=adapter.verify_normalized_policy)
    machine.open_tick(0); _request(machine, "r0", 0, 75); _issue(machine, 0); machine.close_tick()
    machine.open_tick(1)
    with pytest.raises(broker.BrokerError, match="identity/timing"):
        _request(machine, "r1", 0, 76)
    _issue(machine, 1); machine.close_tick()
    for tick in range(2, 75):
        machine.open_tick(tick); _issue(machine, tick); machine.close_tick()
    knots = np.column_stack((np.linspace(0.50, 0.60, 9), np.linspace(0.0, 0.10, 9))).astype(np.float64)
    swapped = adapter.normalize_policy_raw(
        adapter.PolicyRaw("p0", "P4", "skill", 9, 18_000_000, "track_target", knots), 75,
        request_id="r0", request_sequence=0,
    )
    machine.open_tick(75)
    with pytest.raises(broker.BrokerError, match="pending request"):
        machine.deliver(swapped)


def test_safe_hold_is_active_addressable_and_replaced_by_delivery() -> None:
    machine = broker.TemporalBroker(protocol_id="A", capacity=1, terminal_tick=200, proposal_verifier=adapter.verify_normalized_policy)
    machine.open_tick(0); issued = _issue(machine, 0, np.array((0.1, -0.2, 0.3), dtype=np.float64), observation_id=7)
    hold = machine.active
    assert isinstance(hold, ActionChunk) and hold.chunk_id == issued.chunk_id
    assert (hold.source_observation_id, hold.source_observation_time_ns) == (7, 0)
    assert [event.event_type for event in machine.events[-2:]] == ["CHUNK_ACCEPTED", "SAFE_HOLD_ENTERED"]
    machine.close_tick()
    machine.open_tick(1); _request(machine, "r1", 1, 1); machine.deliver(_proposal(1, 1))
    assert any(event.event_type == "CHUNK_REPLACED" and event.chunk_id == hold.chunk_id for event in machine.events)


def test_expiry_hold_copies_actual_observation_identity_not_tick() -> None:
    machine = broker.TemporalBroker(protocol_id="A", capacity=1, terminal_tick=200, proposal_verifier=adapter.verify_normalized_policy)
    for tick in range(126):
        machine.open_tick(tick)
        if tick == 0:
            _request(machine, "r0", 0, 0)
            machine.deliver(_proposal(0, 0))
        _issue(machine, tick, observation_id=1_000 + tick)
        machine.close_tick()
    hold = machine.active
    assert isinstance(hold, ActionChunk)
    assert (hold.source_observation_id, hold.source_observation_time_ns) == (1_125, 250_000_000)
    accepted = [event for event in machine.events if event.event_type == "CHUNK_ACCEPTED" and event.detail == "BROKER_SAFE_HOLD"]
    assert accepted[-1].sidecar["source_observation_id"] == 1_125
