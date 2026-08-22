"""Pure virtual request/response timing and delivery lifecycle."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import heapq
from typing import Any

import numpy as np

from reflect.events import ExecutionEvent, ExecutionEventType
from reflect.rollout import RolloutMetadata, RolloutRecord, sha256_json
from reflect.types import ActionChunk, ControlReference, Observation

from .contracts import ClampReport, CommandStack, ExecutorState, ExperimentConfig, frozen_vector
from .representations import initial_executor_state, p5_transition, reference_for_tick


class DeliveryDisposition(str, Enum):
    ACCEPT = "ACCEPT"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    EXPIRED = "EXPIRED"


class SafeHoldDisposition(str, Enum):
    SAFE_HOLD = "SAFE_HOLD"


@dataclass(frozen=True)
class SafeHoldCommand:
    q_ref: np.ndarray
    dq_ref: np.ndarray
    disposition: SafeHoldDisposition = SafeHoldDisposition.SAFE_HOLD

    def __post_init__(self) -> None:
        object.__setattr__(self, "q_ref", frozen_vector(self.q_ref, "safe_hold.q_ref", shape=(3,)))
        object.__setattr__(self, "dq_ref", frozen_vector(self.dq_ref, "safe_hold.dq_ref", shape=(3,)))
        object.__setattr__(self, "disposition", SafeHoldDisposition(self.disposition))


@dataclass(frozen=True)
class PolicyRequest:
    observation: Observation
    request_tick: int
    period_ticks: int
    payload: ActionChunk

    def __post_init__(self) -> None:
        if not isinstance(self.observation, Observation):
            raise ValueError("observation must be an Observation")
        if type(self.request_tick) is not int or self.request_tick < 0:
            raise ValueError("request_tick must be a nonnegative integer")
        if type(self.period_ticks) is not int or self.period_ticks <= 0:
            raise ValueError("period_ticks must be a positive integer")
        if not isinstance(self.payload, ActionChunk):
            raise ValueError("payload must be an ActionChunk")
        if self.payload.source_observation_id != self.observation.sequence_id:
            raise ValueError("payload source observation does not match request observation")
        if self.payload.source_observation_time_ns != self.observation.source_time_ns:
            raise ValueError("payload source time does not match request observation")
        if self.payload.skill_id != self.observation.current_skill_id:
            raise ValueError("payload skill does not match request observation")
        if self.payload.expected_phase != self.observation.current_phase:
            raise ValueError("payload expected phase does not match request observation")

    @property
    def request_sequence(self) -> int:
        return self.observation.sequence_id


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
    declared_dropped_requests: tuple[int, ...]
    rollout_id: str
    config_hash: str
    observations: tuple[Observation, ...] = ()
    actions: tuple[ActionChunk, ...] = ()
    events: tuple[ExecutionEvent, ...] = ()
    control_references: tuple[ControlReference, ...] = ()

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
        declared = tuple(self.declared_dropped_requests)
        if any(type(item) is not int or item < 0 for item in declared) or len(declared) != len(set(declared)):
            raise ValueError("declared dropped requests must be unique nonnegative integers")
        if not set(declared).issubset(unmatched):
            raise ValueError("declared dropped requests must remain unmatched")
        object.__setattr__(self, "declared_dropped_requests", declared)
        for name in ("rollout_id", "config_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        observations = tuple(self.observations)
        if not all(isinstance(item, Observation) for item in observations):
            raise ValueError("observations must be typed")
        if len({item.sequence_id for item in observations}) != len(observations):
            raise ValueError("observation IDs must be unique")
        if any(left.sequence_id >= right.sequence_id for left, right in zip(observations, observations[1:])):
            raise ValueError("observation IDs must be strictly increasing")
        object.__setattr__(self, "observations", observations)
        actions = tuple(self.actions)
        if not all(isinstance(item, ActionChunk) for item in actions):
            raise ValueError("actions must be typed")
        if len({item.chunk_id for item in actions}) != len(actions):
            raise ValueError("action chunk IDs must be unique")
        object.__setattr__(self, "actions", actions)
        events = tuple(self.events)
        references = tuple(self.control_references)
        if not all(isinstance(item, ExecutionEvent) for item in events):
            raise ValueError("events must be typed")
        if not all(isinstance(item, ControlReference) for item in references):
            raise ValueError("control references must be typed")
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "control_references", references)

    @classmethod
    def initial(cls, q: np.ndarray, config: ExperimentConfig, *, rollout_id: str) -> "SchedulerState":
        frozen = frozen_vector(q, "q", shape=(3,))
        return cls(
            0, None, None, initial_executor_state(frozen), frozen, np.zeros(3), (), (), (),
            rollout_id, sha256_json(scheduler_config(config)),
        )


@dataclass(frozen=True)
class TickTransition:
    events: tuple[ExecutionEvent, ...]
    state: SchedulerState
    control_reference: ControlReference | None
    safe_hold: bool
    safe_hold_command: SafeHoldCommand | None
    control_report: ClampReport | None


def _jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def scheduler_config(config: ExperimentConfig) -> dict[str, object]:
    """Return the exact canonical experiment config bound into scheduler events."""
    value = _jsonable(asdict(config))
    if not isinstance(value, dict):  # pragma: no cover - dataclass invariant
        raise TypeError("experiment config did not serialize as a mapping")
    return value


def scheduler_rollout_record(state: SchedulerState, config: ExperimentConfig) -> RolloutRecord:
    """Construct the shared artifact contract from one terminal scheduler state."""
    validate_terminal_state(state)
    wire_config = scheduler_config(config)
    config_hash = sha256_json(wire_config)
    if state.config_hash != config_hash:
        raise ValueError("scheduler state config identity mismatch")
    tick_ns = int(round(config.arm.timestep_s * 1e9))
    end_ns = max(
        0,
        (state.tick - 1) * tick_ns,
        *(action.expires_at_ns for action in state.actions),
    )
    metadata = RolloutMetadata(
        experiment_id="experiment-01",
        claim_revision=1,
        git_sha="0" * 40,
        working_tree_clean=True,
        dirty_diff_hash=None,
        source_lock_hash="0" * 64,
        os_arch="local",
        cpu="local",
        gpu=None,
        python_version="3.11.13",
        dependency_versions={"numpy": np.__version__},
        seed=0,
        simulator="virtual-scheduler",
        task_config_hash=config_hash,
        model_hashes={},
        action_schema_version=1,
        observation_schema_version=1,
        wall_start_ns=0,
        wall_end_ns=end_ns,
        monotonic_start_ns=0,
        monotonic_end_ns=end_ns,
        status="pass",
    )
    return RolloutRecord(
        metadata,
        wire_config,
        {"ticks": state.tick, "declared_dropped_requests": list(state.declared_dropped_requests)},
        state.events,
        state.observations,
        state.actions,
        state.control_references,
        "Experiment 01 deterministic scheduler trace.\n",
    )


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
    telemetry: Observation | None = None,
    planner_due: bool = False,
    record_execution: bool = True,
) -> TickTransition:
    """Apply the complete deterministic scheduler/lifecycle transition for one 2 ms tick."""
    tick = state.tick
    now_ns = tick * int(round(config.arm.timestep_s * 1e9))
    queue = list(state.queue)
    unmatched = list(state.unmatched_requests)
    declared_drops = list(state.declared_dropped_requests)
    observations = list(state.observations)
    actions = list(state.actions)
    events: list[ExecutionEvent] = []
    references = list(state.control_references)
    sequence = len(state.events)

    def event(
        kind: ExecutionEventType,
        payload: dict[str, object],
        *,
        skill_id: str | None,
        object_ids: tuple[str, ...],
    ) -> None:
        nonlocal sequence
        events.append(
            ExecutionEvent(
                kind,
                now_ns,
                now_ns,
                state.rollout_id,
                sequence,
                "experiment01-scheduler",
                state.config_hash,
                object_ids,
                skill_id,
                payload,
            )
        )
        sequence += 1

    request_observation = request.observation if request is not None else None
    if telemetry is not None and not isinstance(telemetry, Observation):
        raise ValueError("telemetry must be an Observation or null")
    if telemetry is not None and request_observation is not None and telemetry is not request_observation:
        raise ValueError("coincident telemetry and policy request must reuse one Observation")
    incoming_observation = request_observation if request_observation is not None else telemetry
    if incoming_observation is not None:
        if incoming_observation.received_time_ns != now_ns:
            raise ValueError("observation received time must equal current virtual tick")
        if any(item.sequence_id == incoming_observation.sequence_id for item in observations):
            raise ValueError("observation ID was already stored")
        if observations and incoming_observation.sequence_id <= observations[-1].sequence_id:
            raise ValueError("observation IDs must be strictly increasing")
        if incoming_observation.current_skill_id != "track" or incoming_observation.current_phase != "track_target":
            raise ValueError("observation skill/phase must remain track/track_target")
        observations.append(incoming_observation)
        object_ids = tuple(item.entity_id for item in incoming_observation.object_beliefs)
        event(
            ExecutionEventType.OBSERVATION_RECEIVED,
            {
                "observation_id": incoming_observation.sequence_id,
                "observation_role": "policy_and_telemetry" if request is not None else "telemetry",
                "current_phase": incoming_observation.current_phase,
            },
            skill_id=incoming_observation.current_skill_id,
            object_ids=object_ids,
        )
    if request is not None:
        if request.request_tick != tick:
            raise ValueError("request tick must equal current virtual tick")
        if request.request_sequence in unmatched:
            raise ValueError("duplicate request sequence")
        if request.observation.received_time_ns != now_ns:
            raise ValueError("request observation must be received on the request tick")
        object_ids = tuple(item.entity_id for item in request.observation.object_beliefs)
        event(
            ExecutionEventType.POLICY_REQUESTED,
            {
                "source_observation_id": request.request_sequence,
                "drop_injection": drop,
                "current_phase": request.observation.current_phase,
            },
            skill_id=request.observation.current_skill_id,
            object_ids=object_ids,
        )
        unmatched.append(request.request_sequence)
        if drop:
            declared_drops.append(request.request_sequence)
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
        if chunk.generated_time_ns != now_ns:
            raise ValueError("response chunk generation time must equal delivery tick")
        actions.append(chunk)
        source = next(item for item in observations if item.sequence_id == chunk.source_observation_id)
        object_ids = tuple(item.entity_id for item in source.object_beliefs)
        event(
            ExecutionEventType.POLICY_RESPONDED,
            {"chunk_id": chunk.chunk_id, "source_observation_id": chunk.source_observation_id},
            skill_id=chunk.skill_id,
            object_ids=object_ids,
        )
        if last_accepted is not None and chunk.source_observation_id <= last_accepted:
            event(
                ExecutionEventType.CHUNK_REJECTED_OUT_OF_ORDER,
                {"chunk_id": chunk.chunk_id, "source_observation_id": chunk.source_observation_id},
                skill_id=chunk.skill_id,
                object_ids=object_ids,
            )
            continue
        if now_ns >= chunk.expires_at_ns:
            event(
                ExecutionEventType.CHUNK_REJECTED_EXPIRED,
                {"chunk_id": chunk.chunk_id, "source_observation_id": chunk.source_observation_id},
                skill_id=chunk.skill_id,
                object_ids=object_ids,
            )
            continue
        prior_valid = active is not None and now_ns < active.expires_at_ns
        if prior_valid:
            prior_source = next(item for item in observations if item.sequence_id == active.source_observation_id)
            event(
                ExecutionEventType.CHUNK_REPLACED,
                {"chunk_id": active.chunk_id, "source_observation_id": active.source_observation_id},
                skill_id=active.skill_id,
                object_ids=tuple(item.entity_id for item in prior_source.object_beliefs),
            )
        elif active is not None:
            active = None
            executor = ExecutorState(None, state.q, np.zeros(3), state.q, False)
        active = chunk
        last_accepted = chunk.source_observation_id
        if chunk.metadata["stack_id"] == CommandStack.P5.value:
            executor = p5_transition(executor, "ACCEPT", chunk_id=chunk.chunk_id, active_still_valid=prior_valid)
        else:
            executor = ExecutorState(chunk.chunk_id, state.q, np.zeros(3), state.q, False)
        event(
            ExecutionEventType.CHUNK_ACCEPTED,
            {"chunk_id": chunk.chunk_id, "source_observation_id": chunk.source_observation_id},
            skill_id=chunk.skill_id,
            object_ids=object_ids,
        )

    control_reference = None
    safe_hold_command = None
    control_report = None
    if active is not None and now_ns >= active.expires_at_ns:
        active = None
        executor = ExecutorState(None, state.q, np.zeros(3), state.q, False)
    if active is not None:
        stack = CommandStack(active.metadata["stack_id"])
        control_reference, executor, control_report = reference_for_tick(stack, active, state.q, state.dq, now_ns, executor, config)
        if record_execution:
            references.append(control_reference)
            source = next(item for item in observations if item.sequence_id == active.source_observation_id)
            event(
                ExecutionEventType.ACTION_EXECUTED,
                {
                    "source_chunk_id": active.chunk_id,
                    "source_observation_id": active.source_observation_id,
                    "time_ns": now_ns,
                },
                skill_id=active.skill_id,
                object_ids=tuple(item.entity_id for item in source.object_beliefs),
            )
    else:
        executor = ExecutorState(None, state.q, np.zeros(3), state.q, False)
        safe_hold_command = SafeHoldCommand(state.q, np.zeros(3))
    next_state = SchedulerState(
        tick + 1,
        last_accepted,
        active,
        executor,
        state.q,
        state.dq,
        tuple(queue),
        tuple(unmatched),
        tuple(declared_drops),
        state.rollout_id,
        state.config_hash,
        tuple(observations),
        tuple(actions),
        state.events + tuple(events),
        tuple(references),
    )
    return TickTransition(tuple(events), next_state, control_reference, active is None, safe_hold_command, control_report)


def validate_terminal_state(state: SchedulerState, *, allowed_dropped_requests: tuple[int, ...] | None = None) -> None:
    if state.queue:
        raise ValueError("terminal response queue must be empty")
    allowed = state.declared_dropped_requests if allowed_dropped_requests is None else tuple(allowed_dropped_requests)
    if tuple(sorted(allowed)) != tuple(sorted(state.declared_dropped_requests)):
        raise ValueError("terminal allowed drops differ from declared drops")
    if tuple(sorted(state.unmatched_requests)) != tuple(sorted(allowed)):
        raise ValueError("terminal unmatched requests differ from declared drops")
