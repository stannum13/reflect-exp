"""Generate the exact P0 completion report from current repository evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import platform
import subprocess
import sys

from reflect.run_state import load_run_manifest
from reflect.safety import SafetyConfig


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PYTHON_VERSION = (3, 11, 13)
EXCLUDED_REPOSITORY_DIRECTORIES = {".git", ".venv", ".cache", ".superpowers"}
MODEL_ARTIFACT_SUFFIXES = {".bin", ".ckpt", ".onnx", ".pt", ".pth", ".safetensors"}
MODEL_ARTIFACT_DIRECTORIES = {"checkpoints", "models", "weights"}


def command(*args: str) -> str:
    return subprocess.run(
        args, cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def repository_paths() -> set[Path]:
    paths = set()
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_REPOSITORY_DIRECTORIES for part in relative.parts):
            continue
        if path.is_file():
            paths.add(relative)
    return paths


def is_model_artifact(path: Path) -> bool:
    return (
        path.suffix.lower() in MODEL_ARTIFACT_SUFFIXES
        or bool(set(path.parts) & MODEL_ARTIFACT_DIRECTORIES)
    )


def main() -> int:
    manifest = load_run_manifest(ROOT / "docs" / "RUN_MANIFEST.yaml")
    safety = SafetyConfig.from_mapping(os.environ)
    safety.require_simulation_only()
    if safety.validated_remote_target() is not None:
        raise RuntimeError("remote execution must be disabled for P0 reporting")
    if sys.version_info[:3] != EXPECTED_PYTHON_VERSION:
        actual = ".".join(map(str, sys.version_info[:3]))
        expected = ".".join(map(str, EXPECTED_PYTHON_VERSION))
        raise RuntimeError(f"P0 reporting requires Python {expected}, got {actual}")
    command("uv", "lock", "--check")
    tracked_paths = set(filter(None, command("git", "ls-files").splitlines()))
    inspected_paths = repository_paths()
    no_dotenv_is_tracked = ".env" not in tracked_paths
    no_model_artifact_present = not any(map(is_model_artifact, inspected_paths))
    no_large_file_present = all(
        (ROOT / path).stat().st_size <= 100 * 1024 * 1024 for path in inspected_paths
    )
    test_output = command(sys.executable, "-m", "pytest", "-q")
    sha = command("git", "rev-parse", "HEAD")
    status = command("git", "status", "--short") or "clean"
    text = f"""# P0 Run Report

## Executive result

The simulation-only repository foundation is operational.

## Environment

- Generated UTC: {datetime.now(timezone.utc).isoformat()}
- Git SHA before report commit: `{sha}`
- Git status before report commit: `{status}`
- Platform: `{platform.platform()}`
- Python: `{platform.python_version()}`
- Required Python: `{'.'.join(map(str, EXPECTED_PYTHON_VERSION))}` (verified)
- Lockfile: `uv lock --check` passed
- Scope: `{manifest.scope}`

## Commands

```text
UV_CACHE_DIR=.cache/uv uv sync --locked --python 3.11.13
UV_CACHE_DIR=.cache/uv uv run pytest -q
PHYSICAL_DEPLOYMENT_ALLOWED=false REFLECT_REMOTE_ENABLED=0 UV_CACHE_DIR=.cache/uv uv run python -m reflect.safety check
```

## Tests

```text
{test_output}
```

## Results

- Locked interpreter and package import: PASS
- Simulation-only safety guard: PASS
- Remote execution default: DISABLED
- Physical deployment: DISABLED

## Public-source use

This local evidence generator made no network requests.

## Interface findings

P0 promotes only safety configuration and durable run-state validation.

## Blockers

None for P0. Live network access remains conditional for P2.

## Highest-value next action

Implement P1 shared contracts, virtual clock, event schema, rollout writer, and replay.

## Safety

- Physical deployment is rejected by the simulation-only safety policy.
- Remote execution is disabled for this P0 report.
- Tracked paths inspected: {len(tracked_paths)}.
- Repository files inspected: {len(inspected_paths)} (excluding `.git`, `.venv`,
  `.cache`, and `.superpowers`).
- No `.env` file is tracked: {'confirmed' if no_dotenv_is_tracked else 'NOT CONFIRMED'}.
- No model artifact is tracked or present in the inspected repository:
  {'confirmed' if no_model_artifact_present else 'NOT CONFIRMED'}.
- No inspected repository file exceeds 100 MiB:
  {'confirmed' if no_large_file_present else 'NOT CONFIRMED'}.
"""
    (ROOT / "RUN_REPORT.md").write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
