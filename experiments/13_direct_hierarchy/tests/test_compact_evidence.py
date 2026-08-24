from __future__ import annotations

import importlib
import json
from pathlib import Path
import shutil

import pytest


def _module():
    return importlib.import_module("experiments.13_direct_hierarchy.src.compact_evidence")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def compact_pack() -> Path:
    return _repository_root() / "reports/evidence/exp13-direct-hierarchy-v3"


def test_compact_pack_reconstructs_every_derived_byte(compact_pack: Path, tmp_path: Path) -> None:
    module = _module()
    receipt = module.verify_compact_pack(compact_pack)
    assert receipt["status"] == "PASS"
    assert receipt["dispositions"] == {"COMPLETE": 500, "NOT_RUN": 39, "INVALID_EXECUTION": 1}
    rebuilt = tmp_path / "rebuilt"
    module.reconstruct_derived(compact_pack, rebuilt)
    expected = compact_pack / "derived"
    assert module.tree_inventory(rebuilt) == module.tree_inventory(expected)
    plot_data = (compact_pack / "derived/graphs/plot-data.csv").read_text()
    assert "controller-sensitivity,success,P4-P6,-0.35757575757575755" in plot_data
    assert "wake-profiles,R3,mean_wakes,1.1081081081081081" in plot_data
    report = json.loads((compact_pack / "derived/report.json").read_text())
    r3_r2 = report["effects"]["R2"]["mission_success"]
    assert r3_r2["estimate"] == pytest.approx(-0.01)
    assert r3_r2["lower_95"] == pytest.approx(-0.03)
    assert r3_r2["upper_95"] == 0.0
    sensitivity = report["controller_sensitivity_P4_minus_P6"]["mission_success"]
    assert sensitivity["estimate"] == pytest.approx(-0.3575757575757576)
    assert sensitivity["lower_95"] == pytest.approx(-0.42272727272727273)
    assert sensitivity["upper_95"] == pytest.approx(-0.3)


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


@pytest.mark.parametrize("attack", ("extra", "missing_manifest", "missing_disposition", "schema_downgrade", "disposition_schema", "selection_swap"))
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
