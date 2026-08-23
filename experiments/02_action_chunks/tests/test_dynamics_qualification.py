from __future__ import annotations

import importlib
import json
from pathlib import Path

import numpy as np
import pytest


dynamics = importlib.import_module("experiments.02_action_chunks.src.dynamics_qualification")


def test_unsealed_matrix_runs_all_protocols_and_retains_raw_dynamics(tmp_path: Path) -> None:
    output = tmp_path / "dynamics"
    clean = tmp_path / "clean"
    dynamics.run_dynamics_qualification(output, seeds=(0,), implementation_git_sha="0" * 40)
    trials = [json.loads(line) for line in (output / "raw/trials.jsonl").read_text().splitlines()]
    assert {row["protocol_id"] for row in trials} == set("ABCDEFG")
    assert {row["latency_ticks"] for row in trials if row["fault_id"] == "NONE"} == {25, 75, 150}
    assert {row["fault_id"] for row in trials} >= {"DROP", "PAUSE", "ALTERNATIVE", "DISCONTINUITY"}
    assert {row["disposition"] for row in trials} == {"WORKING", "NONWORKING"}
    assert all(row["qualification_only"] and not row["sealed_pilot"] for row in trials)
    for row in trials:
        data = np.load(output / "raw/telemetry" / row["telemetry_file"], allow_pickle=False)
        assert data["q"].shape == (3125, 3)
        assert data["eef"].shape == (3125, 2)
        assert data["torque"].shape == (3125, 3)
        assert np.isfinite(data["q"]).all()
    dynamics.reconstruct_dynamics(output / "raw", clean)
    assert {p.name: p.read_bytes() for p in (output / "derived").iterdir()} == {p.name: p.read_bytes() for p in clean.iterdir()}

    event_rows = [json.loads(line) for line in (output / "raw/events.jsonl").read_text().splitlines()]
    target_row = event_rows[0]
    accepted = next(event for event in target_row["events"] if event["event_type"] == "CHUNK_ACCEPTED" and event.get("sidecar", {}).get("output_sha256"))
    accepted["sidecar"]["output_sha256"] = "0" * 64
    (output / "raw/events.jsonl").write_bytes(b"".join(dynamics._canonical(row) for row in event_rows))
    trial_rows = [json.loads(line) for line in (output / "raw/trials.jsonl").read_text().splitlines()]
    next(row for row in trial_rows if row["cell_id"] == target_row["cell_id"])["events_sha256"] = dynamics._sha(dynamics._canonical(target_row))
    (output / "raw/trials.jsonl").write_bytes(b"".join(dynamics._canonical(row) for row in trial_rows))
    manifest = json.loads((output / "raw/manifest.json").read_bytes())
    for name in ("events.jsonl", "trials.jsonl"):
        member = output / "raw" / name
        row = next(item for item in manifest["files"] if item["path"] == name)
        row.update(bytes=member.stat().st_size, sha256=dynamics._sha(member.read_bytes()))
    (output / "raw/manifest.json").write_bytes(dynamics._canonical(manifest))
    with pytest.raises(dynamics.DynamicsQualificationError, match="exact proposal/broker/issue replay"):
        dynamics.reconstruct_dynamics(output / "raw", tmp_path / "tampered-clean")


def test_two_fresh_dynamic_runs_are_byte_deterministic(tmp_path: Path) -> None:
    dynamics.run_dynamics_qualification(tmp_path / "one", seeds=(3,), implementation_git_sha="1" * 40)
    dynamics.run_dynamics_qualification(tmp_path / "two", seeds=(3,), implementation_git_sha="1" * 40)
    for relative in ("raw/trials.jsonl", "raw/events.jsonl", "raw/manifest.json", "derived/summary.json"):
        assert (tmp_path / "one" / relative).read_bytes() == (tmp_path / "two" / relative).read_bytes()


def test_preserved_pre_fix_evidence_is_machine_rejected(tmp_path: Path) -> None:
    raw = Path("experiments/02_action_chunks/results/unsealed-dynamics-v2/raw")
    with pytest.raises(dynamics.DynamicsQualificationError, match="INVALID_PRE_FIX"):
        dynamics.reconstruct_dynamics(raw, tmp_path / "forbidden")
