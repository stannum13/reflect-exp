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


def _valid_manifest() -> str:
    return (
        "scope: recommended\ncurrent_pass: 0\nmax_passes: 16\n"
        "budgets:\n  cpu_hours_max: 240\n"
        "safety:\n  physical_deployment_allowed: false\n  remote_enabled: false\n"
        "stages:\n"
        + "".join(f"  p{i}: pending\n" for i in range(11))
    )


def test_manifest_rejects_remote_enablement(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(_valid_manifest().replace("remote_enabled: false", "remote_enabled: true"))
    with pytest.raises(ManifestError, match="remote_enabled"):
        load_run_manifest(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current_pass", "'0'"),
        ("current_pass", "0.0"),
        ("current_pass", "false"),
        ("max_passes", "'16'"),
        ("max_passes", "16.0"),
        ("max_passes", "false"),
        ("cpu_hours_max", "'240'"),
        ("cpu_hours_max", "240.0"),
        ("cpu_hours_max", "false"),
        ("remote_enabled", "'false'"),
        ("physical_deployment_allowed", "'false'"),
    ],
)
def test_manifest_rejects_wrong_yaml_types(
    tmp_path: Path, field: str, value: str
) -> None:
    text = _valid_manifest()
    if field == "cpu_hours_max":
        text = text.replace("cpu_hours_max: 240", f"cpu_hours_max: {value}")
    elif field in {"remote_enabled", "physical_deployment_allowed"}:
        text = text.replace(f"{field}: false", f"{field}: {value}")
    else:
        text = text.replace(f"{field}: {'0' if field == 'current_pass' else '16'}", f"{field}: {value}")
    path = tmp_path / "manifest.yaml"
    path.write_text(text)
    with pytest.raises(ManifestError, match=field):
        load_run_manifest(path)


def test_manifest_requires_exact_stage_keys(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(_valid_manifest().replace("  p10: pending\n", "  p11: pending\n"))
    with pytest.raises(ManifestError, match="stage keys"):
        load_run_manifest(path)


@pytest.mark.parametrize("contents", ["", "- p0", "scope: recommended\n"])
def test_manifest_normalizes_malformed_yaml_to_manifest_error(
    tmp_path: Path, contents: str
) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(contents)
    with pytest.raises(ManifestError):
        load_run_manifest(path)
