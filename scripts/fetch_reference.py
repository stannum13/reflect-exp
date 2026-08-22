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
from reflect.source_checkout import (
    SparseCheckoutError,
    SubprocessCheckoutRunner,
    checkout_sparse,
    eligible_checkout_specs,
)
from reflect.source_evidence import (
    CheckoutEvidence,
    canonical_json_bytes,
    write_evidence_create_only,
)
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
from reflect.sources import load_lock, load_registry


ROOT = Path(__file__).resolve().parents[1]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve pinned GitHub metadata or create an approved sparse checkout."
    )
    selectors = parser.add_mutually_exclusive_group(required=True)
    selectors.add_argument("--all-metadata-only", action="store_true")
    selectors.add_argument("--name")
    selectors.add_argument("--experiment")
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--sparse-checkout", action="store_true")
    parser.add_argument("--fragment-dir")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    registry_path: Path | None = None,
    lock_path: Path | None = None,
    resolution_transport: Any | None = None,
    runner: Any | None = None,
    checkout_runner: Any | None = None,
    http_transport: Any | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> int:
    """Run the P2 command, with keyword-only offline test injection seams."""
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.all_metadata_only and (
        arguments.metadata_only or arguments.sparse_checkout
    ):
        parser.error("--all-metadata-only is a complete mode selector")
    if arguments.name is not None and (
        arguments.metadata_only == arguments.sparse_checkout
    ):
        parser.error("--name requires exactly one operation mode")
    if arguments.experiment is not None and not arguments.sparse_checkout:
        parser.error("--experiment requires --sparse-checkout")
    if arguments.experiment is not None and arguments.metadata_only:
        parser.error("--experiment does not support --metadata-only")
    if arguments.sparse_checkout and arguments.fragment_dir is None:
        parser.error("--sparse-checkout requires --fragment-dir")
    if not arguments.sparse_checkout and arguments.fragment_dir is not None:
        parser.error("--fragment-dir requires --sparse-checkout")

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
    if arguments.sparse_checkout:
        lock = load_lock(source_lock_path)
        specs = eligible_checkout_specs(
            registry,
            lock,
            name=arguments.name,
            experiment=arguments.experiment,
        )
        fragment_dir = Path(arguments.fragment_dir)
        if not fragment_dir.is_absolute():
            fragment_dir = project_root / fragment_dir
        checkout_root = project_root / "external"
        checkout_impl = checkout_runner or SubprocessCheckoutRunner()
        output = []
        for spec in specs:
            evidence_path = fragment_dir / f"{spec.name}-checkout.json"
            try:
                checkout = checkout_sparse(spec, checkout_root, checkout_impl)
            except SparseCheckoutError as exc:
                failure = CheckoutEvidence.create(
                    registry_sha256=spec.registry_sha256,
                    repository=spec.name,
                    url=spec.url,
                    locked_sha=spec.commit_sha,
                    patterns=spec.patterns,
                    commands=exc.commands,
                    statuses=exc.statuses,
                    download_bytes=exc.download_bytes,
                    disk_bytes=0,
                    outcome="FAIL",
                    blocker=str(exc),
                    content_hashes={},
                )
                write_evidence_create_only(evidence_path, failure)
                raise
            evidence = CheckoutEvidence.create(
                registry_sha256=spec.registry_sha256,
                repository=spec.name,
                url=spec.url,
                locked_sha=spec.commit_sha,
                patterns=checkout.patterns,
                commands=checkout.commands,
                statuses=checkout.statuses,
                download_bytes=checkout.download_bytes,
                disk_bytes=checkout.disk_bytes,
                outcome="PASS",
                blocker=None,
                content_hashes=checkout.content_hashes,
            )
            write_evidence_create_only(evidence_path, evidence)
            output.append(
                {
                    "destination": os.fspath(checkout.destination),
                    "evidence_sha256": evidence.evidence_sha256,
                    "repository": spec.name,
                    "reused": checkout.reused,
                }
            )
        sys.stdout.buffer.write(canonical_json_bytes(output))
        sys.stdout.flush()
        return 0
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
    except (
        SourceFetchError,
        SparseCheckoutError,
        SafetyViolation,
        OSError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
