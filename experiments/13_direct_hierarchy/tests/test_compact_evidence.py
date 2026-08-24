from __future__ import annotations

import importlib
import json
from pathlib import Path
import shutil

import pytest


def _module():
    return importlib.import_module("experiments.13_direct_hierarchy.src.compact_evidence")


def _canonical_root() -> Path:
    return Path(__file__).resolve().parents[3] / "results/exp13-direct-hierarchy-v3"


@pytest.fixture(scope="module")
def compact_pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    module = _module()
    destination = tmp_path_factory.mktemp("exp13-pack") / "pack"
    module.publish_compact_pack(_canonical_root(), destination)
    return destination


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
    assert "controller-sensitivity,success,P4-P6,-0.35714285714285715" in plot_data
    assert "wake-profiles,R3,mean_wakes,1.1081081081081081" in plot_data


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
