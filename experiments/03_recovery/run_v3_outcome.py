"""Approval-gated CLI for the frozen V3 held-out outcome matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .src.v3_evidence import publish_durable_archive
from .src.v3_outcome import dry_run_outcomes, reconstruct_outcomes, run_outcomes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("dry-run", "execute", "reconstruct", "archive"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--clean-output", type=Path)
    parser.add_argument("--archive-output", type=Path)
    parser.add_argument("--qualification-root", type=Path, required=True)
    parser.add_argument("--approval-binding", type=Path, required=True)
    parser.add_argument("--approval-report", type=Path, required=True)
    args = parser.parse_args()
    approval = dict(qualification_root=args.qualification_root, approval_binding=args.approval_binding, approval_report=args.approval_report)
    if args.command == "dry-run":
        result = dry_run_outcomes(**approval)
    elif args.output is None:
        parser.error(f"{args.command} requires --output")
    elif args.command == "execute":
        result = run_outcomes(args.output, **approval)
    elif args.command == "reconstruct":
        if args.clean_output is None:
            parser.error("reconstruct requires --clean-output")
        result = reconstruct_outcomes(args.output, args.clean_output, **approval)
    else:
        if args.archive_output is None:
            parser.error("archive requires --archive-output")
        result = publish_durable_archive(args.output, args.archive_output)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
