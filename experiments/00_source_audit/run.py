"""Canonical Experiment 00 entrypoint."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path

import yaml

from scripts.source_audit import main as source_audit_main


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline Experiment 00 source audit.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output-dir")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-episodes", type=int, default=0)
    parser.add_argument("--headless", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.max_episodes < 0:
        raise ValueError("--max-episodes must be nonnegative")
    raw = yaml.safe_load(Path(arguments.config).read_text())
    required = {"schema_version", "mode", "manifest", "operations"}
    if not isinstance(raw, dict) or set(raw) != required or raw["schema_version"] != 1:
        raise ValueError("Experiment 00 config has an invalid schema")
    summary = {
        "headless": arguments.headless,
        "max_episodes": arguments.max_episodes,
        "operations": raw["operations"],
        "seed": arguments.seed,
    }
    if arguments.dry_run:
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0
    command = [f"--{raw['mode']}", "--manifest", raw["manifest"]]
    return source_audit_main(command)


if __name__ == "__main__":
    raise SystemExit(main())
