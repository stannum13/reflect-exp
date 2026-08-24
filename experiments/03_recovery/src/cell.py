"""Frozen semantic cell, scenario domain, and architecture-independent precheck."""

from __future__ import annotations

from dataclasses import dataclass, replace
import importlib
import math

import numpy as np

from .contracts import (
    Architecture,
    EpisodeSpec,
    MemoryFact,
    MemorySnapshot,
    RecoveryLevel,
    ScenarioDomain,
    SkillRequest,
    base_memory_snapshot,
    canonical_bytes,
    sha256_bytes,
)


INJECTION_TICK = 750
PRIMARY_SEEDS = tuple(range(20261601, 20261609))
SENSITIVITY_SEEDS = tuple(range(20261601, 20261605))
PRIMARY_CONTROLLER = "P6-res0p5-slew48"
SENSITIVITY_CONTROLLER = "P4-lookahead1-dqon"


class SemanticPlanningError(ValueError):
    pass


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    domain: ScenarioDomain
    injection_tick: int | None
    parameters: tuple[tuple[str, float], ...]
    intended_level: RecoveryLevel
    scorer_label: str

    def __post_init__(self) -> None:
        if not isinstance(self.domain, ScenarioDomain) or not isinstance(self.intended_level, RecoveryLevel):
            raise ValueError("scenario enums must be closed")
        if self.injection_tick is not None and self.injection_tick != INJECTION_TICK:
            raise ValueError("disturbances must inject at tick 750")
        if self.domain is ScenarioDomain.ANCHOR and self.injection_tick is not None:
            raise ValueError("anchor schedules contain no injected event")
        if self.domain is not ScenarioDomain.ANCHOR and self.injection_tick != INJECTION_TICK:
            raise ValueError("disturbance schedule missing tick-750 event")
        if tuple(sorted(self.parameters)) != self.parameters:
            raise ValueError("scenario parameters must be canonical")
        if any(not key.isascii() or not math.isfinite(value) for key, value in self.parameters):
            raise ValueError("scenario parameters must be finite ASCII")

    @property
    def sha256(self) -> str:
        return sha256_bytes(canonical_bytes(self))


def scenario_specs() -> tuple[ScenarioSpec, ...]:
    return (
        ScenarioSpec("anchor-none", ScenarioDomain.ANCHOR, None, (), RecoveryLevel.NONE, "NO_DISTURBANCE"),
        ScenarioSpec("anchor-slow-policy", ScenarioDomain.ANCHOR, None, (("policy_delay_ticks", 25.0),), RecoveryLevel.NONE, "ORDINARY_VALID_DELAY"),
        ScenarioSpec("control-impulse", ScenarioDomain.CONTROL, INJECTION_TICK, (("impulse_dq_rad_s", 0.06),), RecoveryLevel.CONTROL, "CONTROL_IMPULSE"),
        ScenarioSpec("control-dropout", ScenarioDomain.CONTROL, INJECTION_TICK, (("dropout_ticks", 25.0),), RecoveryLevel.CONTROL, "CONTROL_COMMAND_DROPOUT"),
        ScenarioSpec("motion-target-shift", ScenarioDomain.MOTION, INJECTION_TICK, (("target_shift_m", 0.06),), RecoveryLevel.MOTION, "MOTION_TARGET_SHIFT"),
        ScenarioSpec("motion-path-infeasible", ScenarioDomain.MOTION, INJECTION_TICK, (("obstacle_clearance_m", 0.002),), RecoveryLevel.MOTION, "MOTION_PATH_INFEASIBLE"),
        ScenarioSpec("semantic-object-unavailable", ScenarioDomain.SEMANTIC, INJECTION_TICK, (), RecoveryLevel.SEMANTIC, "SEMANTIC_OBJECT_UNAVAILABLE"),
        ScenarioSpec("semantic-restriction-change", ScenarioDomain.SEMANTIC, INJECTION_TICK, (), RecoveryLevel.SEMANTIC, "SEMANTIC_RESTRICTION_CHANGE"),
    )


@dataclass(frozen=True)
class FeasibilityReceipt:
    feasible: bool
    reason: str
    controller_id: str
    scenario_sha256: str
    geometry_sha256: str
    architecture_domain_sha256: str


def _exp01_modules() -> tuple[object, object]:
    contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
    kinematics = importlib.import_module("experiments.01_policy_control.src.kinematics")
    return contracts, kinematics


def controller_config(controller_id: str) -> object:
    if controller_id not in {PRIMARY_CONTROLLER, SENSITIVITY_CONTROLLER}:
        raise ValueError("controller is outside the frozen Experiment 03 domain")
    from dataclasses import replace as dc_replace
    from pathlib import Path

    contracts, _ = _exp01_modules()
    root = Path(__file__).resolve().parents[3]
    base = contracts.load_config(root / "experiments/01_policy_control/configs/base.yaml")
    controller = dc_replace(
        base.controller,
        pd_candidates=((5.0, 0.5),) + tuple(item for item in base.controller.pd_candidates if item != (5.0, 0.5)),
        ik_damping_candidates=(0.001,) + tuple(item for item in base.controller.ik_damping_candidates if item != 0.001),
        reference_slew_rad_s=48.0,
        differential_gain=12.0,
        differential_speed_m_s=1.0,
        null_gain=0.1,
        qdot_limit_rad_s=4.0,
    )
    return dc_replace(
        base,
        study_id="exp03-hierarchy-v1",
        controller=controller,
        timing=dc_replace(base.timing, chunk_horizon_s=0.1),
        residual=dc_replace(base.residual, component_limit_rad=0.5),
        mpc=dc_replace(base.mpc, smoothness_weight=0.02),
    )


def precheck(spec: ScenarioSpec, controller: str) -> FeasibilityReceipt:
    if spec not in scenario_specs():
        raise ValueError("scenario is outside the frozen domain")
    config = controller_config(controller)
    _, kinematics = _exp01_modules()
    q0 = np.array([0.35, -0.70, 0.35], dtype=np.float64)
    targets = [np.array(fact.pose_xy, dtype=np.float64) for fact in base_memory_snapshot().facts]
    if spec.scenario_id == "motion-target-shift":
        targets.append(targets[0] + np.array([0.0, 0.06]))
    solutions = [kinematics.absolute_ik(target, q0, config.arm.link_lengths_m, config.controller.ik_damping_candidates[0], config) for target in targets]
    reached = [kinematics.forward_kinematics(q, config.arm.link_lengths_m) for q in solutions]
    errors = [float(np.linalg.norm(target - actual)) for target, actual in zip(targets, reached, strict=True)]
    feasible = all(np.isfinite(solution).all() for solution in solutions) and max(errors) <= config.thresholds.success_radius_m
    geometry = {
        "q0": q0.tolist(),
        "targets": [item.tolist() for item in targets],
        "solution_sha256s": [sha256_bytes(np.asarray(item, dtype="<f8").tobytes()) for item in solutions],
        "max_ik_error_m": max(errors),
        "scenario_sha256": spec.sha256,
    }
    geometry_sha = sha256_bytes(canonical_bytes(geometry))
    return FeasibilityReceipt(feasible, "PASS" if feasible else "FIXED_GEOMETRY_INFEASIBLE", controller, spec.sha256, geometry_sha, geometry_sha)


def replace_fact(memory: MemorySnapshot, object_id: str, **changes: object) -> MemorySnapshot:
    matches = [item for item in memory.facts if item.object_id == object_id]
    if len(matches) != 1:
        raise ValueError("memory update requires exactly one object")
    changed = replace(matches[0], **changes)
    facts = tuple(changed if item.object_id == object_id else item for item in memory.facts)
    tick = max(item.observed_tick for item in facts)
    ledger = sha256_bytes(memory.evidence_ledger_sha256.encode("ascii") + canonical_bytes(changed))
    return MemorySnapshot(memory.schema_id, memory.version + 1, facts, tick, ledger)


def _valid_fact(fact: MemoryFact) -> bool:
    return fact.available and not fact.stale and not fact.unknown and fact.confidence > 0.0 and "AUTHORIZED" in fact.restrictions and "FORBIDDEN" not in fact.restrictions


def plan_skill(memory: MemorySnapshot, *, preferred_object_id: str | None = None) -> SkillRequest:
    candidates = [item for item in memory.facts if item.semantic_label == "service-panel" and item.affordance == "inspect"]
    if preferred_object_id is not None:
        candidates = [item for item in candidates if item.object_id == preferred_object_id]
    if not candidates:
        raise SemanticPlanningError("semantic facts are missing, stale, unknown, unavailable, or unauthorized")
    selected = next((item for item in candidates if _valid_fact(item)), None)
    if selected is None:
        raise SemanticPlanningError("no authorized semantic plan")
    return SkillRequest(
        f"inspect-{selected.object_id}-v{memory.version}",
        selected.semantic_label,
        selected.affordance,
        selected.object_id,
        ((0.43, 0.64), (-0.22, 0.20)),
        selected.restrictions,
        memory.version,
        "eef_within_0p025m",
    )


@dataclass(frozen=True)
class SemanticCell:
    memory: MemorySnapshot
    skill: SkillRequest

    @classmethod
    def initial(cls) -> "SemanticCell":
        memory = base_memory_snapshot()
        return cls(memory, plan_skill(memory, preferred_object_id="object-a"))


def episode_specs() -> tuple[EpisodeSpec, ...]:
    scenarios = scenario_specs()
    primary = tuple(
        EpisodeSpec(
            f"primary-{architecture.value}-{scenario.scenario_id}-{seed}",
            architecture,
            scenario.scenario_id,
            scenario.domain,
            seed,
            PRIMARY_CONTROLLER,
            False,
        )
        for architecture in Architecture
        for scenario in scenarios
        for seed in PRIMARY_SEEDS
    )
    sensitivity = tuple(
        EpisodeSpec(
            f"sensitivity-R3-{scenario.scenario_id}-{seed}",
            Architecture.LAYER_MATCHED,
            scenario.scenario_id,
            scenario.domain,
            seed,
            SENSITIVITY_CONTROLLER,
            True,
        )
        for scenario in scenarios
        for seed in SENSITIVITY_SEEDS
    )
    return primary + sensitivity


__all__ = [
    "FeasibilityReceipt", "INJECTION_TICK", "PRIMARY_CONTROLLER", "PRIMARY_SEEDS",
    "SENSITIVITY_CONTROLLER", "SENSITIVITY_SEEDS", "ScenarioSpec", "SemanticCell",
    "SemanticPlanningError", "controller_config", "episode_specs", "plan_skill", "precheck",
    "replace_fact", "scenario_specs",
]
