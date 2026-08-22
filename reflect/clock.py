"""Clock abstractions for deterministic rollout execution."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Protocol


def checked_non_negative_int(value: object, field: str) -> int:
    """Return a non-negative integer, rejecting booleans and other numeric types."""
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


class Clock(Protocol):
    def monotonic_ns(self) -> int:
        raise NotImplementedError

    def wall_time_ns(self) -> int:
        raise NotImplementedError


class SystemClock:
    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    def wall_time_ns(self) -> int:
        return time.time_ns()


@dataclass
class VirtualClock:
    start_ns: int = 0
    wall_start_ns: int = 0

    def __post_init__(self) -> None:
        self._monotonic_ns = checked_non_negative_int(self.start_ns, "start_ns")
        self._wall_time_ns = checked_non_negative_int(self.wall_start_ns, "wall_start_ns")

    def monotonic_ns(self) -> int:
        return self._monotonic_ns

    def wall_time_ns(self) -> int:
        return self._wall_time_ns

    def advance_ns(self, duration_ns: int) -> int:
        duration = checked_non_negative_int(duration_ns, "duration_ns")
        self._monotonic_ns += duration
        self._wall_time_ns += duration
        return self._monotonic_ns
