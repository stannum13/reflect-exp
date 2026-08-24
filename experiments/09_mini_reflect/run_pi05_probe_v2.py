"""Publish Exp09 V2 from a pinned local checkout and pre-sanitized observations."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openpi-source", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    backend = importlib.import_module("experiments.09_mini_reflect.src.pi05_backend_v2")
    config_path = Path(__file__).with_name("configs") / "pi05-semantic-probe-v2.json"
    config = json.loads(config_path.read_text(encoding="ascii"))
    if config != {
        "schema_version": 2,
        "study_id": "EXP09_PI05_SEMANTIC_INTERFACE_FEASIBILITY_V2",
        "openpi_commit": backend.PINNED_OPENPI_COMMIT,
        "checkpoint_id": backend.CHECKPOINT_ID,
        "checkpoint_download_allowed": False,
        "network_allowed": False,
        "model_inference_allowed": False,
        "physical_execution_allowed": False,
        "unsupported_disposition": "NOT_RUN",
    }:
        raise backend.ProbeError("V2 config is not exact")
    source = backend.inspect_official_source(args.openpi_source, expected_commit=config["openpi_commit"])
    observations = json.loads(args.observations.read_text(encoding="ascii"))
    backend.publish_probe_v2(args.output, source_root=args.openpi_source, source_receipt=source,
                             observations=observations, forward_receipt=None)
    print((args.output / "derived/summary.json").read_text(encoding="ascii"), end="")


if __name__ == "__main__":
    main()
