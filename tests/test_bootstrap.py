from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_python_and_project_are_pinned() -> None:
    assert (ROOT / ".python-version").read_text().strip() == "3.11.13"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["project"]["requires-python"] == ">=3.11,<3.12"


def test_default_environment_is_simulation_only() -> None:
    values = dict(
        line.split("=", 1)
        for line in (ROOT / ".env.example").read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert values["PHYSICAL_DEPLOYMENT_ALLOWED"] == "false"
    assert values["REFLECT_REMOTE_ENABLED"] == "0"
    assert values["ALLOW_PUSH"] == "0"
    assert values["ALLOW_LARGE_MODELS"] == "0"
    assert values["ALLOW_EXTERNAL_LLM"] == "0"


def test_generated_and_sensitive_paths_are_ignored() -> None:
    ignored = set((ROOT / ".gitignore").read_text().splitlines())
    assert {
        ".venv/",
        ".cache/",
        ".superpowers/",
        ".worktrees/",
        "external/",
        ".env",
    } <= ignored


def test_bootstrap_tools_are_registered_before_install() -> None:
    import yaml

    registry = yaml.safe_load((ROOT / "references" / "bootstrap-tools.yaml").read_text())
    names = {item["name"] for item in registry["repositories"]}
    assert names == {"uv", "hatchling", "pyyaml", "pytest"}
    assert all(item["mode"] == "DIRECT_DEPENDENCY" for item in registry["repositories"])
