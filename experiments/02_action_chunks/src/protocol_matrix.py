"""Qualification-only B/C/E/G transition matrix with reconstructable raw evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Iterable, Sequence

from .contracts import FaultId, ProtocolId, VectorId
from .schedule import iter_cells, iter_request_ticks, schedule_sha256


class MatrixError(ValueError):
    pass


def receding_prefix(old: Sequence[float], new: Sequence[float], issued_rows: int) -> tuple[float, ...]:
    if type(issued_rows) is not int or not 0 <= issued_rows <= len(old):
        raise MatrixError("invalid issued prefix")
    return tuple(float(value) for value in old[:issued_rows]) + tuple(float(value) for value in new)


def temporal_ensemble(old: Sequence[float], new: Sequence[float]) -> tuple[float, ...]:
    if len(old) != len(new) or not old:
        raise MatrixError("ensemble requires equal nonempty futures")
    return tuple((float(left) + float(right)) / 2.0 for left, right in zip(old, new))


def async_continuity(latency_ticks: int, lead_ticks: int) -> tuple[str, int]:
    if type(latency_ticks) is not int or type(lead_ticks) is not int or min(latency_ticks, lead_ticks) <= 0:
        raise MatrixError("latency and lead must be positive integers")
    if latency_ticks < lead_ticks:
        return "STRICT_OVERLAP", 0
    if latency_ticks == lead_ticks:
        return "EXPIRY_HANDOFF", 0
    return "UNAVOIDABLE_HOLD", latency_ticks - lead_ticks


def rtc_projection(old: Sequence[float], new: Sequence[float], overlap_rows: int) -> tuple[float, ...]:
    if len(old) != len(new) or not old or type(overlap_rows) is not int or not 0 <= overlap_rows <= len(old):
        raise MatrixError("invalid RTC projection inputs")
    result = [float(value) for value in new]
    for index in range(overlap_rows):
        gamma = (overlap_rows - index) / overlap_rows
        result[index] = gamma * float(old[index]) + (1.0 - gamma) * float(new[index])
    return tuple(result)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _jsonl(rows: Iterable[dict[str, object]]) -> bytes:
    return b"".join(_canonical(row) for row in rows)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _case(protocol: ProtocolId, seed: int, latency: int, condition: str) -> tuple[dict[str, object], dict[str, object]]:
    vector = VectorId.V1
    fault = {
        ProtocolId.B: FaultId.DROP,
        ProtocolId.C: FaultId.OLD_AFTER_NEWER,
        ProtocolId.E: FaultId.PAUSE,
        ProtocolId.G: FaultId.ALTERNATIVE,
    }[protocol] if condition == "FAULT" else FaultId.NONE
    cells = iter_cells("tuning", [{"stack_id": "QUALIFICATION", "protocol_id": protocol.value, "vector_id": vector.value, "seed": seed}])
    if fault is FaultId.NONE:
        cell = next(item for item in cells if item.fault_id is fault and item.latency_ticks == latency and item.move_ticks == (51,))
    else:
        cell = next(item for item in cells if item.fault_id is fault)
    plans = iter_request_ticks(cell)
    old = (0.0, 0.0, 9.0)
    new = (3.0, 6.0, 9.0)
    detail: dict[str, object]
    disposition = "WORKING"
    if protocol is ProtocolId.B:
        output = receding_prefix(old, new, 2)
        detail = {"issued": list(output), "transition": "RECEDING_PREFIX"}
        if fault is FaultId.DROP:
            disposition = "NONWORKING"
            detail = {"hold_after_exhaustion": True, "transition": "DROP_TO_HOLD"}
    elif protocol is ProtocolId.C:
        output = temporal_ensemble(old, new)
        detail = {"issued": list(output), "transition": "TEMPORAL_ENSEMBLE"}
        if fault is FaultId.OLD_AFTER_NEWER:
            detail = {"accepted_sequence": 2, "rejected_sequence": 1, "transition": "OUT_OF_ORDER_REJECTED"}
    elif protocol is ProtocolId.E:
        continuity, hold = async_continuity(cell.latency_ticks, 75)
        detail = {"continuity_class": continuity, "hold_ticks": hold, "transition": "ASYNC_SAFE_PREFIX"}
        if hold:
            disposition = "NONWORKING"
    else:
        output = rtc_projection(old, new, 2)
        detail = {"issued": list(output), "rtc_role": "RTC_APPROXIMATION", "transition": "COMMITTED_FUTURE_PROJECTION"}
    identity = f"{protocol.value}-{condition.lower()}-s{seed}-l{cell.latency_ticks}"
    event = {
        "schema_version": "exp02-protocol-matrix-event-v1",
        "identity": identity,
        "protocol_id": protocol.value,
        "fault_id": fault.value,
        "request_plans": [
            {"sequence": plan.request_sequence, "request_tick": plan.request_tick, "delivery_tick": plan.actual_delivery_tick, "expiry_tick": plan.expiry_tick, "disposition": plan.disposition}
            for plan in plans
        ],
        "detail": detail,
    }
    trial = {
        "schema_version": "exp02-protocol-matrix-trial-v1",
        "identity": identity,
        "qualification_only": True,
        "protocol_id": protocol.value,
        "vector_id": vector.value,
        "seed": seed,
        "condition": condition,
        "fault_id": fault.value,
        "latency_ticks": cell.latency_ticks,
        "continuity_class": cell.continuity_class,
        "schedule_sha256": schedule_sha256((cell,)),
        "event_sha256": _sha(_canonical(event)),
        "disposition": disposition,
        "analysis_included": False,
    }
    return event, trial


def _derive(raw: dict[str, bytes]) -> dict[str, bytes]:
    trials = [json.loads(line) for line in raw["trials.jsonl"].splitlines()]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(("protocol_id", "condition", "seed", "latency_ticks", "fault_id", "continuity_class", "disposition", "identity"))
    for row in trials:
        writer.writerow(tuple(row[key] for key in ("protocol_id", "condition", "seed", "latency_ticks", "fault_id", "continuity_class", "disposition", "identity")))
    recipe = {
        "schema_version": "exp02-protocol-matrix-recipe-v1",
        "renderer": "protocol_matrix.py",
        "sort": ["protocol_id", "condition", "seed", "latency_ticks", "identity"],
        "source_hashes": {name: _sha(content) for name, content in sorted(raw.items())},
    }
    return {"trial-table.csv": stream.getvalue().encode("utf-8"), "recipe.json": _canonical(recipe)}


def _write_absent(root: Path, files: dict[str, bytes]) -> None:
    if root.exists():
        raise MatrixError("output must be absent")
    root.mkdir(parents=True)
    for name, content in files.items():
        (root / name).write_bytes(content)


def run_matrix(output: Path, *, seeds: Sequence[int], latencies: Sequence[int]) -> None:
    if output.exists():
        raise MatrixError("output must be absent")
    if tuple(latencies) != (25, 75, 150) or not seeds or any(type(seed) is not int for seed in seeds):
        raise MatrixError("matrix requires explicit seeds and latencies 25/75/150")
    events: list[dict[str, object]] = []
    trials: list[dict[str, object]] = []
    for protocol in (ProtocolId.B, ProtocolId.C, ProtocolId.E, ProtocolId.G):
        for seed in sorted(seeds):
            for latency in latencies:
                event, trial = _case(protocol, seed, latency, "CORE")
                events.append(event)
                trials.append(trial)
            event, trial = _case(protocol, seed, 150, "FAULT")
            events.append(event)
            trials.append(trial)
    raw = {"events.jsonl": _jsonl(events), "trials.jsonl": _jsonl(trials)}
    raw["manifest.json"] = _canonical({"schema_version": "exp02-protocol-matrix-manifest-v1", "files": [{"path": name, "bytes": len(content), "sha256": _sha(content)} for name, content in sorted(raw.items())]})
    output.mkdir(parents=True)
    _write_absent(output / "raw", raw)
    _write_absent(output / "derived", _derive(raw))


def reconstruct_matrix(raw_dir: Path, clean_dir: Path) -> None:
    if clean_dir.exists() or raw_dir.is_symlink() or not raw_dir.is_dir():
        raise MatrixError("clean output must be absent and raw must be regular")
    names = tuple(sorted(path.name for path in raw_dir.iterdir()))
    if names != ("events.jsonl", "manifest.json", "trials.jsonl"):
        raise MatrixError("raw inventory is not closed")
    raw = {name: (raw_dir / name).read_bytes() for name in names if name != "manifest.json"}
    manifest = json.loads((raw_dir / "manifest.json").read_bytes())
    expected = {"schema_version": "exp02-protocol-matrix-manifest-v1", "files": [{"path": name, "bytes": len(content), "sha256": _sha(content)} for name, content in sorted(raw.items())]}
    if manifest != expected or _canonical(manifest) != (raw_dir / "manifest.json").read_bytes():
        raise MatrixError("raw manifest is invalid")
    raw["manifest.json"] = (raw_dir / "manifest.json").read_bytes()
    _write_absent(clean_dir, _derive(raw))
