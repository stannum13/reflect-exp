from __future__ import annotations

import importlib

import numpy as np


broker = importlib.import_module("experiments.02_action_chunks.src.broker")


def _proposal(identity: str, sequence: int, start: int, rows: int = 125) -> object:
    actions = np.arange(rows * 2, dtype=np.float64).reshape(rows, 2)
    return broker.NormalizedProposal(identity, sequence, start, actions)


def test_e_expiry_handoff_has_no_hold_tick() -> None:
    machine = broker.TemporalBroker(terminal_tick=525)
    machine.deliver(_proposal("r0", 0, 200), 200)
    for tick in range(200, 325):
        machine.issue(tick, measured_q=(0.0, 0.0))
    machine.deliver(_proposal("r1", 1, 325), 325)
    machine.issue(325, measured_q=(9.0, 9.0))
    assert machine.hold_ticks == ()
    assert not any(event.event_type == "SAFE_HOLD_ENTERED" for event in machine.events)


def test_e_long_latency_emits_one_safe_hold_and_exact_duration() -> None:
    machine = broker.TemporalBroker(terminal_tick=600)
    machine.deliver(_proposal("r0", 0, 200), 200)
    for tick in range(200, 400):
        machine.issue(tick, measured_q=(1.25, -0.5))
    machine.deliver(_proposal("r1", 1, 400), 400)
    machine.issue(400, measured_q=(8.0, 8.0))
    assert machine.hold_ticks == tuple(range(325, 400))
    holds = [event for event in machine.events if event.event_type == "SAFE_HOLD_ENTERED"]
    assert len(holds) == 1
    assert holds[0].tick == 325
    held = [record for record in machine.issued if record.origin == "broker_safe_hold"]
    assert len(held) == 75
    assert all(np.array_equal(record.action, np.array((1.25, -0.5))) for record in held)
    assert all(not record.action.flags.writeable and record.action.flags.c_contiguous for record in machine.issued)


def test_terminal_delivery_expires_empty_at_3125() -> None:
    machine = broker.TemporalBroker(terminal_tick=3125)
    final = _proposal("terminal", 9, 3000)
    machine.deliver(final, 3000)
    for tick in range(3000, 3125):
        machine.issue(tick, measured_q=(0.0, 0.0))
    terminal = machine.finish(3125)
    assert terminal.event_type == "TERMINAL_EMPTY"
    assert machine.active_chunk_id is None
    assert machine.pending_count == 0
