"""Resolve factual GitHub source metadata without cloning repositories."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from typing import Any, Callable

from reflect.safety import SafetyConfig, SafetyViolation
from reflect.source_fetch import (
    CacheStore,
    CachingTransport,
    GitRunner,
    SourceFetchError,
    UrllibTransport,
    atomic_write_lock,
    lock_yaml_bytes,
    resolve_registry,
)
from reflect.sources import load_registry


ROOT = Path(__file__).resolve().parents[1]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve pinned GitHub metadata without creating source checkouts."
    )
    selectors = parser.add_mutually_exclusive_group(required=True)
    selectors.add_argument("--all-metadata-only", action="store_true")
    selectors.add_argument("--name")
    parser.add_argument("--metadata-only", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    registry_path: Path | None = None,
    lock_path: Path | None = None,
    resolution_transport: Any | None = None,
    runner: Any | None = None,
    http_transport: Any | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> int:
    """Run the P2 command, with keyword-only offline test injection seams."""
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.name is not None and not arguments.metadata_only:
        parser.error("--name requires --metadata-only")
    if arguments.all_metadata_only and arguments.metadata_only:
        parser.error("--metadata-only is represented by --all-metadata-only")

    # The guard intentionally precedes registry/cache reads and all transport calls.
    SafetyConfig.from_mapping(os.environ).require_simulation_only()

    project_root = Path(root) if root is not None else ROOT
    source_registry_path = (
        Path(registry_path)
        if registry_path is not None
        else project_root / "references" / "repos.yaml"
    )
    source_lock_path = (
        Path(lock_path)
        if lock_path is not None
        else project_root / "references" / "repos.lock.yaml"
    )
    registry = load_registry(source_registry_path)
    if arguments.all_metadata_only:
        names = tuple(entry.name for entry in registry.repositories)
    else:
        names = (arguments.name,)

    transport = resolution_transport
    if transport is None:
        cache = CacheStore(project_root / "external" / ".metadata")
        transport = CachingTransport(
            runner or GitRunner(),
            http_transport or UrllibTransport(),
            cache,
            clock,
            names[0],
        )
    candidate = resolve_registry(registry, names, transport, clock)
    if arguments.all_metadata_only:
        atomic_write_lock(source_lock_path, candidate)
    else:
        sys.stdout.write(lock_yaml_bytes(candidate).decode("utf-8"))
        sys.stdout.flush()
    return 0


def _entrypoint() -> int:
    try:
        return main()
    except (SourceFetchError, SafetyViolation, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
