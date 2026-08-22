from __future__ import annotations

import importlib
import time
from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest

from reflect.events import ExecutionEventType
from reflect.rollout import RolloutWriter, validate_rollout

from .helpers import config, policy_input


timing = importlib.import_module("experiments.01_policy_control.src.timing")
contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
rep = importlib.import_module("experiments.01_policy_control.src.representations")


def _request(stack, sequence: int, tick: int, *, response_tick: int | None = None):
    response_tick = tick if response_tick is None else response_tick
    value = policy_input(response_ns=response_tick * 2_000_000)
    observation = replace(value.observation, sequence_id=sequence, source_time_ns=tick * 2_000_000, received_time_ns=tick * 2_000_000)
    captured = contracts.PolicyInput(observation, value.skill, response_tick * 2_000_000, value.policy_period_ns, value.q_initial, value.q_initial_target)
    return timing.PolicyRequest(observation, tick, 50, rep.emit_chunk(stack, captured, config()))


def _initial(cfg=None, q=None, rollout_id="timing-test"):
    cfg = config() if cfg is None else cfg
    q = np.zeros(3) if q is None else q
    return timing.SchedulerState.initial(q, cfg, rollout_id=rollout_id)


def _copy_state(state, **changes):
    values = {name: getattr(state, name) for name in (
        "tick", "last_accepted_observation_id", "active_chunk", "executor_state", "q", "dq",
        "queue", "unmatched_requests", "rollout_id", "config_hash", "observations", "actions",
        "events", "control_references",
    )}
    values.update(changes)
    return timing.SchedulerState(**values)


def test_last_request_tick_exact_cutoff() -> None:
    assert timing.last_request_tick(3125, 350, 0, 50) == 2650


def test_delivery_orders_due_responses_and_rejects_stale() -> None:
    old = _request(contracts.CommandStack.P1, 1, 0).payload
    new = _request(contracts.CommandStack.P1, 2, 0).payload
    queue = [timing.ScheduledResponse(200, 2, new), timing.ScheduledResponse(200, 1, old)]
    batch = timing.deliver_due(200, queue, last_accepted_observation_id=1)
    assert [item.response.chunk_id for item in batch.delivered] == [old.chunk_id, new.chunk_id]
    assert [item.disposition for item in batch.delivered] == [timing.DeliveryDisposition.OUT_OF_ORDER, timing.DeliveryDisposition.ACCEPT]
    assert not batch.pending


def test_drop_is_the_only_unmatched_request() -> None:
    request = _request(contracts.CommandStack.P1, 3, 100, response_tick=110)
    assert timing.schedule_response(request, latency_ticks=10, drop=True) is None
    response = timing.schedule_response(request, latency_ticks=10)
    assert response.delivery_tick == 110 and response.request_sequence == 3


def test_real_observation_precedes_request_and_coincidence_reuses_it() -> None:
    cfg = config()
    request = _request(contracts.CommandStack.P1, 1, 0)
    result = timing.transition_tick(_initial(cfg), cfg, request=request, telemetry=request.observation)
    assert result.state.observations == (request.observation,)
    assert [event.event_type for event in result.events[:2]] == [ExecutionEventType.OBSERVATION_RECEIVED, ExecutionEventType.POLICY_REQUESTED]
    assert result.events[1].payload["source_observation_id"] == request.observation.sequence_id
    assert all(event.rollout_id == "timing-test" for event in result.events)
    assert all(event.config_hash == result.state.config_hash for event in result.events)
    assert all(event.skill_id == request.observation.current_skill_id for event in result.events)
    with pytest.raises(ValueError, match="reuse one Observation"):
        timing.transition_tick(_initial(cfg), cfg, request=request, telemetry=replace(request.observation))


def test_total_tick_transition_accept_replace_and_rejection_is_noop() -> None:
    cfg = config()
    first = _request(contracts.CommandStack.P1, 2, 0)
    accepted = timing.transition_tick(_initial(cfg), cfg, request=first)
    assert [event.event_type for event in accepted.events] == [
        ExecutionEventType.OBSERVATION_RECEIVED, ExecutionEventType.POLICY_REQUESTED,
        ExecutionEventType.POLICY_RESPONDED, ExecutionEventType.CHUNK_ACCEPTED,
        ExecutionEventType.ACTION_EXECUTED,
    ]
    second = _request(contracts.CommandStack.P1, 3, 1)
    replaced = timing.transition_tick(accepted.state, cfg, request=second)
    assert [event.event_type for event in replaced.events][2:5] == [ExecutionEventType.POLICY_RESPONDED, ExecutionEventType.CHUNK_REPLACED, ExecutionEventType.CHUNK_ACCEPTED]
    stale = _request(contracts.CommandStack.P2, 1, replaced.state.tick)
    uninterrupted = timing.transition_tick(replaced.state, cfg)
    rejected = timing.transition_tick(replaced.state, cfg, request=stale)
    assert ExecutionEventType.CHUNK_REJECTED_OUT_OF_ORDER in [event.event_type for event in rejected.events]
    assert rejected.state.active_chunk is replaced.state.active_chunk
    assert rejected.control_reference.q_ref.tobytes() == uninterrupted.control_reference.q_ref.tobytes()
    assert rejected.control_reference.dq_ref.tobytes() == uninterrupted.control_reference.dq_ref.tobytes()
    assert rejected.state.executor_state.latched_q_ref.tobytes() == uninterrupted.state.executor_state.latched_q_ref.tobytes()


def test_expired_arrival_and_half_open_expiry_return_real_safe_hold() -> None:
    cfg = config()
    request = _request(contracts.CommandStack.P5, 1, 0)
    accepted = timing.transition_tick(_initial(cfg), cfg, request=request, planner_due=True)
    expiry_tick = request.payload.expires_at_ns // 2_000_000
    q = np.array([0.2, -0.1, 0.3])
    expired_state = _copy_state(accepted.state, tick=expiry_tick, q=q, dq=np.ones(3))
    expired = timing.transition_tick(expired_state, cfg)
    assert expired.safe_hold and expired.safe_hold_command is not None
    assert expired.safe_hold_command.disposition is timing.SafeHoldDisposition.SAFE_HOLD
    assert np.array_equal(expired.safe_hold_command.q_ref, q)
    assert np.array_equal(expired.safe_hold_command.dq_ref, np.zeros(3))
    assert np.array_equal(expired.state.executor_state.latched_q_ref, q)
    assert not expired.state.executor_state.p5_planner_enabled

    late = _request(contracts.CommandStack.P1, 2, expired.state.tick)
    now_ns = expired.state.tick * 2_000_000
    late = replace(late, payload=replace(late.payload, valid_from_ns=now_ns, expires_at_ns=now_ns))
    rejected = timing.transition_tick(expired.state, cfg, request=late)
    assert ExecutionEventType.CHUNK_REJECTED_EXPIRED in [event.event_type for event in rejected.events]
    assert rejected.safe_hold


def test_p5_replacement_preserves_only_p5_to_p5_and_delivery_precedes_planner() -> None:
    cfg = config()
    first = _request(contracts.CommandStack.P5, 1, 0)
    one = timing.transition_tick(_initial(cfg), cfg, request=first, planner_due=True)
    prior_qdot = one.state.executor_state.p5_qdot_previous.copy()
    second = _request(contracts.CommandStack.P5, 2, 1)
    replacement_target = np.array([[0.31, 0.24]])
    second = replace(second, payload=replace(second.payload, actions=replacement_target))
    two = timing.transition_tick(one.state, cfg, request=second, planner_due=True)
    assert two.control_reference.source_chunk_id == second.payload.chunk_id
    expected_qdot = min(
        rep.mpc_candidates(cfg),
        key=lambda qdot: rep.mpc_cost(
            one.state.q,
            replacement_target[0],
            qdot,
            prior_qdot,
            cfg,
            cfg.mpc.smoothness_weight,
        ),
    )
    assert np.array_equal(two.state.executor_state.p5_qdot_previous, expected_qdot)
    p1 = _request(contracts.CommandStack.P1, 3, 2)
    three = timing.transition_tick(two.state, cfg, request=p1)
    assert not three.state.executor_state.p5_planner_enabled
    assert np.array_equal(three.state.executor_state.p5_qdot_previous, np.zeros(3))
    third_p5 = _request(contracts.CommandStack.P5, 4, 3)
    four = timing.transition_tick(three.state, cfg, request=third_p5, planner_due=True)
    assert four.state.executor_state.p5_planner_enabled


def test_scheduler_state_rejects_duplicate_queue_and_is_deep_immutable() -> None:
    response = timing.ScheduledResponse(2, 1, _request(contracts.CommandStack.P1, 1, 0).payload)
    state = _initial()
    with pytest.raises(ValueError, match="duplicate"):
        _copy_state(state, queue=(response, response))
    assert not state.q.flags.writeable
    with pytest.raises((ValueError, FrozenInstanceError)):
        state.q[0] = 3.0


def test_terminal_validation_rejects_queue_and_allows_only_declared_drop() -> None:
    state = _initial()
    response = timing.ScheduledResponse(2, 1, _request(contracts.CommandStack.P1, 1, 0).payload)
    with pytest.raises(ValueError, match="queue"):
        timing.validate_terminal_state(_copy_state(state, queue=(response,)))
    dropped = _copy_state(state, tick=1, unmatched_requests=(4,))
    timing.validate_terminal_state(dropped, allowed_dropped_requests=(4,))
    with pytest.raises(ValueError, match="unmatched"):
        timing.validate_terminal_state(dropped)


def test_scheduler_trace_writes_and_passes_shared_rollout_validator(tmp_path) -> None:
    cfg = config()
    request = _request(contracts.CommandStack.P1, 1, 0)
    result = timing.transition_tick(_initial(cfg, rollout_id="scheduler-artifact"), cfg, request=request)
    record = timing.scheduler_rollout_record(result.state, cfg)
    path = RolloutWriter(tmp_path, "scheduler-artifact").write(record)
    artifact = validate_rollout(path)
    assert artifact.events == result.state.events
    assert artifact.observations[0].current_phase == "track_target"


def test_transition_never_reads_wall_clock_or_sleeps(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("wall time is forbidden")

    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(time, "sleep", forbidden)
    cfg = config()
    timing.transition_tick(_initial(cfg), cfg, request=_request(contracts.CommandStack.P1, 1, 0))
