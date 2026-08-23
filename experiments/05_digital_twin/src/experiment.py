"""Typed four-layer digital twin and deterministic building-planning benchmark."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np


class EvidenceError(ValueError):
    pass


class Mission(str, Enum):
    INSPECT_NEAREST_COOLANT = "INSPECT_NEAREST_COOLANT"
    REACH_PUMP2_WITH_RECHARGE = "REACH_PUMP2_WITH_RECHARGE"
    INSPECT_VALVE7_WITH_ALTERNATE = "INSPECT_VALVE7_WITH_ALTERNATE"
    STORE_CARRIED_TOOL = "STORE_CARRIED_TOOL"
    REPLAN_ON_RESTRICTION = "REPLAN_ON_RESTRICTION"


class Variant(str, Enum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


@dataclass(frozen=True)
class GeometryEntity:
    entity_id: str
    frame: str
    x_m: float
    y_m: float
    radius_m: float


@dataclass(frozen=True)
class GeometryLayer:
    revision: str
    entities: tuple[GeometryEntity, ...]


@dataclass(frozen=True)
class TopologyEdge:
    door_id: str
    room_a: str
    room_b: str
    cost_m: float


@dataclass(frozen=True)
class TopologyLayer:
    revision: str
    edges: tuple[TopologyEdge, ...]


@dataclass(frozen=True)
class SemanticEntity:
    entity_id: str
    class_id: str
    aliases: tuple[str, ...]
    room_id: str
    affordances: tuple[str, ...]
    durable_restricted: bool


@dataclass(frozen=True)
class SemanticLayer:
    revision: str
    entities: tuple[SemanticEntity, ...]
    restricted_rooms: tuple[str, ...]


@dataclass(frozen=True)
class BeliefFact:
    subject_id: str
    predicate: str
    value: str
    confidence: float
    observed_tick: int
    provenance: str
    visible: bool
    uncertainty: float


@dataclass(frozen=True)
class LiveBelief:
    revision: str
    facts: tuple[BeliefFact, ...]


@dataclass(frozen=True)
class EpisodicEvent:
    tick: int
    event_type: str
    subject_id: str
    detail: str


@dataclass(frozen=True)
class WorldFact:
    subject_id: str
    predicate: str
    value: str


@dataclass(frozen=True)
class TwinCase:
    seed: int
    mission: Mission
    instruction: str
    geometry: GeometryLayer
    topology: TopologyLayer
    semantics: SemanticLayer
    belief: LiveBelief
    history: tuple[EpisodicEvent, ...]
    dynamic_events: tuple[EpisodicEvent, ...]
    actual_facts: tuple[WorldFact, ...]
    case_sha256: str


@dataclass(frozen=True)
class Outcome:
    case_sha256: str
    seed: int
    mission: Mission
    variant: Variant
    target_id: str | None
    initial_route: tuple[str, ...]
    final_route: tuple[str, ...]
    actions: tuple[str, ...]
    events_seen: tuple[EpisodicEvent, ...]
    success: bool
    terminal_reason: str
    route_cost_m: float
    forbidden_region_violations: int
    invalid_affordance_choices: int
    stale_belief_failures: int
    invalid_initial_plan: bool
    replanned: bool
    planning_operations: int
    replanning_latency_us: int
    semantic_query_count: int
    geometry_query_count: int
    context_fact_count: int
    outcome_sha256: str


ROOMS = ("Lobby", "CorridorA", "PumpRoom", "ElectricalRoom", "RestrictedLab")
BASE_POSITIONS = {"Lobby": (0.0, 0.0), "CorridorA": (5.0, 0.0), "PumpRoom": (10.0, 0.0), "ElectricalRoom": (5.0, 5.0), "RestrictedLab": (10.0, 5.0)}
EDGE_ROWS = (("Door1", "Lobby", "CorridorA", 5.0), ("Door2", "CorridorA", "PumpRoom", 5.0), ("Door3", "CorridorA", "RestrictedLab", 6.0), ("Door4", "ElectricalRoom", "RestrictedLab", 5.0), ("Door5", "CorridorA", "ElectricalRoom", 5.0), ("Door6", "Lobby", "ElectricalRoom", 7.0))


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _fact_map(rows: Iterable[WorldFact | BeliefFact]) -> dict[tuple[str, str], str]:
    return {(row.subject_id, row.predicate): row.value for row in rows}


def _mission_instruction(mission: Mission, instruction_variant: int) -> str:
    base = {
        Mission.INSPECT_NEAREST_COOLANT: "Inspect the nearest coolant valve without entering a restricted room.",
        Mission.REACH_PUMP2_WITH_RECHARGE: "Reach Pump 2, but recharge first if estimated battery is insufficient.",
        Mission.INSPECT_VALVE7_WITH_ALTERNATE: "Inspect Valve 7; if Door 3 is unavailable, use another route.",
        Mission.STORE_CARRIED_TOOL: "Find a safe location for the carried tool.",
        Mission.REPLAN_ON_RESTRICTION: "Inspect Valve 7 and replan if a room becomes restricted.",
    }[mission]
    return base if instruction_variant == 0 else base.replace("Inspect", "Safely inspect")


def make_case(seed: int, mission: Mission) -> TwinCase:
    if type(seed) is not int or seed < 0 or not isinstance(mission, Mission):
        raise ValueError("seed and mission are closed")
    rng = np.random.Generator(np.random.PCG64(int.from_bytes(hashlib.sha256(canonical(["exp05", seed, mission.value])).digest()[:8], "big")))
    positions = {room: (x + float(rng.uniform(-0.25, 0.25)), y + float(rng.uniform(-0.25, 0.25))) for room, (x, y) in BASE_POSITIONS.items()}
    geometry_rows = [GeometryEntity(room, "Floor1", *positions[room], 1.5) for room in ROOMS]
    asset_rows = (
        ("Valve3", "PumpRoom"), ("Valve7", "RestrictedLab"), ("Pump2", "PumpRoom"),
        ("ChargerLobby", "Lobby"), ("ChargerElectrical", "ElectricalRoom"),
        ("ToolCabinetLobby", "Lobby"), ("ToolCabinetElectrical", "ElectricalRoom"),
        ("InspectionPump", "PumpRoom"), ("InspectionLab", "RestrictedLab"), ("Blocker1", "CorridorA"),
    )
    for entity_id, room in asset_rows:
        x, y = positions[room]; geometry_rows.append(GeometryEntity(entity_id, room, x + float(rng.uniform(-0.35, 0.35)), y + float(rng.uniform(-0.35, 0.35)), 0.2))
    topology = TopologyLayer("exp05-topology-v1", tuple(TopologyEdge(*row) for row in EDGE_ROWS))
    semantics = SemanticLayer("exp05-semantics-v1", (
        SemanticEntity("Valve3", "COOLANT_VALVE", ("coolant valve", "valve 3"), "PumpRoom", ("INSPECT",), False),
        SemanticEntity("Valve7", "COOLANT_VALVE", ("coolant valve", "valve 7"), "RestrictedLab", ("INSPECT",), True),
        SemanticEntity("Pump2", "PUMP", ("pump 2",), "PumpRoom", ("REACH",), False),
        SemanticEntity("ChargerLobby", "CHARGER", ("charger",), "Lobby", ("RECHARGE",), False),
        SemanticEntity("ChargerElectrical", "CHARGER", ("charger",), "ElectricalRoom", ("RECHARGE",), False),
        SemanticEntity("ToolCabinetLobby", "TOOL_STORAGE", ("tool cabinet",), "Lobby", ("STORE_TOOL",), False),
        SemanticEntity("ToolCabinetElectrical", "TOOL_STORAGE", ("tool cabinet",), "ElectricalRoom", ("STORE_TOOL",), False),
    ), ("RestrictedLab",))
    actual_door3 = bool(rng.integers(0, 2)); actual_door2 = bool(rng.integers(0, 4) != 0)
    battery = float(rng.uniform(0.12, 0.85)); valve3_stale = bool(rng.integers(0, 3) == 0)
    lobby_storage = bool(rng.integers(0, 2)); electrical_storage = bool(rng.integers(0, 4) != 0)
    blocker_door = "Door5" if bool(rng.integers(0, 3) == 0) else "NONE"
    belief_door3 = actual_door3 if seed % 3 else True
    door3_confidence = 0.55 if belief_door3 != actual_door3 else 0.95
    belief = LiveBelief("exp05-belief-v1", tuple(sorted((
        BeliefFact("Door2", "AVAILABLE", str(actual_door2).lower(), 0.95, 0, "door-monitor", True, 0.02),
        BeliefFact("Door3", "AVAILABLE", str(belief_door3).lower(), door3_confidence, -1 if door3_confidence < 0.8 else 0, "door-monitor", True, 1.0-door3_confidence),
        BeliefFact("Door5", "AVAILABLE", str(blocker_door != "Door5").lower(), 0.90, 0, "route-monitor", True, 0.10),
        BeliefFact("Robot", "BATTERY", f"{battery:.17g}", 0.90, 0, "battery-estimator", True, 0.08),
        BeliefFact("Valve3", "POSE_STALE", str(valve3_stale).lower(), 0.90, 0, "asset-observer", not valve3_stale, 0.10 if not valve3_stale else 0.75),
        BeliefFact("ToolCabinetLobby", "SAFE_AVAILABLE", str(lobby_storage).lower(), 0.90, 0, "storage-monitor", True, 0.10),
        BeliefFact("ToolCabinetElectrical", "SAFE_AVAILABLE", str(electrical_storage).lower(), 0.90, 0, "storage-monitor", True, 0.10),
        BeliefFact("Pump2", "OPERATIONAL", str(bool(rng.integers(0, 5) != 0)).lower(), 0.85, 0, "asset-monitor", True, 0.15),
    ), key=lambda row: (row.subject_id, row.predicate))))
    history = []
    if not actual_door3 and belief_door3:
        history.append(EpisodicEvent(-2, "EDGE_FAILED", "Door3", "door failed on the previous Valve7 attempt"))
    if not lobby_storage:
        history.append(EpisodicEvent(-3, "AFFORDANCE_FAILED", "ToolCabinetLobby", "cabinet was occupied"))
    dynamic = []
    if mission is Mission.REPLAN_ON_RESTRICTION:
        dynamic.append(EpisodicEvent(1, "ROOM_RESTRICTED", "CorridorA", "access policy changed during execution"))
    if blocker_door != "NONE":
        dynamic.append(EpisodicEvent(0, "ROUTE_BLOCKED", blocker_door, "movable blocker obstructs door"))
    if seed % 5 == 0:
        dynamic.append(EpisodicEvent(0, "INSTRUCTION_CHANGED", mission.value, "safety qualifier added"))
    actual = tuple(sorted((
        WorldFact("Door2", "AVAILABLE", str(actual_door2).lower()),
        WorldFact("Door3", "AVAILABLE", str(actual_door3).lower()),
        WorldFact("Door5", "AVAILABLE", str(blocker_door != "Door5").lower()),
        WorldFact("Robot", "BATTERY", f"{battery:.17g}"),
        WorldFact("Valve3", "POSE_STALE", str(valve3_stale).lower()),
        WorldFact("ToolCabinetLobby", "SAFE_AVAILABLE", str(lobby_storage).lower()),
        WorldFact("ToolCabinetElectrical", "SAFE_AVAILABLE", str(electrical_storage).lower()),
    ), key=lambda row: (row.subject_id, row.predicate)))
    provisional = TwinCase(seed, mission, _mission_instruction(mission, seed % 2), GeometryLayer("exp05-geometry-v1", tuple(geometry_rows)), topology, semantics, belief, tuple(history), tuple(sorted(dynamic, key=lambda row: (row.tick, row.event_type, row.subject_id))), actual, "")
    return TwinCase(**(asdict(provisional) | {"mission": mission, "geometry": provisional.geometry, "topology": topology, "semantics": semantics, "belief": belief, "history": tuple(history), "dynamic_events": provisional.dynamic_events, "actual_facts": actual, "case_sha256": digest(asdict(provisional) | {"case_sha256": None})}))


def _entity(case: TwinCase, entity_id: str) -> SemanticEntity:
    return next(row for row in case.semantics.entities if row.entity_id == entity_id)


def _position(case: TwinCase, entity_id: str) -> tuple[float, float]:
    row = next(item for item in case.geometry.entities if item.entity_id == entity_id)
    return row.x_m, row.y_m


def _route(case: TwinCase, target_room: str, variant: Variant, unavailable: set[str], restricted: set[str]) -> tuple[tuple[str, ...], float, int]:
    if variant is Variant.T0:
        x0, y0 = _position(case, "Lobby"); x1, y1 = _position(case, target_room)
        return ("Lobby", target_room), math.hypot(x1-x0, y1-y0), 1
    adjacency: dict[str, list[tuple[str, str, float]]] = {room: [] for room in ROOMS}
    for edge in case.topology.edges:
        if edge.door_id in unavailable or edge.room_a in restricted or edge.room_b in restricted:
            continue
        adjacency[edge.room_a].append((edge.room_b, edge.door_id, edge.cost_m)); adjacency[edge.room_b].append((edge.room_a, edge.door_id, edge.cost_m))
    frontier = [(0.0, ("Lobby",), "Lobby")]; seen: dict[str, float] = {}; operations = 0
    while frontier:
        frontier.sort(key=lambda row: (row[0], row[1])); cost, path, room = frontier.pop(0); operations += 1
        if room in seen and seen[room] <= cost: continue
        seen[room] = cost
        if room == target_room: return path, cost, operations
        for neighbor, _, edge_cost in adjacency[room]: frontier.append((cost+edge_cost, (*path, neighbor), neighbor))
    return (), math.inf, operations


def _door_for(case: TwinCase, a: str, b: str) -> str:
    return next(edge.door_id for edge in case.topology.edges if {edge.room_a, edge.room_b} == {a, b})


def evaluate(case: TwinCase, variant: Variant) -> Outcome:
    if not isinstance(case, TwinCase) or not isinstance(variant, Variant): raise ValueError("closed case/variant required")
    actual = _fact_map(case.actual_facts); belief = _fact_map(case.belief.facts)
    semantic_queries = 0; geometry_queries = 1; invalid_affordance = 0; stale = 0; actions: list[str] = []; target: str | None
    if case.mission is Mission.INSPECT_NEAREST_COOLANT:
        if variant in {Variant.T0, Variant.T1}:
            target = min((row.entity_id for row in case.geometry.entities if row.entity_id not in ROOMS), key=lambda entity: math.dist(_position(case, "Lobby"), _position(case, entity)))
            invalid_affordance = int(target not in {"Valve3", "Valve7"})
        else:
            semantic_queries += 1; target = "Valve3"
            if variant in {Variant.T3, Variant.T4} and belief[("Valve3", "POSE_STALE")] == "true": actions.append("REFRESH_GEOMETRY:Valve3"); geometry_queries += 1
            elif actual[("Valve3", "POSE_STALE")] == "true": stale = 1
    elif case.mission is Mission.REACH_PUMP2_WITH_RECHARGE:
        target = "Pump2"
        if variant in {Variant.T2, Variant.T3, Variant.T4}: semantic_queries += 1
        if variant in {Variant.T3, Variant.T4} and float(belief[("Robot", "BATTERY")]) < 0.42: actions.append("RECHARGE:ChargerLobby")
    elif case.mission in {Mission.INSPECT_VALVE7_WITH_ALTERNATE, Mission.REPLAN_ON_RESTRICTION}:
        target = "Valve7"; semantic_queries += int(variant in {Variant.T2, Variant.T3, Variant.T4})
    else:
        if variant in {Variant.T0, Variant.T1}:
            target = "ChargerLobby"; invalid_affordance = 1
        elif variant is Variant.T2:
            semantic_queries += 1; target = "ToolCabinetLobby"
        else:
            semantic_queries += 1
            candidates = [entity.entity_id for entity in case.semantics.entities if "STORE_TOOL" in entity.affordances and belief[(entity.entity_id, "SAFE_AVAILABLE")] == "true"]
            target = candidates[0] if candidates else None
    if target is None:
        return _finish(case, variant, target, (), (), tuple(actions), (), False, "NO_SAFE_TARGET", 0.0, 0, invalid_affordance, stale, True, False, 1, 0, semantic_queries, geometry_queries)
    target_room = _entity(case, target).room_id if any(row.entity_id == target for row in case.semantics.entities) else next(row.frame for row in case.geometry.entities if row.entity_id == target)
    unavailable: set[str] = set(); restricted: set[str] = set()
    if variant in {Variant.T2, Variant.T3, Variant.T4}: restricted.update(case.semantics.restricted_rooms)
    if case.mission in {Mission.INSPECT_VALVE7_WITH_ALTERNATE, Mission.REPLAN_ON_RESTRICTION}:
        restricted.discard("RestrictedLab")
    if variant in {Variant.T3, Variant.T4}:
        unavailable.update(subject for (subject, predicate), value in belief.items() if predicate == "AVAILABLE" and value == "false")
    if variant is Variant.T4:
        unavailable.update(row.subject_id for row in case.history if row.event_type == "EDGE_FAILED")
    initial, initial_cost, operations = _route(case, target_room, variant, unavailable, restricted)
    geometry_collision = variant is Variant.T0 and target_room != "Lobby" and not any({edge.room_a, edge.room_b} == {"Lobby", target_room} for edge in case.topology.edges)
    invalid_initial = not initial or geometry_collision
    actual_unavailable = {subject for (subject, predicate), value in actual.items() if predicate == "AVAILABLE" and value == "false"}
    actual_unavailable.update(row.subject_id for row in case.dynamic_events if row.event_type == "ROUTE_BLOCKED")
    if initial and variant is not Variant.T0:
        invalid_initial |= any(_door_for(case, a, b) in actual_unavailable for a, b in zip(initial, initial[1:]))
    final = initial; replanned = False; events_seen: list[EpisodicEvent] = []; replan_ops = 0
    dynamic_restriction = next((row for row in case.dynamic_events if row.event_type == "ROOM_RESTRICTED"), None)
    if dynamic_restriction and len(final) > 1:
        events_seen.append(dynamic_restriction)
        if variant in {Variant.T3, Variant.T4}:
            restricted.add(dynamic_restriction.subject_id); final, _, replan_ops = _route(case, target_room, variant, unavailable, restricted); replanned = True
        elif dynamic_restriction.subject_id in final:
            invalid_initial = True
    if final and variant is not Variant.T0:
        blocked = next((_door_for(case, a, b) for a, b in zip(final, final[1:]) if _door_for(case, a, b) in actual_unavailable), None)
        if blocked and variant in {Variant.T3, Variant.T4}:
            events_seen.append(EpisodicEvent(1, "EDGE_FAILED", blocked, "execution observed unavailable edge")); unavailable.add(blocked); final, _, extra = _route(case, target_room, variant, unavailable, restricted); replan_ops += extra; replanned = True
    final_cost = initial_cost if variant is Variant.T0 else 0.0 if len(final) < 2 else sum(next(edge.cost_m for edge in case.topology.edges if {edge.room_a, edge.room_b} == {a, b}) for a, b in zip(final, final[1:]))
    forbidden_rooms = set(case.semantics.restricted_rooms)
    if case.mission in {Mission.INSPECT_VALVE7_WITH_ALTERNATE, Mission.REPLAN_ON_RESTRICTION}:
        forbidden_rooms.discard("RestrictedLab")
    if dynamic_restriction is not None:
        forbidden_rooms.add(dynamic_restriction.subject_id)
    forbidden = int(any(room in forbidden_rooms for room in final[1:]))
    blocked_remaining = geometry_collision or bool(final and variant is not Variant.T0 and any(_door_for(case, a, b) in actual_unavailable for a, b in zip(final, final[1:])))
    battery_failure = case.mission is Mission.REACH_PUMP2_WITH_RECHARGE and float(actual[("Robot", "BATTERY")]) < 0.42 and not any(action.startswith("RECHARGE") for action in actions)
    storage_failure = case.mission is Mission.STORE_CARRIED_TOOL and (target not in {"ToolCabinetLobby", "ToolCabinetElectrical"} or actual.get((target, "SAFE_AVAILABLE")) != "true")
    success = bool(final and not invalid_affordance and not stale and not forbidden and not blocked_remaining and not battery_failure and not storage_failure)
    reason = "SUCCESS" if success else "NO_ROUTE" if not final else "INVALID_AFFORDANCE" if invalid_affordance else "STALE_GEOMETRY" if stale else "FORBIDDEN_REGION" if forbidden else "GEOMETRY_COLLISION" if geometry_collision else "BLOCKED_EDGE" if blocked_remaining else "BATTERY_EXHAUSTED" if battery_failure else "UNSAFE_STORAGE"
    actions.extend(f"TRAVERSE:{room}" for room in final[1:]); actions.append(f"ACT:{target}" if success else f"FAIL:{reason}")
    return _finish(case, variant, target, initial, final, tuple(actions), tuple(events_seen), success, reason, final_cost if math.isfinite(final_cost) else initial_cost, forbidden, invalid_affordance, stale, invalid_initial, replanned, operations+replan_ops, replan_ops*7, semantic_queries, geometry_queries)


def _finish(case: TwinCase, variant: Variant, target: str | None, initial: tuple[str, ...], final: tuple[str, ...], actions: tuple[str, ...], events: tuple[EpisodicEvent, ...], success: bool, reason: str, cost: float, forbidden: int, invalid_affordance: int, stale: int, invalid_initial: bool, replanned: bool, operations: int, latency: int, semantic_queries: int, geometry_queries: int) -> Outcome:
    context = {Variant.T0: len(case.geometry.entities), Variant.T1: len(case.geometry.entities)+len(case.topology.edges), Variant.T2: len(case.semantics.entities)+len(case.topology.edges), Variant.T3: len(case.belief.facts)+len(case.semantics.entities), Variant.T4: len(case.belief.facts)+len(case.semantics.entities)+len(case.history)}[variant]
    fields = (case.case_sha256, case.seed, case.mission, variant, target, initial, final, actions, events, success, reason, float(cost), forbidden, invalid_affordance, stale, invalid_initial, replanned, operations, latency, semantic_queries, geometry_queries, context)
    wire = [value.value if isinstance(value, Enum) else [asdict(x) for x in value] if value and isinstance(value, tuple) and isinstance(value[0], EpisodicEvent) else value for value in fields]
    return Outcome(*fields, digest(wire))


def _wilson(successes: int, total: int) -> tuple[float, float]:
    z=1.959963984540054;p=successes/total;d=1+z*z/total;c=(p+z*z/(2*total))/d;h=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/d;return c-h,c+h


def _derived(outcomes: Sequence[Outcome], manifest_sha256: str) -> dict[str, bytes]:
    metrics=[]
    for variant in Variant:
        rows=[row for row in outcomes if row.variant is variant];successes=sum(row.success for row in rows);lo,hi=_wilson(successes,len(rows))
        metrics.append({"variant":variant.value,"cases":len(rows),"mission_success_fraction":successes/len(rows),"success_wilson95":[lo,hi],"mean_route_cost_m":sum(row.route_cost_m for row in rows)/len(rows),"forbidden_region_violations":sum(row.forbidden_region_violations for row in rows),"invalid_affordance_choices":sum(row.invalid_affordance_choices for row in rows),"stale_belief_failures":sum(row.stale_belief_failures for row in rows),"invalid_initial_plans":sum(row.invalid_initial_plan for row in rows),"replans":sum(row.replanned for row in rows),"mean_replanning_latency_us":sum(row.replanning_latency_us for row in rows)/len(rows),"semantic_queries":sum(row.semantic_query_count for row in rows),"geometry_queries":sum(row.geometry_query_count for row in rows),"mean_context_facts":sum(row.context_fact_count for row in rows)/len(rows)})
    ordered=sorted(outcomes,key=lambda row:(row.variant.value,row.mission.value,row.seed));samples=[]
    for label,value in (("WORKING",True),("NONWORKING",False)):
        row=next(item for item in ordered if item.success is value and item.variant in {Variant.T3,Variant.T4});samples.append({"label":label,"seed":row.seed,"mission":row.mission.value,"variant":row.variant.value,"case_sha256":row.case_sha256,"outcome_sha256":row.outcome_sha256,"selection":"FIRST_CANONICAL_STRONG_TWIN"})
    return {"metrics.json":canonical({"schema_version":"exp05-metrics-v1","rows":metrics}),"sample-index.json":canonical({"schema_version":"exp05-samples-v1","samples":samples}),"recipe.json":canonical({"schema_version":"exp05-recipe-v1","renderer":"experiment.py:reconstruct","manifest_sha256":manifest_sha256,"sort":["seed","mission","variant"],"uncertainty":"Wilson score 95% over seed-by-mission cases"})}


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as stream: stream.write(payload);stream.flush();os.fsync(stream.fileno())


def run_matrix(output: Path, *, seeds: Iterable[int]) -> None:
    selected=tuple(seeds)
    if output.exists() or not selected or len(set(selected))!=len(selected): raise EvidenceError("absent output and unique seeds required")
    cases=[make_case(seed,mission) for seed in sorted(selected) for mission in Mission];outcomes=[evaluate(case,variant) for case in cases for variant in Variant]
    raw=output/"raw";derived=output/"derived";raw.mkdir(parents=True);derived.mkdir()
    case_bytes=b"".join(canonical(asdict(row)) for row in cases);outcome_bytes=b"".join(canonical(asdict(row)) for row in outcomes);_write(raw/"cases.jsonl",case_bytes);_write(raw/"outcomes.jsonl",outcome_bytes)
    members=[raw/"cases.jsonl",raw/"outcomes.jsonl"];manifest={"schema_version":"exp05-manifest-v1","status":"PRELIMINARY_ENGINEERING_ONLY","seed_count":len(selected),"case_count":len(cases),"outcome_count":len(outcomes),"files":[{"path":path.name,"bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()} for path in members]};manifest_bytes=canonical(manifest);_write(raw/"manifest.json",manifest_bytes)
    for name,payload in _derived(outcomes,hashlib.sha256(manifest_bytes).hexdigest()).items():_write(derived/name,payload)


def reconstruct(raw: Path, output: Path) -> None:
    if output.exists() or not raw.is_dir() or {path.name for path in raw.iterdir()}!={"cases.jsonl","outcomes.jsonl","manifest.json"}:raise EvidenceError("exact raw root and absent output required")
    manifest_bytes=(raw/"manifest.json").read_bytes();manifest=json.loads(manifest_bytes)
    if canonical(manifest)!=manifest_bytes:raise EvidenceError("manifest is noncanonical")
    for row in manifest["files"]:
        path=raw/row["path"]
        if path.stat().st_size!=row["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest()!=row["sha256"]:raise EvidenceError("raw hash mismatch")
    case_rows=[json.loads(line) for line in (raw/"cases.jsonl").read_text().splitlines()];outcome_rows=[json.loads(line) for line in (raw/"outcomes.jsonl").read_text().splitlines()]
    cases=[make_case(row["seed"],Mission(row["mission"])) for row in case_rows]
    if b"".join(canonical(asdict(row)) for row in cases)!=(raw/"cases.jsonl").read_bytes():raise EvidenceError("case inputs do not regenerate")
    outcomes=[evaluate(case,variant) for case in cases for variant in Variant]
    if b"".join(canonical(asdict(row)) for row in outcomes)!=(raw/"outcomes.jsonl").read_bytes():raise EvidenceError("plans/outcomes do not regenerate")
    if manifest["case_count"]!=len(cases) or manifest["outcome_count"]!=len(outcomes):raise EvidenceError("manifest counts drifted")
    output.mkdir()
    for name,payload in _derived(outcomes,hashlib.sha256(manifest_bytes).hexdigest()).items():_write(output/name,payload)
