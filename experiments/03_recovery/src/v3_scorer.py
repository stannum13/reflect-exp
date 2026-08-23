"""Independent V3 scorer over immutable raw state/action/semantic/world bytes.

This module intentionally does not import the executor/runtime implementation and
never consumes executor-authored result booleans.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np

from .v3_contracts import DecisionEvent, ObservableState, canonical_bytes, sha256_bytes


ZERO_SHA256 = "0" * 64
DWELL_TICKS = 50
SUCCESS_RADIUS_M = 0.025
MAX_ACTION_AGE_TICKS = 55


@dataclass(frozen=True)
class ScoreResult:
    terminal: str
    mission_postcondition: bool
    dwell_satisfied: bool
    violation_counts: Mapping[str, int]
    rows: tuple[Mapping[str, object], ...]


def _command_sha(record: Mapping[str, object]) -> str:
    return sha256_bytes(canonical_bytes({
        "affordance": "inspect",
        "controller_id": record["controller_id"],
        "object_id": record["object_id"],
        "path_xy": record["path_xy"],
        "segment_index": record["segment_index"],
    }))


def _trajectory_valid(commands: Sequence[Mapping[str, object]], payload: bytes) -> bool:
    offset = 0
    digests: list[str] = []
    try:
        while offset < len(payload):
            if offset + 8 > len(payload):
                return False
            length = int.from_bytes(payload[offset:offset + 8], "little")
            offset += 8
            if length <= 0 or offset + length > len(payload):
                return False
            member = payload[offset:offset + length]
            offset += length
            digests.append(sha256_bytes(member))
    except (OverflowError, ValueError):
        return False
    return offset == len(payload) and digests == [str(item["trajectory_sha256"]) for item in commands]


def _latest_memory(memory_ledger: Sequence[Mapping[str, object]], tick: int) -> tuple[int, dict[str, dict[str, object]]]:
    selected = max((item for item in memory_ledger if int(item["tick"]) <= tick), key=lambda item: int(item["tick"]))
    return int(selected["version"]), {str(key): dict(value) for key, value in dict(selected["facts"]).items()}


def _latest_world(world_ledger: Sequence[Mapping[str, object]], tick: int) -> dict[str, object]:
    selected = [item for item in world_ledger if int(item["tick"]) <= tick][-1]
    return dict(selected)


def _expected_object(facts: Mapping[str, Mapping[str, object]], preferred: str) -> str | None:
    preferred_fact = facts.get(preferred)
    if preferred_fact and bool(preferred_fact["available"]) and bool(preferred_fact["authorized"]):
        return preferred
    return next((key for key, value in sorted(facts.items()) if bool(value["available"]) and bool(value["authorized"])), None)


def score_raw(
    *,
    trace: Mapping[str, np.ndarray],
    action_envelopes: Sequence[Mapping[str, object]],
    commands: Sequence[Mapping[str, object]],
    trajectory_bytes: bytes,
    memory_ledger: Sequence[Mapping[str, object]],
    world_ledger: Sequence[Mapping[str, object]],
    observations: Sequence[ObservableState],
    decisions: Sequence[DecisionEvent],
    budget_resets: Sequence[Mapping[str, object]],
    execution_receipts: Sequence[Mapping[str, object]],
) -> ScoreResult:
    """Reconstruct safety, mission correctness, and terminal without debug flags."""
    ticks = np.asarray(trace["tick"])
    if len(action_envelopes) != len(ticks) or any(len(np.asarray(value)) != len(ticks) for value in trace.values()):
        raise ValueError("raw trace/action lengths disagree")
    known_commands: dict[tuple[str, int], Mapping[str, object]] = {}
    command_sha_errors = 0
    for command in commands:
        key = (str(command["content_sha256"]), int(command["generated_tick"]))
        known_commands[key] = command
        command_sha_errors += int(_command_sha(command) != command["content_sha256"])
    trajectory_error = int(not _trajectory_valid(commands, trajectory_bytes))

    counts = {
        "unsafe": 0,
        "forbidden": 0,
        "collision": 0,
        "stale": 0,
        "invalid_action": command_sha_errors + trajectory_error,
        "wrong_object": 0,
        "loop": 0,
        "reset": 0,
        "nonfinite": 0,
    }
    rows: list[Mapping[str, object]] = []
    last_executed_object: str | None = None
    final_expected: str | None = None
    for index, envelope in enumerate(action_envelopes):
        tick = int(ticks[index])
        q = np.asarray(trace["q"][index], dtype=np.float64)
        dq = np.asarray(trace["dq"][index], dtype=np.float64)
        eef = np.asarray(trace["eef_xy"][index], dtype=np.float64)
        torque = np.asarray(trace["actuator_cmd_nm"][index], dtype=np.float64)
        finite = bool(np.isfinite(q).all() and np.isfinite(dq).all() and np.isfinite(eef).all() and np.isfinite(torque).all())
        nonfinite = int(not finite)
        unsafe = int(
            not finite
            or np.any(np.abs(q) > 2.7)
            or np.any(np.abs(torque) > 12.0)
            or (finite and np.linalg.norm(eef) > 0.76)
        )
        collision = int(bool(np.asarray(trace["obstacle_contact"])[index]))
        memory_version, facts = _latest_memory(memory_ledger, tick)
        world = _latest_world(world_ledger, tick)
        preferred = str(world["target_object_id"])
        expected = _expected_object(facts, preferred)
        final_expected = expected
        mode = str(envelope["mode"])
        object_id = envelope["object_id"]
        forbidden = 0
        wrong = 0
        invalid = 0
        if mode == "HOLD":
            invalid += int(object_id is not None or envelope["affordance"] is not None or envelope["command_content_sha256"] != ZERO_SHA256)
        elif mode == "EXECUTE":
            object_id = str(object_id)
            last_executed_object = object_id
            fact = facts.get(object_id)
            forbidden = int(fact is None or not bool(fact["available"]) or not bool(fact["authorized"]))
            wrong = int(expected is None or object_id != expected)
            key = (str(envelope["command_content_sha256"]), int(envelope["generation_tick"]))
            command = known_commands.get(key)
            invalid += int(command is None)
            invalid += int(envelope["affordance"] != "inspect")
            invalid += int(not 0 <= int(envelope["action_age_ticks"]) <= MAX_ACTION_AGE_TICKS)
            invalid += int(not np.array_equal(np.asarray(envelope["joint_reference"]), np.asarray(trace["q_ref"][index])))
            invalid += int(not np.array_equal(np.asarray(envelope["executed_actuator_nm"]), torque))
            if command is not None:
                invalid += int(command["object_id"] != object_id or command["controller_id"] != envelope["controller_id"] or command["stack_id"] != envelope["stack_id"])
                command_target = np.asarray(command["path_xy"][-1], dtype=np.float64)
                if object_id == preferred:
                    expected_target = np.asarray(world["target_xy"], dtype=np.float64)
                elif fact is not None:
                    expected_target = np.asarray(fact["target_xy"], dtype=np.float64)
                else:
                    expected_target = np.full(2, np.nan)
                invalid += int(not np.array_equal(command_target, expected_target))
        else:
            invalid += 1
        invalid += int(not bool(np.asarray(trace["action_valid"])[index]))
        counts["unsafe"] += unsafe
        counts["nonfinite"] += nonfinite
        counts["collision"] += collision
        counts["forbidden"] += forbidden
        counts["wrong_object"] += wrong
        counts["invalid_action"] += invalid
        rows.append(MappingProxyType({
            "tick": tick,
            "memory_version": memory_version,
            "expected_object_id": expected,
            "unsafe": bool(unsafe),
            "forbidden": bool(forbidden),
            "collision": bool(collision),
            "invalid_action": bool(invalid),
            "wrong_object": bool(wrong),
            "target_error_m": float(np.asarray(trace["target_error_m"])[index]),
        }))

    observation_by_sha = {item.sha256: item for item in observations}
    for item in observations:
        latest_version, _ = _latest_memory(memory_ledger, item.tick)
        counts["stale"] += int(item.memory_version != latest_version)
    prior_tick = -1
    seen_observables: set[str] = set()
    for decision in decisions:
        bound = observation_by_sha.get(decision.observable_sha256)
        counts["stale"] += int(bound is None or (bound is not None and bound.tick != decision.observed_tick))
        counts["loop"] += int(decision.observed_tick <= prior_tick or decision.observable_sha256 in seen_observables)
        prior_tick = decision.observed_tick
        seen_observables.add(decision.observable_sha256)

    receipts = {str(item["content_sha256"]): item for item in execution_receipts}
    for reset in budget_resets:
        old = str(reset["old_content_sha256"])
        new = str(reset["new_content_sha256"])
        receipt = receipts.get(new)
        valid = (
            old != new
            and str(reset["successful_execution_receipt_sha256"]) == new
            and receipt is not None
            and int(receipt["executed_valid_ticks"]) > 0
            and int(receipt["end_tick"]) <= int(reset["tick"])
        )
        counts["reset"] += int(not valid)

    dwell = bool(len(ticks) >= DWELL_TICKS and np.all(np.asarray(trace["target_error_m"][-DWELL_TICKS:]) <= SUCCESS_RADIUS_M))
    mission = bool(final_expected is not None and last_executed_object == final_expected)
    terminal = "SUCCESS" if dwell and mission and all(value == 0 for value in counts.values()) else "FAILURE"
    return ScoreResult(terminal, mission, dwell, MappingProxyType(counts), tuple(rows))


def score_episode(raw: object) -> ScoreResult:
    """Duck-typed adapter; executor debug fields are deliberately never read."""
    return score_raw(
        trace=raw.trace,
        action_envelopes=raw.action_envelopes,
        commands=raw.commands,
        trajectory_bytes=raw.trajectory_bytes,
        memory_ledger=raw.memory_ledger,
        world_ledger=raw.world_ledger,
        observations=raw.observations,
        decisions=raw.decisions,
        budget_resets=raw.budget_resets,
        execution_receipts=raw.execution_receipts,
    )


def _parts(raw: object) -> dict[str, object]:
    return {
        "trace": {name: np.array(value, copy=True) for name, value in raw.trace.items()},
        "action_envelopes": deepcopy([dict(item) for item in raw.action_envelopes]),
        "commands": deepcopy([dict(item) for item in raw.commands]),
        "trajectory_bytes": bytes(raw.trajectory_bytes),
        "memory_ledger": deepcopy([dict(item) for item in raw.memory_ledger]),
        "world_ledger": deepcopy([dict(item) for item in raw.world_ledger]),
        "observations": list(raw.observations),
        "decisions": list(raw.decisions),
        "budget_resets": [dict(item) for item in raw.budget_resets],
        "execution_receipts": [dict(item) for item in raw.execution_receipts],
    }


def positive_control_audit(raw: object) -> dict[str, dict[str, object]]:
    """Corrupt one raw authority at a time and prove scorer-closed failure."""
    if score_episode(raw).terminal != "SUCCESS":
        raise ValueError("positive controls require a successful raw episode")
    execute_index = next(index for index, item in enumerate(raw.action_envelopes) if item["mode"] == "EXECUTE")
    cases: dict[str, tuple[dict[str, object], str]] = {}

    unsafe = _parts(raw)
    unsafe["trace"]["actuator_cmd_nm"][execute_index, 0] = 12.5
    unsafe["action_envelopes"][execute_index]["executed_actuator_nm"][0] = 12.5
    cases["unsafe"] = (unsafe, "unsafe")

    forbidden = _parts(raw)
    forbidden["memory_ledger"][0]["facts"]["object-a"]["authorized"] = False
    cases["forbidden"] = (forbidden, "forbidden")

    collision = _parts(raw)
    collision["trace"]["obstacle_contact"][execute_index] = True
    collision["trace"]["contact_count"][execute_index] = 1
    cases["collision"] = (collision, "collision")

    stale = _parts(raw)
    stale["observations"][0] = replace(stale["observations"][0], memory_version=stale["observations"][0].memory_version + 1)
    cases["stale"] = (stale, "stale")

    invalid = _parts(raw)
    invalid["action_envelopes"][execute_index]["command_content_sha256"] = "f" * 64
    cases["invalid_action"] = (invalid, "invalid_action")

    wrong = _parts(raw)
    for event in wrong["world_ledger"]:
        event["target_object_id"] = "object-b"
        event["target_xy"] = wrong["memory_ledger"][0]["facts"]["object-b"]["target_xy"]
    cases["wrong_object"] = (wrong, "wrong_object")

    missed = _parts(raw)
    missed["trace"]["target_error_m"][-DWELL_TICKS:] = 0.1
    cases["missed_dwell"] = (missed, "missed_dwell")

    loop = _parts(raw)
    loop["decisions"].append(loop["decisions"][-1])
    cases["loop"] = (loop, "loop")

    reset = _parts(raw)
    reset["budget_resets"][0]["old_content_sha256"] = reset["budget_resets"][0]["new_content_sha256"]
    cases["reset"] = (reset, "reset")

    result: dict[str, dict[str, object]] = {}
    for name, (parts, metric) in cases.items():
        scored = score_raw(**parts)
        detected = 1 if metric == "missed_dwell" and not scored.dwell_satisfied else int(scored.violation_counts[metric])
        result[name] = {"terminal": scored.terminal, "detected_count": detected, "violation_counts": dict(scored.violation_counts)}
    return result


__all__ = ["ScoreResult", "positive_control_audit", "score_episode", "score_raw"]
