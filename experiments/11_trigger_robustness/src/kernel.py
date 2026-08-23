"""Deterministic typed-oracle world and trigger-transport kernel (not a VLA)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


PLANNER_ID = "DETERMINISTIC_TYPED_ORACLE_V1"
CLAIM_SCOPE = "SYNTHETIC_TYPED_ORACLE_TRIGGER_ENGINEERING_NOT_VLA"


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def unit(seed: int, *parts: object) -> float:
    payload = "|".join((str(seed), *(str(part) for part in parts))).encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") / 2**64


def initial_world(seed: int) -> dict[str, Any]:
    offset = int(unit(seed, "layout") * 3)
    entities = {}
    for index, name in enumerate(("valve_a", "valve_b", "valve_c")):
        room = f"room_{(index + offset) % 3}"
        entities[name] = {"available": True, "pose": [index + offset, index % 2, 0], "room": room}
    return {"entities": entities, "restrictions": {"room_0": False, "room_1": False, "room_2": False}}


def choose_plan(belief: Mapping[str, Any], failed_targets: set[str]) -> dict[str, Any]:
    eligible = sorted(
        (name for name, state in belief["entities"].items()
         if state["available"] and not belief["restrictions"][state["room"]]),
        key=lambda name: (belief["entities"][name]["room"], name),
    )
    alternatives = [name for name in eligible if name not in failed_targets]
    target = (alternatives or eligible or [None])[0]
    return {"affordance":"service_valve", "planner_id":PLANNER_ID, "pose": belief["entities"].get(target, {}).get("pose"), "target":target}


def disturbance(world: dict[str, Any], family: str, severity: str, target: str, tick: int) -> dict[str, Any]:
    magnitude = 2 if severity == "HIGH" else 1
    if family == "POSE_SHIFT":
        value = list(world["entities"][target]["pose"]); value[0] += magnitude
        return {"kind":"POSE", "subject":target, "value":value, "source_tick":tick, "truth":True}
    if family == "AVAILABILITY_LOSS":
        return {"kind":"AVAILABILITY", "subject":target, "value":False, "source_tick":tick, "truth":True}
    if family == "RESTRICTION_CHANGE":
        room = world["entities"][target]["room"]
        return {"kind":"RESTRICTION", "subject":room, "value":True, "source_tick":tick, "truth":True}
    return {"kind":"CONTROL_FAILURE", "subject":target, "value":magnitude + 1, "source_tick":tick, "truth":True}


def apply_event(world: dict[str, Any], event: Mapping[str, Any]) -> None:
    kind, subject = event["kind"], event["subject"]
    if kind == "POSE": world["entities"][subject]["pose"] = list(event["value"])
    elif kind == "AVAILABILITY": world["entities"][subject]["available"] = bool(event["value"])
    elif kind == "RESTRICTION": world["restrictions"][subject] = bool(event["value"])


def message_schedule(cell: Mapping[str, Any], event: Mapping[str, Any], quality: Mapping[str, Any], final_tick: int) -> list[dict[str, Any]]:
    seed = int(cell["seed"]); source = int(event["source_tick"]); rows: list[dict[str, Any]] = []
    if unit(seed, cell["episode_id"], "recall") < float(quality["recall"]):
        count = 1 + int(quality["duplicate"])
        for duplicate in range(count):
            delay = int(quality["delay"])
            if int(quality["out_of_order"]) and duplicate == 0: delay += 1
            delivery = min(final_tick, source + delay)
            rows.append({**event, "delivery_tick":delivery, "message_id":f"true-{source}-{duplicate}", "duplicate_index":duplicate})
    for burst in range(int(quality["false_burst"])):
        delivery = min(final_tick, source + burst % 2)
        rows.append({"delivery_tick":delivery,"duplicate_index":0,"kind":"POSE","message_id":f"false-{source}-{burst}","source_tick":source,
                     "subject":f"valve_{chr(97 + (burst + 1) % 3)}","truth":False,"value":[99,99,99]})
    return sorted(rows, key=lambda row: (row["delivery_tick"], -int(row["source_tick"]), row["message_id"]))


def valid_action(world: Mapping[str, Any], plan: Mapping[str, Any]) -> bool:
    target = plan.get("target")
    if target not in world["entities"]: return False
    state = world["entities"][target]
    return bool(state["available"] and not world["restrictions"][state["room"]] and state["pose"] == plan.get("pose"))


def simulate(cell: Mapping[str, Any], config: Mapping[str, Any], quality: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    horizon = int(cell["horizon"]); final_tick = horizon + int(config["recovery_allowance_ticks"])
    world = initial_world(int(cell["seed"])); belief = json.loads(json.dumps(world)); failed: set[str] = set()
    plan = choose_plan(belief, failed); initial_target = plan["target"]
    event_tick = max(2, horizon // 2); event = disturbance(world, str(cell["disturbance_family"]), str(cell["severity"]), initial_target, event_tick)
    schedule = message_schedule(cell, event, quality, final_tick)
    start = {"cell":dict(cell),"expected_tick_count":final_tick,"initial_plan":plan,"initial_world":json.loads(json.dumps(world)),
             "planner_disclaimer":"DETERMINISTIC_TYPED_ORACLE_NOT_VLA","true_event":event}
    cooldown_until = 0; evidence_run = 0; failures = 0; progress = 0; retries = 0; control_left = 0
    store_reads = 0; store_writes = 0; stored_bytes = 0; last_write = 0; last_target = plan["target"]; target_switches = 0
    seen_messages: set[str] = set(); ticks = []
    for tick in range(1, final_tick + 1):
        true_events = []
        if tick == event_tick:
            true_events = [event]; apply_event(world, event)
            if event["kind"] == "CONTROL_FAILURE": control_left = int(event["value"])
        delivered = [row for row in schedule if row["delivery_tick"] == tick]
        novel = [row for row in delivered if row["message_id"] not in seen_messages]
        for row in delivered: seen_messages.add(row["message_id"])
        if novel: evidence_run += 1
        else: evidence_run = 0
        policy = str(cell["trigger_policy"]); reason = "NONE"; requested = False
        if policy == "PERIODIC_ONLY" and tick % int(config["period_ticks"]) == 0: requested, reason = True, "PERIODIC"
        elif policy == "FAILURE_THRESHOLD" and failures >= int(config["failure_threshold"]): requested, reason = True, "FAILURE"
        elif policy == "EVENT_DRIVEN" and novel: requested, reason = True, "EVENT"
        elif policy == "HYBRID":
            if novel and evidence_run >= int(quality["hysteresis"]): requested, reason = True, "EVENT"
            elif failures >= int(config["failure_threshold"]): requested, reason = True, "FAILURE"
            elif tick % int(config["period_ticks"]) == 0: requested, reason = True, "PERIODIC"
        wake = requested and tick >= cooldown_until
        if requested and not wake: reason = "COOLDOWN_SUPPRESSED"
        before = json.loads(json.dumps(plan))
        if wake:
            for row in novel:
                if row["truth"]: apply_event(belief, row)
            store_writes += len(novel); last_write = tick if novel else last_write
            stored_bytes += sum(len(canonical(row)) for row in novel)
            store_reads += 1
            if cell["storage_variant"] == "LIVE_EPISODIC": failed_for_plan = failed
            else: failed_for_plan = set()
            plan = choose_plan(belief, failed_for_plan)
            cooldown_until = tick + int(quality["cooldown"])
        action_valid = valid_action(world, plan); success = action_valid
        if success and control_left and plan["target"] == event["subject"]:
            success = False; control_left -= 1
        if success: progress += 1; failures = 0
        else:
            retries += 1; failures += 1
            if cell["storage_variant"] == "LIVE_EPISODIC" and failures >= 2: failed.add(str(plan["target"]))
        if plan["target"] != last_target: target_switches += 1
        last_target = plan["target"]
        ticks.append({"action":{"success":success,"target":plan["target"],"valid":action_valid},"delivered_messages":delivered,"episode_id":cell["episode_id"],
                      "failures_after":failures,"plan_after":plan,"plan_before":before,"progress_after":progress,"storage":{"age":max(0,tick-last_write),"bytes":stored_bytes,"reads":store_reads,"writes":store_writes},
                      "tick":tick,"trigger":{"reason":reason,"requested":requested,"wake":wake},"true_events":true_events,"world_after":json.loads(json.dumps(world))})
    true_deliveries = [row for row in schedule if row["truth"]]
    wakes = [row for row in ticks if row["trigger"]["wake"]]
    event_wakes = [row for row in wakes if row["trigger"]["reason"] == "EVENT"]
    tp = int(bool(event_wakes and true_deliveries)); fp = sum(1 for row in wakes if row["trigger"]["reason"] == "EVENT" and not any(m["truth"] for m in row["delivered_messages"]))
    latency = (event_wakes[0]["tick"] - event_tick) if event_wakes else None
    terminal = {"completion":progress >= horizon,"cost_proxy":len(wakes)*5 + store_reads + store_writes + retries*2,"episode_id":cell["episode_id"],
                "escalation_failure":sum(r["trigger"]["reason"]=="FAILURE" and r["trigger"]["wake"] for r in ticks),"escalation_event":sum(r["trigger"]["reason"]=="EVENT" and r["trigger"]["wake"] for r in ticks),
                "false_wakes":fp,"late_wakes":int(latency is None or latency>2),"progress":progress,"retries":retries,"storage_age":max(0,final_tick-last_write),"storage_bytes":stored_bytes,
                "storage_reads":store_reads,"storage_writes":store_writes,"terminal_tick":final_tick+1,"thrash":target_switches,"trigger_fn":1-tp,"trigger_latency":latency,
                "trigger_precision":tp/max(1,tp+fp),"trigger_recall":float(tp),"wakes":len(wakes),"wasted_wakes":sum(1 for r in wakes if r["plan_before"]==r["plan_after"])}
    return start, ticks, terminal
