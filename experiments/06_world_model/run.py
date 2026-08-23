"""Create and reconstruct the bounded Experiment 06 engineering evidence."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
from typing import Iterable, Sequence

import mujoco
import numpy as np

from . import model, world


SOURCE_PATHS = (
    Path("experiments/06_world_model/config.json"),
    Path("experiments/06_world_model/world.py"),
    Path("experiments/06_world_model/model.py"),
    Path("experiments/06_world_model/run.py"),
)


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())


def _json_lines(rows: Iterable[object]) -> bytes:
    return b"".join(world.canonical(row) for row in rows)


def _hash_file(path: Path) -> dict[str, object]:
    payload=path.read_bytes();return {"path":path.as_posix(),"bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest()}


def _source_ledger() -> list[dict[str, object]]:
    return [_hash_file(path) for path in SOURCE_PATHS]


def _save_actions(path: Path, actions: np.ndarray) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as stream:
        np.lib.format.write_array(stream,np.asarray(actions,dtype="<f8"),allow_pickle=False);stream.flush();os.fsync(stream.fileno())


def _raw_dataset(raw: Path) -> tuple[model.DatasetRow,...]:
    candidates=[json.loads(line) for line in (raw/"candidates.jsonl").read_text().splitlines()]
    truth={row["candidate_id"]:row for row in (json.loads(line) for line in (raw/"truth.jsonl").read_text().splitlines())}
    actions=np.load(raw/"actions.npy",allow_pickle=False)
    rows=[]
    for item in candidates:
        outcome=truth[item["candidate_id"]]
        rows.append(model.DatasetRow(item["partition"],item["stratum"],item["scene_id"],item["anchor_id"],item["candidate_id"],item["strategy_id"],tuple(item["state_features"]),np.asarray(actions[item["action_index"]],dtype="<f8"),item["action_sha256"],tuple(outcome["terminal_state"]),outcome["position_error_m"],outcome["orientation_error_rad"],outcome["collision"],outcome["action_energy"],outcome["unsafe"],outcome["success"],outcome["terminal_failure"],outcome["actual_cost"],outcome["outcome_sha256"]))
    return tuple(rows)


def _derive(raw: Path, output: Path) -> None:
    output.mkdir(parents=True)
    rows=_raw_dataset(raw);training=tuple(x for x in rows if x.partition=="train");tuning=tuple(x for x in rows if x.partition=="tuning");evaluation=tuple(x for x in rows if x.partition=="evaluation")
    fitted=model.fit_models(training,tuning);predictions=model.predict_all(fitted,evaluation);selections=model.rank_selectors(predictions,evaluation);metrics=model.aggregate_metrics(selections,predictions,evaluation)
    _write(output/"models.json",world.canonical([asdict(x) for x in fitted]));_write(output/"predictions.jsonl",_json_lines(asdict(x) for x in predictions));_write(output/"selections.jsonl",_json_lines(asdict(x) for x in selections));_write(output/"metrics.json",world.canonical(metrics))
    raw_hashes=[_hash_file(path) for path in sorted(raw.iterdir()) if path.is_file()]
    recipe={"schema_version":1,"renderer":"experiments.06_world_model.run:reconstruct","raw_files":raw_hashes,"fit_partitions":["train","tuning"],"prediction_partition":"evaluation","selectors":["DIRECT","W0","W1","W2","W3","W4"],"sort":"canonical generation order","numpy":np.__version__}
    _write(output/"recipe.json",world.canonical(recipe))


def reconstruct(raw: Path, output: Path) -> None:
    if output.exists():raise FileExistsError(output)
    required={"source-ledger.json","scenes.jsonl","anchors.jsonl","candidates.jsonl","actions.npy","truth.jsonl","attempts.jsonl"}
    if not raw.is_dir() or {x.name for x in raw.iterdir()}!=required:raise ValueError("raw evidence file set is not exact")
    _derive(raw,output)


def run_matrix(output: Path, *, specs: Sequence[world.SceneSpec] | None = None, require_full: bool = True) -> dict[str,int]:
    if output.exists():raise FileExistsError(output)
    selected=tuple(world.scene_rows() if specs is None else specs)
    if require_full and selected!=world.scene_rows():raise ValueError("full run requires exact frozen scene manifest")
    if len({x.scene_id for x in selected})!=len(selected):raise ValueError("scene identities overlap")
    source=_source_ledger();output.mkdir(parents=True);raw=output/"raw";raw.mkdir();scenes=[];anchors=[];candidate_rows=[];truth=[];actions=[];attempts=[]
    for spec in selected:
        try:
            scene,scene_anchors,candidates,outcomes=world.run_scene(spec);scenes.append(asdict(scene));anchors.extend(asdict(x) for x in scene_anchors);outcome_by_id={x.candidate_id:x for x in outcomes};anchor_by_id={x.anchor_id:x for x in scene_anchors}
            for candidate in candidates:
                outcome=outcome_by_id[candidate.candidate_id];anchor=anchor_by_id[outcome.anchor_id];index=len(actions);actions.append(candidate.commands)
                candidate_rows.append({"partition":spec.partition,"stratum":spec.stratum,"scene_id":spec.scene_id,"anchor_id":anchor.anchor_id,"candidate_id":candidate.candidate_id,"strategy_id":candidate.strategy_id,"state_features":list(model.scene_features(scene,anchor)),"action_sha256":candidate.action_sha256,"action_index":index})
                truth.append(asdict(outcome))
            attempts.append({"scene_id":spec.scene_id,"outcome":"VALID","anchors":len(scene_anchors),"candidates":len(candidates)})
        except Exception as exc:
            attempts.append({"scene_id":spec.scene_id,"outcome":"INVALID_ATTEMPT","error_type":type(exc).__name__,"error_message":str(exc)})
    _write(raw/"source-ledger.json",world.canonical({"schema_version":1,"git_head":subprocess.run(("git","rev-parse","HEAD"),check=True,stdout=subprocess.PIPE).stdout.decode().strip(),"python":platform.python_version(),"numpy":np.__version__,"mujoco":mujoco.__version__,"files":source}));_write(raw/"scenes.jsonl",_json_lines(scenes));_write(raw/"anchors.jsonl",_json_lines(anchors));_write(raw/"candidates.jsonl",_json_lines(candidate_rows));_save_actions(raw/"actions.npy",np.asarray(actions,dtype="<f8"));_write(raw/"truth.jsonl",_json_lines(truth));_write(raw/"attempts.jsonl",_json_lines(attempts))
    if _source_ledger()!=source:raise RuntimeError("Experiment 06 source changed during execution")
    expected_scenes=len(selected);expected_candidates=expected_scenes*16
    if len(scenes)!=expected_scenes or len(anchors)!=expected_scenes*2 or len(candidate_rows)!=expected_candidates or any(x["outcome"]!="VALID" for x in attempts):raise RuntimeError("Experiment 06 matrix is incomplete")
    if require_full:
        if (sum(x.partition=="train" for x in selected),sum(x.partition=="tuning" for x in selected),sum(x.partition=="evaluation" for x in selected))!=(48,16,24):raise RuntimeError("split counts drifted")
    derived=output/"derived";_derive(raw,derived)
    files=[]
    for path in sorted(x for x in output.rglob("*") if x.is_file()):
        relative=path.relative_to(output);row=_hash_file(path);row["path"]=relative.as_posix();files.append(row)
    counts={"scenes":len(scenes),"anchors":len(anchors),"candidates":len(candidate_rows),"evaluation_candidates":sum(x["partition"]=="evaluation" for x in candidate_rows)}
    manifest={"schema_version":1,"status":"PRELIMINARY_NONCONFIRMATORY_ENGINEERING_ONLY","authority":"NONE","counts":counts,"files":files};_write(output/"manifest.json",world.canonical(manifest))
    return counts


def _main() -> None:
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True);group.add_argument("--output",type=Path);group.add_argument("--reconstruct-from",type=Path);parser.add_argument("--reconstructed-output",type=Path);args=parser.parse_args()
    if args.output is not None:
        print(world.canonical(run_matrix(args.output)).decode(),end="")
    else:
        if args.reconstructed_output is None:parser.error("--reconstructed-output is required with --reconstruct-from")
        reconstruct(args.reconstruct_from,args.reconstructed_output)


if __name__=="__main__":_main()
