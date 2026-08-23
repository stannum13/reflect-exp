"""Bounded P2 trajectory rescue using the existing Exp01 rollout evidence."""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import subprocess

import mujoco
import numpy as np
from reflect.rollout import RolloutWriter, sha256_json, validate_rollout
from reflect.safety import SafetyConfig

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT=Path(__file__).resolve().parent/"results/engineering-p2-rescue"
HORIZONS=(.05,.075,.1);SLEWS=(24.,32.,48.)
TUNING_CONDITIONS=("core-20-000-1","core-10-300-2","core-05-700-2")
CORE_CONDITIONS=tuple(f"core-{rate:02d}-{latency:03d}-{moves}" for rate in (5,10,20) for latency in (0,100,300,700) for moves in (1,2))
FAULT_CONDITIONS=("probe-drop","probe-out-of-order")
TUNING_SEEDS=(20260901,20260902,20260903,20260904)
EVALUATION_SEEDS=(20261001,20261002,20261003,20261004)
FAULT_SEEDS=(20261101,20261102,20261103,20261104)
DECLARED_ROLLOUTS={"tuning":108,"evaluation":288,"fault":16,"total":412}
SOURCE_PATHS=("experiments/01_policy_control/engineering_p2_rescue.py","experiments/01_policy_control/configs/base.yaml","experiments/01_policy_control/src/arm.py","experiments/01_policy_control/src/contracts.py","experiments/01_policy_control/src/evaluate.py","experiments/01_policy_control/src/kinematics.py","experiments/01_policy_control/src/representations.py","experiments/01_policy_control/src/timing.py","reflect/_rollout_io.py","reflect/clock.py","reflect/events.py","reflect/rollout.py","reflect/safety.py","reflect/types.py")

def canonical(value:object)->bytes:return(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()
def digest(payload:bytes)->str:return hashlib.sha256(payload).hexdigest()
def thaw(value:object)->object:
    if is_dataclass(value):return{field.name:thaw(getattr(value,field.name)) for field in fields(value)}
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,Mapping):return{str(k):thaw(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return[thaw(x) for x in value]
    if hasattr(value,"value") and isinstance(getattr(value,"value"),(str,int,float)):return getattr(value,"value")
    return value
def git(*args:str)->bytes:return subprocess.run(("git",*args),cwd=ROOT,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
def source_ledger()->list[dict[str,object]]:
    return[{"path":name,"bytes":len((ROOT/name).read_bytes()),"sha256":digest((ROOT/name).read_bytes())} for name in SOURCE_PATHS]
def file_row(path:Path,root:Path)->dict[str,object]:
    payload=path.read_bytes();return{"path":path.relative_to(root).as_posix(),"bytes":len(payload),"sha256":digest(payload)}

def variant_id(horizon:float,slew:float)->str:return f"P2-h{str(horizon).replace('.','p')}-slew{int(slew)}"

def p2_variants(base:object)->tuple[tuple[str,object,dict[str,float]],...]:
    pd=((5.,.5),)+tuple(x for x in base.controller.pd_candidates if x!=(5.,.5));result=[]
    for horizon in HORIZONS:
        for slew in SLEWS:
            controller=replace(base.controller,pd_candidates=pd,reference_slew_rad_s=slew);cfg=replace(base,controller=controller,timing=replace(base.timing,chunk_horizon_s=horizon),mpc=replace(base.mpc,smoothness_weight=.02));result.append((variant_id(horizon,slew),cfg,{"chunk_horizon_s":horizon,"reference_slew_rad_s":slew,"pd_kp":5.,"pd_kd":.5}))
    return tuple(result)

def p6_comparator(base:object)->tuple[str,object,dict[str,float]]:
    pd=((5.,.5),)+tuple(x for x in base.controller.pd_candidates if x!=(5.,.5));controller=replace(base.controller,pd_candidates=pd,reference_slew_rad_s=48.);cfg=replace(base,controller=controller,residual=replace(base.residual,component_limit_rad=.5),mpc=replace(base.mpc,smoothness_weight=.02));return("P6-res0p5-slew48",cfg,{"residual_component_limit_rad":.5,"reference_slew_rad_s":48.,"pd_kp":5.,"pd_kd":.5})

def select_top_two(rows:Sequence[Mapping[str,object]])->tuple[str,str]:
    grouped={}
    for row in rows:grouped.setdefault(str(row["variant_id"]),[]).append(row)
    if len(grouped)<2:raise ValueError("selection requires at least two variants")
    def rank(item:tuple[str,list[Mapping[str,object]]])->tuple[object,...]:
        name,domain=item;return(-sum(int(x["absolute_working"]) for x in domain),-sum(int(x["metrics"]["recovered_events"]) for x in domain),float(np.mean([x["metrics"]["clamp_fraction"] for x in domain])),float(np.mean([x["metrics"]["discontinuity_mean"] for x in domain])),name)
    return tuple(name for name,_ in sorted(grouped.items(),key=rank)[:2])

def paired_interval(cells:Sequence[Mapping[str,object]],*,seed:int)->dict[str,object]:
    pairs=[(int(x["seed"]),str(x["condition_id"])) for x in cells];seeds=sorted({x[0] for x in pairs});conditions=sorted({x[1] for x in pairs})
    if len(cells)!=len(seeds)*len(conditions) or set(pairs)!={(s,c) for s in seeds for c in conditions}:raise ValueError("paired cells are not rectangular")
    values=np.asarray([float(x["difference"]) for x in sorted(cells,key=lambda x:(int(x["seed"]),str(x["condition_id"])))],dtype=np.float64);rng=np.random.Generator(np.random.PCG64(seed));indexes=rng.integers(0,len(values),size=(10000,len(values)));distribution=np.sort(values[indexes].mean(axis=1));return{"n_pairs":len(values),"estimate":float(values.mean()),"lower":float(distribution[249]),"upper":float(distribution[9749]),"rng":"numpy.random.PCG64","seed":seed,"resamples":10000,"endpoint_rule":"SORTED_NEAREST_RANK_249_9749"}

def _working(metrics:Mapping[str,object],base:object)->tuple[bool,list[str]]:
    disp=int(metrics["displacement_events"]);rec=int(metrics["recovered_events"]);checks=(("INVALID",not metrics["valid"]),("UNSAFE",metrics["unsafe_count"]!=0),("RECOVERY_FRACTION_BELOW_0.90",rec<.9*disp),("SATURATION_ABOVE_0.05",metrics["saturation_fraction"]>base.thresholds.saturation_fraction),("CLAMP_ABOVE_0.01",metrics["clamp_fraction"]>base.thresholds.clamp_fraction));reasons=[name for name,failed in checks if failed];return not reasons,reasons

def _identity(evaluate:object,timing:object,arm:object,cfg:object,head:str,ledger_sha:str)->object:
    return evaluate.EpisodeIdentity(implementation_sha=head,working_tree_clean=False,dirty_diff_hash=ledger_sha,source_lock_hash=digest(b"ENGINEERING_P2_RESCUE_NO_SOURCE_LOCK"),os_arch=f"{platform.system()}-{platform.machine()}",cpu=platform.processor() or platform.machine(),gpu=None,python_version=platform.python_version(),dependency_versions={"mujoco":mujoco.__version__,"numpy":np.__version__},task_config_hash=sha256_json(timing.scheduler_config(cfg)),model_hashes={"arm.xml":digest(arm.MJCF_BYTES)})

def _execute(output:Path,phase:str,variant:str,stack:str,cfg:object,knobs:Mapping[str,object],conditions:Mapping[str,object],seeds:Sequence[int],base:object,modules:tuple[object,...],head:str,ledger:list[dict[str,object]],ledger_sha:str,rows:list[dict[str,object]],attempts:list[dict[str,object]],scenarios:dict[str,object],configs:dict[str,object])->None:
    contracts,evaluate,timing,arm=modules;wire=thaw(cfg);cfg_sha=digest(canonical(wire));configs.setdefault(variant,{"configuration_sha256":cfg_sha,"configuration":wire,"knobs":dict(knobs)});identity=_identity(evaluate,timing,arm,cfg,head,ledger_sha);root=output/"bundles"/phase/variant;root.mkdir(parents=True,mode=0o700)
    for seed in seeds:
        scenario=evaluate.generate_scenario(seed,cfg);scenarios.setdefault(f"{seed}:{scenario.identity_sha256}",thaw(scenario))
        for cid,condition in conditions.items():
            attempt={"phase":phase,"variant_id":variant,"stack_id":stack,"knobs":dict(knobs),"condition_id":cid,"fault_kind":condition.fault.value,"seed":seed,"scenario_identity_sha256":scenario.identity_sha256,"configuration_sha256":cfg_sha}
            try:
                if source_ledger()!=ledger:raise RuntimeError("runtime source changed before rollout")
                record=evaluate.run_episode(contracts.CommandStack(stack),condition,scenario,cfg,identity)
                if source_ledger()!=ledger:raise RuntimeError("runtime source changed during rollout")
                bundle=RolloutWriter(root,f"{stack}-{cid}-{seed}").write(record);validated=validate_rollout(bundle);metrics=thaw(validated.metrics);working,reasons=_working(metrics,base)
                if validated.metadata.git_sha!=head or validated.metadata.dirty_diff_hash!=ledger_sha:raise RuntimeError("bundle source binding differs")
                row=attempt|{"outcome":"VALID","absolute_working":working,"absolute_nonworking_reasons":reasons,"bundle":bundle.relative_to(output).as_posix(),"bundle_files":[file_row(p,output) for p in sorted(bundle.iterdir()) if p.is_file()],"metrics":metrics};rows.append(row);attempts.append(attempt|{"outcome":"VALID","bundle":row["bundle"]})
            except Exception as exc:
                error={"type":type(exc).__name__,"message":str(exc)};attempts.append(attempt|{"outcome":"INVALID_ATTEMPT","error":error,"error_sha256":digest(canonical(error))})

def _analysis(eval_rows:Sequence[Mapping[str,object]],selected:Sequence[str],comparator:str)->dict[str,object]:
    by={(str(x["variant_id"]),int(x["seed"]),str(x["condition_id"])):x for x in eval_rows};metrics=("absolute_working","recovery_fraction","clamp_fraction","discontinuity_mean","p95_error_m");contrasts=[]
    for vindex,variant in enumerate(selected):
        results={}
        for mindex,metric in enumerate(metrics):
            cells=[]
            for seed in EVALUATION_SEEDS:
                for condition in CORE_CONDITIONS:
                    left=by[(variant,seed,condition)];right=by[(comparator,seed,condition)]
                    def value(row:Mapping[str,object])->float:
                        if metric=="absolute_working":return float(row[metric])
                        if metric=="recovery_fraction":return float(row["metrics"]["recovered_events"])/max(1,float(row["metrics"]["displacement_events"]))
                        return float(row["metrics"][metric])
                    cells.append({"seed":seed,"condition_id":condition,"difference":value(left)-value(right)})
            results[metric]={"direction":"P2_MINUS_P6","cells":cells,"interval":paired_interval(cells,seed=20261200+vindex*10+mindex)}
        contrasts.append({"p2_variant":variant,"comparator":comparator,"metrics":results})
    annotations=[]
    for variant in (*selected,comparator):
        domain=sorted((x for x in eval_rows if x["variant_id"]==variant),key=lambda x:(x["seed"],x["condition_id"]))
        for label,pool in (("WORKING",[x for x in domain if x["absolute_working"]]),("NONWORKING",[x for x in domain if not x["absolute_working"]])):
            annotations.append({"variant_id":variant,"label":label if pool else "CLASS_NOT_OBSERVED","denominator":len(domain),"bundle":pool[0]["bundle"] if pool else None,"row_sha256":digest(canonical(pool[0])) if pool else None})
        worst=max(domain,key=lambda x:(x["metrics"]["clamp_fraction"],x["seed"],x["condition_id"]));annotations.append({"variant_id":variant,"label":"MAX_CLAMP","denominator":len(domain),"bundle":worst["bundle"],"row_sha256":digest(canonical(worst))})
    return{"contrasts":contrasts,"annotations":annotations}

def run(output:Path=DEFAULT_OUTPUT)->dict[str,object]:
    SafetyConfig.from_mapping(os.environ).require_simulation_only()
    if output.exists():raise FileExistsError(output)
    contracts=importlib.import_module("experiments.01_policy_control.src.contracts");evaluate=importlib.import_module("experiments.01_policy_control.src.evaluate");timing=importlib.import_module("experiments.01_policy_control.src.timing");arm=importlib.import_module("experiments.01_policy_control.src.arm");modules=(contracts,evaluate,timing,arm);base=contracts.load_config(ROOT/"experiments/01_policy_control/configs/base.yaml");core={x.condition_id:x for x in evaluate.core_conditions(base)};probes={x.condition_id:x for x in evaluate.probe_conditions(base)}
    if tuple(core)!=CORE_CONDITIONS or tuple(probes)!=FAULT_CONDITIONS:raise RuntimeError("condition domain drifted")
    output.mkdir(parents=True);head=git("rev-parse","HEAD").decode().strip();ledger=source_ledger();ledger_sha=digest(canonical(ledger));started=datetime.now(timezone.utc).isoformat();rows=[];attempts=[];scenarios={};configs={};variants={x[0]:(x[1],x[2]) for x in p2_variants(base)}
    tuning={key:core[key] for key in TUNING_CONDITIONS}
    for name,cfg,knobs in p2_variants(base):_execute(output,"tuning",name,"P2",cfg,knobs,tuning,TUNING_SEEDS,base,modules,head,ledger,ledger_sha,rows,attempts,scenarios,configs)
    tuning_rows=[x for x in rows if x["phase"]=="tuning"]
    if len(tuning_rows)!=DECLARED_ROLLOUTS["tuning"] or any(x["outcome"]!="VALID" for x in attempts):raise RuntimeError("tuning matrix incomplete")
    selected=select_top_two(tuning_rows);selection={"schema_version":1,"disposition":"FROZEN_BEFORE_EVALUATION","rule":["WORKING_COUNT_DESC","RECOVERED_EVENTS_DESC","CLAMP_MEAN_ASC","DISCONTINUITY_MEAN_ASC","VARIANT_ID_ASC"],"selected":list(selected),"tuning_rows_sha256":digest(canonical(tuning_rows))};selection_payload=canonical(selection);(output/"selection.json").write_bytes(selection_payload)
    for name in selected:
        cfg,knobs=variants[name];_execute(output,"evaluation",name,"P2",cfg,knobs,core,EVALUATION_SEEDS,base,modules,head,ledger,ledger_sha,rows,attempts,scenarios,configs)
    p6name,p6cfg,p6knobs=p6_comparator(base);_execute(output,"evaluation",p6name,"P6",p6cfg,p6knobs,core,EVALUATION_SEEDS,base,modules,head,ledger,ledger_sha,rows,attempts,scenarios,configs)
    eval_rows=[x for x in rows if x["phase"]=="evaluation"]
    if len(eval_rows)!=DECLARED_ROLLOUTS["evaluation"]:raise RuntimeError("evaluation matrix incomplete")
    for name in selected:
        cfg,knobs=variants[name];_execute(output,"fault",name,"P2",cfg,knobs,probes,FAULT_SEEDS,base,modules,head,ledger,ledger_sha,rows,attempts,scenarios,configs)
    if len(rows)!=DECLARED_ROLLOUTS["total"] or len(attempts)!=DECLARED_ROLLOUTS["total"] or any(x["outcome"]!="VALID" for x in attempts):raise RuntimeError("P2 rescue matrix incomplete")
    analysis=_analysis(eval_rows,selected,p6name);summary={"schema_version":1,"disposition":"PRELIMINARY_NONCONFIRMATORY_ENGINEERING_P2_RESCUE","scientific_use":"ENGINEERING_ONLY_NOT_PILOT_OR_PROMOTION","started_utc":started,"completed_utc":datetime.now(timezone.utc).isoformat(),"execution_implementation_sha":head,"source_ledger":ledger,"source_ledger_sha256":ledger_sha,"script_sha256":digest(Path(__file__).read_bytes()),"runtime":{"python":platform.python_version(),"numpy":np.__version__,"mujoco":mujoco.__version__,"os_arch":f"{platform.system()}-{platform.machine()}"},"domains":{"tuning_conditions":list(TUNING_CONDITIONS),"core_conditions":list(CORE_CONDITIONS),"fault_conditions":list(FAULT_CONDITIONS),"tuning_seeds":list(TUNING_SEEDS),"evaluation_seeds":list(EVALUATION_SEEDS),"fault_seeds":list(FAULT_SEEDS),"declared_rollouts":DECLARED_ROLLOUTS},"absolute_working_rule":{"valid":True,"unsafe_count":0,"recovery_fraction_min":.9,"saturation_fraction_max":base.thresholds.saturation_fraction,"clamp_fraction_max":base.thresholds.clamp_fraction},"selection":selection,"configurations":configs,"conditions":{**{k:thaw(v) for k,v in core.items()},**{k:thaw(v) for k,v in probes.items()}},"scenarios":scenarios,"attempts":attempts,"rollouts":rows,"paired_analysis":analysis}
    (output/"summary.json").write_bytes(canonical(summary));files=[file_row(p,output) for p in sorted(output.rglob("*")) if p.is_file()];manifest={"schema_version":1,"disposition":"COMPLETE_ENGINEERING_NONCONFIRMATORY","counts":DECLARED_ROLLOUTS,"files":files};(output/"manifest.json").write_bytes(canonical(manifest));return{"selected":selected,"rollouts":len(rows),"manifest_sha256":digest(canonical(manifest))}

def reconstruct(output:Path)->dict[str,object]:
    summary=json.loads((output/"summary.json").read_text());manifest=json.loads((output/"manifest.json").read_text());actual=[file_row(p,output) for p in sorted(output.rglob("*")) if p.is_file() and p.name!="manifest.json"]
    if manifest["files"]!=actual:raise ValueError("manifest inventory mismatch")
    rows=summary["rollouts"]
    for row in rows:
        bundle=output/row["bundle"];validated=validate_rollout(bundle)
        if [file_row(p,output) for p in sorted(bundle.iterdir()) if p.is_file()]!=row["bundle_files"] or thaw(validated.metrics)!=row["metrics"]:raise ValueError("rollout reconstruction mismatch")
    tuning=[x for x in rows if x["phase"]=="tuning"];selected=select_top_two(tuning);evaluation=[x for x in rows if x["phase"]=="evaluation"]
    if list(selected)!=summary["selection"]["selected"] or _analysis(evaluation,selected,"P6-res0p5-slew48")!=summary["paired_analysis"]:raise ValueError("analysis reconstruction mismatch")
    return{"selected":selected,"rollouts":len(rows),"manifest_sha256":digest(canonical(manifest))}

def main()->None:
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,default=DEFAULT_OUTPUT);parser.add_argument("--reconstruct",action="store_true");args=parser.parse_args();result=reconstruct(args.output) if args.reconstruct else run(args.output);print(canonical(result).decode(),end="")
if __name__=="__main__":main()
