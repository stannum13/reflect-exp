from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np

from reflect.types import Constraint, ObjectBelief, Observation, Pose, Predicate, RobotState, SkillSpec


contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
BASE = Path(__file__).resolve().parents[1] / "configs/base.yaml"


def config():
    return contracts.load_config(BASE)


def policy_input(period_ns: int = 100_000_000, response_ns: int = 300_000_000):
    target = np.array([0.62, 0.08])
    observation = Observation(
        sequence_id=7,
        source_time_ns=0,
        received_time_ns=0,
        robot_state=RobotState(q=np.array([0.35, -0.70, 0.35]), dq=np.zeros(3)),
        object_beliefs=(ObjectBelief("target", "target", target, 1.0, {}, 1.0, 0, ("synthetic",)),),
        current_skill_id="track",
        current_phase="track_target",
    )
    skill = SkillSpec(
        skill_id="track",
        skill_type="track_target",
        target_entities=("target",),
        target_pose=Pose(np.array([target[0], target[1], 0.0]), np.array([1.0, 0.0, 0.0, 0.0])),
        constraints=(Constraint("workspace", {"radius_m": 0.7}),),
        success_predicate=Predicate("eef_error", {"max_m": 0.025}),
        timeout_s=6.25,
        retry_budget=0,
    )
    q0 = np.array([0.35, -0.70, 0.35])
    kin = importlib.import_module("experiments.01_policy_control.src.kinematics")
    cfg = config()
    q1 = kin.absolute_ik(target, q0, cfg.arm.link_lengths_m, cfg.controller.ik_damping_candidates[0], cfg)
    return contracts.PolicyInput(observation, skill, response_ns, period_ns, q0, q1)
