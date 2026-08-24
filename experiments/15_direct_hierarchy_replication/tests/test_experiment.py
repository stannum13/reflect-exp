from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


def _module():
    return importlib.import_module("experiments.15_direct_hierarchy_replication.src.experiment")


@pytest.fixture(autouse=True)
def _test_git_approval_loader(monkeypatch):
    experiment = _module()
    real_loader = experiment._load_git_approval

    def load(approval_ref, expected_path):
        if not str(approval_ref).startswith("test-file:"):
            return real_loader(approval_ref, expected_path)
        path = Path(str(approval_ref).removeprefix("test-file:"))
        payload = path.read_bytes()
        document = json.loads(payload.decode("ascii"))
        parent = document.get("approval_parent_commit", document["source_commit"])
        commit = "a" * 40 if expected_path == experiment.SOURCE_APPROVAL_PATH else "b" * 40
        return document, payload, commit, parent

    monkeypatch.setattr(experiment, "_load_git_approval", load)


def _approval(tmp_path: Path, experiment, source_commit: str) -> str:
    path = tmp_path / "source-audit-approval.json"
    path.write_bytes(experiment.canonical_bytes({
        "schema_version": 1,
        "experiment_id": experiment.EXPERIMENT_ID,
        "source_commit": source_commit,
        "verdict": "APPROVE",
        "review_scope": "SOURCE_PREREGISTRATION_BEFORE_FREEZE",
        "reviewer": "independent-test-reviewer",
    }))
    return f"test-file:{path}"


def test_frozen_matrix_is_exactly_480_primary_plus_60_sensitivity() -> None:
    experiment = _module()
    specs = experiment.matrix_specs()
    assert len(specs) == len({item.episode_id for item in specs}) == 540
    assert sum(item.matrix_role == "PRIMARY" for item in specs) == 480
    assert sum(item.matrix_role == "SENSITIVITY" for item in specs) == 60
    assert sorted({item.seed for item in specs if item.matrix_role == "PRIMARY"}) == list(range(20262301, 20262311))
    assert sorted({item.seed for item in specs if item.matrix_role == "SENSITIVITY"}) == list(range(20262301, 20262306))


def test_matrix_and_registered_doses_match_final_exp13_except_namespace() -> None:
    experiment = _module()
    reference = importlib.import_module("experiments.13_direct_hierarchy.src.experiment")
    exp15 = experiment.matrix_specs()
    exp13 = reference.matrix_specs()
    def normalized(item):
        return (
            item.architecture.value, item.family, item.severity,
            item.seed % 100, item.controller_id, item.matrix_role,
        )
    assert [normalized(item) for item in exp15] == [normalized(item) for item in exp13]
    for left, right in zip(exp15, exp13, strict=True):
        left_realization = experiment.make_realization(left)
        right_realization = reference.make_realization(right)
        assert (
            left_realization.impulse_nm,
            left_realization.impulse_ticks,
            left_realization.dropout_ticks,
            round((left_realization.target_shift_xy[0] ** 2 + left_realization.target_shift_xy[1] ** 2) ** .5, 6),
            left_realization.obstacle_radius_m,
            left_realization.semantic_delay_ticks,
        ) == (
            right_realization.impulse_nm,
            right_realization.impulse_ticks,
            right_realization.dropout_ticks,
            round((right_realization.target_shift_xy[0] ** 2 + right_realization.target_shift_xy[1] ** 2) ** .5, 6),
            right_realization.obstacle_radius_m,
            right_realization.semantic_delay_ticks,
        )


def test_realization_is_paired_and_registered_dose_is_used() -> None:
    experiment = _module()
    specs = experiment.matrix_specs()
    cells = [item for item in specs if item.family == "control-dropout" and item.severity == "HIGH" and item.seed == 20262301]
    realizations = [experiment.make_realization(item) for item in cells]
    assert {item.parameter_sha256 for item in realizations} == {realizations[0].parameter_sha256}
    assert {item.dropout_ticks for item in realizations} == {50}
    assert len({item.architecture for item in cells if item.matrix_role == "PRIMARY"}) == 4


def test_policy_boundary_has_no_hidden_taxonomy_argument() -> None:
    policy = importlib.import_module("experiments.03_recovery.src.v3_policy")
    assert tuple(inspect.signature(policy.decide).parameters) == ("architecture", "observable", "budget")
    source = inspect.getsource(policy.decide)
    assert all(token not in source for token in ("scenario", "family", "severity", "cause"))


def test_exp15_schema_contains_no_causal_oracle_fields() -> None:
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
    freeze = experiment.freeze(root, source_commit=source_commit, source_approval_ref=_approval(tmp_path, experiment, source_commit))
    assert freeze["configuration"]["total_cells"] == 540
    with pytest.raises(RuntimeError, match="full-matrix preflight"):
        experiment.execute(root, limit=1)
    preflight = experiment.preflight(root)
    assert preflight["total"] == preflight["READY"] + preflight["NOT_RUN"] + preflight["INVALID_PREFLIGHT"] == 540
    result = experiment.execute(root, limit=1)
    assert result == {"completed": 1, "remaining": 539, "total": 540}
    assert experiment.execute(root, limit=1) == {"completed": 2, "remaining": 538, "total": 540}
    dispositions = sorted((root / "raw/dispositions").glob("*.json"))
    assert len(dispositions) == 2
    assert all(json.loads(path.read_text())["disposition"] == "COMPLETE" for path in dispositions)
    first_path = dispositions[0]
    first_spec = next(item for item in experiment.matrix_specs() if item.episode_id == first_path.stem)
    freeze_document = json.loads((root / "freeze.json").read_text())
    experiment._validate_disposition(root, first_path, first_spec, freeze_document)
    manifest = json.loads((root / "raw/episodes" / first_path.stem / "manifest.json").read_text())
    raw_path = root / "raw/episodes" / first_path.stem / manifest["files"][0]["path"]
    raw_path.write_bytes(raw_path.read_bytes() + b"attack")
    with pytest.raises(RuntimeError, match="manifest|inventory"):
        experiment._validate_disposition(root, first_path, first_spec, freeze_document)


def test_not_run_is_sealed_without_episode_and_resume_continues(tmp_path: Path, monkeypatch) -> None:
    experiment = _module()
    root = tmp_path / experiment.EXPERIMENT_ID
    source_commit = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    experiment.freeze(root, source_commit=source_commit, source_approval_ref=_approval(tmp_path, experiment, source_commit))
    receipt = SimpleNamespace(
        disposition="NOT_RUN", reason="registered geometry infeasible",
        architecture_independent=True, precheck_input={"control_id": "test"},
        realization_sha256="a" * 64, geometry_sha256="b" * 64,
        straight_path_blocked=True, waypoint_path_clear=False,
        target_a_ik_error_m=0.0, target_b_ik_error_m=0.0,
    )
    monkeypatch.setattr(experiment, "precheck", lambda _spec: receipt)
    experiment.preflight(root)
    assert experiment.execute(root, limit=1) == {"completed": 1, "remaining": 539, "total": 540}
    path = next((root / "raw/dispositions").glob("*.json"))
    row = json.loads(path.read_text())
    assert row["disposition"] == "NOT_RUN"
    assert row["architecture_independent"] is True
    assert row["precheck_receipt_sha256"]
    assert not (root / "raw/episodes" / row["episode_id"]).exists()


def test_runtime_exception_is_sealed_invalid_and_does_not_abort(tmp_path: Path, monkeypatch) -> None:
    experiment = _module()
    root = tmp_path / experiment.EXPERIMENT_ID
    source_commit = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    experiment.freeze(root, source_commit=source_commit, source_approval_ref=_approval(tmp_path, experiment, source_commit))
    experiment.preflight(root)
    monkeypatch.setattr(experiment, "run_cell", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("boom")))
    assert experiment.execute(root, limit=1) == {"completed": 1, "remaining": 539, "total": 540}
    row = json.loads(next((root / "raw/dispositions").glob("*.json")).read_text())
    assert row["disposition"] == "INVALID_EXECUTION"
    assert row["execution_stage"] == "RUNTIME"
    assert row["exception_class"] == "ValueError"
    assert row["exception_message"] == "boom"
    assert row["source_commit"] == source_commit
    assert len(row["freeze_sha256"]) == 64


def test_preflight_is_closed_create_only_and_execute_rechecks_receipt(tmp_path: Path) -> None:
    experiment = _module()
    root = tmp_path / experiment.EXPERIMENT_ID
    source_commit = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    experiment.freeze(root, source_commit=source_commit, source_approval_ref=_approval(tmp_path, experiment, source_commit))
    first = experiment.preflight(root)
    assert first["total"] == 540
    assert experiment.preflight(root) == first
    receipt_path = next((root / "preflight/receipts").glob("*.json"))
    receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    with pytest.raises(RuntimeError, match="preflight"):
        experiment.execute(root, limit=1)


def test_freeze_requires_separate_exact_source_audit_approval(tmp_path: Path) -> None:
    experiment = _module()
    source_commit = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    with pytest.raises(RuntimeError, match="source audit approval"):
        experiment.freeze(tmp_path / "missing", source_commit=source_commit)
    wrong = _approval(tmp_path, experiment, "0" * 40)
    with pytest.raises(RuntimeError, match="source audit approval"):
        experiment.freeze(tmp_path / "wrong", source_commit=source_commit, source_approval_ref=wrong)
    with pytest.raises(RuntimeError, match="approval Git ref"):
        experiment._load_git_approval("not-a-git-ref", experiment.SOURCE_APPROVAL_PATH)


def test_freeze_revalidates_configuration_environment_and_embedded_approval(tmp_path: Path) -> None:
    experiment = _module()
    source_commit = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    root = tmp_path / "freeze-revalidation"
    experiment.freeze(root, source_commit=source_commit, source_approval_ref=_approval(tmp_path, experiment, source_commit))
    freeze_path = root / "freeze.json"
    original = freeze_path.read_bytes()
    attacked = json.loads(original)
    attacked["configuration_sha256"] = "0" * 64
    freeze_path.write_bytes(experiment.canonical_bytes(attacked))
    with pytest.raises(RuntimeError, match="matrix drift"):
        experiment._validate_freeze(root)
    freeze_path.write_bytes(original)
    attacked = json.loads(original)
    attacked["environment"]["python"] = "forged"
    freeze_path.write_bytes(experiment.canonical_bytes(attacked))
    with pytest.raises(RuntimeError, match="environment binding"):
        experiment._validate_freeze(root)


def test_freeze_rejects_source_closure_not_identical_to_approved_commit(tmp_path: Path, monkeypatch) -> None:
    experiment = _module()
    source_commit = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    approval = _approval(tmp_path, experiment, source_commit)
    original = experiment._source_closure

    def attacked_closure():
        rows = [dict(row) for row in original()]
        rows[0]["sha256"] = "0" * 64
        return rows

    monkeypatch.setattr(experiment, "_source_closure", attacked_closure)
    with pytest.raises(RuntimeError, match="source commit closure"):
        experiment.freeze(tmp_path / "closure-attack", source_commit=source_commit, source_approval_ref=approval)


def test_runner_pauses_at_50_until_exact_independent_release(tmp_path: Path) -> None:
    experiment = _module()
    root = tmp_path / experiment.EXPERIMENT_ID
    source_commit = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    experiment.freeze(root, source_commit=source_commit, source_approval_ref=_approval(tmp_path, experiment, source_commit))
    experiment.preflight(root)
    disposition_root = root / "raw/dispositions"
    disposition_root.mkdir(parents=True)
    for spec in experiment.matrix_specs()[:50]:
        (disposition_root / f"{spec.episode_id}.json").write_bytes(
            experiment.canonical_bytes({"episode_id": spec.episode_id})
        )
    with pytest.raises(RuntimeError, match="paused at first 50"):
        experiment.execute(root, limit=1)
    freeze_sha256 = experiment.sha256_bytes((root / "freeze.json").read_bytes())
    approval = tmp_path / "first50-approval.json"
    approval.write_bytes(experiment.canonical_bytes({
        "schema_version": 1,
        "experiment_id": experiment.EXPERIMENT_ID,
        "verdict": "APPROVE",
        "review_scope": "FIRST_50_CONTINUATION",
        "reviewer": "independent-test-reviewer",
        "source_commit": source_commit,
        "freeze_sha256": freeze_sha256,
        "disposition_count": 50,
        "disposition_inventory_sha256": experiment.disposition_inventory_sha256(root),
        "approval_parent_commit": source_commit,
    }))
    with pytest.raises(RuntimeError, match="disposition .*mismatch"):
        experiment.release_first50(root, f"test-file:{approval}")
    freeze_sha256 = experiment.sha256_bytes((root / "freeze.json").read_bytes())
    for spec in experiment.matrix_specs()[:50]:
        row = experiment._invalid_execution_row(
            spec, RuntimeError("registered test invalid"), stage="RUNTIME",
            source_commit=source_commit, freeze_sha256=freeze_sha256,
        )
        (disposition_root / f"{spec.episode_id}.json").write_bytes(experiment.canonical_bytes(row))
    approval_payload = json.loads(approval.read_text())
    approval_payload["disposition_inventory_sha256"] = experiment.disposition_inventory_sha256(root)
    approval.write_bytes(experiment.canonical_bytes(approval_payload))
    release = experiment.release_first50(root, f"test-file:{approval}")
    assert release["stage"] == "FIRST_50_INDEPENDENT_RELEASE"
    release_path = root / "first50-release.json"
    original_release = release_path.read_bytes()
    forged = json.loads(original_release)
    forged["reviewer"] = "forged-reviewer"
    release_path.write_bytes(experiment.canonical_bytes(forged))
    with pytest.raises(RuntimeError, match="canonical mismatch|release state mismatch"):
        experiment.execute(root, limit=1)
    release_path.write_bytes(original_release)
    first = sorted(disposition_root.glob("*.json"))[0]
    first.write_bytes(first.read_bytes() + b" ")
    with pytest.raises(RuntimeError, match="canonical mismatch|release state mismatch"):
        experiment.execute(root, limit=1)
