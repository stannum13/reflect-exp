"""Single fail-closed Experiment 01 command."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from reflect.safety import SafetyConfig, SafetyViolation

from .src.p3_gate import P3GateError, load_p3_gate, require_p3_gate


REPO_ROOT = Path(__file__).resolve().parents[2]
_SUCCESSFUL_SHARD_RESULTS = frozenset({
    "published", "validated-and-skipped", "declared-invalid",
})
_RESOURCE_SHARD_RESULTS = frozenset({"resource-exhausted"})
_SHARD_DISPOSITION_RESULTS = frozenset({"CONTINUE", "TERMINAL_STOPPED"})
_STAGE_DISPOSITION_RESULTS = frozenset({"ADVANCE", "TERMINAL_STOPPED"})


def _contained(path: str | Path, *, must_exist: bool) -> Path:
    value = Path(path)
    if not value.is_absolute():
        value = REPO_ROOT / value
    resolved = value.resolve(strict=must_exist)
    if not resolved.is_relative_to(REPO_ROOT):
        raise ValueError("Experiment 01 paths must remain under the repository root")
    return resolved


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m experiments.01_policy_control.run")
    parser.add_argument("--config", required=True)
    parser.add_argument("--p3-gate", required=True)
    parser.add_argument("--phase", choices=("pilot", "freeze", "confirmation", "analyze", "report"), required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--shard-id")
    parser.add_argument("--list-shards", action="store_true")
    parser.add_argument("--shard-disposition")
    parser.add_argument("--stage-disposition", action="store_true")
    parser.add_argument("--stage", choices=("revision", "base", "pd_60_6", "pd_100_10", "ik_0_001", "ik_0_05", "p5_0_01", "p5_0_04", "final_four"))
    parser.add_argument("--prepare-manifest")
    parser.add_argument("--bind-preregistration")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--max-episodes", type=int)
    parser.add_argument("--_worker-capability-fd", type=int, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        safety = SafetyConfig.from_mapping(os.environ)
        safety.require_simulation_only()
        if safety.remote_enabled:
            raise SafetyViolation("Experiment 01 forbids remote execution")
        config_path = _contained(args.config, must_exist=True)
        gate_path = _contained(args.p3_gate, must_exist=True)
        output_dir = _contained(args.output_dir, must_exist=False)
        manifest_path = _contained(args.manifest, must_exist=True) if args.manifest else None
        prepare_path = _contained(args.prepare_manifest, must_exist=False) if args.prepare_manifest else None
        binding_path = _contained(args.bind_preregistration, must_exist=False) if args.bind_preregistration else None
        require_p3_gate(REPO_ROOT, load_p3_gate(gate_path))
    except (SafetyViolation, P3GateError, OSError, ValueError):
        return 2
    if not args.headless:
        return 2
    modes = (args.shard_id is not None, args.list_shards, args.shard_disposition is not None, args.stage_disposition, args.preflight)
    if sum(modes) > 1 or (args.prepare_manifest and any(modes)) or (args.bind_preregistration and any(modes)):
        return 1
    if args.max_episodes is not None and (type(args.max_episodes) is not int or args.max_episodes <= 0):
        return 1
    if args._worker_capability_fd is not None:
        return 2

    if args.dry_run:
        payload = {
            "bind_preregistration": str(binding_path.relative_to(REPO_ROOT)) if binding_path else None,
            "headless": True,
            "manifest": str(manifest_path.relative_to(REPO_ROOT)) if manifest_path else None,
            "max_episodes": args.max_episodes,
            "output_dir": str(output_dir.relative_to(REPO_ROOT)),
            "phase": args.phase,
            "prepare_manifest": str(prepare_path.relative_to(REPO_ROOT)) if prepare_path else None,
            "shard_id": args.shard_id,
            "stage": args.stage,
        }
        sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        return 0

    from .src import artifacts

    try:
        if args.list_shards:
            if manifest_path is None:
                return 1
            shards = tuple(artifacts.iter_manifest(manifest_path))
            if args.max_episodes is not None:
                shards = tuple(item for item in shards if item.episode_count == args.max_episodes)
            for item in shards:
                print(item.shard_id)
            return 0
        if args.preflight:
            from .src.contracts import load_config

            cfg = load_config(config_path)
            stats = os.statvfs(output_dir.parent)
            free_bytes = stats.f_bavail * stats.f_frsize
            disposition = artifacts.preflight_resources(
                args.phase,
                retained_bytes=0,
                temp_bytes=0,
                quarantine_bytes=0,
                free_bytes=free_bytes,
                wall_seconds=0,
                cpu_seconds=0,
                config=cfg,
            )
            print(disposition.to_json())
            return 0 if disposition.disposition == "ALLOW" else 3
        if prepare_path is not None:
            if args.stage is None:
                return 1
            artifacts.prepare_manifest(args.stage, manifest_path, prepare_path, config_path, gate_path)
            return 0
        if binding_path is not None:
            if args.phase != "confirmation" or manifest_path is None:
                return 1
            artifacts.bind_preregistration(manifest_path, binding_path)
            return 0
        if args.shard_id is not None:
            if manifest_path is None or args.max_episodes is None:
                return 1
            resource_output, prior_artifacts, confirmation_wave = artifacts.resource_execution_context(
                manifest_path, output_dir, args.shard_id,
            )
            result = artifacts.run_supervised_shard(
                manifest_path, args.shard_id, resource_output, config_path, gate_path,
                args.max_episodes, repo_root=REPO_ROOT,
                prior_artifacts=prior_artifacts, confirmation_wave=confirmation_wave,
            )
            if result in _SUCCESSFUL_SHARD_RESULTS:
                return 0
            if result in _RESOURCE_SHARD_RESULTS:
                return 3
            raise artifacts.ArtifactError("supervisor returned an unknown disposition")
        if args.shard_disposition is not None:
            if args.phase != "pilot" or manifest_path is None:
                return 1
            resource_output, prior_artifacts, confirmation_wave = artifacts.resource_execution_context(
                manifest_path, output_dir, args.shard_disposition,
            )
            result = artifacts.publish_shard_disposition(
                manifest_path, args.shard_disposition, resource_output,
                prior_artifacts=prior_artifacts, confirmation_wave=confirmation_wave,
            )
            if result not in _SHARD_DISPOSITION_RESULTS:
                raise artifacts.ArtifactError("shard disposition returned an unknown status")
            print(result)
            return 0
        if args.stage_disposition:
            if args.phase != "pilot" or manifest_path is None:
                return 1
            resource_output, prior_artifacts, confirmation_wave = artifacts.resource_execution_context(
                manifest_path, output_dir,
            )
            result = artifacts.publish_stage_disposition(
                manifest_path, resource_output, prior_artifacts=prior_artifacts,
                confirmation_wave=confirmation_wave,
            )
            if result not in _STAGE_DISPOSITION_RESULTS:
                raise artifacts.ArtifactError("stage disposition returned an unknown status")
            print(result)
            return 0
        if args.phase == "freeze":
            return artifacts.freeze_protocol(manifest_path, output_dir, config_path)
        if args.phase == "analyze":
            return artifacts.analyze_phase(manifest_path, output_dir)
        if args.phase == "report":
            return artifacts.write_report(manifest_path, output_dir)
        return 1
    except artifacts.ImplementationDriftError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError, artifacts.ArtifactError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
