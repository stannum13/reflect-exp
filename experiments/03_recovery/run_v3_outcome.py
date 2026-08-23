"""Approval-gated CLI for the frozen V3 held-out outcome matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .src.v3_outcome import run_outcomes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("execute", choices=("execute",))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--approval-binding", type=Path, required=True)
    parser.add_argument("--approval-report", type=Path, required=True)
    args = parser.parse_args()
    result = run_outcomes(
        args.output,
        qualification_root=args.qualification_root,
        approval_binding=args.approval_binding,
        approval_report=args.approval_report,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
