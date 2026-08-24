from __future__ import annotations

import importlib
import inspect


def _module():
    return importlib.import_module("experiments.13_direct_hierarchy.src.experiment")


def test_frozen_matrix_is_exactly_480_primary_plus_60_sensitivity() -> None:
    experiment = _module()
    specs = experiment.matrix_specs()
    assert len(specs) == len({item.episode_id for item in specs}) == 540
    assert sum(item.matrix_role == "PRIMARY" for item in specs) == 480
    assert sum(item.matrix_role == "SENSITIVITY" for item in specs) == 60
    assert sorted({item.seed for item in specs if item.matrix_role == "PRIMARY"}) == list(range(20261901, 20261911))
    assert sorted({item.seed for item in specs if item.matrix_role == "SENSITIVITY"}) == list(range(20261901, 20261906))


def test_realization_is_paired_and_registered_dose_is_used() -> None:
    experiment = _module()
    specs = experiment.matrix_specs()
    cells = [item for item in specs if item.family == "control-dropout" and item.severity == "HIGH" and item.seed == 20261901]
    realizations = [experiment.make_realization(item) for item in cells]
    assert {item.parameter_sha256 for item in realizations} == {realizations[0].parameter_sha256}
    assert {item.dropout_ticks for item in realizations} == {50}
    assert len({item.architecture for item in cells if item.matrix_role == "PRIMARY"}) == 4


def test_policy_boundary_has_no_hidden_taxonomy_argument() -> None:
    policy = importlib.import_module("experiments.03_recovery.src.v3_policy")
    assert tuple(inspect.signature(policy.decide).parameters) == ("architecture", "observable", "budget")
    source = inspect.getsource(policy.decide)
    assert all(token not in source for token in ("scenario", "family", "severity", "cause"))


def test_exp13_schema_contains_no_causal_oracle_fields() -> None:
    experiment = _module()
    forbidden = ("counterfactual", "lowest_sufficient", "causal_assignment")
    assert all(not any(token in field for token in forbidden) for field in experiment.OUTCOME_ROW_FIELDS)
