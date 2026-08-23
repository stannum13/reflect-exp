from __future__ import annotations

import importlib
import hashlib
import json
from pathlib import Path

import pytest


contracts = importlib.import_module("experiments.03_recovery.src.v3_contracts")
outcome = importlib.import_module("experiments.03_recovery.src.v3_outcome")
analysis = importlib.import_module("experiments.03_recovery.src.v3_outcome_analysis")


def _approval_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verdict: str) -> tuple[Path, Path, Path]:
    qualification = tmp_path / "hierarchical-recovery-v3-qualification"
    (qualification / "raw").mkdir(parents=True)
    (qualification / "derived").mkdir()
    closure = [{"path": "frozen.py", "bytes": 1, "sha256": "a" * 64}]
    freeze = {
        "source_commit": "b" * 40,
        "source_closure_sha256": contracts.sha256_bytes(contracts.canonical_bytes(closure)),
        "source_closure": closure,
        "self_authorizes_outcomes": False,
        "configuration": {"frozen": True},
        "configuration_sha256": "c" * 64,
        "environment": {"frozen": True},
        "environment_sha256": "d" * 64,
    }
    payloads = {
        "qualification-freeze.json": contracts.canonical_bytes(freeze),
        "raw/manifest.json": contracts.canonical_bytes({"schema_version": 1}),
        "derived/manifest.json": contracts.canonical_bytes({"schema_version": 1}),
    }
    for name, payload in payloads.items():
        (qualification / name).write_bytes(payload)
    hashes = {
        "qualified_source_commit": freeze["source_commit"],
        "source_closure_sha256": freeze["source_closure_sha256"],
        "qualification_freeze_sha256": hashlib.sha256(payloads["qualification-freeze.json"]).hexdigest(),
        "qualification_raw_manifest_sha256": hashlib.sha256(payloads["raw/manifest.json"]).hexdigest(),
        "qualification_derived_manifest_sha256": hashlib.sha256(payloads["derived/manifest.json"]).hexdigest(),
    }
    report = tmp_path / "approval-report.json"
    report.write_bytes(contracts.canonical_bytes({
        "schema_version": 1, "verdict": verdict, "critical_findings": [], "important_findings": [], **hashes,
    }))
    binding = tmp_path / "approval-binding.json"
    binding.write_bytes(contracts.canonical_bytes({
        "schema_version": 1,
        **hashes, "approval_report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
    }))
    monkeypatch.setattr(outcome, "source_closure", lambda: closure)
    monkeypatch.setattr(outcome, "_freeze_record", lambda specs: {
        key: freeze[key] for key in ("configuration", "configuration_sha256", "environment", "environment_sha256")
    })
    return qualification, binding, report


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


def test_rejected_report_cannot_be_accepted_by_caller_created_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    qualification, binding, report = _approval_fixture(tmp_path, monkeypatch, "REJECTED")
    with pytest.raises(outcome.OutcomeAuthorizationError, match="verdict"):
        outcome.verify_outcome_approval(qualification, binding, report)


def test_structured_reviewer_approval_requires_zero_blocking_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    qualification, binding, report = _approval_fixture(tmp_path, monkeypatch, "APPROVED_FOR_OUTCOME")
    verified = outcome.verify_outcome_approval(qualification, binding, report)
    assert verified["reviewer_verdict"] == "APPROVED_FOR_OUTCOME"
    assert "decision" not in verified


def test_accepted_approval_dry_run_is_side_effect_free_and_does_not_sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    qualification, binding, report = _approval_fixture(tmp_path, monkeypatch, "APPROVED_FOR_OUTCOME")
    monkeypatch.setattr(contracts, "make_realization", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sampled")))
    result = outcome.dry_run_outcomes(qualification_root=qualification, approval_binding=binding, approval_report=report)
    assert result["status"] == "AUTHORIZED_DRY_RUN"
    assert result["episode_count"] == 360
    assert not (tmp_path / "hierarchical-recovery-v3").exists()


@pytest.mark.parametrize("key", ("configuration", "environment"))
def test_authorization_rechecks_runtime_configuration_and_environment_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    qualification, binding, report = _approval_fixture(tmp_path, monkeypatch, "APPROVED_FOR_OUTCOME")
    freeze = json.loads((qualification / "qualification-freeze.json").read_text(encoding="ascii"))
    current = {name: freeze[name] for name in ("configuration", "configuration_sha256", "environment", "environment_sha256")}
    current[key] = {"drifted": True}
    monkeypatch.setattr(outcome, "_freeze_record", lambda specs: current)
    with pytest.raises(outcome.OutcomeAuthorizationError, match=key):
        outcome.verify_outcome_approval(qualification, binding, report)


def test_outcome_cli_and_source_are_in_complete_freeze_closure() -> None:
    evidence = importlib.import_module("experiments.03_recovery.src.v3_evidence")
    paths = {item["path"] for item in evidence.source_closure()}
    assert {
        "experiments/03_recovery/run_v3_outcome.py",
        "experiments/03_recovery/src/v3_outcome.py",
        "experiments/03_recovery/src/v3_outcome_analysis.py",
    } <= paths


def test_complete_outcome_analysis_bundle_is_frozen_without_sampling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contracts, "make_realization", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("sampled")))
    rows = []
    for spec in outcome.outcome_specs():
        rows.append({
            "episode_id": spec.episode_id, "architecture": spec.architecture.value,
            "scenario_id": spec.scenario_id, "seed": spec.seed, "controller_id": spec.controller_id,
            "disposition": "TERMINAL", "terminal": "SUCCESS",
            "unsafe": 0, "forbidden": 0, "collision": 0, "invalid_action": 0, "stale": 0, "loop": 0, "reset": 0,
            "control_interventions": 0, "motion_interventions": 0,
            "semantic_interventions": 0 if spec.architecture is contracts.Architecture.R3 else 1,
            "lowest_sufficient_correct": True,
            "physical_trace_sha256": hashlib.sha256(spec.episode_id.encode()).hexdigest(),
            "parameter_use_sha256": hashlib.sha256((spec.episode_id + "parameter").encode()).hexdigest(),
            "precheck_input": {"episode_id": spec.episode_id},
            "precheck_receipt": {"architecture_independent": True},
        })
    payloads = analysis.outcome_payloads(rows, construct_integrity={name: True for name in ("approval", "inventory", "freeze", "cause", "replay", "reconstruction")})
    assert {"decision.json", "paired-rows.csv", "bootstrap.json", "template-cluster-sensitivity.json", "graph-table.csv", "outcome-by-domain.svg", "outcome-by-domain.png", "examples.json"} <= set(payloads)
    assert json.loads(payloads["bootstrap.json"])["draw_count"] == 10_000
    assert payloads["outcome-by-domain.png"].startswith(b"\x89PNG\r\n\x1a\n")
    damaged = [dict(item) for item in rows]
    damaged[0] = {"episode_id": damaged[0]["episode_id"], "architecture": damaged[0]["architecture"], "scenario_id": damaged[0]["scenario_id"], "seed": damaged[0]["seed"], "controller_id": damaged[0]["controller_id"], "disposition": "INVALID"}
    invalid = analysis.evaluate_outcome_gates(damaged, construct_integrity={"reconstruction": True})
    assert invalid["scientific_result"] == "INVALID_EXPERIMENT"
    assert invalid["gates"][7]["passed"] is False


def test_interrupted_outcome_attempt_retains_create_only_invalid_disposition_without_sampling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    qualification, binding, report = _approval_fixture(tmp_path, monkeypatch, "APPROVED_FOR_OUTCOME")
    ready = importlib.import_module("experiments.03_recovery.src.v3_runtime").precheck(
        importlib.import_module("experiments.03_recovery.src.v3_runtime").V3EpisodeSpec(
            contracts.Architecture.R3, "anchor-nominal", 20261891, contracts.PRIMARY_CONTROLLER_ID,
        )
    )
    monkeypatch.setattr(outcome, "precheck", lambda spec: ready)
    monkeypatch.setattr(outcome, "run_episode", lambda spec: (_ for _ in ()).throw(RuntimeError("interrupted probe")))
    root = tmp_path / "hierarchical-recovery-v3"
    with pytest.raises(RuntimeError, match="interrupted probe"):
        outcome.run_outcomes(root, qualification_root=qualification, approval_binding=binding, approval_report=report)
    dispositions = list((root / "raw/dispositions").glob("*.json"))
    assert len(dispositions) == 1
    retained = json.loads(dispositions[0].read_text(encoding="ascii"))
    assert retained["disposition"] == "INVALID"
    assert retained["precheck_receipt"]["architecture_independent"] is True
    with pytest.raises(FileExistsError):
        outcome._write(dispositions[0], b"overwrite")
