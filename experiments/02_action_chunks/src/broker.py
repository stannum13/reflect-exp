"""Integer-tick temporal broker lifecycle for Experiment 02."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

import numpy as np


class BrokerError(ValueError):
    pass


@dataclass(frozen=True)
class FaultPayload:
    revision: str
    actions: np.ndarray
    direction: np.ndarray
    sign: int
    amplitude: float
    step_index: int | None
    pre_sha256: str
    post_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "actions", _readonly_float64(self.actions, ndim=2))
        object.__setattr__(self, "direction", _readonly_float64(self.direction, ndim=1))


def _readonly_float64(values: object, *, ndim: int) -> np.ndarray:
    source = np.asarray(values)
    if source.dtype != np.float64 or source.ndim != ndim or not source.flags.c_contiguous:
        raise BrokerError("actions must be C-contiguous float64 with exact rank")
    if not np.isfinite(source).all():
        raise BrokerError("actions must be finite")
    result = np.array(source, dtype=np.float64, order="C", copy=True)
    result.setflags(write=False)
    return result


def derive_ensemble(parents: tuple[np.ndarray, ...]) -> np.ndarray:
    if not parents:
        raise BrokerError("ensemble requires parents")
    arrays = tuple(_readonly_float64(parent, ndim=2) for parent in parents)
    if len({array.shape for array in arrays}) != 1:
        raise BrokerError("ensemble parents require identical coverage")
    return _readonly_float64(np.mean(np.stack(arrays, axis=0), axis=0), ndim=2)


def derive_overlap_blend(old: np.ndarray, new: np.ndarray, overlap_rows: int) -> np.ndarray:
    left = _readonly_float64(old, ndim=2)
    right = _readonly_float64(new, ndim=2)
    if left.shape != right.shape or type(overlap_rows) is not int or not 0 <= overlap_rows <= len(left):
        raise BrokerError("invalid overlap blend inputs")
    result = np.array(right, copy=True, order="C")
    for row in range(overlap_rows):
        beta = (row + 1) / (overlap_rows + 1)
        result[row] = (1.0 - beta) * left[row] + beta * right[row]
    return _readonly_float64(result, ndim=2)


def derive_rtc_approximation(old: np.ndarray, new: np.ndarray, overlap_rows: int) -> np.ndarray:
    left = _readonly_float64(old, ndim=2)
    right = _readonly_float64(new, ndim=2)
    if left.shape != right.shape or type(overlap_rows) is not int or not 0 < overlap_rows <= len(left):
        raise BrokerError("invalid RTC approximation inputs")
    result = np.array(right, copy=True, order="C")
    for row in range(overlap_rows):
        gamma = (overlap_rows - row) / overlap_rows
        result[row] = gamma * left[row] + (1.0 - gamma) * right[row]
    return _readonly_float64(result, ndim=2)


def apply_fault_payload(actions: np.ndarray, *, stack_id: str, fault_id: str, envelope: tuple[float, float]) -> FaultPayload:
    source = _readonly_float64(actions, ndim=2)
    if source.shape[0] != 125 or stack_id not in {"P2", "P4"} or fault_id not in {"ALTERNATIVE", "DISCONTINUITY"}:
        raise BrokerError("fault payload identity or shape is invalid")
    if len(envelope) != 2 or not envelope[0] < envelope[1]:
        raise BrokerError("fault envelope is invalid")
    if stack_id == "P2":
        if source.shape[1] != 3:
            raise BrokerError("P2 fault rows require width three")
        direction = np.array((1.0, -1.0, 1.0), dtype=np.float64) / np.sqrt(3.0)
        amplitude = 0.05 if fault_id == "ALTERNATIVE" else 0.10
    else:
        if source.shape[1] != 2:
            raise BrokerError("P4 fault rows require width two")
        delta = source[-1] - source[0]
        norm = float(np.linalg.norm(delta))
        if not norm > 0:
            raise BrokerError("P4 fault direction is undefined")
        direction = np.array((-delta[1], delta[0]), dtype=np.float64) / norm
        amplitude = 0.02 if fault_id == "ALTERNATIVE" else 0.03
    step_index = None if fault_id == "ALTERNATIVE" else 2
    selected: np.ndarray | None = None
    selected_sign = 0
    for sign in (1, -1):
        if fault_id == "ALTERNATIVE":
            weights = np.sin(np.pi * np.arange(125, dtype=np.float64) / 124.0)
            weights[0] = 0.0
            weights[-1] = 0.0
        else:
            weights = np.zeros(125, dtype=np.float64)
            weights[2:] = 1.0
        candidate = source + sign * amplitude * weights[:, None] * direction[None, :]
        if np.all(candidate >= envelope[0]) and np.all(candidate <= envelope[1]):
            selected = np.array(candidate, dtype=np.float64, order="C", copy=True)
            selected_sign = sign
            break
    if selected is None:
        raise BrokerError("neither sign fits the hard envelope")
    pre = hashlib.sha256(source.astype("<f8", copy=False).tobytes(order="C")).hexdigest()
    post = hashlib.sha256(selected.astype("<f8", copy=False).tobytes(order="C")).hexdigest()
    return FaultPayload("exp02-fault-payload-v1", selected, direction, selected_sign, amplitude, step_index, pre, post)


@dataclass(frozen=True)
class NormalizedProposal:
    proposal_id: str
    request_sequence: int
    actual_delivery_tick: int
    actions: np.ndarray

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, str) or not self.proposal_id:
            raise BrokerError("proposal_id must be nonempty")
        if type(self.request_sequence) is not int or self.request_sequence < 0:
            raise BrokerError("request_sequence must be a nonnegative integer")
        if type(self.actual_delivery_tick) is not int or self.actual_delivery_tick < 0:
            raise BrokerError("actual_delivery_tick must be a nonnegative integer")
        actions = _readonly_float64(self.actions, ndim=2)
        if not actions.shape[0] or not actions.shape[1]:
            raise BrokerError("proposal actions must be nonempty")
        object.__setattr__(self, "actions", actions)

    @property
    def expiry_tick(self) -> int:
        return self.actual_delivery_tick + self.actions.shape[0]

    @property
    def actions_sha256(self) -> str:
        return hashlib.sha256(self.actions.tobytes(order="C")).hexdigest()


@dataclass(frozen=True)
class BrokerTransition:
    tick: int
    event_type: str
    chunk_id: str | None
    detail: str


@dataclass(frozen=True)
class IssuedAction:
    tick: int
    chunk_id: str
    origin: str
    action: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", _readonly_float64(self.action, ndim=1))


class TemporalBroker:
    """Minimal real lifecycle seam: delivery, issue, safe hold, and close."""

    def __init__(self, *, terminal_tick: int) -> None:
        if type(terminal_tick) is not int or terminal_tick <= 0:
            raise BrokerError("terminal_tick must be a positive integer")
        self._terminal_tick = terminal_tick
        self._active: NormalizedProposal | None = None
        self._last_sequence = -1
        self._hold_id: str | None = None
        self._hold_action: np.ndarray | None = None
        self._events: list[BrokerTransition] = []
        self._issued: list[IssuedAction] = []
        self._hold_ticks: list[int] = []
        self._finished = False

    @property
    def events(self) -> tuple[BrokerTransition, ...]:
        return tuple(self._events)

    @property
    def issued(self) -> tuple[IssuedAction, ...]:
        return tuple(self._issued)

    @property
    def hold_ticks(self) -> tuple[int, ...]:
        return tuple(self._hold_ticks)

    @property
    def active_chunk_id(self) -> str | None:
        return None if self._active is None else self._active.proposal_id

    @property
    def pending_count(self) -> int:
        return 0

    def _expire(self, tick: int) -> None:
        if self._active is not None and tick >= self._active.expiry_tick:
            self._events.append(BrokerTransition(tick, "CHUNK_EXPIRED", self._active.proposal_id, "HALF_OPEN_EXPIRY"))
            self._active = None

    def deliver(self, proposal: NormalizedProposal, tick: int) -> BrokerTransition:
        if self._finished or type(tick) is not int:
            raise BrokerError("broker is closed or tick is invalid")
        self._expire(tick)
        if tick >= proposal.expiry_tick:
            event = BrokerTransition(tick, "CHUNK_REJECTED", proposal.proposal_id, "EXPIRED")
            self._events.append(event)
            return event
        if tick != proposal.actual_delivery_tick:
            raise BrokerError("delivery tick does not match proposal provenance")
        if proposal.expiry_tick <= tick:
            raise BrokerError("proposal is expired")
        if proposal.request_sequence <= self._last_sequence:
            event = BrokerTransition(tick, "CHUNK_REJECTED", proposal.proposal_id, "OUT_OF_ORDER")
            self._events.append(event)
            return event
        self._active = proposal
        self._last_sequence = proposal.request_sequence
        self._hold_id = None
        self._hold_action = None
        event = BrokerTransition(tick, "CHUNK_ACCEPTED", proposal.proposal_id, "DIRECT_NORMALIZED")
        self._events.append(event)
        return event

    def issue(self, tick: int, *, measured_q: object) -> IssuedAction:
        if self._finished or type(tick) is not int or not 0 <= tick < self._terminal_tick:
            raise BrokerError("issue tick is outside the open episode")
        self._expire(tick)
        if self._active is not None:
            row = tick - self._active.actual_delivery_tick
            if not 0 <= row < self._active.actions.shape[0]:
                raise BrokerError("active proposal lacks the requested absolute tick")
            record = IssuedAction(tick, self._active.proposal_id, "normalized_proposal", self._active.actions[row])
        else:
            if self._hold_id is None:
                q = _readonly_float64(measured_q, ndim=1)
                self._hold_id = f"hold-{tick}"
                self._hold_action = q
                self._events.append(BrokerTransition(tick, "SAFE_HOLD_ENTERED", self._hold_id, "LATCHED_CURRENT_Q_ZERO_DQ"))
            assert self._hold_action is not None
            record = IssuedAction(tick, self._hold_id, "broker_safe_hold", self._hold_action)
            self._hold_ticks.append(tick)
        self._issued.append(record)
        return record

    def finish(self, tick: int) -> BrokerTransition:
        if self._finished or tick != self._terminal_tick:
            raise BrokerError("finish must occur exactly once at terminal_tick")
        self._expire(tick)
        if self._active is not None:
            raise BrokerError("terminal broker still has an active proposal")
        self._hold_id = None
        self._hold_action = None
        self._finished = True
        event = BrokerTransition(tick, "TERMINAL_EMPTY", None, "NO_ACTIVE_OR_PENDING")
        self._events.append(event)
        return event
