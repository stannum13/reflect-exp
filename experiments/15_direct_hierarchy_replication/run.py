"""CLI for the frozen Exp15 direct hierarchy outcome."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "preflight", "execute", "release-first50"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tracked-freeze", type=Path)
    parser.add_argument("--source-approval", type=Path)
    parser.add_argument("--first50-approval", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    experiment = importlib.import_module("experiments.15_direct_hierarchy_replication.src.experiment")
    if args.command == "freeze":
        source_commit = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
        result = experiment.freeze(
            args.output, source_commit=source_commit, tracked_path=args.tracked_freeze,
            source_approval=args.source_approval,
        )
        visible = {"status": result["stage"], "source_commit": result["source_commit"], "total": result["configuration"]["total_cells"]}
    elif args.command == "preflight":
        result = experiment.preflight(args.output)
        visible = result
    elif args.command == "release-first50":
        if args.first50_approval is None:
            parser.error("release-first50 requires --first50-approval")
        result = experiment.release_first50(args.output, args.first50_approval)
        visible = result
    else:
        result = experiment.execute(args.output, limit=args.limit)
        visible = result
    print(json.dumps(visible, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
