"""CLI for V3 calibration-only qualification and clean reconstruction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .src.v3_evidence import reconstruct, run_qualification


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("qualify", "reconstruct"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clean-output", type=Path)
    args = parser.parse_args()
    if args.command == "qualify":
        if args.output.name != "hierarchical-recovery-v3-qualification":
            parser.error("qualification output must use the dedicated qualification evidence root")
        result = run_qualification(args.output)
    else:
        if args.clean_output is None:
            parser.error("reconstruct requires --clean-output")
        result = reconstruct(args.output, args.clean_output)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
