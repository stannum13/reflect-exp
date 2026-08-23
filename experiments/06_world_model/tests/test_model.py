from __future__ import annotations

import importlib

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
    return _rows(list(specs[:3])), _rows(list(specs[48:50])), _rows(list(specs[64:66]))


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
    assert tuple(item.selector_id for item in first) == ("W3", "W4")
    assert [item.model_sha256 for item in first] == [item.model_sha256 for item in second]
    assert all(set(item.fit_scene_ids) == {row.scene_id for row in training} for item in first)
    assert all(not set(item.fit_scene_ids) & {row.scene_id for row in tuning} for item in first)


def test_all_selectors_are_total_and_oracle_has_zero_regret(domains: tuple[tuple[object, ...], ...]) -> None:
    training, tuning, evaluation = domains
    fitted = model.fit_models(training, tuning)
    predictions = model.predict_all(fitted, evaluation)
    selections = model.rank_selectors(predictions, evaluation)
    anchors = {(row.scene_id, row.anchor_id) for row in evaluation}
    assert len(selections) == len(anchors) * 6
    assert {item.selector_id for item in selections} == {"DIRECT", "W0", "W1", "W2", "W3", "W4"}
    assert all(item.regret >= -1e-12 for item in selections)
    assert all(abs(item.regret) <= 1e-12 for item in selections if item.selector_id == "W2")
    metrics = model.aggregate_metrics(selections, predictions, evaluation)
    assert set(metrics["overall"]) == {"DIRECT", "W0", "W1", "W2", "W3", "W4"}
    assert metrics["overall"]["W2"]["mean_regret"] == 0.0
    assert all(-1.0 <= item.spearman <= 1.0 for item in selections if item.spearman is not None)
