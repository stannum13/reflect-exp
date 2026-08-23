from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np

from reflect.types import Constraint, ObjectBelief, Observation, Pose, Predicate, RobotState, SkillSpec


contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
evaluate = importlib.import_module("experiments.01_policy_control.src.evaluate")
BASE = Path(__file__).resolve().parents[1] / "configs/base.yaml"


def config():
    return contracts.load_config(BASE)


def resource_evidence(*, phase: str, complete: bool, predecessor: str | None = None):
    expected = tuple(f"P1:fixture:{index:03d}" for index in range(2))
    completed = expected if complete else ()
    return evaluate._resource_completion_from_validated_artifacts(
        phase=phase, revision=1,
        protocol_sha256=("9" if phase == "pilot" else "8") * 64,
        predecessor_protocol_sha256=None if phase == "pilot" else (predecessor or "9" * 64),
        disposition_sha256="f" * 64, expected_shard_ids=expected,
        completed_shard_ids=completed,
        ledger_sha256s=tuple(f"{100 + index:064x}" for index in range(len(completed))),
        completion_sha256s=tuple(f"{200 + index:064x}" for index in range(len(completed))),
        retained_bytes=1024 * len(completed), temporary_peak_bytes=0, quarantine_bytes=0,
    )


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
