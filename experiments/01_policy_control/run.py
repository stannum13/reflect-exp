"""Single fail-closed Experiment 01 command."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from reflect.safety import SafetyConfig, SafetyViolation

from .src.p3_gate import P3GateError, load_p3_gate, require_p3_gate


REPO_ROOT = Path(__file__).resolve().parents[2]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--p3-gate", required=True)
    parser.add_argument("--phase", choices=("pilot", "freeze", "confirmation", "analyze", "report"), required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args, _ = parser.parse_known_args(argv)
    try:
        safety = SafetyConfig.from_mapping(os.environ)
        safety.require_simulation_only()
        if safety.remote_enabled:
            raise SafetyViolation("Experiment 01 forbids remote execution")
        require_p3_gate(REPO_ROOT, load_p3_gate(args.p3_gate))
    except (SafetyViolation, P3GateError, OSError, ValueError):
        return 2
    if not args.headless:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
