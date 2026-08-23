#!/usr/bin/env python3
"""Reconstruct authenticated Experiment 04 derived evidence from raw rows."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=Path(__file__).parent / "raw")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    module = importlib.import_module("experiments.04_memory.src.unfixed_ablation")
    module.reconstruct(arguments.raw, arguments.output)


if __name__ == "__main__":
    main()
