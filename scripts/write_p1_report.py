"""Regenerate the P1 completion report from bounded local evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence

from reflect.run_state import load_run_manifest


ROOT = Path(__file__).resolve().parents[1]
ROLLOUT_ID = "p1-fixture"
GIT_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")


def _run(
    command: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
    expected_returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=None if environment is None else dict(environment),
        capture_output=True,
        text=True,
    )
    if completed.returncode != expected_returncode:
        raise RuntimeError(
            f"command returned {completed.returncode}, expected {expected_returncode}: "
            f"{' '.join(command)}\n{completed.stdout}{completed.stderr}"
        )
    return completed


def _safe_environment(*, physical: bool = False) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "PHYSICAL_DEPLOYMENT_ALLOWED": "true" if physical else "false",
            "REFLECT_REMOTE_ENABLED": "0",
            "UV_CACHE_DIR": ".cache/uv",
        }
    )
    return environment


def _file_hashes(path: Path) -> dict[str, str]:
    return {
        item.name: hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.iterdir())
        if item.is_file()
    }


def _last_nonempty_line(value: str) -> str:
    lines = [line for line in value.splitlines() if line.strip()]
    return lines[-1] if lines else "(no output)"


def _validate_evidence_base(value: str) -> str:
    if GIT_SHA_PATTERN.fullmatch(value) is None:
        raise ValueError("--evidence-base-sha must be a 40- or 64-digit Git SHA")
    resolved = _run(["git", "rev-parse", "--verify", f"{value}^{{commit}}"])
    return resolved.stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-base-sha", required=True)
    arguments = parser.parse_args(argv)
    evidence_base_sha = _validate_evidence_base(arguments.evidence_base_sha)

    manifest = load_run_manifest(ROOT / "docs" / "RUN_MANIFEST.yaml")
    if manifest.current_pass != 2:
        raise RuntimeError("P1 reporting requires current_pass: 2")
    if manifest.stages["p1"] != "complete" or manifest.stages["p2"] != "in_progress":
        raise RuntimeError("P1 reporting requires p1 complete and p2 in_progress")

    safe_environment = _safe_environment()
    lock = _run(["uv", "lock", "--check"], environment=safe_environment)
    tests = _run(["uv", "run", "pytest", "-q"], environment=safe_environment)
    safety = _run(["make", "safety-check"], environment=safe_environment)
    physical_safety = _run(
        ["make", "safety-check"],
        environment=_safe_environment(physical=True),
        expected_returncode=2,
    )

    with tempfile.TemporaryDirectory(prefix="reflect-p1-report-") as temporary:
        temporary_root = Path(temporary)
        first_root = temporary_root / "first"
        second_root = temporary_root / "second"
        first_fixture = _run(
            [
                sys.executable,
                "scripts/write_p1_fixture.py",
                "--output-dir",
                str(first_root),
            ],
            environment=safe_environment,
        )
        replay = _run(
            [
                sys.executable,
                "-m",
                "reflect.rollout",
                "replay",
                str(first_root / ROLLOUT_ID),
            ],
            environment=safe_environment,
        )
        second_fixture = _run(
            [
                sys.executable,
                "scripts/write_p1_fixture.py",
                "--output-dir",
                str(second_root),
            ],
            environment=safe_environment,
        )
        first_hashes = _file_hashes(first_root / ROLLOUT_ID)
        second_hashes = _file_hashes(second_root / ROLLOUT_ID)
        if first_hashes != second_hashes:
            raise RuntimeError("independent P1 fixture file hashes differ")

        physical_root = temporary_root / "physical"
        physical_fixture = _run(
            [
                sys.executable,
                "scripts/write_p1_fixture.py",
                "--output-dir",
                str(physical_root),
            ],
            environment=_safe_environment(physical=True),
            expected_returncode=1,
        )
        if (physical_root / ROLLOUT_ID).exists():
            raise RuntimeError("physical negative control created a rollout artifact")

        fixture_output = first_fixture.stdout.strip().replace(
            str(first_root), "<TEMP_ROOT_A>"
        )
        second_fixture_output = second_fixture.stdout.strip().replace(
            str(second_root), "<TEMP_ROOT_B>"
        )

    diff_check = _run(["git", "diff", "--check"])
    status = _run(["git", "status", "--short"])
    forbidden = _run(
        [
            "git",
            "ls-files",
            ".env",
            "*.pt",
            "*.pth",
            "*.ckpt",
            "*.safetensors",
            "results/**",
            "external/**",
            ".worktrees/**",
            ".superpowers/**",
        ]
    )
    if forbidden.stdout.strip():
        raise RuntimeError("forbidden repository paths are tracked")
    large_files = _run(
        [
            "find",
            ".",
            "-path",
            "./.git",
            "-prune",
            "-o",
            "-path",
            "./.venv",
            "-prune",
            "-o",
            "-path",
            "./.cache",
            "-prune",
            "-o",
            "-path",
            "./.superpowers",
            "-prune",
            "-o",
            "-type",
            "f",
            "-size",
            "+100M",
            "-print",
        ]
    )
    if large_files.stdout.strip():
        raise RuntimeError("unapproved repository file exceeds 100 MiB")

    artifact_hash_lines = "\n".join(
        f"- `{name}`: `{digest}`" for name, digest in sorted(first_hashes.items())
    )
    lock_output = lock.stdout.strip() or "(no output; exit 0)"
    safety_output = _last_nonempty_line(safety.stdout)
    physical_safety_output = _last_nonempty_line(
        physical_safety.stdout + physical_safety.stderr
    )
    physical_fixture_output = _last_nonempty_line(
        physical_fixture.stdout + physical_fixture.stderr
    )
    repository_status = status.stdout.strip() or "clean"

    report = f"""# P1 Run Report

## Executive result

The deterministic simulation-only shared rollout harness passed the bounded P1 gate.

## Evidence base

- Implementation/evidence-base Git SHA: `{evidence_base_sha}`
- Report provenance: commands below were rerun against the current checkout; the SHA
  intentionally names the pre-report implementation commit because a report cannot
  contain the hash of a commit that includes itself.
- Durable state: `p1: complete`, `p2: in_progress`, `current_pass: 2`.
- Working tree observed during report generation: `{repository_status}`

## Lock and tests

```text
UV_CACHE_DIR=.cache/uv uv lock --check
{lock_output}

UV_CACHE_DIR=.cache/uv uv run pytest -q
{tests.stdout.strip()}
```

## Fixture and replay

```text
python scripts/write_p1_fixture.py --output-dir <TEMP_ROOT_A>
{fixture_output}

python -m reflect.rollout replay <TEMP_ROOT_A>/p1-fixture
{replay.stdout.strip()}

python scripts/write_p1_fixture.py --output-dir <TEMP_ROOT_B>
{second_fixture_output}
```

The two independently generated fixture directories had identical SHA-256 hashes
for every file:

{artifact_hash_lines}

## Safety checks

```text
make safety-check
{safety_output}

PHYSICAL_DEPLOYMENT_ALLOWED=true REFLECT_REMOTE_ENABLED=0 make safety-check
exit {physical_safety.returncode}: {physical_safety_output}

PHYSICAL_DEPLOYMENT_ALLOWED=true python scripts/write_p1_fixture.py --output-dir <TEMP_ROOT_PHYSICAL>
exit {physical_fixture.returncode}: {physical_fixture_output}
```

The physical fixture negative control failed before `<TEMP_ROOT_PHYSICAL>/p1-fixture`
was created. Remote execution remained disabled.

## Repository boundary

- `git diff --check`: exit {diff_check.returncode}, no whitespace errors.
- Forbidden tracked-path query: empty.
- Unapproved files larger than 100 MiB: none.

## Scope and limitations

- This is deterministic synthetic artifact/replay evidence; no physics was run.
- Replay reduces saved events and does not rerun physics.
- No network or external source was used by the fixture or replay commands.
- P2 source auditing and empirical experiments have not run.
- The added `scripts/write_p1_report.py` is a documented plan-file-list omission,
  authorized as the narrow mechanism needed to regenerate this report.
- `tests/test_run_state.py` was narrowly updated after the mandated manifest
  transition exposed its stale P1-in-progress assertion; no other run-state test
  was changed.

## Highest-value next bounded action

Run the P2 public-source audit and freeze the approved source registry before any
experiment code or empirical claims.
"""
    (ROOT / "RUN_REPORT.md").write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
