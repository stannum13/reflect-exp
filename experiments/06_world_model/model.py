"""Truth-free controls and compact ridge ensembles for Experiment 06."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Iterable, Sequence
import numpy as np
from . import world

SELECTORS=("DIRECT","W0","W1","W1V2","W2","W3","W4","W3R","W4R","W5")
LEARNED=("W3","W4","W3R","W4R")
W5_THRESHOLD_QUANTILES=(.25,.5,.75)
V4_MODELS_SHA256="70666cdd4226a05e00d0a1b4552fd27760f91d42ca7f93dca4d0706e046a20de"

@dataclass(frozen=True)
class DatasetRow:
    partition:str; stratum:str; scene_id:str; anchor_id:str; candidate_id:str; strategy_id:str
    state_features:tuple[float,...]; commands:np.ndarray; action_sha256:str; terminal_state:tuple[float,...]
    position_error_m:float; orientation_error_rad:float; collision:bool; action_energy:float; unsafe:bool
    success:bool; terminal_failure:bool; actual_cost:float; outcome_sha256:str

@dataclass(frozen=True)
class FittedModel:
    selector_id:str; alpha:float; feature_mean:tuple[float,...]; feature_scale:tuple[float,...]
    coefficient_shape:tuple[int,int]; coefficients:tuple[float,...]; intercept:tuple[float,...]
    fit_scene_ids:tuple[str,...]; tuning_scene_ids:tuple[str,...]; model_sha256:str
    member_alphas:tuple[float,...]=(); selected_for_evaluation:bool=False

@dataclass(frozen=True)
class Prediction:
    selector_id:str; scene_id:str; stratum:str; anchor_id:str; candidate_id:str; strategy_id:str
    predicted_cost:float; predicted_position_error_m:float; predicted_orientation_error_rad:float
    predicted_collision_probability:float; predicted_unsafe_probability:float; predicted_success_probability:float
    uncertainty:float; model_sha256:str

@dataclass(frozen=True)
class Selection:
    selector_id:str; scene_id:str; stratum:str; anchor_id:str; candidate_id:str; strategy_id:str
    selected_actual_cost:float; oracle_actual_cost:float; regret:float; spearman:float|None; success:bool; collision:bool
    source_selector:str|None=None; confidence_score:float|None=None

@dataclass(frozen=True)
class HybridCalibration:
    selected_residual:str; threshold_quantiles:tuple[float,...]; candidate_thresholds:tuple[float,...]
    selected_quantile:float; selected_threshold:float; training_residual_scale:float
    training_scene_ids:tuple[str,...]; tuning_scene_ids:tuple[str,...]; parent_model_sha256s:tuple[str,...]
    tuning_residual_use_fraction:float; calibration_sha256:str

def frozen_models_sha256(models:Sequence[FittedModel])->str:
    return hashlib.sha256(world.canonical([asdict(item) for item in models])).hexdigest()

def load_models(payload:bytes)->tuple[FittedModel,...]:
    value=json.loads(payload)
    if world.canonical(value)!=payload or not isinstance(value,list):raise ValueError("model bytes are not canonical")
    exact=set(FittedModel.__dataclass_fields__);models=[]
    for row in value:
        if not isinstance(row,dict) or set(row)!=exact:raise ValueError("model schema is not exact")
        converted={**row,"feature_mean":tuple(row["feature_mean"]),"feature_scale":tuple(row["feature_scale"]),"coefficient_shape":tuple(row["coefficient_shape"]),"coefficients":tuple(row["coefficients"]),"intercept":tuple(row["intercept"]),"fit_scene_ids":tuple(row["fit_scene_ids"]),"tuning_scene_ids":tuple(row["tuning_scene_ids"]),"member_alphas":tuple(row["member_alphas"])}
        item=FittedModel(**converted);wire=[item.selector_id,item.member_alphas,item.feature_mean,item.feature_scale,item.coefficient_shape,item.coefficients,item.intercept,item.fit_scene_ids,item.tuning_scene_ids]
        if hashlib.sha256(world.canonical(wire)).hexdigest()!=item.model_sha256:raise ValueError("model record hash mismatch")
        models.append(item)
    result=tuple(models)
    if tuple(x.selector_id for x in result)!=LEARNED or sum(x.selected_for_evaluation for x in result)!=1:raise ValueError("model set mismatch")
    return result

def load_frozen_models(payload:bytes)->tuple[FittedModel,...]:
    result=load_models(payload)
    if frozen_models_sha256(result)!=V4_MODELS_SHA256:raise ValueError("frozen v4 model set mismatch")
    return result

def load_calibration(payload:bytes,fitted:Sequence[FittedModel])->HybridCalibration:
    value=json.loads(payload)
    if world.canonical(value)!=payload or not isinstance(value,dict) or set(value)!=set(HybridCalibration.__dataclass_fields__):raise ValueError("calibration schema or encoding is invalid")
    converted={**value,"threshold_quantiles":tuple(value["threshold_quantiles"]),"candidate_thresholds":tuple(value["candidate_thresholds"]),"training_scene_ids":tuple(value["training_scene_ids"]),"tuning_scene_ids":tuple(value["tuning_scene_ids"]),"parent_model_sha256s":tuple(value["parent_model_sha256s"])};item=HybridCalibration(**converted)
    wire=[item.selected_residual,item.threshold_quantiles,item.candidate_thresholds,item.selected_quantile,item.selected_threshold,item.training_residual_scale,item.training_scene_ids,item.tuning_scene_ids,item.parent_model_sha256s,item.tuning_residual_use_fraction,"linear"]
    if hashlib.sha256(world.canonical(wire)).hexdigest()!=item.calibration_sha256 or item.threshold_quantiles!=W5_THRESHOLD_QUANTILES or item.parent_model_sha256s!=tuple(x.model_sha256 for x in fitted) or item.selected_residual!=next(x.selector_id for x in fitted if x.selected_for_evaluation):raise ValueError("calibration hash or parent mismatch")
    if not .25<=item.tuning_residual_use_fraction<=.75 or item.selected_quantile not in W5_THRESHOLD_QUANTILES:raise ValueError("calibration coverage or threshold domain is invalid")
    return item

def scene_features(scene:world.Scene,anchor:world.Anchor)->tuple[float,...]:
    geometry=(1.,0.) if scene.geometry=="disk" else (0.,1.); obstacle=(0.,)*5 if scene.obstacle is None else (1.,*scene.obstacle)
    return tuple(float(x) for x in (*anchor.eef_xy,*anchor.object_state,*scene.target_xy,scene.target_yaw,scene.mass,scene.friction,*geometry,*scene.dimensions,*obstacle))

def dataset_rows(scene:world.Scene,anchors:Sequence[world.Anchor],candidates:Sequence[world.Candidate],outcomes:Sequence[world.Outcome])->tuple[DatasetRow,...]:
    aa={x.anchor_id:x for x in anchors}; cc={x.candidate_id:x for x in candidates}
    if len(aa)!=2 or len(cc)!=16 or len(outcomes)!=16: raise ValueError("one dataset scene requires 2 anchors and 16 candidates")
    return tuple(DatasetRow(scene.spec.partition,scene.spec.stratum,scene.spec.scene_id,o.anchor_id,o.candidate_id,o.strategy_id,scene_features(scene,aa[o.anchor_id]),cc[o.candidate_id].commands,cc[o.candidate_id].action_sha256,o.terminal_state,o.position_error_m,o.orientation_error_rad,o.collision,o.action_energy,o.unsafe,o.success,o.terminal_failure,o.actual_cost,o.outcome_sha256) for o in outcomes)

def _energy(row:DatasetRow)->float:return float(np.sum(np.square(np.asarray(row.commands)))*world.COMMAND_DT)
def _one_hot(strategy:str)->np.ndarray:
    x=np.zeros(len(world.STRATEGIES));x[world.STRATEGIES.index(strategy)]=1.;return x

def _base_terminal(row:DatasetRow)->tuple[np.ndarray,float,float,float,float]:
    """Quasi-static contact/obstacle control, using input state/actions only."""
    s=np.asarray(row.state_features);obj=s[2:4].copy();yaw=float(s[4]);target=s[5:7];eef=s[:2].copy();mass=max(float(s[8]),.1);friction=max(float(s[9]),.05);radius=float(s[12] if s[10] else max(s[13:15]));collision=0.;obstacle=None if s[15]==0 else (s[16:18],s[18:20])
    for command in np.asarray(row.commands):
        eef+=command*world.COMMAND_DT;offset=obj-eef;distance=float(np.linalg.norm(offset));direction=np.array((1.,0.)) if distance==0 else offset/distance;approach=max(0.,float(np.dot(command,direction)))
        if distance<=radius+.055 and approach>0:
            motion=min(.9,.62/(mass*(.55+friction)))*command*world.COMMAND_DT;obj+=motion;yaw+=.35*float(direction[0]*motion[1]-direction[1]*motion[0])/max(radius,.03)
        if obstacle is not None:
            a,b=obstacle;ab=b-a;t=float(np.clip(np.dot(obj-a,ab)/max(np.dot(ab,ab),1e-12),0,1));collision=max(collision,float(np.linalg.norm(obj-(a+t*ab))<=radius+.02))
    pos=float(np.linalg.norm(obj-target));ye=abs((yaw-float(s[7])+math.pi)%(2*math.pi)-math.pi);success=float(pos<=.05 and ye<=.2 and not collision);failure=float(pos>.05 or ye>.2)
    return np.array((obj[0],obj[1],yaw)),collision,failure,success,pos

def _w1(row:DatasetRow)->float:
    s=np.asarray(row.state_features);obj=s[2:4];target=s[5:7];delta=target-obj;u=np.array((1.,0.)) if np.linalg.norm(delta)==0 else delta/np.linalg.norm(delta);q=np.sum(row.commands,axis=0)*world.COMMAND_DT;pred=obj+.55*max(0.,float(np.dot(q,u)))*u;pos=float(np.linalg.norm(pred-target));yaw=abs((s[4]-s[7]+math.pi)%(2*math.pi)-math.pi);collision=.5 if s[-5]==1. else 0.;return pos**2+.1*yaw**2+2*collision+.01*_energy(row)+4*float(pos>.05)-float(pos<=.05 and yaw<=.2)

def _w1v2(row:DatasetRow)->Prediction:
    terminal,collision,failure,success,pos=_base_terminal(row);s=np.asarray(row.state_features);yaw=abs((terminal[2]-s[7]+math.pi)%(2*math.pi)-math.pi);cost=pos**2+.1*yaw**2+2*collision+.01*_energy(row)+4*failure-success
    return Prediction("W1V2",row.scene_id,row.stratum,row.anchor_id,row.candidate_id,row.strategy_id,float(cost),pos,yaw,collision,failure,success,0.,hashlib.sha256(world.canonical(["W1-v2-quasistatic"])).hexdigest())

def _features(row:DatasetRow,selector:str)->np.ndarray:
    s=np.asarray(row.state_features);c=np.asarray(row.commands);one=_one_hot(row.strategy_id);delta=s[5:7]-s[2:4];u=delta/max(float(np.linalg.norm(delta)),1e-12);perp=np.array((-u[1],u[0]));disp=np.sum(c,axis=0)*world.COMMAND_DT
    summary=np.array((*disp,float(np.dot(disp,u)),float(np.dot(disp,perp)),float(np.sum(np.linalg.norm(c,axis=1))*world.COMMAND_DT),*np.mean(c,axis=0),*np.std(c,axis=0),*np.max(np.abs(c),axis=0),_energy(row)))
    if selector=="W3":return np.concatenate((s,one,summary))
    if selector=="W4":return np.concatenate((s,one,c.ravel()))
    contact=np.array([float(np.linalg.norm(s[:2]-s[2:4])),float(np.linalg.norm(delta)),float(s[15]),float(s[8]),float(s[9]),float(s[12] if s[10] else max(s[13:15]))]);interactions=np.outer(one,np.array((summary[2],summary[3],summary[4],summary[-1]))).ravel()
    return np.concatenate((s,one,summary,contact,interactions))

def _targets(rows:Sequence[DatasetRow],selector:str)->np.ndarray:
    if selector=="W3":return np.asarray([[r.actual_cost] for r in rows])
    if selector=="W4":return np.asarray([[*r.terminal_state[:3],float(r.collision),float(r.unsafe),float(r.success)] for r in rows])
    if selector=="W3R":return np.asarray([[r.actual_cost-_w1v2(r).predicted_cost] for r in rows])
    out=[]
    for r in rows:
        base=_base_terminal(r)[0];out.append([*(np.asarray(r.terminal_state[:3])-base),float(r.collision),float(r.terminal_failure),float(r.success)])
    return np.asarray(out)

def _fit(rows:Sequence[DatasetRow],selector:str,alphas:tuple[float,...],tuning_ids:tuple[str,...])->FittedModel:
    x=np.vstack([_features(r,selector) for r in rows]);y=_targets(rows,selector);mean=x.mean(0);scale=np.where(x.std(0)==0,1.,x.std(0));z=(x-mean)/scale;ymean=y.mean(0);coefs=[np.linalg.solve(z.T@z+a*np.eye(z.shape[1]),z.T@(y-ymean)) for a in alphas];coef=np.concatenate(coefs,axis=1);fit_ids=tuple(sorted({r.scene_id for r in rows}));wire=[selector,alphas,mean.tolist(),scale.tolist(),coef.shape,coef.ravel().tolist(),ymean.tolist(),fit_ids,tuning_ids];digest=hashlib.sha256(world.canonical(wire)).hexdigest();return FittedModel(selector,alphas[0],tuple(mean),tuple(scale),coef.shape,tuple(coef.ravel()),tuple(ymean),fit_ids,tuning_ids,digest,alphas,False)

def _outputs(fitted:FittedModel,row:DatasetRow)->np.ndarray:
    coef=np.asarray(fitted.coefficients).reshape(fitted.coefficient_shape);raw=((_features(row,fitted.selector_id)-np.asarray(fitted.feature_mean))/np.asarray(fitted.feature_scale))@coef;return raw.reshape(len(fitted.member_alphas),len(fitted.intercept))+np.asarray(fitted.intercept)

def _prediction(fitted:FittedModel,row:DatasetRow)->Prediction:
    outputs=_outputs(fitted,row);out=outputs.mean(0);s=np.asarray(row.state_features)
    if fitted.selector_id in {"W3","W3R"}:
        unc=float(np.std(outputs[:,0]));cost=float((_w1v2(row).predicted_cost if fitted.selector_id=="W3R" else 0.)+out[0]);pos=math.sqrt(max(0.,cost));yaw=collision=unsafe=success=0.
    else:
        base=np.zeros(3) if fitted.selector_id=="W4" else _base_terminal(row)[0];terminal=base+out[:3];pos=float(np.linalg.norm(terminal[:2]-s[5:7]));yaw=abs((terminal[2]-s[7]+math.pi)%(2*math.pi)-math.pi);collision=float(np.clip(out[3],0,1));unsafe=float(np.clip(out[4],0,1));success=float(np.clip(out[5],0,1));cost=pos**2+.1*yaw**2+2*collision+.01*_energy(row)+4*unsafe-success
        member_costs=[]
        for member in outputs:
            member_terminal=base+member[:3];member_pos=float(np.linalg.norm(member_terminal[:2]-s[5:7]));member_yaw=abs((member_terminal[2]-s[7]+math.pi)%(2*math.pi)-math.pi);member_costs.append(member_pos**2+.1*member_yaw**2+2*float(np.clip(member[3],0,1))+.01*_energy(row)+4*float(np.clip(member[4],0,1))-float(np.clip(member[5],0,1)))
        unc=float(np.std(member_costs))
    return Prediction(fitted.selector_id,row.scene_id,row.stratum,row.anchor_id,row.candidate_id,row.strategy_id,float(cost),pos,yaw,collision,unsafe,success,unc,fitted.model_sha256)

def _groups(rows:Sequence[DatasetRow])->Iterable[tuple[tuple[str,str],list[DatasetRow]]]:
    grouped={}
    for r in rows:grouped.setdefault((r.scene_id,r.anchor_id),[]).append(r)
    for key in sorted(grouped):
        group=sorted(grouped[key],key=lambda r:r.candidate_id)
        if len(group)!=8:raise ValueError("selector group does not have eight candidates")
        yield key,group

def _tuning_regret(fitted:FittedModel,rows:Sequence[DatasetRow])->float:return float(np.mean([min(g,key=lambda r:(_prediction(fitted,r).predicted_cost,r.candidate_id)).actual_cost-min(r.actual_cost for r in g) for _,g in _groups(rows)]))

def fit_models(training_rows:Sequence[DatasetRow],tuning_rows:Sequence[DatasetRow])->tuple[FittedModel,...]:
    if not training_rows or any(r.partition!="train" for r in training_rows):raise ValueError("training partition is not closed")
    if not tuning_rows or any(r.partition!="tuning" for r in tuning_rows):raise ValueError("tuning partition is not closed")
    tids=tuple(sorted({r.scene_id for r in tuning_rows}));fit_ids={r.scene_id for r in training_rows}
    if fit_ids&set(tids):raise ValueError("training and tuning ancestry overlaps")
    legacy=[]
    for selector in ("W3","W4"):
        candidates=[_fit(training_rows,selector,(a,),tids) for a in (1e-3,1e-2,1e-1)];legacy.append(min(candidates,key=lambda x:(_tuning_regret(x,tuning_rows),x.alpha)))
    residual=[_fit(training_rows,s,(.1,1.,10.),tids) for s in ("W3R","W4R")];winner=min(residual,key=lambda x:(_tuning_regret(x,tuning_rows),x.selector_id)).selector_id
    residual=[FittedModel(**({**x.__dict__,"selected_for_evaluation":x.selector_id==winner})) for x in residual]
    return tuple((*legacy,*residual))

def predict_all(models:Sequence[FittedModel],rows:Sequence[DatasetRow])->tuple[Prediction,...]:
    if any(r.partition!="evaluation" for r in rows):raise ValueError("predictions require untouched evaluation rows")
    return _predict_rows(models,rows)

def _predict_rows(models:Sequence[FittedModel],rows:Sequence[DatasetRow])->tuple[Prediction,...]:
    by={x.selector_id:x for x in models}
    if set(by)!=set(LEARNED):raise ValueError("exact learned model set required")
    result=[]
    for r in rows:
        result.append(Prediction("W1",r.scene_id,r.stratum,r.anchor_id,r.candidate_id,r.strategy_id,_w1(r),0.,0.,0.,0.,0.,0.,hashlib.sha256(world.canonical(["W1-v1"])).hexdigest()));result.append(_w1v2(r));result.extend(_prediction(by[s],r) for s in LEARNED)
    return tuple(result)

def _ranks(values:Sequence[float])->np.ndarray:
    order=np.argsort(np.asarray(values),kind="stable");ranks=np.empty(len(order));ranks[order]=np.arange(len(order));return ranks
def _spearman(predicted:Sequence[float],actual:Sequence[float])->float:
    p=_ranks(predicted);a=_ranks(actual);return float(np.corrcoef(p,a)[0,1]) if len(p)>1 else 1.

def _segment_clearance(point:np.ndarray,a:np.ndarray,b:np.ndarray)->float:
    ab=b-a;t=float(np.clip(np.dot(point-a,ab)/max(float(np.dot(ab,ab)),1e-12),0.,1.));return float(np.linalg.norm(point-(a+t*ab)))

def _w5_confidence(group:Sequence[DatasetRow],fitted:Sequence[FittedModel],calibration:HybridCalibration)->tuple[float,tuple[float,float,float,float]]:
    by={x.selector_id:x for x in fitted};selected=by[calibration.selected_residual]
    distances=[float(np.sqrt(np.mean(np.square((_features(r,selected.selector_id)-np.asarray(selected.feature_mean))/np.asarray(selected.feature_scale))))) for r in group]
    selected_predictions=[_prediction(selected,r) for r in group]
    disagreement=max(p.uncertainty for p in selected_predictions)/calibration.training_residual_scale
    w3=[_prediction(by["W3R"],r).predicted_cost for r in group];w4=[_prediction(by["W4R"],r).predicted_cost for r in group]
    rank_disagreement=max(0.,(1.-_spearman(w3,w4))/2.)
    s=np.asarray(group[0].state_features);support=float(s[12] if s[10] else max(s[13:15]));contact_gap=abs(float(np.linalg.norm(s[:2]-s[2:4]))-(support+.055))/max(support,.03)
    obstacle_risk=0.
    if s[15]==1.:
        clearance=_segment_clearance(s[2:4],s[16:18],s[18:20]);obstacle_risk=max(0.,(support+.02-clearance)/max(support+.02,1e-12))
    components=(max(distances),float(disagreement),float(rank_disagreement),float(contact_gap+obstacle_risk))
    return float(np.mean(components)),components

def calibrate_w5(training_rows:Sequence[DatasetRow],tuning_rows:Sequence[DatasetRow],fitted:Sequence[FittedModel])->HybridCalibration:
    if not training_rows or any(r.partition!="train" for r in training_rows):raise ValueError("W5 training ancestry is not closed")
    if not tuning_rows or any(r.partition!="tuning" for r in tuning_rows):raise ValueError("W5 tuning ancestry is not closed")
    by={x.selector_id:x for x in fitted}
    if set(by)!=set(LEARNED):raise ValueError("W5 requires exact residual model parents")
    selected=next((x.selector_id for x in fitted if x.selected_for_evaluation),None)
    if selected not in {"W3R","W4R"}:raise ValueError("W5 residual parent selection is invalid")
    scale=float(np.median([abs(r.actual_cost-_w1v2(r).predicted_cost) for r in training_rows]));scale=max(scale,1e-12)
    provisional=HybridCalibration(selected,W5_THRESHOLD_QUANTILES,(),0.,0.,scale,tuple(sorted({r.scene_id for r in training_rows})),tuple(sorted({r.scene_id for r in tuning_rows})),tuple(x.model_sha256 for x in fitted),0.,"")
    predictions=_predict_rows(fitted,tuning_rows);lookup={(p.selector_id,p.scene_id,p.anchor_id,p.candidate_id):p for p in predictions};groups=list(_groups(tuning_rows));scores=[]
    for _,group in groups:scores.append(_w5_confidence(group,fitted,provisional)[0])
    thresholds=tuple(float(np.quantile(scores,q,method="linear")) for q in W5_THRESHOLD_QUANTILES);eligible=[]
    for q,threshold in zip(W5_THRESHOLD_QUANTILES,thresholds):
        use=[score<=threshold for score in scores];coverage=float(np.mean(use))
        if .25<=coverage<=.75:
            regrets=[]
            for (_,group),residual in zip(groups,use):
                source=selected if residual else "W1V2";chosen=min(group,key=lambda r:(lookup[(source,r.scene_id,r.anchor_id,r.candidate_id)].predicted_cost,r.candidate_id));regrets.append(chosen.actual_cost-min(r.actual_cost for r in group))
            eligible.append((float(np.mean(regrets)),q,threshold,coverage))
    if not eligible:raise ValueError("W5 tuning coverage has no eligible threshold")
    _,selected_q,selected_threshold,coverage=min(eligible,key=lambda x:(x[0],x[1],x[2]));wire=[selected,W5_THRESHOLD_QUANTILES,thresholds,selected_q,selected_threshold,scale,provisional.training_scene_ids,provisional.tuning_scene_ids,provisional.parent_model_sha256s,coverage,"linear"]
    digest=hashlib.sha256(world.canonical(wire)).hexdigest();return HybridCalibration(selected,W5_THRESHOLD_QUANTILES,thresholds,selected_q,selected_threshold,scale,provisional.training_scene_ids,provisional.tuning_scene_ids,provisional.parent_model_sha256s,coverage,digest)

def rank_selectors(predictions:Sequence[Prediction],rows:Sequence[DatasetRow],fitted:Sequence[FittedModel],calibration:HybridCalibration)->tuple[Selection,...]:
    lookup={(p.selector_id,p.scene_id,p.anchor_id,p.candidate_id):p for p in predictions};result=[];predicted=("W1","W1V2","W3","W4","W3R","W4R")
    for (sid,aid),group in _groups(rows):
        oracle=min(group,key=lambda r:(r.actual_cost,r.candidate_id));choices={"DIRECT":next(r for r in group if r.strategy_id=="DIRECT"),"W0":group[int.from_bytes(hashlib.sha256(world.canonical(["W0",sid,aid])).digest()[:8],"big")%8],"W2":oracle}
        for selector in predicted:choices[selector]=min(group,key=lambda r:(lookup[(selector,sid,aid,r.candidate_id)].predicted_cost,r.candidate_id))
        confidence,_=_w5_confidence(group,fitted,calibration);source=calibration.selected_residual if confidence<=calibration.selected_threshold else "W1V2";choices["W5"]=choices[source]
        for selector in SELECTORS:
            chosen=choices[selector];rank_source=source if selector=="W5" else selector;spear=_spearman([lookup[(rank_source,sid,aid,r.candidate_id)].predicted_cost for r in group],[r.actual_cost for r in group]) if rank_source in predicted else None;result.append(Selection(selector,sid,group[0].stratum,aid,chosen.candidate_id,chosen.strategy_id,chosen.actual_cost,oracle.actual_cost,max(0.,chosen.actual_cost-oracle.actual_cost),spear,chosen.success,chosen.collision,source if selector=="W5" else None,confidence if selector=="W5" else None))
    return tuple(result)

def aggregate_metrics(selections:Sequence[Selection],predictions:Sequence[Prediction],rows:Sequence[DatasetRow])->dict[str,object]:
    def aggregate(domain:Sequence[Selection])->dict[str,dict[str,float]]:
        output={}
        for selector in SELECTORS:
            selected=[x for x in domain if x.selector_id==selector];sids=sorted({x.scene_id for x in selected});ranks=[x.spearman for x in selected if x.spearman is not None];output[selector]={"mean_regret":float(np.mean([np.mean([x.regret for x in selected if x.scene_id==sid]) for sid in sids])),"mean_spearman":float(np.mean(ranks)) if ranks else 0.,"top1_accuracy":float(np.mean([x.regret<=1e-12 for x in selected])),"success_fraction":float(np.mean([x.success for x in selected])),"selected_collision_fraction":float(np.mean([x.collision for x in selected]))}
        return output
    def candidate_set(domain:Sequence[DatasetRow])->dict[str,float]:
        groups=[g for _,g in _groups(domain)];return {"candidate_collision_prevalence":float(np.mean([x.collision for x in domain])),"mixed_collision_anchor_fraction":float(np.mean([len({x.collision for x in g})>1 for g in groups])),"all_collision_anchor_fraction":float(np.mean([all(x.collision for x in g) for g in groups]))}
    truth={(r.scene_id,r.anchor_id,r.candidate_id):r for r in rows};quality={}
    for selector in ("W1V2","W3R","W4R"):
        ps=[p for p in predictions if p.selector_id==selector];quality[selector]={"cost_mae":float(np.mean([abs(p.predicted_cost-truth[(p.scene_id,p.anchor_id,p.candidate_id)].actual_cost) for p in ps])),"collision_brier":float(np.mean([(p.predicted_collision_probability-float(truth[(p.scene_id,p.anchor_id,p.candidate_id)].collision))**2 for p in ps])),"success_brier":float(np.mean([(p.predicted_success_probability-float(truth[(p.scene_id,p.anchor_id,p.candidate_id)].success))**2 for p in ps])),"uncertainty_coverage":float(np.mean([abs(p.predicted_cost-truth[(p.scene_id,p.anchor_id,p.candidate_id)].actual_cost)<=max(p.uncertainty,1e-12) for p in ps]))}
    strata={s:[x for x in selections if x.stratum==s] for s in world.STRATA};row_strata={s:[x for x in rows if x.stratum==s] for s in world.STRATA}
    w5=[x for x in selections if x.selector_id=="W5"];hybrid={"overall_residual_use_fraction":float(np.mean([x.source_selector in {"W3R","W4R"} for x in w5])),"strata_residual_use_fraction":{s:float(np.mean([x.source_selector in {"W3R","W4R"} for x in w5 if x.stratum==s])) for s in world.STRATA if any(x.stratum==s for x in w5)}}
    return {"overall":aggregate(selections),"strata":{s:aggregate(v) for s,v in strata.items() if v},"prediction_quality":quality,"candidate_set":{"overall":candidate_set(rows),"strata":{s:candidate_set(v) for s,v in row_strata.items() if v}},"hybrid":hybrid}

def quality_gate(metrics:dict[str,object],latency:dict[str,dict[str,int]],*,latency_limit_ns:int=5_000_000)->dict[str,object]:
    overall=metrics["overall"];strata=metrics["strata"];comparators=("W1V2","W3R","W0","DIRECT");available=[s for s in world.STRATA if s in strata];beaten=sum(all(strata[s]["W5"]["mean_regret"]<strata[s][c]["mean_regret"] for c in comparators) for s in available);coverage=metrics["hybrid"]["overall_residual_use_fraction"];checks={"beats_all_overall":all(overall["W5"]["mean_regret"]<overall[c]["mean_regret"] for c in comparators),"beats_all_in_four_of_five_strata":len(available)==5 and beaten>=4,"latency":latency["W5"]["p95_ns"]<=latency_limit_ns,"nontrivial_coverage":.1<=coverage<=.9};return {"authority":"ENGINEERING_NONCONFIRMATORY","selected_selector":"W5","comparators":list(comparators),"strata_beaten":beaten,"strata_observed":available,"residual_use_fraction":coverage,"checks":checks,"passed":all(checks.values())}
