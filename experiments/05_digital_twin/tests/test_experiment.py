from __future__ import annotations

from dataclasses import fields
import importlib
from pathlib import Path

import pytest

experiment = importlib.import_module("experiments.05_digital_twin.src.experiment")


def test_four_layers_are_typed_separate_and_seeded() -> None:
    first = experiment.make_case(7, experiment.Mission.INSPECT_NEAREST_COOLANT)
    repeated = experiment.make_case(7, experiment.Mission.INSPECT_NEAREST_COOLANT)
    different = experiment.make_case(8, experiment.Mission.INSPECT_NEAREST_COOLANT)
    assert first == repeated and first.case_sha256 == repeated.case_sha256
    assert first.case_sha256 != different.case_sha256
    assert type(first.geometry) is experiment.GeometryLayer
    assert type(first.topology) is experiment.TopologyLayer
    assert type(first.semantics) is experiment.SemanticLayer
    assert type(first.belief) is experiment.LiveBelief
    assert not any(field.name == "layers" for field in fields(first))


def test_strong_twins_reduce_invalid_dynamic_plans() -> None:
    rows = [
        experiment.evaluate(experiment.make_case(seed, mission), variant)
        for seed in range(12)
        for mission in experiment.Mission
        for variant in experiment.Variant
    ]
    by_variant = {variant: [row for row in rows if row.variant is variant] for variant in experiment.Variant}
    assert sum(row.success for row in by_variant[experiment.Variant.T3]) > sum(row.success for row in by_variant[experiment.Variant.T2])
    assert sum(row.invalid_initial_plan for row in by_variant[experiment.Variant.T4]) < sum(row.invalid_initial_plan for row in by_variant[experiment.Variant.T3])
    assert all(row.forbidden_region_violations == 0 for row in by_variant[experiment.Variant.T3] + by_variant[experiment.Variant.T4])


def test_raw_reconstruction_is_exact_and_tamper_fails(tmp_path: Path) -> None:
    root = tmp_path / "run"
    experiment.run_matrix(root, seeds=range(3))
    clean = tmp_path / "clean"
    experiment.reconstruct(root / "raw", clean)
    assert {path.name: path.read_bytes() for path in (root / "derived").iterdir()} == {path.name: path.read_bytes() for path in clean.iterdir()}
    raw = root / "raw/outcomes.jsonl"
    payload = raw.read_bytes()
    raw.write_bytes(payload.replace(b'"success":true', b'"success":false', 1))
    with pytest.raises(experiment.EvidenceError):
        experiment.reconstruct(root / "raw", tmp_path / "bad")
