from __future__ import annotations

import ast
import hashlib
import importlib
import json
from pathlib import Path
import subprocess

import pytest


exp = importlib.import_module("experiments.11_trigger_robustness.src.experiment_v2")
replay = importlib.import_module("experiments.11_trigger_robustness.src.replay_v2")


def _head() -> str:
    return subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()


def _rewrite_manifest(root: Path, manifest_name: str) -> None:
    manifest = json.loads((root / manifest_name).read_text(encoding="ascii"))
    manifest["members"] = exp.inventory(root, exclude=(manifest_name,))
    (root / manifest_name).write_bytes(exp.canonical(manifest))


def _rewrite_root_manifest(root: Path) -> None:
    manifest = json.loads((root / "manifest.json").read_text(encoding="ascii"))
    manifest["members"] = exp.inventory(root, exclude=("manifest.json",))
    (root / "manifest.json").write_bytes(exp.canonical(manifest))


def test_v2_matrix_is_exact_and_uses_wholly_new_seed_namespace() -> None:
    rows = exp.frozen_matrix()
    assert len(rows) == len({row["episode_id"] for row in rows}) == 46_080
    assert {row["seed"] for row in rows} == set(range(20266301, 20266313))
    assert not {row["seed"] for row in rows} & set(range(20266101, 20266213))


def test_replay_is_separate_and_positive_controls_detect_generator_only_bug(monkeypatch) -> None:
    source = (exp.ROOT / "src/replay_v2.py").read_text(encoding="ascii")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any("kernel_v2" in name or "experiment_v2" in name for name in imported)
    assert "simulate(" not in source

    for cell in exp.fixture_matrix():
        start, ticks, terminal = exp.run_episode(cell)
        assert replay.score_episode(start, ticks, terminal, exp.CONFIG)["completion"] == terminal["completion"]

    start, ticks, terminal = exp.run_episode(exp.fixture_matrix()[0])
    forged = json.loads(json.dumps(ticks))
    forged[-1]["action"]["success"] = not forged[-1]["action"]["success"]
    with pytest.raises(replay.ReplayError, match="action|ledger"):
        replay.score_episode(start, forged, terminal, exp.CONFIG)

    kernel = importlib.import_module("experiments.11_trigger_robustness.src.kernel_v2")
    original = kernel.valid_action
    monkeypatch.setattr(kernel, "valid_action", lambda world, plan: not original(world, plan))
    mutant_start, mutant_ticks, mutant_terminal = exp.run_episode(exp.fixture_matrix()[0])
    with pytest.raises(replay.ReplayError, match="action|ledger|terminal"):
        replay.score_episode(mutant_start, mutant_ticks, mutant_terminal, exp.CONFIG)


def test_source_closure_is_transitive_complete_and_commit_authenticated() -> None:
    paths = {row["path"] for row in exp.source_closure()}
    assert {
        "experiments/__init__.py",
        "experiments/11_trigger_robustness/__init__.py",
        "experiments/11_trigger_robustness/src/__init__.py",
        "experiments/11_trigger_robustness/src/kernel_v2.py",
        "experiments/11_trigger_robustness/src/replay_v2.py",
        "experiments/11_trigger_robustness/src/experiment_v2.py",
        "experiments/11_trigger_robustness/configs/trigger-robustness-v2.json",
        "experiments/11_trigger_robustness/configs/seeds-v2.json",
        "experiments/11_trigger_robustness/configs/retired-attempts-v2.json",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
    } <= paths
    exp.audit_source_closure(exp.source_closure())


def test_recursive_inventories_include_manifests_and_reject_extras_and_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    exp.publish(root, exp.fixture_matrix(), implementation_git_sha=_head(), fixture=True)
    declared = {row["path"] for row in json.loads((root / "manifest.json").read_text(encoding="ascii"))["members"]}
    assert "raw/manifest.json" in declared and "derived/manifest.json" in declared

    (root / "raw/nested").mkdir()
    (root / "raw/nested/forgery.json").write_text("{}\n", encoding="ascii")
    with pytest.raises(exp.IntegrityError, match="inventory|unlisted"):
        exp.validate(root, allow_fixture=True)

    root2 = tmp_path / "fixture-link"
    exp.publish(root2, exp.fixture_matrix(), implementation_git_sha=_head(), fixture=True)
    (root2 / "raw/link").symlink_to(root2 / "raw/config.json")
    with pytest.raises(exp.IntegrityError, match="symlink"):
        exp.validate(root2, allow_fixture=True)

    root3 = tmp_path / "fixture-sibling"
    exp.publish(root3, exp.fixture_matrix(), implementation_git_sha=_head(), fixture=True)
    (root3 / "undeclared.txt").write_text("forged\n", encoding="ascii")
    with pytest.raises(exp.IntegrityError, match="inventory|unlisted"):
        exp.validate(root3, allow_fixture=True)


def test_reconstruction_rejects_resealed_config_seed_freeze_and_manifest(tmp_path: Path) -> None:
    for mutation in ("config", "seed", "freeze", "manifest"):
        root = tmp_path / mutation
        exp.publish(root, exp.fixture_matrix(), implementation_git_sha=_head(), fixture=True)
        raw = root / "raw"
        if mutation == "config":
            value = json.loads((raw / "config.json").read_text(encoding="ascii"))
            value["period_ticks"] = 99
            (raw / "config.json").write_bytes(exp.canonical(value))
        elif mutation == "seed":
            value = json.loads((raw / "seeds.json").read_text(encoding="ascii"))
            value["seeds"][0] = 99999999
            (raw / "seeds.json").write_bytes(exp.canonical(value))
        elif mutation == "freeze":
            value = json.loads((raw / "freeze.json").read_text(encoding="ascii"))
            value["matrix_sha256"] = "f" * 64
            (raw / "freeze.json").write_bytes(exp.canonical(value))
        else:
            value = json.loads((raw / "manifest.json").read_text(encoding="ascii"))
            value["schema_version"] = 99
            (raw / "manifest.json").write_bytes(exp.canonical(value))
            _rewrite_root_manifest(root)
            with pytest.raises(exp.IntegrityError, match="manifest|schema"):
                exp.validate(root, allow_fixture=True)
            continue
        _rewrite_manifest(raw, "manifest.json")
        _rewrite_root_manifest(root)
        with pytest.raises(exp.IntegrityError, match="config|seed|freeze|matrix|canonical"):
            exp.validate(root, allow_fixture=True)


def test_paired_contrasts_are_preregistered_clustered_and_gated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(exp.CONFIG, "bootstrap_draws", 50)
    root = tmp_path / "fixture"
    exp.publish(root, exp.fixture_matrix(), implementation_git_sha=_head(), fixture=True)
    contrasts = exp.read_csv(root / "derived/paired-contrasts.csv")
    assert contrasts
    assert {row["axis"] for row in contrasts} == {"storage", "policy", "prompt"}
    assert all(row["effect_id"] in exp.preregistered_effect_ids() for row in contrasts)
    assert all(int(row["effective_seed_n"]) == 2 for row in contrasts)
    assert all(int(row["bootstrap_draws"]) == 50 for row in contrasts)
    assert all(row["gate"] in {"PASS", "FAIL"} for row in contrasts)
    assert (root / "derived/slopes-cliffs.csv").stat().st_size > 0
    assert (root / "derived/heterogeneity.csv").stat().st_size > 0


def test_store_series_are_not_pooled_and_graph_metadata_is_explicit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(exp.CONFIG, "bootstrap_draws", 50)
    root = tmp_path / "fixture"
    exp.publish(root, exp.fixture_matrix(), implementation_git_sha=_head(), fixture=True)
    graph = exp.read_csv(root / "derived/graph-table.csv")
    assert {row["storage_variant"] for row in graph} == set(exp.CONFIG["storage_variants"])
    assert len({(row["storage_variant"], row["trigger_policy"]) for row in graph}) > len(exp.CONFIG["trigger_policies"])
    metadata = json.loads((root / "derived/plot-metadata.json").read_text(encoding="ascii"))
    assert metadata["storage_pooling"] == "NONE"
    assert metadata["transformations"] == ["ARITHMETIC_MEAN_OVER_DECLARED_NUISANCE_AXES"]
    assert metadata["graph_table_sha256"] == hashlib.sha256((root / "derived/graph-table.csv").read_bytes()).hexdigest()
    svg = (root / "derived/dose-response.svg").read_text(encoding="ascii")
    assert all(storage in svg for storage in exp.CONFIG["storage_variants"])
    assert (root / "derived/dose-response.png").read_bytes().startswith(b"\x89PNG")


def test_derived_validation_recomputes_instead_of_accepting_coherent_forgery(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(exp.CONFIG, "bootstrap_draws", 50)
    root = tmp_path / "fixture"
    exp.publish(root, exp.fixture_matrix(), implementation_git_sha=_head(), fixture=True)
    graph = root / "derived/graph-table.csv"
    graph.write_bytes(graph.read_bytes().replace(b"1.0", b"0.0", 1))
    _rewrite_manifest(root / "derived", "manifest.json")
    _rewrite_root_manifest(root)
    with pytest.raises(exp.IntegrityError, match="recomputed|derived"):
        exp.validate(root, allow_fixture=True)


def test_retirement_registry_is_closed_and_authenticates_actual_v1_attempt() -> None:
    registry = exp.load_retirement_registry()
    assert registry["schema_version"] == 2
    assert len(registry["attempts"]) >= 2
    published = next(row for row in registry["attempts"] if row["attempt_id"] == "EXP11_V1_PUBLISHED")
    assert published["disposition"] == "INVALID_REJECTED"
    assert published["claim_authority"] == "NONE"
    assert published["raw_manifest_sha256"] == hashlib.sha256((exp.ROOT / "results/v1/raw/manifest.json").read_bytes()).hexdigest()
    assert published["derived_manifest_sha256"] == hashlib.sha256((exp.ROOT / "results/v1/derived/manifest.json").read_bytes()).hexdigest()


def test_fixture_reconstruction_is_exact_and_requires_root_receipt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(exp.CONFIG, "bootstrap_draws", 50)
    root = tmp_path / "fixture"
    rebuilt = tmp_path / "rebuilt"
    exp.publish(root, exp.fixture_matrix(), implementation_git_sha=_head(), fixture=True)
    receipt = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    exp.reconstruct(root, rebuilt, expected_root_manifest_sha256=receipt, allow_fixture=True)
    assert exp.inventory(root) == exp.inventory(rebuilt)
    with pytest.raises(exp.IntegrityError, match="root manifest receipt"):
        exp.reconstruct(root, tmp_path / "wrong", expected_root_manifest_sha256="0" * 64, allow_fixture=True)
