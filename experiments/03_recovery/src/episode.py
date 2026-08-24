"""MuJoCo execution and complete in-memory episode evidence for Experiment 03."""

from __future__ import annotations

from dataclasses import dataclass, replace
import importlib
import math
from types import MappingProxyType
from typing import Mapping

import numpy as np

from reflect.types import Constraint, ObjectBelief, Observation, Pose, Predicate, RobotState, SkillSpec

from .cell import (
    PRIMARY_CONTROLLER,
    SENSITIVITY_CONTROLLER,
    ScenarioSpec,
    SemanticCell,
    SemanticPlanningError,
    controller_config,
    plan_skill,
    precheck,
    replace_fact,
    scenario_specs,
)
from .contracts import (
    Architecture,
    EpisodeSpec,
    MemorySnapshot,
    MotionCommand,
    ObservableFailure,
    RecoveryBudget,
    RecoveryDecision,
    RecoveryLevel,
    SkillRequest,
    TerminalDisposition,
    canonical_bytes,
    sha256_bytes,
)
from .recovery import decide_recovery


EPISODE_TICKS = 3125
TIMESTEP_S = 0.002


@dataclass(frozen=True)
class EpisodeEvidence:
    spec: EpisodeSpec
    scenario_sha256: str
    feasibility_sha256: str
    controller_fingerprint: Mapping[str, object]
    semantic_plans: tuple[SkillRequest, ...]
    memory_snapshots: tuple[MemorySnapshot, ...]
    motion_commands: tuple[MotionCommand, ...]
    recovery_observations: tuple[ObservableFailure, ...]
    recovery_decisions: tuple[RecoveryDecision, ...]
    scorer: Mapping[str, object]
    terminal: TerminalDisposition
    metrics: Mapping[str, object]
    trace: Mapping[str, np.ndarray]


def _modules() -> tuple[object, object, object, object]:
    contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
    arm = importlib.import_module("experiments.01_policy_control.src.arm")
    kinematics = importlib.import_module("experiments.01_policy_control.src.kinematics")
    representations = importlib.import_module("experiments.01_policy_control.src.representations")
    return contracts, arm, kinematics, representations


def _readonly(value: np.ndarray, *, dtype: object | None = None) -> np.ndarray:
    result = np.asarray(value, dtype=dtype).copy(order="C")
    result.setflags(write=False)
    return result


def _fact(memory: MemorySnapshot, object_id: str) -> object:
    return next(item for item in memory.facts if item.object_id == object_id)


def _authorized_target(memory: MemorySnapshot) -> tuple[str, np.ndarray]:
    for fact in memory.facts:
        if fact.available and not fact.stale and not fact.unknown and "AUTHORIZED" in fact.restrictions and "FORBIDDEN" not in fact.restrictions:
            return fact.object_id, np.asarray(fact.pose_xy, dtype=np.float64)
    raise SemanticPlanningError("no authorized target")


def _skill_spec(request: SkillRequest, target_xy: np.ndarray) -> SkillSpec:
    return SkillSpec(
        request.skill_id,
        "track_target",
        (request.target_object_id,),
        Pose(np.array([target_xy[0], target_xy[1], 0.0]), np.array([1.0, 0.0, 0.0, 0.0])),
        (Constraint("workspace", {"radius_m": 0.70}),),
        Predicate("eef_error", {"max_m": 0.025}),
        6.25,
        0,
    )


def _controller_fingerprint(spec: EpisodeSpec, config: object, arm_module: object) -> Mapping[str, object]:
    common: dict[str, object] = {
        "controller_id": spec.controller_id,
        "reference_slew_rad_s": config.controller.reference_slew_rad_s,
        "pd": list(config.controller.pd_candidates[0]),
        "arm_mjcf_sha256": sha256_bytes(arm_module.MJCF_BYTES),
    }
    if spec.controller_id == PRIMARY_CONTROLLER:
        common.update({"stack_id": "P6", "residual_component_limit_rad": config.residual.component_limit_rad})
    else:
        common.update({"stack_id": "P4", "lookahead_ticks": 1, "dq_feedforward": True})
    return MappingProxyType(common)


def _new_motion_command(
    *,
    spec: EpisodeSpec,
    request: SkillRequest,
    memory: MemorySnapshot,
    q: np.ndarray,
    dq: np.ndarray,
    tick: int,
    sequence: int,
    config: object,
    contracts: object,
    kinematics: object,
    representations: object,
    p6_nominal_q_initial: np.ndarray,
    p6_nominal_q_target: np.ndarray,
) -> tuple[MotionCommand, object, object, np.ndarray]:
    fact = _fact(memory, request.target_object_id)
    target = np.asarray(fact.pose_xy, dtype=np.float64)
    observation = Observation(
        sequence,
        tick * 2_000_000,
        tick * 2_000_000,
        RobotState(q, dq),
        tuple(
            ObjectBelief(item.object_id, item.semantic_label, np.asarray(item.pose_xy), item.confidence, {"available": item.available}, item.confidence, item.observed_tick * 2_000_000, (item.provenance,))
            for item in memory.facts
        ),
        request.skill_id,
        "track_target",
    )
    q_target = kinematics.absolute_ik(target, q, config.arm.link_lengths_m, config.controller.ik_damping_candidates[0], config)
    policy = contracts.PolicyInput(
        observation,
        _skill_spec(request, target),
        tick * 2_000_000,
        100_000_000,
        p6_nominal_q_initial,
        p6_nominal_q_target,
    )
    stack = contracts.CommandStack.P6 if spec.controller_id == PRIMARY_CONTROLLER else contracts.CommandStack.P4
    chunk = representations.emit_chunk(stack, policy, config)
    if stack is contracts.CommandStack.P4:
        chunk = representations.with_p4_executor_tuning(chunk, representations.P4ExecutorTuning(1, True))
    trajectory_sha = sha256_bytes(np.asarray(chunk.actions, dtype="<f8").tobytes(order="C"))
    command_id = f"command-{sequence:03d}"
    command_sha = sha256_bytes(canonical_bytes({
        "command_id": command_id,
        "object_id": request.target_object_id,
        "trajectory_sha256": trajectory_sha,
        "generated_tick": tick,
    }))
    return MotionCommand(command_id, request.target_object_id, tuple(target), True, trajectory_sha, command_sha, tick), chunk, stack, q_target


def _inject(scenario: ScenarioSpec, memory: MemorySnapshot, arm: object) -> tuple[MemorySnapshot, bool, bool, int, np.ndarray | None]:
    """Return observable contract state; scorer label never crosses this seam."""
    action_valid = True
    geometry_feasible = True
    safe_hold_until = 0
    hold_q: np.ndarray | None = None
    if scenario.scenario_id == "control-impulse":
        magnitude = dict(scenario.parameters)["impulse_dq_rad_s"]
        arm.data.qvel[:3] += np.array([magnitude, -magnitude, magnitude / 2.0])
    elif scenario.scenario_id == "control-dropout":
        safe_hold_until = scenario.injection_tick + int(dict(scenario.parameters)["dropout_ticks"])
        hold_q = np.array(arm.data.qpos[:3], copy=True)
    elif scenario.scenario_id == "motion-target-shift":
        original = _fact(memory, "object-a")
        shift = dict(scenario.parameters)["target_shift_m"]
        memory = replace_fact(memory, "object-a", pose_xy=(original.pose_xy[0], original.pose_xy[1] + shift), observed_tick=scenario.injection_tick)
        action_valid = False
    elif scenario.scenario_id == "motion-path-infeasible":
        geometry_feasible = False
    elif scenario.scenario_id == "semantic-object-unavailable":
        memory = replace_fact(memory, "object-a", available=False, observed_tick=scenario.injection_tick)
        action_valid = False
    elif scenario.scenario_id == "semantic-restriction-change":
        memory = replace_fact(memory, "object-a", restrictions=("FORBIDDEN",), observed_tick=scenario.injection_tick)
        action_valid = False
    return memory, action_valid, geometry_feasible, safe_hold_until, hold_q


def run_episode(spec: EpisodeSpec) -> EpisodeEvidence:
    """Execute one fixed 500 Hz MuJoCo episode and retain all evidence inputs."""
    scenarios = {item.scenario_id: item for item in scenario_specs()}
    if spec.scenario_id not in scenarios or scenarios[spec.scenario_id].domain is not spec.scenario_domain:
        raise ValueError("episode scenario/domain mismatch")
    expected_controller = SENSITIVITY_CONTROLLER if spec.sensitivity else PRIMARY_CONTROLLER
    if spec.controller_id != expected_controller or (spec.sensitivity and spec.architecture is not Architecture.LAYER_MATCHED):
        raise ValueError("episode controller/slice mismatch")
    scenario = scenarios[spec.scenario_id]
    receipt = precheck(scenario, spec.controller_id)
    if not receipt.feasible:
        raise RuntimeError("frozen feasibility gate returned NOT_RUN")

    contracts, arm_module, kinematics, representations = _modules()
    config = controller_config(spec.controller_id)
    robot = arm_module.PlanarArm(config)
    q0 = np.array([0.35, -0.70, 0.35], dtype=np.float64)
    robot.reset(q0)
    semantic = SemanticCell.initial()
    memory = semantic.memory
    skill = semantic.skill
    semantic_plans = [skill]
    memory_snapshots = [memory]
    motion_commands: list[MotionCommand] = []
    observations: list[ObservableFailure] = []
    decisions: list[RecoveryDecision] = []
    command = chunk = stack = None
    q_target = np.array(q0, copy=True)
    executor_state = representations.initial_executor_state(q0)
    command_sequence = 0
    previous_q_ref = np.array(q0, copy=True)
    initial_tick = 25 if scenario.scenario_id == "anchor-slow-policy" else 0
    budget: RecoveryBudget | None = None
    previous_level = RecoveryLevel.NONE
    safe_hold_until = 0
    hold_q: np.ndarray | None = None
    terminal = TerminalDisposition.SUCCESS
    resolved_tick: int | None = None
    local_recoveries = motion_replans = action_refreshes = retriggers = semantic_replans = unnecessary_semantic = 0
    repeated_state = False
    initial_target = np.asarray(_fact(memory, skill.target_object_id).pose_xy, dtype=np.float64)
    p6_nominal_target = kinematics.absolute_ik(
        initial_target, q0, config.arm.link_lengths_m, config.controller.ik_damping_candidates[0], config
    )

    trace: dict[str, np.ndarray] = {
        "tick": np.arange(EPISODE_TICKS, dtype=np.int32),
        "q": np.zeros((EPISODE_TICKS, 3), dtype=np.float64),
        "dq": np.zeros((EPISODE_TICKS, 3), dtype=np.float64),
        "q_ref": np.zeros((EPISODE_TICKS, 3), dtype=np.float64),
        "dq_ref": np.zeros((EPISODE_TICKS, 3), dtype=np.float64),
        "action": np.zeros((EPISODE_TICKS, 3), dtype=np.float64),
        "torque": np.zeros((EPISODE_TICKS, 3), dtype=np.float64),
        "target_error_m": np.zeros(EPISODE_TICKS, dtype=np.float64),
        "action_age_s": np.zeros(EPISODE_TICKS, dtype=np.float64),
        "safe_hold": np.zeros(EPISODE_TICKS, dtype=np.bool_),
        "saturation": np.zeros(EPISODE_TICKS, dtype=np.bool_),
        "clamp": np.zeros(EPISODE_TICKS, dtype=np.bool_),
        "discontinuity": np.zeros(EPISODE_TICKS, dtype=np.float64),
    }

    def generate(current_tick: int) -> None:
        nonlocal command, chunk, stack, q_target, command_sequence, executor_state, budget, previous_level
        q_now, dq_now = robot.state()
        command, chunk, stack, q_target = _new_motion_command(
            spec=spec,
            request=skill,
            memory=memory,
            q=q_now,
            dq=dq_now,
            tick=current_tick,
            sequence=command_sequence,
            config=config,
            contracts=contracts,
            kinematics=kinematics,
            representations=representations,
            p6_nominal_q_initial=q0,
            p6_nominal_q_target=p6_nominal_target,
        )
        command_sequence += 1
        motion_commands.append(command)
        executor_state = representations.initial_executor_state(previous_q_ref)
        budget = RecoveryBudget.initial(command.command_sha256)
        previous_level = RecoveryLevel.NONE

    for tick in range(EPISODE_TICKS):
        if command is None and tick == initial_tick:
            generate(tick)

        ordinary_refresh = (
            command is not None
            and tick > initial_tick
            and (tick - initial_tick) % 50 == 0
            and tick != scenario.injection_tick
            and tick >= safe_hold_until
            and terminal is TerminalDisposition.SUCCESS
        )
        if ordinary_refresh:
            generate(tick)

        if scenario.injection_tick == tick:
            if command is None or budget is None:
                raise RuntimeError("disturbance preceded initial command")
            memory_before = memory
            memory, action_valid, geometry_feasible, safe_hold_until, hold_q = _inject(scenario, memory, robot)
            if memory != memory_before:
                memory_snapshots.append(memory)
            semantic_valid = True
            try:
                plan_skill(memory, preferred_object_id=skill.target_object_id)
            except SemanticPlanningError:
                semantic_valid = False

            for recovery_index in range(6):
                observable = ObservableFailure(
                    scenario.domain.value == "CONTROL",
                    True,
                    action_valid,
                    geometry_feasible,
                    semantic_valid,
                    previous_level,
                    command.command_sha256,
                    False,
                    tick + recovery_index,
                )
                observations.append(observable)
                decision = decide_recovery(spec.architecture, observable, budget, command.command_sha256)
                decisions.append(decision)
                budget = decision.budget
                if decision.level is RecoveryLevel.SAFE_ABORT:
                    terminal = TerminalDisposition.SAFE_ABORT
                    hold_q = np.array(robot.data.qpos[:3], copy=True)
                    safe_hold_until = EPISODE_TICKS
                    break
                if decision.level is RecoveryLevel.CONTROL:
                    local_recoveries += 1
                    if scenario.domain.value == "CONTROL":
                        resolved_tick = tick + recovery_index
                        break
                elif decision.level is RecoveryLevel.MOTION:
                    motion_replans += 1
                    action_refreshes += 1
                    if semantic_valid:
                        generate(tick + recovery_index)
                        geometry_feasible = True
                        action_valid = True
                        resolved_tick = tick + recovery_index
                        break
                elif decision.level is RecoveryLevel.SEMANTIC:
                    semantic_replans += 1
                    unnecessary_semantic += int(scenario.domain.value != "SEMANTIC")
                    try:
                        preferred = skill.target_object_id if semantic_valid else None
                        skill = plan_skill(memory, preferred_object_id=preferred)
                        semantic_plans.append(skill)
                        generate(tick + recovery_index)
                        semantic_valid = action_valid = geometry_feasible = True
                        resolved_tick = tick + recovery_index
                        break
                    except SemanticPlanningError:
                        terminal = TerminalDisposition.SAFE_ABORT
                        hold_q = np.array(robot.data.qpos[:3], copy=True)
                        safe_hold_until = EPISODE_TICKS
                        break
                previous_level = decision.level
            else:
                repeated_state = True
                terminal = TerminalDisposition.SAFE_ABORT
                hold_q = np.array(robot.data.qpos[:3], copy=True)
                safe_hold_until = EPISODE_TICKS

        q, dq = robot.state()
        finite = np.isfinite(q).all() and np.isfinite(dq).all()
        if not finite:
            terminal = TerminalDisposition.INVALID_EVIDENCE
            q = np.nan_to_num(q)
            dq = np.nan_to_num(dq)
            hold_q = np.array(q, copy=True)
            safe_hold_until = EPISODE_TICKS

        safe_hold = tick < initial_tick or tick < safe_hold_until or terminal is not TerminalDisposition.SUCCESS
        if safe_hold or chunk is None or stack is None:
            requested_q = np.array(q if hold_q is None else hold_q, copy=True)
            requested_dq = np.zeros(3)
            representation_clamped = False
        else:
            reference, executor_state, report = representations.reference_for_tick(
                stack, chunk, q, dq, tick * 2_000_000, executor_state, config
            )
            requested_q = np.asarray(reference.q_ref)
            requested_dq = np.asarray(reference.dq_ref)
            representation_clamped = report.reference_clamped

        prior = requested_q if safe_hold else previous_q_ref
        q_ref, torque, controller_report = arm_module.bounded_pd(
            q,
            dq,
            requested_q,
            prior,
            config.controller.pd_candidates[0][0],
            config.controller.pd_candidates[0][1],
            config,
            desired_dq=requested_dq,
        )
        target_object_id, mission_target = _authorized_target(memory)
        eef = robot.site_xy()
        trace["q"][tick] = q
        trace["dq"][tick] = dq
        trace["q_ref"][tick] = q_ref
        trace["dq_ref"][tick] = requested_dq
        trace["action"][tick] = q_target
        trace["torque"][tick] = torque
        trace["target_error_m"][tick] = np.linalg.norm(eef - mission_target)
        trace["action_age_s"][tick] = 0.0 if command is None else max(0, tick - command.generated_tick) * TIMESTEP_S
        trace["safe_hold"][tick] = safe_hold
        trace["saturation"][tick] = controller_report.torque_clamped
        trace["clamp"][tick] = representation_clamped or controller_report.reference_clamped or controller_report.joint_clamped
        trace["discontinuity"][tick] = np.linalg.norm(np.asarray(q_ref) - previous_q_ref)
        previous_q_ref = np.array(q_ref, copy=True)
        robot.step(torque)

    final_error = float(trace["target_error_m"][-1])
    dwell = bool(np.all(trace["target_error_m"][-50:] <= config.thresholds.success_radius_m))
    current_object, _ = _authorized_target(memory)
    correct_object = bool(command is not None and command.object_id == current_object)
    if terminal is TerminalDisposition.SUCCESS and not (dwell and correct_object):
        terminal = TerminalDisposition.SAFE_ABORT
    levels = [item.level.value for item in decisions]
    repeated_state = repeated_state or len(levels) > 5
    lowest_correct = scenario.intended_level is RecoveryLevel.NONE or bool(decisions and decisions[0].level is scenario.intended_level)
    unsafe_count = int(np.count_nonzero(~np.isfinite(trace["q"])) + np.count_nonzero(~np.isfinite(trace["torque"])))
    metrics: dict[str, object] = {
        "eventual_success": terminal is TerminalDisposition.SUCCESS,
        "terminal_disposition": terminal.value,
        "unsafe_count": unsafe_count,
        "forbidden_action_count": 0,
        "lowest_sufficient_level": scenario.intended_level.value,
        "lowest_sufficient_correct": lowest_correct,
        "recovery_latency_s": None if scenario.injection_tick is None or resolved_tick is None else (resolved_tick - scenario.injection_tick) * TIMESTEP_S,
        "semantic_replans": semantic_replans,
        "unnecessary_semantic_wakeups": unnecessary_semantic,
        "motion_replans": motion_replans,
        "action_refreshes": action_refreshes,
        "retriggers": retriggers,
        "bounded_local_recoveries": local_recoveries,
        "repeated_state_retry_loop": repeated_state,
        "stale_or_contradictory_memory_decisions": 0,
        "final_target_error_m": final_error,
        "mean_tracking_error_m": float(np.mean(trace["target_error_m"])),
        "p95_tracking_error_m": float(np.quantile(trace["target_error_m"], 0.95)),
        "saturation_fraction": float(np.mean(trace["saturation"])),
        "clamp_fraction": float(np.mean(trace["clamp"])),
        "discontinuity_mean": float(np.mean(trace["discontinuity"])),
        "action_age_p95_s": float(np.quantile(trace["action_age_s"], 0.95)),
        "safe_hold_duration_s": float(np.count_nonzero(trace["safe_hold"]) * TIMESTEP_S),
        "recovery_decision_count": len(decisions),
        "authorized_object_id": current_object,
    }
    scorer = MappingProxyType({
        "episode_id": spec.episode_id,
        "hidden_cause": scenario.scorer_label,
        "intended_lowest_sufficient_level": scenario.intended_level.value,
        "injected_tick": scenario.injection_tick,
        "parameters": dict(scenario.parameters),
    })
    frozen_trace = MappingProxyType({name: _readonly(value) for name, value in trace.items()})
    return EpisodeEvidence(
        spec,
        scenario.sha256,
        receipt.geometry_sha256,
        _controller_fingerprint(spec, config, arm_module),
        tuple(semantic_plans),
        tuple(memory_snapshots),
        tuple(motion_commands),
        tuple(observations),
        tuple(decisions),
        scorer,
        terminal,
        MappingProxyType(metrics),
        frozen_trace,
    )


__all__ = ["EPISODE_TICKS", "EpisodeEvidence", "run_episode"]
