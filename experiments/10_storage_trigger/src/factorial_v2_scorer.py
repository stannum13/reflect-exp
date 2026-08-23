"""Independent low-level ledger scorer for Experiment 10 V2.

This module deliberately does not import the executor.  It reconstructs the
typed world, storage, trigger, action, and progress state from raw authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping, Sequence


PLANNER_ID = "ORACLE_TYPED_SEMANTIC_V2"


class LedgerScoreError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _apply_event(world: dict[str, Any], event: Mapping[str, Any]) -> None:
    kind = str(event["event_kind"])
    subject = str(event["subject_id"])
    if kind == "RESTRICTION":
        world["restrictions"][subject] = bool(event["value"])
    elif kind in {"ROOM", "AVAILABILITY", "POSE"}:
        field_name = {"ROOM": "room_id", "AVAILABILITY": "availability", "POSE": "pose"}[kind]
        world["entities"][subject][field_name] = event["value"]
    else:
        raise LedgerScoreError("unknown material event")


def _eligible(view: Mapping[str, Any]) -> list[str]:
    return sorted(
        (
            entity for entity, state in view["entities"].items()
            if state["availability"] == "AVAILABLE" and not view["restrictions"].get(state["room_id"], False)
        ),
        key=lambda entity: (view["entities"][entity]["room_id"], entity),
    )


def _plan(view: Mapping[str, Any]) -> dict[str, Any]:
    eligible = _eligible(view)
    failures = set(view["failures"])
    alternatives = [entity for entity in eligible if entity not in failures]
    target = alternatives[0] if alternatives else (eligible[0] if eligible else None)
    return {
        "affordance": "service_valve",
        "planner_id": PLANNER_ID,
        "pose": view["entities"].get(target, {}).get("pose") if target else None,
        "subgoals": ["approach", "inspect", "actuate", "verify"],
        "target": target,
    }


def _valid(world: Mapping[str, Any], plan: Mapping[str, Any]) -> bool:
    target = plan.get("target")
    if target not in world["entities"]:
        return False
    state = world["entities"][str(target)]
    return (
        state["availability"] == "AVAILABLE"
        and not world["restrictions"].get(str(state["room_id"]), False)
        and plan.get("pose") == state["pose"]
    )


@dataclass
class StorageReplay:
    variant: str
    initial_world: Mapping[str, Any]
    belief: dict[str, Any] = field(init=False)
    episodes: list[dict[str, Any]] = field(default_factory=list)
    transient: list[dict[str, Any]] = field(default_factory=list)
    reads: int = 0
    writes: int = 0
    latest_write_tick: int = 0

    def __post_init__(self) -> None:
        self.belief = _copy(self.initial_world)

    def ingest(self, event: Mapping[str, Any]) -> None:
        row = dict(event)
        tick = int(row["tick"])
        if self.variant == "NO_MEMORY":
            self.transient = [row]
            return
        if self.variant == "FIXED_SNAPSHOT":
            return
        if self.variant in {"EPISODIC_ONLY", "LIVE_EPISODIC"}:
            self.episodes.append(row)
            self.writes += 1
            self.latest_write_tick = tick
        if self.variant in {"LIVE_BELIEF", "LIVE_EPISODIC"} and row["event_kind"] != "ATTEMPT":
            _apply_event(self.belief, row)
            self.writes += 1
            self.latest_write_tick = tick

    def view(self, tick: int) -> dict[str, Any]:
        self.reads += 1
        if self.variant == "NO_MEMORY":
            world = _copy(self.initial_world)
            events = list(self.transient)
            self.transient.clear()
            for event in events:
                if event["event_kind"] != "ATTEMPT":
                    _apply_event(world, event)
            failures = [event["subject_id"] for event in events if event["event_kind"] == "ATTEMPT"]
        elif self.variant == "EPISODIC_ONLY":
            world = _copy(self.initial_world)
            for event in self.episodes:
                if event["event_kind"] != "ATTEMPT":
                    _apply_event(world, event)
            failures = [event["subject_id"] for event in self.episodes if event["event_kind"] == "ATTEMPT"]
        else:
            world = _copy(self.belief)
            failures = [event["subject_id"] for event in self.episodes if event["event_kind"] == "ATTEMPT"]
        return {**world, "failures": sorted(set(failures)), "tick": tick}

    def stats(self, tick: int) -> dict[str, int]:
        if self.variant == "NO_MEMORY":
            size = 0
        elif self.variant == "EPISODIC_ONLY":
            size = len(_canonical(self.episodes))
        elif self.variant == "LIVE_EPISODIC":
            size = len(_canonical({"entities": self.belief["entities"], "episodes": self.episodes, "restrictions": self.belief["restrictions"]}))
        else:
            size = len(_canonical(self.belief))
        return {
            "age_ticks": max(0, tick - self.latest_write_tick),
            "bytes": size,
            "reads": self.reads,
            "writes": self.writes,
        }


@dataclass
class TriggerReplay:
    variant: str
    period_ticks: int
    failure_threshold: int
    cooldown_ticks: int
    armed: bool = True
    last_wake: int = -10_000
    pending_event: bool = False

    def state(self) -> dict[str, Any]:
        return {"armed": self.armed, "last_wake": self.last_wake, "pending_event": self.pending_event}

    def decide(self, *, tick: int, material_event: bool, failures: int) -> tuple[bool, str]:
        if self.variant == "NO_REPLAN":
            return False, "DISABLED"
        if self.variant == "PERIODIC_ONLY":
            return (True, "PERIODIC") if tick % self.period_ticks == 0 else (False, "NONE")
        failure_due = failures >= self.failure_threshold and self.armed
        if self.variant == "FAILURE_THRESHOLD":
            if failure_due:
                self.armed = False
                self.last_wake = tick
                return True, "FAILURE"
            return False, "NONE"
        if self.variant == "EVENT_DRIVEN":
            if material_event:
                self.last_wake = tick
                return True, "EVENT"
            return False, "NONE"
        self.pending_event = self.pending_event or material_event
        reason = "EVENT" if self.pending_event else ("FAILURE" if failure_due else ("PERIODIC" if tick % self.period_ticks == 0 else "NONE"))
        if reason == "NONE":
            return False, reason
        if tick - self.last_wake < self.cooldown_ticks:
            return False, "COOLDOWN_SUPPRESSED"
        self.last_wake = tick
        if reason == "EVENT":
            self.pending_event = False
        if reason == "FAILURE":
            self.armed = False
        return True, reason

    def note_success(self) -> None:
        self.armed = True


def _expected_events(world: Mapping[str, Any], family: str, severity: str, tick: int, target: str) -> tuple[list[dict[str, Any]], int, str | None]:
    entities = world["entities"]
    candidates = [entity for entity in sorted(entities) if entity != target]
    if family == "POSE_SHIFT":
        delta = 0.4 if severity == "LOW" else 1.2
        pose = entities[target]["pose"]
        return ([{"event_kind": "POSE", "subject_id": target, "tick": tick, "value": [round(pose[0] + delta, 6), round(pose[1] - delta, 6)]}], 0, None)
    if family == "AVAILABILITY_LOSS":
        events = [{"event_kind": "AVAILABILITY", "subject_id": target, "tick": tick, "value": "UNAVAILABLE"}]
        if severity == "HIGH" and candidates:
            events.append({"event_kind": "AVAILABILITY", "subject_id": candidates[0], "tick": tick, "value": "UNAVAILABLE"})
        return events, 0, None
    if family == "RESTRICTION_CHANGE":
        events = [{"event_kind": "RESTRICTION", "subject_id": entities[target]["room_id"], "tick": tick, "value": True}]
        if severity == "HIGH" and candidates:
            events.append({"event_kind": "RESTRICTION", "subject_id": entities[candidates[0]]["room_id"], "tick": tick, "value": True})
        return events, 0, None
    if family == "CONTROL_FAILURE":
        return [], 1 if severity == "LOW" else 3, target
    raise LedgerScoreError("unknown disturbance family")


def score_episode(start: Mapping[str, Any], ticks: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    cell = dict(start["cell"])
    world = _copy(start["initial_world"])
    store = StorageReplay(str(cell["storage_variant"]), world)
    trigger = TriggerReplay(
        str(cell["trigger_variant"]), int(config["period_ticks"]),
        int(config["failure_threshold"]), int(config["hybrid_cooldown_ticks"]),
    )
    plan = _plan(store.view(0))
    if start.get("initial_plan") != plan:
        raise LedgerScoreError("initial plan ledger mismatch")
    horizon = int(cell["horizon"])
    disturbance_tick = max(2, horizon // 2)
    progress = 0
    semantic_wakes = motion_wakes = 1
    control_wakes = retries = escalations = repeated_failures = 0
    stale_decisions = false_triggers = wasted_triggers = late_trigger_ticks = 0
    consecutive_failures = 0
    last_failed_target: str | None = None
    pending_attempt_event = False
    required_since: int | None = None
    trigger_latencies: list[int] = []
    control_remaining = 0
    control_target: str | None = None
    ordered = sorted(ticks, key=lambda row: int(row["tick"]))
    if [int(row["tick"]) for row in ordered] != list(range(1, len(ordered) + 1)):
        raise LedgerScoreError("ledger chronology mismatch")
    for row in ordered:
        tick = int(row["tick"])
        if row.get("episode_id") != cell["episode_id"] or row.get("cell") != cell:
            raise LedgerScoreError("ledger cell identity mismatch")
        if row.get("world_before") != world or row.get("plan_before") != plan:
            raise LedgerScoreError("world/plan ledger mismatch")
        expected_events: list[dict[str, Any]] = []
        if tick == disturbance_tick:
            expected_events, control_remaining, control_target = _expected_events(
                world, str(cell["disturbance_family"]), str(cell["severity"]), tick, str(plan["target"]),
            )
        if row.get("events") != expected_events:
            raise LedgerScoreError("disturbance event ledger mismatch")
        for event in expected_events:
            _apply_event(world, event)
            store.ingest(event)
        material_event = bool(expected_events) or pending_attempt_event
        pending_attempt_event = False
        valid_before = _valid(world, plan)
        failures_before = consecutive_failures
        if (not valid_before or consecutive_failures > 0) and required_since is None:
            required_since = tick
        trigger_before = trigger.state()
        wake, reason = trigger.decide(tick=tick, material_event=material_event, failures=consecutive_failures)
        plan_before = _copy(plan)
        if wake:
            semantic_wakes += 1
            plan = _plan(store.view(tick))
            if plan != plan_before:
                motion_wakes += 1
            else:
                wasted_triggers += 1
            if valid_before and consecutive_failures == 0 and not material_event:
                false_triggers += 1
            if reason == "FAILURE":
                escalations += 1
            if required_since is not None:
                trigger_latencies.append(tick - required_since)
                required_since = None
        expected_trigger = {
            "inputs": {"failures": failures_before, "material_event": material_event},
            "reason": reason, "state_after": trigger.state(), "state_before": trigger_before, "wake": wake,
        }
        if row.get("trigger") != expected_trigger or row.get("plan_after") != plan:
            raise LedgerScoreError("trigger/plan ledger mismatch")
        valid_action = _valid(world, plan)
        fault_before = control_remaining
        success = valid_action
        if valid_action and control_remaining > 0 and plan["target"] == control_target:
            success = False
            control_remaining -= 1
        expected_action = {
            "attempted": True, "control_fault_after": control_remaining,
            "control_fault_before": fault_before, "pose": plan.get("pose"),
            "success": success, "target": plan.get("target"),
        }
        if row.get("action") != expected_action:
            raise LedgerScoreError("action ledger mismatch")
        if not success:
            retries += 1
            control_wakes += 1
            consecutive_failures += 1
            stale_decisions += int(not valid_action)
            if last_failed_target == plan.get("target"):
                repeated_failures += 1
            last_failed_target = str(plan.get("target"))
            attempt = {"event_kind": "ATTEMPT", "subject_id": plan.get("target"), "tick": tick, "value": "FAILED"}
            store.ingest(attempt)
            pending_attempt_event = True
            if required_since is None:
                required_since = tick
        else:
            progress += 1
            consecutive_failures = 0
            last_failed_target = None
            trigger.note_success()
        if required_since is not None and not wake:
            late_trigger_ticks += 1
        stats = store.stats(tick)
        if row.get("storage") != stats or row.get("world_after") != world:
            raise LedgerScoreError("storage/world ledger mismatch")
        if progress >= horizon and tick != len(ordered):
            raise LedgerScoreError("ledger continues after completion")
    if not ordered:
        raise LedgerScoreError("empty episode ledger")
    final_tick = int(ordered[-1]["tick"])
    stats = store.stats(final_tick)
    semantic_latency = semantic_wakes * 0.2 + stats["reads"] * 0.03 + stats["bytes"] / 100_000
    motion_latency = motion_wakes * 0.12
    control_latency = control_wakes * 0.04
    cost = semantic_wakes * 10 + motion_wakes * 4 + control_wakes * 2 + stats["reads"] * 0.05 + stats["bytes"] / 1024
    return {
        **cell,
        "aborts": int(progress < horizon), "budget_cost_proxy": round(cost, 6),
        "completion": int(progress >= horizon), "control_latency_proxy_ms": round(control_latency, 6),
        "control_wakes": control_wakes, "escalations": escalations, "false_triggers": false_triggers,
        "late_trigger_ticks": late_trigger_ticks, "motion_latency_proxy_ms": round(motion_latency, 6),
        "motion_wakes": motion_wakes, "progress": round(min(progress, horizon) / horizon, 6),
        "repeated_failures": repeated_failures, "retries": retries,
        "semantic_latency_proxy_ms": round(semantic_latency, 6), "semantic_wakes": semantic_wakes,
        "stale_decisions": stale_decisions, "storage_age_ticks": stats["age_ticks"],
        "storage_bytes": stats["bytes"], "storage_reads": stats["reads"], "storage_writes": stats["writes"],
        "trigger_latency_ticks_mean": round(sum(trigger_latencies) / len(trigger_latencies), 6) if trigger_latencies else 0.0,
        "wasted_triggers": wasted_triggers,
    }


__all__ = ["LedgerScoreError", "PLANNER_ID", "score_episode"]
