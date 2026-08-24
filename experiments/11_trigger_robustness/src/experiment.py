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
    "experiments/11_trigger_robustness/configs/retired-seed-namespaces.json",
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


METRICS = ("completion","progress","retries","wakes","false_wakes","late_wakes","wasted_wakes","thrash","trigger_precision","trigger_recall","cost_proxy","storage_reads","storage_writes","storage_bytes","storage_age","escalation_event","escalation_failure")


def _mean(values: Sequence[float]) -> float: return sum(values)/len(values)


def _aggregate(cells: Sequence[Mapping[str, Any]], scores: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any,...],list[tuple[Mapping[str,Any],Mapping[str,Any]]]]={}
    for cell,score in zip(cells,scores,strict=True): groups.setdefault(tuple(cell[k] for k in keys),[]).append((cell,score))
    rows=[]
    for identity,members in sorted(groups.items()):
        row={key:value for key,value in zip(keys,identity,strict=True)}; row["n"]=len(members)
        for metric in METRICS: row[metric]=round(_mean([float(score[metric]) for _,score in members]),6)
        rows.append(row)
    return rows


def _svg(graph: Sequence[Mapping[str, Any]]) -> bytes:
    width,height=900,520; left,top,right,bottom=75,35,25,70; plot_w=width-left-right; plot_h=height-top-bottom
    colors={"PERIODIC_ONLY":"#0072B2","FAILURE_THRESHOLD":"#D55E00","EVENT_DRIVEN":"#009E73","HYBRID":"#CC79A7"}
    policies=tuple(policy for policy in CONFIG["trigger_policies"] if any(r["trigger_policy"]==policy for r in graph)); qids=[q["id"] for q in CONFIG["quality_profiles"] if any(r["quality_id"]==q["id"] for r in graph)]
    pieces=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="#ffffff"/>',
            '<text x="450" y="20" text-anchor="middle" font-family="sans-serif" font-size="16">Exp11 completion dose response (synthetic oracle, not VLA)</text>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="#222"/><line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#222"/>']
    for index,qid in enumerate(qids):
        x=left+index*plot_w/max(1,len(qids)-1); pieces.append(f'<text x="{x:.2f}" y="{top+plot_h+18}" transform="rotate(35 {x:.2f} {top+plot_h+18})" font-family="sans-serif" font-size="9">{qid}</text>')
    for p_index,policy in enumerate(policies):
        values=[]
        for qid in qids:
            matched=[float(r["completion"]) for r in graph if r["trigger_policy"]==policy and r["quality_id"]==qid]
            values.append(_mean(matched))
        points=" ".join(f"{left+i*plot_w/max(1,len(qids)-1):.2f},{top+(1-v)*plot_h:.2f}" for i,v in enumerate(values))
        pieces.append(f'<polyline points="{points}" fill="none" stroke="{colors[policy]}" stroke-width="3"/>')
        pieces.append(f'<text x="{left+10}" y="{top+18+p_index*18}" font-family="sans-serif" font-size="12" fill="{colors[policy]}">{policy}</text>')
    pieces.append('</svg>')
    return ("".join(pieces)+"\n").encode("ascii")


def _png(graph: Sequence[Mapping[str, Any]]) -> bytes:
    width,height=900,520; pixels=bytearray([255]*(width*height*3)); colors=((0,114,178),(213,94,0),(0,158,115),(204,121,167)); qids=[q["id"] for q in CONFIG["quality_profiles"] if any(r["quality_id"]==q["id"] for r in graph)]
    def dot(x:int,y:int,color:tuple[int,int,int]):
        for yy in range(max(0,y-3),min(height,y+4)):
            for xx in range(max(0,x-3),min(width,x+4)): pixels[(yy*width+xx)*3:(yy*width+xx)*3+3]=bytes(color)
    for p_index,policy in enumerate(CONFIG["trigger_policies"]):
        for i,qid in enumerate(qids):
            values=[float(r["completion"]) for r in graph if r["trigger_policy"]==policy and r["quality_id"]==qid]
            if values: dot(75+round(i*800/max(1,len(qids)-1)),35+round((1-_mean(values))*415),colors[p_index])
    raw=b"".join(b"\x00"+bytes(pixels[y*width*3:(y+1)*width*3]) for y in range(height))
    def chunk(kind:bytes,data:bytes)->bytes: return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(raw,9))+chunk(b"IEND",b"")


def derive(raw: Path, derived: Path) -> None:
    if derived.exists(): raise IntegrityError("create-only derived root exists")
    cells=_read_jsonl(raw/"cells.jsonl"); scores=validate_raw(raw,expected_cells=cells); derived.mkdir(parents=True)
    episode_rows=[{**cell,**score} for cell,score in zip(cells,scores,strict=True)]
    episode_fields=tuple(cells[0])+tuple(k for k in scores[0] if k not in cells[0])
    cell_keys=("storage_variant","trigger_policy","quality_id","disturbance_family","severity","horizon","prompt_envelope")
    cell_rows=_aggregate(cells,scores,cell_keys); dose_rows=_aggregate(cells,scores,("storage_variant","trigger_policy","quality_id")); hetero_rows=_aggregate(cells,scores,("trigger_policy","quality_id","disturbance_family","severity","horizon"))
    dose_fields=tuple(dose_rows[0]); cell_fields=tuple(cell_rows[0]); hetero_fields=tuple(hetero_rows[0])
    bootstrap=[]
    observed=sorted({(str(r["storage_variant"]),str(r["trigger_policy"]),str(r["quality_id"])) for r in episode_rows})
    for storage,policy,qid in observed:
        members=[row for row in episode_rows if row["storage_variant"]==storage and row["trigger_policy"]==policy and row["quality_id"]==qid]
        result=cluster_bootstrap(members,value="completion",draws=int(CONFIG["bootstrap_draws"]),bootstrap_seed=int(CONFIG["bootstrap_seed"])+len(bootstrap))
        bootstrap.append({"storage_variant":storage,"trigger_policy":policy,"quality_id":qid,"effective_n":result["effective_n"],"estimate":round(result["estimate"],6),"ci_low":round(result["ci_low"],6),"ci_high":round(result["ci_high"],6),"draw_indices_sha256":sha(canonical(result["draw_cluster_indices"]))})
    slopes=[]
    for storage,policy in sorted({(str(r["storage_variant"]),str(r["trigger_policy"])) for r in dose_rows}):
        ordered_qids=[q["id"] for q in CONFIG["quality_profiles"] if any(r["storage_variant"]==storage and r["trigger_policy"]==policy and r["quality_id"]==q["id"] for r in dose_rows)]
        vals=[next(float(r["completion"]) for r in dose_rows if r["storage_variant"]==storage and r["trigger_policy"]==policy and r["quality_id"]==qid) for qid in ordered_qids]
        drops=[vals[i+1]-vals[i] for i in range(len(vals)-1)]; cliff=min(range(len(drops)),key=lambda i:drops[i])
        slopes.append({"storage_variant":storage,"trigger_policy":policy,"clean_to_hostile_slope":round((vals[-1]-vals[0])/max(1,len(vals)-1),6),"largest_adjacent_drop":round(drops[cliff],6),"cliff_after_quality":ordered_qids[cliff]})
    working=max(episode_rows,key=lambda r:(r["completion"],r["progress"],-r["cost_proxy"])); nonworking=min(episode_rows,key=lambda r:(r["completion"],r["progress"],-r["retries"]))
    payloads={
        "episodes.csv":csv_data(episode_rows,episode_fields),"cell-summary.csv":csv_data(cell_rows,cell_fields),"dose-response.csv":csv_data(dose_rows,dose_fields),
        "heterogeneity.csv":csv_data(hetero_rows,hetero_fields),"bootstrap.csv":csv_data(bootstrap,tuple(bootstrap[0])),"slopes-cliffs.csv":csv_data(slopes,tuple(slopes[0])),
        "examples.json":canonical({"nonworking":nonworking,"working":working}),"graph-table.csv":csv_data(dose_rows,dose_fields),"dose-response.svg":_svg(dose_rows),"dose-response.png":_png(dose_rows),
        "plot-style.json":canonical({"background":"#ffffff","colors":{"PERIODIC_ONLY":"#0072B2","FAILURE_THRESHOLD":"#D55E00","EVENT_DRIVEN":"#009E73","HYBRID":"#CC79A7"},"renderer":"STDLIB_ZLIB_DATA_POINTS_V1","theme_independent":True})}
    best=max(dose_rows,key=lambda r:r["completion"]); worst=min(dose_rows,key=lambda r:r["completion"])
    report=("# Experiment 11 Trigger Robustness Dose Response\n\n"
            f"Scope: `{CLAIM_SCOPE}`. The planner is deterministic and typed; these are not VLA results.\n\n"
            f"Validated episodes: {len(cells):,}; exact raw ticks: {sum(s['tick_count'] for s in scores):,}; paired seed clusters: {len(SEEDS)}.\n\n"
            f"Best storage x trigger x quality completion: {best['storage_variant']} x {best['trigger_policy']} x {best['quality_id']} = {best['completion']:.3f}. "
            f"Worst: {worst['storage_variant']} x {worst['trigger_policy']} x {worst['quality_id']} = {worst['completion']:.3f}.\n\n"
            "See `bootstrap.csv` for seed-cluster 95% intervals, `heterogeneity.csv` for family/severity/horizon effects, and `slopes-cliffs.csv` for degradation and cliff locations.\n")
    payloads["RESULT.md"]=report.encode("ascii")
    for name,data in payloads.items(): (derived/name).write_bytes(data)
    manifest={name:{"bytes":len(data),"sha256":sha(data)} for name,data in payloads.items()}; (derived/"manifest.json").write_bytes(canonical({"files":manifest,"raw_tree_sha256":tree_hash(raw),"schema_version":1}))


def validate_derived(raw: Path, derived: Path) -> None:
    manifest=json.loads((derived/"manifest.json").read_text(encoding="ascii"))
    if manifest["raw_tree_sha256"]!=tree_hash(raw): raise IntegrityError("derived/raw binding mismatch")
    actual={p.name for p in derived.iterdir() if p.is_file() and p.name!="manifest.json"}
    if actual!=set(manifest["files"]): raise IntegrityError("derived inventory mismatch")
    for name,receipt in manifest["files"].items():
        data=(derived/name).read_bytes()
        if len(data)!=receipt["bytes"] or sha(data)!=receipt["sha256"]: raise IntegrityError("derived manifest mismatch")


def reconstruct_all(source: Path, target: Path) -> None:
    reconstruct_raw(source/"raw",target/"raw"); derive(target/"raw",target/"derived"); validate_derived(target/"raw",target/"derived")
    if tree_hash(source)!=tree_hash(target): raise IntegrityError("full reconstruction mismatch")


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
    full=sub.add_parser("full"); full.add_argument("root",type=Path)
    rec=sub.add_parser("reconstruct"); rec.add_argument("source",type=Path); rec.add_argument("target",type=Path)
    args=parser.parse_args(argv); cells=fixture_matrix() if getattr(args,"fixture",False) else frozen_matrix()
    if args.cmd=="run": publish_raw(cells,args.root)
    elif args.cmd=="validate": validate_raw(args.root,expected_cells=cells)
    elif args.cmd=="full":
        args.root.mkdir(parents=True); publish_raw(cells,args.root/"raw"); derive(args.root/"raw",args.root/"derived"); validate_derived(args.root/"raw",args.root/"derived")
    else: reconstruct_all(args.source,args.target)
    return 0


if __name__ == "__main__": raise SystemExit(main())
