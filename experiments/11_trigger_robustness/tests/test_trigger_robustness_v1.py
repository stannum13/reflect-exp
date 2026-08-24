from __future__ import annotations

import importlib
import json

import pytest


exp = importlib.import_module("experiments.11_trigger_robustness.src.experiment")
scorer = importlib.import_module("experiments.11_trigger_robustness.src.scorer")


def test_frozen_matrix_is_exact_rich_paired_design():
    rows = exp.frozen_matrix()
    assert len(rows) == 46_080
    assert len({r["episode_id"] for r in rows}) == len(rows)
    assert {r["seed"] for r in rows} == set(range(20266201, 20266213))
    assert {r["quality_id"] for r in rows} == {f"Q{i:02d}_{name}" for i, name in enumerate(("CLEAN","RECALL75","RECALL50","RECALL25","DELAY1","DELAY3","FALSE3","DUP_OOO","GUARDED","HOSTILE"))}


def test_transport_is_deterministic_and_quality_changes_receipts():
    base = exp.fixture_matrix()[0]
    clean = dict(base, quality_id="Q00_CLEAN")
    hostile = dict(base, quality_id="Q09_HOSTILE")
    clean["episode_id"] = exp.episode_id(clean)
    hostile["episode_id"] = exp.episode_id(hostile)
    assert exp.run_episode(clean) == exp.run_episode(clean)
    assert exp.run_episode(clean)[1] != exp.run_episode(hostile)[1]


def test_transport_realization_is_paired_across_policy_storage_and_prompt():
    base = dict(exp.frozen_matrix()[0], quality_id="Q02_RECALL50")
    variants=[]
    for storage,policy,prompt in (("LIVE_BELIEF","EVENT_DRIVEN","COMPACT_TYPED"),("LIVE_EPISODIC","HYBRID","VERBOSE_TYPED")):
        cell=dict(base,storage_variant=storage,trigger_policy=policy,prompt_envelope=prompt); cell["episode_id"]=exp.episode_id(cell)
        _,ticks,_=exp.run_episode(cell)
        variants.append([(m["kind"],m["source_tick"],m["delivery_tick"],m["truth"]) for row in ticks for m in row["delivered_messages"]])
    assert variants[0] == variants[1]


def test_exact_tick_and_terminal_domain_rejects_truncation_and_duplication():
    start, ticks, terminal = exp.run_episode(exp.fixture_matrix()[0])
    score = scorer.score_episode(start, ticks, terminal)
    assert score["tick_count"] == start["expected_tick_count"]
    with pytest.raises(scorer.ScoreError, match="tick domain"):
        scorer.score_episode(start, ticks[:-1], terminal)
    with pytest.raises(scorer.ScoreError, match="terminal"):
        scorer.score_episode(start, ticks, dict(terminal, terminal_tick=terminal["terminal_tick"] - 1))


def test_scorer_rejects_authored_transport_action_and_summary_tamper():
    start, ticks, terminal = exp.run_episode(exp.fixture_matrix()[0])
    bad = json.loads(json.dumps(ticks))
    bad[1]["delivered_messages"].append({"kind":"FALSE_EVENT","message_id":"forged","subject":"valve_z","source_tick":1,"delivery_tick":2,"truth":False})
    with pytest.raises(scorer.ScoreError):
        scorer.score_episode(start, bad, terminal)
    bad = json.loads(json.dumps(ticks))
    bad[-1]["action"]["success"] = not bad[-1]["action"]["success"]
    with pytest.raises(scorer.ScoreError):
        scorer.score_episode(start, bad, terminal)
    with pytest.raises(scorer.ScoreError):
        scorer.score_episode(start, ticks, dict(terminal, progress=999))


def test_source_closure_is_transitive_and_covers_loaded_inputs(tmp_path):
    closure = exp.source_closure()
    assert "experiments/11_trigger_robustness/configs/trigger-robustness-v1.json" in closure
    assert "experiments/11_trigger_robustness/configs/seeds-v1.json" in closure
    assert "experiments/11_trigger_robustness/configs/retired-seed-namespaces.json" in closure
    assert "experiments/11_trigger_robustness/src/scorer.py" in closure
    assert "pyproject.toml" in closure and "uv.lock" in closure and ".python-version" in closure
    assert not any("10_storage_trigger" in p or "04_memory" in p for p in closure)
    exp.audit_source_closure(closure)
    with pytest.raises(exp.IntegrityError):
        exp.audit_source_closure(tuple(p for p in closure if not p.endswith("seeds-v1.json")))


def test_raw_roundtrip_and_manifest_tamper(tmp_path):
    raw = tmp_path / "raw"
    exp.publish_raw(exp.fixture_matrix()[:8], raw)
    exp.validate_raw(raw, expected_cells=exp.fixture_matrix()[:8])
    rebuilt = tmp_path / "rebuilt"
    exp.reconstruct_raw(raw, rebuilt)
    assert exp.tree_hash(raw) == exp.tree_hash(rebuilt)
    with (raw / "ticks.jsonl").open("ab") as handle:
        handle.write(b"{}\n")
    with pytest.raises(exp.IntegrityError):
        exp.validate_raw(raw, expected_cells=exp.fixture_matrix()[:8])


def test_seed_cluster_bootstrap_retains_effective_n():
    rows = [{"seed":seed,"effect":float(seed % 3)} for seed in range(20266101,20266113) for _ in range(4)]
    result = exp.cluster_bootstrap(rows, value="effect", draws=50, bootstrap_seed=7)
    assert result["effective_n"] == 12
    assert len(result["draw_cluster_indices"]) == 50
    assert all(len(draw) == 12 for draw in result["draw_cluster_indices"])


def test_derived_graphs_are_data_faithful_and_full_reconstruction_matches(tmp_path, monkeypatch):
    monkeypatch.setitem(exp.CONFIG, "bootstrap_draws", 50)
    root = tmp_path / "source"; root.mkdir()
    cells = exp.fixture_matrix()[:16]
    exp.publish_raw(cells, root / "raw")
    exp.derive(root / "raw", root / "derived")
    exp.validate_derived(root / "raw", root / "derived")
    assert (root / "derived/dose-response.svg").read_bytes().startswith(b"<svg")
    assert (root / "derived/dose-response.png").read_bytes().startswith(b"\x89PNG")
    rebuilt = tmp_path / "rebuilt"
    exp.reconstruct_all(root, rebuilt)
    assert exp.tree_hash(root) == exp.tree_hash(rebuilt)


def test_tracked_report_authenticates_authoritative_tables():
    report = (exp.ROOT / "TRIGGER_ROBUSTNESS_RESULT.md").read_text(encoding="ascii")
    derived = exp.ROOT / "results/v1/derived"
    for name in ("bootstrap.csv", "graph-table.csv", "heterogeneity.csv", "slopes-cliffs.csv"):
        assert exp.sha((derived / name).read_bytes()) in report
