"""Independent raw-ledger scorer for Experiment 11."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .kernel import canonical, simulate


class ScoreError(ValueError): pass


def score_episode(start: Mapping[str, Any], ticks: Sequence[Mapping[str, Any]], terminal: Mapping[str, Any], *, config: Mapping[str, Any] | None = None, quality: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if config is None or quality is None:
        from .experiment import CONFIG, quality_by_id
        config, quality = CONFIG, quality_by_id(str(start["cell"]["quality_id"]))
    expected_n = int(start["expected_tick_count"])
    if [row.get("tick") for row in ticks] != list(range(1, expected_n + 1)): raise ScoreError("tick domain mismatch")
    if terminal.get("terminal_tick") != expected_n + 1 or terminal.get("episode_id") != start["cell"]["episode_id"]: raise ScoreError("terminal mismatch")
    expected = simulate(start["cell"], config, quality)
    if canonical(start) != canonical(expected[0]): raise ScoreError("start replay mismatch")
    if canonical(list(ticks)) != canonical(expected[1]): raise ScoreError("tick replay mismatch")
    if canonical(terminal) != canonical(expected[2]): raise ScoreError("terminal replay mismatch")
    return {**expected[2], "tick_count":expected_n}
