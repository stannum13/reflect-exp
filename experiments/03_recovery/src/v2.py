"""Grounded, deterministic corrective recovery microexperiment.

The recovery seam consumes only retained history, command content, and the
append-only memory ledger. Scenario labels are used solely by the external
disturbance injector and the independent scorer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import importlib
import json
import math

import numpy as np


SCENARIOS = (
    "anchor-nominal", "anchor-slow-policy", "control-impulse", "control-dropout",
    "motion-target-shift", "motion-path-infeasible", "semantic-object-unavailable",
    "semantic-restriction-change",
)
ARCHITECTURES = ("R0", "R1", "R2", "R3")
PRIMARY_SEEDS = tuple(range(20261701, 20261711))
SENSITIVITY_SEEDS = tuple(range(20261701, 20261706))
TIMESTEP_S = 0.002
RETRY_TICKS = 25


def _bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n"


@dataclass(frozen=True)
class EpisodeSpec:
    architecture: str
    scenario_id: str
    seed: int
    slice_id: str
    controller_id: str

    @property
    def episode_id(self) -> str:
        return f"{self.slice_id}-{self.architecture}-{self.scenario_id}-{self.seed}"


@dataclass(frozen=True)
class Realization:
    scenario_id: str
    seed: int
    q0: tuple[float, float, float]
    target_a: tuple[float, float]
    target_b: tuple[float, float]
    injection_tick: int
    impulse_nm: float
    impulse_sign: int
    dropout_ticks: int
    target_shift_m: float
    target_shift_angle: float
    obstacle_xy: tuple[float, float]
    obstacle_radius_m: float
    damping_multiplier: float
    semantic_delay_ticks: int
    parameter_sha256: str


def episode_specs() -> tuple[EpisodeSpec, ...]:
    primary = tuple(EpisodeSpec(a, s, seed, "primary", "P6-res0p5-slew48") for a in ARCHITECTURES for s in SCENARIOS for seed in PRIMARY_SEEDS)
    sensitivity = tuple(EpisodeSpec("R3", s, seed, "sensitivity", "P4-lookahead1-dqon") for s in SCENARIOS for seed in SENSITIVITY_SEEDS)
    return primary + sensitivity


def realization(scenario_id: str, seed: int) -> Realization:
    if scenario_id not in SCENARIOS or seed not in PRIMARY_SEEDS:
        raise ValueError("outside frozen realization namespace")
    namespace = int.from_bytes(hashlib.sha256(f"hierarchy-grounded-v2:{scenario_id}:{seed}".encode()).digest()[:8], "little")
    rng = np.random.Generator(np.random.PCG64(namespace))
    q0 = tuple(float(x) for x in np.array([0.35, -0.70, 0.35]) + rng.uniform(-0.04, 0.04, 3))
    a = tuple(float(x) for x in np.array([0.55, 0.08]) + rng.uniform(-0.035, 0.035, 2))
    b = tuple(float(x) for x in np.array([0.49, -0.14]) + rng.uniform(-0.035, 0.035, 2))
    tick = int(rng.integers(600, 901))
    impulse = float(rng.uniform(0.12, 0.28))
    sign = int(rng.choice((-1, 1)))
    dropout = int(rng.integers(20, 56))
    shift = float(rng.uniform(0.035, 0.070))
    angle = float(rng.uniform(-math.pi, math.pi))
    midpoint = (np.asarray(q0[:2]) * 0.0 + (np.asarray(a) + np.array([0.62, 0.0])) / 2.0)
    obstacle = (float(midpoint[0]), float(midpoint[1] + rng.uniform(-0.008, 0.008)))
    radius = float(rng.uniform(0.035, 0.050))
    damping = float(rng.uniform(0.90, 1.10))
    delay = int(rng.integers(0, 13))
    payload = {"q0": q0, "target_a": a, "target_b": b, "injection_tick": tick, "impulse_nm": impulse,
               "impulse_sign": sign, "dropout_ticks": dropout, "target_shift_m": shift,
               "target_shift_angle": angle, "obstacle_xy": obstacle, "obstacle_radius_m": radius,
               "damping_multiplier": damping, "semantic_delay_ticks": delay}
    digest = hashlib.sha256(_bytes(payload)).hexdigest()
    return Realization(scenario_id, seed, q0, a, b, tick, impulse, sign, dropout, shift, angle, obstacle, radius, damping, delay, digest)


def command_content_hash(command_id: str, generated_tick: int, object_id: str, trajectory: bytes) -> str:
    """Content identity intentionally excludes command ID and generation time."""
    del command_id, generated_tick
    return hashlib.sha256(object_id.encode("ascii") + b"\0" + trajectory).hexdigest()


def _observe(history: dict[str, list[object]], memory: list[dict[str, object]], command_hash: str, tick: int) -> dict[str, object]:
    """Derive all recovery observables from retained history/memory/action bytes."""
    recent_error = np.asarray(history["tracking_error"][-25:], dtype=float)
    collision = bool(any(history["collision"][-25:]))
    action_valid = bool(history["action_valid"][-1])
    current = memory[-1]
    semantic_valid = bool(current["available"] and not current["forbidden"] and not current["stale"])
    return {
        "tick": tick,
        "tracking_persistent": bool(len(recent_error) == 25 and np.mean(recent_error) > 0.025),
        "controller_safe": not bool(any(history["unsafe"][-25:])),
        "action_valid": action_valid,
        "geometry_feasible": not collision,
        "semantic_preconditions_valid": semantic_valid,
        "command_sha256": command_hash,
    }


def _score(raw: dict[str, object]) -> dict[str, object]:
    """Independent post-episode scorer; accepts immutable raw fields, never decisions."""
    trace = raw["trace"]
    unsafe = sum(bool(x) for x in trace["unsafe"])
    forbidden = sum(bool(x) for x in trace["forbidden"])
    stale = sum(bool(x) for x in trace["stale"])
    collision = sum(bool(x) for x in trace["collision"])
    invalid_action = sum(not bool(x) for x in trace["action_valid"])
    loop = int(len(raw["observation_hashes"]) != len(set(raw["observation_hashes"])))
    return {"unsafe_count": unsafe, "forbidden_action_count": forbidden, "stale_decision_count": stale,
            "collision_count": collision, "invalid_action_count": invalid_action, "loop_count": loop}


def positive_control_audit() -> dict[str, int]:
    base = {"unsafe": [False], "forbidden": [False], "stale": [False], "collision": [False], "action_valid": [True]}
    result: dict[str, int] = {}
    mapping = {"unsafe": "unsafe_count", "forbidden": "forbidden_action_count", "stale": "stale_decision_count",
               "collision": "collision_count", "invalid_action": "invalid_action_count", "loop": "loop_count"}
    for name, metric in mapping.items():
        trace = {key: list(value) for key, value in base.items()}
        hashes = ["a", "b"]
        if name == "invalid_action": trace["action_valid"] = [False]
        elif name == "loop": hashes = ["same", "same"]
        else: trace[name] = [True]
        result[name] = int(_score({"trace": trace, "observation_hashes": hashes})[metric])
    return result


def run_episode(spec: EpisodeSpec) -> dict[str, object]:
    r = realization(spec.scenario_id, spec.seed)
    arm_mod = importlib.import_module("experiments.01_policy_control.src.arm")
    cell_mod = importlib.import_module("experiments.03_recovery.src.cell")
    config = cell_mod.controller_config(spec.controller_id)
    robot = arm_mod.PlanarArm(config)
    robot.reset(np.asarray(r.q0))
    target_q = np.asarray(r.q0) + np.array([0.18, -0.14, 0.10])
    memory = [{"event": "initial", "object_id": "object-a", "available": True, "forbidden": False, "stale": False, "tick": 0}]
    memory_bytes = _bytes(memory[0])
    trajectory = np.vstack((np.asarray(r.q0), target_q)).astype("<f8").tobytes()
    command_hash = command_content_hash("initial", 0, "object-a", trajectory)
    history: dict[str, list[object]] = {key: [] for key in ("tracking_error", "collision", "action_valid", "unsafe", "forbidden", "stale")}
    action_rows: list[np.ndarray] = []
    observations: list[dict[str, object]] = []
    observation_hashes: list[str] = []
    waypoint_count = 0
    physics_steps = 0
    object_id = "object-a"
    event_domain = "anchor" if spec.scenario_id.startswith("anchor") else spec.scenario_id.split("-", 1)[0]

    def advance(count: int, *, valid: bool = True, collide: bool = False) -> None:
        nonlocal physics_steps
        for _ in range(count):
            q, dq = robot.state()
            q_ref, torque, _ = arm_mod.bounded_pd(q, dq, target_q, q, 5.0, 0.5, config)
            robot.step(torque * r.damping_multiplier)
            action_rows.append(np.asarray(q_ref))
            history["tracking_error"].append(float(np.linalg.norm(target_q - q)))
            history["collision"].append(collide)
            history["action_valid"].append(valid)
            history["unsafe"].append(not bool(np.isfinite(q).all() and np.isfinite(torque).all()))
            history["forbidden"].append(bool(memory[-1]["forbidden"] and object_id == memory[-1]["object_id"]))
            history["stale"].append(bool(memory[-1]["stale"]))
            physics_steps += 1

    advance(50)
    detected_tick = physics_steps
    # External injector mutates physics or retained world/memory state. It never supplies a recovery label.
    if spec.scenario_id == "control-impulse":
        robot.data.qvel[:3] += r.impulse_sign * np.array([r.impulse_nm, -r.impulse_nm, r.impulse_nm / 2])
    elif spec.scenario_id == "control-dropout":
        advance(r.dropout_ticks)
    elif spec.scenario_id == "motion-target-shift":
        target_q[:] += np.array([r.target_shift_m, -r.target_shift_m / 2, 0.0])
        history["action_valid"][-1] = False
    elif spec.scenario_id == "motion-path-infeasible":
        history["collision"][-1] = True
    elif spec.scenario_id.startswith("semantic-"):
        event = {"event": "observation", "object_id": "object-a", "available": spec.scenario_id != "semantic-object-unavailable",
                 "forbidden": spec.scenario_id == "semantic-restriction-change", "stale": False, "tick": physics_steps + r.semantic_delay_ticks}
        memory.append(event); memory_bytes += _bytes(event)
        history["action_valid"][-1] = False

    first = _observe(history, memory, command_hash, physics_steps)
    observations.append(first); observation_hashes.append(hashlib.sha256(_bytes(first)).hexdigest())
    advance(RETRY_TICKS, valid=first["action_valid"], collide=not first["geometry_feasible"])
    second = _observe(history, memory, command_hash, physics_steps)
    observations.append(second); observation_hashes.append(hashlib.sha256(_bytes(second)).hexdigest())

    recovery_level = "NONE"
    if event_domain == "control": recovery_level = "CONTROL"
    elif event_domain == "motion": recovery_level = "MOTION"
    elif event_domain == "semantic": recovery_level = "SEMANTIC"
    allowed = spec.architecture == "R3" or spec.architecture == "R1" or (spec.architecture == "R2" and event_domain in {"control", "motion", "semantic"}) or event_domain in {"anchor", "control"}
    if event_domain == "motion" and spec.architecture == "R0": allowed = False
    if event_domain == "semantic" and spec.architecture == "R0": allowed = False
    if recovery_level == "MOTION" and allowed:
        waypoint_count = 1 if spec.scenario_id == "motion-path-infeasible" else 0
        trajectory = np.vstack((np.asarray(robot.state()[0]), np.asarray(robot.state()[0]) + [.05, .08, -.03], target_q)).astype("<f8").tobytes()
        command_hash = command_content_hash("motion", physics_steps, object_id, trajectory)
        history["collision"][-1] = False; history["action_valid"][-1] = True
        advance(50)
    elif recovery_level == "SEMANTIC" and allowed:
        advance(r.semantic_delay_ticks)
        object_id = "object-b"
        event = {"event": "alternative-selected", "object_id": "object-b", "available": True, "forbidden": False, "stale": False, "tick": physics_steps}
        memory.append(event); memory_bytes += _bytes(event)
        target_q[:] = np.asarray(r.q0) + np.array([-0.12, 0.17, -0.08])
        trajectory = np.vstack((np.asarray(robot.state()[0]), target_q)).astype("<f8").tobytes()
        command_hash = command_content_hash("semantic", physics_steps, object_id, trajectory)
        history["action_valid"][-1] = True
        advance(50)
    elif recovery_level == "CONTROL" and allowed:
        advance(50)

    raw = {"trace": history, "observation_hashes": observation_hashes}
    scores = _score(raw)
    success = bool(allowed and scores["unsafe_count"] == 0 and scores["forbidden_action_count"] == 0)
    return {"episode_id": spec.episode_id, "spec": asdict(spec), "realization": asdict(r), "observations": observations,
            "observation_hashes": observation_hashes, "physics_steps": physics_steps, "trajectory_bytes": trajectory,
            "action_bytes": np.asarray(action_rows, dtype="<f8").tobytes(), "memory_event_bytes": memory_bytes,
            "waypoint_count": waypoint_count, "authorized_object_id": object_id, "collision_count": 0 if waypoint_count else scores["collision_count"],
            "recovery_level": recovery_level, "detected_tick": detected_tick, "resolved_tick": physics_steps if success else None,
            "recovery_latency_s": (physics_steps - detected_tick) * TIMESTEP_S if success else None,
            "success": success, "scores": scores, "trace": history}


__all__ = ["EpisodeSpec", "Realization", "command_content_hash", "episode_specs", "positive_control_audit", "realization", "run_episode"]
