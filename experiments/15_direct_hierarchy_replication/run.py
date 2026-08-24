"""CLI for the frozen Exp15 direct hierarchy outcome."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "preflight", "execute", "release-first50"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tracked-freeze", type=Path)
    parser.add_argument("--source-approval-ref")
    parser.add_argument("--source-commit")
    parser.add_argument("--first50-approval-ref")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    experiment = importlib.import_module("experiments.15_direct_hierarchy_replication.src.experiment")
    if args.command == "freeze":
        if args.source_commit is None or args.source_approval_ref is None:
            parser.error("freeze requires --source-commit and --source-approval-ref")
        result = experiment.freeze(
            args.output, source_commit=args.source_commit, tracked_path=args.tracked_freeze,
            source_approval_ref=args.source_approval_ref,
        )
        visible = {"status": result["stage"], "source_commit": result["source_commit"], "total": result["configuration"]["total_cells"]}
    elif args.command == "preflight":
        result = experiment.preflight(args.output)
        visible = result
    elif args.command == "release-first50":
        if args.first50_approval_ref is None:
            parser.error("release-first50 requires --first50-approval-ref")
        result = experiment.release_first50(args.output, args.first50_approval_ref)
        visible = result
    else:
        result = experiment.execute(args.output, limit=args.limit)
        visible = result
    print(json.dumps(visible, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
