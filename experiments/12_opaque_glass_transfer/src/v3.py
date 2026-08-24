from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import mujoco
import numpy as np

from . import experiment as v1
from . import v2


ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "config-v3.json"
CLOSURE_KEYS = {
    "schema", "status", "mode", "source_commit", "source_parent_commit",
    "evidence_commit", "evidence_parent_commit", "chronology_receipt_commit",
    "config_sha256", "source_hashes", "matrix", "seed_namespace",
    "material_namespace", "environment", "attestation_hashes",
}
LEGACY_CLOSURE_KEYS = {
    "schema", "status", "mode", "source_commit", "source_parent_commit",
    "evidence_commit_policy", "config_sha256", "source_hashes", "matrix",
    "seed_namespace", "environment",
}

SOURCE_COMMIT = "f0bd0ca6d4affe0e9ecc6eff392f81cb53247512"
SOURCE_PARENT_COMMIT = "34f063e26d992594ebf77e2066802be96a1c017d"
EVIDENCE_COMMIT = "1ef923f81c913960342298ced6ecc2bd63d7d529"
CHRONOLOGY_RECEIPT_COMMIT = "44546fb62b341dcf783c822e1c77ce110901267a"
CHRONOLOGY_PATH = "experiments/12_opaque_glass_transfer/V3_EVIDENCE_RECEIPT.json"
INVALIDATION_PATH = "experiments/12_opaque_glass_transfer/V1_V2_INVALID_REJECTED.json"
RUN_RECEIPT_KEYS = {
    "condition", "condition_from_xml", "controller", "controller_contract",
    "episode_id", "replans", "retries", "scene_relpath", "seed",
    "semantic_wakes", "tick_count",
}


class IntegrityError(RuntimeError):
    pass


V3Scene = v2.V2Scene


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG.read_text())


def heldout_matrix(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"seed": seed, "condition": condition, "controller": controller}
        for seed in cfg["heldout_seeds"]
        for condition in cfg["heldout_conditions"]
        for controller in cfg["controllers"]
    ]


def assert_pre_freeze_guard(test_source: str, cfg: dict[str, Any]) -> None:
    token = "EVAL" + "_X3"
    if token in test_source:
        raise IntegrityError("evaluation scene named in pre-freeze tests")
    prior = list(range(5101, 5113)) + list(range(6201, 6213))
    for seed in cfg["heldout_seeds"] + prior:
        if str(seed) in test_source:
            raise IntegrityError("held-out seed leaked into pre-freeze tests")
    if cfg["calibration_conditions"] != ["NO_OBSTACLE", "OPAQUE"]:
        raise IntegrityError("calibration closure invalid")


@contextmanager
def _v3_config() -> Iterator[None]:
    previous = v2.CONFIG
    v2.CONFIG = CONFIG
    try:
        yield
    finally:
        v2.CONFIG = previous


def render_scene(seed: int, condition: str) -> V3Scene:
    with _v3_config():
        return v2.render_scene_v2(seed, condition)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def controller_contract(controller: str) -> dict[str, Any]:
    cfg = load_config()
    if controller not in cfg["controllers"]:
        raise IntegrityError("unknown controller")
    paths = {
        "RGB_ONLY": ["rgb_detector", "single_geometric_route", "pd_control"],
        "RGBD_MOTION": ["rgbd_detector", "motion_route", "pd_control"],
        "HIERARCHICAL": ["rgbd_detector", "semantic_route", "motion_route", "pd_control"],
    }
    payload = {
        "controller_id": controller,
        "path": paths[controller],
        "config_sha256": v1.sha256_file(CONFIG),
        "implementation": "experiments/12_opaque_glass_transfer/src/v3.py",
    }
    return {**payload, "contract_sha256": _sha(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())}


def _expected_contract(seed: int, condition: str) -> dict[str, Any]:
    with _v3_config():
        return v2._scene_contract(seed, condition)


def _expected_xml(contract: dict[str, Any]) -> str:
    with _v3_config():
        return v2._xml(contract)


def _png_bytes(rgb: np.ndarray) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "image.png"
        v1.write_png(path, rgb)
        return path.read_bytes()


def _infer_condition(xml: str) -> str:
    cfg = load_config()
    model = mujoco.MjModel.from_xml_string(xml)
    obstacle = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "obstacle")
    if obstacle < 0:
        return "NO_OBSTACLE"
    rgba = [float(x) for x in model.geom_rgba[obstacle]]
    if np.allclose(rgba, cfg["opaque_rgba"], rtol=0, atol=1e-7):
        return "OPAQUE"
    if np.allclose(rgba, cfg["eval_rgba"], rtol=0, atol=1e-7):
        return "EVAL_X3"
    raise IntegrityError("scene identity material unknown")


def authenticate_scene(scene: V3Scene, directory: Path | None = None) -> None:
    expected = _expected_contract(scene.seed, scene.condition)
    if scene.contract != expected or scene.xml != _expected_xml(expected):
        raise IntegrityError("scene identity contract/XML mismatch")
    if _infer_condition(scene.xml) != scene.condition:
        raise IntegrityError("scene identity condition mismatch")
    model = mujoco.MjModel.from_xml_string(scene.xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    rgb, depth = v1._render(model, data)
    if not np.array_equal(rgb, scene.rgb) or not np.array_equal(depth, scene.depth):
        raise IntegrityError("rerender numeric array mismatch")
    if directory is not None and (directory / "rgb.png").read_bytes() != _png_bytes(rgb):
        raise IntegrityError("rerender PNG mismatch")


def _detector(scene: V3Scene, empty_depth: np.ndarray, controller: str) -> v1.Detection:
    with _v3_config():
        return v2._detector(scene, empty_depth, controller)


def _route(detection: v1.Detection, goal: list[float], controller: str) -> list[list[float]]:
    with _v3_config():
        route = v2._route(detection, goal)
    # Preserve controller equivalence in dynamics while making the semantic path
    # receipt controller-specific and causally authenticated.
    return route


def _contacts(model: mujoco.MjModel, data: mujoco.MjData) -> list[dict[str, Any]]:
    return v2._contacts(model, data)


def _run_episode(scene: V3Scene, empty_depth: np.ndarray, controller: str) -> v2.V2Episode:
    with _v3_config():
        episode = v2.run_episode_v2(scene, empty_depth, controller)
    contract = controller_contract(controller)
    episode.metadata["controller_contract"] = contract
    episode.metadata["condition_from_xml"] = _infer_condition(scene.xml)
    for row in episode.ticks:
        row["controller_id"] = controller
        row["controller_path"] = contract["path"]
        row["controller_contract_sha256"] = contract["contract_sha256"]
    return episode


def _strict(path: Path, value: Any) -> None:
    path.write_text(json.dumps(v1._json_finite(value), sort_keys=True, indent=2, allow_nan=False) + "\n")


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(v1._json_finite(row), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n" for row in rows))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _write_scene(path: Path, scene: V3Scene) -> None:
    path.mkdir(parents=True)
    np.save(path / "rgb.npy", scene.rgb, allow_pickle=False)
    np.save(path / "depth.npy", scene.depth, allow_pickle=False)
    v1.write_png(path / "rgb.png", scene.rgb)
    (path / "scene.xml").write_text(scene.xml)
    _strict(path / "scene.json", scene.contract)


def _load_scene(root: Path, rel: str) -> tuple[V3Scene, Path]:
    path = root / rel
    contract = json.loads((path / "scene.json").read_text())
    return V3Scene(
        contract["seed"], contract["condition"],
        np.load(path / "rgb.npy", allow_pickle=False),
        np.load(path / "depth.npy", allow_pickle=False),
        (path / "scene.xml").read_text(), contract,
    ), path


def _write_episode(path: Path, episode: v2.V2Episode) -> None:
    path.mkdir(parents=True)
    _strict(path / "episode.json", episode.metadata)
    _jsonl(path / "ticks.jsonl", episode.ticks)


def _episode_identity(path: Path, meta: dict[str, Any]) -> str:
    return f"seed-{meta['seed']}-{meta['condition'].lower()}-{meta['controller'].lower()}"


def _replay(root: Path, episode_path: Path, check_receipts: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cfg = load_config()
    meta = json.loads((episode_path / "episode.json").read_text())
    ticks = _read_jsonl(episode_path / "ticks.jsonl")
    if episode_path.name != _episode_identity(episode_path, meta):
        raise IntegrityError("episode identity directory/metadata mismatch")
    expected_controller = controller_contract(meta["controller"])
    if meta.get("controller_contract") != expected_controller:
        raise IntegrityError("episode identity controller contract mismatch")
    expected_scene_rel = f"raw/scenes/seed-{meta['seed']}-{meta['condition'].lower()}"
    if meta["scene_relpath"] != expected_scene_rel:
        raise IntegrityError("episode identity scene path mismatch")
    scene, scene_path = _load_scene(root, meta["scene_relpath"])
    if scene.seed != meta["seed"] or scene.condition != meta["condition"]:
        raise IntegrityError("scene identity episode/scene mismatch")
    authenticate_scene(scene, scene_path)
    empty, empty_path = _load_scene(root, f"raw/scenes/seed-{meta['seed']}-no_obstacle")
    authenticate_scene(empty, empty_path)
    detection = _detector(scene, empty.depth, meta["controller"])
    model = mujoco.MjModel.from_xml_string(scene.xml)
    data = mujoco.MjData(model)
    start = np.asarray(model.body_pos[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "robot")][:2], dtype=float)
    goal = [float(x) for x in model.site_pos[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "goal")][:2]]
    route = _route(detection, goal, meta["controller"])
    waypoint = 0
    replayed: list[dict[str, Any]] = []
    for index, stored in enumerate(ticks):
        world = start + data.qpos[:2]
        target = np.asarray(route[waypoint])
        if np.linalg.norm(target - world) < 0.10 and waypoint < len(route) - 1:
            waypoint += 1
            target = np.asarray(route[waypoint])
        expected_command = np.clip(4.2 * (target - world) - 1.8 * data.qvel[:2], -5.0, 5.0)
        if stored["tick"] != index or not np.allclose(stored["command"], expected_command, rtol=0, atol=1e-12):
            raise IntegrityError("controller command/path mismatch")
        if stored.get("controller_id") != meta["controller"] or stored.get("controller_path") != expected_controller["path"] or stored.get("controller_contract_sha256") != expected_controller["contract_sha256"]:
            raise IntegrityError("controller path receipt mismatch")
        data.ctrl[:] = stored["command"]
        mujoco.mj_step(model, data)
        replay = {
            "tick": index,
            "qpos_model": [float(x) for x in data.qpos[:2]],
            "qpos_world": [float(x) for x in start + data.qpos[:2]],
            "qvel": [float(x) for x in data.qvel[:2]],
            "contacts": _contacts(model, data),
            "target": [float(x) for x in target],
            "recovery": "NONE",
        }
        if check_receipts:
            for key in ("qpos_model", "qpos_world", "qvel", "target"):
                if not np.allclose(stored[key], replay[key], rtol=0, atol=1e-12):
                    raise IntegrityError("stored state receipt mismatch")
            if stored["contacts"] != replay["contacts"] or stored["recovery"] != replay["recovery"]:
                raise IntegrityError("stored contact/recovery receipt mismatch")
        replayed.append(replay)
    truth_present = _infer_condition(scene.xml) != "NO_OBSTACLE"
    if truth_present and detection.present and detection.center_xy is not None:
        obstacle = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "obstacle")
        truth = [float(x) for x in model.geom_pos[obstacle][:2]]
        localization = math.dist(detection.center_xy, truth)
    elif not truth_present and not detection.present:
        localization = 0.0
    else:
        localization = math.inf
    obstacle_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "obstacle")
    contact_ticks = sum(any(obstacle_id >= 0 and obstacle_id in (c["geom1"], c["geom2"]) for c in row["contacts"]) for row in replayed)
    final = replayed[-1]["qpos_world"]
    goal_error = math.dist(final, goal)
    completion = goal_error <= cfg["goal_tolerance_m"]
    collision_free = contact_ticks == 0
    path_length = sum(math.dist(a["qpos_world"], b["qpos_world"]) for a, b in zip(replayed, replayed[1:]))
    score = {
        "episode_id": episode_path.name, "seed": meta["seed"], "condition": _infer_condition(scene.xml), "controller": meta["controller"],
        "detection_correct": detection.present == truth_present and (not truth_present or localization <= cfg["localization_tolerance_m"]),
        "detection_present": detection.present, "localization_error_m": localization if math.isfinite(localization) else None,
        "task_complete": completion, "collision_free": collision_free,
        "safe_completion": completion and collision_free and all(abs(row["qpos_world"][1]) < 0.88 for row in replayed),
        "goal_error_m": goal_error, "obstacle_contact_ticks": int(contact_ticks), "path_length_m": path_length,
        "ticks": len(replayed), "replans": 0, "semantic_wakes": 0, "detector_latency_ms": detection.latency_ms,
    }
    return score, replayed


def score_episode(root: Path, episode_path: Path) -> dict[str, Any]:
    return _replay(root, episode_path, check_receipts=False)[0]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()


def _source_paths() -> list[str]:
    return [
        "experiments/12_opaque_glass_transfer/src/v3.py",
        "experiments/12_opaque_glass_transfer/src/v2.py",
        "experiments/12_opaque_glass_transfer/src/experiment.py",
        "experiments/12_opaque_glass_transfer/config-v3.json",
    ]


def _source_hashes(commit: str | None) -> dict[str, str]:
    repo = Path(_git("rev-parse", "--show-toplevel"))
    if commit is None:
        return {path: v1.sha256_file(repo / path) for path in _source_paths()}
    return {path: _sha(subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, check=True, capture_output=True).stdout) for path in _source_paths()}


def _closure(mode: str, matrix: list[dict[str, Any]]) -> dict[str, Any]:
    commit = _git("rev-parse", "HEAD")
    heldout = mode == "HELDOUT"
    return {
        "schema": "opaque-glass-transfer-closure-v3", "status": "COMPLETE", "mode": mode,
        "source_commit": commit, "source_parent_commit": _git("rev-parse", f"{commit}^"),
        "evidence_commit_policy": "evidence tree commit must be a descendant of source_commit; exact receipt is external because Git commits cannot self-hash",
        "config_sha256": v1.sha256_file(CONFIG), "source_hashes": _source_hashes(commit if heldout else None),
        "matrix": matrix, "seed_namespace": load_config()["heldout_seeds"] if heldout else load_config()["calibration_seeds"],
        "environment": {"python": sys.version, "mujoco": mujoco.__version__, "numpy": np.__version__, "platform": platform.platform()},
    }


def _manifest_entries(root: Path) -> list[dict[str, Any]]:
    entries = []
    for path in sorted(root.rglob("*")):
        if path == root / "manifest.json":
            continue
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise IntegrityError(f"symlink: {rel}")
        if path.is_dir():
            entries.append({"path": rel, "type": "directory"})
        elif path.is_file():
            entries.append({"path": rel, "type": "file", "bytes": path.stat().st_size, "sha256": v1.sha256_file(path)})
        else:
            raise IntegrityError(f"unsupported member: {rel}")
    return entries


def write_manifest(root: Path) -> None:
    _strict(root / "manifest.json", {"schema": "recursive-manifest-v3", "entries": _manifest_entries(root)})


def verify_manifest(root: Path) -> None:
    expected = {"schema": "recursive-manifest-v3", "entries": _manifest_entries(root)}
    if json.loads((root / "manifest.json").read_text()) != expected:
        raise IntegrityError("manifest mismatch")
    allowed = {"raw", "closure.json", "manifest.json"}
    if (root / "derived").exists():
        allowed.add("derived")
    if (root / "attestations").exists():
        allowed.add("attestations")
    if {path.name for path in root.iterdir()} != allowed:
        raise IntegrityError("root allowlist mismatch")


def _git_blob(commit: str, path: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise IntegrityError("lifecycle declared Git blob unavailable") from error


def _config_at_source() -> dict[str, Any]:
    return json.loads(_git_blob(SOURCE_COMMIT, "experiments/12_opaque_glass_transfer/config-v3.json"))


def _matrix_from_config(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"seed": seed, "condition": condition, "controller": controller}
        for seed in cfg["heldout_seeds"]
        for condition in cfg["heldout_conditions"]
        for controller in cfg["controllers"]
    ]


def _episode_receipts(root: Path) -> dict[str, Any]:
    episodes = []
    for episode_path in sorted(path for path in (root / "raw/episodes").iterdir() if path.is_dir()):
        meta_path = episode_path / "episode.json"
        ticks_path = episode_path / "ticks.jsonl"
        meta = json.loads(meta_path.read_text())
        scene_path = root / meta["scene_relpath"]
        scene_hashes = {
            name: v1.sha256_file(scene_path / name)
            for name in ("scene.json", "scene.xml", "rgb.npy", "depth.npy", "rgb.png")
        }
        episodes.append({
            "episode_id": episode_path.name,
            "seed": meta["seed"],
            "condition": meta["condition"],
            "controller": meta["controller"],
            "scene_relpath": meta["scene_relpath"],
            "episode_json_sha256": v1.sha256_file(meta_path),
            "ticks_jsonl_sha256": v1.sha256_file(ticks_path),
            "scene_hashes": scene_hashes,
        })
    return {
        "schema": "exp12-v3-episode-receipts-v1",
        "run_json_sha256": v1.sha256_file(root / "raw/run.json"),
        "episodes": episodes,
    }


def seal_lifecycle(root: Path) -> None:
    cfg = _config_at_source()
    attestations = root / "attestations"
    attestations.mkdir(exist_ok=True)
    chronology = _git_blob(CHRONOLOGY_RECEIPT_COMMIT, CHRONOLOGY_PATH)
    invalidation = _git_blob(SOURCE_COMMIT, INVALIDATION_PATH)
    (attestations / "V3_EVIDENCE_RECEIPT.json").write_bytes(chronology)
    (attestations / "V1_V2_INVALID_REJECTED.json").write_bytes(invalidation)
    _strict(attestations / "episode-receipts.json", _episode_receipts(root))
    old = json.loads((root / "closure.json").read_text())
    closure = {
        "schema": "opaque-glass-transfer-lifecycle-v3",
        "status": "COMPLETE",
        "mode": "HELDOUT",
        "source_commit": SOURCE_COMMIT,
        "source_parent_commit": SOURCE_PARENT_COMMIT,
        "evidence_commit": EVIDENCE_COMMIT,
        "evidence_parent_commit": SOURCE_COMMIT,
        "chronology_receipt_commit": CHRONOLOGY_RECEIPT_COMMIT,
        "config_sha256": _sha(_git_blob(SOURCE_COMMIT, "experiments/12_opaque_glass_transfer/config-v3.json")),
        "source_hashes": _source_hashes(SOURCE_COMMIT),
        "matrix": _matrix_from_config(cfg),
        "seed_namespace": cfg["heldout_seeds"],
        "material_namespace": cfg["material_namespace"],
        "environment": old["environment"],
        "attestation_hashes": {
            "V3_EVIDENCE_RECEIPT.json": _sha(chronology),
            "V1_V2_INVALID_REJECTED.json": _sha(invalidation),
            "episode-receipts.json": v1.sha256_file(attestations / "episode-receipts.json"),
        },
    }
    _strict(root / "closure.json", closure)
    write_manifest(root)


def _validate_lifecycle_closure(root: Path) -> dict[str, Any]:
    closure = json.loads((root / "closure.json").read_text())
    cfg = _config_at_source()
    exact = {
        "schema": "opaque-glass-transfer-lifecycle-v3",
        "status": "COMPLETE",
        "mode": "HELDOUT",
        "source_commit": SOURCE_COMMIT,
        "source_parent_commit": SOURCE_PARENT_COMMIT,
        "evidence_commit": EVIDENCE_COMMIT,
        "evidence_parent_commit": SOURCE_COMMIT,
        "chronology_receipt_commit": CHRONOLOGY_RECEIPT_COMMIT,
        "config_sha256": _sha(_git_blob(SOURCE_COMMIT, "experiments/12_opaque_glass_transfer/config-v3.json")),
        "source_hashes": _source_hashes(SOURCE_COMMIT),
        "matrix": _matrix_from_config(cfg),
        "seed_namespace": cfg["heldout_seeds"],
        "material_namespace": cfg["material_namespace"],
    }
    if set(closure) != CLOSURE_KEYS or any(closure.get(key) != value for key, value in exact.items()):
        raise IntegrityError("lifecycle closure identity mismatch")
    try:
        if _git("rev-parse", f"{SOURCE_COMMIT}^") != SOURCE_PARENT_COMMIT:
            raise IntegrityError("lifecycle source parent mismatch")
        if _git("rev-parse", f"{EVIDENCE_COMMIT}^") != SOURCE_COMMIT:
            raise IntegrityError("lifecycle evidence parent mismatch")
        if _git("rev-parse", f"{CHRONOLOGY_RECEIPT_COMMIT}^") != EVIDENCE_COMMIT:
            raise IntegrityError("lifecycle receipt parent mismatch")
    except subprocess.CalledProcessError as error:
        raise IntegrityError("lifecycle commit unavailable") from error
    return closure


def validate_lifecycle(root: Path) -> None:
    try:
        verify_manifest(root)
        closure = _validate_lifecycle_closure(root)
        attestations = root / "attestations"
        expected_files = {
            "V3_EVIDENCE_RECEIPT.json": _git_blob(CHRONOLOGY_RECEIPT_COMMIT, CHRONOLOGY_PATH),
            "V1_V2_INVALID_REJECTED.json": _git_blob(SOURCE_COMMIT, INVALIDATION_PATH),
        }
        if {path.name for path in attestations.iterdir()} != {*expected_files, "episode-receipts.json"}:
            raise IntegrityError("lifecycle attestation allowlist mismatch")
        for name, expected in expected_files.items():
            if (attestations / name).read_bytes() != expected:
                raise IntegrityError("lifecycle attestation blob mismatch")
        expected_receipts = _episode_receipts(root)
        if json.loads((attestations / "episode-receipts.json").read_text()) != expected_receipts:
            raise IntegrityError("lifecycle episode hash receipt mismatch")
        expected_hashes = {
            name: _sha(value) for name, value in expected_files.items()
        }
        expected_hashes["episode-receipts.json"] = v1.sha256_file(attestations / "episode-receipts.json")
        if closure["attestation_hashes"] != expected_hashes:
            raise IntegrityError("lifecycle attestation closure mismatch")
        run = json.loads((root / "raw/run.json").read_text())
        if set(run) != {"mode", "episodes"} or run["mode"] != "HELDOUT" or len(run["episodes"]) != 108:
            raise IntegrityError("lifecycle run schema/mode mismatch")
        run_by_id = {}
        for receipt in run["episodes"]:
            if set(receipt) != RUN_RECEIPT_KEYS:
                raise IntegrityError("lifecycle run receipt schema mismatch")
            episode_id = receipt["episode_id"]
            if episode_id in run_by_id:
                raise IntegrityError("lifecycle duplicate episode receipt")
            meta = json.loads((root / "raw/episodes" / episode_id / "episode.json").read_text())
            if receipt != {**meta, "episode_id": episode_id}:
                raise IntegrityError("lifecycle arbitrary run receipt mismatch")
            run_by_id[episode_id] = receipt
        cfg = _config_at_source()
        matrix = _matrix_from_config(cfg)
        expected_ids = {
            f"seed-{row['seed']}-{row['condition'].lower()}-{row['controller'].lower()}"
            for row in matrix
        }
        raw_ids = {path.name for path in (root / "raw/episodes").iterdir() if path.is_dir()}
        if set(run_by_id) != expected_ids or raw_ids != expected_ids:
            raise IntegrityError("lifecycle raw episode identity mismatch")
        expected_scenes = {
            f"seed-{seed}-{condition.lower()}"
            for seed in cfg["heldout_seeds"]
            for condition in cfg["heldout_conditions"]
        }
        if {path.name for path in (root / "raw/scenes").iterdir() if path.is_dir()} != expected_scenes:
            raise IntegrityError("lifecycle raw scene identity mismatch")
    except IntegrityError:
        raise
    except Exception as error:
        raise IntegrityError("lifecycle validation failure") from error


def _validate_closure(root: Path) -> dict[str, Any]:
    closure = json.loads((root / "closure.json").read_text())
    if closure.get("schema") == "opaque-glass-transfer-lifecycle-v3":
        return _validate_lifecycle_closure(root)
    if set(closure) != LEGACY_CLOSURE_KEYS or closure["schema"] != "opaque-glass-transfer-closure-v3" or closure["status"] != "COMPLETE":
        raise IntegrityError("closure schema/status mismatch")
    if closure["config_sha256"] != v1.sha256_file(CONFIG):
        raise IntegrityError("closure config mismatch")
    expected_hashes = _source_hashes(closure["source_commit"] if closure["mode"] == "HELDOUT" else None)
    if closure["source_hashes"] != expected_hashes:
        raise IntegrityError("closure source mismatch")
    if closure["mode"] == "HELDOUT":
        if closure["matrix"] != heldout_matrix(load_config()) or closure["seed_namespace"] != load_config()["heldout_seeds"]:
            raise IntegrityError("closure matrix/seed mismatch")
    return closure


def validate_raw(root: Path, verify_manifest: bool = True) -> list[dict[str, Any]]:
    if verify_manifest:
        globals()["verify_manifest"](root)
    closure = _validate_closure(root)
    run = json.loads((root / "raw/run.json").read_text())
    episode_paths = sorted(path for path in (root / "raw/episodes").iterdir() if path.is_dir())
    expected_count = 108 if closure["mode"] == "HELDOUT" else len(closure["matrix"])
    if len(episode_paths) != expected_count or len(run["episodes"]) != expected_count:
        raise IntegrityError("raw episode count mismatch")
    scores = []
    for path in episode_paths:
        score, _ = _replay(root, path, check_receipts=True)
        scores.append(score)
    actual = [{key: score[key] for key in ("seed", "condition", "controller")} for score in scores]
    def sort_key(row: dict[str, Any]) -> tuple[Any, Any, Any]:
        return row["seed"], row["condition"], row["controller"]
    if sorted(actual, key=sort_key) != sorted(closure["matrix"], key=sort_key):
        raise IntegrityError("raw matrix identity mismatch")
    return scores


def _bootstrap(values: np.ndarray, rng: np.random.Generator, draws: int) -> dict[str, Any]:
    means = values[rng.integers(0, len(values), size=(draws, len(values)))].mean(axis=1)
    return {"estimate": float(values.mean()), "ci_low": float(np.quantile(means, 0.025)), "ci_high": float(np.quantile(means, 0.975)), "effective_n": len(values), "draws": draws}


def _analysis(scores: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = load_config()
    if len(scores) != 108:
        return {"scores": scores}
    by = {(r["seed"], r["condition"], r["controller"]): r for r in scores}
    summary = []
    for condition in cfg["heldout_conditions"]:
        for controller in cfg["controllers"]:
            cell = [r for r in scores if r["condition"] == condition and r["controller"] == controller]
            summary.append({"condition": condition, "controller": controller, "n": len(cell), "detection_rate": sum(r["detection_correct"] for r in cell)/len(cell), "safe_completion_rate": sum(r["safe_completion"] for r in cell)/len(cell), "collision_free_rate": sum(r["collision_free"] for r in cell)/len(cell), "mean_path_length_m": sum(r["path_length_m"] for r in cell)/len(cell), "mean_ticks": sum(r["ticks"] for r in cell)/len(cell)})
    rng = np.random.default_rng(cfg["bootstrap_seed"])
    contrasts = {}
    for controller in cfg["controllers"]:
        for metric in ("detection_correct", "safe_completion"):
            values = np.array([float(by[(s,"EVAL_X3",controller)][metric])-float(by[(s,"OPAQUE",controller)][metric]) for s in cfg["heldout_seeds"]])
            contrasts[f"{controller}:eval_minus_opaque:{metric}"] = _bootstrap(values, rng, cfg["bootstrap_draws"])
    for controller in ("RGBD_MOTION", "HIERARCHICAL"):
        values = np.array([float(by[(s,"EVAL_X3",controller)]["safe_completion"])-float(by[(s,"EVAL_X3","RGB_ONLY")]["safe_completion"]) for s in cfg["heldout_seeds"]])
        contrasts[f"{controller}_minus_RGB_ONLY:eval:safe_completion"] = _bootstrap(values, rng, cfg["bootstrap_draws"])
    return {"summary": summary, "paired_contrasts": contrasts}


def _graph_rgb(analysis: dict[str, Any]) -> np.ndarray:
    image = np.full((240, 480, 3), 255, dtype=np.uint8)
    rows = [r for r in analysis.get("summary", []) if r["condition"] == "EVAL_X3"]
    colors = [(201,75,69),(59,130,196),(75,155,98)]
    for i, row in enumerate(rows):
        height = int(180 * row["safe_completion_rate"])
        x0 = 55 + i * 145
        image[210-height:210, x0:x0+75] = colors[i]
    image[210:212, 25:455] = 0
    return image


def _svg(path: Path, analysis: dict[str, Any]) -> None:
    rows = [r for r in analysis.get("summary", []) if r["condition"] == "EVAL_X3"]
    bars = []
    for i, row in enumerate(rows):
        x = 65 + i * 155
        h = row["safe_completion_rate"] * 210
        bars.append(f'<rect x="{x}" y="{260-h:.2f}" width="84" height="{h:.2f}" fill="{["#c94b45","#3b82c4","#4b9b62"][i]}"/><text x="{x+42}" y="282" text-anchor="middle">{row["controller"]}</text>')
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="550" height="310"><rect width="100%" height="100%" fill="white"/><text x="275" y="24" text-anchor="middle">V3 evaluation safe completion</text>'+''.join(bars)+'</svg>\n')


def derive(root: Path, scores: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if scores is None:
        scores = validate_raw(root, verify_manifest=False)
    derived = root / "derived"
    if derived.exists():
        shutil.rmtree(derived)
    (derived / "scores").mkdir(parents=True)
    for score in scores:
        _strict(derived / "scores" / f"{score['episode_id']}.json", score)
    with (derived / "episodes.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(scores[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(scores)
    analysis = _analysis(scores)
    _strict(derived / "analysis.json", analysis)
    _svg(derived / "safe-completion.svg", analysis)
    v1.write_png(derived / "safe-completion.png", _graph_rgb(analysis))
    if len(scores) == 108:
        working = next(r for r in scores if r["condition"]=="EVAL_X3" and r["controller"]=="HIERARCHICAL" and r["safe_completion"])
        nonworking = next(r for r in scores if r["condition"]=="EVAL_X3" and r["controller"]=="RGB_ONLY" and not r["safe_completion"])
    else:
        working = scores[0]
        nonworking = scores[0]
    _strict(derived / "samples.json", {"rule":"lowest seed in frozen classes", "working":working, "nonworking":nonworking})
    report = f"# Exp12 V3 reconstructed report\n\nEpisodes: {len(scores)}\n\nAnalysis SHA-256: {v1.sha256_file(derived/'analysis.json')}\n\nDisposition: synthetic rendered transfer only.\n"
    (derived / "REPORT.md").write_text(report)
    return scores


def _compare_derived(reference: Path, rebuilt: Path) -> None:
    ref_files = sorted(p.relative_to(reference).as_posix() for p in reference.rglob("*") if p.is_file())
    new_files = sorted(p.relative_to(rebuilt).as_posix() for p in rebuilt.rglob("*") if p.is_file())
    if ref_files != new_files:
        raise IntegrityError("derived byte mismatch file set")
    for rel in ref_files:
        if (reference/rel).read_bytes() != (rebuilt/rel).read_bytes():
            raise IntegrityError(f"derived byte mismatch: {rel}")


def validate_qualification(root: Path) -> None:
    verify_manifest(root)
    if json.loads((root / "closure.json").read_text()).get("schema") == "opaque-glass-transfer-lifecycle-v3":
        validate_lifecycle(root)
    scores = validate_raw(root)
    with tempfile.TemporaryDirectory() as directory:
        rebuilt = Path(directory) / "rebuilt"
        rebuilt.mkdir()
        shutil.copytree(root / "raw", rebuilt / "raw")
        shutil.copy2(root / "closure.json", rebuilt / "closure.json")
        if (root / "attestations").exists():
            shutil.copytree(root / "attestations", rebuilt / "attestations")
        derive(rebuilt, scores)
        _compare_derived(root / "derived", rebuilt / "derived")


def write_calibration_fixture(tmp_path: Path, seed: int, controller: str, derive: bool = False) -> Path:
    root = tmp_path / "fixture"
    (root / "raw/scenes").mkdir(parents=True)
    (root / "raw/episodes").mkdir()
    absent = render_scene(seed, "NO_OBSTACLE")
    opaque = render_scene(seed, "OPAQUE")
    for scene in (absent, opaque):
        _write_scene(root / f"raw/scenes/seed-{seed}-{scene.condition.lower()}", scene)
    episode = _run_episode(opaque, absent.depth, controller)
    episode_id = f"seed-{seed}-opaque-{controller.lower()}"
    _write_episode(root / "raw/episodes" / episode_id, episode)
    matrix = [{"seed":seed,"condition":"OPAQUE","controller":controller}]
    _strict(root / "raw/run.json", {"mode":"CALIBRATION","episodes":[{**episode.metadata,"episode_id":episode_id}]})
    _strict(root / "closure.json", _closure("CALIBRATION", matrix))
    if derive:
        scores = validate_raw(root, verify_manifest=False)
        globals()["derive"](root, scores)
        write_manifest(root)
    return root


def run(output: Path) -> dict[str, Any]:
    if output.exists():
        raise IntegrityError("output exists")
    cfg = load_config()
    matrix = heldout_matrix(cfg)
    (output/"raw/scenes").mkdir(parents=True)
    (output/"raw/episodes").mkdir()
    _strict(output/"closure.json", _closure("HELDOUT", matrix))
    metas=[]
    for seed in cfg["heldout_seeds"]:
        scenes={condition:render_scene(seed,condition) for condition in cfg["heldout_conditions"]}
        for scene in scenes.values():
            _write_scene(output/f"raw/scenes/seed-{seed}-{scene.condition.lower()}",scene)
        for condition in cfg["heldout_conditions"]:
            for controller in cfg["controllers"]:
                episode=_run_episode(scenes[condition],scenes["NO_OBSTACLE"].depth,controller)
                episode_id=f"seed-{seed}-{condition.lower()}-{controller.lower()}"
                _write_episode(output/"raw/episodes"/episode_id,episode)
                metas.append({**episode.metadata,"episode_id":episode_id})
    _strict(output/"raw/run.json", {"mode":"HELDOUT","episodes":metas})
    scores=validate_raw(output,verify_manifest=False)
    derive(output, scores)
    write_manifest(output)
    validate_qualification(output)
    return {"scores":scores,"analysis":json.loads((output/"derived/analysis.json").read_text())}


def reconstruct(source: Path, target: Path) -> None:
    validate_qualification(source)
    if target.exists():
        raise IntegrityError("target exists")
    target.mkdir()
    shutil.copytree(source/"raw", target/"raw")
    shutil.copy2(source/"closure.json", target/"closure.json")
    if (source / "attestations").exists():
        shutil.copytree(source / "attestations", target / "attestations")
    scores = validate_raw(target, verify_manifest=False)
    derive(target, scores)
    write_manifest(target)
    validate_qualification(target)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.output)["analysis"],sort_keys=True,indent=2))
