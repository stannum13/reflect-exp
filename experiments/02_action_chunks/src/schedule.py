"""Pure sole-source schedule iterator for the P5 A--G study."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping

from .contracts import (
    EXECUTABLE_ROWS,
    REQUEST_CUTOFF_TICK,
    TERMINAL_TICK,
    VECTOR_VALUES,
    CellIdentity,
    FaultId,
    ProtocolId,
    RequestPlan,
    VectorId,
)

_PERIODIC = frozenset({ProtocolId.C, ProtocolId.D, ProtocolId.F, ProtocolId.G})


def _strict_seed(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("seed must be a nonnegative integer, not bool")
    return value


def _cell(protocol: ProtocolId, vector: VectorId | None, stage: str, stack: str, seed: int, latency: int, moves: tuple[int, ...], fault: FaultId) -> CellIdentity:
    return CellIdentity(stage, stack, protocol, vector, seed, latency, moves, fault)


def iter_cells(stage: str, stack_rows: Iterable[Mapping[str, object]]) -> tuple[CellIdentity, ...]:
    """Return the canonical complete cell inventory for the supplied arms."""
    cells: list[CellIdentity] = []
    identities: set[tuple[str, ProtocolId, VectorId | None, int]] = set()
    for raw in stack_rows:
        if set(raw) != {"stack_id", "protocol_id", "vector_id", "seed"}:
            raise ValueError("stack row has unknown or missing keys")
        try:
            protocol = ProtocolId(raw["protocol_id"])
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown protocol") from exc
        vector_raw = raw["vector_id"]
        try:
            vector = None if vector_raw is None else VectorId(vector_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown vector") from exc
        stack = raw["stack_id"]
        if not isinstance(stack, str) or not stack:
            raise ValueError("stack_id must be a nonempty string")
        seed = _strict_seed(raw["seed"])
        identity = (stack, protocol, vector, seed)
        if identity in identities:
            raise ValueError("duplicate arm exceeds its sealed maximum")
        identities.add(identity)
        for latency in (25, 75, 150, 350):
            for moves in ((51,), (51, 1052)):
                cells.append(_cell(protocol, vector, stage, stack, seed, latency, moves, FaultId.NONE))

        if protocol is ProtocolId.A:
            fault_ids = (FaultId.DROP, FaultId.PAUSE, FaultId.DISCONTINUITY)
        else:
            fault_ids = (FaultId.DROP, FaultId.PAUSE, FaultId.ALTERNATIVE, FaultId.DISCONTINUITY)
            if protocol in _PERIODIC and vector in {VectorId.V1, VectorId.V2}:
                fault_ids += (FaultId.OLD_AFTER_NEWER,)
        for fault in fault_ids:
            latency = 25 if fault is FaultId.ALTERNATIVE else 150
            target = _fault_target_tick(protocol, vector, fault)
            cells.append(_cell(protocol, vector, stage, stack, seed, latency, (target + 1,), fault))

    result = tuple(sorted(cells))
    expected = sum(_maximum_per_arm(protocol, vector) for _, protocol, vector, _ in identities)
    if len(result) != expected:
        raise ValueError("cell count exceeds or misses a sealed maximum")
    return result


def _maximum_per_arm(protocol: ProtocolId, vector: VectorId | None) -> int:
    if protocol is ProtocolId.A:
        return 11
    if protocol in {ProtocolId.B, ProtocolId.E} or vector is VectorId.V0:
        return 12
    return 13


def _fault_target_tick(protocol: ProtocolId, vector: VectorId | None, fault: FaultId) -> int:
    if fault is FaultId.OLD_AFTER_NEWER:
        return 201
    if protocol is ProtocolId.A:
        return 50
    assert vector is not None
    k_b, _, _, _, _, j_e = VECTOR_VALUES[vector]
    if fault is FaultId.ALTERNATIVE:
        if protocol is ProtocolId.B:
            return 75 + k_b
        if protocol is ProtocolId.E:
            return 75 + EXECUTABLE_ROWS - j_e
        return 76
    if protocol is ProtocolId.B:
        return 200 + k_b
    if protocol is ProtocolId.E:
        return 200 + EXECUTABLE_ROWS - j_e
    return 201


def _plan(sequence: int, request: int, latency: int, outstanding: int, capacity: int, *, actual: int | None = None, drop: bool = False) -> RequestPlan:
    nominal = request + latency
    if drop:
        return RequestPlan(sequence, request, nominal, None, None, None, outstanding, capacity, "DROP")
    delivered = nominal if actual is None else actual
    return RequestPlan(sequence, request, nominal, delivered, delivered, min(delivered + EXECUTABLE_ROWS, TERMINAL_TICK), outstanding, capacity)


def iter_request_ticks(cell: CellIdentity) -> tuple[RequestPlan, ...]:
    """Derive all admitted requests for one immutable cell without I/O."""
    if not isinstance(cell, CellIdentity):
        raise ValueError("cell must be a CellIdentity")
    protocol = cell.protocol_id
    vector = cell.vector_id
    capacity = 1 if vector is None else VECTOR_VALUES[vector][1]
    if cell.fault_id is not FaultId.NONE:
        if cell.fault_id is FaultId.OLD_AFTER_NEWER:
            return (
                _plan(0, 50, 150, 1, capacity),
                _plan(1, 201, 150, 1, capacity, actual=402),
                _plan(2, 251, 150, 2, capacity),
            )
        target = _fault_target_tick(protocol, vector, cell.fault_id)
        prefix = [] if protocol is ProtocolId.A else [_plan(0, 50, cell.latency_ticks, 1, capacity)]
        sequence = len(prefix)
        if cell.fault_id is FaultId.DROP:
            return tuple(prefix + [_plan(sequence, target, 150, 1, capacity, drop=True)])
        actual = target + 300 if cell.fault_id is FaultId.PAUSE else None
        return tuple(prefix + [_plan(sequence, target, cell.latency_ticks, 1, capacity, actual=actual)])

    latency = cell.latency_ticks
    if protocol is ProtocolId.A:
        return (_plan(0, 50, latency, 1, 1),)
    assert vector is not None
    k_b, _, _, _, _, j_e = VECTOR_VALUES[vector]
    if protocol in {ProtocolId.B, ProtocolId.E}:
        requests: list[RequestPlan] = []
        tick = 50
        increment = k_b if protocol is ProtocolId.B else EXECUTABLE_ROWS - j_e
        while tick <= REQUEST_CUTOFF_TICK:
            requests.append(_plan(len(requests), tick, latency, 1, 1))
            tick = tick + latency + increment
        return tuple(requests)

    requests = []
    pending: list[int] = []
    next_epoch = 50
    tick = 50
    while tick <= REQUEST_CUTOFF_TICK:
        outstanding_at_start = sum(delivery >= tick for delivery in pending)
        if next_epoch <= tick and outstanding_at_start < capacity:
            delivery = tick + latency
            requests.append(_plan(len(requests), tick, latency, outstanding_at_start + 1, capacity))
            pending.append(delivery)
            next_epoch += 50
        tick += 1
    return tuple(requests)


def schedule_sha256(cells: Iterable[CellIdentity]) -> str:
    rows = [
        {
            "cell_id": cell.cell_id,
            "continuity_class": cell.continuity_class,
            "requests": [
                {
                    "actual_delivery_tick": plan.actual_delivery_tick,
                    "coverage_start_tick": plan.coverage_start_tick,
                    "disposition": plan.disposition,
                    "expiry_tick": plan.expiry_tick,
                    "nominal_delivery_tick": plan.nominal_delivery_tick,
                    "outstanding_after_admission": plan.outstanding_after_admission,
                    "queue_capacity": plan.queue_capacity,
                    "request_sequence": plan.request_sequence,
                    "request_tick": plan.request_tick,
                }
                for plan in iter_request_ticks(cell)
            ],
        }
        for cell in sorted(cells)
    ]
    payload = (json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
    return hashlib.sha256(payload).hexdigest()
