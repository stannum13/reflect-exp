"""Deterministic planar-pushing world and exact MuJoCo branch truth."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import mujoco
import numpy as np


HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text())
STRATA = ("ID", "MASS_OOD", "FRICTION_OOD", "GEOMETRY_OOD", "OBSTACLE_OOD")
STRATEGIES = (
    "DIRECT", "LEFT_EDGE", "RIGHT_EDGE", "BELOW", "DIAGONAL",
    "RETREAT_REPOSITION", "SLOW_CONSERVATIVE", "HOLD",
)
DT = float(CONFIG["episode_timestep_s"])
COMMAND_DT = float(CONFIG["candidate_dt_s"])


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _seed(*parts: object) -> int:
    return int.from_bytes(hashlib.sha256(canonical(["exp06-engineering-v1", *parts])).digest()[:8], "big")


@dataclass(frozen=True)
class SceneSpec:
    partition: str
    stratum: str
    ordinal: int
    seed: int
    scene_id: str


@dataclass(frozen=True)
class Scene:
    spec: SceneSpec
    object_xy: tuple[float, float]
    object_yaw: float
    target_xy: tuple[float, float]
    target_yaw: float
    eef_xy: tuple[float, float]
    mass: float
    friction: float
    geometry: str
    dimensions: tuple[float, float, float]
    obstacle: tuple[float, float, float, float] | None
    mjcf_sha256: str


@dataclass(frozen=True)
class Anchor:
    anchor_id: str
    index: int
    eef_xy: tuple[float, float]
    object_state: tuple[float, float, float]
    qpos: tuple[float, ...]
    qvel: tuple[float, ...]
    state_spec: int
    state_size: int
    integration_state: tuple[float, ...]
    mocap_pos: tuple[float, ...]
    mocap_quat: tuple[float, ...]
    restore_sha256: str


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    strategy_id: str
    commands: np.ndarray
    generation_counter: int
    perturbation_magnitude: float
    pre_perturbation_sha256: str
    action_sha256: str


@dataclass(frozen=True)
class Outcome:
    scene_id: str
    anchor_id: str
    candidate_id: str
    strategy_id: str
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
    anchor_restore_sha256: str
    outcome_sha256: str


def scene_rows() -> tuple[SceneSpec, ...]:
    layout: list[tuple[str, str, int]] = []
    layout.extend(("train", "ID", index) for index in range(72))
    layout.extend(("tuning", "ID", index) for index in range(24))
    layout.extend(("evaluation", "ID", index) for index in range(16))
    for stratum in STRATA[1:]:
        layout.extend(("evaluation", stratum, index) for index in range(8))
    rows = []
    for partition, stratum, ordinal in layout:
        seed = _seed("scene-v6-cycle", partition, stratum, ordinal)
        rows.append(SceneSpec(partition, stratum, ordinal, seed, f"exp06-v6/{partition}/{stratum.lower()}/{seed:016x}"))
    return tuple(rows)


def _unit(angle: float) -> np.ndarray:
    return np.array((math.cos(angle), math.sin(angle)), dtype=np.float64)


def generate_scene(spec: SceneSpec) -> Scene:
    if spec not in scene_rows():
        raise ValueError("scene spec is outside the frozen split")
    rng = np.random.Generator(np.random.PCG64(spec.seed))
    center = rng.uniform(-0.12, 0.12, size=2)
    angle = float(rng.uniform(-math.pi, math.pi)); distance = float(rng.uniform(0.22, 0.30))
    target = np.clip(center + distance * _unit(angle), -0.38, 0.38)
    yaw = float(rng.uniform(-math.pi, math.pi)); target_yaw = float(yaw + rng.uniform(-0.45, 0.45))
    mass = float(rng.uniform(0.8, 1.2)); friction = float(rng.uniform(0.4, 0.6))
    geometry = "disk" if int(rng.integers(0, 2)) == 0 else "rectangle"
    dimensions = (float(rng.uniform(0.055, 0.075)), 0.0, 0.0) if geometry == "disk" else (0.0, float(rng.uniform(0.05, 0.07)), float(rng.uniform(0.04, 0.06)))
    obstacle = None
    if int(rng.integers(0, 2)):
        mid = (center + target) / 2; perp = np.array((-math.sin(angle), math.cos(angle))) * 0.10
        obstacle = tuple(float(x) for x in (*list(mid - perp), *list(mid + perp)))
    if spec.stratum == "MASS_OOD": mass = float(rng.uniform(1.4, 1.6))
    if spec.stratum == "FRICTION_OOD": friction = float(rng.uniform(0.75, 0.9))
    if spec.stratum == "GEOMETRY_OOD":
        dimensions = (float(rng.uniform(0.085, 0.095)), 0.0, 0.0) if geometry == "disk" else (0.0, float(rng.uniform(0.08, 0.095)), float(rng.uniform(0.03, 0.04)))
    if spec.stratum == "OBSTACLE_OOD":
        mid = (center + target) / 2; along = _unit(angle) * 0.11
        obstacle = tuple(float(x) for x in (*list(mid - along), *list(mid + along)))
    support = dimensions[0] if geometry == "disk" else max(dimensions[1:])
    eef = center - (support + 0.10) * _unit(angle)
    provisional = Scene(spec, tuple(center), yaw, tuple(target), target_yaw, tuple(eef), mass, friction, geometry, dimensions, obstacle, "")
    model_bytes = build_mjcf(provisional)
    return Scene(**(asdict(provisional) | {"spec": spec, "mjcf_sha256": sha(model_bytes)}))


def _obstacle_xml(scene: Scene) -> str:
    if scene.obstacle is None:
        return ""
    x1, y1, x2, y2 = scene.obstacle; dx, dy = x2-x1, y2-y1; half = math.hypot(dx,dy)/2
    return f'<geom name="obstacle" type="box" pos="{(x1+x2)/2:.17g} {(y1+y2)/2:.17g} 0.04" size="{half:.17g} 0.018 0.04" euler="0 0 {math.atan2(dy,dx):.17g}" mass="1000" friction="1 0.005 0.0001"/>'


def build_mjcf(scene: Scene) -> bytes:
    if scene.geometry == "disk":
        object_geom = f'<geom name="object" type="cylinder" size="{scene.dimensions[0]:.17g} 0.035" mass="{scene.mass:.17g}" friction="{scene.friction:.17g} 0.005 0.0001"/>'
    else:
        object_geom = f'<geom name="object" type="box" size="{scene.dimensions[1]:.17g} {scene.dimensions[2]:.17g} 0.035" mass="{scene.mass:.17g}" friction="{scene.friction:.17g} 0.005 0.0001"/>'
    text = f'''<mujoco model="exp06-push"><option timestep="0.002" gravity="0 0 0" integrator="Euler"/><size nconmax="128"/><worldbody>
<geom name="floor" type="plane" size="1 1 0.01" pos="0 0 0" contype="0" conaffinity="0"/>
<body name="object_body" pos="0 0 0.04"><joint name="object_x" type="slide" axis="1 0 0" damping="0.15"/><joint name="object_y" type="slide" axis="0 1 0" damping="0.15"/><joint name="object_yaw" type="hinge" axis="0 0 1" damping="0.05"/>{object_geom}</body>
<body name="eef" mocap="true" pos="0 0 0.04"><geom name="eef_geom" type="cylinder" size="0.04 0.035" mass="1" friction="1 0.005 0.0001"/></body>
{_obstacle_xml(scene)}
</worldbody></mujoco>\n'''
    return text.encode()


def _new_data(scene: Scene) -> tuple[mujoco.MjModel, mujoco.MjData]:
    model = mujoco.MjModel.from_xml_string(build_mjcf(scene).decode()); data = mujoco.MjData(model)
    data.qpos[:] = (scene.object_xy[0], scene.object_xy[1], scene.object_yaw)
    data.mocap_pos[0] = (scene.eef_xy[0], scene.eef_xy[1], 0.04); mujoco.mj_forward(model, data)
    return model, data


def _advance(model: mujoco.MjModel, data: mujoco.MjData, velocity: np.ndarray) -> bool:
    collision = False
    for _ in range(10):
        data.mocap_pos[0, :2] = np.clip(data.mocap_pos[0, :2] + DT * velocity, -0.48, 0.48)
        mujoco.mj_step(model, data)
        for index in range(data.ncon):
            contact = data.contact[index]
            names = {mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, int(contact.geom1)), mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, int(contact.geom2))}
            collision |= "object" in names and "obstacle" in names
    return collision


def _anchor(scene: Scene, index: int, data: mujoco.MjData) -> Anchor:
    spec=int(mujoco.mjtState.mjSTATE_INTEGRATION);size=mujoco.mj_stateSize(data.model,spec);state=np.empty(size,dtype=np.float64);mujoco.mj_getState(data.model,data,state,spec)
    qpos=tuple(float(x) for x in data.qpos);qvel=tuple(float(x) for x in data.qvel);mocap=tuple(float(x) for x in data.mocap_pos.ravel());mocap_quat=tuple(float(x) for x in data.mocap_quat.ravel());aid=f"{scene.spec.scene_id}/anchor/{index:02d}"
    integration=tuple(float(x) for x in state);restore=sha(canonical([aid,mujoco.__version__,spec,size,integration,mocap,mocap_quat]))
    return Anchor(aid,index,(mocap[0],mocap[1]),(qpos[0],qpos[1],qpos[2]),qpos,qvel,spec,size,integration,mocap,mocap_quat,restore)


def _apply_anchor(model: mujoco.MjModel, data: mujoco.MjData, anchor: Anchor) -> str:
    expected_spec=int(mujoco.mjtState.mjSTATE_INTEGRATION)
    if anchor.state_spec!=expected_spec or anchor.state_size!=mujoco.mj_stateSize(model,expected_spec) or len(anchor.integration_state)!=anchor.state_size:
        raise ValueError("anchor integration state specification is invalid")
    state=np.asarray(anchor.integration_state,dtype=np.float64)
    mujoco.mj_setState(model,data,state,expected_spec)
    data.mocap_pos[:]=np.asarray(anchor.mocap_pos,dtype=np.float64).reshape(data.mocap_pos.shape)
    data.mocap_quat[:]=np.asarray(anchor.mocap_quat,dtype=np.float64).reshape(data.mocap_quat.shape)
    mujoco.mj_forward(model,data)
    restored=np.empty(anchor.state_size,dtype=np.float64);mujoco.mj_getState(model,data,restored,expected_spec)
    if not np.array_equal(restored,state) or not np.array_equal(data.mocap_pos.ravel(),np.asarray(anchor.mocap_pos)) or not np.array_equal(data.mocap_quat.ravel(),np.asarray(anchor.mocap_quat)):
        raise ValueError("anchor integration state did not restore exactly")
    digest=sha(canonical([anchor.anchor_id,mujoco.__version__,expected_spec,anchor.state_size,tuple(float(x) for x in restored),tuple(float(x) for x in data.mocap_pos.ravel()),tuple(float(x) for x in data.mocap_quat.ravel())]))
    if digest!=anchor.restore_sha256:raise ValueError("anchor restore hash mismatch")
    return digest


def probe_anchors(scene: Scene) -> tuple[Anchor, Anchor]:
    model,data=_new_data(scene);c=np.array(scene.object_xy);g=np.array(scene.target_xy);u=(g-c)/np.linalg.norm(g-c)
    support=_support(scene,u);contact=c-(support+0.01)*u
    anchors=[]
    for destination in (contact,contact+0.055*u):
        start=np.array(data.mocap_pos[0,:2]); velocity=(destination-start)/0.5
        for _ in range(25):_advance(model,data,velocity)
        anchors.append(_anchor(scene,len(anchors),data))
    return tuple(anchors)  # type: ignore[return-value]


def _support(scene: Scene, direction: np.ndarray) -> float:
    if scene.geometry == "disk":return scene.dimensions[0]
    yaw=scene.object_yaw;c,s=math.cos(yaw),math.sin(yaw);local=np.array((c*direction[0]+s*direction[1],-s*direction[0]+c*direction[1]))
    return abs(local[0])*scene.dimensions[1]+abs(local[1])*scene.dimensions[2]


def _commands(start: np.ndarray, phases: Iterable[tuple[float,np.ndarray]], multiplier: float) -> np.ndarray:
    phases=tuple(phases);nominal=start.copy();out=[]
    for tick in range(50):
        time=tick*COMMAND_DT;end,waypoint=next(item for item in phases if time < item[0] or item is phases[-1]);raw=multiplier*(waypoint-nominal)/max(COMMAND_DT,end-time);command=np.clip(raw,-CONFIG["command_limit_m_s"],CONFIG["command_limit_m_s"]);out.append(command);nominal+=COMMAND_DT*command
    return np.asarray(out,dtype="<f8")


def action_preimage(commands: np.ndarray) -> bytes:
    array = np.asarray(commands)
    if array.dtype != np.dtype("<f8") or array.shape != (50, 2) or not np.isfinite(array).all():
        raise ValueError("candidate commands have invalid dtype, shape, or values")
    return canonical([array.dtype.str, list(array.shape), COMMAND_DT]) + b"\0" + array.tobytes(order="C")


def _unique_commands(strategy_index: int, commands: np.ndarray, occupied: set[bytes]) -> tuple[np.ndarray, int, float]:
    original = np.asarray(commands, dtype="<f8")
    if action_preimage(original) not in occupied:
        return original, 0, 0.0
    limit = float(CONFIG["command_limit_m_s"])
    tick = (43 + 7 * strategy_index) % 50
    axis = strategy_index % 2
    for counter in range(1, 9):
        magnitude = counter * 1e-9
        candidate = original.copy()
        value = float(candidate[tick, axis])
        preferred = 1.0 if strategy_index % 2 == 0 else -1.0
        if value + preferred * magnitude > limit or value + preferred * magnitude < -limit:
            preferred *= -1.0
        candidate[tick, axis] = value + preferred * magnitude
        if np.max(np.abs(candidate)) > limit or np.max(np.abs(candidate - original)) > 8e-9:
            continue
        if action_preimage(candidate) not in occupied:
            return candidate, counter, magnitude
    raise ValueError("candidate action collision cannot be resolved within frozen perturbation bound")


def compile_candidates(scene: Scene, anchor: Anchor) -> tuple[Candidate, ...]:
    c=np.array(anchor.object_state[:2]);g=np.array(scene.target_xy);e0=np.array(anchor.eef_xy);delta=g-c;u=np.array((1.0,0.0)) if np.linalg.norm(delta)==0 else delta/np.linalg.norm(delta);v=np.array((-u[1],u[0]));hu=_support(scene,u);hv=_support(scene,v);contact=lambda n,off:c-(_support(scene,n)+.01)*n+off
    table={
        "DIRECT":(((.35,contact(u,0*v)),(1.,g-(hu-.02)*u)),1.),
        "LEFT_EDGE":(((.35,contact(u,.75*hv*v)),(1.,g+.25*hv*v)),1.),
        "RIGHT_EDGE":(((.35,contact(u,-.75*hv*v)),(1.,g-.25*hv*v)),1.),
        "BELOW":(((.35,contact(np.array((0.,1.)),0*v)),(1.,g-np.array((0.,_support(scene,np.array((0.,1.)))-.02)))),1.),
        "DIAGONAL":(((.25,c-(hu+.08)*u+.6*hv*v),(.55,contact(u,.6*hv*v)),(1.,g)),1.),
        "RETREAT_REPOSITION":(((.2,e0-.08*u),(.55,contact(u,0*v)),(1.,g)),1.),
        "SLOW_CONSERVATIVE":(((.35,contact(u,0*v)),(1.,g-(hu-.02)*u)),.5),
        "HOLD":(((1.,e0),),0.),
    }
    generated = {strategy: _commands(e0, *table[strategy]) for strategy in STRATEGIES}
    occupied: set[bytes] = {action_preimage(generated["HOLD"])}
    resolved: dict[str, tuple[np.ndarray, int, float]] = {"HOLD": (generated["HOLD"], 0, 0.0)}
    for strategy_index, strategy in enumerate(STRATEGIES[:-1]):
        commands, counter, magnitude = _unique_commands(strategy_index, generated[strategy], occupied)
        occupied.add(action_preimage(commands)); resolved[strategy] = (commands, counter, magnitude)
    result=[]
    for strategy in STRATEGIES:
        commands,counter,magnitude=resolved[strategy];cid=f"{anchor.anchor_id}/candidate/{strategy}"
        pre_hash=sha(action_preimage(generated[strategy]));action_hash=sha(action_preimage(commands))
        result.append(Candidate(cid,strategy,commands,counter,magnitude,pre_hash,action_hash))
    if len({action_preimage(x.commands) for x in result})!=8 or len({x.action_sha256 for x in result})!=8:raise ValueError("candidate command preimages are not distinct")
    return tuple(result)


def _wrap(value: float) -> float:
    return (value+math.pi)%(2*math.pi)-math.pi


def actual_cost(position_error: float,orientation_error: float,collision: bool,energy: float,terminal_failure: bool,success: bool)->float:
    return position_error**2+.1*orientation_error**2+2*float(collision)+.01*energy+4*float(terminal_failure)-float(success)


def run_candidate(scene: Scene,anchor: Anchor,candidate: Candidate)->Outcome:
    model,data=_new_data(scene);restore=_apply_anchor(model,data,anchor);collision=False
    for command in candidate.commands:collision|=_advance(model,data,command)
    terminal=tuple(float(x) for x in (*data.qpos,*data.qvel,*data.mocap_pos[0,:2]));pos=float(np.linalg.norm(data.qpos[:2]-scene.target_xy));yaw=abs(_wrap(float(data.qpos[2]-scene.target_yaw)));energy=float(np.sum(candidate.commands**2)*COMMAND_DT);unsafe=bool(not np.isfinite(terminal).all() if isinstance(terminal,np.ndarray) else not all(math.isfinite(x) for x in terminal)) or bool(np.any(np.abs(data.qpos[:2])>.5));success=bool(pos<=CONFIG["success_position_m"] and yaw<=CONFIG["success_yaw_rad"] and not unsafe);failure=not success;cost=actual_cost(pos,yaw,collision,energy,failure,success)
    wire=[scene.spec.scene_id,anchor.anchor_id,candidate.candidate_id,candidate.strategy_id,candidate.action_sha256,terminal,pos,yaw,collision,energy,unsafe,success,failure,cost,restore]
    return Outcome(scene.spec.scene_id,anchor.anchor_id,candidate.candidate_id,candidate.strategy_id,candidate.action_sha256,terminal,pos,yaw,collision,energy,unsafe,success,failure,cost,restore,sha(canonical(wire)))


def run_scene(spec: SceneSpec)->tuple[Scene,tuple[Anchor,...],tuple[Candidate,...],tuple[Outcome,...]]:
    scene=generate_scene(spec);anchors=probe_anchors(scene);candidates=[];outcomes=[]
    for anchor in anchors:
        current=compile_candidates(scene,anchor);candidates.extend(current);outcomes.extend(run_candidate(scene,anchor,item) for item in current)
    return scene,anchors,tuple(candidates),tuple(outcomes)
