from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
import subprocess


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


def test_independent_direct_score_comes_from_raw_physics() -> None:
    experiment = _module()
    spec = next(item for item in experiment.matrix_specs() if item.architecture.value == "R3")
    raw = experiment.run_cell(spec)
    row = experiment.score_cell(raw)
    assert tuple(row) == experiment.OUTCOME_ROW_FIELDS
    assert row["terminal"] in {"SUCCESS", "FAILURE"}
    assert row["mission_success"] == (row["terminal"] == "SUCCESS")
    assert 0.0 <= row["progress"] <= 1.0
    assert row["peak_torque_nm"] >= row["rms_torque_nm"] >= 0.0
    assert not any(token in json.dumps(row) for token in ("counterfactual", "lowest_sufficient", "causal_assignment"))


def test_freeze_then_one_cell_is_create_only_and_resumable(tmp_path: Path) -> None:
    experiment = _module()
    root = tmp_path / experiment.EXPERIMENT_ID
    source_commit = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    freeze = experiment.freeze(root, source_commit=source_commit)
    assert freeze["configuration"]["total_cells"] == 540
    result = experiment.execute(root, limit=1)
    assert result == {"completed": 1, "remaining": 539, "total": 540}
    assert experiment.execute(root, limit=1) == {"completed": 2, "remaining": 538, "total": 540}
    dispositions = sorted((root / "raw/dispositions").glob("*.json"))
    assert len(dispositions) == 2
    assert all(json.loads(path.read_text())["disposition"] == "COMPLETE" for path in dispositions)
