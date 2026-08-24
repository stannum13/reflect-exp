from __future__ import annotations

import hashlib
import importlib
import csv
import json
from pathlib import Path
import tarfile
from dataclasses import replace

import pytest


contracts = importlib.import_module("experiments.03_recovery.src.v3_contracts")
evidence = importlib.import_module("experiments.03_recovery.src.v3_evidence")
ROOT = Path(__file__).resolve().parents[3]


def _tracked_qualification(tmp_path: Path) -> tuple[Path, Path, Path]:
    durable = ROOT / "reports/evidence/hierarchical-recovery-v3-qualification"
    receipt = json.loads((durable / "manifest.json").read_text(encoding="ascii"))
    output = tmp_path / "hierarchical-recovery-v3-qualification"
    output.mkdir()
    with tarfile.open(durable / receipt["archive"], "r:gz") as stream:
        stream.extractall(output, filter="data")
    receipt["verification"] = {
        "experiment_03_passed": 188,
        "v3_deselected": 60,
        "v3_passed": 128,
    }
    archive_manifest = tmp_path / "archive-manifest.json"
    archive_manifest.write_bytes(contracts.canonical_bytes(receipt))
    report = tmp_path / "qualification-report.md"
    report.write_bytes(evidence.render_qualification_report(output, archive_manifest))
    receipt["qualification_report_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
    archive_manifest.write_bytes(contracts.canonical_bytes(receipt))
    return output, report, archive_manifest


def _refresh_report_receipt(report: Path, archive_manifest: Path) -> None:
    receipt = json.loads(archive_manifest.read_text(encoding="ascii"))
    receipt["qualification_report_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
    archive_manifest.write_bytes(contracts.canonical_bytes(receipt))


def test_qualification_matrix_is_calibration_only_and_covers_required_contrasts() -> None:
    specs = evidence.qualification_specs()
    assert len(specs) == 18
    assert {item.seed for item in specs} == set(contracts.CALIBRATION_SEEDS)
    assert all(item.seed not in range(20261801, 20261811) for item in specs)
    assert {item.scenario_id for item in specs} == set(contracts.SCENARIO_IDS)
    assert {item.architecture for item in specs if item.scenario_id == "semantic-object-unavailable" and item.seed == 20261893} == set(contracts.Architecture)
    assert {item.controller_id for item in specs if item.scenario_id == "anchor-nominal" and item.seed == 20261894} == {
        contracts.PRIMARY_CONTROLLER_ID,
        contracts.SENSITIVITY_CONTROLLER_ID,
    }


def test_complete_local_import_closure_is_frozen() -> None:
    closure = evidence.source_closure()
    paths = {item["path"] for item in closure}
    assert {
        "experiments/03_recovery/run_v3_qualification.py",
        "experiments/03_recovery/src/contracts.py",
        "experiments/03_recovery/src/v3_contracts.py",
        "experiments/03_recovery/src/v3_policy.py",
        "experiments/03_recovery/src/v3_runtime.py",
        "experiments/03_recovery/src/v3_scorer.py",
        "experiments/03_recovery/src/v3_evidence.py",
        "experiments/01_policy_control/configs/base.yaml",
        "experiments/01_policy_control/src/arm.py",
        "experiments/01_policy_control/src/contracts.py",
        "experiments/01_policy_control/src/kinematics.py",
        "experiments/01_policy_control/src/representations.py",
        "reflect/types.py",
        "docs/superpowers/specs/2026-08-23-hierarchical-recovery-v3-preregistered.md",
        "pyproject.toml",
        "uv.lock",
    } <= paths
    assert evidence.verify_source_closure(closure) == closure
    assert all(len(item["sha256"]) == 64 and item["bytes"] > 0 for item in closure)


def test_structural_cause_boundary_audit_closes_observable_and_policy_call_sites() -> None:
    audit = evidence.cause_boundary_audit()
    assert audit["passed"] is True
    assert audit["observable_parameters"] == [
        "tick", "trace_rows", "action_valid", "geometry_feasible", "semantic_preconditions_valid",
        "memory_version", "command_content_sha256", "successful_execution_content_sha256",
        "command_gap_ticks", "reobserve_index",
    ]
    assert audit["forbidden_identifiers"] == []
    assert audit["observable_call_count"] >= 2
    assert audit["policy_call_count"] >= 1
    assert {"_observable", "_path_clear_from_observation", "_command_gap_from_action_history", "retained_load_estimate_nm"} <= set(audit["dependency_closure"])
    assert audit["transitive_forbidden_identifiers"] == []


def test_full_qualification_publication_and_raw_reconstruction_are_byte_exact(tmp_path: Path) -> None:
    output = tmp_path / "hierarchical-recovery-v3-qualification"
    result = evidence.run_qualification(output)
    assert result["status"] == "READY_FOR_FRESH_READ_ONLY_REVIEW"
    assert result["episode_count"] == 18
    assert result["hard_gates_passed"] == 10
    assert not (tmp_path / "hierarchical-recovery-v3").exists()

    raw_manifest = json.loads((output / "raw/manifest.json").read_text(encoding="ascii"))
    assert raw_manifest["episode_count"] == 18
    assert raw_manifest["not_run_positive_control"]["disposition"] == "NOT_RUN"
    assert raw_manifest["not_run_positive_control"]["reason"] == "TARGET_OUTSIDE_REACH"
    assert set(raw_manifest["not_run_positive_control"]["precheck_input"]) == {
        "control_id", "q0", "target_a_xy", "target_b_xy", "obstacle_xy", "obstacle_radius_m",
    }
    assert all(row["seed"] in contracts.CALIBRATION_SEEDS for row in raw_manifest["episodes"])
    first = output / "raw/episodes" / raw_manifest["episodes"][0]["episode_id"]
    assert (first / "contact-envelopes.jsonl").is_file()
    assert (output / "derived/examples.json").is_file()
    for stem in ("injection-timing", "controller-paths", "budget-sequences", "scorer-controls"):
        assert (output / f"derived/{stem}.csv").is_file()
        assert (output / f"derived/{stem}.svg").is_file()
        assert (output / f"derived/{stem}.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    gate_audits = json.loads((output / "derived/gate-audits.json").read_text(encoding="ascii"))
    assert set(gate_audits) == {"injection", "disturbance", "budgets", "cause_boundary", "not_run"}
    assert all(item["passed"] is True for item in gate_audits.values())
    freeze = json.loads((output / "qualification-freeze.json").read_text(encoding="ascii"))
    assert set(freeze["environment"]) >= {
        "python", "python_executable_sha256", "numpy", "mujoco", "platform", "png_renderer",
    }
    assert freeze["configuration"]["outcome_matrix"]["episode_count"] == 360
    clean = tmp_path / "clean-reconstruction"
    replay = evidence.reconstruct(output, clean)
    assert replay["matched"] is True
    assert replay["episodes_replayed"] == 18
    assert replay["raw_tree_sha256"] == hashlib.sha256((output / "raw/manifest.json").read_bytes()).hexdigest()
    expected = sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file())
    actual = sorted(path.relative_to(clean).as_posix() for path in clean.rglob("*") if path.is_file())
    assert actual == expected
    assert all((output / name).read_bytes() == (clean / name).read_bytes() for name in expected)


def test_durable_archive_is_content_addressed_and_extracts_byte_exact(tmp_path: Path) -> None:
    output = tmp_path / "hierarchical-recovery-v3-qualification"
    evidence.run_qualification(output)
    destination = tmp_path / "durable"
    receipt = evidence.publish_durable_archive(output, destination)
    assert evidence.publish_durable_archive(output, destination) == receipt
    archive = destination / receipt["archive"]
    assert archive.name == f"{receipt['archive_sha256']}.tar.gz"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == receipt["archive_sha256"]
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(archive, "r:gz") as stream:
        stream.extractall(extracted, filter="data")
    assert evidence.tree_sha256(output) == evidence.tree_sha256(extracted)
    payload = archive.read_bytes()
    archive.unlink()
    with pytest.raises(RuntimeError, match="archive member mismatch"):
        evidence.publish_durable_archive(output, destination)
    assert not archive.exists()
    archive.write_bytes(payload + b"tamper")
    with pytest.raises(RuntimeError, match="archive member mismatch"):
        evidence.publish_durable_archive(output, destination)


def test_durable_archive_rejects_arbitrary_incomplete_tree(tmp_path: Path) -> None:
    arbitrary = tmp_path / "one-file"
    arbitrary.mkdir()
    (arbitrary / "claim.json").write_text("{}\n", encoding="ascii")
    with pytest.raises(RuntimeError, match="publishable evidence"):
        evidence.publish_durable_archive(arbitrary, tmp_path / "archive")


def test_manifest_inventory_rejects_unlisted_recursive_member(tmp_path: Path) -> None:
    root = tmp_path / "derived"
    root.mkdir()
    payload = b"declared\n"
    (root / "declared.bin").write_bytes(payload)
    inventory = [{
        "path": "declared.bin", "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }]
    evidence._validate_inventory(root, inventory)
    (root / "unlisted.bin").write_bytes(b"unlisted\n")
    with pytest.raises(RuntimeError, match="unlisted|closed inventory"):
        evidence._validate_inventory(root, inventory)


def test_qualification_report_facts_are_authenticated_from_derived_data(tmp_path: Path) -> None:
    output, report, archive_manifest = _tracked_qualification(tmp_path)
    assert evidence.verify_qualification_report(output, report, archive_manifest=archive_manifest)["matched"] is True
    original = report.read_text(encoding="utf-8")
    commit = json.loads((output / "qualification-freeze.json").read_text(encoding="ascii"))["source_commit"]
    report.write_text(
        original.replace(f"Qualified source commit: `{commit}`", f"Qualified source commit: `{'0' * 40}`")
        + f"\n<!--\nQualified source commit: `{commit}`\n-->\n",
        encoding="utf-8",
    )
    _refresh_report_receipt(report, archive_manifest)
    with pytest.raises(RuntimeError, match="report consistency"):
        evidence.verify_qualification_report(output, report, archive_manifest=archive_manifest)
    original = report.read_text(encoding="utf-8")
    report.write_text(original, encoding="utf-8")
    original = (ROOT / ".superpowers/sdd/hierarchy-v3-qualification-report.md").read_text(encoding="utf-8")
    p6 = next(row for row in csv.DictReader((output / "derived/controller-paths.csv").read_text(encoding="ascii").splitlines()) if row["controller_id"] == "P6-res0p5-slew48")
    report.write_text(
        original
        .replace(p6["trajectory_sha256"], "0" * 64, 1)
        .replace("| invalid action/trajectory | 17 |", "| invalid action/trajectory | 1 |", 1)
        + f"\n<!-- orphan tokens {p6['trajectory_sha256']} | invalid action/trajectory | 17 | -->\n",
        encoding="utf-8",
    )
    _refresh_report_receipt(report, archive_manifest)
    with pytest.raises(RuntimeError, match="report consistency"):
        evidence.verify_qualification_report(output, report, archive_manifest=archive_manifest)


@pytest.mark.parametrize(("old", "forged"), (
    ("The 10 registered hard gates all pass", "The 0 registered hard gates all pass"),
    ("Status: **READY FOR FRESH READ-ONLY REVIEW**", "Status: **STALE**"),
    ("exactly **18 executed episodes**", "exactly **99 executed episodes**"),
))
def test_qualification_report_rejects_forged_visible_inventory_and_gate_counts(
    tmp_path: Path, old: str, forged: str,
) -> None:
    output, report, archive_manifest = _tracked_qualification(tmp_path)
    original = report.read_text(encoding="utf-8")
    assert old in original
    report.write_text(original.replace(old, forged, 1), encoding="utf-8")
    _refresh_report_receipt(report, archive_manifest)
    with pytest.raises(RuntimeError, match="report consistency"):
        evidence.verify_qualification_report(output, report, archive_manifest=archive_manifest)


@pytest.mark.parametrize(("old", "forged"), (
    ("Held-out seeds `20261801..20261810` were not executed", "Held-out seeds `20261801..20261811` were not executed"),
    ("The frozen post-approval matrix contains 360 cells", "The frozen post-approval matrix contains 359 cells"),
    ("320 primary P6 cells and 40 fixed P4 sensitivity cells", "321 primary P6 cells and 39 fixed P4 sensitivity cells"),
    ("Independent scoring reconstructed **17 SUCCESS** and **1 expected FAILURE**", "Independent scoring reconstructed **18 SUCCESS** and **0 expected FAILURE**"),
    ("The retained calibration seeds are `20261891`, `20261892`, `20261893`, and `20261894`", "The retained calibration seeds are `20261891`, `20261892`, `20261893`, and `20261895`"),
    ("| R3/P6, all eight registered scenarios, seed `20261891` | 8 | 8 SUCCESS |", "| R3/P6, all eight registered scenarios, seed `20261891` | 7 | 7 SUCCESS |"),
    ("| R0/R1/R2/R3 semantic-object-unavailable, seed `20261893` | 4 | 3 SUCCESS; R0 expected FAILURE |", "| R0/R1/R2/R3 semantic-object-unavailable, seed `20261893` | 4 | 4 SUCCESS |"),
    ("| R0/R1/R2/R3 control-impulse, seed `20261892` | 4 | 4 SUCCESS |", "| R0/R1/R2/R3 control-impulse, seed `20261892` | 5 | 5 SUCCESS |"),
    ("| R3 P6/P4 anchor sensitivity, seed `20261894` | 2 | 2 SUCCESS |", "| R3 P6/P4 anchor sensitivity, seed `20261894` | 1 | 1 SUCCESS |"),
    ("exact sampled-tick injection, six realized disturbances", "exact sampled-tick injection, five realized disturbances"),
    ("independent raw scorer, nine terminal-positive controls", "independent raw scorer, eight terminal-positive controls"),
    ("`emit_chunk:P6 -> reference_for_tick:P6 -> bounded_pd`", "`stale-p6-call-path`"),
    ("`emit_chunk:P4 -> with_p4_executor_tuning:1:dqon -> reference_for_tick:P4 -> bounded_pd`", "`stale-p4-call-path`"),
    ("| collision | 1 |", "| collision | 2 |"),
    ("| forbidden execution | 9 |", "| forbidden execution | 8 |"),
    ("| loop/no progress | 1 |", "| loop/no progress | 2 |"),
    ("| missed dwell | 1 |", "| missed dwell | 2 |"),
    ("| invalid reset | 1 |", "| invalid reset | 2 |"),
    ("| stale observation/memory | 2 |", "| stale observation/memory | 1 |"),
    ("| unsafe torque | 1 |", "| unsafe torque | 2 |"),
    ("| wrong object | 9 |", "| wrong object | 8 |"),
    ("working episode `qualification-P6-R3-semantic-object-unavailable-20261891`", "working episode `qualification-P6-R3-anchor-nominal-20261891`"),
    ("nonworking episode `qualification-P6-R0-semantic-object-unavailable-20261893`", "nonworking episode `qualification-P6-R3-semantic-object-unavailable-20261893`"),
    ("NOT_RUN control `architecture-independent-unreachable-geometry-v1`", "NOT_RUN control `stale-not-run-control`"),
    ("It replayed all **18** episodes with `matched=true`", "It replayed all **17** episodes with `matched=true`"),
    ("It replayed all **18** episodes with `matched=true`", "It replayed all **18** episodes with `matched=false`"),
    ("Reviewer decision: **PENDING — approve or reject**", "Reviewer decision: **APPROVED**"),
))
def test_qualification_report_rejects_forged_visible_semantic_fact_with_recomputed_receipt(
    tmp_path: Path, old: str, forged: str,
) -> None:
    output, report, archive_manifest = _tracked_qualification(tmp_path)
    original = report.read_text(encoding="utf-8")
    assert old in original
    report.write_text(original.replace(old, forged, 1), encoding="utf-8")
    _refresh_report_receipt(report, archive_manifest)
    with pytest.raises(RuntimeError, match="report consistency"):
        evidence.verify_qualification_report(output, report, archive_manifest=archive_manifest)


@pytest.mark.parametrize("line", (
    "The 10 registered hard gates all pass in the qualification bundle:",
    "| R3/P6, all eight registered scenarios, seed `20261891` | 8 | 8 SUCCESS |",
    "| collision | 1 |",
    "The retained examples bind the working episode `qualification-P6-R3-semantic-object-unavailable-20261891`, nonworking episode `qualification-P6-R0-semantic-object-unavailable-20261893`, and architecture-independent NOT_RUN control `architecture-independent-unreachable-geometry-v1`.",
    "Reviewer decision: **PENDING — approve or reject**",
))
def test_qualification_report_rejects_duplicate_visible_mutable_fact(tmp_path: Path, line: str) -> None:
    output, report, archive_manifest = _tracked_qualification(tmp_path)
    original = report.read_text(encoding="utf-8")
    matched = next(item for item in original.splitlines() if line in item)
    report.write_text(f"{original}\n{matched}\n", encoding="utf-8")
    _refresh_report_receipt(report, archive_manifest)
    with pytest.raises(RuntimeError, match="report consistency"):
        evidence.verify_qualification_report(output, report, archive_manifest=archive_manifest)


def test_qualification_report_rejects_any_appended_visible_text_with_recomputed_authentication(tmp_path: Path) -> None:
    output, report, archive_manifest = _tracked_qualification(tmp_path)
    report.write_text(
        report.read_text(encoding="utf-8") + "\nThis extra visible claim is not artifact-derived.\n",
        encoding="utf-8",
    )
    _refresh_report_receipt(report, archive_manifest)
    with pytest.raises(RuntimeError, match="canonical|report consistency"):
        evidence.verify_qualification_report(output, report, archive_manifest=archive_manifest)


def test_publication_is_create_only(tmp_path: Path) -> None:
    output = tmp_path / "hierarchical-recovery-v3-qualification"
    output.mkdir()
    with pytest.raises(FileExistsError):
        evidence.run_qualification(output)


def test_budget_audit_rejects_tampered_before_after_transition() -> None:
    spec = evidence.V3EpisodeSpec(contracts.Architecture.R0, "semantic-object-unavailable", 20261893, contracts.PRIMARY_CONTROLLER_ID)
    raw = evidence.run_episode(spec)
    first = raw.decisions[0]
    forged_after = replace(first.budget_after, control_remaining=first.budget_before.control_remaining)
    forged = replace(raw, decisions=(replace(first, budget_after=forged_after), *raw.decisions[1:]))
    score = evidence.score_episode(forged)
    audit = evidence._budget_audit({spec.episode_id: forged}, {spec.episode_id: score})
    assert audit["passed"] is False


@pytest.mark.parametrize("scenario", contracts.SCENARIO_IDS[1:])
def test_disturbance_audit_rejects_matched_anchor_domain_substitution(scenario: str) -> None:
    anchor_spec = evidence.V3EpisodeSpec(contracts.Architecture.R3, "anchor-nominal", 20261891, contracts.PRIMARY_CONTROLLER_ID)
    disturbed_spec = evidence.V3EpisodeSpec(contracts.Architecture.R3, scenario, 20261891, contracts.PRIMARY_CONTROLLER_ID)
    anchor = evidence.run_episode(anchor_spec)
    disturbed = evidence.run_episode(disturbed_spec)
    forged = replace(
        disturbed,
        trace=anchor.trace,
        action_envelopes=anchor.action_envelopes,
        commands=anchor.commands,
        trajectory_bytes=anchor.trajectory_bytes,
        memory_events=anchor.memory_events,
        memory_ledger=anchor.memory_ledger,
    )
    audit = evidence._disturbance_audit({anchor_spec.episode_id: anchor, disturbed_spec.episode_id: forged})
    assert audit["passed"] is False


def test_precheck_audit_rejects_missing_and_tampered_qualification_receipts() -> None:
    spec = evidence.V3EpisodeSpec(contracts.Architecture.R3, "anchor-nominal", 20261891, contracts.PRIMARY_CONTROLLER_ID)
    raw = evidence.run_episode(spec)
    not_run = evidence._not_run_control()
    complete = {f"identity-{index}": raw for index in range(18)}
    assert evidence._precheck_audit(complete, not_run)["passed"] is True
    assert evidence._precheck_audit(dict(list(complete.items())[:-1]), not_run)["passed"] is False
    forged = replace(raw, precheck=replace(raw.precheck, geometry_sha256="f" * 64))
    tampered = dict(complete)
    tampered["identity-0"] = forged
    assert evidence._precheck_audit(tampered, not_run)["passed"] is False
