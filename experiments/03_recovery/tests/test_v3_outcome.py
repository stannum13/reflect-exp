from __future__ import annotations

import importlib
import hashlib
import json
from pathlib import Path
from dataclasses import replace

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
        domain = "CONTROL" if spec.scenario_id.startswith("control-") else "MOTION" if spec.scenario_id.startswith("motion-") else "SEMANTIC" if spec.scenario_id.startswith("semantic-") else "ANCHOR"
        parameter_sha = hashlib.sha256((spec.episode_id + "parameter").encode()).hexdigest()
        precheck_input = {
            "episode_id": spec.episode_id, "scenario_id": spec.scenario_id, "stage": "OUTCOME", "seed": spec.seed,
            "q0": [0.0, 0.0, 0.0], "target_a_xy": [0.5, 0.0], "target_b_xy": [0.4, 0.1],
            "injection_tick": 700, "impulse_nm": 0.2, "impulse_ticks": 8, "dropout_ticks": 30,
            "target_shift_xy": [0.04, 0.0], "obstacle_xy": [0.3, 0.0], "obstacle_radius_m": 0.04,
            "damping_multiplier": 1.0, "semantic_delay_ticks": 4, "parameter_sha256": parameter_sha,
        }
        rows.append({
            "episode_id": spec.episode_id, "architecture": spec.architecture.value,
            "scenario_id": spec.scenario_id, "seed": spec.seed, "controller_id": spec.controller_id,
            "template_id": spec.scenario_id, "domain": domain,
            "matrix_role": "PRIMARY" if spec.controller_id == contracts.PRIMARY_CONTROLLER_ID else "SENSITIVITY",
            "approval_report_sha256": "a" * 64,
            "disposition": "TERMINAL", "terminal": "SUCCESS",
            "unsafe": 0, "forbidden": 0, "collision": 0, "invalid_action": 0, "stale": 0, "loop": 0, "reset": 0,
            "control_interventions": 0, "motion_interventions": 1 if spec.architecture is contracts.Architecture.R2 else 0,
            "semantic_interventions": 0 if spec.architecture is contracts.Architecture.R3 else 1,
            "counterfactual_event_audit": {"event_count": 1, "matched_event_count": 1, "fraction": 1.0, "events": []},
            "physical_trace_sha256": hashlib.sha256(spec.episode_id.encode()).hexdigest(),
            "parameter_use_sha256": parameter_sha,
            "precheck_input": precheck_input,
            "precheck_receipt": {"architecture_independent": True, "realization_sha256": parameter_sha},
        })
    payloads = analysis.outcome_payloads(rows, construct_integrity={name: True for name in ("approval", "inventory", "freeze", "cause", "replay", "reconstruction")})
    assert {"decision.json", "paired-rows.csv", "bootstrap.json", "template-cluster-sensitivity.json", "graph-table.csv", "outcome-by-domain.svg", "outcome-by-domain.png", "examples.json"} <= set(payloads)
    assert json.loads(payloads["bootstrap.json"])["draw_count"] == 10_000
    assert payloads["outcome-by-domain.png"].startswith(b"\x89PNG\r\n\x1a\n")
    integrity = {name: True for name in ("approval", "inventory", "freeze", "cause", "replay", "reconstruction")}
    baseline = analysis.evaluate_outcome_gates(rows, construct_integrity=integrity)
    assert baseline["gates"][7]["passed"] is True
    assert baseline["matrix_identity"]["paired_count"] == 80
    assert baseline["gates"][2]["passed"] is True
    assert baseline["gates"][3]["passed"] is True
    assert baseline["fixed_best_comparator"] == "R0"
    aggregate_ni = [dict(item) for item in rows]
    semantic_cells = [item for item in aggregate_ni if item["controller_id"] == contracts.PRIMARY_CONTROLLER_ID and item["scenario_id"] == "semantic-object-unavailable" and item["architecture"] in {"R1", "R3"}]
    for item in semantic_cells:
        if item["seed"] == 20261801:
            item["terminal"] = "FAILURE" if item["architecture"] == "R3" else "SUCCESS"
        elif item["seed"] == 20261802:
            item["terminal"] = "SUCCESS" if item["architecture"] == "R3" else "FAILURE"
    assert analysis.evaluate_outcome_gates(aggregate_ni, construct_integrity=integrity)["gates"][2]["passed"] is True
    fixed_rule = [dict(item) for item in rows]
    for item in fixed_rule:
        if item["controller_id"] == contracts.PRIMARY_CONTROLLER_ID and item["domain"] == "CONTROL" and item["architecture"] in {"R0", "R1", "R2", "R3"}:
            first_half = item["seed"] <= 20261805
            if item["architecture"] in {"R0", "R2", "R3"}:
                item["terminal"] = "SUCCESS" if first_half else "FAILURE"
            else:
                item["terminal"] = "FAILURE" if first_half else "SUCCESS"
    fixed_result = analysis.evaluate_outcome_gates(fixed_rule, construct_integrity=integrity)
    assert fixed_result["fixed_best_comparator"] == "R0"
    assert fixed_result["gates"][5]["passed"] is True
    for field, value in (("architecture", "R0" if rows[0]["architecture"] != "R0" else "R3"), ("seed", 20261899), ("controller_id", "forged"), ("scenario_id", "forged-template"), ("matrix_role", "PRIMARY" if rows[0]["matrix_role"] != "PRIMARY" else "SENSITIVITY"), ("approval_report_sha256", "b" * 64)):
        substituted = [dict(item) for item in rows]
        substituted[0][field] = value
        result = analysis.evaluate_outcome_gates(substituted, construct_integrity=integrity)
        assert result["gates"][7]["passed"] is False, field
        assert result["scientific_result"] == "INVALID_EXPERIMENT"
    for malformed in (rows[:-1], [*rows, dict(rows[0])], [dict(rows[0]), *rows[1:-1], dict(rows[0])]):
        result = analysis.evaluate_outcome_gates(malformed, construct_integrity=integrity)
        assert result["gates"][7]["passed"] is False
        assert result["scientific_result"] == "INVALID_EXPERIMENT"
    damaged = [dict(item) for item in rows]
    damaged[0] = {"episode_id": damaged[0]["episode_id"], "architecture": damaged[0]["architecture"], "scenario_id": damaged[0]["scenario_id"], "seed": damaged[0]["seed"], "controller_id": damaged[0]["controller_id"], "disposition": "INVALID"}
    invalid = analysis.evaluate_outcome_gates(damaged, construct_integrity=integrity)
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
    assert (root / "approval/approval-report.json").read_bytes() == report.read_bytes()
    assert (root / "approval/approval-binding.json").read_bytes() == binding.read_bytes()
    sealed = outcome.seal_invalid_outcomes(root)
    assert sealed["status"] == "SEALED_INVALID_EXPERIMENT"
    reconstruction = outcome.reconstruct_outcomes(
        root, tmp_path / "invalid-clean", qualification_root=qualification,
        approval_binding=binding, approval_report=report,
    )
    assert reconstruction["matched"] is True
    assert reconstruction["scientific_result"] == "INVALID_EXPERIMENT"
    assert json.loads((root / "derived/decision.json").read_text(encoding="ascii"))["gates"][7]["passed"] is False


def test_realization_bootstrap_resamples_ten_seed_clusters_with_perfect_within_seed_correlation() -> None:
    pairs = []
    templates = analysis.DOMAINS["MOTION"] + analysis.DOMAINS["SEMANTIC"]
    for seed_index, seed in enumerate(range(20261801, 20261811)):
        effect = 1 if seed_index < 5 else -1
        for template in templates:
            pairs.append({"scenario_id": template, "seed": seed, "r3_success": int(effect == 1), "r0_success": int(effect == -1)})
    result = analysis.realization_bootstrap(pairs)
    assert result["effective_n"] == 10
    assert result["effective_n_unit"] == "seed_realization_clusters"
    assert all(len(cluster["rows"]) == 4 for cluster in result["cluster_inputs"])
    first_indices = result["cluster_indices"][0]
    cluster_effects = [1.0] * 5 + [-1.0] * 5
    assert result["draws"][0] == pytest.approx(sum(cluster_effects[index] for index in first_indices) / 10)
    sensitivity = result["template_cluster_sensitivity"]
    assert sensitivity["cluster_unit"] == "template_with_all_10_realizations"
    assert len(sensitivity["draws"]) == 10_000


def test_counterfactual_oracle_binds_each_failure_event_to_ordered_minimal_effect() -> None:
    runtime = importlib.import_module("experiments.03_recovery.src.v3_runtime")
    raw = runtime.run_episode(runtime.V3EpisodeSpec(contracts.Architecture.R3, "control-impulse", 20261892, contracts.PRIMARY_CONTROLLER_ID))
    first_observation = raw.observations[0]
    first_decision = raw.decisions[0]
    second_observation = replace(first_observation, tick=first_observation.tick + contracts.REOBSERVE_TICKS, reobserve_index=first_observation.reobserve_index + 1, geometry_feasible=False)
    second_decision = replace(first_decision, level=contracts.DecisionLevel.MOTION, observed_tick=second_observation.tick, observable_sha256=second_observation.sha256)
    doubled = replace(raw, observations=(first_observation, second_observation), decisions=(first_decision, second_decision))
    baseline = outcome.counterfactual_event_audit(doubled)
    assert baseline["event_count"] == 2
    assert baseline["matched_event_count"] == 2
    decisions = list(doubled.decisions)
    reversed_levels = tuple(replace(item, level=decisions[-1 - index].level) for index, item in enumerate(decisions))
    assert outcome.counterfactual_event_audit(replace(doubled, decisions=reversed_levels))["matched_event_count"] < 2
    assert outcome.counterfactual_event_audit(replace(doubled, decisions=(decisions[0],)))["matched_event_count"] < 2
    assert outcome.counterfactual_event_audit(replace(doubled, decisions=()))["matched_event_count"] == 0
    over = tuple(replace(item, level=contracts.DecisionLevel.SEMANTIC) for item in decisions)
    assert outcome.counterfactual_event_audit(replace(doubled, decisions=over))["matched_event_count"] < 2
