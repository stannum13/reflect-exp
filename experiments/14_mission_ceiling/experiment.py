from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import deque
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).parent
CONFIG = ROOT / "config.json"
AXES = ("route", "topology", "constraint", "disturbance", "intervention", "paraphrase", "novelty")


class IntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Scenario:
    seed: int
    mission: str
    horizon: int
    variant: str
    instruction: str
    start: str
    initial_goal: str
    intervention_goal: str
    target_object: str
    required_objects: tuple[str, ...]
    terminal_action: str
    graph: tuple[tuple[str, str], ...]
    blocked_initial: tuple[tuple[str, str], ...]
    locked_edges: tuple[tuple[str, str], ...]
    unsafe_rooms: tuple[str, ...]
    object_locations: tuple[tuple[str, str], ...]
    event_step: int


@dataclass(frozen=True)
class BuildingState:
    agent_room: str
    object_locations: tuple[tuple[str, str], ...]
    inventory: tuple[str, ...]
    blocked_edges: tuple[tuple[str, str], ...]
    active_goal: str
    unsafe_rooms: tuple[str, ...]
    effects: tuple[str, ...]
    safety_violations: int


@dataclass(frozen=True)
class Transition:
    state: BuildingState
    accepted: bool
    reason: str


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG.read_text())


def matrix(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"seed": seed, "mission": mission, "horizon": horizon, "variant": variant, "agent": agent}
        for seed in cfg["seeds"]
        for mission in cfg["missions"]
        for horizon in cfg["horizons"]
        for variant in cfg["variants"]
        for agent in cfg["agents"]
    ]


def _edge(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def make_scenario(seed: int, mission: str, horizon: int, variant: str) -> Scenario:
    if mission not in load_config()["missions"] or horizon not in (4, 8, 12, 16) or variant not in ("baseline", *AXES):
        raise ValueError("scenario outside frozen matrix")
    distance = max(1, horizon // 2 - (2 if mission == "tool" else 1))
    chain = ["dock", *[f"room_{i}" for i in range(1, distance + 1)], "goal"]
    graph = {_edge(a, b) for a, b in zip(chain, chain[1:])}
    pivot = 1 + seed % max(1, len(chain) - 2)
    pivot = min(pivot, len(chain) - 2)
    left, right = chain[pivot - 1], chain[pivot]
    bypass = f"bypass_{pivot}"
    graph |= {_edge(left, bypass), _edge(bypass, right)}
    alternate_goal = "archive"
    graph.add(_edge(chain[-2], alternate_goal))
    side = "supply"
    graph.add(_edge("dock", side))
    target = {
        "parcel": "parcel", "retrieve": "record", "tool": "machine",
        "unpack": "crate", "store": "sample", "rearrange": "block",
    }[mission]
    required = (target, "wrench") if mission == "tool" else (target,)
    terminal = {
        "parcel": "deliver", "retrieve": "retrieve", "tool": "use_tool",
        "unpack": "unpack", "store": "store", "rearrange": "place",
    }[mission]
    locations = [(target, "dock")]
    if mission == "tool":
        locations = [(target, "goal"), ("wrench", "dock")]
    blocked: set[tuple[str, str]] = set()
    locked: set[tuple[str, str]] = set()
    unsafe: tuple[str, ...] = ()
    if variant == "topology":
        blocked.add(_edge(left, right))
    if variant == "constraint":
        unsafe = (chain[pivot],)
    if variant == "novelty":
        locked.add(_edge(left, right))
        locations.append(("badge", "dock"))
    instruction = f"{terminal} {target} to {chain[-1]}"
    if variant == "paraphrase":
        instruction = f"Please ensure the {target} winds up properly handled at {chain[-1]}"
    return Scenario(
        seed, mission, horizon, variant, instruction, "dock", chain[-1], alternate_goal,
        target, required, terminal, tuple(sorted(graph)), tuple(sorted(blocked)),
        tuple(sorted(locked)), unsafe, tuple(sorted(locations)), max(1, horizon // 3),
    )


def scenario_from_row(row: dict[str, Any]) -> Scenario:
    return make_scenario(int(row["seed"]), str(row["mission"]), int(row["horizon"]), str(row["variant"]))


def initial_state(scenario: Scenario) -> BuildingState:
    return BuildingState(
        scenario.start, scenario.object_locations, (), scenario.blocked_initial,
        scenario.initial_goal, scenario.unsafe_rooms, (), 0,
    )


def state_from_json(value: dict[str, Any]) -> BuildingState:
    return BuildingState(
        value["agent_room"], tuple(tuple(x) for x in value["object_locations"]),
        tuple(value["inventory"]), tuple(tuple(x) for x in value["blocked_edges"]),
        value["active_goal"], tuple(value["unsafe_rooms"]), tuple(value["effects"]),
        int(value["safety_violations"]),
    )


def _locations(state: BuildingState) -> dict[str, str]:
    return dict(state.object_locations)


def _replace_locations(state: BuildingState, values: dict[str, str]) -> BuildingState:
    return replace(state, object_locations=tuple(sorted(values.items())))


def observation(scenario: Scenario, state: BuildingState, step_index: int) -> dict[str, Any]:
    return {
        "step": step_index, "room": state.agent_room, "objects": dict(state.object_locations),
        "inventory": list(state.inventory), "blocked_edges": [list(x) for x in state.blocked_edges],
        "locked_edges": [list(x) for x in scenario.locked_edges], "unsafe_rooms": list(state.unsafe_rooms),
        "active_goal": state.active_goal, "instruction": scenario.instruction,
    }


def apply_event(scenario: Scenario, state: BuildingState, step_index: int) -> tuple[BuildingState, str]:
    if step_index != scenario.event_step:
        return state, "NONE"
    if scenario.variant == "route":
        chain_edges = [e for e in scenario.graph if "bypass" not in e[0] and "bypass" not in e[1] and "archive" not in e and "supply" not in e]
        edge = sorted(chain_edges)[scenario.seed % len(chain_edges)]
        return replace(state, blocked_edges=tuple(sorted({*state.blocked_edges, edge}))), f"BLOCK:{edge[0]}:{edge[1]}"
    if scenario.variant == "disturbance":
        loc = _locations(state)
        inventory = list(state.inventory)
        if scenario.target_object in inventory:
            inventory.remove(scenario.target_object)
        loc[scenario.target_object] = "supply"
        return replace(_replace_locations(state, loc), inventory=tuple(sorted(inventory))), "OBJECT_TO_SUPPLY"
    if scenario.variant == "intervention":
        return replace(state, active_goal=scenario.intervention_goal), "GOAL_TO_ARCHIVE"
    return state, "NONE"


def step(scenario: Scenario, state: BuildingState, action: dict[str, Any], step_index: int) -> Transition:
    kind = action.get("kind")
    if kind == "wait":
        return Transition(state, True, "wait")
    if kind == "move":
        target = str(action.get("to"))
        edge = _edge(state.agent_room, target)
        if edge not in scenario.graph or edge in state.blocked_edges:
            return Transition(state, False, "route unavailable")
        if edge in scenario.locked_edges and "badge" not in state.inventory:
            return Transition(state, False, "badge required")
        violations = state.safety_violations + int(target in state.unsafe_rooms)
        return Transition(replace(state, agent_room=target, safety_violations=violations), True, "moved")
    if kind == "pickup":
        obj = str(action.get("object"))
        locations = _locations(state)
        if locations.get(obj) != state.agent_room:
            return Transition(state, False, "object absent")
        del locations[obj]
        return Transition(replace(_replace_locations(state, locations), inventory=tuple(sorted({*state.inventory, obj}))), True, "picked")
    if kind == scenario.terminal_action:
        if state.agent_room != state.active_goal or any(obj not in state.inventory and _locations(state).get(obj) != state.active_goal for obj in scenario.required_objects):
            return Transition(state, False, "terminal precondition")
        locations = _locations(state)
        inventory = list(state.inventory)
        for obj in scenario.required_objects:
            if obj in inventory:
                inventory.remove(obj)
            locations[obj] = state.active_goal
        effect = f"{scenario.terminal_action}:{scenario.target_object}:{state.active_goal}"
        return Transition(replace(_replace_locations(state, locations), inventory=tuple(sorted(inventory)), effects=tuple(sorted({*state.effects, effect}))), True, "terminal effect")
    return Transition(state, False, "unknown action")


def _neighbors(scenario: Scenario, state: BuildingState, room: str, safe: bool, understands_locks: bool) -> list[str]:
    values = []
    for a, b in scenario.graph:
        if room not in (a, b):
            continue
        other = b if room == a else a
        edge = _edge(room, other)
        if edge in state.blocked_edges or (safe and other in state.unsafe_rooms):
            continue
        if edge in scenario.locked_edges and not understands_locks and "badge" not in state.inventory:
            pass
        values.append(other)
    return sorted(values)


def _path(scenario: Scenario, state: BuildingState, target: str, safe: bool, understands_locks: bool) -> list[str]:
    queue: deque[tuple[str, list[str]]] = deque([(state.agent_room, [])])
    seen = {state.agent_room}
    while queue:
        room, path = queue.popleft()
        if room == target:
            return path
        for nxt in _neighbors(scenario, state, room, safe, understands_locks):
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, [*path, nxt]))
    return []


def _plan(scenario: Scenario, state: BuildingState, agent: str, semantic_goal: str) -> list[dict[str, Any]]:
    if scenario.variant == "paraphrase" and agent == "open_loop":
        return [{"kind": "wait"}]
    safe = agent == "full_hierarchy"
    understands_locks = agent == "full_hierarchy"
    actions: list[dict[str, Any]] = []
    simulated = state
    required = list(scenario.required_objects)
    if understands_locks and scenario.locked_edges and "badge" not in simulated.inventory:
        required.insert(0, "badge")
    for obj in required:
        if obj in simulated.inventory:
            continue
        location = _locations(simulated).get(obj)
        if location is None:
            continue
        for room in _path(scenario, simulated, location, safe, understands_locks):
            action = {"kind": "move", "to": room}
            actions.append(action)
            simulated = step(scenario, simulated, action, -1).state
        action = {"kind": "pickup", "object": obj}
        actions.append(action)
        simulated = step(scenario, simulated, action, -1).state
    for room in _path(scenario, simulated, semantic_goal, safe, understands_locks):
        action = {"kind": "move", "to": room}
        actions.append(action)
        simulated = step(scenario, simulated, action, -1).state
    actions.append({"kind": scenario.terminal_action})
    return actions


def run_episode(row: dict[str, Any]) -> dict[str, Any]:
    scenario = scenario_from_row(row)
    agent = str(row["agent"])
    state = initial_state(scenario)
    open_plan = _plan(scenario, state, agent, scenario.initial_goal)
    open_index = 0
    retries = replans = 0
    last_goal = scenario.initial_goal
    ledger: list[dict[str, Any]] = []
    for index in range(scenario.horizon):
        before_event = state
        state, event = apply_event(scenario, state, index)
        if agent == "full_hierarchy" and state.active_goal != last_goal:
            replans += 1
            last_goal = state.active_goal
        if agent == "open_loop":
            action = open_plan[open_index] if open_index < len(open_plan) else {"kind": "wait"}
            open_index += 1
            memory_step = 0
        else:
            semantic_goal = state.active_goal if agent == "full_hierarchy" else scenario.initial_goal
            plan = _plan(scenario, state, agent, semantic_goal)
            action = plan[0] if plan else {"kind": "wait"}
            memory_step = index
        transition = step(scenario, state, action, index)
        retry = not transition.accepted and agent in {"lower_recovery", "full_hierarchy"}
        retries += int(retry)
        state = transition.state
        terminal = _mission_complete(scenario, state)
        ledger.append({
            "step": index, "state_before": asdict(before_event), "event": event,
            "action": action, "accepted": transition.accepted, "reason": transition.reason,
            "observation_after": observation(scenario, state, index),
            "memory": {"fresh_at_step": memory_step, "episodic_schema": scenario.mission if agent == "full_hierarchy" else None},
            "retry": retry, "semantic_replan": agent == "full_hierarchy" and event == "GOAL_TO_ARCHIVE",
            "terminal": terminal,
        })
        if terminal:
            break
    score = score_episode(scenario, state, {"steps": ledger, "retries": retries, "replans": replans})
    return {"row": row, "scenario": asdict(scenario), "ledger": ledger, "terminal_state": asdict(state), "score": score}


def _mission_complete(scenario: Scenario, state: BuildingState) -> bool:
    effect = f"{scenario.terminal_action}:{scenario.target_object}:{state.active_goal}"
    locations = _locations(state)
    return effect in state.effects and all(locations.get(obj) == state.active_goal for obj in scenario.required_objects)


def score_episode(scenario: Scenario, terminal: BuildingState, trace: dict[str, Any]) -> dict[str, Any]:
    locations = _locations(terminal)
    object_ready = all(obj in terminal.inventory or locations.get(obj) == terminal.active_goal for obj in scenario.required_objects)
    at_goal = terminal.agent_room == terminal.active_goal
    effect = f"{scenario.terminal_action}:{scenario.target_object}:{terminal.active_goal}"
    effect_done = effect in terminal.effects
    complete = object_ready and at_goal and effect_done
    components = [object_ready, at_goal, effect_done]
    steps = trace.get("steps", [])
    freshness = 0.0 if not steps else sum(max(0, row["step"] - row["memory"]["fresh_at_step"]) for row in steps) / len(steps)
    retries = int(trace.get("retries", sum(bool(x.get("retry")) for x in steps)))
    replans = int(trace.get("replans", sum(bool(x.get("semantic_replan")) for x in steps)))
    return {
        "mission_complete": bool(complete), "safe": terminal.safety_violations == 0,
        "progress": sum(components) / len(components), "retries": retries,
        "semantic_replans": replans, "memory_staleness": freshness,
        "steps": len(steps), "action_cost": len(steps) + 0.25 * retries + 0.5 * replans,
    }


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _manifest_entries(root: Path) -> list[dict[str, Any]]:
    entries = []
    for path in sorted(root.rglob("*")):
        if path == root / "manifest.json":
            continue
        if path.is_symlink():
            raise IntegrityError("symlink")
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            entries.append({"path": rel, "type": "directory"})
        elif path.is_file():
            entries.append({"path": rel, "type": "file", "bytes": path.stat().st_size, "sha256": _sha_file(path)})
    return entries


def write_manifest(root: Path) -> None:
    _write_json(root / "manifest.json", {"schema": "exp14-recursive-manifest-v1", "entries": _manifest_entries(root)})


def verify_manifest(root: Path) -> None:
    expected = {"schema": "exp14-recursive-manifest-v1", "entries": _manifest_entries(root)}
    if json.loads((root / "manifest.json").read_text()) != expected:
        raise IntegrityError("manifest mismatch")
    allowed = {"raw", "derived", "closure.json", "manifest.json"}
    if {x.name for x in root.iterdir()} != allowed:
        raise IntegrityError("root allowlist")


def _bootstrap(values: np.ndarray, rng: np.random.Generator, draws: int) -> dict[str, Any]:
    if len(values) == 1:
        return {"estimate": float(values[0]), "ci_low": None, "ci_high": None, "effective_n": 1, "draws": draws}
    sampled = values[rng.integers(0, len(values), size=(draws, len(values)))].mean(axis=1)
    return {"estimate": float(values.mean()), "ci_low": float(np.quantile(sampled, 0.025)), "ci_high": float(np.quantile(sampled, 0.975)), "effective_n": int(len(values)), "draws": draws}


def seed_cluster_contrast(
    rows: list[dict[str, Any]],
    other_agent: str,
    draws: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    by = {
        (int(row["seed"]), row["mission"], int(row["horizon"]), row["variant"], row["agent"]): row
        for row in rows
    }
    seed_means = []
    for seed in sorted({int(row["seed"]) for row in rows}):
        differences = []
        cells = sorted({
            (row["mission"], int(row["horizon"]), row["variant"])
            for row in rows if int(row["seed"]) == seed
        })
        for mission, horizon, variant in cells:
            full_key = (seed, mission, horizon, variant, "full_hierarchy")
            other_key = (seed, mission, horizon, variant, other_agent)
            if full_key not in by or other_key not in by:
                continue
            full = by[full_key]["mission_complete"]
            other = by[other_key]["mission_complete"]
            full_value = full if isinstance(full, bool) else full == "True"
            other_value = other if isinstance(other, bool) else other == "True"
            differences.append(float(full_value) - float(other_value))
        if differences:
            seed_means.append(float(np.mean(differences)))
    if not seed_means:
        raise IntegrityError("no complete paired seed clusters")
    return _bootstrap(np.asarray(seed_means), np.random.default_rng(bootstrap_seed), draws)


def _derive(root: Path) -> None:
    raw_files = sorted((root / "raw" / "episodes").glob("*.json"))
    episodes = [json.loads(path.read_text()) for path in raw_files]
    rows = []
    for episode in episodes:
        row = {**episode["row"], **episode["score"], "episode_id": episode["episode_id"]}
        rows.append(row)
    derived = root / "derived"
    if derived.exists():
        shutil.rmtree(derived)
    derived.mkdir()
    fields = list(rows[0])
    with (derived / "episodes.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    cfg = load_config()
    summaries = []
    for agent in cfg["agents"]:
        for variant in cfg["variants"]:
            cell = [r for r in rows if r["agent"] == agent and r["variant"] == variant]
            if cell:
                summaries.append({"agent": agent, "variant": variant, "n": len(cell), "completion": sum(r["mission_complete"] for r in cell) / len(cell), "safety": sum(r["safe"] for r in cell) / len(cell), "progress": sum(r["progress"] for r in cell) / len(cell)})
    contrasts = {}
    for offset, other in enumerate(cfg["agents"][:-1]):
        contrasts[f"full_minus_{other}:completion"] = seed_cluster_contrast(
            rows, other, cfg["bootstrap_draws"], cfg["bootstrap_seed"] + offset,
        )
    heterogeneity = []
    for horizon in cfg["horizons"]:
        for variant in cfg["variants"]:
            cell = [r for r in rows if r["horizon"] == horizon and r["variant"] == variant]
            if cell:
                heterogeneity.append({"horizon": horizon, "variant": variant, "n": len(cell), "completion": sum(r["mission_complete"] for r in cell) / len(cell)})
    _write_json(derived / "analysis.json", {"summary": summaries, "paired_contrasts": contrasts, "heterogeneity": heterogeneity})
    working = next((r for r in rows if r["agent"] == "full_hierarchy" and r["mission_complete"]), rows[0])
    nonworking = next((r for r in rows if r["agent"] == "open_loop" and not r["mission_complete"]), rows[0])
    _write_json(derived / "samples.json", {"rule": "lowest matrix-order qualifying episode", "working": working, "nonworking": nonworking})


def execute(rows: list[dict[str, Any]], output: Path, source_commit: str) -> None:
    if output.exists():
        raise IntegrityError("output exists")
    (output / "raw" / "episodes").mkdir(parents=True)
    graph_rows = []
    for index, row in enumerate(rows):
        episode = run_episode(row)
        episode_id = f"{index:05d}-s{row['seed']}-{row['mission']}-h{row['horizon']}-{row['variant']}-{row['agent']}"
        episode["episode_id"] = episode_id
        _write_json(output / "raw" / "episodes" / f"{episode_id}.json", episode)
        if row["agent"] == load_config()["agents"][0]:
            graph_rows.append({"seed": row["seed"], "mission": row["mission"], "horizon": row["horizon"], "variant": row["variant"], "graph": episode["scenario"]["graph"]})
    (output / "raw" / "graphs.jsonl").write_text("".join(json.dumps(x, sort_keys=True, separators=(",", ":")) + "\n" for x in graph_rows))
    matrix_hash = _sha_bytes(_canonical(rows))
    _write_json(output / "closure.json", {
        "schema": "exp14-evidence-closure-v1", "status": "COMPLETE",
        "source_commit": source_commit, "config_sha256": _sha_file(CONFIG),
        "matrix_sha256": matrix_hash, "matrix_rows": len(rows),
        "seeds": sorted({r["seed"] for r in rows}), "claim_scope": load_config()["claim_scope"],
    })
    _derive(output)
    write_manifest(output)
    verify_manifest(output)


def reconstruct(source: Path, target: Path) -> None:
    verify_manifest(source)
    if target.exists():
        raise IntegrityError("target exists")
    target.mkdir()
    shutil.copytree(source / "raw", target / "raw")
    shutil.copy2(source / "closure.json", target / "closure.json")
    _derive(target)
    write_manifest(target)
    verify_manifest(target)


def reanalyse(source: Path, target: Path, analysis_commit: str) -> None:
    verify_manifest(source)
    if target.exists():
        raise IntegrityError("target exists")
    target.mkdir()
    shutil.copytree(source / "raw", target / "raw")
    prior = json.loads((source / "closure.json").read_text())
    _write_json(target / "closure.json", {
        "schema": "exp14-seed-cluster-analysis-closure-v2",
        "status": "COMPLETE",
        "outcome_source_commit": prior["source_commit"],
        "analysis_commit": analysis_commit,
        "config_sha256": prior["config_sha256"],
        "matrix_sha256": prior["matrix_sha256"],
        "matrix_rows": prior["matrix_rows"],
        "seeds": prior["seeds"],
        "raw_inventory_sha256": _sha_bytes(_canonical(_manifest_entries(source / "raw"))),
        "supersedes_manifest_sha256": _sha_file(source / "manifest.json"),
        "correction": "paired bootstrap resamples seed clusters; one-seed shards have no inferential interval",
        "claim_scope": prior["claim_scope"],
    })
    _derive(target)
    write_manifest(target)
    verify_manifest(target)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    rows = matrix(load_config())
    if args.limit is not None:
        rows = rows[: args.limit]
    execute(rows, args.output, args.source_commit)


if __name__ == "__main__":
    main()
