"""Frozen runner, publisher, estimator, and reconstructor for Experiment 11."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import itertools
import json
from pathlib import Path
import random
import shutil
import struct
from typing import Any, Iterable, Mapping, Sequence
import zlib

from .kernel import CLAIM_SCOPE, PLANNER_ID, canonical, simulate


ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "configs/trigger-robustness-v1.json"
SEEDS_PATH = ROOT / "configs/seeds-v1.json"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="ascii"))
SEEDS = tuple(json.loads(SEEDS_PATH.read_text(encoding="ascii"))["seeds"])
PLAN_PATH = REPO / "docs/superpowers/plans/2026-08-24-trigger-robustness-dose-response.md"
BASE_CLOSURE = (
    "experiments/11_trigger_robustness/src/__init__.py", "experiments/11_trigger_robustness/src/kernel.py",
    "experiments/11_trigger_robustness/src/scorer.py", "experiments/11_trigger_robustness/src/experiment.py",
    "experiments/11_trigger_robustness/configs/trigger-robustness-v1.json",
    "experiments/11_trigger_robustness/configs/seeds-v1.json", "pyproject.toml", "uv.lock", ".python-version",
    "docs/superpowers/plans/2026-08-24-trigger-robustness-dose-response.md",
)


class IntegrityError(ValueError): pass


def sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def jsonl(rows: Iterable[Mapping[str, Any]]) -> bytes: return b"".join(canonical(row) for row in rows)


def csv_data(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    out = io.StringIO(newline=""); writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n"); writer.writeheader()
    for row in rows: writer.writerow({field:row[field] for field in fields})
    return out.getvalue().encode("ascii")


def quality_by_id(identifier: str) -> dict[str, Any]:
    return next(dict(row) for row in CONFIG["quality_profiles"] if row["id"] == identifier)


def episode_id(cell: Mapping[str, Any]) -> str:
    return "__".join((str(cell[k]) for k in ("storage_variant","trigger_policy","quality_id","disturbance_family","severity"))) + f"__H{cell['horizon']}__{cell['prompt_envelope']}__S{cell['seed']}"


def _matrix(seeds: Sequence[int], *, compact: bool = False) -> tuple[dict[str, Any], ...]:
    qualities = tuple(row["id"] for row in CONFIG["quality_profiles"])
    product = itertools.product(CONFIG["storage_variants"], CONFIG["trigger_policies"], qualities,
                                CONFIG["disturbance_families"], CONFIG["severities"], CONFIG["mission_horizons"], CONFIG["prompt_envelopes"], seeds)
    rows=[]
    for storage, policy, quality, family, severity, horizon, envelope, seed in product:
        cell={"claim_scope":CLAIM_SCOPE,"disturbance_family":family,"horizon":horizon,"planner_id":PLANNER_ID,"prompt_envelope":envelope,
              "quality_id":quality,"seed":seed,"severity":severity,"storage_variant":storage,"trigger_policy":policy}
        cell["episode_id"] = episode_id(cell); rows.append(cell)
    return tuple(rows)


def frozen_matrix() -> tuple[dict[str, Any], ...]: return _matrix(SEEDS)


def fixture_matrix() -> tuple[dict[str, Any], ...]:
    rows=[]
    for storage, policy, quality, family, seed in itertools.product(CONFIG["storage_variants"], CONFIG["trigger_policies"], ("Q00_CLEAN","Q09_HOSTILE"), ("POSE_SHIFT","CONTROL_FAILURE"), CONFIG["calibration_seeds"]):
        cell={"claim_scope":CLAIM_SCOPE,"disturbance_family":family,"horizon":4,"planner_id":PLANNER_ID,"prompt_envelope":"COMPACT_TYPED","quality_id":quality,
              "seed":seed,"severity":"HIGH","storage_variant":storage,"trigger_policy":policy}; cell["episode_id"]=episode_id(cell); rows.append(cell)
    return tuple(rows)


def run_episode(cell: Mapping[str, Any]): return simulate(cell, CONFIG, quality_by_id(str(cell["quality_id"])))


def source_closure() -> tuple[str, ...]: return tuple(sorted(BASE_CLOSURE))


def audit_source_closure(paths: Sequence[str]) -> None:
    given=set(paths)
    if set(BASE_CLOSURE) != given: raise IntegrityError("source/config/seed/environment closure mismatch")
    for relative in given:
        path=REPO/relative
        if not path.is_file(): raise IntegrityError(f"missing closure member {relative}")
    modules={"experiments.11_trigger_robustness.src."+Path(p).stem:p for p in given if p.startswith("experiments/11_trigger_robustness/src/") and p.endswith(".py")}
    for relative in tuple(modules.values()):
        tree=ast.parse((REPO/relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level and node.module:
                target="experiments.11_trigger_robustness.src."+node.module
                if target not in modules: raise IntegrityError(f"unclosed local import {target}")


def freeze_receipt() -> dict[str, Any]:
    closure=source_closure(); audit_source_closure(closure)
    return {"claim_scope":CLAIM_SCOPE,"closure":{p:sha((REPO/p).read_bytes()) for p in closure},"matrix_count":len(frozen_matrix()),
            "matrix_sha256":sha(jsonl(frozen_matrix())),"python":"3.11","schema_version":1}


def _files(root: Path) -> list[Path]: return sorted(path for path in root.rglob("*") if path.is_file() and path.name != "manifest.json")
def tree_hash(root: Path) -> str: return sha(canonical({str(p.relative_to(root)):sha(p.read_bytes()) for p in _files(root)}))


def publish_raw(cells: Sequence[Mapping[str, Any]], root: Path) -> None:
    if root.exists(): raise IntegrityError("create-only raw root exists")
    root.mkdir(parents=True)
    starts=[]; ticks=[]; terminals=[]
    for cell in cells:
        start, episode_ticks, terminal=run_episode(cell); starts.append(start); ticks.extend(episode_ticks); terminals.append(terminal)
    payloads={"cells.jsonl":jsonl(cells),"freeze.json":canonical(freeze_receipt()),"starts.jsonl":jsonl(starts),"terminals.jsonl":jsonl(terminals),"ticks.jsonl":jsonl(ticks)}
    for name,data in payloads.items(): (root/name).write_bytes(data)
    manifest={name:{"bytes":len(data),"sha256":sha(data)} for name,data in payloads.items()}
    (root/"manifest.json").write_bytes(canonical({"files":manifest,"schema_version":1}))


def _read_jsonl(path: Path) -> list[dict[str, Any]]: return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]


def validate_raw(root: Path, *, expected_cells: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    from .scorer import score_episode
    manifest=json.loads((root/"manifest.json").read_text(encoding="ascii")); expected_names=set(manifest["files"])
    actual_names={p.name for p in root.iterdir() if p.is_file() and p.name!="manifest.json"}
    if actual_names != expected_names: raise IntegrityError("raw inventory mismatch")
    for name,receipt in manifest["files"].items():
        data=(root/name).read_bytes()
        if len(data)!=receipt["bytes"] or sha(data)!=receipt["sha256"]: raise IntegrityError("raw manifest mismatch")
    cells=_read_jsonl(root/"cells.jsonl")
    if canonical(cells)!=canonical(list(expected_cells)): raise IntegrityError("matrix identity mismatch")
    starts=_read_jsonl(root/"starts.jsonl"); terminals=_read_jsonl(root/"terminals.jsonl"); tick_rows=_read_jsonl(root/"ticks.jsonl")
    if len(starts)!=len(cells) or len(terminals)!=len(cells): raise IntegrityError("episode inventory mismatch")
    ticks_by={cell["episode_id"]:[] for cell in cells}
    for row in tick_rows:
        if row.get("episode_id") not in ticks_by: raise IntegrityError("unknown tick episode")
        ticks_by[row["episode_id"]].append(row)
    scores=[]
    for cell,start,terminal in zip(cells,starts,terminals,strict=True):
        if start["cell"]!=cell or terminal["episode_id"]!=cell["episode_id"]: raise IntegrityError("ordered episode mismatch")
        scores.append(score_episode(start,ticks_by[cell["episode_id"]],terminal))
    return scores


def reconstruct_raw(source: Path, target: Path) -> None:
    cells=_read_jsonl(source/"cells.jsonl"); publish_raw(cells,target); validate_raw(target,expected_cells=cells)
    if tree_hash(source)!=tree_hash(target): raise IntegrityError("raw reconstruction mismatch")


def cluster_bootstrap(rows: Sequence[Mapping[str, Any]], *, value: str, draws: int, bootstrap_seed: int) -> dict[str, Any]:
    seeds=sorted({int(row["seed"]) for row in rows}); grouped={seed:[float(r[value]) for r in rows if int(r["seed"])==seed] for seed in seeds}; rng=random.Random(bootstrap_seed)
    indices=[]; estimates=[]
    for _ in range(draws):
        draw=[rng.randrange(len(seeds)) for _ in seeds]; indices.append(draw); values=[x for index in draw for x in grouped[seeds[index]]]; estimates.append(sum(values)/len(values))
    ordered=sorted(estimates); lo=ordered[int(.025*draws)]; hi=ordered[min(draws-1,int(.975*draws))]
    return {"ci_high":hi,"ci_low":lo,"draw_cluster_indices":indices,"effective_n":len(seeds),"estimate":sum(estimates)/len(estimates)}


def main(argv: Sequence[str] | None=None) -> int:
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="cmd",required=True)
    run=sub.add_parser("run"); run.add_argument("root",type=Path); run.add_argument("--fixture",action="store_true")
    val=sub.add_parser("validate"); val.add_argument("root",type=Path); val.add_argument("--fixture",action="store_true")
    args=parser.parse_args(argv); cells=fixture_matrix() if args.fixture else frozen_matrix()
    if args.cmd=="run": publish_raw(cells,args.root)
    else: validate_raw(args.root,expected_cells=cells)
    return 0


if __name__ == "__main__": raise SystemExit(main())
