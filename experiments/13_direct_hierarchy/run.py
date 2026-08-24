"""CLI for the frozen Exp13 direct hierarchy outcome."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "execute"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tracked-freeze", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    experiment = importlib.import_module("experiments.13_direct_hierarchy.src.experiment")
    if args.command == "freeze":
        source_commit = subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
        result = experiment.freeze(args.output, source_commit=source_commit, tracked_path=args.tracked_freeze)
        visible = {"status": result["stage"], "source_commit": result["source_commit"], "total": result["configuration"]["total_cells"]}
    else:
        result = experiment.execute(args.output, limit=args.limit)
        visible = result
    print(json.dumps(visible, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
