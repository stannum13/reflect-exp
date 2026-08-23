from __future__ import annotations

import importlib
from dataclasses import replace

import pytest

world = importlib.import_module("experiments.06_world_model.world")
model = importlib.import_module("experiments.06_world_model.model")


def _rows(specs: list[object]) -> tuple[object, ...]:
    rows = []
    for spec in specs:
        scene, anchors, candidates, outcomes = world.run_scene(spec)
        rows.extend(model.dataset_rows(scene, anchors, candidates, outcomes))
    return tuple(rows)


@pytest.fixture(scope="module")
def domains() -> tuple[tuple[object, ...], tuple[object, ...], tuple[object, ...]]:
    specs = world.scene_rows()
    return tuple(_rows([next(x for x in specs if x.partition == part)]) for part in ("train", "tuning", "evaluation"))


def test_fit_rejects_partition_leakage(domains: tuple[tuple[object, ...], ...]) -> None:
    training, tuning, evaluation = domains
    with pytest.raises(ValueError, match="training partition"):
        model.fit_models(training + evaluation[:1], tuning)
    with pytest.raises(ValueError, match="tuning partition"):
        model.fit_models(training, tuning + evaluation[:1])


def test_ridge_models_are_byte_stable_and_bind_only_train_tune(domains: tuple[tuple[object, ...], ...]) -> None:
    training, tuning, _ = domains
    first = model.fit_models(training, tuning)
    second = model.fit_models(training, tuning)
    assert tuple(item.selector_id for item in first) == ("W3", "W4", "W3R", "W4R")
    assert [item.model_sha256 for item in first] == [item.model_sha256 for item in second]
    assert all(set(item.fit_scene_ids) == {row.scene_id for row in training} for item in first)
    assert all(not set(item.fit_scene_ids) & {row.scene_id for row in tuning} for item in first)


def test_all_selectors_are_total_and_oracle_has_zero_regret(domains: tuple[tuple[object, ...], ...]) -> None:
    training, tuning, evaluation = domains
    fitted = model.fit_models(training, tuning)
    predictions = model.predict_all(fitted, evaluation)
    selections = model.rank_selectors(predictions, evaluation)
    anchors = {(row.scene_id, row.anchor_id) for row in evaluation}
    assert len(selections) == len(anchors) * 9
    assert {item.selector_id for item in selections} == {"DIRECT", "W0", "W1", "W1V2", "W2", "W3", "W4", "W3R", "W4R"}
    assert all(item.regret >= -1e-12 for item in selections)
    assert all(abs(item.regret) <= 1e-12 for item in selections if item.selector_id == "W2")
    metrics = model.aggregate_metrics(selections, predictions, evaluation)
    assert set(metrics["overall"]) == {"DIRECT", "W0", "W1", "W1V2", "W2", "W3", "W4", "W3R", "W4R"}
    assert metrics["overall"]["W2"]["mean_regret"] == 0.0
    assert "collision_fraction" not in metrics["overall"]["W2"]
    assert "selected_collision_fraction" in metrics["overall"]["W2"]
    assert metrics["candidate_set"]["overall"]["candidate_collision_prevalence"] == sum(row.collision for row in evaluation) / len(evaluation)
    assert 0.0 <= metrics["candidate_set"]["overall"]["mixed_collision_anchor_fraction"] <= 1.0
    assert all(-1.0 <= item.spearman <= 1.0 for item in selections if item.spearman is not None)


def test_v4_predictions_are_truth_free_and_tuning_selects_one_residual(domains: tuple[tuple[object, ...], ...]) -> None:
    training, tuning, evaluation = domains
    fitted = model.fit_models(training, tuning)
    altered = tuple(replace(row, actual_cost=9999.0, terminal_state=(99.0, 99.0, 99.0), collision=not row.collision, success=not row.success, terminal_failure=not row.terminal_failure, action_energy=9999.0) for row in evaluation)
    original = model.predict_all(fitted, evaluation)
    mutated = model.predict_all(fitted, altered)
    assert [(x.selector_id, x.predicted_cost, x.predicted_collision_probability, x.predicted_success_probability) for x in original] == [(x.selector_id, x.predicted_cost, x.predicted_collision_probability, x.predicted_success_probability) for x in mutated]
    residuals = [item for item in fitted if item.selector_id in {"W3R", "W4R"}]
    assert sum(item.selected_for_evaluation for item in residuals) == 1
    assert all(len(item.member_alphas) == 3 and item.tuning_scene_ids for item in residuals)


def test_quality_gate_is_mechanical() -> None:
    overall = {name: {"mean_regret": value} for name, value in {"DIRECT": .5, "W1V2": .7, "W3R": .4}.items()}
    strata = {name: {"W1V2": {"mean_regret": .7}, "W3R": {"mean_regret": .6 if index < 4 else .8}} for index, name in enumerate(world.STRATA)}
    gate = model.quality_gate({"overall": overall, "strata": strata}, "W3R", {"W3R": {"p95_ns": 1000}}, latency_limit_ns=5000)
    assert gate["passed"] is True
    assert gate["strata_beaten"] == 4
