from __future__ import annotations

import importlib
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from reflect.events import ExecutionEventType

from .helpers import config, policy_input


timing = importlib.import_module("experiments.01_policy_control.src.timing")


def test_last_request_tick_exact_cutoff() -> None:
    assert timing.last_request_tick(3125, 350, 0, 50) == 2650


def test_delivery_orders_due_responses_and_rejects_stale() -> None:
    contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
    old, new = _chunk(contracts.CommandStack.P1, 1), _chunk(contracts.CommandStack.P1, 2)
    queue = [
        timing.ScheduledResponse(200, 2, new),
        timing.ScheduledResponse(200, 1, old),
    ]
    batch = timing.deliver_due(200, queue, last_accepted_observation_id=1)
    assert [item.response.chunk_id for item in batch.delivered] == [old.chunk_id, new.chunk_id]
    assert [item.disposition for item in batch.delivered] == [timing.DeliveryDisposition.OUT_OF_ORDER, timing.DeliveryDisposition.ACCEPT]
    assert not batch.pending


def test_drop_is_the_only_unmatched_request() -> None:
    contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
    chunk = _chunk(contracts.CommandStack.P1, 3)
    request = timing.PolicyRequest(3, 100, 50, chunk)
    assert timing.schedule_response(request, latency_ticks=10, drop=True) is None
    response = timing.schedule_response(request, latency_ticks=10, drop=False)
    assert response.delivery_tick == 110 and response.request_sequence == 3


def _chunk(stack, sequence: int, response_ns: int = 0):
    contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
    rep = importlib.import_module("experiments.01_policy_control.src.representations")
    value = policy_input(response_ns=response_ns)
    observation = value.observation
    object.__setattr__(observation, "sequence_id", sequence)
    return rep.emit_chunk(stack, value, config())


def test_total_tick_transition_accept_replace_and_out_of_order() -> None:
    contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
    cfg = config()
    state = timing.SchedulerState.initial(np.zeros(3))
    first = timing.PolicyRequest(1, 0, 50, _chunk(contracts.CommandStack.P1, 1))
    result = timing.transition_tick(state, cfg, request=first, latency_ticks=0, telemetry_due=True)
    assert [event.event_type for event in result.events] == [
        ExecutionEventType.OBSERVATION_RECEIVED,
        ExecutionEventType.POLICY_REQUESTED,
        ExecutionEventType.POLICY_RESPONDED,
        ExecutionEventType.CHUNK_ACCEPTED,
        ExecutionEventType.ACTION_EXECUTED,
    ]
    assert result.state.active_chunk.source_observation_id == 1 and not result.safe_hold

    second = timing.PolicyRequest(2, 1, 50, _chunk(contracts.CommandStack.P1, 2, 2_000_000))
    replaced = timing.transition_tick(result.state, cfg, request=second, latency_ticks=0)
    assert [event.event_type for event in replaced.events][1:4] == [
        ExecutionEventType.POLICY_RESPONDED,
        ExecutionEventType.CHUNK_REPLACED,
        ExecutionEventType.CHUNK_ACCEPTED,
    ]

    stale = timing.ScheduledResponse(replaced.state.tick, 1, first.payload)
    stale_state = timing.SchedulerState(
        replaced.state.tick, replaced.state.last_accepted_observation_id,
        replaced.state.active_chunk, replaced.state.executor_state,
        replaced.state.q, replaced.state.dq, (stale,), replaced.state.unmatched_requests,
    )
    rejected = timing.transition_tick(stale_state, cfg)
    assert [event.event_type for event in rejected.events][:2] == [ExecutionEventType.POLICY_RESPONDED, ExecutionEventType.CHUNK_REJECTED_OUT_OF_ORDER]


def test_half_open_expiry_safe_hold_and_p5_reset_reaccept() -> None:
    contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
    cfg = config()
    p5 = _chunk(contracts.CommandStack.P5, 1)
    state = timing.SchedulerState.initial(np.zeros(3))
    accepted = timing.transition_tick(state, cfg, request=timing.PolicyRequest(1, 0, 50, p5), latency_ticks=0, planner_due=True)
    assert accepted.state.executor_state.p5_planner_enabled
    expired_tick = p5.expires_at_ns // 2_000_000
    expired_state = timing.SchedulerState(expired_tick, 1, p5, accepted.state.executor_state, np.zeros(3), np.zeros(3), (), ())
    expired = timing.transition_tick(expired_state, cfg)
    assert expired.safe_hold and expired.state.active_chunk is None
    assert not expired.state.executor_state.p5_planner_enabled
    newer = _chunk(contracts.CommandStack.P5, 2, expired.state.tick * 2_000_000)
    reaccepted = timing.transition_tick(expired.state, cfg, request=timing.PolicyRequest(2, expired.state.tick, 50, newer), latency_ticks=0, planner_due=True)
    assert reaccepted.state.executor_state.p5_planner_enabled


def test_scheduler_state_rejects_duplicate_queue_and_is_deep_immutable() -> None:
    contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
    chunk = _chunk(contracts.CommandStack.P1, 1)
    response = timing.ScheduledResponse(2, 1, chunk)
    with pytest.raises(ValueError, match="duplicate"):
        timing.SchedulerState(0, None, None, timing.initial_executor_state(np.zeros(3)), np.zeros(3), np.zeros(3), (response, response), ())
    state = timing.SchedulerState.initial(np.zeros(3))
    assert not state.q.flags.writeable
    with pytest.raises((ValueError, FrozenInstanceError)):
        state.q[0] = 3.0


def test_terminal_validation_allows_only_declared_drop() -> None:
    state = timing.SchedulerState.initial(np.zeros(3))
    dropped = timing.SchedulerState(1, None, None, state.executor_state, state.q, state.dq, (), (4,))
    timing.validate_terminal_state(dropped, allowed_dropped_requests=(4,))
    with pytest.raises(ValueError, match="unmatched"):
        timing.validate_terminal_state(dropped)
