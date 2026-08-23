from __future__ import annotations

import importlib
import hashlib
import inspect
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from reflect.rollout import sha256_json

from .helpers import config, policy_input


rep=importlib.import_module("experiments.01_policy_control.src.representations")
contracts=importlib.import_module("experiments.01_policy_control.src.contracts")
arm=importlib.import_module("experiments.01_policy_control.src.arm")
kin=importlib.import_module("experiments.01_policy_control.src.kinematics")


def test_p4_executor_tuning_is_closed_and_strict() -> None:
    assert rep.P4ExecutorTuning(12,True).lookahead_ticks==12
    for ticks in (0,2,50,True):
        with pytest.raises(ValueError):rep.P4ExecutorTuning(ticks,False)
    with pytest.raises(ValueError):rep.P4ExecutorTuning(12,1)


def test_p4_lookahead_and_feedforward_are_truth_free_bounded_and_legacy_safe() -> None:
    cfg=config();value=policy_input(period_ns=100_000_000,response_ns=300_000_000);chunk=rep.emit_chunk(contracts.CommandStack.P4,value,cfg);q=np.array([.3,-.6,.25]);state=rep.initial_executor_state(q)
    legacy,_,_=rep.reference_for_tick(contracts.CommandStack.P4,chunk,q,np.zeros(3),chunk.valid_from_ns,state,cfg)
    one=rep.with_p4_executor_tuning(chunk,rep.P4ExecutorTuning(1,False));off=rep.with_p4_executor_tuning(chunk,rep.P4ExecutorTuning(12,False));on=rep.with_p4_executor_tuning(chunk,rep.P4ExecutorTuning(12,True))
    one_ref,_,_=rep.reference_for_tick(contracts.CommandStack.P4,one,q,np.zeros(3),chunk.valid_from_ns,state,cfg)
    off_ref,_,_=rep.reference_for_tick(contracts.CommandStack.P4,off,q,np.zeros(3),chunk.valid_from_ns,state,cfg);on_ref,_,_=rep.reference_for_tick(contracts.CommandStack.P4,on,q,np.zeros(3),chunk.valid_from_ns,state,cfg)
    assert legacy.q_ref.tobytes()==one_ref.q_ref.tobytes()
    assert not np.array_equal(legacy.q_ref,off_ref.q_ref)
    assert np.array_equal(off_ref.q_ref,on_ref.q_ref)
    assert np.array_equal(legacy.dq_ref,np.zeros(3)) and np.array_equal(off_ref.dq_ref,np.zeros(3))
    assert np.linalg.norm(on_ref.dq_ref)>0 and np.max(np.abs(on_ref.dq_ref))<=cfg.controller.qdot_limit_rad_s
    assert set(inspect.signature(rep.reference_for_tick).parameters)=={"stack","chunk","q","dq","time_ns","state","config"}


def test_p4_lookahead_uses_current_xy_and_500hz_tick_units_not_future_knots() -> None:
    base=config();cfg=replace(base,controller=replace(base.controller,reference_slew_rad_s=48.));value=policy_input(period_ns=100_000_000,response_ns=300_000_000);chunk=rep.emit_chunk(contracts.CommandStack.P4,value,cfg);q=np.array([.3,-.6,.25]);state=rep.initial_executor_state(q);tuned=rep.with_p4_executor_tuning(chunk,rep.P4ExecutorTuning(49,True))
    ref,_,_=rep.reference_for_tick(contracts.CommandStack.P4,tuned,q,np.zeros(3),chunk.valid_from_ns,state,cfg)
    candidate,qdot=kin.differential_ik_command(chunk.actions[0],q,cfg.arm.link_lengths_m,cfg.controller.ik_damping_candidates[0],cfg,lookahead_ticks=49)
    expected=q+np.clip(candidate-q,-48*cfg.arm.timestep_s,48*cfg.arm.timestep_s)
    assert ref.q_ref.tobytes()==expected.tobytes()
    assert ref.dq_ref.tobytes()==qdot.tobytes()
    assert np.allclose(candidate,q+qdot*49*cfg.arm.timestep_s)
    assert tuned.actions.tobytes()==chunk.actions.tobytes() and tuned.dt_s==chunk.dt_s


def test_pd_velocity_feedforward_defaults_to_exact_legacy_and_is_bounded() -> None:
    cfg=config();q=np.array([.1,-.2,.3]);dq=np.array([.2,-.1,.05]);target=np.array([.15,-.25,.35]);previous=np.array([.14,-.24,.34])
    legacy=arm.bounded_pd(q,dq,target,previous,5.,.5,cfg)
    zero=arm.bounded_pd(q,dq,target,previous,5.,.5,cfg,desired_dq=np.zeros(3))
    fed=arm.bounded_pd(q,dq,target,previous,5.,.5,cfg,desired_dq=np.array([4.,-4.,4.]))
    assert legacy[0].tobytes()==zero[0].tobytes() and legacy[1].tobytes()==zero[1].tobytes() and legacy[2]==zero[2]
    assert not np.array_equal(fed[1],legacy[1])
    assert np.all(fed[1]>=cfg.arm.torque_min_nm) and np.all(fed[1]<=cfg.arm.torque_max_nm)


def test_joint_limit_outward_feedforward_is_suppressed_and_safe_hold_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg=config();value=policy_input();chunk=rep.with_p4_executor_tuning(rep.emit_chunk(contracts.CommandStack.P4,value,cfg),rep.P4ExecutorTuning(49,True));q=np.full(3,cfg.arm.joint_max_rad);state=rep.initial_executor_state(q)
    monkeypatch.setattr(rep,"differential_ik_command",lambda *args,**kwargs:(q+.5,np.ones(3)))
    ref,_,_=rep.reference_for_tick(contracts.CommandStack.P4,chunk,q,np.zeros(3),chunk.valid_from_ns,state,cfg)
    assert np.array_equal(ref.q_ref,q) and np.array_equal(ref.dq_ref,np.zeros(3))
    timing=importlib.import_module("experiments.01_policy_control.src.timing");hold=timing.SafeHoldCommand(q,np.zeros(3));assert np.array_equal(hold.dq_ref,np.zeros(3))


@pytest.mark.parametrize(
    ("joint_limit", "outward_velocity", "inward_velocity"),
    (("max", 1.0, -1.0), ("min", -1.0, 1.0)),
)
def test_exact_joint_limit_suppresses_only_outward_feedforward(
    monkeypatch: pytest.MonkeyPatch,
    joint_limit: str,
    outward_velocity: float,
    inward_velocity: float,
) -> None:
    cfg=config();value=policy_input();chunk=rep.with_p4_executor_tuning(rep.emit_chunk(contracts.CommandStack.P4,value,cfg),rep.P4ExecutorTuning(49,True))
    limit=cfg.arm.joint_max_rad if joint_limit=="max" else cfg.arm.joint_min_rad
    q=np.full(3,limit);state=rep.initial_executor_state(q)
    monkeypatch.setattr(rep,"differential_ik_command",lambda *args,**kwargs:(q.copy(),np.full(3,outward_velocity)))
    outward,_,_=rep.reference_for_tick(contracts.CommandStack.P4,chunk,q,np.zeros(3),chunk.valid_from_ns,state,cfg)
    assert np.array_equal(outward.q_ref,q)
    assert np.array_equal(outward.dq_ref,np.zeros(3))
    monkeypatch.setattr(rep,"differential_ik_command",lambda *args,**kwargs:(q.copy(),np.full(3,inward_velocity)))
    inward,_,_=rep.reference_for_tick(contracts.CommandStack.P4,chunk,q,np.zeros(3),chunk.valid_from_ns,state,cfg)
    assert np.array_equal(inward.q_ref,q)
    assert np.array_equal(inward.dq_ref,np.full(3,inward_velocity))


def test_rescue_grid_and_selection_are_exact() -> None:
    rescue=importlib.import_module("experiments.01_policy_control.engineering_p4_rescue")
    assert rescue.LOOKAHEADS==(1,12,25,49) and rescue.FEEDFORWARD==(False,True)
    assert len(rescue.variant_specs())==8 and len({x[0] for x in rescue.variant_specs()})==8
    rows=[]
    for name,working,recovered,clamp,disc,ik in (("b",10,20,.01,.02,0),("a",10,20,.01,.02,0),("c",11,18,.03,.04,1)):
        rows.append({"variant_id":name,"absolute_working":working,"ik_failures":ik,"metrics":{"recovered_events":recovered,"clamp_fraction":clamp,"discontinuity_mean":disc}})
    for name in ("d","e","f","g","h"):rows.append({"variant_id":name,"absolute_working":0,"ik_failures":0,"metrics":{"recovered_events":0,"clamp_fraction":1.,"discontinuity_mean":1.}})
    assert rescue.select_top_two(rows)==("c","a")
    probe=rescue.mechanism_probe(rescue.aggressive_config(config()))
    assert probe["pre_slew_distinct"] is True and probe["post_slew_distinct_count"]==4
    assert {row["lookahead_ticks"] for row in probe["rows"]}=={1,12,25,49}
    assert all(row["tick_seconds"]==.002 and row["qdot_max_abs"]<=4. for row in probe["rows"])


def test_tuned_p4_episode_records_feedforward_and_zero_dq_safe_hold() -> None:
    rescue=importlib.import_module("experiments.01_policy_control.engineering_p4_rescue");evaluate=importlib.import_module("experiments.01_policy_control.src.evaluate");timing=importlib.import_module("experiments.01_policy_control.src.timing");cfg=rescue.aggressive_config(config());identity=evaluate.EpisodeIdentity(implementation_sha="1"*40,working_tree_clean=True,dirty_diff_hash=None,source_lock_hash="2"*64,os_arch="test",cpu="test",gpu=None,python_version="3.11.13",dependency_versions={"numpy":np.__version__},task_config_hash=sha256_json(timing.scheduler_config(cfg)),model_hashes={"arm.xml":"3"*64})
    record=evaluate.run_episode(contracts.CommandStack.P4,evaluate.core_conditions(cfg)[0],evaluate.generate_scenario(20261301,cfg),cfg,identity,p4_executor_tuning=rep.P4ExecutorTuning(12,True));raw=record.metrics["raw_500hz"]
    assert any(any(abs(value)>0 for value in row) for row in raw["dq_ref"])
    assert all(not raw["safe_hold"][index] or np.array_equal(raw["dq_ref"][index],np.zeros(3)) for index in range(len(raw["tick"])))


def test_committed_p4_rescue_receipt_binds_reconstructable_raw_when_present() -> None:
    rescue=importlib.import_module("experiments.01_policy_control.engineering_p4_rescue")
    root=Path(rescue.__file__).resolve().parent
    receipt=json.loads((root/"ENGINEERING_P4_RESCUE_EVIDENCE.json").read_text())
    evidence=Path(rescue.ROOT)/receipt["evidence"]["relative_path"]
    assert receipt["disposition"]=="PRELIMINARY_MECHANISM_RESCUE_CANDIDATE_FOR_FORMAL_P4_PILOT_NO_PROMOTION"
    assert receipt["selected"]==["P4-lookahead1-dqon","P4-lookahead12-dqon"]
    assert receipt["aggregates"]["P4-lookahead1-dqon"]["working"]==88
    assert receipt["aggregates"]["P6-res0p5-slew48"]["working"]==96
    if evidence.is_dir():
        rows=[]
        for path in sorted(x for x in evidence.rglob("*") if x.is_file()):
            payload=path.read_bytes();rows.append({"path":path.relative_to(evidence).as_posix(),"bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest()})
        assert len(rows)==receipt["evidence"]["files"]
        assert sum(row["bytes"] for row in rows)==receipt["evidence"]["bytes"]
        assert hashlib.sha256(rescue.canonical(rows)).hexdigest()==receipt["evidence"]["inventory_sha256"]
        assert rescue.reconstruct(evidence)["manifest_sha256"]==receipt["evidence"]["manifest_sha256"]
