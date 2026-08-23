"""P4 policy-output adapter and representation-safe P5 joint hold."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib

import numpy as np

from reflect.types import ActionChunk, ControlReference

from .broker import SealedProposal, _seal_proposal, apply_fault_payload


_kinematics = importlib.import_module("experiments.01_policy_control.src.kinematics")
_TICK_NS = 2_000_000
_KNOT_NS = 100_000_000
_ROWS = 125


class AdapterError(ValueError):
    pass


def _strict_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdapterError(f"{name} must be a nonnegative integer, not bool")
    return value


def _matrix(value: object, shape: tuple[int, int]) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind != "f" or array.dtype.itemsize != 8 or array.shape != shape or not np.isfinite(array).all():
        raise AdapterError(f"policy output must contain exactly nine finite float64 knots with shape {shape}")
    result = np.array(array, dtype="<f8", order="C", copy=True)
    result.setflags(write=False)
    return result


def _sha(array: np.ndarray) -> str:
    return hashlib.sha256(array.astype("<f8", copy=False).tobytes(order="C")).hexdigest()


@dataclass(frozen=True)
class PolicyRaw:
    proposal_id: str
    stack_id: str
    skill_id: str
    source_observation_id: int
    source_observation_time_ns: int
    expected_phase: str
    actions: np.ndarray

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.proposal_id, self.skill_id, self.expected_phase)):
            raise AdapterError("policy identifiers must be nonempty strings")
        if self.stack_id not in {"P2", "P4"}:
            raise AdapterError("adapter supports only promoted P2/P4 policy output")
        _strict_int("source_observation_id", self.source_observation_id)
        _strict_int("source_observation_time_ns", self.source_observation_time_ns)
        width = 3 if self.stack_id == "P2" else 2
        object.__setattr__(self, "actions", _matrix(self.actions, (9, width)))

    @property
    def actions_sha256(self) -> str:
        return _sha(self.actions)

    @property
    def dt_s(self) -> float:
        return 0.100


def _matrix_rows(value: object, shape: tuple[int, int]) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind != "f" or array.dtype.itemsize != 8 or array.shape != shape or not np.isfinite(array).all():
        raise AdapterError(f"normalized proposal must be finite float64 with shape {shape}")
    result = np.array(array, dtype="<f8", order="C", copy=True)
    result.setflags(write=False)
    return result


def normalize_policy_raw(
    raw: PolicyRaw,
    actual_delivery_tick: int | None,
    *,
    normal_delivery_tick: int | None = None,
    request_id: str | None = None,
    request_sequence: int | None = None,
) -> SealedProposal:
    if not isinstance(raw, PolicyRaw):
        raise AdapterError("raw must be PolicyRaw")
    if actual_delivery_tick is None:
        raise AdapterError("actual delivery is required before materialization")
    tick = _strict_int("actual_delivery_tick", actual_delivery_tick)
    normal = tick if normal_delivery_tick is None else _strict_int("normal_delivery_tick", normal_delivery_tick)
    sequence = raw.source_observation_id if request_sequence is None else _strict_int("request_sequence", request_sequence)
    request = raw.proposal_id if request_id is None else request_id
    if not isinstance(request, str) or not request:
        raise AdapterError("request_id must be nonempty")
    if tick + _ROWS > 3125:
        raise AdapterError("normalized coverage exceeds terminal tick")
    actions = np.vstack(
        [_kinematics.linear_knot_reference(raw.actions, row * _TICK_NS, _KNOT_NS) for row in range(_ROWS)]
    ).astype("<f8", order="C", copy=False)
    representation = "JOINT_POSITION" if raw.stack_id == "P2" else "EEF_TRAJECTORY"
    return _seal_proposal(
        proposal_id=raw.proposal_id, request_id=request, request_sequence=sequence,
        stack_id=raw.stack_id, representation=representation, skill_id=raw.skill_id, expected_phase=raw.expected_phase,
        source_observation_id=raw.source_observation_id, source_observation_time_ns=raw.source_observation_time_ns,
        normal_delivery_tick=normal, actual_delivery_tick=tick, coverage_start_tick=tick, coverage_end_tick=tick + _ROWS,
        delivery_mode="normal" if normal == tick else "paused", raw_actions=raw.actions, actions=actions,
        policy_actions_sha256=raw.actions_sha256, normalized_actions_sha256=_sha(actions), fault_id=None,
        fault_revision=None, fault_step_index=None, fault_amplitude=None, fault_direction=None, fault_sign=None,
        pre_fault_normalized_sha256=None, disposition="DELIVERED",
    )


def verify_normalized_policy(normalized: SealedProposal) -> bool:
    if not isinstance(normalized, SealedProposal):
        return False
    try:
        raw = PolicyRaw(normalized.proposal_id, normalized.stack_id, normalized.skill_id, normalized.source_observation_id, normalized.source_observation_time_ns, normalized.expected_phase, normalized.raw_actions)
        base = normalize_policy_raw(raw, normalized.actual_delivery_tick, normal_delivery_tick=normalized.normal_delivery_tick, request_id=normalized.request_id, request_sequence=normalized.request_sequence)
        expected = base.actions
        if normalized.fault_id is not None:
            if normalized.fault_revision != "exp02-fault-payload-v1" or normalized.fault_id not in {"ALTERNATIVE", "DISCONTINUITY"}:
                return False
            direction = np.asarray(normalized.fault_direction, dtype=np.float64)
            if direction.shape != (expected.shape[1],) or normalized.fault_sign not in {-1, 1}:
                return False
            expected_amplitude = {("P2", "ALTERNATIVE"): 0.05, ("P2", "DISCONTINUITY"): 0.10, ("P4", "ALTERNATIVE"): 0.02, ("P4", "DISCONTINUITY"): 0.03}[(normalized.stack_id, normalized.fault_id)]
            if normalized.fault_amplitude != expected_amplitude or normalized.pre_fault_normalized_sha256 != _sha(base.actions):
                return False
            if normalized.fault_id == "ALTERNATIVE":
                weights = np.sin(np.pi * np.arange(125, dtype=np.float64) / 124.0); weights[[0, -1]] = 0.0
                if normalized.fault_step_index is not None: return False
            else:
                weights = np.zeros(125); weights[2:] = 1.0
                if normalized.fault_step_index != 2: return False
            expected = base.actions + normalized.fault_sign * expected_amplitude * weights[:, None] * direction[None, :]
        return _sha(expected) == normalized.normalized_actions_sha256 and expected.astype("<f8").tobytes(order="C") == normalized.actions.tobytes(order="C")
    except (AdapterError, KeyError, TypeError, ValueError):
        return False


def inject_fault(normalized: SealedProposal, *, fault_id: str, envelope: tuple[float, float]) -> SealedProposal:
    if not verify_normalized_policy(normalized) or normalized.fault_id is not None:
        raise AdapterError("fault injection requires an unfaulted inverse-verified proposal")
    fault = apply_fault_payload(normalized.actions, stack_id=normalized.stack_id, fault_id=fault_id, envelope=envelope)
    return _seal_proposal(
        proposal_id=normalized.proposal_id, request_id=normalized.request_id, request_sequence=normalized.request_sequence,
        stack_id=normalized.stack_id, representation=normalized.representation, skill_id=normalized.skill_id, expected_phase=normalized.expected_phase,
        source_observation_id=normalized.source_observation_id, source_observation_time_ns=normalized.source_observation_time_ns,
        normal_delivery_tick=normalized.normal_delivery_tick, actual_delivery_tick=normalized.actual_delivery_tick,
        coverage_start_tick=normalized.coverage_start_tick, coverage_end_tick=normalized.coverage_end_tick,
        delivery_mode=normalized.delivery_mode, raw_actions=normalized.raw_actions, actions=fault.actions,
        policy_actions_sha256=normalized.policy_actions_sha256, normalized_actions_sha256=fault.post_sha256,
        fault_id=fault_id, fault_revision=fault.revision, fault_step_index=fault.step_index,
        fault_amplitude=fault.amplitude, fault_direction=tuple(float(value) for value in fault.direction), fault_sign=fault.sign,
        pre_fault_normalized_sha256=fault.pre_sha256, disposition="DELIVERED",
    )


def make_safe_hold(
    q: object,
    *,
    source_observation_id: int,
    source_observation_time_ns: int,
    skill_id: str,
    expected_phase: str,
    start_tick: int,
    terminal_tick: int,
) -> ActionChunk:
    start = _strict_int("start_tick", start_tick)
    terminal = _strict_int("terminal_tick", terminal_tick)
    _strict_int("source_observation_id", source_observation_id)
    _strict_int("source_observation_time_ns", source_observation_time_ns)
    vector = np.asarray(q)
    if vector.dtype.kind != "f" or vector.dtype.itemsize != 8 or vector.shape != (3,) or not np.isfinite(vector).all():
        raise AdapterError("hold q must be finite float64 shape three")
    if not start < terminal or terminal != 3125:
        raise AdapterError("hold must extend exactly to terminal tick 3125")
    latched = np.array(vector, dtype="<f8", order="C", copy=True)
    actions = np.tile(latched, (terminal - start, 1))
    q_hash = hashlib.sha256(latched.tobytes(order="C")).hexdigest()
    return ActionChunk(
        chunk_id=f"p5-hold-{start}-{q_hash[:16]}",
        skill_id=skill_id,
        source_observation_id=source_observation_id,
        source_observation_time_ns=source_observation_time_ns,
        generated_time_ns=start * _TICK_NS,
        valid_from_ns=start * _TICK_NS,
        expires_at_ns=terminal * _TICK_NS,
        dt_s=0.002,
        actions=actions,
        representation="JOINT_POSITION",
        expected_phase=expected_phase,
        metadata={"origin": "broker_safe_hold", "hold_adapter": "p5_joint_pd_latch_v1", "hold_latched_tick": start, "measured_q_sha256": q_hash},
    )


def dispatch_executable(chunk: ActionChunk | SealedProposal, *, tick: int) -> ActionChunk | ControlReference | None:
    current = _strict_int("tick", tick)
    if isinstance(chunk, SealedProposal):
        if not verify_normalized_policy(chunk):
            raise AdapterError("dispatch requires mandatory inverse/raw binding")
        if current != chunk.actual_delivery_tick:
            raise AdapterError("direct proposal dispatch must start at actual delivery")
        return ActionChunk(
            chunk_id=f"p5-direct-{chunk.proposal_id}",
            skill_id=chunk.skill_id,
            source_observation_id=chunk.source_observation_id,
            source_observation_time_ns=chunk.source_observation_time_ns,
            generated_time_ns=current * _TICK_NS,
            valid_from_ns=current * _TICK_NS,
            expires_at_ns=(current + _ROWS) * _TICK_NS,
            dt_s=0.002,
            actions=chunk.actions,
            representation=chunk.representation,
            expected_phase=chunk.expected_phase,
            metadata={"origin": "direct_normalized", "stack_id": chunk.stack_id, "policy_actions_sha256": chunk.policy_actions_sha256, "normalized_actions_sha256": chunk.actions_sha256},
        )
    if not isinstance(chunk, ActionChunk) or chunk.metadata.get("origin") != "broker_safe_hold":
        raise AdapterError("dispatch supports only representation-safe broker hold")
    time_ns = current * _TICK_NS
    if time_ns < chunk.valid_from_ns:
        raise AdapterError("hold cannot execute before validity")
    if time_ns >= chunk.expires_at_ns:
        return None
    row = (time_ns - chunk.valid_from_ns) // _TICK_NS
    q_ref = chunk.actions[row]
    return ControlReference(chunk.chunk_id, time_ns, q_ref, np.zeros(3, dtype=np.float64), None, None, "p5_joint_pd_hold")
