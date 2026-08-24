from __future__ import annotations

import importlib
import json
from pathlib import Path
import shutil

import pytest
import numpy as np


def _module():
    return importlib.import_module("experiments.15_direct_hierarchy_replication.src.compact_evidence")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_portable_contract_is_frozen_before_outcomes() -> None:
    module = _module()
    assert module.BOOTSTRAP_DRAWS == 10_000
    assert module.BOOTSTRAP_SEED == 1313
    assert "derived/bootstrap/draws.csv" in module.DERIVED_PATHS
    assert "derived/graphs/plot-data.csv" in module.DERIVED_PATHS
    assert "derived/graphs/style.json" in module.DERIVED_PATHS
    for binding in (module.EXPECTED_FREEZE_SHA256, module.EXPECTED_RAW_INVENTORY_SHA256):
        assert binding == "UNSEALED_BEFORE_OUTCOME" or (len(binding) == 64 and set(binding) <= set("0123456789abcdef"))


def test_sample_annotations_never_substitute_another_population_and_allow_absence() -> None:
    module = _module()
    rows = [
        {"episode_id": "working", "disposition": "COMPLETE", "matrix_role": "PRIMARY", "architecture": "R3", "controller_id": "P6-res0p5-slew48", "mission_success": True, "safety_composite": False, "progress": 1.0},
        {"episode_id": "wrong-population", "disposition": "COMPLETE", "matrix_role": "PRIMARY", "architecture": "R1", "controller_id": "P6-res0p5-slew48", "mission_success": False, "safety_composite": True, "progress": 0.0},
    ]
    annotations = module._selected_annotations(rows)
    assert annotations[0]["category_status"] == "PRESENT"
    assert annotations[0]["episode_id"] == "working"
    assert annotations[1]["category_status"] == "ABSENT"
    assert annotations[1]["episode_id"] is None
    assert all(item["selection_population"] == "PRIMARY_P6_R3_COMPLETE" for item in annotations)


def test_sensitivity_plan_and_actual_n_eff_are_exactly_preregistered() -> None:
    module = _module()
    seeds = list(range(20262301, 20262306))
    plan = module._balanced_sensitivity_plan(seeds)
    assert plan.shape == (10_000, 5)
    assert plan[:3].tolist() == [
        [20262301] * 5,
        [20262301] * 4 + [20262302],
        [20262301] * 4 + [20262303],
    ]
    assert np.array_equal(plan[:3125], plan[3125:6250])
    assert np.array_equal(plan[:3125], plan[6250:9375])
    effect, draws = module._effect({20262301: [1.0], 20262303: [0.0]}, np.asarray([[20262301, 20262303]] * 10_000))
    assert effect["n_eff"] == 2
    assert effect["estimate"] == .5
    assert len(draws) == 10_000


@pytest.fixture(scope="module")
def compact_pack() -> Path:
    return _repository_root() / "reports/evidence/exp15-direct-hierarchy-replication-v2"


def test_compact_pack_reconstructs_every_derived_byte(compact_pack: Path, tmp_path: Path) -> None:
    module = _module()
    receipt = module.verify_compact_pack(compact_pack)
    assert receipt["status"] == "PASS"
    assert sum(receipt["dispositions"].values()) == 540
    rebuilt = tmp_path / "rebuilt"
    module.reconstruct_derived(compact_pack, rebuilt)
    expected = compact_pack / "derived"
    assert module.tree_inventory(rebuilt) == module.tree_inventory(expected)
    plot_data = (compact_pack / "derived/graphs/plot-data.csv").read_text()
    assert "controller-sensitivity,success,P4-P6," in plot_data
    assert "wake-profiles,R3,mean_wakes," in plot_data
    report = json.loads((compact_pack / "derived/report.json").read_text())
    r3_r2 = report["effects"]["R2"]["mission_success"]
    assert r3_r2["draws"] == 10_000
    assert r3_r2["n_eff"] == 10
    sensitivity = report["controller_sensitivity_P4_minus_P6"]["mission_success"]
    assert sensitivity["draws"] == 10_000
    assert sensitivity["n_eff"] == 5


def test_compact_pack_rejects_extra_and_symlink(compact_pack: Path, tmp_path: Path) -> None:
    module = _module()
    attacked = tmp_path / "extra"
    shutil.copytree(compact_pack, attacked)
    (attacked / "unexpected.txt").write_text("attack")
    with pytest.raises(RuntimeError, match="inventory"):
        module.verify_compact_pack(attacked)
    attacked = tmp_path / "symlink"
    shutil.copytree(compact_pack, attacked)
    (attacked / "derived/report-link.json").symlink_to("report.json")
    with pytest.raises(RuntimeError, match="symlink"):
        module.verify_compact_pack(attacked)


def test_compact_pack_rejects_rehashed_outcome_substitution(compact_pack: Path, tmp_path: Path) -> None:
    module = _module()
    attacked = tmp_path / "substitution"
    shutil.copytree(compact_pack, attacked)
    disposition = next((attacked / "inputs/dispositions").glob("*.json"))
    row = json.loads(disposition.read_text())
    if row["disposition"] != "COMPLETE":
        disposition = next(path for path in (attacked / "inputs/dispositions").glob("*.json") if json.loads(path.read_text())["disposition"] == "COMPLETE")
        row = json.loads(disposition.read_text())
    row["mission_success"] = not row["mission_success"]
    disposition.write_bytes(module.canonical_bytes(row))
    module.reseal_inventory_for_test(attacked)
    with pytest.raises(RuntimeError, match="substitution|derived reconstruction"):
        module.verify_compact_pack(attacked)


def test_compact_pack_rejects_rehashed_selected_raw_substitution(compact_pack: Path, tmp_path: Path) -> None:
    module = _module()
    attacked = tmp_path / "raw-substitution"
    shutil.copytree(compact_pack, attacked)
    raw_file = next(path for path in (attacked / "inputs/selected-episodes/working").glob("*") if path.name != "manifest.json")
    raw_file.write_bytes(raw_file.read_bytes() + b"attack")
    module.reseal_inventory_for_test(attacked)
    with pytest.raises(RuntimeError, match="selected raw substitution"):
        module.verify_compact_pack(attacked)


@pytest.mark.parametrize("attack", ("extra", "missing_manifest", "missing_disposition", "missing_preflight", "schema_downgrade", "disposition_schema", "selection_swap"))
def test_compact_pack_rejects_exact_closure_attacks(compact_pack: Path, tmp_path: Path, attack: str) -> None:
    module = _module()
    attacked = tmp_path / attack
    shutil.copytree(compact_pack, attacked)
    expected = ""
    if attack == "extra":
        (attacked / "inputs/unregistered.json").write_text("{}")
        module.reseal_inventory_for_test(attacked)
        expected = "allowlist"
    elif attack == "missing_manifest":
        next((attacked / "inputs/manifests").glob("*.json")).unlink()
        module.reseal_inventory_for_test(attacked)
        expected = "manifest identity"
    elif attack == "missing_disposition":
        next((attacked / "inputs/dispositions").glob("*.json")).unlink()
        module.reseal_inventory_for_test(attacked)
        expected = "disposition identity"
    elif attack == "missing_preflight":
        (attacked / "inputs/preflight-index.json").unlink()
        module.reseal_inventory_for_test(attacked)
        expected = "allowlist|preflight"
    elif attack == "schema_downgrade":
        path = attacked / "pack-manifest.json"
        manifest = json.loads(path.read_text())
        manifest["schema_version"] = 0
        path.write_bytes(module.canonical_bytes(manifest))
        expected = "schema"
    elif attack == "disposition_schema":
        path = next(path for path in (attacked / "inputs/dispositions").glob("*.json") if json.loads(path.read_text())["disposition"] == "COMPLETE")
        row = json.loads(path.read_text())
        row["unregistered"] = True
        path.write_bytes(module.canonical_bytes(row))
        module.reseal_inventory_for_test(attacked)
        expected = "disposition schema"
    else:
        path = attacked / "inputs/sample-annotations.json"
        annotations = json.loads(path.read_text())
        annotations[0]["episode_id"], annotations[1]["episode_id"] = annotations[1]["episode_id"], annotations[0]["episode_id"]
        path.write_bytes(module.canonical_bytes(annotations))
        module.reseal_inventory_for_test(attacked)
        expected = "selection"
    with pytest.raises(RuntimeError, match=expected):
        module.verify_compact_pack(attacked)
