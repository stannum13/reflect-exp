from __future__ import annotations

import importlib
import hashlib
import json
from pathlib import Path

import pytest


def _module():
    return importlib.import_module("experiments.10_storage_trigger.src.factorial")


def test_frozen_matrix_has_exact_paired_factorial_and_oracle_label() -> None:
    factorial = _module()
    rows = factorial.frozen_matrix()
    assert len(rows) == 12_000
    assert len({row["episode_id"] for row in rows}) == 12_000
    assert {row["planner_id"] for row in rows} == {"ORACLE_TYPED_SEMANTIC_V1"}
    assert {row["claim_scope"] for row in rows} == {"SYNTHETIC_ENGINEERING_ORACLE_NOT_VLA"}
    assert {row["seed"] for row in rows} == set(range(20264101, 20264121))
    assert all("pi0" not in json.dumps(row).lower() for row in rows)


def test_trigger_rules_enforce_threshold_event_cooldown_and_hysteresis() -> None:
    factorial = _module()
    periodic = factorial.TriggerState("PERIODIC_ONLY")
    assert [periodic.decide(tick=tick, material_event=False, failures=0, plan_valid=True)[0] for tick in range(1, 7)] == [False, False, True, False, False, True]

    threshold = factorial.TriggerState("FAILURE_THRESHOLD")
    assert threshold.decide(tick=1, material_event=False, failures=1, plan_valid=False)[0] is False
    assert threshold.decide(tick=2, material_event=False, failures=2, plan_valid=False)[0] is True
    assert threshold.decide(tick=3, material_event=False, failures=3, plan_valid=False)[0] is False
    threshold.note_success()
    assert threshold.decide(tick=4, material_event=False, failures=2, plan_valid=False)[0] is True

    event = factorial.TriggerState("EVENT_DRIVEN")
    assert event.decide(tick=1, material_event=True, failures=0, plan_valid=False) == (True, "EVENT")
    hybrid = factorial.TriggerState("HYBRID")
    assert hybrid.decide(tick=3, material_event=False, failures=0, plan_valid=True) == (True, "PERIODIC")
    assert hybrid.decide(tick=4, material_event=True, failures=0, plan_valid=False) == (False, "COOLDOWN_SUPPRESSED")
    assert hybrid.decide(tick=5, material_event=True, failures=0, plan_valid=False) == (True, "EVENT")


def test_storage_variants_have_distinct_write_read_and_reconstruction_semantics() -> None:
    factorial = _module()
    initial = factorial.initial_task(20264101)
    event = {"event_kind": "AVAILABILITY", "subject_id": initial["initial_target"], "value": "UNAVAILABLE", "tick": 2}
    stores = {name: factorial.StorageState(name, initial) for name in factorial.STORAGE_VARIANTS}
    for store in stores.values():
        store.ingest(event)
    assert stores["FIXED_SNAPSHOT"].view(2)["entities"][initial["initial_target"]]["availability"] == "AVAILABLE"
    assert stores["LIVE_BELIEF"].view(2)["entities"][initial["initial_target"]]["availability"] == "UNAVAILABLE"
    assert stores["EPISODIC_ONLY"].view(2)["entities"][initial["initial_target"]]["availability"] == "UNAVAILABLE"
    assert stores["NO_MEMORY"].stats()["bytes"] == 0
    assert stores["LIVE_EPISODIC"].stats()["writes"] > stores["LIVE_BELIEF"].stats()["writes"]


def test_reconstruction_is_byte_exact_and_raw_tampering_fails(tmp_path: Path) -> None:
    factorial = _module()
    output = tmp_path / "out"
    replay = tmp_path / "replay"
    factorial.run_fixture(output, implementation_git_sha="0" * 40)
    factorial.reconstruct(output / "raw", replay)
    assert {path.name for path in output.joinpath("derived").iterdir()} == {
        "RESULTS.md", "annotations.json", "cell-summary.csv", "contrasts.csv",
        "derived-manifest.json", "plot-style.json", "storage-trigger-summary.csv",
        "storage-trigger.svg", "storage-trigger.png", "trigger-profile.csv",
    }
    for path in output.joinpath("derived").iterdir():
        assert path.read_bytes() == (replay / path.name).read_bytes()
    episodes = output / "raw" / "episodes.csv"
    episodes.write_bytes(episodes.read_bytes() + b"tamper\n")
    with pytest.raises(factorial.FactorialError, match="manifest"):
        factorial.reconstruct(output / "raw", tmp_path / "bad")


def test_reconstruction_rescores_episode_metrics_after_manifest_rehash(tmp_path: Path) -> None:
    factorial = _module()
    output = tmp_path / "out"
    factorial.run_fixture(output, implementation_git_sha="0" * 40)
    raw = output / "raw"
    rows = factorial._read_csv(raw / "episodes.csv")
    assert {"stale_decisions", "motion_latency_proxy_ms", "control_latency_proxy_ms"} <= rows[0].keys()
    rows[0]["completion"] = "0" if rows[0]["completion"] == "1" else "1"
    content = factorial._csv_bytes(rows, factorial.EPISODE_FIELDS)
    (raw / "episodes.csv").write_bytes(content)
    manifest = json.loads((raw / "raw-manifest.json").read_text(encoding="ascii"))
    member = next(row for row in manifest["members"] if row["path"] == "episodes.csv")
    member["bytes"] = len(content)
    member["sha256"] = hashlib.sha256(content).hexdigest()
    (raw / "raw-manifest.json").write_bytes(factorial._canonical(manifest))
    with pytest.raises(factorial.FactorialError, match="score|step"):
        factorial.reconstruct(raw, tmp_path / "forged")
