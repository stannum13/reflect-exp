from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

world = importlib.import_module("experiments.06_world_model.world")
runner = importlib.import_module("experiments.06_world_model.run")


def test_small_matrix_is_create_only_complete_and_reconstructable(tmp_path: Path) -> None:
    specs = (*world.scene_rows()[:3], *world.scene_rows()[48:50], *world.scene_rows()[64:66])
    output = tmp_path / "evidence"
    result = runner.run_matrix(output, specs=specs, require_full=False)
    assert result == {"scenes": 7, "anchors": 14, "candidates": 112, "evaluation_candidates": 32}
    assert len((output / "raw/scenes.jsonl").read_text().splitlines()) == 7
    assert len((output / "raw/anchors.jsonl").read_text().splitlines()) == 14
    assert len((output / "raw/candidates.jsonl").read_text().splitlines()) == 112
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "PRELIMINARY_NONCONFIRMATORY_ENGINEERING_ONLY"
    assert len({row["path"] for row in manifest["files"]}) == len(manifest["files"])
    with pytest.raises(FileExistsError):
        runner.run_matrix(output, specs=specs, require_full=False)
    reconstructed = tmp_path / "reconstructed"
    runner.reconstruct(output / "raw", reconstructed)
    assert {
        path.name: path.read_bytes() for path in (output / "derived").iterdir()
    } == {
        path.name: path.read_bytes() for path in reconstructed.iterdir()
    }
