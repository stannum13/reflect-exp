from __future__ import annotations

import importlib


timing = importlib.import_module("experiments.01_policy_control.src.timing")


def test_last_request_tick_exact_cutoff() -> None:
    assert timing.last_request_tick(3125, 350, 0, 50) == 2650


def test_delivery_orders_due_responses_and_rejects_stale() -> None:
    queue = [
        timing.ScheduledResponse(200, 2, "new"),
        timing.ScheduledResponse(200, 1, "old"),
    ]
    batch = timing.deliver_due(200, queue, last_accepted_observation_id=1)
    assert [item.response for item in batch.delivered] == ["old", "new"]
    assert [item.disposition for item in batch.delivered] == [timing.DeliveryDisposition.OUT_OF_ORDER, timing.DeliveryDisposition.ACCEPT]
    assert not batch.pending


def test_drop_is_the_only_unmatched_request() -> None:
    request = timing.PolicyRequest(3, 100, 50, "payload")
    assert timing.schedule_response(request, latency_ticks=10, drop=True) is None
    response = timing.schedule_response(request, latency_ticks=10, drop=False)
    assert response.delivery_tick == 110 and response.request_sequence == 3
