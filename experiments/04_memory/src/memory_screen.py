"""Minimal, nonconfirmatory Experiment 04 memory-architecture screen.

The runner consumes observations only.  Scorer truth is kept in a separate artifact
and is joined only after a variant has emitted its answers and decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np


VARIANTS = ("M0", "M1", "M2", "M3", "M4", "M5", "M6", "H0", "V0")
SEEDS = (20260891, 20260892, 20260893, 20260894)
FUZZY_SEED_SLOTS = (1, 3)
FUZZY_ALIAS_TOKENS = tuple(
    hashlib.sha256(f"exp04-fuzzy-v3:{index}".encode("ascii")).hexdigest()[:12]
    for index in range(16)
)
QUERY_IDS = (
    "LOCATION", "LAST_OBSERVED", "POSE_USABLE", "PRIOR_ATTEMPT",
    "LAST_FAILURE_REASON", "REACHABLE_VALVE", "CHANGES_SINCE",
    "ROUTE_BLOCKER", "DUPLICATE_IDENTITY", "CONFLICTS_UNKNOWN",
)
BASE_CONFIG = {
    "confidence_threshold": 0.70, "context_bytes": 4096, "context_facts": 16,
    "contradiction_delta": 0.20, "hash_dimension": 256, "retained_event_cap": 128,
    "retained_input_bytes": 65536, "retained_input_facts": 256, "retrieval_r": 8,
    "ttl_multiplier": 1.0,
}
ACTION_QUERIES = {"POSE_USABLE", "REACHABLE_VALVE", "ROUTE_BLOCKER", "DUPLICATE_IDENTITY"}
IDENTITY_QUERIES = {"REACHABLE_VALVE", "DUPLICATE_IDENTITY"}
QUERY_RETRIEVAL_TEXT = {
    "LOCATION": "location entity tool 0001 predicate in on near held by observed at",
    "LAST_OBSERVED": "last observed entity valve 0001 predicate observed at pose visibility",
    "POSE_USABLE": "pose usable entity asset 0002 now predicate pose visibility observed at",
    "PRIOR_ATTEMPT": "prior attempt entity door 0003 action open door predicate attempt outcome",
    "LAST_FAILURE_REASON": "last failure reason entity door 0003 action open door predicate attempt outcome",
    "REACHABLE_VALVE": "reachable valve robot 0001 valve class predicate reachable restricted by blocks connects affordance operational state",
    "CHANGES_SINCE": "changes since room 0004 predicate observed at in on blocks connects reachable restricted by pose visibility door state battery level operational state attempt outcome",
    "ROUTE_BLOCKER": "route blocker robot 0001 destination room 0003 predicate connects blocks reachable restricted by door state",
    "DUPLICATE_IDENTITY": "duplicate identity label service valve predicate label alias entity class observed at visibility",
    "CONFLICTS_UNKNOWN": "conflicts unknown entity asset 0001 predicate operational state",
}


class ScreenError(ValueError):
    pass


@dataclass(frozen=True)
class Fact:
    fact_id: str
    subject_id: str
    predicate: str
    value: str
    observed_tick: int
    received_tick: int
    confidence: float
    status: str = "asserted"

    def row(self) -> dict[str, object]:
        return {
            "confidence": self.confidence,
            "fact_id": self.fact_id,
            "observed_tick": self.observed_tick,
            "predicate": self.predicate,
            "received_tick": self.received_tick,
            "source_event_id": f"event/{self.fact_id}",
            "status": self.status,
            "subject_id": self.subject_id,
            "value": self.value,
        }


@dataclass(frozen=True)
class SeedWorld:
    seed: int
    primary_valve_id: str
    alternate_valve_id: str
    restricted_room_id: str
    pose_age_ticks: int
    failure_reason: str
    blocker_id: str
    changed_tool_id: str
    changed_asset_id: str
    duplicate_reverse_order: bool
    operational_confidence: float
    failed_confidence: float


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _jsonl(rows: Sequence[Mapping[str, object]]) -> bytes:
    return b"".join(_canonical(row) for row in rows)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fact(case: int, suffix: str, subject: str, predicate: str, value: str, observed: int, received: int, confidence: float, status: str = "asserted") -> dict[str, object]:
    return Fact(f"{case:02d}-{suffix}", subject, predicate, value, observed, received, confidence, status).row()


def _world_for_seed(seed: int) -> SeedWorld:
    if type(seed) is not int or seed < 0:
        raise ScreenError("seed must be a nonnegative integer")
    rng = np.random.Generator(np.random.PCG64(seed))
    identities = rng.choice(np.arange(100, 999), size=6, replace=False)
    slot = SEEDS.index(seed) if seed in SEEDS else seed % 4
    confidence_pairs = ((.84, .81), (.84, .56), (.56, .84), (.56, .54))
    operational, failed = confidence_pairs[slot]
    return SeedWorld(
        seed=seed,
        primary_valve_id=f"valve/{int(identities[0]):04d}",
        alternate_valve_id=f"valve/{int(identities[1]):04d}",
        restricted_room_id="room/0003" if slot % 2 == 0 else "room/0004",
        pose_age_ticks=(1, 2, 3, 1)[slot],
        failure_reason=("BLOCKED", "JAMMED", "OBSTRUCTED", "LOCKED")[slot],
        blocker_id=f"door/{int(identities[2]):04d}",
        changed_tool_id=f"tool/{int(identities[3]):04d}",
        changed_asset_id=f"asset/{int(identities[4]):04d}",
        duplicate_reverse_order=bool(slot % 2),
        operational_confidence=operational,
        failed_confidence=failed,
    )


def _truth_for_world(world: SeedWorld) -> dict[str, tuple[str, str]]:
    reachable = world.alternate_valve_id if world.restricted_room_id == "room/0003" else world.primary_valve_id
    if world.pose_age_ticks >= 2:
        pose = ("STALE", "RESCAN")
    else:
        pose = ("USABLE", "ACT")
    operational = world.operational_confidence >= float(BASE_CONFIG["confidence_threshold"])
    failed = world.failed_confidence >= float(BASE_CONFIG["confidence_threshold"])
    if operational and failed:
        conflict = ("CONTRADICTED", "REPORT_UNKNOWN")
    elif operational:
        conflict = ("OPERATIONAL", "ACT")
    elif failed:
        conflict = ("FAILED", "ACT")
    else:
        conflict = ("UNKNOWN", "REPORT_UNKNOWN")
    return {
        "LOCATION": ("UNKNOWN", "RESCAN"),
        "LAST_OBSERVED": (f"tick/{world.seed % 17}", "REPORT"),
        "POSE_USABLE": pose,
        "PRIOR_ATTEMPT": ("YES", "REPORT"),
        "LAST_FAILURE_REASON": (world.failure_reason, "REPORT"),
        "REACHABLE_VALVE": (reachable, "CHOOSE_ALTERNATIVE"),
        "CHANGES_SINCE": (f"{world.changed_tool_id}:ON:{world.changed_asset_id}", "REPORT"),
        "ROUTE_BLOCKER": (world.blocker_id, "CHOOSE_ALTERNATIVE"),
        "DUPLICATE_IDENTITY": ("AMBIGUOUS", "REIDENTIFY"),
        "CONFLICTS_UNKNOWN": conflict,
    }


def generate_seed(seed: int) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Derive observations and isolated scorer truth independently from one seed world."""
    world = _world_for_seed(seed)
    rng = np.random.Generator(np.random.PCG64(seed ^ 0x04A11CE))
    delays = rng.choice(np.array((0, 1)), size=10, p=(0.5, 0.5))
    last_seen = f"tick/{world.seed % 17}"
    seed_slot = SEEDS.index(seed) if seed in SEEDS else seed % 4
    if seed_slot in FUZZY_SEED_SLOTS:
        aliases = [
            _fact(8, f"{world.seed}-p{index:02d}", world.primary_valve_id, "ALIAS", f"service valve unit {index}", 1, 2, .90)
            for index in range(8)
        ] + [
            _fact(8, f"{world.seed}-z{index:02d}", world.alternate_valve_id, "ALIAS", token, 1, 2, .90)
            for index, token in enumerate(FUZZY_ALIAS_TOKENS)
        ]
    else:
        aliases = [
            _fact(8, f"{world.seed}-a", world.primary_valve_id, "ALIAS", "service valve", 1, 2, .90),
            _fact(8, f"{world.seed}-b", world.alternate_valve_id, "ALIAS", "service valve", 1, 2, .90),
        ]
        if world.duplicate_reverse_order:
            aliases.reverse()
    definitions = (
        ("LOCATION", [_fact(0, "base", "tool/0001", "IN", "room/0001", 0, 0, .90)], [], "UNKNOWN", "RESCAN"),
        ("LAST_OBSERVED", [_fact(1, "seen", world.primary_valve_id, "OBSERVED_AT", last_seen, 0, 0, .90)], [_fact(1, "occ", world.primary_valve_id, "VISIBILITY", "OCCLUDED", 1, 2, .95)], last_seen, "REPORT"),
        ("POSE_USABLE", [_fact(2, "pose", "asset/0002", "POSE", "10.0,0.0,0.0", 0, 0, .90)], [], "", ""),
        ("PRIOR_ATTEMPT", [], [_fact(3, "attempt", world.blocker_id, "ATTEMPT_OUTCOME", f"OPEN_DOOR:FAILED:{world.failure_reason}", 1, 2, .90)], "", ""),
        ("LAST_FAILURE_REASON", [], [_fact(4, "failure", world.blocker_id, "ATTEMPT_OUTCOME", f"OPEN_DOOR:FAILED:{world.failure_reason}", 1, 2, .90)], "", ""),
        ("REACHABLE_VALVE", [
            _fact(5, "v3", world.primary_valve_id, "IN", "room/0003", 0, 0, .90),
            _fact(5, "v7", world.alternate_valve_id, "IN", "room/0004", 0, 0, .90),
        ], [_fact(5, "restrict", world.restricted_room_id, "RESTRICTED_BY", "restriction/0001", 1, 2, .90)], "", ""),
        ("CHANGES_SINCE", [], [_fact(6, "placed", world.changed_tool_id, "ON", world.changed_asset_id, 1, 2, .90)], "", ""),
        ("ROUTE_BLOCKER", [_fact(7, "edge", world.blocker_id, "CONNECTS", "room/0002|room/0003", 0, 0, .90)], [_fact(7, "blocked", world.blocker_id, "DOOR_STATE", "BLOCKED", 1, 2, .90)], "", ""),
        ("DUPLICATE_IDENTITY", [], aliases, "", ""),
        ("CONFLICTS_UNKNOWN", [], [
            _fact(9, "ok", "asset/0001", "OPERATIONAL_STATE", "OPERATIONAL", 1, 2, world.operational_confidence, "asserted"),
            _fact(9, "bad", "asset/0001", "OPERATIONAL_STATE", "FAILED", 1, 2, world.failed_confidence, "contradicted"),
        ], "", ""),
    )
    truth_map = _truth_for_world(world)
    observations: list[dict[str, object]] = []
    truths: list[dict[str, object]] = []
    for index, (query, baseline, delivered, _, _) in enumerate(definitions):
        received_tick = 2 + int(delays[index])
        adjusted = [dict(row, received_tick=received_tick) for row in delivered]
        query_tick = world.pose_age_ticks if query == "POSE_USABLE" else received_tick
        observations.append({
            "baseline_facts": baseline,
            "case_id": f"case/{index:02d}",
            "delivered_facts": adjusted,
            "delivery_delay_ticks": int(delays[index]),
            "query_id": query,
            "query_tick": query_tick,
            "schema_version": "exp04-engineering-observation-v3",
            "seed": seed,
        })
        answer, decision = truth_map[query]
        truths.append({"case_id": f"case/{index:02d}", "expected_answer": answer,
                       "expected_decision": decision, "query_id": query,
                       "schema_version": "exp04-engineering-scorer-truth-v3", "seed": seed})
    return tuple(observations), tuple(truths)


def _facts_for(variant_id: str, observation: Mapping[str, object]) -> list[dict[str, object]]:
    baseline = [dict(row) for row in observation["baseline_facts"]]  # type: ignore[union-attr]
    delivered = [dict(row) for row in observation["delivered_facts"]]  # type: ignore[union-attr]
    if variant_id == "M0":
        return delivered
    if variant_id == "M2":
        return [row for row in baseline + delivered if row["predicate"] in {"ATTEMPT_OUTCOME", "ON"}]
    if variant_id == "V0":
        return baseline + delivered
    if variant_id == "M1":
        return baseline + delivered
    if variant_id in {"M3", "M4", "M5", "M6", "H0"}:
        if variant_id == "M3":
            return [row for row in baseline + delivered if row["predicate"] != "ATTEMPT_OUTCOME"]
        return baseline + delivered
    raise ScreenError("unknown variant")


def _tokens(value: str) -> tuple[str, ...]:
    normalized = "".join(character.casefold() if character.isalnum() else " " for character in value)
    return tuple(token for token in normalized.split() if token)


def _vector_retrieve(query_id: str, facts: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    """Frozen local signed-hash vector retrieval used by M6/V0."""
    if not facts:
        return ()
    documents = [
        _tokens(f"subject {row['subject_id']} predicate {row['predicate']} object {row['value']} provenance {row['source_event_id']}")
        for row in facts
    ]
    query = _tokens(QUERY_RETRIEVAL_TEXT[query_id])
    count = len(documents); average_length = sum(map(len, documents)) / count
    frequencies = {token: sum(token in document for document in documents) for token in set().union(*map(set, documents))}
    idf = {token: math.log(1.0 + (count - frequency + 0.5) / (frequency + 0.5)) for token, frequency in frequencies.items()}

    def component(token: str) -> tuple[int, float]:
        integer = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest(), "big")
        return integer & 255, 1.0 if ((integer >> 8) & 1) == 0 else -1.0

    query_vector = np.zeros(256, dtype=np.float64)
    for token in set(query):
        if token in idf:
            index, sign = component(token); query_vector[index] += sign * idf[token] * query.count(token)
    query_norm = float(np.linalg.norm(query_vector))
    if query_norm == 0.0:
        return ()
    query_vector /= query_norm
    ranked = []
    for row, document in zip(facts, documents):
        vector = np.zeros(256, dtype=np.float64)
        for token in set(document):
            frequency = document.count(token)
            weight = idf[token] * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * len(document) / average_length))
            index, sign = component(token); vector[index] += sign * weight
        norm = float(np.linalg.norm(vector))
        cosine = 0.0 if norm == 0.0 else float(np.dot(query_vector, vector / norm))
        if cosine > 0.0:
            ranked.append((cosine, -int(row["received_tick"]), str(row["fact_id"]), dict(row)))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    return tuple(item[3] for item in ranked[: int(BASE_CONFIG["retrieval_r"])])


_QUERY_PREDICATES = {
    "LOCATION": ("IN",), "LAST_OBSERVED": ("OBSERVED_AT", "VISIBILITY"),
    "POSE_USABLE": ("POSE",), "PRIOR_ATTEMPT": ("ATTEMPT_OUTCOME",),
    "LAST_FAILURE_REASON": ("ATTEMPT_OUTCOME",),
    "REACHABLE_VALVE": ("IN", "RESTRICTED_BY"), "CHANGES_SINCE": ("ON",),
    "ROUTE_BLOCKER": ("CONNECTS", "DOOR_STATE"), "DUPLICATE_IDENTITY": ("ALIAS",),
    "CONFLICTS_UNKNOWN": ("OPERATIONAL_STATE",),
}


def _typed_retrieve(query_id: str, facts: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    predicates = set(_QUERY_PREDICATES[query_id])
    return tuple(
        dict(row) for row in facts
        if row["predicate"] in predicates
        and (query_id != "DUPLICATE_IDENTITY" or _tokens(str(row["value"])) == ("service", "valve"))
    )


def _lexical_retrieve(query_id: str, facts: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    query = set(_tokens(QUERY_RETRIEVAL_TEXT[query_id]))
    ranked = []
    for row in facts:
        tokens = set(_tokens(f"{row['subject_id']} {row['predicate']} {row['value']}"))
        overlap = len(query & tokens)
        if overlap:
            ranked.append((-overlap, -int(row["received_tick"]), str(row["fact_id"]), dict(row)))
    ranked.sort(key=lambda item: item[:3])
    return tuple(item[3] for item in ranked[: int(BASE_CONFIG["retrieval_r"])])


def _retrieval_union(query_id: str, facts: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    by_id: dict[str, dict[str, object]] = {}
    for channel in (_typed_retrieve, _lexical_retrieve, _vector_retrieve):
        for row in channel(query_id, facts):
            by_id.setdefault(str(row["fact_id"]), row)
    return tuple(by_id[key] for key in sorted(by_id))


def _nonvector_union(query_id: str, facts: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    by_id: dict[str, dict[str, object]] = {}
    for channel in (_typed_retrieve, _lexical_retrieve):
        for row in channel(query_id, facts):
            by_id.setdefault(str(row["fact_id"]), row)
    return tuple(by_id[key] for key in sorted(by_id))


def _answer(variant: str, query: str, facts: Sequence[Mapping[str, object]], now: int) -> tuple[str, str, tuple[str, ...]]:
    predicates: dict[str, list[Mapping[str, object]]] = {}
    for row in facts:
        predicates.setdefault(str(row["predicate"]), []).append(row)
    cited: list[Mapping[str, object]] = []
    answer, decision = "UNKNOWN", "REPORT_UNKNOWN"
    structured = variant in {"M3", "M4", "M5", "M6", "V0"}
    episodic = variant in {"M1", "M2", "M4", "M5", "M6", "V0"}
    confidence_aware = variant in {"M5", "M6"}
    if query == "LOCATION":
        cited = predicates.get("IN", [])
        if cited and not confidence_aware:
            answer, decision = str(cited[-1]["value"]), "ACT"
        else:
            answer, decision = "UNKNOWN", "RESCAN"
    elif query == "LAST_OBSERVED":
        cited = predicates.get("OBSERVED_AT", [])
        if cited: answer, decision = str(cited[-1]["value"]), "REPORT"
    elif query == "POSE_USABLE":
        cited = predicates.get("POSE", [])
        stale = bool(cited) and now - int(cited[-1]["received_tick"]) >= 2
        if cited and not (confidence_aware and stale): answer, decision = "USABLE", "ACT"
        elif stale: answer, decision = "STALE", "RESCAN"
        else: decision = "RESCAN"
    elif query in {"PRIOR_ATTEMPT", "LAST_FAILURE_REASON"}:
        cited = predicates.get("ATTEMPT_OUTCOME", []) if episodic else []
        if cited:
            answer = "YES" if query == "PRIOR_ATTEMPT" else str(cited[-1]["value"]).split(":")[-1]
            decision = "REPORT"
    elif query == "REACHABLE_VALVE":
        locations = predicates.get("IN", []) if structured else []
        restrictions = {str(row["subject_id"]) for row in predicates.get("RESTRICTED_BY", [])}
        candidates = [row for row in locations if str(row["subject_id"]).startswith("valve/") and str(row["value"]) not in restrictions]
        cited = candidates + predicates.get("RESTRICTED_BY", [])
        if candidates: answer, decision = str(candidates[0]["subject_id"]), "CHOOSE_ALTERNATIVE"
    elif query == "CHANGES_SINCE":
        cited = predicates.get("ON", []) if episodic else []
        if cited: answer, decision = f"{cited[-1]['subject_id']}:ON:{cited[-1]['value']}", "REPORT"
    elif query == "ROUTE_BLOCKER":
        cited = predicates.get("DOOR_STATE", []) if structured else []
        if cited: answer, decision = str(cited[-1]["subject_id"]), "CHOOSE_ALTERNATIVE"
    elif query == "DUPLICATE_IDENTITY":
        aliases = predicates.get("ALIAS", [])
        cited = aliases
        if len({row["subject_id"] for row in aliases}) > 1: answer, decision = "AMBIGUOUS", "REIDENTIFY"
    elif query == "CONFLICTS_UNKNOWN":
        states = predicates.get("OPERATIONAL_STATE", [])
        cited = states
        usable = [row for row in states if float(row["confidence"]) >= float(BASE_CONFIG["confidence_threshold"])]
        if confidence_aware and {row["status"] for row in usable} == {"asserted", "contradicted"}:
            answer, decision = "CONTRADICTED", "REPORT_UNKNOWN"
        elif confidence_aware and usable:
            answer, decision = str(usable[-1]["value"]), "ACT"
        elif confidence_aware:
            answer, decision = "UNKNOWN", "REPORT_UNKNOWN"
        elif states:
            answer, decision = str(states[-1]["value"]), "ACT"
    return answer, decision, tuple(str(row["fact_id"]) for row in cited)


def _run_flat_history(seed: int, observations: Sequence[Mapping[str, object]]) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Independent append-only event comparator; it shares inputs, not graph code."""
    compiled: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []
    for observation in observations:
        events = []
        for phase in ("baseline_facts", "delivered_facts"):
            for fact in observation[phase]:  # type: ignore[union-attr]
                event = {
                    "case_id": observation["case_id"], "confidence": fact["confidence"],
                    "event_id": fact["fact_id"], "observed_tick": fact["observed_tick"],
                    "payload_predicate": fact["predicate"], "payload_subject_id": fact["subject_id"],
                    "payload_value": fact["value"], "received_tick": fact["received_tick"],
                    "record_kind": "FLAT_EVENT", "status": fact["status"], "variant_id": "H0",
                }
                events.append(event); compiled.append(event)
        query = str(observation["query_id"]); now = int(observation["query_tick"])
        matches = lambda predicate: [row for row in events if row["payload_predicate"] == predicate]
        answer, decision, cited = "UNKNOWN", "REPORT_UNKNOWN", []
        if query == "LOCATION":
            cited = matches("IN")
            if cited: answer, decision = str(cited[-1]["payload_value"]), "ACT"
            else: decision = "RESCAN"
        elif query == "LAST_OBSERVED":
            cited = matches("OBSERVED_AT")
            if cited: answer, decision = str(cited[-1]["payload_value"]), "REPORT"
        elif query == "POSE_USABLE":
            cited = matches("POSE")
            if cited: answer, decision = "USABLE", "ACT"
            else: decision = "RESCAN"
        elif query in {"PRIOR_ATTEMPT", "LAST_FAILURE_REASON"}:
            cited = matches("ATTEMPT_OUTCOME")
            if cited:
                answer = "YES" if query == "PRIOR_ATTEMPT" else str(cited[-1]["payload_value"]).split(":")[-1]
                decision = "REPORT"
        elif query == "REACHABLE_VALVE":
            locations = matches("IN"); restrictions = {str(row["payload_subject_id"]) for row in matches("RESTRICTED_BY")}
            candidates = [row for row in locations if str(row["payload_subject_id"]).startswith("valve/") and str(row["payload_value"]) not in restrictions]
            cited = candidates + matches("RESTRICTED_BY")
            if candidates: answer, decision = str(candidates[0]["payload_subject_id"]), "CHOOSE_ALTERNATIVE"
        elif query == "CHANGES_SINCE":
            cited = matches("ON")
            if cited: answer, decision = f"{cited[-1]['payload_subject_id']}:ON:{cited[-1]['payload_value']}", "REPORT"
        elif query == "ROUTE_BLOCKER":
            cited = matches("DOOR_STATE")
            if cited: answer, decision = str(cited[-1]["payload_subject_id"]), "CHOOSE_ALTERNATIVE"
        elif query == "DUPLICATE_IDENTITY":
            cited = matches("ALIAS")
            if len({row["payload_subject_id"] for row in cited}) > 1: answer, decision = "AMBIGUOUS", "REIDENTIFY"
        elif query == "CONFLICTS_UNKNOWN":
            cited = matches("OPERATIONAL_STATE")
            if cited: answer, decision = str(cited[-1]["payload_value"]), "ACT"
        decisions.append({
            "answer": answer, "case_id": observation["case_id"],
            "cited_fact_ids": tuple(str(row["event_id"]) for row in cited),
            "context_bytes": len(_canonical(cited)), "decision": decision, "query_id": query,
            "retrieval_channel": None, "retrieval_channels": (), "retrieval_fact_ids": (),
            "schema_version": "exp04-engineering-query-decision-v3", "seed": seed, "variant_id": "H0",
        })
    return tuple(compiled), tuple(decisions)


def run_variant(variant_id: str, seed: int, observations: Sequence[Mapping[str, object]]) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Execute one architecture without accepting scorer truth."""
    if variant_id not in VARIANTS or type(seed) is not int or len(observations) != 10:
        raise ScreenError("invalid variant execution input")
    if variant_id == "H0":
        return _run_flat_history(seed, observations)
    compiled: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []
    for observation in observations:
        if observation.get("seed") != seed or observation.get("query_id") not in QUERY_IDS:
            raise ScreenError("observation identity is invalid")
        facts = _facts_for(variant_id, observation)
        compiled.extend({"case_id": observation["case_id"], "variant_id": variant_id, **row} for row in facts)
        query_id = str(observation["query_id"])
        if variant_id == "M6":
            retrieved = _retrieval_union(query_id, facts)
        elif variant_id == "V0":
            retrieved = _vector_retrieve(query_id, facts)
        elif variant_id == "M5" and query_id == "DUPLICATE_IDENTITY":
            retrieved = _nonvector_union(query_id, facts)
        else:
            retrieved = ()
        answer_facts = retrieved if variant_id in {"M6", "V0"} or (variant_id == "M5" and query_id == "DUPLICATE_IDENTITY") else facts
        answer, decision, cited = _answer(variant_id, query_id, answer_facts, int(observation["query_tick"]))
        context_bytes = len(_canonical([row for row in facts if str(row["fact_id"]) in cited]))
        decisions.append({
            "answer": answer, "case_id": observation["case_id"], "cited_fact_ids": cited,
            "context_bytes": context_bytes, "decision": decision, "query_id": observation["query_id"],
            "retrieval_channel": "TYPED_LEXICAL_VECTOR_UNION_V3" if variant_id == "M6" else ("SIGNED_HASH_VECTOR_V3" if variant_id == "V0" else ("TYPED_LEXICAL_UNION_V3" if variant_id == "M5" and query_id == "DUPLICATE_IDENTITY" else None)),
            "retrieval_channels": ("TYPED", "LEXICAL", "VECTOR") if variant_id == "M6" else (("VECTOR",) if variant_id == "V0" else (("TYPED", "LEXICAL") if variant_id == "M5" and query_id == "DUPLICATE_IDENTITY" else ())),
            "retrieval_fact_ids": tuple(str(row["fact_id"]) for row in retrieved),
            "schema_version": "exp04-engineering-query-decision-v3", "seed": seed,
            "variant_id": variant_id,
        })
    return tuple(compiled), tuple(decisions)


def _score(decisions: Sequence[Mapping[str, object]], truths: Sequence[Mapping[str, object]], facts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    truth_by_case = {row["case_id"]: row for row in truths}
    scored = []
    for row in decisions:
        truth = truth_by_case[row["case_id"]]
        correct = row["answer"] == truth["expected_answer"] and row["decision"] == truth["expected_decision"]
        stale = row["query_id"] == "POSE_USABLE" and truth["expected_decision"] == "RESCAN" and row["decision"] == "ACT"
        wrong = row["query_id"] in IDENTITY_QUERIES and row["answer"] not in {truth["expected_answer"], "UNKNOWN"}
        scored.append({"case_id": row["case_id"], "correct": correct, "query_id": row["query_id"], "stale_action": stale, "wrong_identity": wrong})
    correct = sum(bool(row["correct"]) for row in scored)
    stale = sum(bool(row["stale_action"]) for row in scored if row["query_id"] in ACTION_QUERIES)
    wrong = sum(bool(row["wrong_identity"]) for row in scored if row["query_id"] in IDENTITY_QUERIES)
    scans = sum(row["decision"] in {"RESCAN", "REIDENTIFY"} for row in decisions)
    ambiguous = next(row for row in scored if row["query_id"] == "DUPLICATE_IDENTITY")
    duplicate_decision = next(row for row in decisions if row["query_id"] == "DUPLICATE_IDENTITY")
    fuzzy_candidates = {
        str(row.get("fact_id", row.get("event_id"))) for row in facts
        if row.get("predicate", row.get("payload_predicate")) == "ALIAS"
        and row.get("value", row.get("payload_value")) in FUZZY_ALIAS_TOKENS
    }
    vector_executed = "VECTOR" in duplicate_decision["retrieval_channels"]
    fuzzy_hits = len(fuzzy_candidates & set(duplicate_decision["retrieval_fact_ids"])) if vector_executed else None
    return {
        "ambiguous_retrieval_rate": float(bool(ambiguous["correct"])), "correct_count": correct,
        "correct_rate": correct / 10.0, "disposition": "COMPLETE", "input_fact_count": len(facts),
        "fuzzy_vector_candidate_count": len(fuzzy_candidates),
        "fuzzy_vector_candidate_hit_count": fuzzy_hits,
        "fuzzy_vector_candidate_miss_count": len(fuzzy_candidates) - fuzzy_hits if fuzzy_hits is not None else None,
        "repeated_scan_count": scans, "schema_version": "exp04-engineering-metrics-v3",
        "stale_action_rate": stale / 4.0, "stale_wrong_composite": 0.5 * stale / 4.0 + 0.5 * wrong / 2.0,
        "wrong_identity_rate": wrong / 2.0,
    }


def _write(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def _bundle_files(variant: str, seed: int, observations: Sequence[Mapping[str, object]], truths: Sequence[Mapping[str, object]], *, implementation_git_sha: str, implementation_source_sha256: str, protocol_config_sha256: str) -> dict[str, bytes]:
    facts, decisions = run_variant(variant, seed, observations)
    metrics = _score(decisions, truths, facts)
    files = {
        "compiled-facts.jsonl": _jsonl(facts), "metrics.json": _canonical(metrics),
        "observation-trace.jsonl": _jsonl(observations), "query-decisions.jsonl": _jsonl(decisions),
        "scorer-truth.jsonl": _jsonl(truths),
    }
    inventory = [{"bytes": len(content), "path": name, "sha256": _sha(content)} for name, content in sorted(files.items())]
    replay = _sha(b"".join(files[name] for name in sorted(files) if name != "metrics.json"))
    manifest = {
        "claim_status": "ENGINEERING_NONCONFIRMATORY", "disposition": "COMPLETE", "files": inventory,
        "implementation_git_sha": implementation_git_sha, "implementation_source_sha256": implementation_source_sha256,
        "observation_trace_sha256": _sha(files["observation-trace.jsonl"]), "replay_sha256": replay,
        "protocol_config_sha256": protocol_config_sha256, "schema_version": "exp04-engineering-bundle-manifest-v3",
        "seed": seed, "variant_id": variant,
    }
    files["bundle-manifest.json"] = _canonical(manifest)
    return files


def _load_rows(path: Path) -> tuple[dict[str, object], ...]:
    return tuple(json.loads(line) for line in path.read_text(encoding="ascii").splitlines())


def _derive(raw: Path) -> dict[str, bytes]:
    root_manifest_bytes = (raw / "raw-manifest.json").read_bytes()
    root_manifest = json.loads(root_manifest_bytes)
    if _canonical(root_manifest) != root_manifest_bytes:
        raise ScreenError("raw manifest is noncanonical")
    metric_rows: list[dict[str, object]] = []
    samples: list[dict[str, object]] = []
    for entry in root_manifest["bundles"]:
        bundle = raw / "bundles" / entry["bundle_id"]
        manifest_bytes = (bundle / "bundle-manifest.json").read_bytes()
        if _sha(manifest_bytes) != entry["manifest_sha256"]:
            raise ScreenError("bundle manifest hash mismatch")
        manifest = json.loads(manifest_bytes)
        for name in ("implementation_git_sha", "implementation_source_sha256", "protocol_config_sha256"):
            if manifest.get(name) != root_manifest.get(name):
                raise ScreenError("bundle source/config identity mismatch")
        for item in manifest["files"]:
            content = (bundle / item["path"]).read_bytes()
            if len(content) != item["bytes"] or _sha(content) != item["sha256"]:
                raise ScreenError("bundle member hash mismatch")
        observations = _load_rows(bundle / "observation-trace.jsonl")
        truths = _load_rows(bundle / "scorer-truth.jsonl")
        facts, decisions = run_variant(str(manifest["variant_id"]), int(manifest["seed"]), observations)
        if _jsonl(facts) != (bundle / "compiled-facts.jsonl").read_bytes() or _jsonl(decisions) != (bundle / "query-decisions.jsonl").read_bytes():
            raise ScreenError("bundle replay mismatch")
        metrics = _score(decisions, truths, facts)
        if _canonical(metrics) != (bundle / "metrics.json").read_bytes():
            raise ScreenError("metric replay mismatch")
        metric_rows.append({"seed": manifest["seed"], "variant_id": manifest["variant_id"], **metrics})
        truth_by_case = {row["case_id"]: row for row in truths}
        for decision in decisions:
            truth = truth_by_case[decision["case_id"]]
            working = decision["answer"] == truth["expected_answer"] and decision["decision"] == truth["expected_decision"]
            samples.append({
                "answer": decision["answer"], "case_id": decision["case_id"], "class": "WORKING" if working else "NONWORKING",
                "decision": decision["decision"], "expected_answer": truth["expected_answer"],
                "expected_decision": truth["expected_decision"], "query_id": decision["query_id"],
                "seed": manifest["seed"], "variant_id": manifest["variant_id"],
            })
    variants = []
    for variant in VARIANTS:
        rows = [row for row in metric_rows if row["variant_id"] == variant]
        fuzzy_count = sum(int(row["fuzzy_vector_candidate_count"]) for row in rows)
        fuzzy_hits = [int(row["fuzzy_vector_candidate_hit_count"]) for row in rows if row["fuzzy_vector_candidate_hit_count"] is not None]
        fuzzy_misses = [int(row["fuzzy_vector_candidate_miss_count"]) for row in rows if row["fuzzy_vector_candidate_miss_count"] is not None]
        variants.append({
            "ambiguous_retrieval_rate": sum(float(row["ambiguous_retrieval_rate"]) for row in rows) / len(rows),
            "correct_rate": sum(float(row["correct_rate"]) for row in rows) / len(rows),
            "fuzzy_vector_candidate_count": fuzzy_count,
            "fuzzy_vector_candidate_hit_count": sum(fuzzy_hits) if fuzzy_hits else None,
            "fuzzy_vector_candidate_hit_rate": sum(fuzzy_hits) / fuzzy_count if fuzzy_hits and fuzzy_count else (0.0 if fuzzy_hits else None),
            "fuzzy_vector_candidate_miss_count": sum(fuzzy_misses) if fuzzy_misses else None,
            "repeated_scan_count": sum(int(row["repeated_scan_count"]) for row in rows) / len(rows),
            "seed_count": len(rows),
            "stale_action_rate": sum(float(row["stale_action_rate"]) for row in rows) / len(rows),
            "stale_wrong_composite": sum(float(row["stale_wrong_composite"]) for row in rows) / len(rows),
            "variant_id": variant,
            "wrong_identity_rate": sum(float(row["wrong_identity_rate"]) for row in rows) / len(rows),
        })
    selected: list[dict[str, object]] = []
    for variant in VARIANTS:
        candidates = sorted((row for row in samples if row["variant_id"] == variant), key=lambda row: (int(row["seed"]), str(row["query_id"])))
        for label in ("WORKING", "NONWORKING"):
            match = next((row for row in candidates if row["class"] == label), None)
            selected.append(match if match is not None else {"class": "CLASS_NOT_OBSERVED", "denominator": len(candidates), "requested_class": label, "variant_id": variant})
    aggregate = {"bundle_count": len(metric_rows), "case_answer_count": len(samples), "claim_status": "ENGINEERING_NONCONFIRMATORY", "schema_version": "exp04-engineering-aggregate-v3", "variants": variants}
    annotations = {"samples": selected, "schema_version": "exp04-engineering-annotations-v3", "selection_rule": "FIRST_CANONICAL_WORKING_AND_NONWORKING_PER_VARIANT_WHEN_OBSERVED"}
    recipe = {
        "code_sha256": root_manifest["implementation_source_sha256"],
        "inputs": {"raw_manifest_sha256": _sha(root_manifest_bytes)},
        "operation": "validate every bundle hash; replay independent graph, flat-log, and retrieval comparators from observation-trace without scorer truth; join independently derived scorer truth; recompute metrics, aggregate, annotations, and report",
        "schema_version": "exp04-engineering-recipe-v3", "seeds": list(SEEDS), "variants": list(VARIANTS),
    }
    by = {row["variant_id"]: row for row in variants}
    report = (
        "# Experiment 04 Engineering Memory Screen v3\n\n"
        "Status: ENGINEERING_NONCONFIRMATORY\n\n"
        f"The BASE-only screen completed {len(metric_rows)} bundles and {len(samples)} case answers. "
        f"M4 correctness was {by['M4']['correct_rate']:.3f} versus M0 {by['M0']['correct_rate']:.3f}, "
        f"V0 {by['V0']['correct_rate']:.3f}, and H0 {by['H0']['correct_rate']:.3f}. "
        f"M5 stale/wrong composite was {by['M5']['stale_wrong_composite']:.3f} versus M4 {by['M4']['stale_wrong_composite']:.3f}. "
        f"M6 ambiguous retrieval was {by['M6']['ambiguous_retrieval_rate']:.3f} versus M5 {by['M5']['ambiguous_retrieval_rate']:.3f}. "
        f"The frozen signed-hash vector retrieved {by['M6']['fuzzy_vector_candidate_hit_count']} of "
        f"{by['M6']['fuzzy_vector_candidate_count']} fuzzy alternate candidates; misses are retained, not replaced.\n\n"
        "These fixed public engineering seeds do not support confirmation, promotion, or a production memory claim.\n"
    ).encode("ascii")
    return {"RESULTS.md": report, "aggregate.json": _canonical(aggregate), "annotations.json": _canonical(annotations), "recipe.json": _canonical(recipe)}


def run_screen(output: Path, *, seeds: Sequence[int], implementation_git_sha: str) -> None:
    if output.exists() or tuple(seeds) != SEEDS:
        raise ScreenError("output must be absent and seeds must equal the frozen engineering set")
    if len(implementation_git_sha) != 40 or any(character not in "0123456789abcdef" for character in implementation_git_sha):
        raise ScreenError("implementation_git_sha must be lowercase SHA-1")
    source_sha256 = _sha(Path(__file__).read_bytes())
    config_sha256 = _sha(_canonical({
        "base_config": BASE_CONFIG,
        "fuzzy_alias_generator": "sha256('exp04-fuzzy-v3:<zero-based-index>')[:12]",
        "fuzzy_alias_tokens": FUZZY_ALIAS_TOKENS,
        "fuzzy_seed_slots": FUZZY_SEED_SLOTS,
        "queries": QUERY_IDS,
        "seeds": SEEDS,
        "variants": VARIANTS,
    }))
    bundles = output / "raw" / "bundles"; derived = output / "derived"
    bundles.mkdir(parents=True); derived.mkdir()
    inventory = []
    for variant in VARIANTS:
        for seed in SEEDS:
            observations, truths = generate_seed(seed)
            bundle_id = f"{variant}.seed-{seed}"; destination = bundles / bundle_id; destination.mkdir()
            files = _bundle_files(variant, seed, observations, truths, implementation_git_sha=implementation_git_sha, implementation_source_sha256=source_sha256, protocol_config_sha256=config_sha256)
            for name, content in files.items(): _write(destination / name, content)
            inventory.append({"bundle_id": bundle_id, "manifest_sha256": _sha(files["bundle-manifest.json"])})
    raw_manifest = {"bundles": inventory, "claim_status": "ENGINEERING_NONCONFIRMATORY", "implementation_git_sha": implementation_git_sha, "implementation_source_sha256": source_sha256, "protocol_config_sha256": config_sha256, "schema_version": "exp04-engineering-raw-manifest-v3"}
    _write(output / "raw" / "raw-manifest.json", _canonical(raw_manifest))
    for name, content in _derive(output / "raw").items(): _write(derived / name, content)


def reconstruct_screen(raw: Path, clean: Path) -> None:
    if clean.exists() or not raw.is_dir() or raw.is_symlink():
        raise ScreenError("raw input must be regular and clean output absent")
    derived = _derive(raw)
    clean.mkdir()
    for name, content in derived.items(): _write(clean / name, content)
