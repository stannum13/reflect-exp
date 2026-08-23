"""Unsealed, qualification-only A--G MuJoCo integration probe."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Sequence

import numpy as np

from reflect.types import ActionChunk

from .adapter import PolicyRaw, dispatch_executable, inject_fault, normalize_policy_raw, verify_normalized_policy
from .broker import TemporalBroker
from .contracts import FaultId, ProtocolId, VECTOR_VALUES, VectorId
from .schedule import iter_cells, iter_request_ticks


arm_module = importlib.import_module("experiments.01_policy_control.src.arm")
contracts = importlib.import_module("experiments.01_policy_control.src.contracts")
kinematics = importlib.import_module("experiments.01_policy_control.src.kinematics")
representations = importlib.import_module("experiments.01_policy_control.src.representations")

_DT_NS = 2_000_000
_TELEMETRY_DTYPE = np.dtype(
    [("q", "<f8", (3,)), ("dq", "<f8", (3,)), ("eef", "<f8", (2,)),
     ("target", "<f8", (2,)), ("q_ref", "<f8", (3,)), ("torque", "<f8", (3,)),
     ("error", "<f8"), ("hold", "?"), ("active", "?")]
)


class DynamicsQualificationError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _save_npy(path: Path, value: np.ndarray) -> None:
    with path.open("xb") as stream:
        np.lib.format.write_array(stream, value, allow_pickle=False)


def _matrix_bytes(value: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(value, dtype="<f8", order="C").tobytes(order="C")).hexdigest()


def _selected_cells(seed: int) -> tuple[object, ...]:
    cells = []
    for protocol in ProtocolId:
        vector = None if protocol is ProtocolId.A else VectorId.V1
        row = {"stack_id": "P4", "protocol_id": protocol.value, "vector_id": None if vector is None else vector.value, "seed": seed}
        arm_cells = iter_cells("tuning", (row,))
        for latency in (25, 75, 150):
            cells.append(next(cell for cell in arm_cells if cell.fault_id is FaultId.NONE and cell.latency_ticks == latency and cell.move_ticks == (51,)))
        chosen = {ProtocolId.A: FaultId.DROP, ProtocolId.D: FaultId.DISCONTINUITY, ProtocolId.E: FaultId.PAUSE, ProtocolId.F: FaultId.ALTERNATIVE}.get(protocol)
        if chosen is not None:
            cells.append(next(cell for cell in arm_cells if cell.fault_id is chosen))
    return tuple(cells)


def _run_cell(cell: object, config: object) -> tuple[np.ndarray, dict[str, object], list[dict[str, object]]]:
    arm = arm_module.PlanarArm(config)
    q0 = np.array((0.2, -0.4, 0.2), dtype=np.float64)
    arm.reset(q0)
    initial_target = np.array(arm.site_xy(), copy=True)
    target = np.array(initial_target, copy=True)
    moved_target = initial_target + np.array((-0.06, 0.06), dtype=np.float64)
    plans = iter_request_ticks(cell)
    request_at = {plan.request_tick: plan for plan in plans}
    delivery_at = {plan.actual_delivery_tick: plan for plan in plans if plan.actual_delivery_tick is not None}
    captures: dict[int, tuple[np.ndarray, np.ndarray, int]] = {}
    telemetry = np.empty(3125, dtype=_TELEMETRY_DTYPE)
    vector = None if cell.vector_id is None else VECTOR_VALUES[cell.vector_id]
    capacity = 1 if vector is None else vector[1]
    overlap = 1 if vector is None else (vector[3] if cell.protocol_id is ProtocolId.F else vector[4] if cell.protocol_id is ProtocolId.G else 1)
    ensemble_lambda = 0.0 if vector is None else float(vector[2])
    machine = TemporalBroker(protocol_id=cell.protocol_id.value, capacity=capacity, terminal_tick=3125, proposal_verifier=verify_normalized_policy, overlap_rows=overlap, ensemble_lambda=ensemble_lambda)
    executable: ActionChunk | None = None
    executor = representations.initial_executor_state(q0)
    previous_q_ref = np.array(q0, copy=True)
    events: list[dict[str, object]] = []
    injected_jump = 0.0
    move_ticks = set(cell.move_ticks)
    for tick in range(3125):
        machine.open_tick(tick)
        if tick in move_ticks:
            target = np.array(moved_target if np.array_equal(target, initial_target) else initial_target, copy=True)
            events.append({"tick": tick, "event_type": "TARGET_MOVED"})
        q, dq = arm.state()
        if tick in request_at:
            plan = request_at[tick]
            captures[plan.request_sequence] = (np.array(q, copy=True), np.array(target, copy=True), tick * _DT_NS)
            machine.request(
                f"r{plan.request_sequence}", plan.request_sequence,
                delivery_tick=plan.nominal_delivery_tick if plan.actual_delivery_tick is None else plan.actual_delivery_tick,
                stack_id="P4", skill_id="qualification-skill", expected_phase="track_target",
                source_observation_id=plan.request_sequence, source_observation_time_ns=tick * _DT_NS,
                drop=plan.disposition == "DROP",
            )
        if tick in delivery_at:
            plan = delivery_at[tick]
            q_request, target_request, source_time = captures[plan.request_sequence]
            start = kinematics.forward_kinematics(q_request, config.arm.link_lengths_m)
            knots = np.vstack([(1.0 - index / 8) * start + (index / 8) * target_request for index in range(9)])
            raw = PolicyRaw(f"{cell.cell_id}-r{plan.request_sequence}", "P4", "qualification-skill", plan.request_sequence, source_time, "track_target", knots)
            normalized = normalize_policy_raw(raw, tick, normal_delivery_tick=plan.nominal_delivery_tick, request_id=f"r{plan.request_sequence}", request_sequence=plan.request_sequence)
            if cell.fault_id in {FaultId.ALTERNATIVE, FaultId.DISCONTINUITY} and plan.request_sequence == len(plans) - 1:
                normalized = inject_fault(normalized, fault_id=cell.fault_id.value, envelope=(-1.0, 1.0))
                injected_jump = float(np.max(np.linalg.norm(np.diff(normalized.actions, axis=0), axis=1)))
            events.append({"tick": tick, "event_type": "PROPOSAL_BYTES", "proposal_id": normalized.proposal_id,
                           "request_id": normalized.request_id, "request_sequence": normalized.request_sequence,
                           "coverage": [normalized.coverage_start_tick, normalized.coverage_end_tick],
                           "policy_actions_sha256": normalized.policy_actions_sha256,
                           "normalized_actions_sha256": normalized.normalized_actions_sha256,
                           "raw_actions": normalized.raw_actions.tolist(), "normalized_actions": normalized.actions.tolist(),
                           "fault_id": normalized.fault_id, "fault_revision": normalized.fault_revision,
                           "fault_step_index": normalized.fault_step_index, "fault_amplitude": normalized.fault_amplitude,
                           "fault_direction": normalized.fault_direction, "fault_sign": normalized.fault_sign,
                           "pre_fault_normalized_sha256": normalized.pre_fault_normalized_sha256})
            machine.deliver(normalized); executable = None
        q, dq = arm.state()
        issued = machine.issue(measured_q=q)
        if issued.origin != "broker_safe_hold":
            active = machine.active
            assert active is not None
            if executable is None or executable.chunk_id != active.chunk_id:
                executable = ActionChunk(
                    chunk_id=active.chunk_id, skill_id=active.skill_id, source_observation_id=active.source_observation_id,
                    source_observation_time_ns=active.source_observation_time_ns, generated_time_ns=active.coverage[0] * _DT_NS,
                    valid_from_ns=active.coverage[0] * _DT_NS, expires_at_ns=active.coverage[1] * _DT_NS, dt_s=0.002,
                    actions=active.actions, representation=active.representation, expected_phase="track_target",
                    metadata={"origin": "broker_executable", "rule": active.rule, "parent_sha256s": active.parent_sha256s,
                              "parent_coverages": active.parent_coverages, "owner_observation_id": active.owner_observation_id,
                              "b": active.coverage[0], "z": active.coverage[1], "h": active.h, "output_sha256": active.output_sha256},
                )
            reference, executor, _ = representations.reference_for_tick(contracts.CommandStack.P4, executable, q, dq, tick * _DT_NS, executor, config)
            command_q = reference.q_ref; is_hold = False
        else:
            hold = machine.active
            assert isinstance(hold, ActionChunk) and hold.chunk_id == issued.chunk_id
            reference = dispatch_executable(hold, tick=tick)
            assert reference is not None and not isinstance(reference, ActionChunk)
            command_q = reference.q_ref; is_hold = True
        q_ref, torque, _ = arm_module.bounded_pd(q, dq, command_q, previous_q_ref, config.controller.pd_candidates[0][0], config.controller.pd_candidates[0][1], config)
        previous_q_ref = np.array(q_ref, copy=True)
        arm.step(torque)
        eef = arm.site_xy()
        telemetry[tick] = (q, dq, eef, target, q_ref, torque, float(np.linalg.norm(target - eef)), is_hold, machine.active is not None)
        machine.close_tick()
    recovery = True
    for move in cell.move_ticks:
        end = min(3125, move + 1001)
        success = telemetry["error"][move:end] <= config.thresholds["success_radius_m"]
        recovery &= any(np.all(success[index:index + 50]) for index in range(max(0, len(success) - 49)))
    fault_guard = not (cell.fault_id is FaultId.DISCONTINUITY and injected_jump > 0.025)
    finite = all(np.isfinite(telemetry[name]).all() for name in ("q", "dq", "eef", "q_ref", "torque", "error"))
    disposition = "WORKING" if recovery and fault_guard and finite else "NONWORKING"
    metrics = {"recovery_pass": bool(recovery), "fault_guard_pass": bool(fault_guard), "finite": bool(finite), "max_error_m": float(np.max(telemetry["error"])), "final_error_m": float(telemetry["error"][-1]), "hold_ticks": int(np.sum(telemetry["hold"])), "injected_jump": injected_jump, "disposition": disposition}
    machine.open_tick(3125); machine.finish()
    events.extend({"tick": event.tick, "event_type": event.event_type, "chunk_id": event.chunk_id, "detail": event.detail, "sidecar": None if event.sidecar is None else dict(event.sidecar)} for event in machine.events)
    events.extend({"tick": item.tick, "event_type": "HOLD_COMMAND_ISSUED", "chunk_id": item.chunk_id, "q_ref": item.action.tolist(), "dq_ref": [0.0, 0.0, 0.0]} for item in machine.issued if item.origin == "broker_safe_hold")
    phase = {"TARGET_MOVED": 0, "POLICY_REQUESTED": 1, "REQUEST_DROPPED": 1, "PROPOSAL_BYTES": 2,
             "CHUNK_EXPIRED": 3, "POLICY_RESPONDED": 4, "CHUNK_REPLACED": 5, "DERIVATION_RECOMPUTED": 5,
             "CHUNK_ACCEPTED": 6, "SAFE_HOLD_ENTERED": 7, "HOLD_COMMAND_ISSUED": 8, "TERMINAL_EMPTY": 9}
    events.sort(key=lambda row: (int(row["tick"]), phase[str(row["event_type"])], str(row.get("chunk_id", row.get("proposal_id", "")))))
    events = [{"sequence_id": sequence, **row} for sequence, row in enumerate(events)]
    return telemetry, metrics, events


def _summary(trials: list[dict[str, object]]) -> bytes:
    counts: dict[str, int] = {}
    for row in trials:
        key = f"{row['protocol_id']}|{row['fault_id']}|{row['latency_ticks']}|{row['disposition']}"
        counts[key] = counts.get(key, 0) + 1
    return _canonical({"schema_version": "exp02-unsealed-dynamics-summary-v1", "qualification_only": True, "sealed_pilot": False, "trial_count": len(trials), "counts": [{"identity": key, "count": counts[key]} for key in sorted(counts)]})


def _derived_files(trials: list[dict[str, object]], manifest_sha256: str) -> dict[str, bytes]:
    ordered = sorted(trials, key=lambda row: str(row["cell_id"]))
    samples = []
    for label in ("WORKING", "NONWORKING"):
        row = next(item for item in ordered if item["disposition"] == label)
        samples.append({"label": label, "cell_id": row["cell_id"], "telemetry_file": row["telemetry_file"], "telemetry_sha256": row["telemetry_sha256"], "events_sha256": row["events_sha256"], "selection": "FIRST_CANONICAL_ID"})
    recipe = {"schema_version": "exp02-unsealed-dynamics-recipe-v2", "renderer": "dynamics_qualification.py", "manifest_sha256": manifest_sha256, "event_link_formula": "sha256(canonical_json(event_row,sort_keys=True,separators=comma_colon,allow_nan=False)+LF)", "sort": ["cell_id"], "time_axis": {"column": "tick", "scale_s": 0.002}, "series": [{"column": "error", "units": "m"}, {"column": "q", "units": "rad"}, {"column": "torque", "units": "N*m"}], "sample_rule": "first canonical WORKING and NONWORKING"}
    return {"summary.json": _summary(trials), "sample-index.json": _canonical({"schema_version": "exp02-unsealed-dynamics-samples-v1", "samples": samples}), "recipe.json": _canonical(recipe)}


def run_dynamics_qualification(output: Path, *, seeds: Sequence[int], implementation_git_sha: str) -> None:
    if output.exists() or not seeds or any(type(seed) is not int or seed < 0 for seed in seeds):
        raise DynamicsQualificationError("output must be absent and seeds explicit")
    if len(implementation_git_sha) != 40 or any(character not in "0123456789abcdef" for character in implementation_git_sha):
        raise DynamicsQualificationError("implementation_git_sha must be lowercase SHA-1")
    config = contracts.load_config(Path("experiments/01_policy_control/configs/base.yaml"))
    raw = output / "raw"; telemetry_dir = raw / "telemetry"; derived = output / "derived"
    telemetry_dir.mkdir(parents=True); derived.mkdir()
    trials: list[dict[str, object]] = []; events: list[dict[str, object]] = []
    for seed in sorted(seeds):
        for cell in _selected_cells(seed):
            telemetry, metrics, cell_events = _run_cell(cell, config)
            filename = f"{cell.cell_id}.npy"
            _save_npy(telemetry_dir / filename, telemetry)
            telemetry_hash = _sha((telemetry_dir / filename).read_bytes())
            event_row = {"schema_version": "exp02-unsealed-dynamics-events-v1", "cell_id": cell.cell_id, "events": cell_events}
            events.append(event_row)
            trials.append({"schema_version": "exp02-unsealed-dynamics-trial-v1", "cell_id": cell.cell_id, "protocol_id": cell.protocol_id.value, "vector_id": None if cell.vector_id is None else cell.vector_id.value, "seed": seed, "latency_ticks": cell.latency_ticks, "fault_id": cell.fault_id.value, "move_ticks": list(cell.move_ticks), "qualification_only": True, "sealed_pilot": False, "telemetry_file": filename, "telemetry_sha256": telemetry_hash, "events_sha256": _sha(_canonical(event_row)), **metrics})
    trials_bytes = b"".join(_canonical(row) for row in trials); events_bytes = b"".join(_canonical(row) for row in events)
    (raw / "trials.jsonl").write_bytes(trials_bytes); (raw / "events.jsonl").write_bytes(events_bytes)
    members = [raw / "events.jsonl", raw / "trials.jsonl", *sorted(telemetry_dir.iterdir())]
    manifest = {"schema_version": "exp02-unsealed-dynamics-manifest-v2", "qualification_only": True, "sealed_pilot": False, "implementation_git_sha": implementation_git_sha, "mujoco_version": "3.12.0", "model_sha256": _sha(arm_module.MJCF_BYTES), "config_sha256": _sha(Path("experiments/01_policy_control/configs/base.yaml").read_bytes()), "event_link_formula": "sha256(canonical_json(event_row,sort_keys=True,separators=comma_colon,allow_nan=False)+LF)", "files": [{"path": path.relative_to(raw).as_posix(), "bytes": path.stat().st_size, "sha256": _sha(path.read_bytes())} for path in members]}
    manifest_bytes = _canonical(manifest); (raw / "manifest.json").write_bytes(manifest_bytes)
    for name, content in _derived_files(trials, _sha(manifest_bytes)).items():
        (derived / name).write_bytes(content)


def reconstruct_dynamics(raw: Path, clean: Path) -> None:
    if clean.exists() or not raw.is_dir() or raw.is_symlink():
        raise DynamicsQualificationError("raw must be regular and clean output absent")
    invalidation_path = raw.parent / "INVALIDATION.json"
    if invalidation_path.exists():
        invalidation_bytes = invalidation_path.read_bytes()
        invalidation = json.loads(invalidation_bytes)
        expected_reasons = ["PREFX_BROKER_BYPASS", "PREFX_DERIVATION_INCOMPLETE", "PREFX_EVENT_LINK_INCOMPLETE", "PREFX_UNSEALED_PROPOSAL"]
        if (_canonical(invalidation) != invalidation_bytes
                or invalidation.get("schema_version") != "exp02-invalid-evidence-v1"
                or invalidation.get("effective_disposition") != "INVALID_PRE_FIX"
                or invalidation.get("reason_ids") != expected_reasons
                or invalidation.get("raw_manifest_sha256") != _sha((raw / "manifest.json").read_bytes())
                or invalidation.get("trials_sha256") != _sha((raw / "trials.jsonl").read_bytes())
                or invalidation.get("events_sha256") != _sha((raw / "events.jsonl").read_bytes())):
            raise DynamicsQualificationError("invalid evidence record is malformed")
        raise DynamicsQualificationError("INVALID_PRE_FIX evidence is not consumable")
    manifest_bytes = (raw / "manifest.json").read_bytes(); manifest = json.loads(manifest_bytes)
    if _canonical(manifest) != manifest_bytes or manifest.get("qualification_only") is not True or manifest.get("sealed_pilot") is not False:
        raise DynamicsQualificationError("manifest is invalid")
    for row in manifest["files"]:
        path = raw / row["path"]
        if path.is_symlink() or not path.is_file() or path.stat().st_size != row["bytes"] or _sha(path.read_bytes()) != row["sha256"]:
            raise DynamicsQualificationError("raw member hash mismatch")
    trials = [json.loads(line) for line in (raw / "trials.jsonl").read_text(encoding="ascii").splitlines()]
    event_rows = [json.loads(line) for line in (raw / "events.jsonl").read_text(encoding="ascii").splitlines()]
    by_cell = {row["cell_id"]: row for row in event_rows}
    if len(by_cell) != len(event_rows):
        raise DynamicsQualificationError("duplicate event identity")
    expected_ids = {
        cell.cell_id
        for seed in sorted({trial["seed"] for trial in trials})
        for cell in _selected_cells(seed)
    }
    if {trial["cell_id"] for trial in trials} != expected_ids or set(by_cell) != expected_ids:
        raise DynamicsQualificationError("trial/event inventory is incomplete")
    config = contracts.load_config(Path("experiments/01_policy_control/configs/base.yaml"))
    cells = {cell.cell_id: cell for seed in sorted({trial["seed"] for trial in trials}) for cell in _selected_cells(seed)}
    for trial in trials:
        event_row = by_cell.get(trial["cell_id"])
        telemetry_path = raw / "telemetry" / trial["telemetry_file"]
        if event_row is None or _sha(_canonical(event_row)) != trial["events_sha256"] or _sha(telemetry_path.read_bytes()) != trial["telemetry_sha256"]:
            raise DynamicsQualificationError("trial event/telemetry link is invalid")
        if [event.get("sequence_id") for event in event_row["events"]] != list(range(len(event_row["events"]))) or any(event_row["events"][index]["tick"] > event_row["events"][index + 1]["tick"] for index in range(len(event_row["events"]) - 1)):
            raise DynamicsQualificationError("canonical event order is invalid")
        replay_telemetry, replay_metrics, replay_events = _run_cell(cells[trial["cell_id"]], config)
        stored_telemetry = np.load(telemetry_path, allow_pickle=False)
        if (stored_telemetry.dtype != replay_telemetry.dtype or stored_telemetry.shape != replay_telemetry.shape
                or stored_telemetry.tobytes(order="C") != replay_telemetry.tobytes(order="C")):
            raise DynamicsQualificationError("telemetry does not match deterministic broker/dynamics replay")
        if _canonical(replay_events) != _canonical(event_row["events"]):
            raise DynamicsQualificationError("events do not match exact proposal/broker/issue replay")
        if any(trial.get(key) != value for key, value in replay_metrics.items()):
            raise DynamicsQualificationError("trial metrics do not match telemetry replay")
    clean.mkdir(parents=True)
    for name, content in _derived_files(trials, _sha(manifest_bytes)).items():
        (clean / name).write_bytes(content)
