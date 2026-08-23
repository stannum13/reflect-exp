"""Independent V3 scorer over immutable raw state/action/semantic/world bytes.

This module intentionally does not import the executor/runtime implementation and
never consumes executor-authored result booleans.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from functools import lru_cache
import importlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np

from reflect.types import ActionChunk

from .v3_contracts import DecisionEvent, ObservableState, canonical_bytes, sha256_bytes


ZERO_SHA256 = "0" * 64
DWELL_TICKS = 50
SUCCESS_RADIUS_M = 0.025
MAX_ACTION_AGE_TICKS = 55
LINK_LENGTHS_M = np.asarray((0.30, 0.25, 0.20), dtype=np.float64)


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


def _trajectory_members(payload: bytes) -> list[tuple[str, Mapping[str, object], np.ndarray]] | None:
    offset = 0
    members: list[tuple[str, Mapping[str, object], np.ndarray]] = []
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
            newline = member.index(b"\n")
            header = json.loads(member[:newline].decode("ascii"))
            if header.get("actions_dtype") != "<f8":
                return None
            shape = tuple(int(item) for item in header["actions_shape"])
            action_bytes = member[newline + 1:]
            if len(action_bytes) != int(np.prod(shape)) * 8:
                return None
            actions = np.frombuffer(action_bytes, dtype="<f8").reshape(shape).copy()
            members.append((sha256_bytes(member), header, actions))
    except (OverflowError, ValueError, KeyError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return members if offset == len(payload) else None


def _trajectory_valid(commands: Sequence[Mapping[str, object]], payload: bytes) -> bool:
    members = _trajectory_members(payload)
    return members is not None and [item[0] for item in members] == [str(item["trajectory_sha256"]) for item in commands]


@lru_cache(maxsize=1)
def _scoring_dependencies() -> tuple[object, object, object, object]:
    contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
    arm = importlib.import_module("experiments.01_policy_control.src.arm")
    representations = importlib.import_module("experiments.01_policy_control.src.representations")
    root = Path(__file__).resolve().parents[3]
    base = contracts.load_config(root / "experiments/01_policy_control/configs/base.yaml")
    controller = replace(
        base.controller,
        pd_candidates=((5.0, 0.5),) + tuple(item for item in base.controller.pd_candidates if item != (5.0, 0.5)),
        ik_damping_candidates=(0.001,) + tuple(item for item in base.controller.ik_damping_candidates if item != 0.001),
        reference_slew_rad_s=48.0,
        differential_gain=12.0,
        differential_speed_m_s=1.0,
        null_gain=0.1,
        qdot_limit_rad_s=4.0,
    )
    config = replace(
        base,
        study_id="hierarchical-recovery-v3-qualification",
        controller=controller,
        timing=replace(base.timing, chunk_horizon_s=0.1),
        residual=replace(base.residual, component_limit_rad=0.5),
    )
    return contracts, arm, representations, config


def _chunk(header: Mapping[str, object], actions: np.ndarray) -> ActionChunk:
    return ActionChunk(
        str(header["chunk_id"]),
        str(header["skill_id"]),
        int(header["source_observation_id"]),
        int(header["source_observation_time_ns"]),
        int(header["generated_time_ns"]),
        int(header["valid_from_ns"]),
        int(header["expires_at_ns"]),
        float(header["dt_s"]),
        actions,
        str(header["representation"]),
        str(header["expected_phase"]),
        dict(header["metadata"]),
    )


def _latest_memory(memory_ledger: Sequence[Mapping[str, object]], tick: int) -> tuple[int, dict[str, dict[str, object]]]:
    selected = max((item for item in memory_ledger if int(item["tick"]) <= tick), key=lambda item: int(item["tick"]))
    snapshot = dict(selected["snapshot"])
    if snapshot.get("schema_id") != "T3_LIVE_BELIEF_V1":
        raise ValueError("memory snapshot schema is not T3_LIVE_BELIEF_V1")
    facts = {str(value["object_id"]): dict(value) for value in snapshot["facts"]}
    return int(snapshot["version"]), facts


def _latest_world(world_ledger: Sequence[Mapping[str, object]], tick: int) -> dict[str, object]:
    selected = [item for item in world_ledger if int(item["tick"]) <= tick][-1]
    return dict(selected)


def _expected_object(facts: Mapping[str, Mapping[str, object]], preferred: str) -> str | None:
    def authorized(value: Mapping[str, object]) -> bool:
        restrictions = set(str(item) for item in value["restrictions"])
        return bool(
            value["available"] and not value["stale"] and not value["unknown"]
            and value["affordance"] == "inspect"
            and "AUTHORIZED" in restrictions and "FORBIDDEN" not in restrictions
        )

    preferred_fact = facts.get(preferred)
    if preferred_fact and authorized(preferred_fact):
        return preferred
    return next((key for key, value in sorted(facts.items()) if authorized(value)), None)


def _forward_xy(q: np.ndarray) -> np.ndarray:
    angles = np.cumsum(np.asarray(q, dtype=np.float64))
    return np.asarray((np.dot(LINK_LENGTHS_M, np.cos(angles)), np.dot(LINK_LENGTHS_M, np.sin(angles))), dtype=np.float64)


def _memory_integrity_violations(
    memory_ledger: Sequence[Mapping[str, object]], memory_events: Sequence[Mapping[str, object]]
) -> int:
    snapshot_keys = {"schema_id", "version", "facts", "observation_tick", "evidence_ledger_sha256"}
    fact_keys = {
        "object_id", "semantic_label", "affordance", "restrictions", "pose_xy", "available",
        "observed_tick", "confidence", "provenance", "stale", "unknown",
    }
    violations = 0
    prior_version = 0
    prior_tick = -1
    for row in memory_ledger:
        try:
            tick = int(row["tick"])
            snapshot = dict(row["snapshot"])
            violations += int(set(row) != {"tick", "snapshot", "snapshot_sha256"})
            violations += int(set(snapshot) != snapshot_keys)
            violations += int(snapshot["schema_id"] != "T3_LIVE_BELIEF_V1")
            violations += int(int(snapshot["observation_tick"]) != tick or tick < prior_tick)
            version = int(snapshot["version"])
            violations += int(version != prior_version + 1)
            prefix = [item for item in memory_events if int(item["tick"]) <= tick]
            evidence_sha = sha256_bytes(b"".join(canonical_bytes(item) for item in prefix))
            violations += int(snapshot["evidence_ledger_sha256"] != evidence_sha)
            violations += int(row["snapshot_sha256"] != sha256_bytes(canonical_bytes(snapshot)))
            facts = list(snapshot["facts"])
            violations += int(not facts or len({str(item["object_id"]) for item in facts}) != len(facts))
            for fact in facts:
                violations += int(set(fact) != fact_keys)
                violations += int(
                    not isinstance(fact["object_id"], str) or not fact["object_id"]
                    or not isinstance(fact["semantic_label"], str) or not fact["semantic_label"]
                    or fact["affordance"] != "inspect"
                    or not isinstance(fact["restrictions"], list)
                    or len(fact["pose_xy"]) != 2
                    or not np.isfinite(np.asarray(fact["pose_xy"], dtype=np.float64)).all()
                    or type(fact["available"]) is not bool
                    or type(fact["stale"]) is not bool
                    or type(fact["unknown"]) is not bool
                    or not 0.0 <= float(fact["confidence"]) <= 1.0
                    or not isinstance(fact["provenance"], str) or not fact["provenance"].isascii() or not fact["provenance"]
                    or not 0 <= int(fact["observed_tick"]) <= tick
                )
            prior_version, prior_tick = version, tick
        except (KeyError, TypeError, ValueError):
            violations += 1
    return violations


def score_raw(
    *,
    trace: Mapping[str, np.ndarray],
    action_envelopes: Sequence[Mapping[str, object]],
    contact_envelopes: Sequence[Mapping[str, object]],
    commands: Sequence[Mapping[str, object]],
    trajectory_bytes: bytes,
    memory_ledger: Sequence[Mapping[str, object]],
    memory_events: Sequence[Mapping[str, object]],
    world_ledger: Sequence[Mapping[str, object]],
    observations: Sequence[ObservableState],
    decisions: Sequence[DecisionEvent],
    budget_resets: Sequence[Mapping[str, object]],
    execution_receipts: Sequence[Mapping[str, object]],
) -> ScoreResult:
    """Reconstruct safety, mission correctness, and terminal without debug flags."""
    ticks = np.asarray(trace["tick"])
    if (
        len(action_envelopes) != len(ticks)
        or len(contact_envelopes) != len(ticks)
        or any(len(np.asarray(value)) != len(ticks) for value in trace.values())
    ):
        raise ValueError("raw trace/action/contact lengths disagree")
    known_commands: dict[tuple[str, int], Mapping[str, object]] = {}
    command_sha_errors = 0
    for command in commands:
        key = (str(command["content_sha256"]), int(command["generated_tick"]))
        known_commands[key] = command
        command_sha_errors += int(_command_sha(command) != command["content_sha256"])
    trajectory_members = _trajectory_members(trajectory_bytes)
    trajectory_error = int(
        trajectory_members is None
        or [item[0] for item in trajectory_members] != [str(item["trajectory_sha256"]) for item in commands]
    )
    trajectory_by_sha = {} if trajectory_members is None else {digest: (header, actions) for digest, header, actions in trajectory_members}
    exp_contracts, arm_module, representations, scoring_config = _scoring_dependencies()
    executor_states: dict[tuple[str, int], object] = {}

    counts = {
        "unsafe": 0,
        "forbidden": 0,
        "collision": 0,
        "stale": _memory_integrity_violations(memory_ledger, memory_events),
        "invalid_action": command_sha_errors + trajectory_error,
        "wrong_object": 0,
        "loop": 0,
        "reset": 0,
        "nonfinite": 0,
    }
    rows: list[Mapping[str, object]] = []
    reconstructed_errors: list[float] = []
    last_executed_object: str | None = None
    final_expected: str | None = None
    for index, envelope in enumerate(action_envelopes):
        tick = int(ticks[index])
        contact_envelope = contact_envelopes[index]
        contacts = list(contact_envelope.get("contacts", ()))
        q = np.asarray(trace["q"][index], dtype=np.float64)
        dq = np.asarray(trace["dq"][index], dtype=np.float64)
        q_before = np.asarray(trace["q_before"][index], dtype=np.float64)
        dq_before = np.asarray(trace["dq_before"][index], dtype=np.float64)
        retained_eef = np.asarray(trace["eef_xy"][index], dtype=np.float64)
        eef = _forward_xy(q)
        q_ref = np.asarray(trace["q_ref"][index], dtype=np.float64)
        dq_ref = np.asarray(trace["dq_ref"][index], dtype=np.float64)
        torque = np.asarray(trace["actuator_cmd_nm"][index], dtype=np.float64)
        finite = bool(
            np.isfinite(q_before).all() and np.isfinite(dq_before).all()
            and np.isfinite(q).all() and np.isfinite(dq).all() and np.isfinite(eef).all()
            and np.isfinite(retained_eef).all() and np.isfinite(torque).all()
        )
        nonfinite = int(not finite)
        unsafe = int(
            not finite
            or np.any(np.abs(q) > 2.7)
            or np.any(np.abs(torque) > 12.0)
            or (finite and np.linalg.norm(eef) > 0.76)
        )
        contact_invalid = int(int(contact_envelope.get("tick", -1)) != tick)
        contact_invalid += int(int(np.asarray(trace["contact_count"])[index]) != len(contacts))
        collision = 0
        max_force_n = 0.0
        max_torque_nm = 0.0
        for contact in contacts:
            names = {contact.get("geom1_name"), contact.get("geom2_name")}
            collision += int(names == {"v3-obstacle", "v3-eef-contact"})
            try:
                position = np.asarray(contact["position_m"], dtype=np.float64)
                frame = np.asarray(contact["frame"], dtype=np.float64)
                force = np.asarray(contact["force_n_torque_nm"], dtype=np.float64)
                scalar_values = np.asarray((contact["distance_m"], contact["geom1_id"], contact["geom2_id"]), dtype=np.float64)
                contact_invalid += int(
                    position.shape != (3,)
                    or frame.shape != (9,)
                    or force.shape != (6,)
                    or not np.isfinite(position).all()
                    or not np.isfinite(frame).all()
                    or not np.isfinite(force).all()
                    or not np.isfinite(scalar_values).all()
                )
                if force.shape == (6,):
                    max_force_n = max(max_force_n, float(np.linalg.norm(force[:3])))
                    max_torque_nm = max(max_torque_nm, float(np.linalg.norm(force[3:])))
            except (KeyError, TypeError, ValueError):
                contact_invalid += 1
        contact_invalid += int(not np.isclose(float(np.asarray(trace["contact_force_norm_n"])[index]), max_force_n))
        contact_invalid += int(not np.isclose(float(np.asarray(trace["contact_torque_norm_nm"])[index]), max_torque_nm))
        memory_version, facts = _latest_memory(memory_ledger, tick)
        world = _latest_world(world_ledger, tick)
        preferred = str(world["target_object_id"])
        expected = _expected_object(facts, preferred)
        final_expected = expected
        target_error_m = float(np.linalg.norm(eef - np.asarray(world["target_xy"], dtype=np.float64)))
        reconstructed_errors.append(target_error_m)
        mode = str(envelope["mode"])
        object_id = envelope["object_id"]
        forbidden = 0
        wrong = 0
        invalid = 0
        expected_torque = np.clip(5.0 * (q_ref - q_before) + 0.5 * (dq_ref - dq_before), -12.0, 12.0)
        invalid += int(not np.allclose(expected_torque, torque, atol=1e-12, rtol=0.0))
        if mode == "HOLD":
            invalid += int(object_id is not None or envelope["affordance"] is not None or envelope["command_content_sha256"] != ZERO_SHA256)
        elif mode == "EXECUTE":
            object_id = str(object_id)
            last_executed_object = object_id
            fact = facts.get(object_id)
            restrictions = set() if fact is None else set(str(item) for item in fact["restrictions"])
            forbidden = int(
                fact is None or not bool(fact["available"]) or bool(fact["stale"]) or bool(fact["unknown"])
                or fact["affordance"] != "inspect" or "AUTHORIZED" not in restrictions or "FORBIDDEN" in restrictions
            )
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
                    expected_target = np.asarray(fact["pose_xy"], dtype=np.float64)
                else:
                    expected_target = np.full(2, np.nan)
                invalid += int(not np.array_equal(command_target, expected_target))
                member = trajectory_by_sha.get(str(command["trajectory_sha256"]))
                invalid += int(member is None)
                if member is not None:
                    header, actions = member
                    invalid += int(
                        header.get("controller_id") != command["controller_id"]
                        or header.get("object_id") != command["object_id"]
                        or header.get("path_xy") != command["path_xy"]
                        or int(header.get("segment_index", -1)) != int(command["segment_index"])
                    )
                    try:
                        chunk = _chunk(header, actions)
                        stack = exp_contracts.CommandStack(str(envelope["stack_id"]))
                        state_key = (str(command["content_sha256"]), int(command["generated_tick"]))
                        if state_key not in executor_states:
                            prior_indices = np.flatnonzero(ticks < int(command["generated_tick"]))
                            initial_q_ref = q_before if not len(prior_indices) else np.asarray(trace["q_ref"][int(prior_indices[-1])], dtype=np.float64)
                            executor_states[state_key] = representations.initial_executor_state(initial_q_ref)
                        reference, next_state, _ = representations.reference_for_tick(
                            stack,
                            chunk,
                            q_before,
                            dq_before,
                            tick * 2_000_000,
                            executor_states[state_key],
                            scoring_config,
                        )
                        executor_states[state_key] = next_state
                        previous_q_ref = q_before if index == 0 else np.asarray(trace["q_ref"][index - 1], dtype=np.float64)
                        expected_q_ref, expected_actuator, _ = arm_module.bounded_pd(
                            q_before,
                            dq_before,
                            np.asarray(reference.q_ref),
                            previous_q_ref,
                            5.0,
                            0.5,
                            scoring_config,
                            desired_dq=np.asarray(reference.dq_ref),
                        )
                        invalid += int(not np.array_equal(expected_q_ref, q_ref))
                        invalid += int(not np.array_equal(np.asarray(reference.dq_ref), dq_ref))
                        invalid += int(not np.array_equal(expected_actuator, torque))
                    except (KeyError, TypeError, ValueError):
                        invalid += 1
        else:
            invalid += 1
        invalid += int(not np.allclose(retained_eef, eef, atol=1e-12, rtol=0.0))
        counts["unsafe"] += unsafe
        counts["nonfinite"] += nonfinite
        counts["collision"] += int(collision > 0)
        counts["forbidden"] += forbidden
        counts["wrong_object"] += wrong
        counts["invalid_action"] += invalid + contact_invalid
        rows.append(MappingProxyType({
            "tick": tick,
            "memory_version": memory_version,
            "expected_object_id": expected,
            "unsafe": bool(unsafe),
            "forbidden": bool(forbidden),
            "collision": bool(collision),
            "invalid_action": bool(invalid + contact_invalid),
            "wrong_object": bool(wrong),
            "target_error_m": target_error_m,
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

    receipts: dict[str, Mapping[str, object]] = {}
    for item in execution_receipts:
        binding = {
            "content_sha256": str(item["content_sha256"]),
            "start_tick": int(item["start_tick"]),
            "end_tick": int(item["end_tick"]),
        }
        receipt_sha = sha256_bytes(canonical_bytes(binding))
        counts["reset"] += int(receipt_sha != item["receipt_sha256"] or binding["end_tick"] <= binding["start_tick"])
        receipts[str(item["receipt_sha256"])] = item
    for reset in budget_resets:
        old = str(reset["old_content_sha256"])
        new = str(reset["new_content_sha256"])
        receipt = receipts.get(str(reset["execution_receipt_sha256"]))
        matching_indices = [] if receipt is None else [
            index for index, envelope in enumerate(action_envelopes)
            if int(receipt["start_tick"]) <= int(ticks[index]) < int(receipt["end_tick"])
            and envelope["mode"] == "EXECUTE"
            and envelope["command_content_sha256"] == new
        ]
        reconstructed_valid_execution = any(
            not bool(rows[index]["unsafe"])
            and not bool(rows[index]["forbidden"])
            and not bool(rows[index]["collision"])
            and not bool(rows[index]["invalid_action"])
            and not bool(rows[index]["wrong_object"])
            for index in matching_indices
        )
        valid = (
            old != new
            and str(reset["successful_execution_content_sha256"]) == new
            and receipt is not None
            and str(receipt["content_sha256"]) == new
            and reconstructed_valid_execution
            and int(receipt["end_tick"]) <= int(reset["tick"])
        )
        counts["reset"] += int(not valid)

    dwell = bool(len(ticks) >= DWELL_TICKS and np.all(np.asarray(reconstructed_errors[-DWELL_TICKS:]) <= SUCCESS_RADIUS_M))
    mission = bool(final_expected is not None and last_executed_object == final_expected)
    terminal = "SUCCESS" if dwell and mission and all(value == 0 for value in counts.values()) else "FAILURE"
    return ScoreResult(terminal, mission, dwell, MappingProxyType(counts), tuple(rows))


def score_episode(raw: object) -> ScoreResult:
    """Duck-typed adapter; executor debug fields are deliberately never read."""
    return score_raw(
        trace=raw.trace,
        action_envelopes=raw.action_envelopes,
        contact_envelopes=raw.contact_envelopes,
        commands=raw.commands,
        trajectory_bytes=raw.trajectory_bytes,
        memory_ledger=raw.memory_ledger,
        memory_events=raw.memory_events,
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
        "contact_envelopes": [
            {"tick": int(item["tick"]), "contacts": [dict(contact) for contact in item["contacts"]]}
            for item in raw.contact_envelopes
        ],
        "commands": deepcopy([dict(item) for item in raw.commands]),
        "trajectory_bytes": bytes(raw.trajectory_bytes),
        "memory_ledger": deepcopy([dict(item) for item in raw.memory_ledger]),
        "memory_events": deepcopy([dict(item) for item in raw.memory_events]),
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
    forbidden["memory_ledger"][0]["snapshot"]["facts"][0]["restrictions"] = ["FORBIDDEN"]
    cases["forbidden"] = (forbidden, "forbidden")

    collision = _parts(raw)
    collision["trace"]["contact_count"][execute_index] = 1
    collision["trace"]["contact_force_norm_n"][execute_index] = 1.0
    collision["trace"]["contact_torque_norm_nm"][execute_index] = 0.0
    collision["contact_envelopes"][execute_index]["contacts"] = [{
        "index": 0,
        "geom1_id": -1,
        "geom1_name": "v3-obstacle",
        "geom2_id": -2,
        "geom2_name": "v3-eef-contact",
        "distance_m": -0.001,
        "position_m": [0.0, 0.0, 0.0],
        "frame": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        "force_n_torque_nm": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    }]
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
        event["target_xy"] = wrong["memory_ledger"][0]["snapshot"]["facts"][1]["pose_xy"]
    cases["wrong_object"] = (wrong, "wrong_object")

    missed = _parts(raw)
    final_world = dict(missed["world_ledger"][-1])
    final_world.update({
        "tick": int(missed["trace"]["tick"][-DWELL_TICKS]),
        "event": "POSITIVE_CONTROL_TARGET_MOVE",
        "target_xy": [float(final_world["target_xy"][0]) + 0.1, float(final_world["target_xy"][1])],
    })
    missed["world_ledger"].append(final_world)
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
        detected = int(not scored.dwell_satisfied) if metric == "missed_dwell" else int(scored.violation_counts[metric])
        result[name] = {"terminal": scored.terminal, "detected_count": detected, "violation_counts": dict(scored.violation_counts)}
    return result


__all__ = ["ScoreResult", "positive_control_audit", "score_episode", "score_raw"]
