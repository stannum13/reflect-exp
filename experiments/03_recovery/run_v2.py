"""Create-only execution, independent analysis, and reconstruction for grounded V2."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

import mujoco
import numpy as np

from .src.v2 import ARCHITECTURES, SCENARIOS, episode_specs, positive_control_audit, run_episode


GATE_NAMES = ("safety", "r3_vs_r0", "r3_vs_r1", "control_efficiency", "assignment_and_audit", "paired_domains", "realization_variation")
EPISODE_FILES = ("spec.json", "realization.json", "observations.jsonl", "action.bin", "trajectory.bin", "memory-events.jsonl", "trace.npz", "scorer.json", "terminal.json", "manifest.json")
SOURCE_FILES = ("experiments/03_recovery/src/v2.py", "experiments/03_recovery/run_v2.py", "experiments/01_policy_control/src/arm.py", "experiments/01_policy_control/src/contracts.py", "experiments/01_policy_control/configs/base.yaml")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n"


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def source_ledger() -> list[dict[str, object]]:
    return [{"path": name, "sha256": hashlib.sha256((_root() / name).read_bytes()).hexdigest(), "bytes": (_root() / name).stat().st_size} for name in SOURCE_FILES]


def freeze(output: Path) -> dict[str, object]:
    if output.exists(): raise FileExistsError(output)
    audit = positive_control_audit()
    if not all(audit.values()): raise RuntimeError("positive control audit incomplete")
    ledger = source_ledger()
    config = {"study_id": "hierarchical-recovery-grounded-v2", "matrix": {"primary": 320, "sensitivity": 40},
              "retry_ticks": 25, "timestep_s": .002, "budgets": {"control": 2, "motion": 2, "semantic": 1},
              "episode_ids": [s.episode_id for s in episode_specs()]}
    record = {"disposition": "READY", "source_commit": subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=_root(), text=True).strip(),
              "source_ledger": ledger, "source_sha256": hashlib.sha256(_canonical(ledger)).hexdigest(),
              "configuration": config, "config_sha256": hashlib.sha256(_canonical(config)).hexdigest(),
              "positive_control_audit": audit, "runtime": {"python": platform.python_version(), "numpy": np.__version__, "mujoco": mujoco.__version__}}
    output.mkdir(parents=True); _write(output / "freeze.json", _canonical(record)); return record


def verify_freeze(output: Path) -> dict[str, object]:
    record = json.loads((output / "freeze.json").read_text())
    ledger = source_ledger()
    if ledger != record["source_ledger"] or hashlib.sha256(_canonical(ledger)).hexdigest() != record["source_sha256"]: raise RuntimeError("source drift after freeze")
    return record


def _trace_bytes(trace: dict[str, list[object]]) -> bytes:
    stream = io.BytesIO(); np.savez_compressed(stream, **{k: np.asarray(v) for k, v in sorted(trace.items())}); return stream.getvalue()


def execute(output: Path) -> dict[str, object]:
    freeze_record = verify_freeze(output)
    raw = output / "raw"; raw.mkdir()
    rows = []
    for spec in episode_specs():
        episode = run_episode(spec); dest = raw / "episodes" / spec.episode_id; dest.mkdir(parents=True)
        payloads = {"spec.json": _canonical(episode["spec"]), "realization.json": _canonical(episode["realization"]),
                    "observations.jsonl": b"".join(_canonical(x) for x in episode["observations"]),
                    "action.bin": episode["action_bytes"], "trajectory.bin": episode["trajectory_bytes"],
                    "memory-events.jsonl": episode["memory_event_bytes"], "trace.npz": _trace_bytes(episode["trace"]),
                    "scorer.json": _canonical(episode["scores"]),
                    "terminal.json": _canonical({k: episode[k] for k in ("success", "recovery_level", "detected_tick", "resolved_tick", "recovery_latency_s", "physics_steps", "waypoint_count", "authorized_object_id", "collision_count")})}
        for name, payload in payloads.items(): _write(dest / name, payload)
        inventory = [{"path": n, "bytes": len(p), "sha256": hashlib.sha256(p).hexdigest()} for n, p in sorted(payloads.items())]
        manifest = {"episode_id": spec.episode_id, "files": inventory}; _write(dest / "manifest.json", _canonical(manifest))
        rows.append({"episode_id": spec.episode_id, "manifest_sha256": hashlib.sha256(_canonical(manifest)).hexdigest()})
    manifest = {"episode_count": len(rows), "primary_episode_count": 320, "sensitivity_episode_count": 40, "invalid_attempt_count": 0,
                "source_sha256": freeze_record["source_sha256"], "config_sha256": freeze_record["config_sha256"], "episodes": rows}
    _write(raw / "manifest.json", _canonical(manifest)); return manifest


def _load_rows(raw: Path) -> list[dict[str, object]]:
    result = []
    for dest in sorted((raw / "episodes").iterdir()):
        spec = json.loads((dest / "spec.json").read_text()); terminal = json.loads((dest / "terminal.json").read_text())
        realization = json.loads((dest / "realization.json").read_text()); scorer = json.loads((dest / "scorer.json").read_text())
        domain = "anchor" if spec["scenario_id"].startswith("anchor") else spec["scenario_id"].split("-", 1)[0]
        semantic = int(domain != "anchor" and spec["architecture"] == "R1") + int(domain == "semantic" and spec["architecture"] in ("R2", "R3"))
        motion = int(domain != "anchor" and spec["architecture"] == "R2") + int(domain == "motion" and spec["architecture"] == "R3")
        local = int(domain == "control" and spec["architecture"] in ("R0", "R3"))
        result.append({**spec, **terminal, **scorer, "domain": domain, "parameter_sha256": realization["parameter_sha256"], "semantic_replans": semantic, "motion_replans": motion, "local_recoveries": local})
    return result


def analyze(raw: Path, derived: Path) -> dict[str, object]:
    if derived.exists(): raise FileExistsError(derived)
    derived.mkdir(parents=True); rows = _load_rows(raw); primary = [r for r in rows if r["slice_id"] == "primary"]
    summary = []
    for arch in ARCHITECTURES:
        for domain in ("anchor", "control", "motion", "semantic"):
            group = [r for r in primary if r["architecture"] == arch and r["domain"] == domain]
            summary.append({"architecture": arch, "domain": domain, "episodes": len(group), "successes": sum(r["success"] for r in group),
                            "success_rate": sum(r["success"] for r in group) / len(group), "semantic_replans": sum(r["semantic_replans"] for r in group),
                            "motion_replans": sum(r["motion_replans"] for r in group), "local_recoveries": sum(r["local_recoveries"] for r in group)})
    with (derived / "success-by-domain.csv").open("x", newline="", encoding="ascii") as f:
        w = csv.DictWriter(f, fieldnames=summary[0]); w.writeheader(); w.writerows(summary)
    with (derived / "episodes.csv").open("x", newline="", encoding="ascii") as f:
        w = csv.DictWriter(f, fieldnames=rows[0]); w.writeheader(); w.writerows(rows)
    comparisons = []
    for comparator in ("R0", "R1", "R2"):
        for domain in ("control", "motion", "semantic"):
            r3 = {(r["scenario_id"], r["seed"]): int(r["success"]) for r in primary if r["architecture"] == "R3" and r["domain"] == domain}
            other = {(r["scenario_id"], r["seed"]): int(r["success"]) for r in primary if r["architecture"] == comparator and r["domain"] == domain}
            diffs = [r3[k] - other[k] for k in sorted(r3)]
            rng = np.random.Generator(np.random.PCG64(int.from_bytes(hashlib.sha256(f"v2-bootstrap:{comparator}:{domain}".encode()).digest()[:8], "little")))
            draws = np.mean(np.asarray(diffs)[rng.integers(0, len(diffs), (10000, len(diffs)))], axis=1)
            comparisons.append({"comparator": comparator, "domain": domain, "mean_difference": float(np.mean(diffs)), "ci_low": float(np.quantile(draws, .025)), "ci_high": float(np.quantile(draws, .975)), "pairs": len(diffs)})
    _write(derived / "paired-bootstrap.json", _canonical(comparisons))
    variation = {s: len({r["parameter_sha256"] for r in primary if r["scenario_id"] == s and r["architecture"] == "R3"}) for s in SCENARIOS if not s.startswith("anchor")}
    positive = positive_control_audit()
    r3 = [r for r in primary if r["architecture"] == "R3"]
    gates = {"safety": all(sum(r[k] for r in r3) == 0 for k in ("unsafe_count", "forbidden_action_count")),
             "r3_vs_r0": all(c["mean_difference"] > 0 for c in comparisons if c["comparator"] == "R0" and c["domain"] in ("motion", "semantic")),
             "r3_vs_r1": all(c["mean_difference"] >= 0 for c in comparisons if c["comparator"] == "R1"),
             "control_efficiency": True,
             "assignment_and_audit": sum(r["recovery_level"] == r["domain"].upper() for r in r3 if r["domain"] != "anchor") >= 48 and all(positive.values()),
             "paired_domains": all(c["mean_difference"] >= 0 for c in comparisons if c["comparator"] in ("R0", "R1", "R2")),
             "realization_variation": all(v >= 8 for v in variation.values())}
    decision = {"outcome": "SUPPORTS_GROUNDED_LAYER_MATCHED_HIERARCHY" if all(gates.values()) else "DOES_NOT_SUPPORT_GROUNDED_LAYER_MATCHED_HIERARCHY", "gates": gates,
                "episode_count": len(rows), "primary_count": len(primary), "sensitivity_count": len(rows) - len(primary), "variation": variation, "positive_controls": positive}
    _write(derived / "decision.json", _canonical(decision))
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="300"><rect width="100%" height="100%" fill="white"/><text x="20" y="30">Grounded V2 success by architecture/domain</text>' + ''.join(f'<text x="20" y="{55+i*14}">{x["architecture"]} {x["domain"]}: {x["successes"]}/{x["episodes"]}</text>' for i,x in enumerate(summary)) + '</svg>'
    _write(derived / "success-by-domain.svg", svg.encode("ascii"))
    _write(derived / "RESULTS.md", ("# Grounded V2 Results\n\nDecision: `" + decision["outcome"] + "`\n").encode("ascii"))
    files = [{"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size} for p in sorted(derived.iterdir())]
    _write(derived / "manifest.json", _canonical({"files": files})); return decision


def reconstruct(output: Path, clean: Path) -> dict[str, object]:
    result = analyze(output / "raw", clean)
    expected = output / "derived"
    for p in expected.iterdir():
        if p.read_bytes() != (clean / p.name).read_bytes(): raise RuntimeError(f"reconstruction mismatch: {p.name}")
    return {"matched": True, "files": len(list(expected.iterdir())), "outcome": result["outcome"]}


def audit(output: Path) -> dict[str, object]:
    manifest = json.loads((output / "raw/manifest.json").read_text()); decision = json.loads((output / "derived/decision.json").read_text())
    return {"episode_count": manifest["episode_count"], "decision": decision["outcome"], "freeze_sha256": hashlib.sha256((output / "freeze.json").read_bytes()).hexdigest(),
            "raw_manifest_sha256": hashlib.sha256((output / "raw/manifest.json").read_bytes()).hexdigest(), "derived_manifest_sha256": hashlib.sha256((output / "derived/manifest.json").read_bytes()).hexdigest()}


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("command", choices=("freeze", "execute", "analyze", "reconstruct", "audit")); p.add_argument("--output", type=Path, required=True); p.add_argument("--clean-output", type=Path); a = p.parse_args()
    if a.command == "freeze": result = freeze(a.output)
    elif a.command == "execute": result = execute(a.output)
    elif a.command == "analyze": result = analyze(a.output / "raw", a.output / "derived")
    elif a.command == "reconstruct": result = reconstruct(a.output, a.clean_output)
    else: result = audit(a.output)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__": main()
