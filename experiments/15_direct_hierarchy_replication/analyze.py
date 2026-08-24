"""Run post-outcome Exp15 analysis without changing the frozen runner closure."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analysis = importlib.import_module("experiments.15_direct_hierarchy_replication.src.analysis")
    result = analysis.analyze(args.output)
    print(json.dumps({"status": result["reconstruction"], "dispositions": result["dispositions"]}, sort_keys=True))


if __name__ == "__main__":
    main()
