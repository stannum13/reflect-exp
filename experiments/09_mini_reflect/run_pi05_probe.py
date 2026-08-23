"""Collect and publish the authentic OpenPI pi0.5 feasibility probe."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openpi-source", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--checkpoint-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    backend = importlib.import_module("experiments.09_mini_reflect.src.pi05_backend")
    config_path = Path(__file__).with_name("configs") / "pi05-semantic-probe.json"
    config = json.loads(config_path.read_text(encoding="ascii"))
    if config["openpi_commit"] != backend.PINNED_OPENPI_COMMIT:
        raise backend.ProbeError("config and implementation OpenPI commits differ")
    if config["checkpoint_uri"] != backend.CHECKPOINT_URI:
        raise backend.ProbeError("config and implementation checkpoint URIs differ")
    if config["checkpoint_download_allowed"] or config["model_substitution_allowed"]:
        raise backend.ProbeError("unsafe feasibility config")
    source = backend.inspect_official_source(
        args.openpi_source, expected_commit=config["openpi_commit"]
    )
    observations = backend.collect_observations(
        args.openpi_source,
        python_executable=args.python,
        checkpoint_cache=args.checkpoint_cache,
        environ=dict(os.environ),
    )
    smoke = backend.run_official_base_policy_smoke(args.openpi_source)
    backend.publish_probe(
        args.output,
        source_finding=source,
        observations=observations,
        api_smoke=smoke,
    )
    print((args.output / "derived" / "summary.json").read_text(encoding="ascii"), end="")


if __name__ == "__main__":
    main()
