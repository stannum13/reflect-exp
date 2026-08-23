from __future__ import annotations

import importlib
from pathlib import Path

import pytest


contracts = importlib.import_module("experiments.03_recovery.src.v3_contracts")
outcome = importlib.import_module("experiments.03_recovery.src.v3_outcome")


def test_outcome_plan_is_exact_and_constructing_it_does_not_sample_or_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contracts, "make_realization", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("outcome sampled")))
    specs = outcome.outcome_specs()
    assert len(specs) == 360
    assert len({item.episode_id for item in specs}) == 360
    assert {item.seed for item in specs} == set(range(20261801, 20261811))
    assert all(item.stage is contracts.RunStage.OUTCOME for item in specs)
    p6 = [item for item in specs if item.controller_id == contracts.PRIMARY_CONTROLLER_ID]
    p4 = [item for item in specs if item.controller_id == contracts.SENSITIVITY_CONTROLLER_ID]
    assert len(p6) == 320
    assert len(p4) == 40
    assert {item.seed for item in p4} == set(range(20261801, 20261806))


def test_qualification_namespace_still_rejects_held_out_seed_without_sampling() -> None:
    with pytest.raises(ValueError, match="qualification"):
        outcome.V3EpisodeSpec(
            contracts.Architecture.R3,
            "anchor-nominal",
            20261801,
            contracts.PRIMARY_CONTROLLER_ID,
        )


def test_outcome_execution_refuses_before_output_or_episode_without_immutable_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "hierarchical-recovery-v3"
    called = False

    def forbidden_episode(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("episode executed before approval")

    monkeypatch.setattr(outcome, "run_episode", forbidden_episode)
    with pytest.raises(outcome.OutcomeAuthorizationError, match="approval"):
        outcome.run_outcomes(
            output,
            qualification_root=tmp_path / "hierarchical-recovery-v3-qualification",
            approval_binding=tmp_path / "approval-binding.json",
            approval_report=tmp_path / "approval-report.md",
        )
    assert called is False
    assert not output.exists()


def test_outcome_cli_and_source_are_in_complete_freeze_closure() -> None:
    evidence = importlib.import_module("experiments.03_recovery.src.v3_evidence")
    paths = {item["path"] for item in evidence.source_closure()}
    assert {
        "experiments/03_recovery/run_v3_outcome.py",
        "experiments/03_recovery/src/v3_outcome.py",
    } <= paths
