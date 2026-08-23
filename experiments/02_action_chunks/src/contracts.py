"""Closed, immutable identities for the P5 action-chunk study."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


REQUEST_CUTOFF_TICK = 2500
TERMINAL_TICK = 3125
EXECUTABLE_ROWS = 125
CORE_LATENCIES = (25, 75, 150, 350)
CORE_MOVE_SCHEDULES = ((51,), (51, 1052))


class ProtocolId(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"


class VectorId(str, Enum):
    V0 = "v0"
    V1 = "v1"
    V2 = "v2"


class FaultId(str, Enum):
    NONE = "NONE"
    DROP = "DROP"
    OLD_AFTER_NEWER = "OLD_AFTER_NEWER"
    PAUSE = "PAUSE"
    ALTERNATIVE = "ALTERNATIVE"
    DISCONTINUITY = "DISCONTINUITY"
    STATIONARY_CONTROL = "STATIONARY_CONTROL"


VECTOR_VALUES = {
    VectorId.V0: (1, 1, 0, 1, 1, 25),
    VectorId.V1: (2, 2, 1, 2, 2, 75),
    VectorId.V2: (4, 4, 4, 4, 4, 124),
}


def _strict_int(name: str, value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, not bool")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


@dataclass(frozen=True, order=True)
class CellIdentity:
    stage: str
    stack_id: str
    protocol_id: ProtocolId
    vector_id: VectorId | None
    seed: int
    latency_ticks: int
    move_ticks: tuple[int, ...]
    fault_id: FaultId
    continuity_class: str | None = field(init=False, compare=True)

    def __post_init__(self) -> None:
        if self.stage not in {"tuning", "validation", "confirmation"}:
            raise ValueError("stage must be tuning, validation, or confirmation")
        if not isinstance(self.stack_id, str) or not self.stack_id:
            raise ValueError("stack_id must be a nonempty string")
        if not isinstance(self.protocol_id, ProtocolId):
            raise ValueError("protocol_id must be a closed ProtocolId")
        if self.protocol_id is ProtocolId.A:
            if self.vector_id is not None:
                raise ValueError("A is untuned and forbids a vector")
        elif not isinstance(self.vector_id, VectorId):
            raise ValueError("B--G require a closed vector")
        _strict_int("seed", self.seed)
        _strict_int("latency_ticks", self.latency_ticks, minimum=1)
        if not isinstance(self.move_ticks, tuple) or any(
            isinstance(tick, bool) or not isinstance(tick, int) for tick in self.move_ticks
        ):
            raise ValueError("move schedule must be an integer tuple")
        if not isinstance(self.fault_id, FaultId):
            raise ValueError("fault_id must be a closed FaultId")
        if self.fault_id is FaultId.NONE:
            if self.latency_ticks not in CORE_LATENCIES:
                raise ValueError("core latency is outside the sealed set")
            if self.move_ticks not in CORE_MOVE_SCHEDULES:
                raise ValueError("altered core move schedule")
        if self.fault_id is FaultId.OLD_AFTER_NEWER and (
            self.protocol_id not in {ProtocolId.C, ProtocolId.D, ProtocolId.F, ProtocolId.G}
            or self.vector_id is VectorId.V0
        ):
            raise ValueError("OLD_AFTER_NEWER is N/A for this cell")
        continuity: str | None = None
        if self.protocol_id is ProtocolId.E:
            assert self.vector_id is not None
            lead = VECTOR_VALUES[self.vector_id][5]
            if self.fault_id is FaultId.ALTERNATIVE:
                continuity = "EXPIRY_HANDOFF" if self.vector_id is VectorId.V0 else "POSITIVE_OVERLAP"
            elif self.latency_ticks < lead:
                continuity = "STRICT_OVERLAP"
            elif self.latency_ticks == lead:
                continuity = "EXPIRY_HANDOFF"
            else:
                continuity = "UNAVOIDABLE_HOLD"
        object.__setattr__(self, "continuity_class", continuity)

    @property
    def cell_id(self) -> str:
        vector = "anchor" if self.vector_id is None else self.vector_id.value
        moves = "-".join(str(tick) for tick in self.move_ticks)
        return (
            f"{self.stage}.{self.stack_id}.{self.protocol_id.value}.{vector}."
            f"s{self.seed}.l{self.latency_ticks}.m{moves}.{self.fault_id.value}"
        )


@dataclass(frozen=True)
class RequestPlan:
    request_sequence: int
    request_tick: int
    nominal_delivery_tick: int
    actual_delivery_tick: int | None
    coverage_start_tick: int | None
    expiry_tick: int | None
    outstanding_after_admission: int
    queue_capacity: int = 1
    disposition: str = "DELIVER"

    def __post_init__(self) -> None:
        for name in ("request_sequence", "request_tick", "nominal_delivery_tick", "outstanding_after_admission", "queue_capacity"):
            _strict_int(name, getattr(self, name), minimum=1 if name in {"outstanding_after_admission", "queue_capacity"} else 0)
        for name in ("actual_delivery_tick", "coverage_start_tick", "expiry_tick"):
            value = getattr(self, name)
            if value is not None:
                _strict_int(name, value)
        if self.request_tick > REQUEST_CUTOFF_TICK:
            raise ValueError("request is after the sealed cutoff")
        if self.outstanding_after_admission > self.queue_capacity:
            raise ValueError("request exceeds queue capacity")
        if self.disposition not in {"DELIVER", "DROP"}:
            raise ValueError("unknown request disposition")
        if self.disposition == "DROP":
            if any(value is not None for value in (self.actual_delivery_tick, self.coverage_start_tick, self.expiry_tick)):
                raise ValueError("dropped request cannot carry delivered coverage")
        else:
            if None in (self.actual_delivery_tick, self.coverage_start_tick, self.expiry_tick):
                raise ValueError("delivered request requires complete coverage")
            assert self.actual_delivery_tick is not None
            assert self.coverage_start_tick is not None
            assert self.expiry_tick is not None
            if self.nominal_delivery_tick < self.request_tick:
                raise ValueError("delivery precedes request")
            if self.coverage_start_tick != self.actual_delivery_tick:
                raise ValueError("coverage must be anchored to actual delivery")
            if not self.coverage_start_tick < self.expiry_tick <= TERMINAL_TICK:
                raise ValueError("coverage exceeds terminal bound")
