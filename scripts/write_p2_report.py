"""Safety-first CLI for publishing a report from complete local P2 evidence."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Mapping, Sequence

from reflect import p2_report
from reflect._p2_report_io import (
    EvidenceSnapshot,
    atomic_write_report,
    read_evidence_snapshot,
    run_local_command,
    validate_implementation_commit,
)
from reflect.p2_report import (
    Attempt,
    AttemptLog,
    CommandResult,
    REQUIRED_COMMANDS,
    parse_attempt_log,
    require_safe_state,
)


ROOT = Path(__file__).resolve().parents[1]
__all__ = [
    "Attempt",
    "AttemptLog",
    "CommandResult",
    "REQUIRED_COMMANDS",
    "build_report",
    "main",
    "parse_attempt_log",
    "require_safe_state",
]


def _environment_enabled(name: str) -> bool:
    value = os.environ.get(name, "").strip().casefold()
    if value in {"", "0", "false", "no", "off"}:
        return False
    if value in {"1", "true", "yes", "on"}:
        return True
    raise RuntimeError(f"{name} has an unrecognized safety value")


def _run_verification(
    command: tuple[str, ...], *, root: Path
) -> CommandResult:
    completed = run_local_command(root, command)
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _render(
    *,
    snapshot: EvidenceSnapshot,
    implementation_sha: str,
    command_results: Mapping[str, CommandResult],
    physical_deployment_allowed: bool,
    remote_enabled: bool,
    expected_registry_entries: int | None,
) -> str:
    return p2_report.build_report(
        registry_bytes=snapshot.registry,
        lock_bytes=snapshot.lock,
        attempt_bytes=snapshot.attempts,
        implementation_sha=implementation_sha,
        command_results=command_results,
        physical_deployment_allowed=physical_deployment_allowed,
        remote_enabled=remote_enabled,
        expected_registry_entries=expected_registry_entries,
    )


def build_report(
    *,
    project_root: Path,
    implementation_sha: str,
    command_results: Mapping[str, CommandResult],
    physical_deployment_allowed: bool,
    remote_enabled: bool,
    expected_registry_entries: int | None = None,
) -> str:
    """Compatibility facade over secure snapshots and the pure renderer."""
    root = Path(project_root)
    require_safe_state(
        physical_deployment_allowed=physical_deployment_allowed,
        remote_enabled=remote_enabled,
    )
    snapshot = read_evidence_snapshot(root)
    validated_sha = validate_implementation_commit(root, implementation_sha)
    return _render(
        snapshot=snapshot,
        implementation_sha=validated_sha,
        command_results=command_results,
        physical_deployment_allowed=physical_deployment_allowed,
        remote_enabled=remote_enabled,
        expected_registry_entries=expected_registry_entries,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    expected_registry_entries: int = 45,
) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-base-sha", required=True)
    arguments = parser.parse_args(argv)
    project_root = Path(root) if root is not None else ROOT
    physical = _environment_enabled("PHYSICAL_DEPLOYMENT_ALLOWED")
    remote = _environment_enabled("REFLECT_REMOTE_ENABLED")

    # Safety is deliberately the first operation that can precede a command.
    require_safe_state(
        physical_deployment_allowed=physical,
        remote_enabled=remote,
    )
    snapshot = read_evidence_snapshot(project_root)
    p2_report.validate_evidence(
        registry_bytes=snapshot.registry,
        lock_bytes=snapshot.lock,
        attempt_bytes=snapshot.attempts,
        expected_registry_entries=expected_registry_entries,
    )
    implementation_sha = validate_implementation_commit(
        project_root, arguments.evidence_base_sha
    )
    results = {
        name: _run_verification(command, root=project_root)
        for name, command in REQUIRED_COMMANDS.items()
    }
    if read_evidence_snapshot(project_root) != snapshot:
        raise RuntimeError("P2 evidence changed while verification commands ran")
    report = _render(
        snapshot=snapshot,
        implementation_sha=implementation_sha,
        command_results=results,
        physical_deployment_allowed=physical,
        remote_enabled=remote,
        expected_registry_entries=expected_registry_entries,
    )
    validate_implementation_commit(project_root, implementation_sha)
    atomic_write_report(project_root, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
