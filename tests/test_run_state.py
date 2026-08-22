from pathlib import Path

import pytest

from reflect.run_state import ManifestError, load_run_manifest


ROOT = Path(__file__).resolve().parents[1]


def test_repository_manifest_has_bounded_recommended_scope() -> None:
    manifest = load_run_manifest(ROOT / "docs" / "RUN_MANIFEST.yaml")
    assert manifest.scope == "recommended"
    assert manifest.current_pass == 0
    assert manifest.max_passes == 16
    assert manifest.cpu_hours_max == 240
    assert manifest.physical_deployment_allowed is False
    assert manifest.remote_enabled is False
    assert manifest.stages["p0"] == "in_progress"
    assert manifest.stages["p1"] == "pending"


def test_manifest_rejects_pass_overrun(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(
        "scope: recommended\ncurrent_pass: 17\nmax_passes: 16\n"
        "budgets:\n  cpu_hours_max: 240\n"
        "safety:\n  physical_deployment_allowed: false\n  remote_enabled: false\n"
        "stages:\n  p0: in_progress\n"
    )
    with pytest.raises(ManifestError, match="current_pass"):
        load_run_manifest(path)
