from __future__ import annotations

import importlib

import numpy as np


adapter = importlib.import_module("experiments.02_action_chunks.src.adapter")
broker = importlib.import_module("experiments.02_action_chunks.src.broker")


def _proposal(sequence: int, actual: int, *, normal: int | None = None) -> object:
    knots = np.column_stack((np.linspace(0.5, 0.6, 9), np.linspace(0.0, 0.1, 9))).astype(np.float64)
    raw = adapter.PolicyRaw(f"p{sequence}", "P4", "skill", sequence, sequence * 2_000_000, "track_target", knots)
    return adapter.normalize_policy_raw(raw, actual, normal_delivery_tick=actual if normal is None else normal, request_id=f"r{sequence}", request_sequence=sequence)


def _tick(machine: object, tick: int, *, request: tuple[str, int, int] | None = None, proposal: object | None = None) -> None:
    machine.open_tick(tick)
    if request is not None:
        machine.request(
            request[0], request[1], delivery_tick=request[2], stack_id="P4", skill_id="skill",
            expected_phase="track_target", source_observation_id=request[1],
            source_observation_time_ns=request[1] * 2_000_000,
        )
    if proposal is not None: machine.deliver(proposal)
    machine.issue(measured_q=np.zeros(3, dtype=np.float64), source_observation_id=tick, source_observation_time_ns=tick * 2_000_000)
    machine.close_tick()


def test_e_expiry_handoff_has_no_hold_tick() -> None:
    machine = broker.TemporalBroker(protocol_id="E", capacity=1, terminal_tick=525, proposal_verifier=adapter.verify_normalized_policy)
    for tick in range(326):
        request = ("r0", 0, 200) if tick == 50 else (("r1", 1, 325) if tick == 250 else None)
        proposal = _proposal(0, 200) if tick == 200 else (_proposal(1, 325) if tick == 325 else None)
        _tick(machine, tick, request=request, proposal=proposal)
    assert 325 not in machine.hold_ticks
    assert not any(event.event_type == "SAFE_HOLD_ENTERED" and 200 <= event.tick <= 325 for event in machine.events)


def test_e_long_latency_emits_one_safe_hold_and_exact_duration() -> None:
    machine = broker.TemporalBroker(protocol_id="E", capacity=1, terminal_tick=600, proposal_verifier=adapter.verify_normalized_policy)
    for tick in range(401):
        request = ("r0", 0, 200) if tick == 50 else (("r1", 1, 400) if tick == 250 else None)
        proposal = _proposal(0, 200) if tick == 200 else (_proposal(1, 400, normal=325) if tick == 400 else None)
        _tick(machine, tick, request=request, proposal=proposal)
    assert tuple(tick for tick in machine.hold_ticks if 200 <= tick <= 400) == tuple(range(325, 400))
    holds = [event for event in machine.events if event.event_type == "SAFE_HOLD_ENTERED" and event.tick >= 200]
    assert len(holds) == 1 and holds[0].tick == 325


def test_terminal_delivery_expires_empty_at_3125() -> None:
    machine = broker.TemporalBroker(protocol_id="A", capacity=1, terminal_tick=3125, proposal_verifier=adapter.verify_normalized_policy)
    for tick in range(3125):
        _tick(machine, tick, request=("r9", 9, 3000) if tick == 2500 else None, proposal=_proposal(9, 3000, normal=2850) if tick == 3000 else None)
    machine.open_tick(3125)
    terminal = machine.finish()
    assert terminal.event_type == "TERMINAL_EMPTY" and machine.active_chunk_id is None and machine.pending_count == 0
