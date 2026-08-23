"""Pure-NumPy learned and control selectors for Experiment 06."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Iterable, Sequence

import numpy as np

from . import world


@dataclass(frozen=True)
class DatasetRow:
    partition: str
    stratum: str
    scene_id: str
    anchor_id: str
    candidate_id: str
    strategy_id: str
    state_features: tuple[float, ...]
    commands: np.ndarray
    action_sha256: str
    terminal_state: tuple[float, ...]
    position_error_m: float
    orientation_error_rad: float
    collision: bool
    action_energy: float
    unsafe: bool
    success: bool
    terminal_failure: bool
    actual_cost: float
    outcome_sha256: str


@dataclass(frozen=True)
class FittedModel:
    selector_id: str
    alpha: float
    feature_mean: tuple[float, ...]
    feature_scale: tuple[float, ...]
    coefficient_shape: tuple[int, int]
    coefficients: tuple[float, ...]
    intercept: tuple[float, ...]
    fit_scene_ids: tuple[str, ...]
    tuning_scene_ids: tuple[str, ...]
    model_sha256: str


@dataclass(frozen=True)
class Prediction:
    selector_id: str
    scene_id: str
    stratum: str
    anchor_id: str
    candidate_id: str
    strategy_id: str
    predicted_cost: float
    predicted_position_error_m: float
    predicted_orientation_error_rad: float
    predicted_collision_probability: float
    predicted_unsafe_probability: float
    predicted_success_probability: float
    uncertainty: float
    model_sha256: str


@dataclass(frozen=True)
class Selection:
    selector_id: str
    scene_id: str
    stratum: str
    anchor_id: str
    candidate_id: str
    strategy_id: str
    selected_actual_cost: float
    oracle_actual_cost: float
    regret: float
    spearman: float | None
    success: bool
    collision: bool


def scene_features(scene: world.Scene, anchor: world.Anchor) -> tuple[float, ...]:
    geometry = (1.0, 0.0) if scene.geometry == "disk" else (0.0, 1.0)
    obstacle = (0.0,) * 5 if scene.obstacle is None else (1.0, *scene.obstacle)
    return tuple(float(x) for x in (*anchor.eef_xy, *anchor.object_state, *scene.target_xy, scene.target_yaw, scene.mass, scene.friction, *geometry, *scene.dimensions, *obstacle))


def dataset_rows(scene: world.Scene, anchors: Sequence[world.Anchor], candidates: Sequence[world.Candidate], outcomes: Sequence[world.Outcome]) -> tuple[DatasetRow, ...]:
    anchor_by_id = {item.anchor_id: item for item in anchors}; candidate_by_id = {item.candidate_id: item for item in candidates}
    if len(anchor_by_id) != 2 or len(candidate_by_id) != 16 or len(outcomes) != 16:
        raise ValueError("one dataset scene requires 2 anchors and 16 candidates")
    result=[]
    for outcome in outcomes:
        anchor=anchor_by_id[outcome.anchor_id];candidate=candidate_by_id[outcome.candidate_id]
        result.append(DatasetRow(scene.spec.partition,scene.spec.stratum,scene.spec.scene_id,anchor.anchor_id,candidate.candidate_id,candidate.strategy_id,scene_features(scene,anchor),candidate.commands,candidate.action_sha256,outcome.terminal_state,outcome.position_error_m,outcome.orientation_error_rad,outcome.collision,outcome.action_energy,outcome.unsafe,outcome.success,outcome.terminal_failure,outcome.actual_cost,outcome.outcome_sha256))
    return tuple(result)


def _one_hot(strategy: str) -> np.ndarray:
    result=np.zeros(len(world.STRATEGIES));result[world.STRATEGIES.index(strategy)]=1.0;return result


def _features(row: DatasetRow, selector: str) -> np.ndarray:
    state=np.asarray(row.state_features);commands=np.asarray(row.commands);one=_one_hot(row.strategy_id)
    if selector == "W3":
        displacement=np.sum(commands,axis=0)*world.COMMAND_DT;steps=np.diff(np.vstack((np.zeros((1,2)),commands)),axis=0)
        summary=np.concatenate((displacement,[float(np.sum(np.linalg.norm(commands,axis=1))*world.COMMAND_DT)],np.mean(commands,axis=0),np.std(commands,axis=0),np.max(np.abs(commands),axis=0),[row.action_energy]))
        return np.concatenate((state,one,summary))
    if selector == "W4":return np.concatenate((state,one,commands.ravel()))
    raise ValueError("unknown learned selector")


def _targets(rows: Sequence[DatasetRow], selector: str) -> np.ndarray:
    if selector == "W3":return np.asarray([[row.actual_cost] for row in rows])
    return np.asarray([[row.terminal_state[0],row.terminal_state[1],row.terminal_state[2],float(row.collision),float(row.unsafe),float(row.success)] for row in rows])


def _fit(rows: Sequence[DatasetRow], selector: str, alpha: float, tuning_ids: tuple[str,...]) -> FittedModel:
    x=np.vstack([_features(row,selector) for row in rows]);y=_targets(rows,selector);mean=np.mean(x,axis=0);scale=np.std(x,axis=0);scale=np.where(scale==0,1.0,scale);z=(x-mean)/scale;ymean=np.mean(y,axis=0);coef=np.linalg.solve(z.T@z+alpha*np.eye(z.shape[1]),z.T@(y-ymean));fit_ids=tuple(sorted({row.scene_id for row in rows}));wire=[selector,alpha,mean.tolist(),scale.tolist(),list(coef.shape),coef.ravel().tolist(),ymean.tolist(),list(fit_ids),list(tuning_ids)];digest=hashlib.sha256(world.canonical(wire)).hexdigest()
    return FittedModel(selector,alpha,tuple(mean),tuple(scale),coef.shape,tuple(coef.ravel()),tuple(ymean),fit_ids,tuning_ids,digest)


def _model_output(model: FittedModel,row: DatasetRow)->np.ndarray:
    mean=np.asarray(model.feature_mean);scale=np.asarray(model.feature_scale);coef=np.asarray(model.coefficients).reshape(model.coefficient_shape);return ( (_features(row,model.selector_id)-mean)/scale)@coef+np.asarray(model.intercept)


def _prediction(model: FittedModel,row: DatasetRow)->Prediction:
    output=_model_output(model,row)
    if model.selector_id=="W3":
        cost=float(output[0]);pos=max(0.0,math.sqrt(max(0.0,cost)));yaw=0.0;collision=unsafe=success=0.0
    else:
        pos=float(np.linalg.norm(output[:2]-np.asarray(row.state_features[5:7])));yaw=abs((float(output[2]-row.state_features[7])+math.pi)%(2*math.pi)-math.pi);collision=float(np.clip(output[3],0,1));unsafe=float(np.clip(output[4],0,1));success=float(np.clip(output[5],0,1));failure=1-success;cost=pos**2+.1*yaw**2+2*collision+.01*row.action_energy+4*failure-success
    return Prediction(model.selector_id,row.scene_id,row.stratum,row.anchor_id,row.candidate_id,row.strategy_id,float(cost),pos,yaw,collision,unsafe,success,0.0,model.model_sha256)


def _ranks(values: Sequence[float])->np.ndarray:
    values=np.asarray(values,dtype=float);order=np.argsort(values,kind="stable");result=np.empty(len(values),dtype=float);index=0
    while index<len(values):
        end=index+1
        while end<len(values) and values[order[end]]==values[order[index]]:end+=1
        result[order[index:end]]=(index+end-1)/2;index=end
    return result


def _spearman(predicted:Sequence[float],actual:Sequence[float])->float:
    p=_ranks(predicted);a=_ranks(actual)
    if np.all(p==p[0]) and np.all(a==a[0]):return 1.0
    if np.all(p==p[0]) or np.all(a==a[0]):return 0.0
    return float(np.corrcoef(p,a)[0,1])


def _tuning_regret(fitted:FittedModel,rows:Sequence[DatasetRow])->float:
    total=[]
    for _,group in _groups(rows):
        selected=min(group,key=lambda row:(_prediction(fitted,row).predicted_cost,row.candidate_id));total.append(selected.actual_cost-min(row.actual_cost for row in group))
    return float(np.mean(total))


def fit_models(training_rows: Sequence[DatasetRow], tuning_rows: Sequence[DatasetRow]) -> tuple[FittedModel,FittedModel]:
    if not training_rows or any(row.partition!="train" for row in training_rows):raise ValueError("training partition is not closed")
    if not tuning_rows or any(row.partition!="tuning" for row in tuning_rows):raise ValueError("tuning partition is not closed")
    training_ids={row.scene_id for row in training_rows};tuning_ids=tuple(sorted({row.scene_id for row in tuning_rows}))
    if training_ids & set(tuning_ids):raise ValueError("training and tuning ancestry overlaps")
    result=[]
    for selector in ("W3","W4"):
        candidates=[_fit(training_rows,selector,alpha,tuning_ids) for alpha in (1e-3,1e-2,1e-1)]
        result.append(min(candidates,key=lambda item:(_tuning_regret(item,tuning_rows),item.alpha)))
    return tuple(result)  # type: ignore[return-value]


def _groups(rows: Sequence[DatasetRow])->Iterable[tuple[tuple[str,str],list[DatasetRow]]]:
    grouped={}
    for row in rows:grouped.setdefault((row.scene_id,row.anchor_id),[]).append(row)
    for key in sorted(grouped):
        group=sorted(grouped[key],key=lambda row:row.candidate_id)
        if len(group)!=8:raise ValueError("selector group does not have eight candidates")
        yield key,group


def _w1(row:DatasetRow)->float:
    state=np.asarray(row.state_features);obj=state[2:4];target=state[5:7];delta=target-obj;u=np.array((1.,0.)) if np.linalg.norm(delta)==0 else delta/np.linalg.norm(delta);q=np.sum(row.commands,axis=0)*world.COMMAND_DT;pred=obj+.55*max(0.,float(np.dot(q,u)))*u;pos=float(np.linalg.norm(pred-target));yaw=abs((state[4]-state[7]+math.pi)%(2*math.pi)-math.pi);collision=.5 if state[-5]==1. else 0.;return pos**2+.1*yaw**2+2*collision+.01*row.action_energy+4*float(pos>.05)-float(pos<=.05 and yaw<=.2)


def predict_all(models:Sequence[FittedModel],rows:Sequence[DatasetRow])->tuple[Prediction,...]:
    if any(row.partition!="evaluation" for row in rows):raise ValueError("predictions require untouched evaluation rows")
    by_id={item.selector_id:item for item in models}
    if set(by_id)!={"W3","W4"}:raise ValueError("exact learned model set required")
    result=[]
    for row in rows:
        result.append(Prediction("W1",row.scene_id,row.stratum,row.anchor_id,row.candidate_id,row.strategy_id,_w1(row),0.,0.,0.,0.,0.,0.,hashlib.sha256(world.canonical(["W1-v1"])).hexdigest()))
        result.extend(_prediction(by_id[name],row) for name in ("W3","W4"))
    return tuple(result)


def rank_selectors(predictions:Sequence[Prediction],rows:Sequence[DatasetRow])->tuple[Selection,...]:
    lookup={(p.selector_id,p.scene_id,p.anchor_id,p.candidate_id):p for p in predictions};result=[]
    for (scene_id,anchor_id),group in _groups(rows):
        oracle=min(group,key=lambda row:(row.actual_cost,row.candidate_id));stratum=group[0].stratum
        random_index=int.from_bytes(hashlib.sha256(world.canonical(["W0",scene_id,anchor_id])).digest()[:8],"big")%8
        choices={"DIRECT":next(row for row in group if row.strategy_id=="DIRECT"),"W0":group[random_index],"W2":oracle}
        for selector in ("W1","W3","W4"):
            choices[selector]=min(group,key=lambda row:(lookup[(selector,scene_id,anchor_id,row.candidate_id)].predicted_cost,row.candidate_id))
        for selector in ("DIRECT","W0","W1","W2","W3","W4"):
            chosen=choices[selector];spearman=None
            if selector in {"W1","W3","W4"}:spearman=_spearman([lookup[(selector,scene_id,anchor_id,row.candidate_id)].predicted_cost for row in group],[row.actual_cost for row in group])
            result.append(Selection(selector,scene_id,stratum,anchor_id,chosen.candidate_id,chosen.strategy_id,chosen.actual_cost,oracle.actual_cost,max(0.,chosen.actual_cost-oracle.actual_cost),spearman,chosen.success,chosen.collision))
    return tuple(result)


def aggregate_metrics(selections:Sequence[Selection],predictions:Sequence[Prediction],rows:Sequence[DatasetRow])->dict[str,object]:
    del predictions,rows
    def aggregate(domain:Sequence[Selection])->dict[str,dict[str,float]]:
        output={}
        for selector in ("DIRECT","W0","W1","W2","W3","W4"):
            selected=[x for x in domain if x.selector_id==selector];scene_ids=sorted({x.scene_id for x in selected})
            scene_regret=[np.mean([x.regret for x in selected if x.scene_id==sid]) for sid in scene_ids];rank=[x.spearman for x in selected if x.spearman is not None]
            output[selector]={"mean_regret":float(np.mean(scene_regret)),"mean_spearman":float(np.mean(rank)) if rank else 0.0,"top1_accuracy":float(np.mean([x.regret<=1e-12 for x in selected])),"success_fraction":float(np.mean([x.success for x in selected])),"collision_fraction":float(np.mean([x.collision for x in selected]))}
        return output
    strata = {stratum: [x for x in selections if x.stratum == stratum] for stratum in world.STRATA}
    return {"overall":aggregate(selections),"strata":{stratum:aggregate(domain) for stratum,domain in strata.items() if domain}}
