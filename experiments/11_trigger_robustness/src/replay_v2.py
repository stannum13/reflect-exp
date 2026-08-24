"""Independent Experiment 11 V2 raw-ledger replay scorer.

No executor module is imported.  This implementation separately specifies the
world, transport, storage, trigger, action, and terminal transition rules.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


PLANNER_ID = "DETERMINISTIC_TYPED_ORACLE_V2"


class ReplayError(ValueError):
    pass


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _unit(seed: int, *labels: object) -> float:
    preimage = "|".join((str(seed), *(str(label) for label in labels))).encode("ascii")
    return int.from_bytes(hashlib.sha256(preimage).digest()[:8], "big") / 2**64


def _initial(seed: int) -> dict[str, Any]:
    shift = int(_unit(seed, "layout") * 3)
    return {
        "entities": {
            name: {"available": True, "pose": [index + shift, index % 2, 0], "room": f"room_{(index + shift) % 3}"}
            for index, name in enumerate(("valve_a", "valve_b", "valve_c"))
        },
        "restrictions": {"room_0": False, "room_1": False, "room_2": False},
    }


def _plan(view: Mapping[str, Any], excluded: set[str]) -> dict[str, Any]:
    valid = [
        name for name in sorted(view["entities"], key=lambda item: (view["entities"][item]["room"], item))
        if view["entities"][name]["available"] and not view["restrictions"][view["entities"][name]["room"]]
    ]
    alternatives = [name for name in valid if name not in excluded]
    chosen = (alternatives or valid or [None])[0]
    return {"affordance": "service_valve", "planner_id": PLANNER_ID,
            "pose": view["entities"].get(chosen, {}).get("pose"), "target": chosen}


def _event(world: Mapping[str, Any], family: str, severity: str, target: str, tick: int) -> dict[str, Any]:
    amount = 2 if severity == "HIGH" else 1
    if family == "POSE_SHIFT":
        pose = list(world["entities"][target]["pose"])
        pose[0] += amount
        return {"kind": "POSE", "subject": target, "value": pose, "source_tick": tick, "truth": True}
    if family == "AVAILABILITY_LOSS":
        return {"kind": "AVAILABILITY", "subject": target, "value": False, "source_tick": tick, "truth": True}
    if family == "RESTRICTION_CHANGE":
        room = world["entities"][target]["room"]
        return {"kind": "RESTRICTION", "subject": room, "value": True, "source_tick": tick, "truth": True}
    if family == "CONTROL_FAILURE":
        return {"kind": "CONTROL_FAILURE", "subject": target, "value": amount + 1, "source_tick": tick, "truth": True}
    raise ReplayError("unknown disturbance family")


def _apply(state: dict[str, Any], event: Mapping[str, Any]) -> None:
    if event["kind"] == "POSE":
        state["entities"][event["subject"]]["pose"] = list(event["value"])
    elif event["kind"] == "AVAILABILITY":
        state["entities"][event["subject"]]["available"] = bool(event["value"])
    elif event["kind"] == "RESTRICTION":
        state["restrictions"][event["subject"]] = bool(event["value"])


def _messages(cell: Mapping[str, Any], event: Mapping[str, Any], quality: Mapping[str, Any], last_tick: int) -> list[dict[str, Any]]:
    seed, source = int(cell["seed"]), int(event["source_tick"])
    output: list[dict[str, Any]] = []
    identity = (cell["disturbance_family"], cell["severity"], cell["horizon"], seed)
    if _unit(seed, *identity, "recall") < float(quality["recall"]):
        for copy_index in range(int(quality["duplicate"]) + 1):
            lag = int(quality["delay"]) + int(bool(quality["out_of_order"]) and copy_index == 0)
            output.append({
                **event, "delivery_tick": min(last_tick, source + lag), "duplicate_index": copy_index,
                "message_id": f"true-{source}-{copy_index}",
                "prompt_bytes": 48 if cell["prompt_envelope"] == "COMPACT_TYPED" else 192,
            })
    for false_index in range(int(quality["false_burst"])):
        output.append({
            "delivery_tick": min(last_tick, source + false_index % 2), "duplicate_index": 0,
            "kind": "POSE", "message_id": f"false-{source}-{false_index}",
            "prompt_bytes": 48 if cell["prompt_envelope"] == "COMPACT_TYPED" else 192,
            "source_tick": source, "subject": f"valve_{chr(97 + (false_index + 1) % 3)}",
            "truth": False, "value": [99, 99, 99],
        })
    output.sort(key=lambda message: (message["delivery_tick"], -int(message["source_tick"]), message["message_id"]))
    return output


def _valid(world: Mapping[str, Any], plan: Mapping[str, Any]) -> bool:
    target = plan.get("target")
    return bool(
        target in world["entities"]
        and world["entities"][target]["available"]
        and not world["restrictions"][world["entities"][target]["room"]]
        and plan.get("pose") == world["entities"][target]["pose"]
    )


def _replay(start: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cell = dict(start["cell"])
    quality = next((row for row in config["quality_profiles"] if row["id"] == cell["quality_id"]), None)
    if quality is None:
        raise ReplayError("unknown quality profile")
    horizon = int(cell["horizon"])
    last_tick = horizon + int(config["recovery_allowance_ticks"])
    world = _initial(int(cell["seed"]))
    belief = _copy(world)
    failures_set: set[str] = set()
    plan = _plan(belief, failures_set)
    disturbance_tick = max(2, horizon // 2)
    true_event = _event(world, str(cell["disturbance_family"]), str(cell["severity"]), str(plan["target"]), disturbance_tick)
    expected_start = {"cell": cell, "expected_tick_count": last_tick, "initial_plan": plan, "initial_world": _copy(world),
                      "planner_disclaimer": "DETERMINISTIC_TYPED_ORACLE_NOT_VLA", "true_event": true_event}
    if start != expected_start:
        raise ReplayError("start ledger mismatch")
    schedule = _messages(cell, true_event, quality, last_tick)
    cooldown_until = evidence_streak = consecutive_failures = progress = retries = fault_remaining = 0
    reads = writes = byte_count = latest_write = switches = 0
    previous_target = plan["target"]
    observed_messages: set[str] = set()
    expected_ticks: list[dict[str, Any]] = []
    for tick in range(1, last_tick + 1):
        world_events: list[dict[str, Any]] = []
        if tick == disturbance_tick:
            world_events.append(true_event)
            _apply(world, true_event)
            if true_event["kind"] == "CONTROL_FAILURE":
                fault_remaining = int(true_event["value"])
        receipts = [message for message in schedule if int(message["delivery_tick"]) == tick]
        new_receipts = [message for message in receipts if message["message_id"] not in observed_messages]
        observed_messages.update(message["message_id"] for message in receipts)
        evidence_streak = evidence_streak + 1 if new_receipts else 0
        policy = str(cell["trigger_policy"])
        requested, reason = False, "NONE"
        if policy == "PERIODIC_ONLY" and tick % int(config["period_ticks"]) == 0:
            requested, reason = True, "PERIODIC"
        elif policy == "FAILURE_THRESHOLD" and consecutive_failures >= int(config["failure_threshold"]):
            requested, reason = True, "FAILURE"
        elif policy == "EVENT_DRIVEN" and new_receipts:
            requested, reason = True, "EVENT"
        elif policy == "HYBRID":
            if new_receipts and evidence_streak >= int(quality["hysteresis"]):
                requested, reason = True, "EVENT"
            elif consecutive_failures >= int(config["failure_threshold"]):
                requested, reason = True, "FAILURE"
            elif tick % int(config["period_ticks"]) == 0:
                requested, reason = True, "PERIODIC"
        wake = requested and tick >= cooldown_until
        if requested and not wake:
            reason = "COOLDOWN_SUPPRESSED"
        old_plan = _copy(plan)
        if wake:
            for message in new_receipts:
                if message["truth"]:
                    _apply(belief, message)
            writes += len(new_receipts)
            latest_write = tick if new_receipts else latest_write
            byte_count += sum(len(_bytes(message)) for message in new_receipts)
            reads += 1
            excluded = failures_set if cell["storage_variant"] == "LIVE_EPISODIC" else set()
            plan = _plan(belief, excluded)
            cooldown_until = tick + int(quality["cooldown"])
        valid = _valid(world, plan)
        successful = valid
        if successful and fault_remaining and plan["target"] == true_event["subject"]:
            successful = False
            fault_remaining -= 1
        if successful:
            progress += 1
            consecutive_failures = 0
        else:
            retries += 1
            consecutive_failures += 1
            if cell["storage_variant"] == "LIVE_EPISODIC" and consecutive_failures >= 2:
                failures_set.add(str(plan["target"]))
        switches += int(plan["target"] != previous_target)
        previous_target = plan["target"]
        expected_ticks.append({
            "action": {"success": successful, "target": plan["target"], "valid": valid}, "delivered_messages": receipts,
            "episode_id": cell["episode_id"], "failures_after": consecutive_failures, "plan_after": _copy(plan), "plan_before": old_plan,
            "progress_after": progress, "storage": {"age": max(0, tick - latest_write), "bytes": byte_count, "reads": reads, "writes": writes},
            "tick": tick, "trigger": {"reason": reason, "requested": requested, "wake": wake}, "true_events": world_events, "world_after": _copy(world),
        })
    wakes = [row for row in expected_ticks if row["trigger"]["wake"]]
    event_wakes = [row for row in wakes if row["trigger"]["reason"] == "EVENT"]
    true_receipts = [message for message in schedule if message["truth"]]
    tp = int(bool(event_wakes and true_receipts))
    fp = sum(1 for row in event_wakes if not any(message["truth"] for message in row["delivered_messages"]))
    latency = event_wakes[0]["tick"] - disturbance_tick if event_wakes else None
    terminal = {
        "completion": progress >= horizon,
        "cost_proxy": len(wakes) * 5 + reads + writes + retries * 2 + sum(int(message["prompt_bytes"]) / 48 for row in expected_ticks for message in row["delivered_messages"]),
        "episode_id": cell["episode_id"], "escalation_failure": sum(row["trigger"]["reason"] == "FAILURE" and row["trigger"]["wake"] for row in expected_ticks),
        "escalation_event": sum(row["trigger"]["reason"] == "EVENT" and row["trigger"]["wake"] for row in expected_ticks),
        "false_wakes": fp, "late_wakes": int(latency is None or latency > 2), "progress": progress, "retries": retries,
        "storage_age": max(0, last_tick - latest_write), "storage_bytes": byte_count, "storage_reads": reads, "storage_writes": writes,
        "terminal_tick": last_tick + 1, "thrash": switches, "trigger_fn": 1 - tp, "trigger_latency": latency,
        "trigger_precision": tp / max(1, tp + fp), "trigger_recall": float(tp), "wakes": len(wakes),
        "wasted_wakes": sum(1 for row in wakes if row["plan_before"] == row["plan_after"]),
    }
    return expected_ticks, terminal


def score_episode(start: Mapping[str, Any], ticks: Sequence[Mapping[str, Any]], terminal: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    expected_ticks, expected_terminal = _replay(start, config)
    if list(ticks) != expected_ticks:
        raise ReplayError("tick/action ledger mismatch")
    if dict(terminal) != expected_terminal:
        raise ReplayError("terminal ledger mismatch")
    return {**expected_terminal, "tick_count": len(expected_ticks)}
