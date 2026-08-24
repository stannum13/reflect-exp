from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


exp = importlib.import_module("experiments.14_mission_ceiling.experiment")


def test_exact_balanced_matrix_and_fresh_seeds() -> None:
    cfg = exp.load_config()
    matrix = exp.matrix(cfg)
    assert len(matrix) == 9216
    assert len({tuple(row.values()) for row in matrix}) == 9216
    assert cfg["seeds"] == list(range(8401, 8413))
    assert set(cfg["variants"]) == {"baseline", *exp.AXES}
    for axis in exp.AXES:
        assert sum(row["variant"] == axis for row in matrix) == 1152


def test_building_step_enforces_real_preconditions_and_mutates_state() -> None:
    scenario = exp.make_scenario(7401, "parcel", 8, "baseline")
    state = exp.initial_state(scenario)
    invalid = exp.step(scenario, state, {"kind": "pickup", "object": "record"}, 0)
    assert invalid.accepted is False
    assert invalid.state == state
    moved = exp.step(scenario, state, {"kind": "move", "to": "room_1"}, 0)
    assert moved.accepted is True
    assert moved.state.agent_room == "room_1"
    assert state.agent_room == "dock"


def test_independent_scorer_uses_terminal_state_not_agent_claim() -> None:
    scenario = exp.make_scenario(7402, "retrieve", 4, "baseline")
    state = exp.initial_state(scenario)
    fake = {"agent_claimed_success": True, "steps": []}
    score = exp.score_episode(scenario, state, fake)
    assert score["mission_complete"] is False
    assert score["progress"] < 1.0
    assert "agent_claimed_success" not in score


@pytest.mark.parametrize("agent", ["open_loop", "live_memory", "lower_recovery", "full_hierarchy"])
def test_episode_is_deterministic_and_retains_complete_step_ledger(agent: str) -> None:
    row = {"seed": 7403, "mission": "tool", "horizon": 12, "variant": "disturbance", "agent": agent}
    first = exp.run_episode(row)
    second = exp.run_episode(row)
    assert first == second
    assert 1 <= len(first["ledger"]) <= 12
    required = {"step", "state_before", "action", "accepted", "observation_after", "memory", "retry", "semantic_replan", "event", "terminal"}
    assert required <= first["ledger"][0].keys()
    assert first["score"] == exp.score_episode(exp.scenario_from_row(row), exp.state_from_json(first["terminal_state"]), {"steps": first["ledger"]})


def test_manifest_rejects_extra_after_small_evidence_run(tmp_path: Path) -> None:
    rows = [
        {"seed": 7401, "mission": "parcel", "horizon": 8, "variant": variant, "agent": agent}
        for variant in ("baseline", "route")
        for agent in exp.load_config()["agents"]
    ]
    root = tmp_path / "evidence"
    exp.execute(rows, root, source_commit="f" * 40)
    exp.verify_manifest(root)
    (root / "extra.txt").write_text("x")
    with pytest.raises(exp.IntegrityError):
        exp.verify_manifest(root)


def test_reconstruction_is_raw_derived_and_byte_exact(tmp_path: Path) -> None:
    rows = [
        {"seed": seed, "mission": "retrieve", "horizon": 8, "variant": variant, "agent": agent}
        for seed in (7401, 7402)
        for variant in ("baseline", "disturbance")
        for agent in exp.load_config()["agents"]
    ]
    source = tmp_path / "source"
    target = tmp_path / "target"
    exp.execute(rows, source, source_commit="e" * 40)
    exp.reconstruct(source, target)
    assert (source / "derived" / "episodes.csv").read_bytes() == (target / "derived" / "episodes.csv").read_bytes()
    assert json.loads((source / "closure.json").read_text())["matrix_rows"] == 16


def test_paired_bootstrap_resamples_seed_clusters_not_cells() -> None:
    rows = []
    for seed, full_value in ((7401, True), (7402, False)):
        for mission in ("parcel", "retrieve"):
            for horizon in (4, 8):
                base = {"seed": seed, "mission": mission, "horizon": horizon, "variant": "baseline"}
                rows.append({**base, "agent": "open_loop", "mission_complete": False})
                rows.append({**base, "agent": "full_hierarchy", "mission_complete": full_value})
    contrast = exp.seed_cluster_contrast(rows, "open_loop", draws=1000, bootstrap_seed=7)
    assert contrast["effective_n"] == 2
    assert contrast["estimate"] == pytest.approx(0.5)
    one_seed = exp.seed_cluster_contrast([row for row in rows if row["seed"] == 7401], "open_loop", draws=1000, bootstrap_seed=7)
    assert one_seed["effective_n"] == 1
    assert one_seed["ci_low"] is None
    assert one_seed["ci_high"] is None
