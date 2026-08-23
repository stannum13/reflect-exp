"""P4 policy-output adapter and representation-safe P5 joint hold."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib

import numpy as np

from reflect.types import ActionChunk, ControlReference


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


@dataclass(frozen=True)
class NormalizedPolicyProposal:
    proposal_id: str
    stack_id: str
    skill_id: str
    source_observation_id: int
    source_observation_time_ns: int
    expected_phase: str
    representation: str
    actual_delivery_tick: int
    actions: np.ndarray
    policy_actions_sha256: str

    def __post_init__(self) -> None:
        width = 3 if self.stack_id == "P2" else 2
        object.__setattr__(self, "actions", _matrix_rows(self.actions, (125, width)))

    @property
    def coverage_ticks(self) -> tuple[int, int]:
        return self.actual_delivery_tick, self.actual_delivery_tick + _ROWS

    @property
    def actions_sha256(self) -> str:
        return _sha(self.actions)

    @property
    def dt_s(self) -> float:
        return 0.002


def _matrix_rows(value: object, shape: tuple[int, int]) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind != "f" or array.dtype.itemsize != 8 or array.shape != shape or not np.isfinite(array).all():
        raise AdapterError(f"normalized proposal must be finite float64 with shape {shape}")
    result = np.array(array, dtype="<f8", order="C", copy=True)
    result.setflags(write=False)
    return result


def normalize_policy_raw(raw: PolicyRaw, actual_delivery_tick: int | None) -> NormalizedPolicyProposal:
    if not isinstance(raw, PolicyRaw):
        raise AdapterError("raw must be PolicyRaw")
    if actual_delivery_tick is None:
        raise AdapterError("actual delivery is required before materialization")
    tick = _strict_int("actual_delivery_tick", actual_delivery_tick)
    if tick + _ROWS > 3125:
        raise AdapterError("normalized coverage exceeds terminal tick")
    actions = np.vstack(
        [_kinematics.linear_knot_reference(raw.actions, row * _TICK_NS, _KNOT_NS) for row in range(_ROWS)]
    ).astype("<f8", order="C", copy=False)
    representation = "JOINT_POSITION" if raw.stack_id == "P2" else "EEF_TRAJECTORY"
    return NormalizedPolicyProposal(
        raw.proposal_id,
        raw.stack_id,
        raw.skill_id,
        raw.source_observation_id,
        raw.source_observation_time_ns,
        raw.expected_phase,
        representation,
        tick,
        actions,
        raw.actions_sha256,
    )


def verify_normalized_policy(raw: PolicyRaw, normalized: NormalizedPolicyProposal) -> bool:
    if not isinstance(raw, PolicyRaw) or not isinstance(normalized, NormalizedPolicyProposal):
        return False
    try:
        rebuilt = normalize_policy_raw(raw, normalized.actual_delivery_tick)
    except AdapterError:
        return False
    return (
        rebuilt.proposal_id == normalized.proposal_id
        and rebuilt.stack_id == normalized.stack_id
        and rebuilt.skill_id == normalized.skill_id
        and rebuilt.source_observation_id == normalized.source_observation_id
        and rebuilt.source_observation_time_ns == normalized.source_observation_time_ns
        and rebuilt.expected_phase == normalized.expected_phase
        and rebuilt.representation == normalized.representation
        and rebuilt.policy_actions_sha256 == normalized.policy_actions_sha256
        and rebuilt.actions.tobytes(order="C") == normalized.actions.tobytes(order="C")
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


def dispatch_executable(chunk: ActionChunk | NormalizedPolicyProposal, *, tick: int) -> ActionChunk | ControlReference | None:
    current = _strict_int("tick", tick)
    if isinstance(chunk, NormalizedPolicyProposal):
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
