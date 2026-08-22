from __future__ import annotations

import pytest

from reflect.clock import VirtualClock


def test_virtual_clock_advances_only_explicitly() -> None:
    clock = VirtualClock(start_ns=100)

    assert clock.monotonic_ns() == 100
    assert clock.wall_time_ns() == 0
    assert clock.advance_ns(25) == 125
    assert clock.monotonic_ns() == 125
    assert clock.wall_time_ns() == 25

    with pytest.raises(ValueError, match="non-negative"):
        clock.advance_ns(-1)


@pytest.mark.parametrize("value", [True, -1])
def test_virtual_clock_rejects_invalid_start_times(value: object) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        VirtualClock(start_ns=value)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="non-negative"):
        VirtualClock(wall_start_ns=value)  # type: ignore[arg-type]


def test_virtual_clock_advances_both_time_domains_from_configured_starts() -> None:
    clock = VirtualClock(start_ns=20, wall_start_ns=500)

    clock.advance_ns(8)

    assert clock.monotonic_ns() == 28
    assert clock.wall_time_ns() == 508
