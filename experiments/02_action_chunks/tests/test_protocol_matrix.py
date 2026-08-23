from __future__ import annotations

import importlib
import json
from pathlib import Path


matrix = importlib.import_module("experiments.02_action_chunks.src.protocol_matrix")


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_four_transition_rules_are_exact() -> None:
    assert matrix.receding_prefix((1.0, 2.0, 3.0), (7.0, 8.0), 1) == (1.0, 7.0, 8.0)
    assert matrix.temporal_ensemble((0.0, 2.0), (2.0, 4.0)) == (1.0, 3.0)
    assert matrix.async_continuity(25, 75) == ("STRICT_OVERLAP", 0)
    assert matrix.async_continuity(75, 75) == ("EXPIRY_HANDOFF", 0)
    assert matrix.async_continuity(150, 75) == ("UNAVOIDABLE_HOLD", 75)
    assert matrix.rtc_projection((0.0, 0.0, 9.0), (3.0, 6.0, 9.0), 2) == (0.0, 3.0, 9.0)


def test_matrix_runs_varied_protocol_seed_latency_cases_and_reconstructs(tmp_path: Path) -> None:
    output = tmp_path / "matrix"
    clean = tmp_path / "clean"
    matrix.run_matrix(output, seeds=(0, 1), latencies=(25, 75, 150))
    trials = [json.loads(line) for line in (output / "raw/trials.jsonl").read_text().splitlines()]
    assert len(trials) == 32
    assert {row["protocol_id"] for row in trials} == {"B", "C", "E", "G"}
    assert {row["latency_ticks"] for row in trials if row["condition"] == "CORE"} == {25, 75, 150}
    assert {row["seed"] for row in trials} == {0, 1}
    assert {(row["protocol_id"], row["fault_id"]) for row in trials if row["condition"] == "FAULT"} == {
        ("B", "DROP"), ("C", "OLD_AFTER_NEWER"), ("E", "PAUSE"), ("G", "ALTERNATIVE")
    }
    assert {row["disposition"] for row in trials} == {"WORKING", "NONWORKING"}
    matrix.reconstruct_matrix(output / "raw", clean)
    assert _tree(output / "derived") == _tree(clean)


def test_two_matrix_runs_are_byte_identical(tmp_path: Path) -> None:
    matrix.run_matrix(tmp_path / "one", seeds=(0, 1), latencies=(25, 75, 150))
    matrix.run_matrix(tmp_path / "two", seeds=(0, 1), latencies=(25, 75, 150))
    assert _tree(tmp_path / "one") == _tree(tmp_path / "two")
