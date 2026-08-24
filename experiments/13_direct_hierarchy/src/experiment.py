"""Frozen direct-outcome matrix over the production hierarchy runtime."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import math
from types import MappingProxyType
from typing import Mapping

import numpy as np

_contracts = importlib.import_module("experiments.03_recovery.src.v3_contracts")
_runtime = importlib.import_module("experiments.03_recovery.src.v3_runtime")
Architecture = _contracts.Architecture
PRIMARY_CONTROLLER_ID = _contracts.PRIMARY_CONTROLLER_ID
RunStage = _contracts.RunStage
SENSITIVITY_CONTROLLER_ID = _contracts.SENSITIVITY_CONTROLLER_ID
canonical_bytes = _contracts.canonical_bytes
sha256_bytes = _contracts.sha256_bytes
PrecheckControlSpec = _runtime.PrecheckControlSpec
precheck = _runtime.precheck
run_episode = _runtime.run_episode


EXPERIMENT_ID = "exp13-direct-hierarchy-v1"
PRIMARY_SEEDS = tuple(range(20261901, 20261911))
SENSITIVITY_SEEDS = PRIMARY_SEEDS[:5]
FAMILIES = (
    "control-impulse",
    "control-dropout",
    "motion-target-shift",
    "motion-path-infeasible",
    "semantic-object-unavailable",
    "semantic-restriction-change",
)
SEVERITIES = ("LOW", "HIGH")
OUTCOME_ROW_FIELDS = (
    "episode_id", "architecture", "family", "severity", "seed", "controller_id",
    "matrix_role", "terminal", "mission_success", "safety_composite", "progress",
    "retry_count", "control_wakes", "motion_wakes", "semantic_wakes",
    "recovery_latency_ticks", "aborts", "peak_torque_nm", "rms_torque_nm",
    "peak_contact_force_n", "trajectory_length_rad", "action_cost",
)


@dataclass(frozen=True)
class DirectSpec:
    architecture: Architecture
    family: str
    severity: str
    seed: int
    controller_id: str
    matrix_role: str
    stage: RunStage = RunStage.OUTCOME

    @property
    def scenario_id(self) -> str:
        return self.family

    @property
    def episode_id(self) -> str:
        controller = "P6" if self.controller_id == PRIMARY_CONTROLLER_ID else "P4"
        return f"exp13-{controller}-{self.architecture.value}-{self.family}-{self.severity.lower()}-{self.seed}"


@dataclass(frozen=True)
class DirectRealization:
    scenario_id: str
    stage: RunStage
    seed: int
    q0: tuple[float, float, float]
    target_a_xy: tuple[float, float]
    target_b_xy: tuple[float, float]
    injection_tick: int
    impulse_nm: float
    impulse_ticks: int
    dropout_ticks: int
    target_shift_xy: tuple[float, float]
    obstacle_xy: tuple[float, float]
    obstacle_radius_m: float
    damping_multiplier: float
    semantic_delay_ticks: int
    parameter_sha256: str


def matrix_specs() -> tuple[DirectSpec, ...]:
    primary = (
        DirectSpec(architecture, family, severity, seed, PRIMARY_CONTROLLER_ID, "PRIMARY")
        for architecture in Architecture
        for family in FAMILIES
        for severity in SEVERITIES
        for seed in PRIMARY_SEEDS
    )
    sensitivity = (
        DirectSpec(Architecture.R3, family, severity, seed, SENSITIVITY_CONTROLLER_ID, "SENSITIVITY")
        for family in FAMILIES
        for severity in SEVERITIES
        for seed in SENSITIVITY_SEEDS
    )
    specs = tuple(sorted((*primary, *sensitivity), key=lambda item: item.episode_id))
    if len(specs) != 540 or len({item.episode_id for item in specs}) != 540:
        raise RuntimeError("Exp13 frozen matrix identity error")
    return specs


def make_realization(spec: DirectSpec) -> DirectRealization:
    if spec.family not in FAMILIES or spec.severity not in SEVERITIES:
        raise ValueError("Exp13 family/severity outside freeze")
    if spec.seed not in PRIMARY_SEEDS:
        raise ValueError("Exp13 seed outside freeze")
    namespace = int.from_bytes(
        hashlib.sha256(f"{EXPERIMENT_ID}:{spec.family}:{spec.severity}:{spec.seed}".encode("ascii")).digest()[:8],
        "little",
    )
    rng = np.random.Generator(np.random.PCG64(namespace))
    q0 = tuple(float(item) for item in np.array((0.35, -0.70, 0.35)) + rng.uniform(-0.025, 0.025, 3))
    target_a = np.array((0.55, 0.08)) + rng.uniform(-0.018, 0.018, 2)
    target_b = np.array((0.49, -0.14)) + rng.uniform(-0.018, 0.018, 2)
    direction = float(rng.uniform(-math.pi, math.pi))
    shift_m = 0.040 if spec.severity == "LOW" else 0.065
    shift = shift_m * np.asarray((math.cos(direction), math.sin(direction)))
    angles = np.cumsum(np.asarray(q0))
    links = np.asarray((0.30, 0.25, 0.20))
    start = np.asarray((np.dot(links, np.cos(angles)), np.dot(links, np.sin(angles))))
    obstacle = (start + target_a) / 2.0 + rng.uniform(-0.006, 0.006, 2)
    high = spec.severity == "HIGH"
    values = {
        "scenario_id": spec.family,
        "stage": RunStage.OUTCOME,
        "seed": spec.seed,
        "q0": q0,
        "target_a_xy": tuple(float(item) for item in target_a),
        "target_b_xy": tuple(float(item) for item in target_b),
        "injection_tick": int(rng.integers(600, 901)),
        "impulse_nm": 0.26 if high else 0.14,
        "impulse_ticks": 10 if high else 5,
        "dropout_ticks": 50 if high else 25,
        "target_shift_xy": tuple(float(item) for item in shift),
        "obstacle_xy": tuple(float(item) for item in obstacle),
        "obstacle_radius_m": 0.0475 if high else 0.0375,
        "damping_multiplier": float(rng.uniform(0.90, 1.10)),
        "semantic_delay_ticks": 10 if high else 2,
    }
    identity = {key: value for key, value in values.items() if key not in {"stage"}}
    return DirectRealization(**values, parameter_sha256=sha256_bytes(canonical_bytes(identity)))


def run_cell(spec: DirectSpec) -> object:
    realization = make_realization(spec)
    receipt = precheck(PrecheckControlSpec(
        f"{EXPERIMENT_ID}:{spec.family}:{spec.severity}:{spec.seed}",
        realization.q0,
        realization.target_a_xy,
        realization.target_b_xy,
        realization.obstacle_xy,
        realization.obstacle_radius_m,
    ))
    return run_episode(spec, realization_override=realization, precheck_override=receipt)


def frozen_configuration() -> Mapping[str, object]:
    return MappingProxyType({
        "experiment_id": EXPERIMENT_ID,
        "primary_seeds": PRIMARY_SEEDS,
        "sensitivity_seeds": SENSITIVITY_SEEDS,
        "families": FAMILIES,
        "severities": SEVERITIES,
        "primary_cells": 480,
        "sensitivity_cells": 60,
        "total_cells": 540,
        "bootstrap_draws": 10_000,
        "fixed_best_simpler_comparator": "R2",
        "causal_claims": False,
    })


__all__ = [
    "DirectRealization", "DirectSpec", "EXPERIMENT_ID", "FAMILIES", "OUTCOME_ROW_FIELDS",
    "PRIMARY_SEEDS", "SENSITIVITY_SEEDS", "SEVERITIES", "frozen_configuration",
    "make_realization", "matrix_specs", "run_cell",
]
