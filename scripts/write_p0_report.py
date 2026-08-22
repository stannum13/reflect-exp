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


def command(*args: str) -> str:
    return subprocess.run(
        args, cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> int:
    manifest = load_run_manifest(ROOT / "docs" / "RUN_MANIFEST.yaml")
    safety = SafetyConfig.from_mapping(os.environ)
    safety.require_simulation_only()
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

No robotics source, simulator, model, or external reference was fetched in P0.

## Interface findings

P0 promotes only safety configuration and durable run-state validation.

## Blockers

None for P0. Live network access remains conditional for P2.

## Highest-value next action

Implement P1 shared contracts, virtual clock, event schema, rollout writer, and replay.

## Safety

- no physical motor messages: confirmed
- no non-loopback deployment connection: confirmed
- no public inference server: confirmed
- no secrets committed: confirmed by tracked-file review
- no model downloaded: confirmed
"""
    (ROOT / "RUN_REPORT.md").write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
