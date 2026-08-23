"""Construct-valid MuJoCo runtime for V3 qualification episodes.

Only the injector sees ``scenario_id``. Recovery policy inputs are constructed from
retained state, action, geometry, and causally delivered memory bytes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import importlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import mujoco
import numpy as np

from reflect.types import Constraint, ObjectBelief, Observation, Pose, Predicate, RobotState, SkillSpec

from .v3_contracts import (
    Architecture,
    BudgetState,
    DecisionEvent,
    DecisionLevel,
    EPISODE_TICKS,
    ObservableState,
    PRIMARY_CONTROLLER_ID,
    REOBSERVE_TICKS,
    SCENARIO_IDS,
    SENSITIVITY_CONTROLLER_ID,
    TIMESTEP_S,
    V3Realization,
    canonical_bytes,
    initial_budget,
    make_realization,
    sha256_bytes,
)
from .v3_policy import decide


ZERO_SHA256 = "0" * 64
COMMAND_REFRESH_TICKS = 50
VALID_COMMAND_GAP_TICKS = 15
EEF_CONTACT_RADIUS_M = 0.012


@dataclass(frozen=True)
class V3EpisodeSpec:
    architecture: Architecture
    scenario_id: str
    seed: int
    controller_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "architecture", Architecture(self.architecture))
        if self.scenario_id not in SCENARIO_IDS:
            raise ValueError("unknown V3 qualification scenario")
        if self.controller_id not in {PRIMARY_CONTROLLER_ID, SENSITIVITY_CONTROLLER_ID}:
            raise ValueError("unknown V3 qualification controller")
        if self.controller_id == SENSITIVITY_CONTROLLER_ID and self.architecture is not Architecture.R3:
            raise ValueError("repaired P4 is a R3 sensitivity controller only")
        make_realization(self.scenario_id, self.seed)

    @property
    def episode_id(self) -> str:
        controller = "P6" if self.controller_id == PRIMARY_CONTROLLER_ID else "P4"
        return f"qualification-{controller}-{self.architecture.value}-{self.scenario_id}-{self.seed}"


@dataclass(frozen=True)
class PrecheckReceipt:
    disposition: str
    reason: str
    architecture_independent: bool
    realization_sha256: str
    geometry_sha256: str
    straight_path_blocked: bool
    waypoint_path_clear: bool
    target_a_ik_error_m: float
    target_b_ik_error_m: float


@dataclass(frozen=True)
class V3EpisodeRaw:
    spec: V3EpisodeSpec
    realization: V3Realization
    precheck: PrecheckReceipt
    controller_binding: Mapping[str, object]
    injection_rows: tuple[int, ...]
    parameter_use_receipt: Mapping[str, object]
    hidden_cause: Mapping[str, object]
    world_ledger: tuple[Mapping[str, object], ...]
    semantic_events: tuple[Mapping[str, object], ...]
    memory_ledger: tuple[Mapping[str, object], ...]
    memory_events: tuple[Mapping[str, object], ...]
    observations: tuple[ObservableState, ...]
    decisions: tuple[DecisionEvent, ...]
    budget_resets: tuple[Mapping[str, object], ...]
    execution_receipts: tuple[Mapping[str, object], ...]
    commands: tuple[Mapping[str, object], ...]
    trajectory_bytes: bytes
    action_envelopes: tuple[Mapping[str, object], ...]
    contact_envelopes: tuple[Mapping[str, object], ...]
    trace: Mapping[str, np.ndarray]
    executor_debug: Mapping[str, object]


@dataclass
class _ActiveCommand:
    record: dict[str, object]
    chunk: object
    stack: object
    executor_state: object
    path: tuple[tuple[float, float], ...]
    segment_index: int
    segment_generated_tick: int


@dataclass
class _Attempt:
    level: DecisionLevel
    start_tick: int
    end_tick: int
    old_content_sha256: str
    new_content_sha256: str
    executed_valid_ticks: int = 0


def _modules() -> tuple[object, object, object, object]:
    contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
    arm = importlib.import_module("experiments.01_policy_control.src.arm")
    kinematics = importlib.import_module("experiments.01_policy_control.src.kinematics")
    representations = importlib.import_module("experiments.01_policy_control.src.representations")
    return contracts, arm, kinematics, representations


def _controller_config() -> object:
    contracts, _, _, _ = _modules()
    root = Path(__file__).resolve().parents[3]
    base = contracts.load_config(root / "experiments/01_policy_control/configs/base.yaml")
    controller = replace(
        base.controller,
        pd_candidates=((5.0, 0.5),) + tuple(item for item in base.controller.pd_candidates if item != (5.0, 0.5)),
        ik_damping_candidates=(0.001,) + tuple(item for item in base.controller.ik_damping_candidates if item != 0.001),
        reference_slew_rad_s=48.0,
        differential_gain=12.0,
        differential_speed_m_s=1.0,
        null_gain=0.1,
        qdot_limit_rad_s=4.0,
    )
    return replace(
        base,
        study_id="hierarchical-recovery-v3-qualification",
        controller=controller,
        timing=replace(base.timing, chunk_horizon_s=0.1),
        residual=replace(base.residual, component_limit_rad=0.5),
    )


def _forward_xy(q: tuple[float, float, float] | np.ndarray) -> np.ndarray:
    angles = np.cumsum(np.asarray(q, dtype=np.float64))
    links = np.asarray((0.30, 0.25, 0.20))
    return np.asarray((np.dot(links, np.cos(angles)), np.dot(links, np.sin(angles))), dtype=np.float64)


def _segment_distance(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    delta = end - start
    denominator = float(delta @ delta)
    alpha = 0.0 if denominator == 0.0 else float(np.clip(((point - start) @ delta) / denominator, 0.0, 1.0))
    return float(np.linalg.norm(point - (start + alpha * delta)))


def _blocked(start: np.ndarray, end: np.ndarray, center: np.ndarray, radius: float) -> bool:
    return _segment_distance(center, start, end) <= radius + EEF_CONTACT_RADIUS_M + 0.002


def _waypoint_path(start: np.ndarray, target: np.ndarray, center: np.ndarray, radius: float) -> tuple[tuple[float, float], ...]:
    delta = target - start
    norm = float(np.linalg.norm(delta))
    if norm == 0.0:
        return (tuple(float(item) for item in target),)
    perpendicular = np.asarray((-delta[1], delta[0])) / norm
    for sign in (1.0, -1.0):
        waypoint = center + sign * perpendicular * (radius + EEF_CONTACT_RADIUS_M + 0.055)
        if np.linalg.norm(waypoint) < 0.72 and not _blocked(start, waypoint, center, radius) and not _blocked(waypoint, target, center, radius):
            return (tuple(float(item) for item in waypoint), tuple(float(item) for item in target))
    raise ValueError("no frozen waypoint route")


def precheck(spec: V3EpisodeSpec, *, force_not_run: bool = False) -> PrecheckReceipt:
    """Run the architecture-independent feasibility gate before realization execution."""
    realization = make_realization(spec.scenario_id, spec.seed)
    _, _, kinematics, _ = _modules()
    config = _controller_config()
    q0 = np.asarray(realization.q0)
    targets = (np.asarray(realization.target_a_xy), np.asarray(realization.target_b_xy))
    solutions = tuple(kinematics.absolute_ik(target, q0, config.arm.link_lengths_m, config.controller.ik_damping_candidates[0], config) for target in targets)
    errors = tuple(float(np.linalg.norm(_forward_xy(solution) - target)) for solution, target in zip(solutions, targets, strict=True))
    start = _forward_xy(q0)
    obstacle = np.asarray(realization.obstacle_xy)
    radius = realization.obstacle_radius_m
    straight_blocked = _blocked(start, targets[0], obstacle, radius)
    try:
        waypoint = _waypoint_path(start, targets[0], obstacle, radius)
        waypoint_clear = len(waypoint) == 2
    except ValueError:
        waypoint = ()
        waypoint_clear = False
    geometry = {
        "q0": realization.q0,
        "targets": (realization.target_a_xy, realization.target_b_xy),
        "ik_solution_sha256s": tuple(sha256_bytes(np.asarray(item, dtype="<f8").tobytes()) for item in solutions),
        "ik_errors_m": errors,
        "obstacle_xy": realization.obstacle_xy,
        "obstacle_radius_m": radius,
        "straight_path_blocked": straight_blocked,
        "waypoint": waypoint,
        "waypoint_path_clear": waypoint_clear,
    }
    feasible = not force_not_run and max(errors) <= config.thresholds.success_radius_m and straight_blocked and waypoint_clear
    return PrecheckReceipt(
        "READY" if feasible else "NOT_RUN",
        "PASS" if feasible else "ARCHITECTURE_INDEPENDENT_FEASIBILITY_CONTROL",
        True,
        realization.parameter_sha256,
        sha256_bytes(canonical_bytes(geometry)),
        straight_blocked,
        waypoint_clear,
        errors[0],
        errors[1],
    )


class _World:
    def __init__(self, realization: V3Realization, config: object, arm_module: object):
        xml = arm_module.MJCF_BYTES.decode("utf-8")
        obstacle = '<geom name="v3-obstacle" type="sphere" pos="5 5 0" size="0.04" contype="2" conaffinity="4" rgba="0.8 0.1 0.1 1"/>'
        objects = (
            f'<geom name="v3-object-a" type="sphere" pos="{realization.target_a_xy[0]} {realization.target_a_xy[1]} 0" size="0.009" contype="0" conaffinity="0" rgba="0.1 0.6 0.9 1"/>'
            f'<geom name="v3-object-b" type="sphere" pos="{realization.target_b_xy[0]} {realization.target_b_xy[1]} 0" size="0.009" contype="0" conaffinity="0" rgba="0.1 0.9 0.4 1"/>'
        )
        xml = xml.replace("<worldbody>", f"<worldbody>{obstacle}{objects}", 1)
        xml = xml.replace(
            '<site name="eef" pos=".20 0 0" size=".01"/>',
            '<site name="eef" pos=".20 0 0" size=".01"/><geom name="v3-eef-contact" type="sphere" pos=".20 0 0" size=".012" contype="4" conaffinity="2" rgba="0 0 0 0"/>',
            1,
        )
        self.model = mujoco.MjModel.from_xml_string(xml)
        self.data = mujoco.MjData(self.model)
        self.config = config
        self.model.dof_damping[:3] *= realization.damping_multiplier
        self.obstacle_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "v3-obstacle")
        self.eef_geom_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "v3-eef-contact")
        self.site_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SITE, "eef")

    def reset(self, q: tuple[float, float, float]) -> None:
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[:3] = np.asarray(q)
        self.data.qvel[:3] = 0.0
        mujoco.mj_forward(self.model, self.data)

    def state(self) -> tuple[np.ndarray, np.ndarray]:
        return np.array(self.data.qpos[:3], copy=True), np.array(self.data.qvel[:3], copy=True)

    def site_xy(self) -> np.ndarray:
        return np.array(self.data.site_xpos[self.site_id, :2], copy=True)

    def activate_obstacle(self, realization: V3Realization) -> None:
        self.model.geom_pos[self.obstacle_id] = (realization.obstacle_xy[0], realization.obstacle_xy[1], 0.0)
        self.model.geom_size[self.obstacle_id, 0] = realization.obstacle_radius_m
        mujoco.mj_forward(self.model, self.data)

    def contacts(self) -> tuple[Mapping[str, object], ...]:
        contacts: list[Mapping[str, object]] = []
        for index in range(self.data.ncon):
            contact = self.data.contact[index]
            geom1 = int(contact.geom1)
            geom2 = int(contact.geom2)
            force = np.zeros(6, dtype=np.float64)
            mujoco.mj_contactForce(self.model, self.data, index, force)
            contacts.append(MappingProxyType({
                "index": index,
                "geom1_id": geom1,
                "geom1_name": mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, geom1),
                "geom2_id": geom2,
                "geom2_name": mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, geom2),
                "distance_m": float(contact.dist),
                "position_m": [float(item) for item in contact.pos],
                "frame": [float(item) for item in contact.frame],
                "force_n_torque_nm": [float(item) for item in force],
            }))
        return tuple(contacts)

    def step(self, torque: np.ndarray, external: np.ndarray) -> None:
        self.data.ctrl[:] = np.asarray(torque)
        self.data.qfrc_applied[:3] = np.asarray(external)
        mujoco.mj_step(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)


def _skill(object_id: str, target: np.ndarray, version: int) -> SkillSpec:
    return SkillSpec(
        f"inspect-{object_id}-v{version}",
        "track_target",
        (object_id,),
        Pose(np.asarray((target[0], target[1], 0.0)), np.asarray((1.0, 0.0, 0.0, 0.0))),
        (Constraint("workspace", {"radius_m": 0.72}),),
        Predicate("eef_error", {"max_m": 0.025}),
        EPISODE_TICKS * TIMESTEP_S,
        0,
    )


def _t3_contracts() -> tuple[type, type]:
    module = importlib.import_module("experiments.03_recovery.src.contracts")
    return module.MemoryFact, module.MemorySnapshot


def _fact_authorized(fact: Mapping[str, object]) -> bool:
    restrictions = set(str(item) for item in fact["restrictions"])
    return bool(
        fact["available"]
        and not fact["stale"]
        and not fact["unknown"]
        and fact["affordance"] == "inspect"
        and "AUTHORIZED" in restrictions
        and "FORBIDDEN" not in restrictions
    )


def _t3_snapshot_row(
    memory: Mapping[str, Mapping[str, object]],
    version: int,
    tick: int,
    memory_events: list[Mapping[str, object]],
) -> Mapping[str, object]:
    memory_fact_type, memory_snapshot_type = _t3_contracts()
    facts = tuple(memory_fact_type(
        str(fact["object_id"]),
        str(fact["semantic_label"]),
        str(fact["affordance"]),
        tuple(str(item) for item in fact["restrictions"]),
        tuple(float(item) for item in fact["pose_xy"]),
        bool(fact["available"]),
        int(fact["observed_tick"]),
        float(fact["confidence"]),
        str(fact["provenance"]),
        bool(fact["stale"]),
        bool(fact["unknown"]),
    ) for _, fact in sorted(memory.items()))
    evidence_sha256 = sha256_bytes(b"".join(canonical_bytes(item) for item in memory_events))
    snapshot = memory_snapshot_type("T3_LIVE_BELIEF_V1", version, facts, tick, evidence_sha256)
    snapshot_wire = json.loads(snapshot.to_bytes())
    return MappingProxyType({"tick": tick, "snapshot": snapshot_wire, "snapshot_sha256": snapshot.sha256})


def _memory_beliefs(memory: Mapping[str, Mapping[str, object]]) -> tuple[ObjectBelief, ...]:
    return tuple(
        ObjectBelief(
            object_id,
            "service-panel",
            np.asarray(fact["pose_xy"]),
            float(fact["confidence"]),
            {
                "affordance": fact["affordance"],
                "available": fact["available"],
                "restrictions": tuple(fact["restrictions"]),
                "stale": fact["stale"],
                "unknown": fact["unknown"],
            },
            float(fact["confidence"]),
            int(fact["observed_tick"]) * 2_000_000,
            (str(fact["provenance"]),),
        )
        for object_id, fact in sorted(memory.items())
    )


def _command_content(controller_id: str, object_id: str, path: tuple[tuple[float, float], ...], segment_index: int) -> bytes:
    return canonical_bytes({
        "affordance": "inspect",
        "controller_id": controller_id,
        "object_id": object_id,
        "path_xy": path,
        "segment_index": segment_index,
    })


def _generate_command(
    *,
    spec: V3EpisodeSpec,
    tick: int,
    sequence: int,
    object_id: str,
    path: tuple[tuple[float, float], ...],
    segment_index: int,
    q: np.ndarray,
    dq: np.ndarray,
    q0: np.ndarray,
    memory: Mapping[str, Mapping[str, object]],
    memory_version: int,
    previous_q_ref: np.ndarray,
    config: object,
    exp_contracts: object,
    kinematics: object,
    representations: object,
) -> tuple[_ActiveCommand, bytes]:
    target = np.asarray(path[segment_index])
    q_target = kinematics.absolute_ik(target, q, config.arm.link_lengths_m, config.controller.ik_damping_candidates[0], config)
    initial_target = kinematics.absolute_ik(np.asarray(memory[object_id]["pose_xy"]), q0, config.arm.link_lengths_m, config.controller.ik_damping_candidates[0], config)
    observation = Observation(
        sequence,
        tick * 2_000_000,
        tick * 2_000_000,
        RobotState(q, dq),
        _memory_beliefs(memory),
        f"inspect-{object_id}-v{memory_version}",
        "track_target",
    )
    policy_input = exp_contracts.PolicyInput(
        observation,
        _skill(object_id, target, memory_version),
        tick * 2_000_000,
        100_000_000,
        q,
        q_target if spec.controller_id == PRIMARY_CONTROLLER_ID else initial_target,
    )
    stack = exp_contracts.CommandStack.P6 if spec.controller_id == PRIMARY_CONTROLLER_ID else exp_contracts.CommandStack.P4
    chunk = representations.emit_chunk(stack, policy_input, config)
    if stack is exp_contracts.CommandStack.P4:
        chunk = representations.with_p4_executor_tuning(chunk, representations.P4ExecutorTuning(1, True))
    content = _command_content(spec.controller_id, object_id, path, segment_index)
    content_sha = sha256_bytes(content)
    actions = np.asarray(chunk.actions, dtype="<f8")
    trajectory = canonical_bytes({
        "chunk_id": chunk.chunk_id,
        "skill_id": chunk.skill_id,
        "source_observation_id": chunk.source_observation_id,
        "source_observation_time_ns": chunk.source_observation_time_ns,
        "generated_time_ns": chunk.generated_time_ns,
        "valid_from_ns": chunk.valid_from_ns,
        "expires_at_ns": chunk.expires_at_ns,
        "dt_s": chunk.dt_s,
        "controller_id": spec.controller_id,
        "object_id": object_id,
        "path_xy": path,
        "segment_index": segment_index,
        "actions_shape": actions.shape,
        "actions_dtype": "<f8",
        "representation": chunk.representation,
        "expected_phase": chunk.expected_phase,
        "metadata": dict(chunk.metadata),
    }) + actions.tobytes(order="C")
    trajectory_sha = sha256_bytes(trajectory)
    record = {
        "command_id": f"command-{sequence:04d}",
        "generated_tick": tick,
        "controller_id": spec.controller_id,
        "stack_id": stack.value,
        "object_id": object_id,
        "affordance": "inspect",
        "path_xy": [list(item) for item in path],
        "segment_index": segment_index,
        "content_sha256": content_sha,
        "trajectory_sha256": trajectory_sha,
        "trajectory_bytes": len(trajectory),
    }
    active = _ActiveCommand(record, chunk, stack, representations.initial_executor_state(previous_q_ref), path, segment_index, tick)
    return active, trajectory


def _path_clear(active: _ActiveCommand | None, obstacle_active: bool, realization: V3Realization, eef: np.ndarray) -> bool:
    if active is None or not obstacle_active:
        return True
    center = np.asarray(realization.obstacle_xy)
    radius = realization.obstacle_radius_m
    points = (tuple(float(item) for item in eef),) + active.path[active.segment_index:]
    return all(not _blocked(np.asarray(start), np.asarray(end), center, radius) for start, end in zip(points, points[1:]))


def _observable(
    *,
    tick: int,
    trace_rows: Mapping[str, list[object]],
    action_valid: bool,
    geometry_feasible: bool,
    semantic_preconditions_valid: bool,
    memory_version: int,
    command_content_sha256: str,
    successful_execution_content_sha256: str,
    command_gap_ticks: int,
    reobserve_index: int,
) -> ObservableState:
    errors = np.asarray(trace_rows["target_error_m"][-REOBSERVE_TICKS:], dtype=np.float64)
    holds = np.asarray(trace_rows["safe_hold"][-REOBSERVE_TICKS:], dtype=np.bool_)
    tracking_active = bool(len(errors) == REOBSERVE_TICKS and len(holds) == REOBSERVE_TICKS and not np.any(holds))
    mean = float(np.mean(errors)) if tracking_active else 0.0
    slope = 0.0 if not tracking_active or len(errors) < 2 else float((errors[-1] - errors[0]) / (len(errors) - 1))
    recent_torques = np.asarray(trace_rows["actuator_cmd_nm"][-REOBSERVE_TICKS:], dtype=np.float64)
    recent_q = np.asarray(trace_rows["q"][-REOBSERVE_TICKS:], dtype=np.float64)
    recent_dq = np.asarray(trace_rows["dq"][-REOBSERVE_TICKS:], dtype=np.float64)
    safe = bool(
        (not len(recent_torques) or np.isfinite(recent_torques).all())
        and (not len(recent_q) or np.isfinite(recent_q).all())
        and (not len(recent_dq) or np.isfinite(recent_dq).all())
    )
    return ObservableState(
        tick,
        max(0, tick - max(0, len(errors) - 1)),
        mean,
        slope,
        retained_load_estimate_nm(trace_rows, tick),
        command_gap_ticks,
        safe,
        action_valid,
        geometry_feasible,
        semantic_preconditions_valid,
        memory_version,
        command_content_sha256,
        successful_execution_content_sha256,
        reobserve_index,
    )


@lru_cache(maxsize=1)
def _nominal_observer_model() -> mujoco.MjModel:
    """Return the frozen nominal plant used only for retained-state inverse dynamics."""
    _, arm_module, _, _ = _modules()
    return mujoco.MjModel.from_xml_string(arm_module.MJCF_BYTES.decode("utf-8"))


def retained_load_estimate_nm(trace: Mapping[str, object], observed_tick: int) -> float:
    """Estimate generalized load from retained states/actions before a decision."""
    ticks = np.asarray(trace["tick"], dtype=np.int64)
    eligible = np.flatnonzero(ticks < observed_tick)
    if len(eligible) < 2:
        return 0.0
    previous_index, current_index = int(eligible[-2]), int(eligible[-1])
    q_previous = np.asarray(trace["q"][previous_index], dtype=np.float64)
    dq_previous = np.asarray(trace["dq"][previous_index], dtype=np.float64)
    dq_current = np.asarray(trace["dq"][current_index], dtype=np.float64)
    applied_torque = np.asarray(trace["actuator_cmd_nm"][current_index], dtype=np.float64)
    if not all(np.isfinite(item).all() for item in (q_previous, dq_previous, dq_current, applied_torque)):
        return float("inf")
    model = _nominal_observer_model()
    data = mujoco.MjData(model)
    data.qpos[:3] = q_previous
    data.qvel[:3] = dq_previous
    data.qacc[:3] = (dq_current - dq_previous) / TIMESTEP_S
    mujoco.mj_inverse(model, data)
    residual = np.asarray(data.qfrc_inverse[:3]) - applied_torque
    return float(np.mean(np.abs(residual)))


def _readonly_trace(rows: Mapping[str, list[object]]) -> Mapping[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    dtypes: dict[str, object] = {"tick": np.int32, "contact_count": np.int16}
    for name, values in rows.items():
        array = np.asarray(values, dtype=dtypes.get(name))
        array.setflags(write=False)
        result[name] = array
    return MappingProxyType(result)


def _controller_binding(spec: V3EpisodeSpec, arm_module: object) -> Mapping[str, object]:
    if spec.controller_id == PRIMARY_CONTROLLER_ID:
        call_path = "representations.emit_chunk:P6->reference_for_tick:P6->arm.bounded_pd"
        knobs = {"stack": "P6", "residual_component_limit_rad": 0.5, "reference_slew_rad_s": 48.0}
    else:
        call_path = "representations.emit_chunk:P4->with_p4_executor_tuning:1:dqon->reference_for_tick:P4->arm.bounded_pd"
        knobs = {"stack": "P4", "lookahead_ticks": 1, "dq_feedforward": True, "reference_slew_rad_s": 48.0}
    return MappingProxyType({
        "controller_id": spec.controller_id,
        "call_path": call_path,
        "arm_mjcf_sha256": sha256_bytes(arm_module.MJCF_BYTES),
        "knobs": knobs,
    })


def run_episode(spec: V3EpisodeSpec) -> V3EpisodeRaw:
    """Execute one calibration episode and return immutable raw evidence inputs."""
    realization = make_realization(spec.scenario_id, spec.seed)
    receipt = precheck(spec)
    if receipt.disposition != "READY":
        raise RuntimeError("architecture-independent precheck returned NOT_RUN")
    exp_contracts, arm_module, kinematics, representations = _modules()
    config = _controller_config()
    world = _World(realization, config, arm_module)
    world.reset(realization.q0)
    q0 = np.asarray(realization.q0)
    previous_q_ref = np.array(q0, copy=True)
    hold_q = np.array(q0, copy=True)
    memory: dict[str, dict[str, object]] = {
        object_id: {
            "object_id": object_id,
            "semantic_label": "service-panel",
            "affordance": "inspect",
            "restrictions": ("AUTHORIZED",),
            "pose_xy": list(target),
            "available": True,
            "observed_tick": 0,
            "confidence": 1.0,
            "provenance": "v3-initial-world-observation",
            "stale": False,
            "unknown": False,
        }
        for object_id, target in (("object-a", realization.target_a_xy), ("object-b", realization.target_b_xy))
    }
    memory_version = 1
    memory_events: list[Mapping[str, object]] = [MappingProxyType({
        "event_id": f"initial-{object_id}",
        "tick": 0,
        "event": "OBSERVED_OBJECT",
        "object_id": object_id,
        "fact": dict(fact),
    }) for object_id, fact in sorted(memory.items())]
    memory_ledger: list[Mapping[str, object]] = [_t3_snapshot_row(memory, memory_version, 0, memory_events)]
    semantic_events: list[Mapping[str, object]] = []
    world_ledger: list[Mapping[str, object]] = [MappingProxyType({
        "tick": 0,
        "event": "INITIAL_WORLD",
        "target_object_id": "object-a",
        "target_xy": list(realization.target_a_xy),
        "obstacle_active": False,
    })]
    hidden_cause = MappingProxyType({
        "scenario_id": spec.scenario_id,
        "injection_tick": realization.injection_tick,
        "semantic_delivery_tick": realization.injection_tick + realization.semantic_delay_ticks if spec.scenario_id.startswith("semantic-") else None,
    })
    parameter_use = {
        "q0": list(realization.q0),
        "target_a_xy": list(realization.target_a_xy),
        "target_b_xy": list(realization.target_b_xy),
        "injection_tick": realization.injection_tick,
        "damping_multiplier": realization.damping_multiplier,
    }
    if spec.scenario_id == "control-impulse":
        parameter_use.update({"impulse_nm": realization.impulse_nm, "impulse_ticks": realization.impulse_ticks})
    elif spec.scenario_id == "control-dropout":
        parameter_use["dropout_ticks"] = realization.dropout_ticks
    elif spec.scenario_id == "motion-target-shift":
        parameter_use["target_shift_xy"] = list(realization.target_shift_xy)
    elif spec.scenario_id == "motion-path-infeasible":
        parameter_use.update({"obstacle_xy": list(realization.obstacle_xy), "obstacle_radius_m": realization.obstacle_radius_m})
    elif spec.scenario_id.startswith("semantic-"):
        parameter_use["semantic_delay_ticks"] = realization.semantic_delay_ticks
    parameter_use["receipt_sha256"] = sha256_bytes(canonical_bytes(parameter_use))

    trace_rows: dict[str, list[object]] = {name: [] for name in (
        "tick", "q_before", "dq_before", "q", "dq", "eef_xy", "q_ref", "dq_ref", "actuator_cmd_nm", "applied_force_nm",
        "contact_count", "obstacle_contact", "contact_force_norm_n", "contact_torque_norm_nm",
        "target_xy", "target_error_m", "safe_hold", "action_valid", "world_authorized",
    )}
    action_envelopes: list[Mapping[str, object]] = []
    contact_envelopes: list[Mapping[str, object]] = []
    observations: list[ObservableState] = []
    decisions: list[DecisionEvent] = []
    resets: list[Mapping[str, object]] = []
    execution_receipts: list[Mapping[str, object]] = []
    commands: list[Mapping[str, object]] = []
    trajectories: list[bytes] = []
    active: _ActiveCommand | None = None
    command_sequence = 0
    budget: BudgetState | None = None
    attempt: _Attempt | None = None
    reobserve_index = 0
    obstacle_active = False
    mission_started = False
    aborted = False
    forced_hold_tick = -1
    dropout_start: int | None = None
    gap_ticks = 0
    injection_rows: list[int] = []
    current_object_id = "object-a"

    def current_target() -> np.ndarray:
        return np.asarray(memory[current_object_id]["pose_xy"], dtype=np.float64)

    def make_command(tick: int, object_id: str, path: tuple[tuple[float, float], ...], segment_index: int = 0) -> None:
        nonlocal active, command_sequence, previous_q_ref
        q, dq = world.state()
        active, trajectory = _generate_command(
            spec=spec,
            tick=tick,
            sequence=command_sequence,
            object_id=object_id,
            path=path,
            segment_index=segment_index,
            q=q,
            dq=dq,
            q0=q0,
            memory=memory,
            memory_version=memory_version,
            previous_q_ref=previous_q_ref,
            config=config,
            exp_contracts=exp_contracts,
            kinematics=kinematics,
            representations=representations,
        )
        command_sequence += 1
        commands.append(MappingProxyType(dict(active.record)))
        trajectories.append(trajectory)

    def command_is_valid() -> bool:
        if active is None:
            return True
        fact = memory[active.record["object_id"]]
        expected = np.asarray(fact["pose_xy"])
        final = np.asarray(active.path[-1])
        return bool(_fact_authorized(fact) and np.allclose(final, expected, atol=0.0, rtol=0.0))

    def semantic_valid() -> bool:
        fact = memory[current_object_id]
        return _fact_authorized(fact)

    def start_attempt(decision: DecisionEvent, tick: int) -> None:
        nonlocal attempt, current_object_id, forced_hold_tick, hold_q
        if decision.level not in {DecisionLevel.CONTROL, DecisionLevel.MOTION, DecisionLevel.SEMANTIC}:
            return
        old = ZERO_SHA256 if active is None else str(active.record["content_sha256"])
        new = old
        hold_q = world.state()[0]
        if decision.level is DecisionLevel.MOTION and semantic_valid():
            target = current_target()
            if obstacle_active:
                path = _waypoint_path(world.site_xy(), target, np.asarray(realization.obstacle_xy), realization.obstacle_radius_m)
            else:
                path = (tuple(float(item) for item in target),)
            make_command(tick, current_object_id, path)
            new = str(active.record["content_sha256"])
        elif decision.level is DecisionLevel.SEMANTIC:
            candidates = [name for name, fact in sorted(memory.items()) if _fact_authorized(fact)]
            if not candidates:
                forced_hold_tick = tick
            else:
                current_object_id = candidates[0] if current_object_id not in candidates else current_object_id
                target = current_target()
                if current_object_id == "object-a" and semantic_valid():
                    start = world.site_xy()
                    delta = target - start
                    norm = max(float(np.linalg.norm(delta)), 1e-12)
                    perpendicular = np.asarray((-delta[1], delta[0])) / norm
                    waypoint = (start + target) / 2.0 + perpendicular * 0.04
                    path = (tuple(float(item) for item in waypoint), tuple(float(item) for item in target))
                else:
                    path = (tuple(float(item) for item in target),)
                make_command(tick, current_object_id, path)
                world_ledger.append(MappingProxyType({
                    "tick": tick,
                    "event": "AUTHORIZED_ALTERNATIVE_SELECTED",
                    "target_object_id": current_object_id,
                    "target_xy": list(target),
                    "obstacle_active": obstacle_active,
                }))
                new = str(active.record["content_sha256"])
            forced_hold_tick = tick
        attempt = _Attempt(decision.level, tick, tick + REOBSERVE_TICKS, old, new)

    def handle_decision(observable: ObservableState) -> None:
        nonlocal budget, aborted
        if budget is None:
            active_sha = ZERO_SHA256 if active is None else str(active.record["content_sha256"])
            budget = initial_budget(active_sha)
        event = decide(spec.architecture, observable, budget)
        observations.append(observable)
        decisions.append(event)
        budget = event.budget_after
        if event.level is DecisionLevel.SAFE_ABORT:
            aborted = True
        else:
            start_attempt(event, observable.tick)

    for tick in range(EPISODE_TICKS):
        external_force = np.zeros(3, dtype=np.float64)
        injection_tick = realization.injection_tick
        delivery_tick = injection_tick + realization.semantic_delay_ticks

        if tick == injection_tick:
            injection_rows.append(tick)
            mission_started = True
            if spec.scenario_id != "anchor-slow-policy":
                make_command(tick, "object-a", (realization.target_a_xy,))
                budget = initial_budget(str(active.record["content_sha256"]))
            world_ledger.append(MappingProxyType({
                "tick": tick,
                "event": "MISSION_AND_INJECTION_BOUNDARY",
                "target_object_id": "object-a",
                "target_xy": list(realization.target_a_xy),
                "obstacle_active": False,
            }))
            if spec.scenario_id == "control-dropout":
                dropout_start = tick
            elif spec.scenario_id == "motion-target-shift":
                shifted = np.asarray(realization.target_a_xy) + np.asarray(realization.target_shift_xy)
                memory["object-a"]["pose_xy"] = [float(item) for item in shifted]
                memory["object-a"]["observed_tick"] = tick
                memory["object-a"]["provenance"] = "v3-target-pose-observation"
                memory_version += 1
                memory_events.append(MappingProxyType({
                    "event_id": f"target-pose-{tick}",
                    "tick": tick,
                    "event": "OBSERVED_POSE",
                    "object_id": "object-a",
                    "pose_xy": list(shifted),
                    "confidence": 1.0,
                    "provenance": "v3-target-pose-observation",
                }))
                memory_ledger.append(_t3_snapshot_row(memory, memory_version, tick, memory_events))
                world_ledger.append(MappingProxyType({"tick": tick, "event": "TARGET_SHIFT", "target_object_id": "object-a", "target_xy": list(shifted), "obstacle_active": False}))
            elif spec.scenario_id == "motion-path-infeasible":
                world.activate_obstacle(realization)
                obstacle_active = True
                world_ledger.append(MappingProxyType({"tick": tick, "event": "OBSTACLE_ACTIVATED", "target_object_id": "object-a", "target_xy": list(realization.target_a_xy), "obstacle_active": True}))
            elif spec.scenario_id.startswith("semantic-"):
                semantic_events.append(MappingProxyType({
                    "event": "PENDING_OBSERVATION",
                    "injection_tick": tick,
                    "delivery_tick": delivery_tick,
                    "object_id": "object-a",
                    "new_available": spec.scenario_id != "semantic-object-unavailable",
                    "new_authorized": spec.scenario_id != "semantic-restriction-change",
                }))

        if spec.scenario_id == "anchor-slow-policy" and tick == injection_tick + 10:
            make_command(tick, "object-a", (realization.target_a_xy,))
            budget = initial_budget(str(active.record["content_sha256"]))

        if spec.scenario_id == "control-impulse" and injection_tick <= tick < injection_tick + realization.impulse_ticks:
            sign = 1.0 if realization.seed % 2 else -1.0
            external_force = sign * realization.impulse_nm * np.asarray((1.0, -1.0, 0.5))

        if spec.scenario_id.startswith("semantic-") and tick == delivery_tick:
            if spec.scenario_id == "semantic-object-unavailable":
                memory["object-a"]["available"] = False
            else:
                memory["object-a"]["restrictions"] = ("FORBIDDEN",)
            memory["object-a"]["observed_tick"] = tick
            memory["object-a"]["confidence"] = 1.0
            memory["object-a"]["provenance"] = "v3-semantic-observation"
            memory["object-a"]["stale"] = False
            memory["object-a"]["unknown"] = False
            memory_version += 1
            memory_events.append(MappingProxyType({
                "event_id": f"semantic-{tick}",
                "tick": tick,
                "event": "OBSERVED_AVAILABILITY" if spec.scenario_id == "semantic-object-unavailable" else "OBSERVED_RESTRICTION",
                "object_id": "object-a",
                "available": memory["object-a"]["available"],
                "restrictions": list(memory["object-a"]["restrictions"]),
                "confidence": 1.0,
                "provenance": "v3-semantic-observation",
            }))
            memory_ledger.append(_t3_snapshot_row(memory, memory_version, tick, memory_events))
            semantic_events.append(MappingProxyType({"event": "DELIVERED_OBSERVATION", "delivery_tick": tick, "memory_version": memory_version, "object_id": "object-a"}))
            forced_hold_tick = tick

        if active is not None and attempt is None and not aborted and tick > active.segment_generated_tick and (tick - active.segment_generated_tick) % COMMAND_REFRESH_TICKS == 0:
            make_command(tick, str(active.record["object_id"]), active.path, active.segment_index)
            if budget is None or budget.last_observed_tick < 0:
                budget = initial_budget(str(active.record["content_sha256"]))

        gap_active = dropout_start is not None and tick < dropout_start + realization.dropout_ticks
        if gap_active:
            gap_ticks += 1
        elif dropout_start is not None and tick >= dropout_start + realization.dropout_ticks:
            gap_ticks = 0

        action_valid_now = command_is_valid()
        geometry_now = _path_clear(active, obstacle_active, realization, world.site_xy())
        semantic_now = semantic_valid()

        # Policy calls are driven by observable contract failures, never taxonomy.
        if mission_started and attempt is None and not aborted:
            observable_gap = gap_ticks if gap_ticks > VALID_COMMAND_GAP_TICKS else 0
            observable = _observable(
                tick=tick,
                trace_rows=trace_rows,
                action_valid=action_valid_now,
                geometry_feasible=geometry_now,
                semantic_preconditions_valid=semantic_now,
                memory_version=memory_version,
                command_content_sha256=ZERO_SHA256 if active is None else str(active.record["content_sha256"]),
                successful_execution_content_sha256=ZERO_SHA256,
                command_gap_ticks=observable_gap,
                reobserve_index=reobserve_index,
            )
            if observable.failure_detected:
                handle_decision(observable)

        hold_reason: str | None = None
        if aborted:
            hold_reason = "SAFE_ABORT"
        elif not mission_started:
            hold_reason = "PRE_MISSION"
        elif active is None:
            hold_reason = "POLICY_DELAY"
        elif gap_active:
            hold_reason = "COMMAND_WITHHELD"
        elif tick == forced_hold_tick:
            hold_reason = "INVALIDATION_GUARD"
        elif attempt is not None and (not command_is_valid() or not semantic_valid()):
            hold_reason = "INVALID_COMMAND_GUARD"

        q, dq = world.state()
        if hold_reason is not None or active is None:
            requested_q = np.array(hold_q if hold_reason in {"SAFE_ABORT", "INVALID_COMMAND_GUARD", "INVALIDATION_GUARD"} else q, copy=True)
            requested_dq = np.zeros(3)
            stack_id = "HOLD"
            mode = "HOLD"
            object_for_action: str | None = None
            content_for_action = ZERO_SHA256
            generated_tick = tick
            cartesian_reference = world.site_xy()
        else:
            reference, active.executor_state, _ = representations.reference_for_tick(
                active.stack,
                active.chunk,
                q,
                dq,
                tick * 2_000_000,
                active.executor_state,
                config,
            )
            requested_q = np.asarray(reference.q_ref)
            requested_dq = np.asarray(reference.dq_ref)
            stack_id = active.stack.value
            mode = "EXECUTE"
            object_for_action = str(active.record["object_id"])
            content_for_action = str(active.record["content_sha256"])
            generated_tick = int(active.record["generated_tick"])
            cartesian_reference = np.asarray(active.path[active.segment_index])

        prior = requested_q if mode == "HOLD" else previous_q_ref
        q_ref, torque, _ = arm_module.bounded_pd(q, dq, requested_q, prior, 5.0, 0.5, config, desired_dq=requested_dq)
        previous_q_ref = np.array(q_ref, copy=True)
        world.step(torque, external_force)
        q_after, dq_after = world.state()
        contacts = world.contacts()
        obstacle_contact = any(
            {contact["geom1_name"], contact["geom2_name"]} == {"v3-obstacle", "v3-eef-contact"}
            for contact in contacts
        )
        contact_force_norm_n = max(
            (float(np.linalg.norm(np.asarray(contact["force_n_torque_nm"][:3], dtype=np.float64))) for contact in contacts),
            default=0.0,
        )
        contact_torque_norm_nm = max(
            (float(np.linalg.norm(np.asarray(contact["force_n_torque_nm"][3:], dtype=np.float64))) for contact in contacts),
            default=0.0,
        )
        eef = world.site_xy()
        target = current_target()
        world_authorized = object_for_action is None or _fact_authorized(memory[object_for_action])
        geometry_for_envelope = _path_clear(active, obstacle_active, realization, world.site_xy())
        valid_envelope = mode == "HOLD" or (command_is_valid() and geometry_for_envelope and world_authorized)
        if attempt is not None and mode == "EXECUTE" and valid_envelope and not obstacle_contact:
            attempt.executed_valid_ticks += 1

        trace_rows["tick"].append(tick)
        trace_rows["q_before"].append(q.tolist())
        trace_rows["dq_before"].append(dq.tolist())
        trace_rows["q"].append(q_after.tolist())
        trace_rows["dq"].append(dq_after.tolist())
        trace_rows["eef_xy"].append(eef.tolist())
        trace_rows["q_ref"].append(np.asarray(q_ref).tolist())
        trace_rows["dq_ref"].append(np.asarray(requested_dq).tolist())
        trace_rows["actuator_cmd_nm"].append(np.asarray(torque).tolist())
        trace_rows["applied_force_nm"].append(external_force.tolist())
        trace_rows["contact_count"].append(len(contacts))
        trace_rows["obstacle_contact"].append(obstacle_contact)
        trace_rows["contact_force_norm_n"].append(contact_force_norm_n)
        trace_rows["contact_torque_norm_nm"].append(contact_torque_norm_nm)
        trace_rows["target_xy"].append(target.tolist())
        trace_rows["target_error_m"].append(float(np.linalg.norm(eef - target)))
        trace_rows["safe_hold"].append(mode == "HOLD")
        trace_rows["action_valid"].append(valid_envelope)
        trace_rows["world_authorized"].append(world_authorized)
        action_envelopes.append(MappingProxyType({
            "tick": tick,
            "controller_id": spec.controller_id,
            "stack_id": stack_id,
            "mode": mode,
            "object_id": object_for_action,
            "affordance": None if object_for_action is None else "inspect",
            "command_content_sha256": content_for_action,
            "generation_tick": generated_tick,
            "action_age_ticks": 0 if mode == "HOLD" else tick - generated_tick,
            "cartesian_reference": [float(item) for item in cartesian_reference],
            "joint_reference": [float(item) for item in q_ref],
            "executed_actuator_nm": [float(item) for item in torque],
            "external_force_nm": [float(item) for item in external_force],
            "hold_reason": hold_reason,
        }))
        contact_envelopes.append(MappingProxyType({"tick": tick, "contacts": contacts}))

        if active is not None and len(active.path) > active.segment_index + 1 and attempt is None:
            segment_target = np.asarray(active.path[active.segment_index])
            if np.linalg.norm(eef - segment_target) <= 0.035 or tick - active.segment_generated_tick >= 125:
                make_command(tick + 1, str(active.record["object_id"]), active.path, active.segment_index + 1)

        if attempt is not None and tick + 1 >= attempt.end_tick:
            completed_level = attempt.level
            successful_sha = attempt.new_content_sha256 if attempt.new_content_sha256 != attempt.old_content_sha256 and attempt.executed_valid_ticks > 0 else ZERO_SHA256
            execution_receipt_sha = ZERO_SHA256
            if successful_sha != ZERO_SHA256:
                receipt_binding = {
                    "content_sha256": successful_sha,
                    "start_tick": attempt.start_tick,
                    "end_tick": tick + 1,
                }
                execution_receipt_sha = sha256_bytes(canonical_bytes(receipt_binding))
                execution_receipts.append(MappingProxyType({
                    **receipt_binding,
                    "executed_valid_ticks": attempt.executed_valid_ticks,
                    "receipt_sha256": execution_receipt_sha,
                }))
            if completed_level is DecisionLevel.CONTROL and active is not None:
                make_command(tick + 1, str(active.record["object_id"]), active.path, active.segment_index)
            before = budget
            observable = _observable(
                tick=tick + 1,
                trace_rows=trace_rows,
                action_valid=command_is_valid(),
                geometry_feasible=_path_clear(active, obstacle_active, realization, world.site_xy()),
                semantic_preconditions_valid=semantic_valid(),
                memory_version=memory_version,
                command_content_sha256=ZERO_SHA256 if active is None else str(active.record["content_sha256"]),
                successful_execution_content_sha256=successful_sha,
                command_gap_ticks=gap_ticks if gap_ticks > VALID_COMMAND_GAP_TICKS else 0,
                reobserve_index=reobserve_index + 1,
            )
            attempt = None
            reobserve_index += 1
            event = decide(spec.architecture, observable, before)
            observations.append(observable)
            decisions.append(event)
            if event.budget_before.active_content_sha256 != before.active_content_sha256:
                resets.append(MappingProxyType({
                    "tick": observable.tick,
                    "old_content_sha256": before.active_content_sha256,
                    "new_content_sha256": event.budget_before.active_content_sha256,
                    "successful_execution_content_sha256": successful_sha,
                    "execution_receipt_sha256": execution_receipt_sha,
                }))
            budget = event.budget_after
            if event.level is DecisionLevel.SAFE_ABORT:
                aborted = True
                hold_q = world.state()[0]
            elif event.level is not DecisionLevel.NONE:
                start_attempt(event, observable.tick)

    combined_trajectories = b"".join(len(item).to_bytes(8, "little") + item for item in trajectories)
    executed_ticks = sum(item["mode"] == "EXECUTE" for item in action_envelopes)
    return V3EpisodeRaw(
        spec,
        realization,
        receipt,
        _controller_binding(spec, arm_module),
        tuple(injection_rows),
        MappingProxyType(parameter_use),
        hidden_cause,
        tuple(world_ledger),
        tuple(semantic_events),
        tuple(memory_ledger),
        tuple(memory_events),
        tuple(observations),
        tuple(decisions),
        tuple(resets),
        tuple(execution_receipts),
        tuple(commands),
        combined_trajectories,
        tuple(action_envelopes),
        tuple(contact_envelopes),
        _readonly_trace(trace_rows),
        MappingProxyType({"aborted": aborted, "executed_ticks": executed_ticks}),
    )


__all__ = ["PrecheckReceipt", "V3EpisodeRaw", "V3EpisodeSpec", "precheck", "run_episode"]
