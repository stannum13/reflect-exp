"""Create and reconstruct the bounded Experiment 06 engineering evidence."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time
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
V4_PARENT_MANIFEST_SHA256="40be9ef3b736684b89854af856462aab3ad65c8f2a9f2bfdb1463a26a7bdc8c4"
V4_SOURCE_GIT_HEAD="0ff47efb29b30cccc7a265d8992310c6aca4be7f"


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


def _git_file_bytes(head: str, path: Path) -> bytes:
    return subprocess.run(("git", "show", f"{head}:{path.as_posix()}"), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def _load_canonical_json(path: Path) -> dict[str, object]:
    payload=path.read_bytes();value=json.loads(payload)
    if not isinstance(value,dict) or world.canonical(value)!=payload:raise ValueError(f"noncanonical JSON: {path.name}")
    return value


def _load_canonical_jsonl(path: Path) -> list[dict[str, object]]:
    payload=path.read_bytes();rows=[]
    for line in payload.splitlines(keepends=True):
        value=json.loads(line)
        if not isinstance(value,dict) or world.canonical(value)!=line:raise ValueError(f"noncanonical JSONL: {path.name}")
        rows.append(value)
    return rows


def _validate_source_ledger(raw: Path) -> dict[str, object]:
    ledger=_load_canonical_json(raw/"source-ledger.json");head=ledger.get("git_head")
    if not isinstance(head,str) or re.fullmatch(r"[0-9a-f]{40}",head) is None:raise ValueError("source Git commit is invalid")
    files=ledger.get("files")
    if not isinstance(files,list) or [row.get("path") for row in files if isinstance(row,dict)]!=[path.as_posix() for path in SOURCE_PATHS]:raise ValueError("source Git file domain is invalid")
    current=_source_ledger()
    for declared,working,path in zip(files,current,SOURCE_PATHS):
        if declared!=working:raise ValueError("source Git ledger differs from replay source")
        try:committed=_git_file_bytes(head,path)
        except (OSError,subprocess.SubprocessError) as exc:raise ValueError("source Git object is unavailable") from exc
        if len(committed)!=declared["bytes"] or hashlib.sha256(committed).hexdigest()!=declared["sha256"]:raise ValueError("source Git blob hash mismatch")
    return ledger


def _validate_root_manifest(raw: Path) -> dict[str, object]:
    root=raw.parent;manifest=_load_canonical_json(root/"manifest.json")
    if manifest.get("schema_version")!=3 or manifest.get("status")!="VALIDITY_REPAIRED_ENGINEERING_ONLY" or manifest.get("authority")!="NONE":raise ValueError("root manifest status is invalid")
    files=manifest.get("files")
    if not isinstance(files,list):raise ValueError("root manifest inventory is invalid")
    declared={row.get("path"):row for row in files if isinstance(row,dict)}
    if len(declared)!=len(files):raise ValueError("root manifest inventory collides")
    actual={path.relative_to(root).as_posix():path for path in root.rglob("*") if path.is_file() and path.name!="manifest.json"}
    if set(declared)!=set(actual):raise ValueError("root manifest file set is not exact")
    for name,path in actual.items():
        payload=path.read_bytes();row=declared[name]
        if set(row)!={"path","bytes","sha256"} or row["bytes"]!=len(payload) or row["sha256"]!=hashlib.sha256(payload).hexdigest():raise ValueError("root manifest member hash mismatch")
    return manifest


def _save_actions(path: Path, actions: np.ndarray) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as stream:
        np.lib.format.write_array(stream,np.asarray(actions,dtype="<f8"),allow_pickle=False);stream.flush();os.fsync(stream.fileno())


def _raw_dataset(raw: Path) -> tuple[model.DatasetRow,...]:
    candidates=_load_canonical_jsonl(raw/"candidates.jsonl")
    truth={row["candidate_id"]:row for row in _load_canonical_jsonl(raw/"truth.jsonl")}
    actions=np.load(raw/"actions.npy",allow_pickle=False)
    rows=[]
    for item in candidates:
        outcome=truth[item["candidate_id"]]
        if outcome.get("action_sha256")!=item.get("action_sha256"):raise ValueError("outcome action parent mismatch")
        command=np.asarray(actions[item["action_index"]],dtype="<f8")
        if world.sha(world.action_preimage(command))!=item["action_sha256"]:raise ValueError("candidate action hash mismatch")
        rows.append(model.DatasetRow(item["partition"],item["stratum"],item["scene_id"],item["anchor_id"],item["candidate_id"],item["strategy_id"],tuple(item["state_features"]),command,item["action_sha256"],tuple(outcome["terminal_state"]),outcome["position_error_m"],outcome["orientation_error_rad"],outcome["collision"],outcome["action_energy"],outcome["unsafe"],outcome["success"],outcome["terminal_failure"],outcome["actual_cost"],outcome["outcome_sha256"]))
    return tuple(rows)

def _frozen_models(raw:Path)->tuple[model.FittedModel,...]|None:
    path=raw/"frozen-models.json"
    if not path.exists():return None
    provenance=_load_canonical_json(raw/"model-provenance.json")
    expected={"schema_version":1,"disposition":"V4_MODELS_BYTE_FROZEN_NO_REFIT","models_sha256":model.V4_MODELS_SHA256,"parent_manifest_sha256":V4_PARENT_MANIFEST_SHA256,"parent_source_git_head":V4_SOURCE_GIT_HEAD,"selection":"W3R","training_scenes":72,"tuning_scenes":24}
    if provenance!=expected or hashlib.sha256(path.read_bytes()).hexdigest()!=model.V4_MODELS_SHA256:raise ValueError("frozen model provenance mismatch")
    fitted=model.load_frozen_models(path.read_bytes());rows=world.scene_rows();train={x.scene_id for x in rows if x.partition=="train"};tune={x.scene_id for x in rows if x.partition=="tuning"};evaluation={x.scene_id for x in rows if x.partition=="evaluation"}
    if any(set(x.fit_scene_ids)!=train or set(x.tuning_scene_ids)!=tune or set(x.fit_scene_ids)&evaluation or set(x.tuning_scene_ids)&evaluation for x in fitted):raise ValueError("frozen model ancestry does not bind the frozen split")
    return fitted


def _authenticate_and_replay(raw: Path) -> None:
    manifest=_validate_root_manifest(raw);_validate_source_ledger(raw)
    scene_rows=_load_canonical_jsonl(raw/"scenes.jsonl");anchor_rows=_load_canonical_jsonl(raw/"anchors.jsonl");candidate_rows=_load_canonical_jsonl(raw/"candidates.jsonl");truth_rows=_load_canonical_jsonl(raw/"truth.jsonl");attempt_rows=_load_canonical_jsonl(raw/"attempts.jsonl")
    allowed={spec.scene_id:(index,spec) for index,spec in enumerate(world.scene_rows())};selected=[];indices=[]
    for row in scene_rows:
        spec_row=row.get("spec")
        if not isinstance(spec_row,dict) or spec_row.get("scene_id") not in allowed:raise ValueError("scene replay identity is outside the frozen split")
        index,spec=allowed[str(spec_row["scene_id"])];indices.append(index);selected.append(spec)
    if indices!=sorted(set(indices)):raise ValueError("scene replay split order or identity is invalid")
    if manifest.get("matrix_kind")=="FULL_FROZEN" and tuple(selected)!=world.scene_rows():raise ValueError("scene replay full split is incomplete")
    if manifest.get("matrix_kind") not in {"FULL_FROZEN","BOUNDED_TEST_SUBSET"}:raise ValueError("scene replay matrix kind is invalid")
    actions=np.load(raw/"actions.npy",allow_pickle=False)
    if actions.dtype!=np.dtype("<f8") or actions.shape!=(len(selected)*16,50,2) or not np.isfinite(actions).all():raise ValueError("candidate replay action array is invalid")
    expected_scenes=[];expected_anchors=[];expected_candidates=[];expected_truth=[];expected_actions=[];expected_attempts=[]
    for spec in selected:
        scene,anchors,candidates,outcomes=world.run_scene(spec);expected_scenes.append(asdict(scene));expected_anchors.extend(asdict(item) for item in anchors)
        outcome_by_id={item.candidate_id:item for item in outcomes};anchor_by_id={item.anchor_id:item for item in anchors}
        for candidate in candidates:
            outcome=outcome_by_id[candidate.candidate_id];anchor=anchor_by_id[outcome.anchor_id];index=len(expected_actions);expected_actions.append(candidate.commands)
            expected_candidates.append({"partition":spec.partition,"stratum":spec.stratum,"scene_id":spec.scene_id,"anchor_id":anchor.anchor_id,"candidate_id":candidate.candidate_id,"strategy_id":candidate.strategy_id,"state_features":list(model.scene_features(scene,anchor)),"generation_counter":candidate.generation_counter,"perturbation_magnitude":candidate.perturbation_magnitude,"pre_perturbation_sha256":candidate.pre_perturbation_sha256,"action_sha256":candidate.action_sha256,"action_index":index})
            expected_truth.append(asdict(outcome))
        expected_attempts.append({"scene_id":spec.scene_id,"outcome":"VALID","anchors":len(anchors),"candidates":len(candidates)})
    if world.canonical(expected_scenes)!=world.canonical(scene_rows):raise ValueError("scene replay mismatch")
    if world.canonical(expected_anchors)!=world.canonical(anchor_rows):raise ValueError("anchor replay mismatch")
    if world.canonical(expected_candidates)!=world.canonical(candidate_rows) or not np.array_equal(np.asarray(expected_actions,dtype="<f8"),actions):raise ValueError("candidate replay mismatch")
    if world.canonical(expected_truth)!=world.canonical(truth_rows):raise ValueError("outcome replay mismatch")
    if world.canonical(expected_attempts)!=world.canonical(attempt_rows):raise ValueError("attempt replay mismatch")


def _derive(raw: Path, output: Path) -> None:
    output.mkdir(parents=True)
    rows=_raw_dataset(raw);training=tuple(x for x in rows if x.partition=="train");tuning=tuple(x for x in rows if x.partition=="tuning");evaluation=tuple(x for x in rows if x.partition=="evaluation")
    fitted=_frozen_models(raw) or model.fit_models(training,tuning);predictions=model.predict_all(fitted,evaluation);selections=model.rank_selectors(predictions,evaluation);metrics=model.aggregate_metrics(selections,predictions,evaluation)
    latency=_load_canonical_json(raw/"latency.json")
    selected=next(x.selector_id for x in fitted if x.selected_for_evaluation)
    gate=model.quality_gate(metrics,selected,latency["selectors"])
    chosen=[x for x in selections if x.selector_id==selected]; baseline={(x.scene_id,x.anchor_id):x for x in selections if x.selector_id=="W1V2"}
    examples=[]
    for kind,pool in (("WORKING",[x for x in chosen if x.regret<baseline[(x.scene_id,x.anchor_id)].regret]),("NONWORKING",[x for x in chosen if x.regret>=baseline[(x.scene_id,x.anchor_id)].regret]),("MAX_REGRET",chosen)):
        if pool:
            item=max(pool,key=lambda x:(x.regret,x.scene_id,x.anchor_id));examples.append({"kind":kind,"selector_id":selected,"scene_id":item.scene_id,"anchor_id":item.anchor_id,"candidate_id":item.candidate_id,"stratum":item.stratum,"regret":item.regret,"selection_sha256":world.sha(world.canonical(asdict(item)))})
    _write(output/"models.json",world.canonical([asdict(x) for x in fitted]));_write(output/"predictions.jsonl",_json_lines(asdict(x) for x in predictions));_write(output/"selections.jsonl",_json_lines(asdict(x) for x in selections));_write(output/"metrics.json",world.canonical(metrics));_write(output/"latency.json",world.canonical(latency));_write(output/"gate.json",world.canonical(gate));_write(output/"annotations.json",world.canonical(examples))
    raw_hashes=[_hash_file(path) for path in sorted(raw.iterdir()) if path.is_file()]
    recipe={"schema_version":5 if _frozen_models(raw) else 4,"renderer":"experiments.06_world_model.run:reconstruct","raw_files":raw_hashes,"fit_partition":"sealed v4 model ancestry; no refit" if _frozen_models(raw) else "train","tuning_partition":"sealed v4 selection; no retune" if _frozen_models(raw) else "tuning","untouched_prediction_partition":"evaluation","selectors":list(model.SELECTORS),"selected_residual_selector":selected,"annotation_rule":"max regret; first available working/nonworking class by maximum regret","sort":"canonical generation order","numpy":np.__version__}
    _write(output/"recipe.json",world.canonical(recipe))


def reconstruct(raw: Path, output: Path) -> None:
    if output.exists():raise FileExistsError(output)
    required={"source-ledger.json","scenes.jsonl","anchors.jsonl","candidates.jsonl","actions.npy","truth.jsonl","attempts.jsonl","latency.json"}
    if (raw/"frozen-models.json").exists():required|={"frozen-models.json","model-provenance.json"}
    if not raw.is_dir() or {x.name for x in raw.iterdir()}!=required:raise ValueError("raw evidence file set is not exact")
    _authenticate_and_replay(raw)
    _derive(raw,output)


def run_matrix(output: Path, *, specs: Sequence[world.SceneSpec] | None = None, require_full: bool = True, frozen_models_from:Path|None=None) -> dict[str,int]:
    if output.exists():raise FileExistsError(output)
    selected=tuple(world.scene_rows() if specs is None else specs)
    if require_full and selected!=world.scene_rows():raise ValueError("full run requires exact frozen scene manifest")
    if len({x.scene_id for x in selected})!=len(selected):raise ValueError("scene identities overlap")
    source=_source_ledger();git_head=subprocess.run(("git","rev-parse","HEAD"),check=True,stdout=subprocess.PIPE).stdout.decode().strip()
    source_receipt={"schema_version":3,"git_head":git_head,"python":platform.python_version(),"numpy":np.__version__,"mujoco":mujoco.__version__,"files":source}
    output.mkdir(parents=True);raw=output/"raw";raw.mkdir();_write(raw/"source-ledger.json",world.canonical(source_receipt));_validate_source_ledger(raw)
    if frozen_models_from is not None:
        frozen_payload=frozen_models_from.read_bytes();model.load_frozen_models(frozen_payload);_write(raw/"frozen-models.json",frozen_payload);_write(raw/"model-provenance.json",world.canonical({"schema_version":1,"disposition":"V4_MODELS_BYTE_FROZEN_NO_REFIT","models_sha256":model.V4_MODELS_SHA256,"parent_manifest_sha256":V4_PARENT_MANIFEST_SHA256,"parent_source_git_head":V4_SOURCE_GIT_HEAD,"selection":"W3R","training_scenes":72,"tuning_scenes":24}));_frozen_models(raw)
    scenes=[];anchors=[];candidate_rows=[];truth=[];actions=[];attempts=[]
    for spec in selected:
        try:
            scene,scene_anchors,candidates,outcomes=world.run_scene(spec);scenes.append(asdict(scene));anchors.extend(asdict(x) for x in scene_anchors);outcome_by_id={x.candidate_id:x for x in outcomes};anchor_by_id={x.anchor_id:x for x in scene_anchors}
            for candidate in candidates:
                outcome=outcome_by_id[candidate.candidate_id];anchor=anchor_by_id[outcome.anchor_id];index=len(actions);actions.append(candidate.commands)
                candidate_rows.append({"partition":spec.partition,"stratum":spec.stratum,"scene_id":spec.scene_id,"anchor_id":anchor.anchor_id,"candidate_id":candidate.candidate_id,"strategy_id":candidate.strategy_id,"state_features":list(model.scene_features(scene,anchor)),"generation_counter":candidate.generation_counter,"perturbation_magnitude":candidate.perturbation_magnitude,"pre_perturbation_sha256":candidate.pre_perturbation_sha256,"action_sha256":candidate.action_sha256,"action_index":index})
                truth.append(asdict(outcome))
            attempts.append({"scene_id":spec.scene_id,"outcome":"VALID","anchors":len(scene_anchors),"candidates":len(candidates)})
        except Exception as exc:
            attempts.append({"scene_id":spec.scene_id,"outcome":"INVALID_ATTEMPT","error_type":type(exc).__name__,"error_message":str(exc)})
    _write(raw/"scenes.jsonl",_json_lines(scenes));_write(raw/"anchors.jsonl",_json_lines(anchors));_write(raw/"candidates.jsonl",_json_lines(candidate_rows));_save_actions(raw/"actions.npy",np.asarray(actions,dtype="<f8"));_write(raw/"truth.jsonl",_json_lines(truth));_write(raw/"attempts.jsonl",_json_lines(attempts))
    if _source_ledger()!=source:raise RuntimeError("Experiment 06 source changed during execution")
    expected_scenes=len(selected);expected_candidates=expected_scenes*16
    if len(scenes)!=expected_scenes or len(anchors)!=expected_scenes*2 or len(candidate_rows)!=expected_candidates or any(x["outcome"]!="VALID" for x in attempts):raise RuntimeError("Experiment 06 matrix is incomplete")
    if require_full:
        if (sum(x.partition=="train" for x in selected),sum(x.partition=="tuning" for x in selected),sum(x.partition=="evaluation" for x in selected))!=(72,24,48):raise RuntimeError("split counts drifted")
    rows=_raw_dataset(raw);training=tuple(x for x in rows if x.partition=="train");tuning=tuple(x for x in rows if x.partition=="tuning");evaluation=tuple(x for x in rows if x.partition=="evaluation");fitted=_frozen_models(raw) or model.fit_models(training,tuning);samples={}
    for fitted_model in fitted:
        durations=[]
        for row in evaluation[:min(64,len(evaluation))]:
            start=time.perf_counter_ns();model._prediction(fitted_model,row);durations.append(time.perf_counter_ns()-start)
        samples[fitted_model.selector_id]={"samples_ns":durations,"p50_ns":int(np.percentile(durations,50)),"p95_ns":int(np.percentile(durations,95))}
    _write(raw/"latency.json",world.canonical({"clock":"time.perf_counter_ns","unit":"ns_per_candidate","selectors":samples}))
    derived=output/"derived";_derive(raw,derived)
    files=[]
    for path in sorted(x for x in output.rglob("*") if x.is_file()):
        relative=path.relative_to(output);row=_hash_file(path);row["path"]=relative.as_posix();files.append(row)
    counts={"scenes":len(scenes),"anchors":len(anchors),"candidates":len(candidate_rows),"evaluation_candidates":sum(x["partition"]=="evaluation" for x in candidate_rows)}
    manifest={"schema_version":3,"status":"VALIDITY_REPAIRED_ENGINEERING_ONLY","authority":"NONE","matrix_kind":"FULL_FROZEN" if require_full else "BOUNDED_TEST_SUBSET","counts":counts,"files":files};_write(output/"manifest.json",world.canonical(manifest))
    return counts


def _main() -> None:
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True);group.add_argument("--output",type=Path);group.add_argument("--reconstruct-from",type=Path);parser.add_argument("--reconstructed-output",type=Path);parser.add_argument("--frozen-models-from",type=Path);args=parser.parse_args()
    if args.output is not None:
        print(world.canonical(run_matrix(args.output,frozen_models_from=args.frozen_models_from)).decode(),end="")
    else:
        if args.reconstructed_output is None:parser.error("--reconstructed-output is required with --reconstruct-from")
        reconstruct(args.reconstruct_from,args.reconstructed_output)


if __name__=="__main__":_main()
