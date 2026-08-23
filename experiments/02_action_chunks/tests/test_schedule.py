from __future__ import annotations

import importlib

import pytest

contracts = importlib.import_module("experiments.02_action_chunks.src.contracts")
schedule = importlib.import_module("experiments.02_action_chunks.src.schedule")
CellIdentity = contracts.CellIdentity
FaultId = contracts.FaultId
ProtocolId = contracts.ProtocolId
VectorId = contracts.VectorId
iter_cells = schedule.iter_cells
iter_request_ticks = schedule.iter_request_ticks
schedule_sha256 = schedule.schedule_sha256


def _row(protocol: ProtocolId, vector: VectorId | None = None) -> dict[str, object]:
    return {"stack_id": "P2", "protocol_id": protocol.value, "vector_id": None if vector is None else vector.value, "seed": 17}


def test_exact_per_seed_cell_counts_and_sorted_identity() -> None:
    rows = [_row(ProtocolId.A)]
    rows += [_row(protocol, vector) for protocol in ProtocolId if protocol is not ProtocolId.A for vector in VectorId]
    cells = tuple(iter_cells("tuning", rows))
    assert cells == tuple(sorted(cells))
    counts = {(protocol.value, None if vector is None else vector.value): sum(c.protocol_id is protocol and c.vector_id is vector for c in cells) for protocol in ProtocolId for vector in ((None,) if protocol is ProtocolId.A else tuple(VectorId))}
    assert counts[("A", None)] == 11
    for protocol in ("B", "E"):
        assert [counts[(protocol, vector)] for vector in ("v0", "v1", "v2")] == [12, 12, 12]
    for protocol in ("C", "D", "F", "G"):
        assert [counts[(protocol, vector)] for vector in ("v0", "v1", "v2")] == [12, 13, 13]
    assert schedule_sha256(cells) == schedule_sha256(tuple(reversed(cells)))


def test_core_and_periodic_hand_schedules() -> None:
    core = CellIdentity("tuning", "P2", ProtocolId.A, None, 1, 25, (51, 1052), FaultId.NONE)
    assert core.move_ticks == (51, 1052)
    assert tuple((p.request_tick, p.actual_delivery_tick) for p in iter_request_ticks(core)) == ((50, 75),)

    i1 = CellIdentity("tuning", "P2", ProtocolId.C, VectorId.V0, 1, 75, (51,), FaultId.NONE)
    plans = iter_request_ticks(i1)
    assert [(p.request_tick, p.actual_delivery_tick) for p in plans[:3]] == [(50, 125), (126, 201), (202, 277)]

    i2 = CellIdentity("tuning", "P2", ProtocolId.C, VectorId.V1, 1, 150, (51,), FaultId.NONE)
    plans = iter_request_ticks(i2)
    assert [(p.request_tick, p.actual_delivery_tick) for p in plans[:3]] == [(50, 200), (100, 250), (201, 351)]
    assert all(plan.request_tick <= 2500 for plan in plans)
    assert max(plan.outstanding_after_admission for plan in plans) <= 2


def test_e_continuity_classes_and_fault_schedules() -> None:
    classes = {}
    for vector, latency in ((VectorId.V0, 25), (VectorId.V1, 75), (VectorId.V2, 150)):
        cells = iter_cells("tuning", [_row(ProtocolId.E, vector)])
        cell = next(c for c in cells if c.fault_id is FaultId.NONE and c.latency_ticks == latency and c.move_ticks == (51,))
        classes[vector.value] = cell.continuity_class
    assert classes == {"v0": "EXPIRY_HANDOFF", "v1": "EXPIRY_HANDOFF", "v2": "UNAVOIDABLE_HOLD"}
    strict = next(c for c in iter_cells("tuning", [_row(ProtocolId.E, VectorId.V2)]) if c.fault_id is FaultId.NONE and c.latency_ticks == 25)
    assert strict.continuity_class == "STRICT_OVERLAP"

    old = next(c for c in iter_cells("tuning", [_row(ProtocolId.D, VectorId.V1)]) if c.fault_id is FaultId.OLD_AFTER_NEWER)
    assert [(p.request_tick, p.actual_delivery_tick) for p in iter_request_ticks(old)] == [(50, 200), (201, 402), (251, 401)]
    assert not any(c.fault_id is FaultId.OLD_AFTER_NEWER for c in iter_cells("tuning", [_row(ProtocolId.D, VectorId.V0)]))


def test_schedule_rejects_nonapplicable_or_excess_inventory() -> None:
    with pytest.raises(ValueError, match="N/A"):
        CellIdentity("tuning", "P2", ProtocolId.A, None, 1, 150, (51,), FaultId.OLD_AFTER_NEWER)
    with pytest.raises(ValueError, match="duplicate|maximum"):
        tuple(iter_cells("tuning", [_row(ProtocolId.A), _row(ProtocolId.A)]))
