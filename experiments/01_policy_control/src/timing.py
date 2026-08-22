"""Pure virtual request/response timing and delivery lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import heapq
from typing import Any

import numpy as np

from reflect.events import ExecutionEvent, ExecutionEventType
from reflect.types import ActionChunk, ControlReference

from .contracts import CommandStack, ExecutorState, ExperimentConfig, frozen_vector
from .representations import initial_executor_state, p5_transition, reference_for_tick


class DeliveryDisposition(str, Enum):
    ACCEPT = "ACCEPT"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class PolicyRequest:
    request_sequence: int
    request_tick: int
    period_ticks: int
    payload: ActionChunk

    def __post_init__(self) -> None:
        for name in ("request_sequence", "request_tick"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if type(self.period_ticks) is not int or self.period_ticks <= 0:
            raise ValueError("period_ticks must be a positive integer")
        if not isinstance(self.payload, ActionChunk):
            raise ValueError("payload must be an ActionChunk")


@dataclass(frozen=True, order=True)
class ScheduledResponse:
    delivery_tick: int
    request_sequence: int
    response: ActionChunk = field(compare=False)

    def __post_init__(self) -> None:
        for name in ("delivery_tick", "request_sequence"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if not isinstance(self.response, ActionChunk):
            raise ValueError("response must be an ActionChunk")


@dataclass(frozen=True)
class DeliveredResponse:
    response: Any
    request_sequence: int
    disposition: DeliveryDisposition


@dataclass(frozen=True)
class DeliveryBatch:
    delivered: tuple[DeliveredResponse, ...]
    pending: tuple[ScheduledResponse, ...]
    last_accepted_observation_id: int


@dataclass(frozen=True)
class SchedulerState:
    tick: int
    last_accepted_observation_id: int | None
    active_chunk: ActionChunk | None
    executor_state: ExecutorState
    q: np.ndarray
    dq: np.ndarray
    queue: tuple[ScheduledResponse, ...]
    unmatched_requests: tuple[int, ...]

    def __post_init__(self) -> None:
        if type(self.tick) is not int or self.tick < 0:
            raise ValueError("tick must be a nonnegative integer")
        if self.last_accepted_observation_id is not None and (type(self.last_accepted_observation_id) is not int or self.last_accepted_observation_id < 0):
            raise ValueError("last accepted observation must be nonnegative or null")
        if self.active_chunk is not None and not isinstance(self.active_chunk, ActionChunk):
            raise ValueError("active_chunk must be an ActionChunk or null")
        if not isinstance(self.executor_state, ExecutorState):
            raise ValueError("executor_state must be typed")
        object.__setattr__(self, "q", frozen_vector(self.q, "q", shape=(3,)))
        object.__setattr__(self, "dq", frozen_vector(self.dq, "dq", shape=(3,)))
        queue = tuple(self.queue)
        keys = [(item.delivery_tick, item.request_sequence) for item in queue]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate response queue key")
        if any(item.delivery_tick < self.tick for item in queue):
            raise ValueError("response delivery cannot be in the past")
        object.__setattr__(self, "queue", tuple(sorted(queue)))
        unmatched = tuple(self.unmatched_requests)
        if any(type(item) is not int or item < 0 for item in unmatched) or len(unmatched) != len(set(unmatched)):
            raise ValueError("unmatched requests must be unique nonnegative integers")
        object.__setattr__(self, "unmatched_requests", unmatched)

    @classmethod
    def initial(cls, q: np.ndarray) -> "SchedulerState":
        frozen = frozen_vector(q, "q", shape=(3,))
        return cls(0, None, None, initial_executor_state(frozen), frozen, np.zeros(3), (), ())


@dataclass(frozen=True)
class TickTransition:
    events: tuple[ExecutionEvent, ...]
    state: SchedulerState
    control_reference: ControlReference | None
    safe_hold: bool


def last_request_tick(episode_ticks: int, latency_ticks: int, extra_delay_ticks: int, period_ticks: int) -> int:
    if period_ticks <= 0:
        raise ValueError("period_ticks must be positive")
    cutoff = episode_ticks - latency_ticks - extra_delay_ticks - ((5 * period_ticks + 1) // 2)
    return max(0, cutoff - cutoff % period_ticks)


def schedule_response(
    request: PolicyRequest,
    latency_ticks: int,
    *,
    drop: bool = False,
    extra_delay_ticks: int = 0,
    response: Any | None = None,
) -> ScheduledResponse | None:
    if drop:
        return None
    if type(latency_ticks) is not int or latency_ticks < 0 or type(extra_delay_ticks) is not int or extra_delay_ticks < 0:
        raise ValueError("response delays must be nonnegative integers")
    return ScheduledResponse(
        request.request_tick + latency_ticks + extra_delay_ticks,
        request.request_sequence,
        request.payload if response is None else response,
    )


def deliver_due(
    now_tick: int,
    queue: list[ScheduledResponse] | tuple[ScheduledResponse, ...],
    last_accepted_observation_id: int,
) -> DeliveryBatch:
    heap = list(queue)
    heapq.heapify(heap)
    delivered: list[DeliveredResponse] = []
    accepted = last_accepted_observation_id
    while heap and heap[0].delivery_tick <= now_tick:
        item = heapq.heappop(heap)
        disposition = DeliveryDisposition.ACCEPT if item.request_sequence > accepted else DeliveryDisposition.OUT_OF_ORDER
        if disposition is DeliveryDisposition.ACCEPT:
            accepted = item.request_sequence
        delivered.append(DeliveredResponse(item.response, item.request_sequence, disposition))
    return DeliveryBatch(tuple(delivered), tuple(sorted(heap)), accepted)


def transition_tick(
    state: SchedulerState,
    config: ExperimentConfig,
    *,
    request: PolicyRequest | None = None,
    latency_ticks: int = 0,
    drop: bool = False,
    extra_delay_ticks: int = 0,
    telemetry_due: bool = False,
    planner_due: bool = False,
) -> TickTransition:
    """Apply the complete deterministic scheduler/lifecycle transition for one 2 ms tick."""
    tick = state.tick
    now_ns = tick * int(round(config.arm.timestep_s * 1e9))
    queue = list(state.queue)
    unmatched = list(state.unmatched_requests)
    events: list[ExecutionEvent] = []
    sequence = tick * 16

    def event(kind: ExecutionEventType, payload: dict[str, object]) -> None:
        nonlocal sequence
        events.append(ExecutionEvent(kind, now_ns, now_ns, "experiment01-scheduler", sequence, "scheduler", "config-v1", ("target",), "track", payload))
        sequence += 1

    if telemetry_due:
        observation_id = request.request_sequence if request is not None else (state.last_accepted_observation_id or 0)
        event(ExecutionEventType.OBSERVATION_RECEIVED, {"observation_id": observation_id, "observation_role": "policy_and_telemetry" if request is not None else "telemetry"})
    if request is not None:
        if request.request_tick != tick:
            raise ValueError("request tick must equal current virtual tick")
        if request.request_sequence in unmatched:
            raise ValueError("duplicate request sequence")
        event(ExecutionEventType.POLICY_REQUESTED, {"observation_id": request.request_sequence, "drop_injection": drop})
        unmatched.append(request.request_sequence)
        response = schedule_response(request, latency_ticks, drop=drop, extra_delay_ticks=extra_delay_ticks)
        if response is not None:
            if any((item.delivery_tick, item.request_sequence) == (response.delivery_tick, response.request_sequence) for item in queue):
                raise ValueError("duplicate response queue key")
            queue.append(response)

    last_accepted = state.last_accepted_observation_id
    active = state.active_chunk
    executor = state.executor_state
    due = sorted(item for item in queue if item.delivery_tick == tick)
    queue = [item for item in queue if item.delivery_tick != tick]
    for response in due:
        if response.request_sequence in unmatched:
            unmatched.remove(response.request_sequence)
        chunk = response.response
        event(ExecutionEventType.POLICY_RESPONDED, {"chunk_id": chunk.chunk_id})
        if last_accepted is not None and chunk.source_observation_id <= last_accepted:
            event(ExecutionEventType.CHUNK_REJECTED_OUT_OF_ORDER, {"chunk_id": chunk.chunk_id})
            continue
        if now_ns >= chunk.expires_at_ns:
            event(ExecutionEventType.CHUNK_REJECTED_EXPIRED, {"chunk_id": chunk.chunk_id})
            continue
        prior_valid = active is not None and now_ns < active.expires_at_ns
        if prior_valid:
            event(ExecutionEventType.CHUNK_REPLACED, {"chunk_id": active.chunk_id})
        elif active is not None:
            active = None
            executor = p5_transition(executor, "EXPIRY")
        active = chunk
        last_accepted = chunk.source_observation_id
        if chunk.metadata["stack_id"] == CommandStack.P5.value:
            executor = p5_transition(executor, "ACCEPT", chunk_id=chunk.chunk_id, active_still_valid=prior_valid)
        else:
            executor = ExecutorState(chunk.chunk_id, executor.latched_q_ref, executor.p5_qdot_previous, executor.p5_planner_q_ref, executor.p5_planner_enabled)
        event(ExecutionEventType.CHUNK_ACCEPTED, {"chunk_id": chunk.chunk_id})

    control_reference = None
    if active is not None and now_ns >= active.expires_at_ns:
        active = None
        executor = p5_transition(executor, "EXPIRY")
    if active is not None:
        stack = CommandStack(active.metadata["stack_id"])
        control_reference, executor, _ = reference_for_tick(stack, active, state.q, state.dq, now_ns, executor, config)
        event(ExecutionEventType.ACTION_EXECUTED, {"source_chunk_id": active.chunk_id})
    else:
        executor = p5_transition(executor, "SAFE_HOLD")
    next_state = SchedulerState(tick + 1, last_accepted, active, executor, state.q, state.dq, tuple(queue), tuple(unmatched))
    return TickTransition(tuple(events), next_state, control_reference, active is None)


def validate_terminal_state(state: SchedulerState, *, allowed_dropped_requests: tuple[int, ...] = ()) -> None:
    if state.queue:
        raise ValueError("terminal response queue must be empty")
    if tuple(sorted(state.unmatched_requests)) != tuple(sorted(allowed_dropped_requests)):
        raise ValueError("terminal unmatched requests differ from declared drops")
