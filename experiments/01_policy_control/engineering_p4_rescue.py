"""Frozen Cartesian lookahead/feed-forward rescue for Experiment 01 P4."""
from __future__ import annotations
import argparse,hashlib,importlib,json,os,platform,subprocess
from collections.abc import Mapping,Sequence
from dataclasses import fields,is_dataclass,replace
from datetime import datetime,timezone
from pathlib import Path
import mujoco,numpy as np
from reflect.rollout import RolloutWriter,sha256_json,validate_rollout
from reflect.safety import SafetyConfig
from .engineering_p2_rescue import canonical,digest,file_row,paired_interval,thaw

ROOT=Path(__file__).resolve().parents[2];DEFAULT_OUTPUT=Path(__file__).resolve().parent/"results/engineering-p4-rescue"
LOOKAHEADS=(1,12,25,49);FEEDFORWARD=(False,True)
TUNING_CONDITIONS=("core-20-000-1","core-10-300-2","core-05-700-2")
CORE_CONDITIONS=tuple(f"core-{rate:02d}-{latency:03d}-{moves}" for rate in(5,10,20) for latency in(0,100,300,700) for moves in(1,2));FAULT_CONDITIONS=("probe-drop","probe-out-of-order")
TUNING_SEEDS=(20261301,20261302,20261303,20261304);EVALUATION_SEEDS=(20261401,20261402,20261403,20261404);FAULT_SEEDS=(20261501,20261502,20261503,20261504)
DECLARED={"tuning":96,"evaluation":384,"fault":8,"total":488}
SOURCE_PATHS=("experiments/01_policy_control/engineering_p4_rescue.py","experiments/01_policy_control/engineering_p2_rescue.py","experiments/01_policy_control/configs/base.yaml","experiments/01_policy_control/src/arm.py","experiments/01_policy_control/src/contracts.py","experiments/01_policy_control/src/evaluate.py","experiments/01_policy_control/src/kinematics.py","experiments/01_policy_control/src/representations.py","experiments/01_policy_control/src/timing.py","reflect/_rollout_io.py","reflect/clock.py","reflect/events.py","reflect/rollout.py","reflect/safety.py","reflect/types.py")
def git(*args:str)->bytes:return subprocess.run(("git",*args),cwd=ROOT,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
def source_ledger()->list[dict[str,object]]:return[{"path":p,"bytes":len((ROOT/p).read_bytes()),"sha256":digest((ROOT/p).read_bytes())}for p in SOURCE_PATHS]
def variant_id(n:int,ff:bool)->str:return f"P4-lookahead{n}-dq{'on' if ff else 'off'}"
def variant_specs()->tuple[tuple[str,int,bool],...]:return tuple((variant_id(n,ff),n,ff)for n in LOOKAHEADS for ff in FEEDFORWARD)

def select_top_two(rows:Sequence[Mapping[str,object]])->tuple[str,str]:
    grouped={}
    for row in rows:grouped.setdefault(str(row["variant_id"]),[]).append(row)
    if len(grouped)!=8:raise ValueError("selection requires exact eight-arm tuning grid")
    def rank(item:tuple[str,list[Mapping[str,object]]])->tuple[object,...]:
        name,domain=item;return(-sum(int(x["absolute_working"])for x in domain),-sum(int(x["metrics"]["recovered_events"])for x in domain),float(np.mean([x["metrics"]["clamp_fraction"]for x in domain])),float(np.mean([x["metrics"]["discontinuity_mean"]for x in domain])),sum(int(x["ik_failures"])for x in domain),name)
    return tuple(name for name,_ in sorted(grouped.items(),key=rank)[:2])

def aggressive_config(base:object)->object:
    c=base.controller;pd=((5.,.5),)+tuple(x for x in c.pd_candidates if x!=(5.,.5));damping=(.001,)+tuple(x for x in c.ik_damping_candidates if x!=.001);controller=replace(c,pd_candidates=pd,ik_damping_candidates=damping,reference_slew_rad_s=48.,differential_gain=12.,differential_speed_m_s=1.,null_gain=.1,qdot_limit_rad_s=4.);return replace(base,controller=controller,timing=replace(base.timing,chunk_horizon_s=.1),mpc=replace(base.mpc,smoothness_weight=.02))

def mechanism_probe(cfg:object)->dict[str,object]:
    kin=importlib.import_module("experiments.01_policy_control.src.kinematics");q=np.array([.35,-.7,.35]);xy=kin.forward_kinematics(q,cfg.arm.link_lengths_m)+np.array([.03,.02]);rows=[]
    for n in LOOKAHEADS:
        candidate,qdot=kin.differential_ik_command(xy,q,cfg.arm.link_lengths_m,cfg.controller.ik_damping_candidates[0],cfg,lookahead_ticks=n);post=q+np.clip(candidate-q,-cfg.controller.reference_slew_rad_s*cfg.arm.timestep_s,cfg.controller.reference_slew_rad_s*cfg.arm.timestep_s);rows.append({"lookahead_ticks":n,"tick_seconds":cfg.arm.timestep_s,"candidate_sha256":digest(candidate.tobytes()),"post_slew_sha256":digest(post.tobytes()),"qdot_sha256":digest(qdot.tobytes()),"candidate_delta_norm":float(np.linalg.norm(candidate-q)),"post_slew_delta_norm":float(np.linalg.norm(post-q)),"qdot_max_abs":float(np.max(np.abs(qdot)))})
    return{"rows":rows,"pre_slew_distinct":len({x["candidate_sha256"]for x in rows})==4,"post_slew_distinct_count":len({x["post_slew_sha256"]for x in rows}),"dq_off_on_qref_intentionally_equal":True}

def _working(m:Mapping[str,object],base:object)->tuple[bool,list[str]]:
    disp=int(m["displacement_events"]);rec=int(m["recovered_events"]);checks=(("INVALID",not m["valid"]),("UNSAFE",m["unsafe_count"]!=0),("RECOVERY_FRACTION_BELOW_0.90",rec<.9*disp),("SATURATION_ABOVE_0.05",m["saturation_fraction"]>base.thresholds.saturation_fraction),("CLAMP_ABOVE_0.01",m["clamp_fraction"]>base.thresholds.clamp_fraction));reasons=[x for x,bad in checks if bad];return not reasons,reasons
def _identity(evaluate:object,timing:object,arm:object,cfg:object,head:str,ledger_sha:str)->object:return evaluate.EpisodeIdentity(implementation_sha=head,working_tree_clean=False,dirty_diff_hash=ledger_sha,source_lock_hash=digest(b"ENGINEERING_P4_RESCUE_NO_SOURCE_LOCK"),os_arch=f"{platform.system()}-{platform.machine()}",cpu=platform.processor()or platform.machine(),gpu=None,python_version=platform.python_version(),dependency_versions={"mujoco":mujoco.__version__,"numpy":np.__version__},task_config_hash=sha256_json(timing.scheduler_config(cfg)),model_hashes={"arm.xml":digest(arm.MJCF_BYTES)})

def _execute(output:Path,phase:str,variant:str,stack:str,cfg:object,knobs:Mapping[str,object],tuning:object|None,conditions:Mapping[str,object],seeds:Sequence[int],base:object,mods:tuple[object,...],head:str,ledger:list[dict[str,object]],ledger_sha:str,rows:list[dict[str,object]],attempts:list[dict[str,object]],scenarios:dict[str,object],configs:dict[str,object])->None:
    contracts,evaluate,timing,arm=mods;wire=thaw(cfg);cfg_sha=digest(canonical(wire));configs.setdefault(variant,{"configuration_sha256":cfg_sha,"configuration":wire,"knobs":dict(knobs)});ident=_identity(evaluate,timing,arm,cfg,head,ledger_sha);root=output/"bundles"/phase/variant;root.mkdir(parents=True,mode=0o700)
    for seed in seeds:
        scenario=evaluate.generate_scenario(seed,cfg);scenarios.setdefault(f"{seed}:{scenario.identity_sha256}",thaw(scenario))
        for cid,condition in conditions.items():
            attempt={"phase":phase,"variant_id":variant,"stack_id":stack,"knobs":dict(knobs),"condition_id":cid,"fault_kind":condition.fault.value,"seed":seed,"scenario_identity_sha256":scenario.identity_sha256,"configuration_sha256":cfg_sha}
            try:
                if source_ledger()!=ledger:raise RuntimeError("runtime source changed before rollout")
                record=evaluate.run_episode(contracts.CommandStack(stack),condition,scenario,cfg,ident,p4_executor_tuning=tuning)
                if source_ledger()!=ledger:raise RuntimeError("runtime source changed during rollout")
                bundle=RolloutWriter(root,f"{stack}-{cid}-{seed}").write(record);validated=validate_rollout(bundle);metrics=thaw(validated.metrics);working,reasons=_working(metrics,base)
                if validated.metadata.git_sha!=head or validated.metadata.dirty_diff_hash!=ledger_sha:raise RuntimeError("bundle source binding differs")
                row=attempt|{"outcome":"VALID","absolute_working":working,"absolute_nonworking_reasons":reasons,"ik_failures":0,"bundle":bundle.relative_to(output).as_posix(),"bundle_files":[file_row(p,output)for p in sorted(bundle.iterdir())if p.is_file()],"metrics":metrics};rows.append(row);attempts.append(attempt|{"outcome":"VALID","bundle":row["bundle"]})
            except Exception as exc:
                error={"type":type(exc).__name__,"message":str(exc)};attempts.append(attempt|{"outcome":"INVALID_ATTEMPT","error":error,"error_sha256":digest(canonical(error))})

def _analysis(eval_rows:Sequence[Mapping[str,object]],selected:Sequence[str])->dict[str,object]:
    by={(str(x["variant_id"]),int(x["seed"]),str(x["condition_id"])):x for x in eval_rows};comparators=("P4-legacy","P6-res0p5-slew48");contrasts=[]
    for vi,variant in enumerate(selected):
        for ci,comparator in enumerate(comparators):
            metrics={}
            for mi,metric in enumerate(("absolute_working","recovery_fraction","clamp_fraction","discontinuity_mean","p95_error_m")):
                cells=[]
                for seed in EVALUATION_SEEDS:
                    for condition in CORE_CONDITIONS:
                        def value(row:Mapping[str,object])->float:
                            if metric=="absolute_working":return float(row[metric])
                            if metric=="recovery_fraction":return float(row["metrics"]["recovered_events"])/max(1,float(row["metrics"]["displacement_events"]))
                            return float(row["metrics"][metric])
                        cells.append({"seed":seed,"condition_id":condition,"difference":value(by[(variant,seed,condition)])-value(by[(comparator,seed,condition)])})
                metrics[metric]={"direction":"P4_MINUS_COMPARATOR","cells":cells,"interval":paired_interval(cells,seed=20261600+vi*20+ci*10+mi)}
            contrasts.append({"p4_variant":variant,"comparator":comparator,"metrics":metrics})
    annotations=[]
    for variant in (*selected,*comparators):
        domain=sorted((x for x in eval_rows if x["variant_id"]==variant),key=lambda x:(x["seed"],x["condition_id"]))
        for label,pool in(("WORKING",[x for x in domain if x["absolute_working"]]),("NONWORKING",[x for x in domain if not x["absolute_working"]])):annotations.append({"variant_id":variant,"label":label if pool else"CLASS_NOT_OBSERVED","denominator":len(domain),"bundle":pool[0]["bundle"]if pool else None,"row_sha256":digest(canonical(pool[0]))if pool else None})
    return{"contrasts":contrasts,"annotations":annotations}

def run(output:Path=DEFAULT_OUTPUT)->dict[str,object]:
    SafetyConfig.from_mapping(os.environ).require_simulation_only()
    if output.exists():raise FileExistsError(output)
    contracts=importlib.import_module("experiments.01_policy_control.src.contracts");evaluate=importlib.import_module("experiments.01_policy_control.src.evaluate");timing=importlib.import_module("experiments.01_policy_control.src.timing");arm=importlib.import_module("experiments.01_policy_control.src.arm");rep=importlib.import_module("experiments.01_policy_control.src.representations");mods=(contracts,evaluate,timing,arm);base=contracts.load_config(ROOT/"experiments/01_policy_control/configs/base.yaml");cfg=aggressive_config(base);core={x.condition_id:x for x in evaluate.core_conditions(cfg)};probes={x.condition_id:x for x in evaluate.probe_conditions(cfg)}
    if tuple(core)!=CORE_CONDITIONS or tuple(probes)!=FAULT_CONDITIONS:raise RuntimeError("condition domain drifted")
    output.mkdir(parents=True);head=git("rev-parse","HEAD").decode().strip();ledger=source_ledger();ledger_sha=digest(canonical(ledger));rows=[];attempts=[];scenarios={};configs={};started=datetime.now(timezone.utc).isoformat();tune_conditions={k:core[k]for k in TUNING_CONDITIONS}
    specs={name:rep.P4ExecutorTuning(n,ff)for name,n,ff in variant_specs()}
    for name,n,ff in variant_specs():_execute(output,"tuning",name,"P4",cfg,{"lookahead_ticks":n,"dq_feedforward":ff},specs[name],tune_conditions,TUNING_SEEDS,base,mods,head,ledger,ledger_sha,rows,attempts,scenarios,configs)
    tuning=[x for x in rows if x["phase"]=="tuning"]
    if len(tuning)!=DECLARED["tuning"]or any(x["outcome"]!="VALID"for x in attempts):raise RuntimeError("tuning incomplete")
    selected=select_top_two(tuning);selection={"schema_version":1,"disposition":"FROZEN_BEFORE_EVALUATION","rule":["WORKING_COUNT_DESC","RECOVERED_EVENTS_DESC","CLAMP_MEAN_ASC","DISCONTINUITY_MEAN_ASC","IK_FAILURES_ASC","VARIANT_ID_ASC"],"selected":list(selected),"tuning_rows_sha256":digest(canonical(tuning))};(output/"selection.json").write_bytes(canonical(selection))
    for name in selected:_execute(output,"evaluation",name,"P4",cfg,thaw(specs[name]),specs[name],core,EVALUATION_SEEDS,base,mods,head,ledger,ledger_sha,rows,attempts,scenarios,configs)
    _execute(output,"evaluation","P4-legacy","P4",cfg,{"lookahead_ticks":1,"dq_feedforward":False,"role":"legacy_executor"},None,core,EVALUATION_SEEDS,base,mods,head,ledger,ledger_sha,rows,attempts,scenarios,configs)
    p6cfg=replace(cfg,residual=replace(cfg.residual,component_limit_rad=.5));_execute(output,"evaluation","P6-res0p5-slew48","P6",p6cfg,{"residual_component_limit_rad":.5,"role":"strong_comparator"},None,core,EVALUATION_SEEDS,base,mods,head,ledger,ledger_sha,rows,attempts,scenarios,configs)
    evaluation=[x for x in rows if x["phase"]=="evaluation"]
    if len(evaluation)!=DECLARED["evaluation"]:raise RuntimeError("evaluation incomplete")
    top=selected[0];_execute(output,"fault",top,"P4",cfg,thaw(specs[top]),specs[top],probes,FAULT_SEEDS,base,mods,head,ledger,ledger_sha,rows,attempts,scenarios,configs)
    if len(rows)!=DECLARED["total"]or len(attempts)!=DECLARED["total"]or any(x["outcome"]!="VALID"for x in attempts):raise RuntimeError("P4 rescue incomplete")
    analysis=_analysis(evaluation,selected);summary={"schema_version":1,"disposition":"PRELIMINARY_NONCONFIRMATORY_ENGINEERING_P4_RESCUE","scientific_use":"ENGINEERING_ONLY_NOT_PILOT_OR_PROMOTION","started_utc":started,"completed_utc":datetime.now(timezone.utc).isoformat(),"execution_implementation_sha":head,"source_ledger":ledger,"source_ledger_sha256":ledger_sha,"script_sha256":digest(Path(__file__).read_bytes()),"runtime":{"python":platform.python_version(),"numpy":np.__version__,"mujoco":mujoco.__version__,"os_arch":f"{platform.system()}-{platform.machine()}"},"domains":{"tuning_conditions":list(TUNING_CONDITIONS),"core_conditions":list(CORE_CONDITIONS),"fault_conditions":list(FAULT_CONDITIONS),"tuning_seeds":list(TUNING_SEEDS),"evaluation_seeds":list(EVALUATION_SEEDS),"fault_seeds":list(FAULT_SEEDS),"declared_rollouts":DECLARED},"mechanism_probe":mechanism_probe(cfg),"selection":selection,"configurations":configs,"conditions":{**{k:thaw(v)for k,v in core.items()},**{k:thaw(v)for k,v in probes.items()}},"scenarios":scenarios,"attempts":attempts,"rollouts":rows,"paired_analysis":analysis};(output/"summary.json").write_bytes(canonical(summary));files=[file_row(p,output)for p in sorted(output.rglob("*"))if p.is_file()];manifest={"schema_version":1,"disposition":"COMPLETE_ENGINEERING_NONCONFIRMATORY","counts":DECLARED,"files":files};(output/"manifest.json").write_bytes(canonical(manifest));return{"selected":selected,"rollouts":len(rows),"manifest_sha256":digest(canonical(manifest))}

def reconstruct(output:Path)->dict[str,object]:
    summary=json.loads((output/"summary.json").read_text());manifest=json.loads((output/"manifest.json").read_text());actual=[file_row(p,output)for p in sorted(output.rglob("*"))if p.is_file()and p.name!="manifest.json"]
    if manifest["files"]!=actual:raise ValueError("manifest inventory mismatch")
    for row in summary["rollouts"]:
        bundle=output/row["bundle"];validated=validate_rollout(bundle)
        if[row for row in [file_row(p,output)for p in sorted(bundle.iterdir())if p.is_file()]][0:]!=row["bundle_files"]or thaw(validated.metrics)!=row["metrics"]:raise ValueError("rollout reconstruction mismatch")
    tuning=[x for x in summary["rollouts"]if x["phase"]=="tuning"];selected=select_top_two(tuning);evaluation=[x for x in summary["rollouts"]if x["phase"]=="evaluation"]
    if list(selected)!=summary["selection"]["selected"]or _analysis(evaluation,selected)!=summary["paired_analysis"]:raise ValueError("analysis reconstruction mismatch")
    return{"selected":selected,"rollouts":len(summary["rollouts"]),"manifest_sha256":digest(canonical(manifest))}
def main()->None:
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=DEFAULT_OUTPUT);p.add_argument("--reconstruct",action="store_true");a=p.parse_args();print(canonical(reconstruct(a.output)if a.reconstruct else run(a.output)).decode(),end="")
if __name__=="__main__":main()
