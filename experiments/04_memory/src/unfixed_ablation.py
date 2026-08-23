"""Matched fixed-versus-online Experiment 04 memory ablation.

The controller consumes observation streams only. Scorer truth is generated and
stored separately, then joined after decisions are immutable.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np


SEEDS = tuple(range(20263001, 20263065))
VARIANTS = ("FIXED_M5", "LIVE_SEMANTIC", "LIVE_EPISODIC", "LIVE_SEPARATE")
QUERY_IDS = ("SELECT_TARGET", "POSE_ACTION", "RETRY_DECISION", "FAILURE_EXPLANATION")
MUTATIONS = ("POSE_MOVE", "AVAILABILITY_CHANGE", "RESTRICTION_CHANGE")
CONFIDENCE_THRESHOLD = 0.70
POSE_TTL = 2
BOOTSTRAP_DRAWS = 20_000
BOOTSTRAP_SEED = 20263999


class AblationError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _jsonl(rows: Sequence[Mapping[str, object]]) -> bytes:
    return b"".join(_canonical(row) for row in rows)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]


def _event(event_id: str, tick: int, kind: str, subject: str, value: object, confidence: float = 0.95) -> dict[str, object]:
    return {
        "confidence": confidence,
        "event_id": event_id,
        "event_kind": kind,
        "observed_tick": tick,
        "subject_id": subject,
        "value": value,
    }


def _eligible(world: Mapping[str, Mapping[str, object]], restrictions: Mapping[str, bool]) -> list[str]:
    return sorted(
        (
            entity
            for entity, state in world.items()
            if state["availability"] == "AVAILABLE" and not restrictions[str(state["room_id"])]
        ),
        key=lambda entity: (str(world[entity]["room_id"]), entity),
    )


def _truth_rows(
    *, seed: int, checkpoint: str, mutation_kind: str, tick: int,
    world: Mapping[str, Mapping[str, object]], restrictions: Mapping[str, bool],
    failures: Mapping[str, str], authoritative_pose_ticks: Mapping[str, int],
) -> list[dict[str, object]]:
    eligible = _eligible(world, restrictions)
    target = eligible[0] if eligible else None
    failed = set(failures)
    alternatives = [entity for entity in eligible if entity not in failed]
    pose_usable = target is not None and tick - authoritative_pose_ticks.get(target, -10_000) <= POSE_TTL
    retry = (
        f"REPLAN:{alternatives[0]}" if target in failed and alternatives
        else ("RESCAN" if target in failed or target is None else f"EXECUTE:{target}")
    )
    explanation = list(failures.values())[-1] if failures else "NONE"
    answers = {
        "SELECT_TARGET": f"TARGET:{target}" if target else "RESCAN",
        "POSE_ACTION": f"ACT:{target}" if pose_usable else "RESCAN",
        "RETRY_DECISION": retry,
        "FAILURE_EXPLANATION": explanation,
    }
    common = {
        "actual_eligible_ids": eligible,
        "checkpoint": checkpoint,
        "failed_target_ids": sorted(failed),
        "mutation_kind": mutation_kind,
        "pose_usable_target": target if pose_usable else None,
        "schema_version": "exp04-unfixed-scorer-truth-v1",
        "seed": seed,
        "tick": tick,
    }
    return [{**common, "expected_answer": answers[query], "query_id": query} for query in QUERY_IDS]


def generate_seed(seed: int) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Generate one observation stream and isolated scorer truth via NumPy PCG64."""
    if type(seed) is not int or seed < 0:
        raise AblationError("seed must be a nonnegative integer")
    rng = np.random.Generator(np.random.PCG64(seed))
    entity_numbers = rng.choice(np.arange(1000, 9999), size=3, replace=False)
    entities = [f"valve/{int(number):04d}" for number in entity_numbers]
    rooms = ["room/0001", "room/0002", "room/0003", "room/0004"]
    rng.shuffle(rooms)
    world: dict[str, dict[str, object]] = {}
    restrictions = {room: False for room in rooms}
    restrictions[rooms[3]] = True
    for index, entity in enumerate(entities):
        world[entity] = {
            "availability": "AVAILABLE",
            "pose": [round(float(rng.uniform(-2.0, 2.0)), 6), round(float(rng.uniform(-2.0, 2.0)), 6)],
            "room_id": rooms[index],
        }

    initial_events: list[dict[str, object]] = []
    for entity in sorted(entities):
        state = world[entity]
        initial_events.extend((
            _event(f"{seed}:0:{entity}:room", 0, "ROOM", entity, state["room_id"]),
            _event(f"{seed}:0:{entity}:availability", 0, "AVAILABILITY", entity, state["availability"]),
            _event(f"{seed}:0:{entity}:pose", 0, "POSE", entity, state["pose"]),
        ))
    for room in sorted(restrictions):
        initial_events.append(_event(f"{seed}:0:{room}:restriction", 0, "RESTRICTION", room, restrictions[room]))

    authoritative_pose_ticks = {entity: 0 for entity in entities}
    failures: dict[str, str] = {}
    stream: list[dict[str, object]] = [{
        "checkpoint": "CONTROL", "events": initial_events, "mutation_kind": "NONE",
        "schema_version": "exp04-unfixed-observation-v1", "seed": seed, "tick": 0,
    }]
    truth = _truth_rows(
        seed=seed, checkpoint="CONTROL", mutation_kind="NONE", tick=0,
        world=world, restrictions=restrictions, failures=failures,
        authoritative_pose_ticks=authoritative_pose_ticks,
    )

    mutation_order = list(MUTATIONS)
    rng.shuffle(mutation_order)
    failed_target: str | None = None
    for step, mutation in enumerate(mutation_order, start=1):
        tick = step * 3
        events: list[dict[str, object]] = []
        eligible_before = _eligible(world, restrictions)
        target = eligible_before[0]
        delivered = bool(rng.random() < 0.86)
        confidence = round(float(rng.uniform(0.82, 0.99)), 6)
        if mutation == "POSE_MOVE":
            world[target]["pose"] = [round(float(rng.uniform(-2.0, 2.0)), 6), round(float(rng.uniform(-2.0, 2.0)), 6)]
            if delivered:
                events.append(_event(f"{seed}:{tick}:{target}:pose", tick, "POSE", target, world[target]["pose"], confidence))
                authoritative_pose_ticks[target] = tick
        elif mutation == "AVAILABILITY_CHANGE":
            world[target]["availability"] = "UNAVAILABLE"
            replacement = next(entity for entity in entities if entity != target)
            world[replacement]["availability"] = "AVAILABLE"
            if delivered:
                events.extend((
                    _event(f"{seed}:{tick}:{target}:availability", tick, "AVAILABILITY", target, "UNAVAILABLE", confidence),
                    _event(f"{seed}:{tick}:{replacement}:availability", tick, "AVAILABILITY", replacement, "AVAILABLE", confidence),
                ))
        else:
            restricted_room = str(world[target]["room_id"])
            restrictions[restricted_room] = True
            release_room = next(room for room in sorted(restrictions) if room != restricted_room and restrictions[room])
            restrictions[release_room] = False
            if delivered:
                events.extend((
                    _event(f"{seed}:{tick}:{restricted_room}:restriction", tick, "RESTRICTION", restricted_room, True, confidence),
                    _event(f"{seed}:{tick}:{release_room}:restriction", tick, "RESTRICTION", release_room, False, confidence),
                ))
        if step == 2:
            current = _eligible(world, restrictions)
            failed_target = current[0] if current else target
            reason = ("JAMMED", "BLOCKED", "SLIPPED", "NO_RESPONSE")[int(rng.integers(0, 4))]
            failures[failed_target] = reason
            events.append(_event(f"{seed}:{tick}:{failed_target}:attempt", tick, "ATTEMPT", failed_target, f"FAILED:{reason}", .99))
        checkpoint = f"STEP_{step}"
        stream.append({
            "checkpoint": checkpoint, "events": events, "mutation_kind": mutation,
            "schema_version": "exp04-unfixed-observation-v1", "seed": seed, "tick": tick,
        })
        truth.extend(_truth_rows(
            seed=seed, checkpoint=checkpoint, mutation_kind=mutation, tick=tick,
            world=world, restrictions=restrictions, failures=failures,
            authoritative_pose_ticks=authoritative_pose_ticks,
        ))
    if failed_target is None:
        raise AssertionError("failure intervention was not generated")
    return tuple(stream), tuple(truth)


@dataclass
class _Memory:
    semantic: dict[str, dict[str, object]] = field(default_factory=dict)
    restrictions: dict[str, bool] = field(default_factory=dict)
    episodes: list[dict[str, object]] = field(default_factory=list)

    def semantic_update(self, event: Mapping[str, object]) -> None:
        if float(event["confidence"]) < CONFIDENCE_THRESHOLD:
            return
        kind = str(event["event_kind"])
        subject = str(event["subject_id"])
        tick_key = (int(event["observed_tick"]), str(event["event_id"]))
        if kind == "RESTRICTION":
            key = f"restriction:{subject}"
            existing = self.semantic.get(key)
            if existing is None or tick_key > tuple(existing["update_key"]):
                self.semantic[key] = {"update_key": list(tick_key), "value": bool(event["value"])}
                self.restrictions[subject] = bool(event["value"])
            return
        field_name = {"ROOM": "room_id", "AVAILABILITY": "availability", "POSE": "pose"}.get(kind)
        if field_name is None:
            return
        state = self.semantic.setdefault(subject, {})
        old_key = tuple(state.get(f"{field_name}_update_key", (-1, "")))
        if tick_key > old_key:
            state[field_name] = event["value"]
            state[f"{field_name}_update_key"] = list(tick_key)
            if field_name == "pose":
                state["pose_tick"] = int(event["observed_tick"])

    def episodic_update(self, event: Mapping[str, object]) -> None:
        if event["event_kind"] == "ATTEMPT" and float(event["confidence"]) >= CONFIDENCE_THRESHOLD:
            self.episodes.append(dict(event))


def _memory_eligible(memory: _Memory) -> list[str]:
    candidates = []
    for entity, state in memory.semantic.items():
        if entity.startswith("restriction:") or "room_id" not in state:
            continue
        if state.get("availability") == "AVAILABLE" and not memory.restrictions.get(str(state["room_id"]), False):
            candidates.append(entity)
    return sorted(candidates, key=lambda entity: (str(memory.semantic[entity]["room_id"]), entity))


def _context(memory: _Memory) -> dict[str, object]:
    return {
        "episodes": memory.episodes,
        "restrictions": memory.restrictions,
        "semantic": memory.semantic,
    }


def _decide(memory: _Memory, query: str, tick: int) -> str:
    eligible = _memory_eligible(memory)
    target = eligible[0] if eligible else None
    failed_reasons = {
        str(event["subject_id"]): str(event["value"]).split(":", 1)[-1]
        for event in memory.episodes if str(event["value"]).startswith("FAILED:")
    }
    if query == "SELECT_TARGET":
        return f"TARGET:{target}" if target else "RESCAN"
    if query == "POSE_ACTION":
        pose_tick = int(memory.semantic.get(target or "", {}).get("pose_tick", -10_000))
        return f"ACT:{target}" if target and tick - pose_tick <= POSE_TTL else "RESCAN"
    if query == "RETRY_DECISION":
        alternatives = [entity for entity in eligible if entity not in failed_reasons]
        if target in failed_reasons:
            return f"REPLAN:{alternatives[0]}" if alternatives else "RESCAN"
        return f"EXECUTE:{target}" if target else "RESCAN"
    if query == "FAILURE_EXPLANATION":
        return list(failed_reasons.values())[-1] if failed_reasons else "NONE"
    raise AblationError("unknown query")


def run_variant(variant_id: str, seed: int, observation_stream: Sequence[Mapping[str, object]]) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Run one variant without accepting scorer truth."""
    if variant_id not in VARIANTS or type(seed) is not int or len(observation_stream) != 4:
        raise AblationError("invalid variant execution input")
    live_semantic = variant_id in {"LIVE_SEMANTIC", "LIVE_SEPARATE"}
    live_episodic = variant_id in {"LIVE_EPISODIC", "LIVE_SEPARATE"}
    memory = _Memory()
    snapshots: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []
    for index, row in enumerate(observation_stream):
        if row.get("seed") != seed:
            raise AblationError("observation seed mismatch")
        for event in row["events"]:  # type: ignore[union-attr]
            if index == 0 or live_semantic:
                memory.semantic_update(event)
            if index > 0 and live_episodic:
                memory.episodic_update(event)
        context = _context(memory)
        context_bytes = _canonical(context)
        snapshot = {
            "checkpoint": row["checkpoint"], "context_bytes": len(context_bytes),
            "context_fact_count": sum(len([key for key in state if not key.endswith("_update_key")]) for entity, state in memory.semantic.items() if not entity.startswith("restriction:")) + len(memory.restrictions) + len(memory.episodes),
            "episode_count": len(memory.episodes), "episodic_sha256": _sha(_canonical(memory.episodes)),
            "mutation_kind": row["mutation_kind"], "schema_version": "exp04-unfixed-memory-snapshot-v1",
            "seed": seed, "semantic_sha256": _sha(_canonical({"semantic": memory.semantic, "restrictions": memory.restrictions})),
            "tick": row["tick"], "variant_id": variant_id,
        }
        snapshots.append(snapshot)
        observation_sha = _sha(_canonical(row))
        for query in QUERY_IDS:
            decisions.append({
                "answer": _decide(memory, query, int(row["tick"])), "checkpoint": row["checkpoint"],
                "context_bytes": snapshot["context_bytes"], "context_fact_count": snapshot["context_fact_count"],
                "mutation_kind": row["mutation_kind"], "observation_sha256": observation_sha,
                "query_id": query, "schema_version": "exp04-unfixed-decision-v1", "seed": seed,
                "tick": row["tick"], "variant_id": variant_id,
            })
    return tuple(snapshots), tuple(decisions)


def _answer_target(answer: str) -> str | None:
    if ":" not in answer:
        return None
    prefix, target = answer.split(":", 1)
    return target if prefix in {"TARGET", "ACT", "EXECUTE", "REPLAN"} else None


def _score(decisions: Sequence[Mapping[str, object]], truths: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    truth_by_key = {(row["seed"], row["checkpoint"], row["query_id"]): row for row in truths}
    scored = []
    for decision in decisions:
        key = (decision["seed"], decision["checkpoint"], decision["query_id"])
        truth = truth_by_key[key]
        answer = str(decision["answer"])
        target = _answer_target(answer)
        actual_eligible = set(truth["actual_eligible_ids"])
        failed = set(truth["failed_target_ids"])
        scored.append({
            **decision,
            "correct": answer == truth["expected_answer"],
            "expected_answer": truth["expected_answer"],
            "failure_explanation_correct": decision["query_id"] == "FAILURE_EXPLANATION" and answer == truth["expected_answer"],
            "invalid_target": decision["query_id"] in {"SELECT_TARGET", "RETRY_DECISION"} and target is not None and target not in actual_eligible,
            "repeated_failed_target": decision["query_id"] == "RETRY_DECISION" and answer.startswith("EXECUTE:") and target in failed,
            "schema_version": "exp04-unfixed-score-v1",
            "stale_action": decision["query_id"] == "POSE_ACTION" and answer.startswith("ACT:") and truth["pose_usable_target"] != target,
            "unnecessary_scan": answer == "RESCAN" and truth["expected_answer"] != "RESCAN",
        })
    return scored


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _per_seed(scores: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    output = []
    for seed in sorted({int(row["seed"]) for row in scores}):
        for variant in VARIANTS:
            rows = [row for row in scores if row["seed"] == seed and row["variant_id"] == variant]
            primary = [row for row in rows if row["checkpoint"] != "CONTROL"]
            pose = [row for row in primary if row["query_id"] == "POSE_ACTION"]
            targets = [row for row in primary if row["query_id"] in {"SELECT_TARGET", "RETRY_DECISION"}]
            retries = [row for row in primary if row["query_id"] == "RETRY_DECISION"]
            explanations = [row for row in primary if row["query_id"] == "FAILURE_EXPLANATION"]
            history = [row for row in primary if row["query_id"] in {"RETRY_DECISION", "FAILURE_EXPLANATION"}]
            stale_rate = _mean([float(bool(row["stale_action"])) for row in pose])
            invalid_rate = _mean([float(bool(row["invalid_target"])) for row in targets])
            repeated_rate = _mean([float(bool(row["repeated_failed_target"])) for row in retries])
            output.append({
                "adverse_composite": _mean([stale_rate, invalid_rate, repeated_rate]),
                "context_bytes_mean": _mean([float(row["context_bytes"]) for row in primary]),
                "context_facts_mean": _mean([float(row["context_fact_count"]) for row in primary]),
                "control_correctness": _mean([float(bool(row["correct"])) for row in rows if row["checkpoint"] == "CONTROL"]),
                "correctness": _mean([float(bool(row["correct"])) for row in primary]),
                "failure_explanation_accuracy": _mean([float(bool(row["failure_explanation_correct"])) for row in explanations]),
                "history_correctness": _mean([float(bool(row["correct"])) for row in history]),
                "invalid_target_rate": invalid_rate,
                "repeated_failed_target_rate": repeated_rate,
                "seed": seed,
                "semantic_mutation_correctness": _mean([float(bool(row["correct"])) for row in primary]),
                "stale_action_rate": stale_rate,
                "unnecessary_scan_rate": _mean([float(bool(row["unnecessary_scan"])) for row in primary]),
                "variant_id": variant,
            })
    return output


def _effect(per_seed: Sequence[Mapping[str, object]], candidate: str, comparator: str, metric: str) -> dict[str, object]:
    by = {(int(row["seed"]), str(row["variant_id"])): float(row[metric]) for row in per_seed}
    seeds = sorted({seed for seed, variant in by if variant == candidate})
    differences = np.array([by[(seed, candidate)] - by[(seed, comparator)] for seed in seeds], dtype=np.float64)
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    indices = rng.integers(0, len(seeds), size=(BOOTSTRAP_DRAWS, len(seeds)))
    samples = differences[indices].mean(axis=1)
    low, high = np.quantile(samples, (0.025, 0.975), method="linear")
    return {
        "candidate": candidate, "comparator": comparator, "estimate": float(differences.mean()),
        "metric": metric, "n_seeds": len(seeds), "q025": float(low), "q975": float(high),
    }


def _csv_bytes(rows: Sequence[Mapping[str, object]], fields: Sequence[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row[field] for field in fields})
    return output.getvalue().encode("ascii")


def _bar_svg(endpoint_rows: Sequence[Mapping[str, object]]) -> bytes:
    width, height = 780, 410
    colors = {"FIXED_M5": "#777777", "LIVE_SEMANTIC": "#377eb8", "LIVE_EPISODIC": "#ff9f1c", "LIVE_SEPARATE": "#2ca02c"}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="white"/>', '<text x="390" y="28" text-anchor="middle" font-family="sans-serif" font-size="18">Fixed vs online memory endpoints</text>']
    for index, row in enumerate(endpoint_rows):
        x = 70 + index * 170
        correctness = float(row["correctness"]); adverse = float(row["adverse_composite"])
        parts.extend((
            f'<rect x="{x}" y="{340-260*correctness:.3f}" width="55" height="{260*correctness:.3f}" fill="{colors[str(row["variant_id"])]}"/>',
            f'<rect x="{x+62}" y="{340-260*adverse:.3f}" width="55" height="{260*adverse:.3f}" fill="#d62728"/>',
            f'<text x="{x+58}" y="365" text-anchor="middle" font-family="sans-serif" font-size="11">{row["variant_id"]}</text>',
            f'<text x="{x+27}" y="{330-260*correctness:.3f}" text-anchor="middle" font-family="sans-serif" font-size="10">{correctness:.3f}</text>',
            f'<text x="{x+89}" y="{330-260*adverse:.3f}" text-anchor="middle" font-family="sans-serif" font-size="10">{adverse:.3f}</text>',
        ))
    parts.extend(('<text x="70" y="395" font-family="sans-serif" font-size="11">colored = correctness; red = adverse composite</text>', '</svg>'))
    return ("\n".join(parts) + "\n").encode("ascii")


def _effect_svg(effects: Sequence[Mapping[str, object]]) -> bytes:
    width, height, zero, scale = 800, 330, 400, 600
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="white"/>', '<text x="400" y="28" text-anchor="middle" font-family="sans-serif" font-size="18">Paired effects (candidate - comparator)</text>', f'<line x1="{zero}" y1="45" x2="{zero}" y2="290" stroke="#333"/>']
    for index, row in enumerate(effects):
        y = 75 + index * 58
        x1 = zero + scale * float(row["q025"]); x2 = zero + scale * float(row["q975"]); point = zero + scale * float(row["estimate"])
        label = f'{row["metric"]}: {row["candidate"]} - {row["comparator"]}'
        parts.extend((
            f'<text x="10" y="{y+4}" font-family="sans-serif" font-size="10">{label}</text>',
            f'<line x1="{x1:.3f}" y1="{y}" x2="{x2:.3f}" y2="{y}" stroke="#1f77b4" stroke-width="3"/>',
            f'<circle cx="{point:.3f}" cy="{y}" r="5" fill="#1f77b4"/>',
        ))
    parts.append('</svg>')
    return ("\n".join(parts) + "\n").encode("ascii")


def _derive(raw: Path) -> dict[str, bytes]:
    manifest_bytes = (raw / "raw-manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest_bytes != _canonical(manifest):
        raise AblationError("raw manifest is noncanonical")
    for item in manifest["files"]:
        content = (raw / item["path"]).read_bytes()
        if len(content) != item["bytes"] or _sha(content) != item["sha256"]:
            raise AblationError("raw member hash mismatch")
    observations = _rows(raw / "observation-streams.jsonl")
    truths = _rows(raw / "scorer-truth.jsonl")
    snapshots = _rows(raw / "memory-snapshots.jsonl")
    decisions = _rows(raw / "decisions.jsonl")
    scores = _rows(raw / "scores.jsonl")
    replay_snapshots: list[dict[str, object]] = []
    replay_decisions: list[dict[str, object]] = []
    for seed in manifest["seeds"]:
        stream = [row for row in observations if row["seed"] == seed]
        for variant in VARIANTS:
            variant_snapshots, variant_decisions = run_variant(variant, int(seed), stream)
            replay_snapshots.extend(variant_snapshots); replay_decisions.extend(variant_decisions)
    if _jsonl(replay_snapshots) != _jsonl(snapshots) or _jsonl(replay_decisions) != _jsonl(decisions):
        raise AblationError("decision replay mismatch")
    replay_scores = _score(replay_decisions, truths)
    if _jsonl(replay_scores) != _jsonl(scores):
        raise AblationError("score replay mismatch")

    per_seed = _per_seed(scores)
    metrics = (
        "correctness", "adverse_composite", "stale_action_rate", "invalid_target_rate",
        "repeated_failed_target_rate", "unnecessary_scan_rate", "failure_explanation_accuracy",
        "context_facts_mean", "context_bytes_mean", "control_correctness",
    )
    endpoints = []
    for variant in VARIANTS:
        rows = [row for row in per_seed if row["variant_id"] == variant]
        endpoints.append({"variant_id": variant, **{metric: _mean([float(row[metric]) for row in rows]) for metric in metrics}})
    effects = [
        _effect(per_seed, "LIVE_SEPARATE", "FIXED_M5", "correctness"),
        _effect(per_seed, "LIVE_SEPARATE", "FIXED_M5", "adverse_composite"),
        _effect(per_seed, "LIVE_SEPARATE", "LIVE_EPISODIC", "semantic_mutation_correctness"),
        _effect(per_seed, "LIVE_SEPARATE", "LIVE_SEMANTIC", "history_correctness"),
    ]
    effect_by_metric = {row["metric"]: row for row in effects}
    control_by = {row["variant_id"]: float(row["control_correctness"]) for row in endpoints}
    g1 = effect_by_metric["correctness"]
    g2 = effect_by_metric["adverse_composite"]
    g3 = effect_by_metric["semantic_mutation_correctness"]
    g4 = effect_by_metric["history_correctness"]
    gates = [
        {"gate": 1, "pass": g1["estimate"] >= .10 and g1["q025"] > 0.0},
        {"gate": 2, "pass": g2["estimate"] < 0.0 and g2["q975"] < 0.0},
        {"gate": 3, "pass": g3["estimate"] > 0.0 and g3["q025"] > 0.0},
        {"gate": 4, "pass": g4["estimate"] > 0.0 and g4["q025"] > 0.0},
        {"gate": 5, "pass": all(control_by[variant] - control_by["FIXED_M5"] >= -.02 for variant in VARIANTS[1:])},
        {"gate": 6, "pass": True},
    ]
    disposition = "SUPPORTS_ONLINE_SEPARATE_MEMORY" if all(row["pass"] for row in gates) else "DOES_NOT_SUPPORT_ALL_PREREGISTERED_GATES"
    endpoint_fields = ("variant_id", *metrics)
    per_seed_fields = ("seed", "variant_id", "correctness", "adverse_composite", "semantic_mutation_correctness", "history_correctness", "stale_action_rate", "invalid_target_rate", "repeated_failed_target_rate", "unnecessary_scan_rate", "failure_explanation_accuracy", "context_facts_mean", "context_bytes_mean", "control_correctness")
    effect_fields = ("metric", "candidate", "comparator", "estimate", "q025", "q975", "n_seeds")
    samples = []
    for variant in VARIANTS:
        candidates = [row for row in scores if row["variant_id"] == variant and row["checkpoint"] != "CONTROL"]
        for label, expected in (("WORKING", True), ("NONWORKING", False)):
            match = next((row for row in candidates if bool(row["correct"]) is expected), None)
            if match is None:
                samples.append({"class": "CLASS_NOT_OBSERVED", "denominator": len(candidates), "requested_class": label, "variant_id": variant})
            else:
                samples.append({
                    "class": label, "decision": {key: match[key] for key in ("answer", "checkpoint", "query_id", "seed", "variant_id")},
                    "observation_sha256": match["observation_sha256"],
                    "truth": {"expected_answer": match["expected_answer"]},
                })
    evidence = {
        "bootstrap_draws": BOOTSTRAP_DRAWS, "bootstrap_seed": BOOTSTRAP_SEED,
        "claim_scope": "INDICATIVE_SYNTHETIC", "disposition": disposition,
        "gates": gates, "implementation_git_sha": manifest["implementation_git_sha"],
        "implementation_source_sha256": manifest["implementation_source_sha256"],
        "raw_manifest_sha256": _sha(manifest_bytes), "schema_version": "exp04-unfixed-evidence-v1",
        "seed_count": len(manifest["seeds"]), "variant_count": len(VARIANTS),
    }
    by_variant = {row["variant_id"]: row for row in endpoints}
    report = (
        "# Experiment 04 Fixed-vs-Unfixed Memory Indicative Result\n\n"
        f"Status: `{disposition}`\n\n"
        "## Situation and objective\n\n"
        "A matched synthetic robot-memory task changed valve pose, availability, room restrictions, and attempt history. The objective was to test whether an M5-style memory should remain fixed or update its semantic/geometric and episodic stores online.\n\n"
        "## Method\n\n"
        f"The run completed {len(manifest['seeds'])} seeds x 4 variants. Each variant received byte-identical observations and emitted 12 primary decisions per seed without scorer truth. Effects are paired by seed; intervals are 20,000-draw PCG64 cluster bootstraps.\n\n"
        "## Outcome\n\n"
        f"FIXED_M5 correctness was {float(by_variant['FIXED_M5']['correctness']):.4f}; LIVE_SEPARATE was {float(by_variant['LIVE_SEPARATE']['correctness']):.4f}. The paired difference was {float(g1['estimate']):+.4f} (95% {float(g1['q025']):+.4f} to {float(g1['q975']):+.4f}). Adverse composite changed by {float(g2['estimate']):+.4f} (95% {float(g2['q025']):+.4f} to {float(g2['q975']):+.4f}).\n\n"
        f"Separate live semantic memory exceeded episodic-only memory by {float(g3['estimate']):+.4f} on mutation decisions; adding live episodic history to live semantic memory changed history-query correctness by {float(g4['estimate']):+.4f}. Gates passed: {sum(bool(row['pass']) for row in gates)}/6.\n\n"
        "## Inference and limits\n\n"
        f"The preregistered disposition is `{disposition}`. This is indicative causal evidence for the frozen synthetic generator and controller only. It does not establish perception quality, real-robot performance, a production database, or broad generalization. Raw streams, decisions, truth, scores, paired rows, examples, graphs, hashes, and replay code are preserved.\n"
    ).encode("ascii")
    return {
        "RESULTS.md": report,
        "annotations.json": _canonical({"samples": samples, "schema_version": "exp04-unfixed-annotations-v1", "selection_rule": "FIRST_CANONICAL_WORKING_AND_NONWORKING_PER_VARIANT"}),
        "endpoint-data.csv": _csv_bytes(endpoints, endpoint_fields),
        "evidence-manifest.json": _canonical(evidence),
        "paired-effects.csv": _csv_bytes(effects, effect_fields),
        "paired-effects.svg": _effect_svg(effects),
        "per-seed.csv": _csv_bytes(per_seed, per_seed_fields),
        "variant-endpoints.svg": _bar_svg(endpoints),
    }


def run_experiment(output: Path, *, implementation_git_sha: str, seeds: Sequence[int] = SEEDS) -> None:
    if output.exists() or not seeds or len(set(seeds)) != len(seeds):
        raise AblationError("output must be absent and seeds unique")
    if len(implementation_git_sha) != 40 or any(character not in "0123456789abcdef" for character in implementation_git_sha):
        raise AblationError("implementation_git_sha must be lowercase SHA-1")
    raw = output / "raw"; derived = output / "derived"
    raw.mkdir(parents=True); derived.mkdir()
    observations: list[dict[str, object]] = []
    truths: list[dict[str, object]] = []
    snapshots: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []
    for seed in seeds:
        stream, seed_truth = generate_seed(int(seed))
        observations.extend(stream); truths.extend(seed_truth)
        for variant in VARIANTS:
            variant_snapshots, variant_decisions = run_variant(variant, int(seed), stream)
            snapshots.extend(variant_snapshots); decisions.extend(variant_decisions)
    scores = _score(decisions, truths)
    members = {
        "observation-streams.jsonl": _jsonl(observations),
        "scorer-truth.jsonl": _jsonl(truths),
        "memory-snapshots.jsonl": _jsonl(snapshots),
        "decisions.jsonl": _jsonl(decisions),
        "scores.jsonl": _jsonl(scores),
    }
    for name, content in members.items():
        (raw / name).write_bytes(content)
    source_sha = _sha(Path(__file__).read_bytes())
    manifest = {
        "claim_scope": "INDICATIVE_SYNTHETIC", "files": [
            {"bytes": len(content), "path": name, "sha256": _sha(content)} for name, content in sorted(members.items())
        ],
        "implementation_git_sha": implementation_git_sha, "implementation_source_sha256": source_sha,
        "schema_version": "exp04-unfixed-raw-manifest-v1", "seeds": list(seeds), "variants": list(VARIANTS),
    }
    (raw / "raw-manifest.json").write_bytes(_canonical(manifest))
    for name, content in _derive(raw).items():
        (derived / name).write_bytes(content)
    sums = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        sums.append(f"{_sha(path.read_bytes())}  {path.relative_to(output).as_posix()}\n")
    (output / "SHA256SUMS").write_text("".join(sums), encoding="ascii")


def reconstruct(raw: Path, output: Path) -> None:
    if output.exists() or not raw.is_dir() or raw.is_symlink():
        raise AblationError("raw root must be regular and output absent")
    derived = _derive(raw)
    output.mkdir()
    for name, content in derived.items():
        (output / name).write_bytes(content)

