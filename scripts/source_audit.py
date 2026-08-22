"""Offline Experiment 00 source-compatibility commands."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import os
from pathlib import Path
import sys

from reflect.safety import SafetyConfig
from reflect.source_compat import (
    CompatibilityEvidence,
    consolidate_compatibility,
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
    parser.add_argument("--operation", choices=[item.value for item in SourceOperation])
    parser.add_argument("--fragment")
    parser.add_argument("--registry", default="references/repos.yaml")
    parser.add_argument("--lock", default="references/repos.lock.yaml")
    parser.add_argument("--manifest", default="experiments/00_source_audit/configs/operation-manifest.yaml")
    parser.add_argument("--fragment-dir", default="experiments/00_source_audit/results/fragments")
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
    manifest = load_operation_manifest(_beneath(root, arguments.manifest, "manifest"), registry, lock, root)
    if arguments.operate:
        if arguments.operation is None or arguments.fragment is None:
            raise ValueError("--operate requires --operation and --fragment")
        sources = {item.name: item for item in registry.repositories}
        locked = {item.name: item for item in lock.entries}
        if arguments.operate not in sources:
            raise ValueError("unknown operation repository")
        source = sources[arguments.operate]
        pin = locked[arguments.operate]
        existing = tuple(path for path in source.selected_paths if pin.path_statuses[path] is PathStatus.EXISTS)
        if not existing:
            raise ValueError("operation repository has no locked existing path")
        evidence = run_source_operation(
            OperationSpec(
                registry.registry_sha256, source.name, pin.commit_sha or "",
                source.experiments[0], existing[0], SourceOperation(arguments.operation),
                pin.license_status.value, pin.license_spdx,
            ),
            _beneath(root, arguments.checkout_root, "checkout root") / source.name,
        )
        destination = _beneath(root, arguments.fragment, "fragment")
        write_fragment_create_only(destination, evidence)
        sys.stdout.buffer.write(evidence.canonical_bytes())
        return 0
    fragment_dir = _beneath(root, arguments.fragment_dir, "fragment directory")
    fragments = []
    if fragment_dir.exists():
        for path in sorted(fragment_dir.glob("*.json")):
            raw = json.loads(path.read_text())
            if raw.get("evidence_type") == "COMPATIBILITY":
                fragments.append(CompatibilityEvidence.from_dict(raw))
    rows = consolidate_compatibility(registry, lock, fragments, manifest.requirement_observations)
    hashes = write_compatibility_outputs(root, registry, lock, rows, check=arguments.check)
    sys.stdout.buffer.write(canonical_json_bytes({"mode": "check" if arguments.check else "write", "outputs": hashes, "rows": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
