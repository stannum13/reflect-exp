"""V2R2 chronology and terminal-domain gate for the independent V2 scorer."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .factorial_v2_scorer import LedgerScoreError, PLANNER_ID, score_episode as _score_v2


def score_episode(
    start: Mapping[str, Any], ticks: Sequence[Mapping[str, Any]], config: Mapping[str, Any]
) -> dict[str, Any]:
    """Score only an exact, raw-order tick domain with a canonical terminal."""
    actual = [int(row["tick"]) for row in ticks]
    if actual != list(range(1, len(ticks) + 1)):
        raise LedgerScoreError("raw ledger chronology/tick domain mismatch")
    try:
        score = _score_v2(start, ticks, config)
    except LedgerScoreError as exc:
        if "continues after completion" in str(exc):
            raise LedgerScoreError("extra ticks beyond exact terminal tick domain") from exc
        raise
    terminal_limit = int(start["cell"]["horizon"]) + int(config["recovery_allowance_ticks"])
    if int(score["completion"]) == 0 and len(ticks) != terminal_limit:
        raise LedgerScoreError("early truncation before exact terminal tick domain")
    if len(ticks) > terminal_limit:
        raise LedgerScoreError("extra ticks beyond exact terminal tick domain")
    return score


__all__ = ["LedgerScoreError", "PLANNER_ID", "score_episode"]
