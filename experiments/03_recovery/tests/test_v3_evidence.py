from __future__ import annotations

import hashlib
import importlib
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
    report = tmp_path / "qualification-report.md"
    report.write_bytes(
        (ROOT / ".superpowers/sdd/hierarchy-v3-qualification-report.md").read_bytes()
        + b"\nGoverned verification receipt: **69 V3 passed, 60 deselected; 129 Experiment 03 passed**.\n"
    )
    receipt["verification"] = {
        "experiment_03_passed": 129,
        "v3_deselected": 60,
        "v3_passed": 69,
    }
    receipt["qualification_report_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
    archive_manifest = tmp_path / "archive-manifest.json"
    archive_manifest.write_bytes(contracts.canonical_bytes(receipt))
    return output, report, archive_manifest


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


def test_qualification_report_facts_are_authenticated_from_derived_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "hierarchical-recovery-v3-qualification"
    (output / "derived").mkdir(parents=True)
    commit = "b" * 40
    (output / "qualification-freeze.json").write_bytes(contracts.canonical_bytes({"source_commit": commit}))
    (output / "raw").mkdir()
    (output / "raw/manifest.json").write_bytes(contracts.canonical_bytes({"schema_version": 1}))
    (output / "derived/manifest.json").write_bytes(contracts.canonical_bytes({"schema_version": 1}))
    (output / "derived/qualification-summary.json").write_bytes(contracts.canonical_bytes({
        "episode_count": 18,
        "hard_gates_passed": 10,
        "status": "READY_FOR_FRESH_READ_ONLY_REVIEW",
    }))
    hashes = [hashlib.sha256(f"controller-{index}".encode()).hexdigest() for index in range(6)]
    (output / "derived/controller-paths.csv").write_text(
        "controller_id,trajectory_sha256,q_ref_sha256,torque_sha256\n"
        f"P4-lookahead1-dqon,{hashes[0]},{hashes[1]},{hashes[2]}\n"
        f"P6-res0p5-slew48,{hashes[3]},{hashes[4]},{hashes[5]}\n", encoding="ascii",
    )
    (output / "derived/scorer-controls.csv").write_text("control,terminal,detected_count\ninvalid_action,FAILURE,17\n", encoding="ascii")
    report = tmp_path / "report.md"
    freeze_hash, raw_hash, derived_hash = [
        hashlib.sha256((output / name).read_bytes()).hexdigest()
        for name in ("qualification-freeze.json", "raw/manifest.json", "derived/manifest.json")
    ]
    retained = [path for path in output.rglob("*") if path.is_file()]
    archive_sha = "a" * 64
    report.write_text("\n".join((
        f"Qualified source commit: `{commit}`",
        "Status: **READY FOR FRESH READ-ONLY REVIEW**",
        f"Files: **{len(retained)}**",
        f"Bytes: **{sum(path.stat().st_size for path in retained):,}**",
        "The retained matrix contains exactly **18 executed episodes**, all using calibration seeds.",
        "The 10 registered hard gates all pass in the qualification bundle:",
        "| Controller | Call path | Trajectory SHA-256 | q_ref SHA-256 | torque SHA-256 |",
        "|---|---|---|---|---|",
        f"| P6 | `p6` | `{hashes[3]}` | `{hashes[4]}` | `{hashes[5]}` |",
        f"| repaired P4 | `p4` | `{hashes[0]}` | `{hashes[1]}` | `{hashes[2]}` |",
        "| Control | Detected count |", "|---|---:|",
        "| invalid action/trajectory | 17 |",
        "| Artifact | SHA-256 |", "|---|---|",
        f"| qualification freeze | `{freeze_hash}` |",
        f"| raw manifest / raw reconstruction | `{raw_hash}` |",
        f"| derived manifest / derived reconstruction | `{derived_hash}` |",
        "Governed verification receipt: **1 V3 passed, 2 deselected; 3 Experiment 03 passed**.",
        "The ignored working bundle is durably retained as the tracked, deterministic, content-addressed archive "
        f"`reports/evidence/hierarchical-recovery-v3-qualification/{archive_sha}.tar.gz` "
        f"(**123 bytes; {len(retained)} members**) with a tracked manifest and byte-exact extraction test.",
    )), encoding="utf-8")
    archive_manifest = tmp_path / "archive-manifest.json"
    archive_manifest.write_bytes(contracts.canonical_bytes({
        "archive_bytes": 123,
        "archive_sha256": archive_sha,
        "member_count": len(retained),
        "qualification_report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
        "tree_sha256": evidence.tree_sha256(output),
        "verification": {"experiment_03_passed": 3, "v3_deselected": 2, "v3_passed": 1},
    }))
    monkeypatch.setattr(evidence, "validate_publishable_evidence", lambda root: {"kind": "QUALIFICATION"})
    assert evidence.verify_qualification_report(output, report, archive_manifest=archive_manifest)["matched"] is True
    original = report.read_text(encoding="utf-8")
    report.write_text(
        original.replace(f"Qualified source commit: `{commit}`", "Qualified source commit: `stale`")
        + f"\n<!--\nQualified source commit: `{commit}`\n-->\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="report consistency"):
        evidence.verify_qualification_report(output, report, archive_manifest=archive_manifest)
    report.write_text(
        original
        .replace(hashes[3], "stale-p6-hash", 1)
        .replace("| invalid action/trajectory | 17 |", "| invalid action/trajectory | 1 |", 1)
        + f"\n<!-- orphan tokens {hashes[3]} | invalid action/trajectory | 17 | -->\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="report consistency"):
        evidence.verify_qualification_report(output, report, archive_manifest=archive_manifest)


@pytest.mark.parametrize(("old", "forged"), (
    ("Files: **437**", "Files: **999**"),
    ("Bytes: **50,009,565**", "Bytes: **1**"),
    ("The 10 registered hard gates all pass", "The 0 registered hard gates all pass"),
    ("Status: **READY FOR FRESH READ-ONLY REVIEW**", "Status: **STALE**"),
    ("exactly **18 executed episodes**", "exactly **99 executed episodes**"),
    ("V3 selection **69 passed, 60 deselected", "V3 selection **999 passed, 60 deselected"),
    ("8,759,557 bytes; 437 members", "8,759,557 bytes; 999 members"),
))
def test_qualification_report_rejects_forged_visible_inventory_and_gate_counts(
    tmp_path: Path, old: str, forged: str,
) -> None:
    output, report, archive_manifest = _tracked_qualification(tmp_path)
    original = report.read_text(encoding="utf-8")
    assert old in original
    report.write_text(original.replace(old, forged, 1), encoding="utf-8")
    with pytest.raises(RuntimeError, match="report consistency"):
        evidence.verify_qualification_report(output, report, archive_manifest=archive_manifest)


@pytest.mark.parametrize("line", (
    "Files: **437**",
    "The 10 registered hard gates all pass in the qualification bundle:",
))
def test_qualification_report_rejects_duplicate_visible_mutable_fact(tmp_path: Path, line: str) -> None:
    output, report, archive_manifest = _tracked_qualification(tmp_path)
    original = report.read_text(encoding="utf-8")
    matched = next(item for item in original.splitlines() if item.startswith(line))
    report.write_text(f"{original}\n{matched}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="report consistency"):
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
