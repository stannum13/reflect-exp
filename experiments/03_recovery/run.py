"""CLI for freezing, executing, merging, reconstructing, and auditing Experiment 03."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .src.analyze import analyze
from .src.evidence import SHARD_IDS, freeze, merge_shards, reconstruct, run_shard


def audit(output: Path) -> dict[str, object]:
    raw = output / "raw"
    decision = json.loads((output / "derived/decision.json").read_text(encoding="ascii"))
    manifest = json.loads((raw / "manifest.json").read_text(encoding="ascii"))
    cause_boundary_violations = []
    for item in manifest["episodes"]:
        root = raw / "episodes" / item["episode_id"]
        payload = (root / "recovery-decisions.jsonl").read_bytes().lower()
        if b"cause" in payload or b"scenario" in payload:
            cause_boundary_violations.append(item["episode_id"])
    draws = (output / "derived/bootstrap-draws.jsonl").read_text(encoding="ascii").splitlines()
    draw_rows = [json.loads(line) for line in draws]
    expected_draws = 9 * 10_000
    draw_seeds = [int(item["draw_seed"]) for item in draw_rows]
    result = {
        "decision": decision["outcome"],
        "episode_count": manifest["episode_count"],
        "primary_episode_count": manifest["primary_episode_count"],
        "sensitivity_episode_count": manifest["sensitivity_episode_count"],
        "invalid_attempt_count": manifest["invalid_attempt_count"],
        "cause_boundary_violations": cause_boundary_violations,
        "bootstrap_draw_rows": len(draw_rows),
        "bootstrap_draw_seeds_unique": len(draw_seeds) == len(set(draw_seeds)),
        "bootstrap_complete": len(draw_rows) == expected_draws,
        "raw_manifest_sha256": hashlib.sha256((raw / "manifest.json").read_bytes()).hexdigest(),
        "derived_manifest_sha256": hashlib.sha256((output / "derived/manifest.json").read_bytes()).hexdigest(),
    }
    if cause_boundary_violations or not result["bootstrap_complete"] or not result["bootstrap_draw_seeds_unique"]:
        raise RuntimeError("independent evidence audit failed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "shard", "merge", "reconstruct", "audit"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shard-id", choices=SHARD_IDS)
    parser.add_argument("--clean-output", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze(args.output)
    elif args.command == "shard":
        if args.shard_id is None:
            parser.error("shard requires --shard-id")
        result = run_shard(args.output, args.shard_id)
    elif args.command == "merge":
        raw = merge_shards(args.output, tuple(args.output / "shards" / item for item in SHARD_IDS))
        result = analyze(raw, args.output / "derived")
    elif args.command == "reconstruct":
        if args.clean_output is None:
            parser.error("reconstruct requires --clean-output")
        result = reconstruct(args.output / "raw", args.clean_output)
    else:
        result = audit(args.output)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
