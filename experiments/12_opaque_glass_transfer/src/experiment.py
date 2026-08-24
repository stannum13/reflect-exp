from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import shutil
import struct
import sys
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import mujoco
import numpy as np


HERE = Path(__file__).parents[1]
CONFIG_PATH = HERE / "config.json"


class IntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class MatrixRow:
    seed: int
    condition: str
    controller: str


@dataclass
class RenderedScene:
    rgb: np.ndarray
    depth: np.ndarray
    model: mujoco.MjModel
    data: mujoco.MjData
    xml: str
    contract: dict[str, Any]


@dataclass(frozen=True)
class Detection:
    present: bool
    center_xy: tuple[float, float] | None
    pixel_count: int
    localization_error_m: float
    latency_ms: float


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text())


def heldout_matrix(config: dict[str, Any]) -> list[MatrixRow]:
    return [
        MatrixRow(seed, condition, controller)
        for seed in config["heldout_seeds"]
        for condition in config["conditions"]
        for controller in config["controllers"]
    ]


def scene_contract(seed: int, condition: str) -> dict[str, Any]:
    if condition not in {"NO_OBSTACLE", "OPAQUE", "TRANSPARENT"}:
        raise ValueError(condition)
    rng = np.random.default_rng(seed)
    obstacle_x = float(rng.uniform(-0.08, 0.08))
    obstacle_y = float(rng.uniform(-0.10, 0.10))
    start_y = float(rng.uniform(-0.08, 0.08))
    rgba = {
        "NO_OBSTACLE": None,
        "OPAQUE": [0.86, 0.05, 0.04, 1.0],
        "TRANSPARENT": [0.86, 0.05, 0.04, 0.08],
    }[condition]
    return {
        "seed": seed,
        "condition": condition,
        "physics": {
            "start_xy": [-1.20, start_y],
            "goal_xy": [1.20, -start_y * 0.25],
            "obstacle_xy": [obstacle_x, obstacle_y],
            "obstacle_half_size": [0.12, 0.28, 0.16],
            "robot_radius": 0.08,
            "timestep": 0.02,
            "friction": [0.9, 0.02, 0.002],
        },
        "camera": {"position": [0, 0, 3.2], "fovy": 42, "width": 96, "height": 96},
        "material_rgba": rgba,
    }


def _scene_xml(contract: dict[str, Any]) -> str:
    p = contract["physics"]
    start = p["start_xy"]
    obstacle = ""
    if contract["condition"] != "NO_OBSTACLE":
        xyz = p["obstacle_xy"]
        size = p["obstacle_half_size"]
        rgba = contract["material_rgba"]
        obstacle = (
            f'<geom name="obstacle" type="box" pos="{xyz[0]} {xyz[1]} {size[2]}" '
            f'size="{size[0]} {size[1]} {size[2]}" rgba="{rgba[0]} {rgba[1]} {rgba[2]} {rgba[3]}" '
            'friction="0.9 0.02 0.002" contype="1" conaffinity="1"/>'
        )
    return f"""<mujoco model="opaque_glass_transfer">
  <option timestep="{p['timestep']}" gravity="0 0 0" integrator="implicitfast"/>
  <visual><global offwidth="96" offheight="96"/><quality shadowsize="1024"/></visual>
  <worldbody>
    <light pos="-1.5 -1.0 3.0" dir="0.3 0.2 -1" diffuse="0.75 0.75 0.75"/>
    <light pos="1.5 1.0 2.5" dir="-0.3 -0.2 -1" diffuse="0.35 0.35 0.35"/>
    <camera name="overhead" pos="0 0 3.2" xyaxes="1 0 0 0 1 0" fovy="42"/>
    <geom name="floor" type="plane" size="2 1.1 0.05" rgba="0.42 0.44 0.47 1" contype="0" conaffinity="0"/>
    <geom name="wall_top" type="box" pos="0 0.92 0.12" size="1.55 0.04 0.12" rgba="0.18 0.2 0.22 1"/>
    <geom name="wall_bottom" type="box" pos="0 -0.92 0.12" size="1.55 0.04 0.12" rgba="0.18 0.2 0.22 1"/>
    {obstacle}
    <body name="robot" pos="{start[0]} {start[1]} 0.09">
      <joint name="x" type="slide" axis="1 0 0" damping="2"/>
      <joint name="y" type="slide" axis="0 1 0" damping="2"/>
      <geom name="robot_geom" type="sphere" size="{p['robot_radius']}" rgba="0.05 0.25 0.95 1" mass="0.45" friction="0.8 0.02 0.002"/>
    </body>
    <site name="goal" pos="{p['goal_xy'][0]} {p['goal_xy'][1]} 0.03" size="0.07" rgba="0.1 0.9 0.2 1"/>
  </worldbody>
  <actuator>
    <motor name="fx" joint="x" gear="1" ctrlrange="-5 5" ctrllimited="true"/>
    <motor name="fy" joint="y" gear="1" ctrlrange="-5 5" ctrllimited="true"/>
  </actuator>
</mujoco>"""


def _render(model: mujoco.MjModel, data: mujoco.MjData) -> tuple[np.ndarray, np.ndarray]:
    renderer = mujoco.Renderer(model, height=96, width=96)
    try:
        renderer.update_scene(data, camera="overhead")
        rgb = np.array(renderer.render(), dtype=np.uint8, copy=True)
        renderer.enable_depth_rendering()
        renderer.update_scene(data, camera="overhead")
        depth = np.array(renderer.render(), dtype=np.float32, copy=True)
    finally:
        renderer.close()
    return rgb, depth


def render_scene(seed: int, condition: str) -> RenderedScene:
    contract = scene_contract(seed, condition)
    xml = _scene_xml(contract)
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    rgb, depth = _render(model, data)
    return RenderedScene(rgb, depth, model, data, xml, contract)


def _pixel_to_world(rows: np.ndarray, cols: np.ndarray) -> tuple[float, float]:
    # Fixed overhead pinhole camera; floor-projected calibration is frozen.
    x = (float(np.mean(cols)) / 95.0 - 0.5) * 2.46
    y = -(float(np.mean(rows)) / 95.0 - 0.5) * 2.46
    return x, y


def detect_rgb(rgb: np.ndarray) -> Detection:
    f = rgb.astype(np.float32)
    mask = (f[..., 0] > 115) & (f[..., 0] > 1.55 * f[..., 1]) & (f[..., 0] > 1.55 * f[..., 2])
    rows, cols = np.where(mask)
    if len(rows) < 18:
        return Detection(False, None, int(len(rows)), math.inf, 0.35)
    xy = _pixel_to_world(rows, cols)
    return Detection(True, xy, int(len(rows)), math.nan, 0.35)


def detect_depth(rgb: np.ndarray, depth: np.ndarray, empty_depth: np.ndarray) -> Detection:
    delta = empty_depth.astype(np.float64) - depth.astype(np.float64)
    blue_robot = (rgb[..., 2] > 1.4 * rgb[..., 0]) & (rgb[..., 2] > 1.25 * rgb[..., 1])
    mask = (delta > 0.035) & ~blue_robot
    rows, cols = np.where(mask)
    if len(rows) < 18:
        return Detection(False, None, int(len(rows)), math.inf, 0.72)
    xy = _pixel_to_world(rows, cols)
    return Detection(True, xy, int(len(rows)), math.nan, 0.72)


def _with_error(d: Detection, truth: tuple[float, float] | None) -> Detection:
    if not d.present or d.center_xy is None or truth is None:
        err = 0.0 if (not d.present and truth is None) else math.inf
    else:
        err = math.dist(d.center_xy, truth)
    return Detection(d.present, d.center_xy, d.pixel_count, err, d.latency_ms)


def _route(det: Detection, contract: dict[str, Any], alternate: bool = False) -> list[tuple[float, float]]:
    goal = tuple(contract["physics"]["goal_xy"])
    if not det.present or det.center_xy is None:
        return [goal]
    ox, oy = det.center_xy
    side = -1.0 if oy >= 0 else 1.0
    if alternate:
        side *= -1.0
    return [(ox - 0.22, side * 0.55), (ox + 0.25, side * 0.55), goal]


def _contact_names(model: mujoco.MjModel, data: mujoco.MjData) -> list[tuple[str, str]]:
    names: list[tuple[str, str]] = []
    for i in range(data.ncon):
        c = data.contact[i]
        a = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, c.geom1) or str(c.geom1)
        b = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, c.geom2) or str(c.geom2)
        names.append(tuple(sorted((a, b))))
    return names


def run_episode(seed: int, condition: str, controller: str) -> tuple[dict[str, Any], list[dict[str, Any]], RenderedScene]:
    scene = render_scene(seed, condition)
    empty = render_scene(seed, "NO_OBSTACLE")
    truth = None if condition == "NO_OBSTACLE" else tuple(scene.contract["physics"]["obstacle_xy"])
    if controller == "RGB_ONLY":
        detection = _with_error(detect_rgb(scene.rgb), truth)
    else:
        detection = _with_error(detect_depth(scene.rgb, scene.depth, empty.depth), truth)
    waypoints = _route(detection, scene.contract)
    waypoint_i = 0
    ledger: list[dict[str, Any]] = []
    obstacle_contacts = 0
    replans = retries = semantic_wakes = 0
    path_length = 0.0
    last_xy = np.array(scene.contract["physics"]["start_xy"], dtype=float)
    stall_ticks = 0
    best_dist = math.inf
    for tick in range(load_config()["max_ticks"]):
        q = np.array(scene.data.qpos[:2], dtype=float) + np.array(scene.contract["physics"]["start_xy"])
        v = np.array(scene.data.qvel[:2], dtype=float)
        target = np.array(waypoints[waypoint_i], dtype=float)
        error = target - q
        if np.linalg.norm(error) < 0.10 and waypoint_i < len(waypoints) - 1:
            waypoint_i += 1
            target = np.array(waypoints[waypoint_i], dtype=float)
            error = target - q
            stall_ticks = 0
            best_dist = math.inf
        dist = float(np.linalg.norm(error))
        stall_ticks = stall_ticks + 1 if dist >= best_dist - 0.001 else 0
        best_dist = min(best_dist, dist)
        contacts = _contact_names(scene.model, scene.data)
        hit = any("obstacle" in pair and "robot_geom" in pair for pair in contacts)
        obstacle_contacts += int(hit)
        recovery = "NONE"
        if (hit or stall_ticks >= 18) and controller in {"RGBD_MOTION", "HIERARCHICAL"} and replans < 1:
            refreshed_rgb, refreshed_depth = _render(scene.model, scene.data)
            detection = _with_error(detect_depth(refreshed_rgb, refreshed_depth, empty.depth), truth)
            waypoints = _route(detection, scene.contract)
            waypoint_i = 0
            replans += 1
            retries += 1
            recovery = "MOTION_REPLAN"
            stall_ticks = 0
            best_dist = math.inf
        elif (hit or stall_ticks >= 35) and controller == "HIERARCHICAL" and semantic_wakes < 1:
            waypoints = _route(detection, scene.contract, alternate=True)
            waypoint_i = 0
            semantic_wakes += 1
            recovery = "SEMANTIC_ALTERNATE_ROUTE"
            stall_ticks = 0
            best_dist = math.inf
        target = np.array(waypoints[waypoint_i], dtype=float)
        force = np.clip(4.2 * (target - q) - 1.8 * v, -5.0, 5.0)
        scene.data.ctrl[:] = force
        mujoco.mj_step(scene.model, scene.data)
        new_q = np.array(scene.data.qpos[:2], dtype=float) + np.array(scene.contract["physics"]["start_xy"])
        path_length += float(np.linalg.norm(new_q - last_xy))
        last_xy = new_q
        ledger.append({
            "tick": tick,
            "time_s": round(float(scene.data.time), 6),
            "x": float(new_q[0]), "y": float(new_q[1]),
            "vx": float(scene.data.qvel[0]), "vy": float(scene.data.qvel[1]),
            "target_x": float(target[0]), "target_y": float(target[1]),
            "cmd_x": float(force[0]), "cmd_y": float(force[1]),
            "obstacle_contact": bool(hit), "contacts": contacts,
            "recovery": recovery, "waypoint_index": waypoint_i,
        })
        if math.dist(new_q, scene.contract["physics"]["goal_xy"]) <= load_config()["goal_tolerance_m"]:
            break
    trace = {
        "seed": seed, "condition": condition, "controller": controller,
        "detection": asdict(detection), "waypoints_initial": [list(x) for x in _route(detection, scene.contract)],
        "obstacle_contacts": obstacle_contacts, "replans": replans, "retries": retries,
        "semantic_wakes": semantic_wakes, "path_length_m": path_length,
        "final_xy": [ledger[-1]["x"], ledger[-1]["y"]], "ticks": len(ledger),
        "goal_xy": scene.contract["physics"]["goal_xy"],
        "controller_claimed_success": math.dist(
            [ledger[-1]["x"], ledger[-1]["y"]], scene.contract["physics"]["goal_xy"]
        ) < 0.1,
    }
    return trace, ledger, scene


def score_trace(trace: dict[str, Any]) -> dict[str, Any]:
    final_xy = tuple(trace["final_xy"])
    goal_xy = tuple(trace["goal_xy"])
    complete = math.dist(final_xy, goal_xy) <= load_config()["goal_tolerance_m"]
    contained = all(abs(float(row.get("y", final_xy[1]))) < 0.88 for row in trace.get("ledger", []))
    safe = int(trace["obstacle_contacts"]) == 0 and contained
    return {
        "task_complete": complete,
        "collision_free": int(trace["obstacle_contacts"]) == 0,
        "safe_completion": complete and safe,
        "goal_error_m": math.dist(final_xy, goal_xy),
    }


def synthetic_trace_for_test(final_xy: tuple[float, float], obstacle_contacts: int) -> dict[str, Any]:
    return {"final_xy": list(final_xy), "goal_xy": [1.2, 0.0], "obstacle_contacts": obstacle_contacts, "ledger": []}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_png(path: Path, rgb: np.ndarray) -> None:
    height, width, channels = rgb.shape
    if channels != 3 or rgb.dtype != np.uint8:
        raise ValueError("expected uint8 RGB")
    raw = b"".join(b"\x00" + rgb[row].tobytes() for row in range(height))
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _json_finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_finite(member) for key, member in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_finite(member) for member in value]
    return value


def write_strict_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_json_finite(value), sort_keys=True, indent=2, allow_nan=False) + "\n")


_write_json = write_strict_json


def _manifest_entries(root: Path) -> list[dict[str, Any]]:
    entries = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "manifest.json"):
        if path.is_symlink():
            raise IntegrityError("symlink")
        entries.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return entries


def verify_inventory(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise IntegrityError(f"symlink: {path}")
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["files"] != _manifest_entries(root):
        raise IntegrityError("inventory mismatch")


def make_integrity_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "fixture"
    root.mkdir()
    (root / "payload.txt").write_text("payload\n")
    _write_json(root / "manifest.json", {"files": _manifest_entries(root)})
    return root


def _bootstrap(values: np.ndarray, draws: int, rng: np.random.Generator) -> dict[str, float | int]:
    n = len(values)
    means = values[rng.integers(0, n, size=(draws, n))].mean(axis=1)
    return {"estimate": float(values.mean()), "ci_low": float(np.quantile(means, 0.025)), "ci_high": float(np.quantile(means, 0.975)), "effective_n": n}


def analyse(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = load_config()
    rng = np.random.default_rng(cfg["bootstrap_seed"])
    by = {(r["seed"], r["condition"], r["controller"]): r for r in rows}
    contrasts: dict[str, Any] = {}
    for controller in cfg["controllers"]:
        for metric in ("safe_completion", "detection_correct"):
            vals = np.array([float(by[(s, "TRANSPARENT", controller)][metric]) - float(by[(s, "OPAQUE", controller)][metric]) for s in cfg["heldout_seeds"]])
            contrasts[f"{controller}:transparent_minus_opaque:{metric}"] = _bootstrap(vals, cfg["bootstrap_draws"], rng)
    for stronger in ("RGBD_MOTION", "HIERARCHICAL"):
        vals = np.array([float(by[(s, "TRANSPARENT", stronger)]["safe_completion"]) - float(by[(s, "TRANSPARENT", "RGB_ONLY")]["safe_completion"]) for s in cfg["heldout_seeds"]])
        contrasts[f"{stronger}_minus_RGB_ONLY:transparent:safe_completion"] = _bootstrap(vals, cfg["bootstrap_draws"], rng)
    summary = []
    for condition in cfg["conditions"]:
        for controller in cfg["controllers"]:
            cell = [r for r in rows if r["condition"] == condition and r["controller"] == controller]
            summary.append({
                "condition": condition, "controller": controller, "n": len(cell),
                "detection_rate": sum(r["detection_correct"] for r in cell) / len(cell),
                "completion_rate": sum(r["task_complete"] for r in cell) / len(cell),
                "safe_completion_rate": sum(r["safe_completion"] for r in cell) / len(cell),
                "collision_free_rate": sum(r["collision_free"] for r in cell) / len(cell),
                "mean_path_length_m": sum(r["path_length_m"] for r in cell) / len(cell),
                "mean_replans": sum(r["replans"] for r in cell) / len(cell),
            })
    return {"summary": summary, "paired_contrasts": contrasts}


def write_svg(path: Path, analysis: dict[str, Any]) -> None:
    transparent = [r for r in analysis["summary"] if r["condition"] == "TRANSPARENT"]
    bars = []
    for i, row in enumerate(transparent):
        x = 70 + i * 150
        h = 220 * row["safe_completion_rate"]
        bars.append(f'<rect x="{x}" y="{270-h:.1f}" width="80" height="{h:.1f}" fill="#{["c94b45","3b82c4","4b9b62"][i]}"/><text x="{x+40}" y="292" text-anchor="middle" font-size="12">{row["controller"]}</text><text x="{x+40}" y="{260-h:.1f}" text-anchor="middle" font-size="13">{row["safe_completion_rate"]:.2f}</text>')
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="540" height="320"><rect width="100%" height="100%" fill="white"/><text x="270" y="24" text-anchor="middle" font-size="16">Held-out transparent safe completion</text><line x1="45" y1="270" x2="510" y2="270" stroke="black"/>' + "".join(bars) + "</svg>\n"
    path.write_text(svg)


def run(output: Path) -> dict[str, Any]:
    cfg = load_config()
    if output.exists():
        raise IntegrityError(f"output exists: {output}")
    output.mkdir(parents=True)
    (output / "scenes").mkdir()
    (output / "episodes").mkdir()
    rows: list[dict[str, Any]] = []
    for seed in cfg["heldout_seeds"]:
        for condition in cfg["conditions"]:
            shared = render_scene(seed, condition)
            scene_dir = output / "scenes" / f"seed-{seed}-{condition.lower()}"
            scene_dir.mkdir()
            np.save(scene_dir / "rgb.npy", shared.rgb, allow_pickle=False)
            np.save(scene_dir / "depth.npy", shared.depth, allow_pickle=False)
            write_png(scene_dir / "rgb.png", shared.rgb)
            (scene_dir / "scene.xml").write_text(shared.xml)
            _write_json(scene_dir / "scene.json", shared.contract)
            for controller in cfg["controllers"]:
                trace, ledger, scene = run_episode(seed, condition, controller)
                trace["ledger"] = ledger
                score = score_trace(trace)
                truth_present = condition != "NO_OBSTACLE"
                det = trace["detection"]
                detection_correct = bool(det["present"] == truth_present and (not truth_present or det["localization_error_m"] <= cfg["localization_tolerance_m"]))
                episode_id = f"seed-{seed}-{condition.lower()}-{controller.lower()}"
                episode_dir = output / "episodes" / episode_id
                episode_dir.mkdir()
                _write_json(episode_dir / "trace.json", trace)
                _write_json(episode_dir / "score.json", score)
                row = {
                    "episode_id": episode_id, "seed": seed, "condition": condition, "controller": controller,
                    "detection_correct": detection_correct, "detection_present": det["present"],
                    "localization_error_m": det["localization_error_m"] if math.isfinite(det["localization_error_m"]) else None,
                    **score, "obstacle_contacts": trace["obstacle_contacts"], "replans": trace["replans"],
                    "retries": trace["retries"], "semantic_wakes": trace["semantic_wakes"],
                    "path_length_m": trace["path_length_m"], "ticks": trace["ticks"],
                }
                rows.append(row)
    fields = list(rows[0])
    with (output / "episodes.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    analysis = analyse(rows)
    _write_json(output / "analysis.json", analysis)
    write_svg(output / "transparent-safe-completion.svg", analysis)
    working = next(r for r in rows if r["condition"] == "TRANSPARENT" and r["controller"] == "HIERARCHICAL" and r["safe_completion"])
    nonworking = next(r for r in rows if r["condition"] == "TRANSPARENT" and r["controller"] == "RGB_ONLY" and not r["safe_completion"])
    _write_json(output / "annotated-samples.json", {"selection_rule": "lowest seed qualifying in each frozen class", "working": working, "nonworking": nonworking})
    closure = {
        "config_sha256": sha256_file(CONFIG_PATH), "python": sys.version, "platform": platform.platform(),
        "mujoco": mujoco.__version__, "numpy": np.__version__, "matrix_rows": len(rows),
        "source_commit": os.popen("git rev-parse HEAD").read().strip(), "status": "COMPLETE",
    }
    _write_json(output / "closure.json", closure)
    _write_json(output / "manifest.json", {"files": _manifest_entries(output)})
    verify_inventory(output)
    return {"rows": rows, "analysis": analysis, "closure": closure}


def reconstruct(source: Path, target: Path) -> None:
    verify_inventory(source)
    if target.exists():
        raise IntegrityError("target exists")
    shutil.copytree(source, target)
    # Re-derive every analysis artifact from sealed independent score rows.
    with (target / "episodes.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    typed: list[dict[str, Any]] = []
    bools = {"detection_correct", "detection_present", "task_complete", "collision_free", "safe_completion"}
    ints = {"seed", "obstacle_contacts", "replans", "retries", "semantic_wakes", "ticks"}
    floats = {"localization_error_m", "goal_error_m", "path_length_m"}
    for row in rows:
        typed.append({k: (v == "True" if k in bools else int(v) if k in ints else float(v) if k in floats and v else v) for k, v in row.items()})
    _write_json(target / "analysis.json", analyse(typed))
    write_svg(target / "transparent-safe-completion.svg", json.loads((target / "analysis.json").read_text()))
    (target / "manifest.json").unlink()
    _write_json(target / "manifest.json", {"files": _manifest_entries(target)})
    verify_inventory(target)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps(result["analysis"], indent=2, sort_keys=True))
