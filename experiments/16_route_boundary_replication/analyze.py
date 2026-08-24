"""Run post-outcome Exp16 analysis without changing the frozen runner closure."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    analysis = importlib.import_module("experiments.16_route_boundary_replication.src.analysis")
    result = analysis.analyze(args.output)
    print(json.dumps({"status": result["reconstruction"], "dispositions": result["dispositions"]}, sort_keys=True))


if __name__ == "__main__":
    main()
