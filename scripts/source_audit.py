"""Offline Experiment 00 source-compatibility commands."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import importlib
import os
from pathlib import Path
import sys

from reflect.safety import SafetyConfig
from reflect.source_compat import (
    consolidate_compatibility,
    load_manifest_fragments,
    load_operation_manifest,
    write_compatibility_outputs,
)
from reflect.source_evidence import canonical_json_bytes
from reflect.source_ops import OperationSpec, SourceOperation, run_source_operation, write_fragment_create_only
from reflect.sources import PathStatus, load_lock, load_registry


ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or generate offline source-compatibility evidence.")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--write", action="store_true")
    modes.add_argument("--operate")
    parser.add_argument("--registry", default="references/repos.yaml")
    parser.add_argument("--lock", default="references/repos.lock.yaml")
    parser.add_argument("--manifest", default="experiments/00_source_audit/configs/operation-manifest.yaml")
    parser.add_argument("--checkout-root", default="external")
    parser.add_argument("--root", default=os.fspath(ROOT))
    return parser


def _beneath(root: Path, value: str, field: str) -> Path:
    path = Path(value)
    candidate = path if path.is_absolute() else root / path
    resolved_parent = candidate.parent.resolve(strict=False)
    try:
        resolved_parent.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{field} escapes project root") from exc
    return candidate


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    SafetyConfig.from_mapping(os.environ).require_simulation_only()
    root = Path(arguments.root).resolve()
    registry = load_registry(_beneath(root, arguments.registry, "registry"))
    lock = load_lock(_beneath(root, arguments.lock, "lock"))
    manifest_path = _beneath(root, arguments.manifest, "manifest")
    manifest = load_operation_manifest(manifest_path, registry, lock, root)
    if arguments.operate:
        matches = tuple(item for item in manifest.operations if item.operation_id == arguments.operate)
        if len(matches) != 1:
            raise ValueError("--operate requires one exact manifest operation ID")
        operation = matches[0]
        if operation.operation == "PACKAGE_RUNTIME":
            smoke = importlib.import_module("experiments.00_source_audit.src.smoke")
            destination = smoke.write_mujoco_smoke(manifest_path, registry, lock, root)
            sys.stdout.buffer.write(destination.read_bytes())
            return 0
        if operation.operation not in {item.value for item in SourceOperation}:
            raise ValueError("--operate supports only bounded static manifest operations")
        sources = {item.name: item for item in registry.repositories}
        locked = {item.name: item for item in lock.entries}
        source = sources[operation.repository]
        pin = locked[operation.repository]
        if pin.path_statuses[operation.selected_path] is not PathStatus.EXISTS:
            raise ValueError("operation selected path is not locked existing")
        _, checkouts, seen = load_manifest_fragments(root, manifest, registry, lock)
        checkout = next((item for item in checkouts if item.repository == source.name), None)
        if checkout is None or checkout.outcome != "PASS" or not any(entry.operation == "CHECKOUT" and entry.repository == source.name and entry.operation_id in seen for entry in manifest.operations):
            raise ValueError("operation requires its exact manifest-declared PASS checkout receipt")
        evidence = run_source_operation(
            OperationSpec(
                registry.registry_sha256, source.name, pin.commit_sha or "",
                operation.experiment, operation.selected_path, operation.operation_id,
                SourceOperation(operation.operation), pin.license_status.value,
                pin.license_spdx, operation.platform, operation.python_requirement,
                operation.compiler_or_runtime, operation.timeout_seconds,
                operation.download_ceiling_bytes, operation.disk_ceiling_bytes,
                operation.file_ceiling_bytes, operation.file_count_ceiling,
                operation.depth_ceiling, operation.no_copy, operation.no_models,
            ),
            _beneath(root, arguments.checkout_root, "checkout root") / source.name,
        )
        destination = _beneath(root, operation.relative_output, "fragment")
        write_fragment_create_only(destination, evidence)
        sys.stdout.buffer.write(evidence.canonical_bytes())
        return 0
    fragments, checkouts, seen = load_manifest_fragments(root, manifest, registry, lock)
    rows = consolidate_compatibility(
        registry, lock, fragments, manifest.requirement_observations, manifest, checkouts
    )
    hashes = write_compatibility_outputs(
        root, registry, lock, rows, check=arguments.check,
        manifest=manifest, seen_operation_ids=seen,
        checkouts=checkouts,
    )
    sys.stdout.buffer.write(canonical_json_bytes({"mode": "check" if arguments.check else "write", "outputs": hashes, "rows": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
