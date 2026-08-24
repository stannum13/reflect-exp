from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import mujoco
import numpy as np

from . import experiment as v1


ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "config-v2.json"


class IntegrityError(RuntimeError):
    pass


@dataclass
class V2Scene:
    seed: int
    condition: str
    rgb: np.ndarray
    depth: np.ndarray
    xml: str
    contract: dict[str, Any]


@dataclass
class V2Episode:
    metadata: dict[str, Any]
    ticks: list[dict[str, Any]]


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG.read_text())


def heldout_matrix(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"seed": seed, "condition": condition, "controller": controller}
        for seed in cfg["heldout_seeds"]
        for condition in cfg["heldout_conditions"]
        for controller in cfg["controllers"]
    ]


def assert_pre_freeze_source_guard(test_source: str, cfg: dict[str, Any]) -> None:
    forbidden_condition = "EVAL" + "_X2"
    if forbidden_condition in test_source:
        raise IntegrityError("pre-freeze test names evaluation condition")
    for seed in cfg["heldout_seeds"]:
        if str(seed) in test_source:
            raise IntegrityError("held-out seed leaked into tests")
    if cfg["calibration_conditions"] != ["NO_OBSTACLE", "OPAQUE"]:
        raise IntegrityError("calibration conditions are not closed")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _array_sha(array: np.ndarray) -> str:
    return _sha_bytes(array.tobytes(order="C"))


def _scene_contract(seed: int, condition: str) -> dict[str, Any]:
    cfg = load_config()
    if condition not in cfg["heldout_conditions"]:
        raise ValueError(condition)
    rng = np.random.default_rng(seed)
    physics = {
        "start_xy": [-1.20, float(rng.uniform(-0.08, 0.08))],
        "goal_xy": [1.20, 0.0],
        "obstacle_xy": [float(rng.uniform(-0.08, 0.08)), float(rng.uniform(-0.10, 0.10))],
        "obstacle_half_size": [0.12, 0.28, 0.16],
        "robot_radius": 0.08,
        "timestep": 0.02,
        "friction": [0.9, 0.02, 0.002],
    }
    if condition == "NO_OBSTACLE":
        rgba = None
    elif condition == "OPAQUE":
        rgba = cfg["opaque_rgba"]
    else:
        rgba = cfg["eval_rgba"]
    return {
        "seed": seed,
        "condition": condition,
        "material_namespace": cfg["material_namespace"],
        "physics": physics,
        "camera": {"position": [0, 0, 3.2], "fovy": 42, "width": 96, "height": 96},
        "material_rgba": rgba,
    }


def _xml(contract: dict[str, Any]) -> str:
    p = contract["physics"]
    obstacle = ""
    if contract["material_rgba"] is not None:
        x, y = p["obstacle_xy"]
        sx, sy, sz = p["obstacle_half_size"]
        r, g, b, a = contract["material_rgba"]
        obstacle = f'<geom name="obstacle" type="box" pos="{x} {y} {sz}" size="{sx} {sy} {sz}" rgba="{r} {g} {b} {a}" friction="0.9 0.02 0.002" contype="1" conaffinity="1"/>'
    start_x, start_y = p["start_xy"]
    goal_x, goal_y = p["goal_xy"]
    return f"""<mujoco model="opaque_glass_transfer_v2">
  <option timestep="0.02" gravity="0 0 0" integrator="implicitfast"/>
  <visual><global offwidth="96" offheight="96"/><quality shadowsize="1024"/></visual>
  <worldbody>
    <light pos="-1.5 -1.0 3.0" dir="0.3 0.2 -1" diffuse="0.75 0.75 0.75"/>
    <light pos="1.5 1.0 2.5" dir="-0.3 -0.2 -1" diffuse="0.35 0.35 0.35"/>
    <camera name="overhead" pos="0 0 3.2" xyaxes="1 0 0 0 1 0" fovy="42"/>
    <geom name="floor" type="plane" size="2 1.1 0.05" rgba="0.42 0.44 0.47 1" contype="0" conaffinity="0"/>
    <geom name="wall_top" type="box" pos="0 0.92 0.12" size="1.55 0.04 0.12" rgba="0.18 0.2 0.22 1"/>
    <geom name="wall_bottom" type="box" pos="0 -0.92 0.12" size="1.55 0.04 0.12" rgba="0.18 0.2 0.22 1"/>
    {obstacle}
    <body name="robot" pos="{start_x} {start_y} 0.09">
      <joint name="x" type="slide" axis="1 0 0" damping="2"/>
      <joint name="y" type="slide" axis="0 1 0" damping="2"/>
      <geom name="robot_geom" type="sphere" size="0.08" rgba="0.05 0.25 0.95 1" mass="0.45" friction="0.8 0.02 0.002"/>
    </body>
    <site name="goal" pos="{goal_x} {goal_y} 0.03" size="0.07" rgba="0.1 0.9 0.2 1"/>
  </worldbody>
  <actuator>
    <motor name="fx" joint="x" gear="1" ctrlrange="-5 5" ctrllimited="true"/>
    <motor name="fy" joint="y" gear="1" ctrlrange="-5 5" ctrllimited="true"/>
  </actuator>
</mujoco>"""


def render_scene_v2(seed: int, condition: str) -> V2Scene:
    contract = _scene_contract(seed, condition)
    xml = _xml(contract)
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    rgb, depth = v1._render(model, data)
    return V2Scene(seed, condition, rgb, depth, xml, contract)


def _detector(scene: V2Scene, empty_depth: np.ndarray, controller: str) -> v1.Detection:
    if controller == "RGB_ONLY":
        return v1.detect_rgb(scene.rgb)
    return v1.detect_depth(scene.rgb, scene.depth, empty_depth)


def _route(detection: v1.Detection, goal: list[float]) -> list[list[float]]:
    if not detection.present or detection.center_xy is None:
        return [list(goal)]
    ox, oy = detection.center_xy
    side = -1.0 if oy >= 0 else 1.0
    return [[ox - 0.22, side * 0.55], [ox + 0.25, side * 0.55], list(goal)]


def _contacts(model: mujoco.MjModel, data: mujoco.MjData) -> list[dict[str, Any]]:
    rows = []
    force = np.zeros(6, dtype=np.float64)
    for index in range(data.ncon):
        contact = data.contact[index]
        mujoco.mj_contactForce(model, data, index, force)
        rows.append({"geom1": int(contact.geom1), "geom2": int(contact.geom2), "normal_force": float(force[0])})
    return rows


def run_episode_v2(scene: V2Scene, empty_depth: np.ndarray, controller: str) -> V2Episode:
    cfg = load_config()
    model = mujoco.MjModel.from_xml_string(scene.xml)
    data = mujoco.MjData(model)
    detection = _detector(scene, empty_depth, controller)
    route = _route(detection, scene.contract["physics"]["goal_xy"])
    waypoint = 0
    best = math.inf
    stall = 0
    replans = retries = semantic_wakes = 0
    xml_hash = _sha_bytes(scene.xml.encode())
    rgb_hash = _array_sha(scene.rgb)
    depth_hash = _array_sha(scene.depth)
    world_hash = _sha_bytes(_canonical(scene.contract["physics"]))
    material_hash = _sha_bytes(_canonical({"namespace": scene.contract["material_namespace"], "rgba": scene.contract["material_rgba"]}))
    detection_record = asdict(detection)
    detection_hash = _sha_bytes(_canonical(v1._json_finite(detection_record)))
    start = np.asarray(scene.contract["physics"]["start_xy"], dtype=float)
    ticks: list[dict[str, Any]] = []
    for tick in range(cfg["max_ticks"]):
        world = start + data.qpos[:2]
        target = np.asarray(route[waypoint])
        if np.linalg.norm(target - world) < 0.10 and waypoint < len(route) - 1:
            waypoint += 1
            target = np.asarray(route[waypoint])
            best = math.inf
            stall = 0
        distance = float(np.linalg.norm(target - world))
        stall = stall + 1 if distance >= best - 0.001 else 0
        best = min(best, distance)
        command = np.clip(4.2 * (target - world) - 1.8 * data.qvel[:2], -5.0, 5.0)
        data.ctrl[:] = command
        mujoco.mj_step(model, data)
        world_post = start + data.qpos[:2]
        contacts = _contacts(model, data)
        row = {
            "tick": tick,
            "time_s": float(data.time),
            "qpos_model": [float(x) for x in data.qpos[:2]],
            "qpos_world": [float(x) for x in world_post],
            "qvel": [float(x) for x in data.qvel[:2]],
            "command": [float(x) for x in command],
            "target": [float(x) for x in target],
            "waypoint_index": waypoint,
            "contacts": contacts,
            "controller_detection": v1._json_finite(detection_record),
            "recovery": "NONE",
            "xml_sha256": xml_hash,
            "rgb_sha256": rgb_hash,
            "depth_sha256": depth_hash,
            "world_sha256": world_hash,
            "material_sha256": material_hash,
            "detection_sha256": detection_hash,
        }
        ticks.append(row)
        if math.dist(world_post, scene.contract["physics"]["goal_xy"]) <= cfg["goal_tolerance_m"]:
            break
    return V2Episode({
        "seed": scene.seed,
        "condition": scene.condition,
        "controller": controller,
        "scene_relpath": f"raw/scenes/seed-{scene.seed}-{scene.condition.lower()}",
        "replans": replans,
        "retries": retries,
        "semantic_wakes": semantic_wakes,
        "tick_count": len(ticks),
    }, ticks)


def _same_contacts(expected: list[dict[str, Any]], observed: list[dict[str, Any]]) -> bool:
    if len(expected) != len(observed):
        return False
    for a, b in zip(expected, observed, strict=True):
        if (a["geom1"], a["geom2"]) != (b["geom1"], b["geom2"]):
            return False
        if not math.isclose(a["normal_force"], b["normal_force"], rel_tol=1e-9, abs_tol=1e-9):
            return False
    return True


def validate_physical_replay(xml: str, ticks: list[dict[str, Any]]) -> None:
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    for index, row in enumerate(ticks):
        if row["tick"] != index:
            raise IntegrityError("physical replay tick sequence mismatch")
        data.ctrl[:] = row["command"]
        mujoco.mj_step(model, data)
        if not np.allclose(data.qpos[:2], row["qpos_model"], rtol=0, atol=1e-12):
            raise IntegrityError("physical replay qpos mismatch")
        if not np.allclose(data.qvel[:2], row["qvel"], rtol=0, atol=1e-12):
            raise IntegrityError("physical replay qvel mismatch")
        if not _same_contacts(_contacts(model, data), row["contacts"]):
            raise IntegrityError("physical replay contacts mismatch")


def _strict_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(v1._json_finite(value), sort_keys=True, indent=2, allow_nan=False) + "\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(v1._json_finite(row), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n" for row in rows))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _write_scene(path: Path, scene: V2Scene) -> None:
    path.mkdir(parents=True)
    np.save(path / "rgb.npy", scene.rgb, allow_pickle=False)
    np.save(path / "depth.npy", scene.depth, allow_pickle=False)
    v1.write_png(path / "rgb.png", scene.rgb)
    (path / "scene.xml").write_text(scene.xml)
    _strict_json(path / "scene.json", scene.contract)


def _write_episode(path: Path, episode: V2Episode) -> None:
    path.mkdir(parents=True)
    _strict_json(path / "episode.json", episode.metadata)
    _write_jsonl(path / "ticks.jsonl", episode.ticks)


def _load_episode(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return json.loads((path / "episode.json").read_text()), _read_jsonl(path / "ticks.jsonl")


def _load_scene(root: Path, relpath: str) -> tuple[dict[str, Any], str, np.ndarray, np.ndarray]:
    path = root / relpath
    return (
        json.loads((path / "scene.json").read_text()),
        (path / "scene.xml").read_text(),
        np.load(path / "rgb.npy", allow_pickle=False),
        np.load(path / "depth.npy", allow_pickle=False),
    )


def score_raw_episode(root: Path, episode_path: Path) -> dict[str, Any]:
    cfg = load_config()
    meta, ticks = _load_episode(episode_path)
    contract, xml, rgb, depth = _load_scene(root, meta["scene_relpath"])
    empty_rel = f"raw/scenes/seed-{meta['seed']}-no_obstacle"
    _, _, _, empty_depth = _load_scene(root, empty_rel)
    validate_physical_replay(xml, ticks)
    scene = V2Scene(meta["seed"], meta["condition"], rgb, depth, xml, contract)
    detection = _detector(scene, empty_depth, meta["controller"])
    model = mujoco.MjModel.from_xml_string(xml)
    obstacle_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "obstacle")
    truth_present = obstacle_id >= 0
    if truth_present and detection.present and detection.center_xy is not None:
        truth = contract["physics"]["obstacle_xy"]
        localization_error = math.dist(detection.center_xy, truth)
    elif not truth_present and not detection.present:
        localization_error = 0.0
    else:
        localization_error = math.inf
    detection_correct = detection.present == truth_present and (not truth_present or localization_error <= cfg["localization_tolerance_m"])
    obstacle_contacts = 0
    for row in ticks:
        obstacle_contacts += sum(1 for c in row["contacts"] if obstacle_id >= 0 and obstacle_id in (c["geom1"], c["geom2"]))
    final = ticks[-1]["qpos_world"]
    goal = contract["physics"]["goal_xy"]
    goal_error = math.dist(final, goal)
    complete = goal_error <= cfg["goal_tolerance_m"]
    contained = all(abs(row["qpos_world"][1]) < 0.88 for row in ticks)
    collision_free = obstacle_contacts == 0
    path = sum(math.dist(a["qpos_world"], b["qpos_world"]) for a, b in zip(ticks, ticks[1:]))
    return {
        "episode_id": episode_path.name,
        "seed": meta["seed"],
        "condition": meta["condition"],
        "controller": meta["controller"],
        "detection_correct": bool(detection_correct),
        "detection_present": bool(detection.present),
        "localization_error_m": localization_error if math.isfinite(localization_error) else None,
        "task_complete": bool(complete),
        "collision_free": bool(collision_free),
        "safe_completion": bool(complete and collision_free and contained),
        "goal_error_m": goal_error,
        "obstacle_contact_ticks": obstacle_contacts,
        "path_length_m": path,
        "ticks": len(ticks),
        "replans": sum(row["recovery"] == "MOTION_REPLAN" for row in ticks),
        "semantic_wakes": sum(row["recovery"].startswith("SEMANTIC") for row in ticks),
        "detector_latency_ms": detection.latency_ms,
    }


def _entry_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path == root / "inventory.json":
            continue
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise IntegrityError(f"symlink: {rel}")
        if path.is_dir():
            rows.append({"path": rel, "type": "directory"})
        elif path.is_file():
            rows.append({"path": rel, "type": "file", "bytes": path.stat().st_size, "sha256": v1.sha256_file(path)})
        else:
            raise IntegrityError(f"unsupported member: {rel}")
    return rows


def write_inventory(root: Path) -> None:
    _strict_json(root / "inventory.json", {"schema": "recursive-inventory-v2", "entries": _entry_rows(root)})


def verify_inventory(root: Path) -> None:
    inventory = json.loads((root / "inventory.json").read_text())
    if inventory != {"schema": "recursive-inventory-v2", "entries": _entry_rows(root)}:
        raise IntegrityError("inventory mismatch")
    allowed_root = {"raw", "closure.json", "inventory.json"}
    if (root / "derived").exists():
        allowed_root.add("derived")
    if {path.name for path in root.iterdir()} != allowed_root:
        raise IntegrityError("root allowlist mismatch")
    if {path.name for path in (root / "raw").iterdir()} != {"scenes", "episodes", "run.json"}:
        raise IntegrityError("raw allowlist mismatch")
    if (root / "derived").exists():
        expected = {"scores", "episodes.csv", "analysis.json", "safe-completion.svg", "samples.json"}
        if {path.name for path in (root / "derived").iterdir()} != expected:
            raise IntegrityError("derived allowlist mismatch")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()


def _source_hashes(commit: str) -> dict[str, str]:
    paths = [
        "experiments/12_opaque_glass_transfer/src/v2.py",
        "experiments/12_opaque_glass_transfer/src/experiment.py",
        "experiments/12_opaque_glass_transfer/config-v2.json",
    ]
    return {path: _sha_bytes(subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, check=True, capture_output=True).stdout) for path in paths}


def _worktree_source_hashes() -> dict[str, str]:
    repo = Path(_git("rev-parse", "--show-toplevel"))
    paths = [
        "experiments/12_opaque_glass_transfer/src/v2.py",
        "experiments/12_opaque_glass_transfer/src/experiment.py",
        "experiments/12_opaque_glass_transfer/config-v2.json",
    ]
    return {path: v1.sha256_file(repo / path) for path in paths}


def _closure(mode: str, matrix: list[dict[str, Any]]) -> dict[str, Any]:
    commit = _git("rev-parse", "HEAD")
    source_hashes = _source_hashes(commit) if mode == "HELDOUT" else _worktree_source_hashes()
    return {
        "status": "COMPLETE",
        "mode": mode,
        "source_commit": commit,
        "source_hashes": source_hashes,
        "config_sha256": v1.sha256_file(CONFIG),
        "seed_namespace": load_config()["heldout_seeds"] if mode == "HELDOUT" else load_config()["calibration_seeds"],
        "matrix": matrix,
        "environment": {"python": sys.version, "mujoco": mujoco.__version__, "numpy": np.__version__, "platform": platform.platform()},
    }


def write_calibration_raw_fixture(tmp_path: Path, seed: int, controller: str) -> Path:
    root = tmp_path / "fixture"
    (root / "raw" / "scenes").mkdir(parents=True)
    (root / "raw" / "episodes").mkdir()
    empty = render_scene_v2(seed, "NO_OBSTACLE")
    opaque = render_scene_v2(seed, "OPAQUE")
    for scene in (empty, opaque):
        _write_scene(root / "raw" / "scenes" / f"seed-{seed}-{scene.condition.lower()}", scene)
    episode = run_episode_v2(opaque, empty.depth, controller)
    episode.metadata["scene_relpath"] = f"raw/scenes/seed-{seed}-opaque"
    _write_episode(root / "raw" / "episodes" / "episode", episode)
    _strict_json(root / "raw" / "run.json", {"mode": "CALIBRATION", "episodes": [episode.metadata]})
    _strict_json(root / "closure.json", _closure("CALIBRATION", [{"seed": seed, "condition": "OPAQUE", "controller": controller}]))
    return root


def _validate_closure(root: Path) -> None:
    closure = json.loads((root / "closure.json").read_text())
    if closure["config_sha256"] != v1.sha256_file(CONFIG):
        raise IntegrityError("config closure mismatch")
    expected_sources = _source_hashes(closure["source_commit"]) if closure["mode"] == "HELDOUT" else _worktree_source_hashes()
    if closure["source_hashes"] != expected_sources:
        raise IntegrityError("source closure mismatch")
    if closure["mode"] == "HELDOUT":
        expected = heldout_matrix(load_config())
        if closure["matrix"] != expected or closure["seed_namespace"] != load_config()["heldout_seeds"]:
            raise IntegrityError("seed/matrix closure mismatch")


def validate_raw(root: Path) -> None:
    if (root / "inventory.json").exists():
        verify_inventory(root)
    _validate_closure(root)
    run = json.loads((root / "raw" / "run.json").read_text())
    episode_dirs = sorted(path for path in (root / "raw" / "episodes").iterdir() if path.is_dir())
    if run["mode"] == "HELDOUT" and len(episode_dirs) != 108:
        raise IntegrityError("raw matrix count mismatch")
    actual_matrix = []
    for episode_path in episode_dirs:
        meta, ticks = _load_episode(episode_path)
        actual_matrix.append({key: meta[key] for key in ("seed", "condition", "controller")})
        contract, xml, rgb, depth = _load_scene(root, meta["scene_relpath"])
        validate_physical_replay(xml, ticks)
        expected = {
            "xml_sha256": _sha_bytes(xml.encode()),
            "rgb_sha256": _array_sha(rgb),
            "depth_sha256": _array_sha(depth),
            "world_sha256": _sha_bytes(_canonical(contract["physics"])),
            "material_sha256": _sha_bytes(_canonical({"namespace": contract["material_namespace"], "rgba": contract["material_rgba"]})),
        }
        for row in ticks:
            if any(row[key] != value for key, value in expected.items()):
                raise IntegrityError("raw semantic hash mismatch")
    if run["mode"] == "HELDOUT":
        def key(row: dict[str, Any]) -> tuple[Any, Any, Any]:
            return row["seed"], row["condition"], row["controller"]
        if sorted(actual_matrix, key=key) != sorted(heldout_matrix(load_config()), key=key):
            raise IntegrityError("raw semantic matrix mismatch")
        scenes = [json.loads((path / "scene.json").read_text()) for path in (root / "raw" / "scenes").iterdir()]
        if len(scenes) != 36:
            raise IntegrityError("raw scene matrix mismatch")
        for seed in load_config()["heldout_seeds"]:
            matched = [scene for scene in scenes if scene["seed"] == seed]
            if len(matched) != 3 or any(scene["physics"] != matched[0]["physics"] or scene["camera"] != matched[0]["camera"] for scene in matched[1:]):
                raise IntegrityError("appearance manipulation changed physics/camera")


def _bootstrap(values: np.ndarray, rng: np.random.Generator, draws: int) -> dict[str, Any]:
    means = values[rng.integers(0, len(values), size=(draws, len(values)))].mean(axis=1)
    return {"estimate": float(values.mean()), "ci_low": float(np.quantile(means, 0.025)), "ci_high": float(np.quantile(means, 0.975)), "effective_n": len(values), "draws": draws}


def _analysis(scores: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = load_config()
    by = {(r["seed"], r["condition"], r["controller"]): r for r in scores}
    summary = []
    for condition in cfg["heldout_conditions"]:
        for controller in cfg["controllers"]:
            cell = [r for r in scores if r["condition"] == condition and r["controller"] == controller]
            summary.append({
                "condition": condition, "controller": controller, "n": len(cell),
                "detection_rate": sum(r["detection_correct"] for r in cell) / len(cell),
                "safe_completion_rate": sum(r["safe_completion"] for r in cell) / len(cell),
                "collision_free_rate": sum(r["collision_free"] for r in cell) / len(cell),
                "mean_path_length_m": sum(r["path_length_m"] for r in cell) / len(cell),
                "mean_ticks": sum(r["ticks"] for r in cell) / len(cell),
            })
    rng = np.random.default_rng(cfg["bootstrap_seed"])
    contrasts = {}
    for controller in cfg["controllers"]:
        for metric in ("detection_correct", "safe_completion"):
            vals = np.array([float(by[(s, "EVAL_X2", controller)][metric]) - float(by[(s, "OPAQUE", controller)][metric]) for s in cfg["heldout_seeds"]])
            contrasts[f"{controller}:eval_minus_opaque:{metric}"] = _bootstrap(vals, rng, cfg["bootstrap_draws"])
    for controller in ("RGBD_MOTION", "HIERARCHICAL"):
        vals = np.array([float(by[(s, "EVAL_X2", controller)]["safe_completion"]) - float(by[(s, "EVAL_X2", "RGB_ONLY")]["safe_completion"]) for s in cfg["heldout_seeds"]])
        contrasts[f"{controller}_minus_RGB_ONLY:eval:safe_completion"] = _bootstrap(vals, rng, cfg["bootstrap_draws"])
    return {"summary": summary, "paired_contrasts": contrasts}


def _svg(path: Path, analysis: dict[str, Any]) -> None:
    rows = [r for r in analysis["summary"] if r["condition"] == "EVAL_X2"]
    bars = []
    for i, row in enumerate(rows):
        x = 65 + i * 155
        h = row["safe_completion_rate"] * 210
        bars.append(f'<rect x="{x}" y="{260-h:.2f}" width="84" height="{h:.2f}" fill="{["#c94b45","#3b82c4","#4b9b62"][i]}"/><text x="{x+42}" y="282" text-anchor="middle" font-size="11">{row["controller"]}</text><text x="{x+42}" y="{250-h:.2f}" text-anchor="middle">{row["safe_completion_rate"]:.2f}</text>')
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="550" height="310"><rect width="100%" height="100%" fill="white"/><text x="275" y="24" text-anchor="middle">V2 held-out glass-like appearance: safe completion</text><line x1="42" y1="260" x2="520" y2="260" stroke="black"/>' + "".join(bars) + "</svg>\n")


def derive(root: Path) -> list[dict[str, Any]]:
    validate_raw(root)
    derived = root / "derived"
    if derived.exists():
        shutil.rmtree(derived)
    (derived / "scores").mkdir(parents=True)
    scores = []
    for episode_path in sorted(path for path in (root / "raw" / "episodes").iterdir() if path.is_dir()):
        score = score_raw_episode(root, episode_path)
        scores.append(score)
        _strict_json(derived / "scores" / f"{episode_path.name}.json", score)
    with (derived / "episodes.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(scores[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(scores)
    analysis = _analysis(scores)
    _strict_json(derived / "analysis.json", analysis)
    _svg(derived / "safe-completion.svg", analysis)
    working = next(r for r in scores if r["condition"] == "EVAL_X2" and r["controller"] == "HIERARCHICAL" and r["safe_completion"])
    nonworking = next(r for r in scores if r["condition"] == "EVAL_X2" and r["controller"] == "RGB_ONLY" and not r["safe_completion"])
    _strict_json(derived / "samples.json", {"rule": "lowest seed in preregistered working/nonworking classes", "working": working, "nonworking": nonworking})
    return scores


def run(output: Path) -> dict[str, Any]:
    if output.exists():
        raise IntegrityError("output already exists")
    cfg = load_config()
    matrix = heldout_matrix(cfg)
    (output / "raw" / "scenes").mkdir(parents=True)
    (output / "raw" / "episodes").mkdir()
    _strict_json(output / "closure.json", {**_closure("HELDOUT", matrix), "status": "RUNNING"})
    metas = []
    try:
        for seed in cfg["heldout_seeds"]:
            scenes = {condition: render_scene_v2(seed, condition) for condition in cfg["heldout_conditions"]}
            for condition, scene in scenes.items():
                _write_scene(output / "raw" / "scenes" / f"seed-{seed}-{condition.lower()}", scene)
            empty_depth = scenes["NO_OBSTACLE"].depth
            for condition in cfg["heldout_conditions"]:
                for controller in cfg["controllers"]:
                    episode = run_episode_v2(scenes[condition], empty_depth, controller)
                    episode_id = f"seed-{seed}-{condition.lower()}-{controller.lower()}"
                    _write_episode(output / "raw" / "episodes" / episode_id, episode)
                    metas.append({**episode.metadata, "episode_id": episode_id})
        _strict_json(output / "raw" / "run.json", {"mode": "HELDOUT", "episodes": metas})
        _strict_json(output / "closure.json", _closure("HELDOUT", matrix))
        scores = derive(output)
        write_inventory(output)
        verify_inventory(output)
        return {"scores": scores, "analysis": json.loads((output / "derived" / "analysis.json").read_text())}
    except Exception:
        closure = json.loads((output / "closure.json").read_text())
        closure["status"] = "INVALID_INTERRUPTED"
        _strict_json(output / "closure.json", closure)
        raise


def reconstruct(source: Path, target: Path) -> None:
    verify_inventory(source)
    validate_raw(source)
    if target.exists():
        raise IntegrityError("reconstruction target exists")
    target.mkdir(parents=True)
    shutil.copytree(source / "raw", target / "raw")
    shutil.copy2(source / "closure.json", target / "closure.json")
    derive(target)
    write_inventory(target)
    verify_inventory(target)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.output)["analysis"], indent=2, sort_keys=True))
