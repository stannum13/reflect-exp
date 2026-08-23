"""Integer-tick temporal broker lifecycle for Experiment 02."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Callable, Mapping

import numpy as np
from reflect.types import ActionChunk


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


def derive_overlap_blend(old: np.ndarray, new: np.ndarray, overlap_rows: int, blend_window: int | None = None) -> np.ndarray:
    left = _readonly_float64(old, ndim=2)
    right = _readonly_float64(new, ndim=2)
    if left.shape != right.shape or type(overlap_rows) is not int or not 0 <= overlap_rows <= len(left):
        raise BrokerError("invalid overlap blend inputs")
    result = np.array(right, copy=True, order="C")
    denominator = overlap_rows if blend_window is None else blend_window
    if denominator < overlap_rows or denominator <= 0:
        raise BrokerError("blend window cannot be shorter than overlap")
    for row in range(overlap_rows):
        beta = (row + 1) / (denominator + 1)
        result[row] = (1.0 - beta) * left[row] + beta * right[row]
    return _readonly_float64(result, ndim=2)


def derive_rtc_approximation(old: np.ndarray, new: np.ndarray, overlap_rows: int, projection_window: int | None = None) -> np.ndarray:
    left = _readonly_float64(old, ndim=2)
    right = _readonly_float64(new, ndim=2)
    if left.shape != right.shape or type(overlap_rows) is not int or not 0 < overlap_rows <= len(left):
        raise BrokerError("invalid RTC approximation inputs")
    result = np.array(right, copy=True, order="C")
    denominator = overlap_rows if projection_window is None else projection_window
    if denominator < overlap_rows or denominator <= 0:
        raise BrokerError("projection window cannot be shorter than overlap")
    for row in range(overlap_rows):
        gamma = (denominator - row) / denominator
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


_SEAL_KEY = b"exp02-sealed-proposal-v1"


def _array_sha(value: np.ndarray) -> str:
    return hashlib.sha256(value.astype("<f8", copy=False).tobytes(order="C")).hexdigest()


@dataclass(frozen=True)
class SealedProposal:
    proposal_id: str
    request_id: str
    request_sequence: int
    stack_id: str
    representation: str
    skill_id: str
    expected_phase: str
    source_observation_id: int
    source_observation_time_ns: int
    normal_delivery_tick: int
    actual_delivery_tick: int
    coverage_start_tick: int
    coverage_end_tick: int
    delivery_mode: str
    raw_actions: np.ndarray
    actions: np.ndarray
    policy_actions_sha256: str
    normalized_actions_sha256: str
    fault_id: str | None
    fault_revision: str | None
    fault_step_index: int | None
    fault_amplitude: float | None
    fault_direction: tuple[float, ...] | None
    fault_sign: int | None
    pre_fault_normalized_sha256: str | None
    disposition: str
    _signature: str

    def __post_init__(self) -> None:
        width = 3 if self.stack_id == "P2" else 2 if self.stack_id == "P4" else 0
        expected_representation = "JOINT_POSITION" if self.stack_id == "P2" else "EEF_TRAJECTORY"
        if width == 0 or self.representation != expected_representation:
            raise BrokerError("proposal stack/representation binding is invalid")
        if not all(isinstance(value, str) and value for value in (self.proposal_id, self.request_id, self.skill_id, self.expected_phase)):
            raise BrokerError("proposal identities are invalid")
        for name in ("request_sequence", "source_observation_id", "source_observation_time_ns", "normal_delivery_tick", "actual_delivery_tick", "coverage_start_tick", "coverage_end_tick"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise BrokerError(f"{name} must be a nonnegative integer")
        if self.delivery_mode not in {"normal", "paused"} or self.disposition != "DELIVERED":
            raise BrokerError("proposal delivery/disposition is invalid")
        if (self.delivery_mode == "normal") != (self.actual_delivery_tick == self.normal_delivery_tick) or (self.delivery_mode == "paused" and self.actual_delivery_tick <= self.normal_delivery_tick):
            raise BrokerError("proposal normal/paused timing binding is invalid")
        if self.coverage_start_tick != self.actual_delivery_tick or self.coverage_end_tick != min(self.actual_delivery_tick + 125, 3125) or self.coverage_end_tick - self.coverage_start_tick != 125:
            raise BrokerError("proposal coverage binding is invalid")
        raw = _readonly_float64(self.raw_actions, ndim=2); actions = _readonly_float64(self.actions, ndim=2)
        if raw.shape != (9, width) or actions.shape != (125, width):
            raise BrokerError("proposal raw/normalized shapes are invalid")
        object.__setattr__(self, "raw_actions", raw); object.__setattr__(self, "actions", actions)
        if _array_sha(raw) != self.policy_actions_sha256 or _array_sha(actions) != self.normalized_actions_sha256:
            raise BrokerError("proposal byte/hash binding is invalid")
        fault_fields = (self.fault_revision, self.fault_step_index, self.fault_amplitude,
                        self.fault_direction, self.fault_sign, self.pre_fault_normalized_sha256)
        if self.fault_id is None and any(value is not None for value in fault_fields):
            raise BrokerError("no-fault metadata must be entirely null")
        if self.fault_id is not None and (self.fault_id not in {"ALTERNATIVE", "DISCONTINUITY"}
                                          or any(value is None for index, value in enumerate(fault_fields) if index != 1)
                                          or (self.fault_id == "ALTERNATIVE" and self.fault_step_index is not None)
                                          or (self.fault_id == "DISCONTINUITY" and self.fault_step_index != 2)):
            raise BrokerError("fault metadata is incomplete")
        if self._signature != _proposal_signature(self):
            raise BrokerError("proposal seal is invalid")

    @property
    def expiry_tick(self) -> int:
        return self.coverage_end_tick

    @property
    def coverage_ticks(self) -> tuple[int, int]:
        return self.coverage_start_tick, self.coverage_end_tick

    @property
    def actions_sha256(self) -> str:
        return self.normalized_actions_sha256

    @property
    def dt_s(self) -> float:
        return 0.002


def _proposal_signature(value: SealedProposal | Mapping[str, object]) -> str:
    names = ("proposal_id", "request_id", "request_sequence", "stack_id", "representation", "skill_id", "expected_phase", "source_observation_id", "source_observation_time_ns", "normal_delivery_tick", "actual_delivery_tick", "coverage_start_tick", "coverage_end_tick", "delivery_mode", "policy_actions_sha256", "normalized_actions_sha256", "fault_id", "fault_revision", "fault_step_index", "fault_amplitude", "fault_direction", "fault_sign", "pre_fault_normalized_sha256", "disposition")
    payload = {name: (getattr(value, name) if isinstance(value, SealedProposal) else value[name]) for name in names}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    return hashlib.sha256(_SEAL_KEY + encoded).hexdigest()


def _seal_proposal(**values: object) -> SealedProposal:
    values["_signature"] = _proposal_signature(values)
    return SealedProposal(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class ExecutableChunk:
    chunk_id: str
    representation: str
    skill_id: str
    source_observation_id: int
    source_observation_time_ns: int
    coverage: tuple[int, int]
    actions: np.ndarray
    rule: str
    parent_sha256s: tuple[str, ...]
    parent_coverages: tuple[tuple[str, int, int], ...]
    owner_observation_id: int
    h: int | None
    output_sha256: str

    def __post_init__(self) -> None:
        actions = _readonly_float64(self.actions, ndim=2); object.__setattr__(self, "actions", actions)
        if self.coverage[1] - self.coverage[0] != len(actions) or self.coverage[1] <= self.coverage[0]:
            raise BrokerError("executable coverage is invalid")
        if self.parent_sha256s != tuple(sorted(self.parent_sha256s)) or _array_sha(actions) != self.output_sha256:
            raise BrokerError("executable parent/output binding is invalid")
        if self.rule in {"OVERLAP_BLEND", "RTC_APPROXIMATION"} and (type(self.h) is not int or self.h <= 0):
            raise BrokerError("overlap derivation requires positive h")


NormalizedProposal = SealedProposal


@dataclass(frozen=True)
class BrokerTransition:
    tick: int
    event_type: str
    chunk_id: str | None
    detail: str
    sidecar: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.sidecar is not None:
            object.__setattr__(self, "sidecar", MappingProxyType(dict(self.sidecar)))


@dataclass(frozen=True)
class IssuedAction:
    tick: int
    chunk_id: str
    origin: str
    action: np.ndarray

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", _readonly_float64(self.action, ndim=1))


@dataclass(frozen=True)
class PendingRequest:
    request_id: str
    request_sequence: int
    request_tick: int
    delivery_tick: int
    stack_id: str
    skill_id: str
    expected_phase: str
    source_observation_id: int
    source_observation_time_ns: int


class TemporalBroker:
    """Total integer-tick request/delivery/derivation/issue lifecycle."""

    def __init__(self, *, protocol_id: str, capacity: int, terminal_tick: int, proposal_verifier: Callable[[SealedProposal], bool], overlap_rows: int = 1, ensemble_lambda: float = 0.0, request_cutoff_tick: int = 2500) -> None:
        if protocol_id not in set("ABCDEFG") or type(capacity) is not int or capacity <= 0 or type(terminal_tick) is not int or terminal_tick <= 0:
            raise BrokerError("broker configuration is invalid")
        if type(overlap_rows) is not int or overlap_rows <= 0 or not callable(proposal_verifier) or type(request_cutoff_tick) is not int or request_cutoff_tick < 0:
            raise BrokerError("broker verifier/overlap configuration is invalid")
        self.protocol_id = protocol_id; self.capacity = capacity; self._terminal_tick = terminal_tick
        self._verifier = proposal_verifier; self._overlap_rows = overlap_rows; self._lambda = float(ensemble_lambda)
        self._request_cutoff_tick = min(request_cutoff_tick, terminal_tick - 1)
        self._active: ExecutableChunk | None = None
        self._contributors: list[SealedProposal] = []
        self._pending: dict[str, PendingRequest] = {}
        self._last_sequence = -1
        self._last_request_observation_id = -1
        self._last_request_observation_time_ns = -1
        self._hold: ActionChunk | None = None
        self._events: list[BrokerTransition] = []
        self._issued: list[IssuedAction] = []
        self._hold_ticks: list[int] = []
        self._finished = False
        self._current_tick = -1; self._tick_open = False; self._requested_this_tick = False; self._issued_this_tick = False; self._pending_at_start = 0; self._last_delivery_order: tuple[int, int] | None = None; self._transition_prepared = False

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
        active = self.active
        return None if active is None else active.chunk_id

    @property
    def active(self) -> ExecutableChunk | ActionChunk | None:
        return self._active if self._active is not None else self._hold

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def open_tick(self, tick: int) -> None:
        if self._finished or self._tick_open or type(tick) is not int or tick != self._current_tick + 1 or tick > self._terminal_tick:
            raise BrokerError("ticks must be monotonic, contiguous, and opened once")
        self._current_tick = tick; self._tick_open = True; self._requested_this_tick = False; self._issued_this_tick = False; self._pending_at_start = len(self._pending); self._last_delivery_order = None; self._transition_prepared = False

    def _prepare_transition(self) -> None:
        if self._transition_prepared:
            return
        self._transition_prepared = True
        self._contributors = [item for item in self._contributors if item.coverage_end_tick > self._current_tick]
        if self._active is not None and self._current_tick >= self._active.coverage[1]:
            expired = self._active; self._active = None
            self._events.append(BrokerTransition(self._current_tick, "CHUNK_EXPIRED", expired.chunk_id, "HALF_OPEN_EXPIRY"))
            if self.protocol_id == "C" and self._contributors:
                self._active = self._derive_c()
                self._events.append(BrokerTransition(self._current_tick, "DERIVATION_RECOMPUTED", self._active.chunk_id, "CONTRIBUTOR_EXPIRY", self._sidecar(self._active)))
                self._events.append(BrokerTransition(self._current_tick, "CHUNK_ACCEPTED", self._active.chunk_id, self._active.rule, self._sidecar(self._active)))
        if self._hold is not None and self._current_tick * 2_000_000 >= self._hold.expires_at_ns:
            expired_hold = self._hold
            self._hold = None
            self._events.append(BrokerTransition(self._current_tick, "CHUNK_EXPIRED", expired_hold.chunk_id, "HOLD_TERMINAL_EXPIRY"))

    def request(self, request_id: str, request_sequence: int, *, delivery_tick: int, stack_id: str,
                skill_id: str, expected_phase: str, source_observation_id: int,
                source_observation_time_ns: int, drop: bool = False) -> BrokerTransition:
        if not self._tick_open or self._requested_this_tick:
            raise BrokerError("at most one request is allowed per open nonterminal tick")
        if self._current_tick > self._request_cutoff_tick:
            raise BrokerError("request is after the sealed cutoff")
        if (not isinstance(request_id, str) or not request_id or request_id in self._pending
                or type(request_sequence) is not int or request_sequence < 0
                or type(delivery_tick) is not int or delivery_tick < self._current_tick
                or stack_id not in {"P2", "P4"}
                or not isinstance(skill_id, str) or not skill_id
                or not isinstance(expected_phase, str) or not expected_phase
                or type(source_observation_id) is not int
                or type(source_observation_time_ns) is not int
                or source_observation_id <= self._last_request_observation_id
                or source_observation_time_ns <= self._last_request_observation_time_ns):
            raise BrokerError("request identity/timing is invalid")
        if self._pending_at_start >= self.capacity or len(self._pending) >= self.capacity:
            raise BrokerError("request exceeds capacity measured at tick start")
        self._requested_this_tick = True
        self._last_request_observation_id = source_observation_id
        self._last_request_observation_time_ns = source_observation_time_ns
        if drop:
            event = BrokerTransition(self._current_tick, "REQUEST_DROPPED", request_id, "NO_RESPONSE_OR_WRAPPER")
        else:
            self._pending[request_id] = PendingRequest(
                request_id, request_sequence, self._current_tick, delivery_tick, stack_id, skill_id,
                expected_phase, source_observation_id, source_observation_time_ns,
            )
            event = BrokerTransition(self._current_tick, "POLICY_REQUESTED", request_id, "PENDING")
        self._events.append(event); return event

    def deliver(self, proposal: SealedProposal) -> BrokerTransition:
        if not self._tick_open or not isinstance(proposal, SealedProposal) or not self._verifier(proposal):
            raise BrokerError("delivery requires an inverse-verified sealed proposal in an open tick")
        self._prepare_transition()
        pending = self._pending.get(proposal.request_id)
        if (pending is None or pending.request_sequence != proposal.request_sequence
                or pending.delivery_tick != self._current_tick or proposal.actual_delivery_tick != self._current_tick
                or pending.stack_id != proposal.stack_id or pending.skill_id != proposal.skill_id
                or pending.expected_phase != proposal.expected_phase
                or pending.source_observation_id != proposal.source_observation_id
                or pending.source_observation_time_ns != proposal.source_observation_time_ns):
            raise BrokerError("delivery does not match a pending request")
        order = (proposal.actual_delivery_tick, proposal.request_sequence)
        if self._last_delivery_order is not None and order <= self._last_delivery_order:
            raise BrokerError("same-tick deliveries must be strictly ordered")
        self._last_delivery_order = order
        del self._pending[proposal.request_id]
        if self._current_tick >= proposal.coverage_end_tick:
            self._events.append(BrokerTransition(self._current_tick, "POLICY_RESPONDED", proposal.proposal_id, "RAW_REJECTED"))
            event = BrokerTransition(self._current_tick, "CHUNK_REJECTED", proposal.proposal_id, "EXPIRED")
            self._events.append(event); return event
        if proposal.request_sequence <= self._last_sequence:
            self._events.append(BrokerTransition(self._current_tick, "POLICY_RESPONDED", proposal.proposal_id, "RAW_REJECTED"))
            event = BrokerTransition(self._current_tick, "CHUNK_REJECTED", proposal.proposal_id, "OUT_OF_ORDER")
            self._events.append(event); return event
        self._last_sequence = proposal.request_sequence
        previous: ExecutableChunk | ActionChunk | None = self.active
        if self.protocol_id == "C":
            self._contributors.append(proposal); self._contributors.sort(key=lambda item: (item.actual_delivery_tick, item.request_sequence, item.proposal_id)); self._active = self._derive_c()
        elif self.protocol_id in {"F", "G"}:
            self._active = self._derive_overlap(proposal)
        else:
            self._active = self._direct(proposal)
        self._hold = None
        self._events.append(BrokerTransition(self._current_tick, "POLICY_RESPONDED", self._active.chunk_id, "EXECUTABLE_RESPONSE", self._sidecar(self._active)))
        previous_valid = (previous.coverage[0] <= self._current_tick < previous.coverage[1]
                          if isinstance(previous, ExecutableChunk)
                          else previous is not None and previous.valid_from_ns <= self._current_tick * 2_000_000 < previous.expires_at_ns)
        if previous is not None and previous_valid and previous.chunk_id != self._active.chunk_id:
            self._events.append(BrokerTransition(self._current_tick, "CHUNK_REPLACED", previous.chunk_id, "UNISSUED_FUTURE_REPLACED", {"replacement_chunk_id": self._active.chunk_id}))
        event = BrokerTransition(self._current_tick, "CHUNK_ACCEPTED", self._active.chunk_id, self._active.rule, self._sidecar(self._active))
        self._events.append(event); return event

    def _direct(self, proposal: SealedProposal) -> ExecutableChunk:
        parents = (proposal.normalized_actions_sha256,)
        return ExecutableChunk(f"direct-{proposal.proposal_id}", proposal.representation, proposal.skill_id, proposal.source_observation_id, proposal.source_observation_time_ns, (self._current_tick, proposal.coverage_end_tick), proposal.actions, "DIRECT_NORMALIZED", parents, ((proposal.proposal_id, proposal.coverage_start_tick, proposal.coverage_end_tick),), proposal.source_observation_id, None, _array_sha(proposal.actions))

    def _derive_c(self) -> ExecutableChunk:
        valid = [item for item in self._contributors if item.coverage_start_tick <= self._current_tick < item.coverage_end_tick]
        if not valid: raise BrokerError("C derivation has no current contributors")
        z = min(item.coverage_end_tick for item in valid); rows = []
        for absolute in range(self._current_tick, z):
            weights = [np.exp(-self._lambda * ((absolute - item.actual_delivery_tick) * 0.002)) for item in valid]
            values = [item.actions[absolute - item.coverage_start_tick] for item in valid]
            rows.append(sum(weight * value for weight, value in zip(weights, values)) / sum(weights))
        actions = np.asarray(rows, dtype=np.float64); owner = valid[-1]
        hashes = tuple(sorted(item.normalized_actions_sha256 for item in valid)); coverages = tuple((item.proposal_id, item.coverage_start_tick, item.coverage_end_tick) for item in valid)
        return ExecutableChunk(f"derived-C-{owner.proposal_id}-{self._current_tick}", owner.representation, owner.skill_id, owner.source_observation_id, owner.source_observation_time_ns, (self._current_tick, z), actions, "TEMPORAL_ENSEMBLE", hashes, coverages, owner.source_observation_id, None, _array_sha(actions))

    def _derive_overlap(self, proposal: SealedProposal) -> ExecutableChunk:
        old = self._active
        compatible = old is not None and old.representation == proposal.representation and old.coverage[0] <= self._current_tick < old.coverage[1]
        if not compatible: return self._direct(proposal)
        assert old is not None
        z = proposal.coverage_end_tick; h = min(self._overlap_rows, z - self._current_tick, old.coverage[1] - self._current_tick)
        if h <= 0: return self._direct(proposal)
        old_start = self._current_tick - old.coverage[0]; old_rows = old.actions[old_start:old_start + (z - self._current_tick)]
        new_rows = proposal.actions[: z - self._current_tick]
        padded_old = np.array(new_rows, copy=True); padded_old[:len(old_rows)] = old_rows
        if self.protocol_id == "F": actions = derive_overlap_blend(padded_old, new_rows, h, self._overlap_rows); rule = "OVERLAP_BLEND"
        else: actions = derive_rtc_approximation(padded_old, new_rows, h, self._overlap_rows); rule = "RTC_APPROXIMATION"
        hashes = tuple(sorted((*old.parent_sha256s, proposal.normalized_actions_sha256)))
        coverages = (*old.parent_coverages, (proposal.proposal_id, proposal.coverage_start_tick, proposal.coverage_end_tick))
        return ExecutableChunk(f"derived-{self.protocol_id}-{proposal.proposal_id}-{self._current_tick}", proposal.representation, proposal.skill_id, proposal.source_observation_id, proposal.source_observation_time_ns, (self._current_tick, z), actions, rule, hashes, coverages, proposal.source_observation_id, h, _array_sha(actions))

    def _sidecar(self, chunk: ExecutableChunk) -> dict[str, object]:
        revision, parameter = {
            "DIRECT_NORMALIZED": ("exp02-direct-normalized-v1", None),
            "TEMPORAL_ENSEMBLE": ("exp02-temporal-ensemble-v1", {"lambda": self._lambda}),
            "OVERLAP_BLEND": ("exp02-overlap-blend-v1", {"M": self._overlap_rows}),
            "RTC_APPROXIMATION": ("exp02-rtc-approximation-v1", {"L": self._overlap_rows}),
        }[chunk.rule]
        return {"parent_sha256s": chunk.parent_sha256s, "parent_coverages": chunk.parent_coverages,
                "owner_observation_id": chunk.owner_observation_id, "b": chunk.coverage[0],
                "z": chunk.coverage[1], "h": chunk.h, "rule": chunk.rule,
                "derivation_revision": revision, "derivation_parameter": parameter,
                "output_sha256": chunk.output_sha256}

    def issue(self, *, measured_q: object) -> IssuedAction:
        if not self._tick_open or self._current_tick >= self._terminal_tick or self._issued_this_tick:
            raise BrokerError("exactly one issue is allowed per open execution tick")
        self._prepare_transition()
        self._issued_this_tick = True
        if self._active is not None:
            row = self._current_tick - self._active.coverage[0]
            if not 0 <= row < self._active.actions.shape[0]:
                raise BrokerError("active proposal lacks the requested absolute tick")
            record = IssuedAction(self._current_tick, self._active.chunk_id, "executable", self._active.actions[row])
        else:
            if self._hold is None:
                q = _readonly_float64(measured_q, ndim=1)
                if q.shape != (3,): raise BrokerError("safe hold requires measured joint position")
                q_hash = hashlib.sha256(q.astype("<f8", copy=False).tobytes(order="C")).hexdigest()
                hold_actions = np.tile(q, (self._terminal_tick - self._current_tick, 1))
                self._hold = ActionChunk(
                    chunk_id=f"hold-{self._current_tick}-{q_hash[:16]}", skill_id="broker-safe-hold",
                    source_observation_id=self._current_tick,
                    source_observation_time_ns=self._current_tick * 2_000_000,
                    generated_time_ns=self._current_tick * 2_000_000,
                    valid_from_ns=self._current_tick * 2_000_000,
                    expires_at_ns=self._terminal_tick * 2_000_000, dt_s=0.002,
                    actions=hold_actions, representation="JOINT_POSITION", expected_phase="track_target",
                    metadata={"origin": "broker_safe_hold", "hold_adapter": "p5_joint_pd_latch_v1",
                              "hold_latched_tick": self._current_tick, "measured_q_sha256": q_hash},
                )
                sidecar = {"source_observation_id": self._hold.source_observation_id,
                           "source_observation_time_ns": self._hold.source_observation_time_ns,
                           "q_sha256": q_hash, "dq_ref": (0.0, 0.0, 0.0)}
                self._events.append(BrokerTransition(self._current_tick, "CHUNK_ACCEPTED", self._hold.chunk_id, "BROKER_SAFE_HOLD", sidecar))
                self._events.append(BrokerTransition(self._current_tick, "SAFE_HOLD_ENTERED", self._hold.chunk_id, "LATCHED_CURRENT_Q_ZERO_DQ", sidecar))
            row = self._current_tick - self._hold.valid_from_ns // 2_000_000
            record = IssuedAction(self._current_tick, self._hold.chunk_id, "broker_safe_hold", self._hold.actions[row])
            self._hold_ticks.append(self._current_tick)
        self._issued.append(record); return record

    def close_tick(self) -> None:
        if not self._tick_open or self._current_tick >= self._terminal_tick or not self._issued_this_tick:
            raise BrokerError("execution tick cannot close without exactly one issue")
        if any(item.delivery_tick <= self._current_tick for item in self._pending.values()):
            raise BrokerError("delivery tick closed with an unmatched response")
        self._tick_open = False

    def finish(self) -> BrokerTransition:
        if self._finished or not self._tick_open or self._current_tick != self._terminal_tick:
            raise BrokerError("finish requires the open terminal tick")
        self._prepare_transition()
        if self._active is not None or self._hold is not None or self._pending:
            raise BrokerError("terminal has active or unmatched pending state")
        self._finished = True; self._tick_open = False
        event = BrokerTransition(self._current_tick, "TERMINAL_EMPTY", None, "NO_ACTIVE_OR_PENDING")
        self._events.append(event); return event
