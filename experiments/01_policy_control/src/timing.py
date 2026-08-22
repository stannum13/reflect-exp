"""Pure virtual request/response timing and delivery lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import heapq
from typing import Any


class DeliveryDisposition(str, Enum):
    ACCEPT = "ACCEPT"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class PolicyRequest:
    request_sequence: int
    request_tick: int
    period_ticks: int
    payload: Any


@dataclass(frozen=True, order=True)
class ScheduledResponse:
    delivery_tick: int
    request_sequence: int
    response: Any


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
