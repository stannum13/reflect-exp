"""Runnable, non-scientific qualification slice for P5 broker invariants."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence


class QualificationError(ValueError):
    """Qualification evidence is conflicting or cannot be reconstructed."""


@dataclass(frozen=True)
class QualificationCondition:
    condition_id: str
    protocol_id: str
    policy_condition: str
    latency_ticks: int
    expected_disposition: str


_CONDITIONS = (
    QualificationCondition("a-smooth-25", "A", "SMOOTH", 25, "WORKING"),
    QualificationCondition("a-drop-150", "A", "DROPPED", 150, "NONWORKING"),
    QualificationCondition("d-shift-25", "D", "TARGET_SHIFT", 25, "WORKING"),
    QualificationCondition(
        "d-discontinuous-150", "D", "DISCONTINUOUS", 150, "NONWORKING"
    ),
    QualificationCondition("f-alternative-25", "F", "ALTERNATIVE", 25, "WORKING"),
    QualificationCondition("f-drop-150", "F", "DROPPED", 150, "NONWORKING"),
)
_RAW_NAMES = (
    "events.jsonl",
    "trials.jsonl",
    "dispositions.jsonl",
    "manifest.json",
)
_DERIVED_NAMES = ("trial-table.csv", "sample-index.json", "recipe.json")
_TRIAL_KEYS = frozenset(
    {
        "schema_version",
        "study_id",
        "qualification_only",
        "protocol_revision",
        "condition_id",
        "protocol_id",
        "policy_condition",
        "seed",
        "rng_namespace",
        "latency_ticks",
        "tick_start",
        "tick_end",
        "units",
        "frame",
        "config_sha256",
        "events_sha256",
        "event_line_start",
        "event_line_end",
        "terminal_state",
        "validity",
        "disposition",
        "analysis_included",
    }
)
_DISPOSITION_KEYS = frozenset(
    {
        "schema_version",
        "study_id",
        "condition_id",
        "disposition",
        "reason",
        "analysis_included",
        "trial_sha256",
    }
)
_EVENT_BASE_KEYS = frozenset(
    {
        "schema_version",
        "study_id",
        "qualification_only",
        "condition_id",
        "sequence_id",
        "tick",
        "event_type",
    }
)
_EVENT_EXTRA_KEYS = {
    "POLICY_REQUESTED": frozenset(),
    "RESPONSE_DROPPED": frozenset(),
    "SAFE_HOLD_ENTERED": frozenset(),
    "TERMINAL_EMPTY": frozenset(),
    "POLICY_RESPONDED": frozenset(
        {"valid_from_tick", "valid_until_tick", "proposal_values"}
    ),
    "CHUNK_ACCEPTED": frozenset(
        {
            "valid_from_tick",
            "valid_until_tick",
            "proposal_values",
            "reconciliation",
            "blend_beta",
        }
    ),
    "ACTION_ISSUED": frozenset(
        {
            "value",
            "units",
            "frame",
            "valid_until_tick",
            "issued_prefix_sha256",
        }
    ),
}


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _jsonl(rows: Iterable[dict[str, object]]) -> bytes:
    return b"".join(_canonical(row) for row in rows)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise QualificationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_json(content: bytes, label: str) -> Any:
    try:
        return json.loads(
            content.decode("utf-8", "strict"), object_pairs_hook=_strict_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"{label} is not strict JSON") from exc


def _load_jsonl(content: bytes, label: str) -> list[dict[str, Any]]:
    if not content.endswith(b"\n"):
        raise QualificationError(f"{label} must end with LF")
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(content.splitlines(), start=1):
        value = _load_json(line, f"{label}:{index}")
        if not isinstance(value, dict) or _canonical(value).rstrip(b"\n") != line:
            raise QualificationError(f"{label}:{index} is not canonical")
        rows.append(value)
    return rows


def _event(
    condition: QualificationCondition,
    sequence: int,
    tick: int,
    event_type: str,
    **extra: object,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "study_id": "exp02-action-chunks",
        "qualification_only": True,
        "condition_id": condition.condition_id,
        "sequence_id": sequence,
        "tick": tick,
        "event_type": event_type,
        **extra,
    }


def _simulate(condition: QualificationCondition) -> list[dict[str, object]]:
    request_tick = 10
    delivery_tick = request_tick + condition.latency_ticks
    events = [_event(condition, 0, request_tick, "POLICY_REQUESTED")]
    if condition.policy_condition == "DROPPED":
        events.append(_event(condition, 1, delivery_tick, "RESPONSE_DROPPED"))
        events.append(
            _event(condition, 2, max(60, delivery_tick), "SAFE_HOLD_ENTERED")
        )
        events.append(_event(condition, 3, 249, "TERMINAL_EMPTY"))
        return events

    valid_until = min(delivery_tick + 50, 250)
    if condition.policy_condition == "DISCONTINUOUS":
        proposed = [0.0, 0.0, 0.4, -0.4, 0.4]
    elif condition.policy_condition == "TARGET_SHIFT":
        proposed = [0.05 * (offset + 1) for offset in range(5)]
    elif condition.policy_condition == "ALTERNATIVE":
        proposed = [0.0, 0.07, 0.10, 0.07, 0.0]
    else:
        proposed = [0.02 * offset for offset in range(5)]
    revised = [value + 0.01 for value in proposed]
    reconciliation = "OVERLAP_BLEND" if condition.protocol_id == "F" else "REPLACE"
    blend_beta: list[float] | None = (
        [(index + 1) / 3 for index in range(2)]
        if condition.protocol_id == "F"
        else None
    )
    events.extend(
        (
            _event(
                condition,
                1,
                delivery_tick,
                "POLICY_RESPONDED",
                valid_from_tick=delivery_tick,
                valid_until_tick=valid_until,
                proposal_values=proposed,
            ),
            _event(
                condition,
                2,
                delivery_tick,
                "CHUNK_ACCEPTED",
                valid_from_tick=delivery_tick,
                valid_until_tick=valid_until,
                proposal_values=proposed,
                reconciliation=reconciliation,
                blend_beta=blend_beta,
            ),
        )
    )
    issued: list[float] = []
    sequence = 3
    for offset in range(min(5, valid_until - delivery_tick)):
        tick = delivery_tick + offset
        if offset == 1:
            events.append(_event(condition, sequence, tick, "POLICY_REQUESTED"))
            sequence += 1
        if offset == 2:
            events.extend(
                (
                    _event(
                        condition,
                        sequence,
                        tick,
                        "POLICY_RESPONDED",
                        valid_from_tick=tick,
                        valid_until_tick=valid_until,
                        proposal_values=revised,
                    ),
                    _event(
                        condition,
                        sequence + 1,
                        tick,
                        "CHUNK_ACCEPTED",
                        valid_from_tick=tick,
                        valid_until_tick=valid_until,
                        proposal_values=revised,
                        reconciliation=reconciliation,
                        blend_beta=blend_beta,
                    ),
                )
            )
            sequence += 2
        if condition.protocol_id == "F" and offset in {2, 3}:
            beta = (offset - 1) / 3
            value = (1.0 - beta) * proposed[offset] + beta * revised[offset]
        elif offset >= 2:
            value = revised[offset]
        else:
            value = proposed[offset]
        issued.append(value)
        prefix_hash = _sha(_canonical([condition.condition_id, issued]))
        events.append(
            _event(
                condition,
                sequence,
                tick,
                "ACTION_ISSUED",
                value=value,
                units="normalized_action",
                frame="fixture_axis",
                valid_until_tick=valid_until,
                issued_prefix_sha256=prefix_hash,
            )
        )
        sequence += 1
    events.append(_event(condition, sequence, 249, "TERMINAL_EMPTY"))
    return events


def _build_raw() -> dict[str, bytes]:
    config_hash = _sha(
        _canonical(
            [
                [
                    item.condition_id,
                    item.protocol_id,
                    item.policy_condition,
                    item.latency_ticks,
                    item.expected_disposition,
                ]
                for item in _CONDITIONS
            ]
        )
    )
    events: list[dict[str, object]] = []
    trials: list[dict[str, object]] = []
    dispositions: list[dict[str, object]] = []
    for condition in _CONDITIONS:
        case_events = _simulate(condition)
        first_line = len(events) + 1
        events.extend(case_events)
        last_line = len(events)
        event_hash = _sha(_jsonl(case_events))
        trials.append(
            {
                "schema_version": 1,
                "study_id": "exp02-action-chunks",
                "qualification_only": True,
                "protocol_revision": "exp02-qualification-v1",
                "condition_id": condition.condition_id,
                "protocol_id": condition.protocol_id,
                "policy_condition": condition.policy_condition,
                "seed": 0,
                "rng_namespace": "exp02-qualification-fixed-v1",
                "latency_ticks": condition.latency_ticks,
                "tick_start": 0,
                "tick_end": 249,
                "units": "normalized_action",
                "frame": "fixture_axis",
                "config_sha256": config_hash,
                "events_sha256": event_hash,
                "event_line_start": first_line,
                "event_line_end": last_line,
                "terminal_state": "EMPTY",
                "validity": "VALID",
                "disposition": condition.expected_disposition,
                "analysis_included": False,
            }
        )
        dispositions.append(
            {
                "schema_version": 1,
                "study_id": "exp02-action-chunks",
                "condition_id": condition.condition_id,
                "disposition": condition.expected_disposition,
                "reason": (
                    "BROKER_INVARIANTS_PASS"
                    if condition.expected_disposition == "WORKING"
                    else "OBSERVED_QUALIFICATION_FAILURE"
                ),
                "analysis_included": False,
                "trial_sha256": _sha(_canonical(trials[-1])),
            }
        )
    raw = {
        "events.jsonl": _jsonl(events),
        "trials.jsonl": _jsonl(trials),
        "dispositions.jsonl": _jsonl(dispositions),
    }
    raw["manifest.json"] = _canonical(
        {
            "schema_version": 1,
            "study_id": "exp02-action-chunks",
            "qualification_only": True,
            "files": [
                {"path": name, "bytes": len(raw[name]), "sha256": _sha(raw[name])}
                for name in sorted(raw)
            ],
        }
    )
    return raw


def _validated_raw(raw_dir: Path) -> tuple[
    dict[str, bytes], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]:
    if raw_dir.is_symlink() or not raw_dir.is_dir():
        raise QualificationError("raw evidence directory is not regular")
    names = tuple(sorted(path.name for path in raw_dir.iterdir()))
    if names != tuple(sorted(_RAW_NAMES)):
        raise QualificationError("raw evidence inventory is not closed")
    content: dict[str, bytes] = {}
    for name in _RAW_NAMES:
        path = raw_dir / name
        if path.is_symlink() or not path.is_file():
            raise QualificationError(f"raw evidence member is not regular: {name}")
        content[name] = path.read_bytes()
    manifest = _load_json(content["manifest.json"], "manifest")
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "study_id",
        "qualification_only",
        "files",
    }:
        raise QualificationError("raw manifest schema is invalid")
    expected_files = [
        {"path": name, "bytes": len(content[name]), "sha256": _sha(content[name])}
        for name in sorted(name for name in _RAW_NAMES if name != "manifest.json")
    ]
    if manifest != {
        "schema_version": 1,
        "study_id": "exp02-action-chunks",
        "qualification_only": True,
        "files": expected_files,
    }:
        raise QualificationError("raw manifest hash inventory is invalid")
    trials = _load_jsonl(content["trials.jsonl"], "trials")
    events = _load_jsonl(content["events.jsonl"], "events")
    dispositions = _load_jsonl(content["dispositions.jsonl"], "dispositions")
    _validate_evidence_rows(trials, events, dispositions)
    if len(trials) != len(_CONDITIONS) or len(dispositions) != len(trials):
        raise QualificationError("every scheduled trial requires one disposition")
    if [row.get("condition_id") for row in trials] != [
        row.get("condition_id") for row in dispositions
    ]:
        raise QualificationError("trial/disposition identities differ")
    for trial in trials:
        start = trial.get("event_line_start")
        end = trial.get("event_line_end")
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(events):
            raise QualificationError("trial event range is invalid")
        selected = events[start - 1 : end]
        if _sha(_jsonl(selected)) != trial.get("events_sha256"):
            raise QualificationError("trial event hash is invalid")
    return content, trials, events, dispositions


def _validate_evidence_rows(
    trials: list[dict[str, Any]],
    events: list[dict[str, Any]],
    dispositions: list[dict[str, Any]],
) -> None:
    if len(trials) != len(_CONDITIONS) or len(dispositions) != len(_CONDITIONS):
        raise QualificationError("every scheduled trial requires one disposition")
    expected_ids = [condition.condition_id for condition in _CONDITIONS]
    if [row.get("condition_id") for row in trials] != expected_ids:
        raise QualificationError("trial condition inventory is invalid")
    if [row.get("condition_id") for row in dispositions] != expected_ids:
        raise QualificationError("disposition condition inventory is invalid")

    previous_end = 0
    for condition, trial, disposition in zip(_CONDITIONS, trials, dispositions):
        if set(trial) != _TRIAL_KEYS:
            raise QualificationError("trial schema has missing or unknown keys")
        if set(disposition) != _DISPOSITION_KEYS:
            raise QualificationError("disposition schema has missing or unknown keys")
        expected_trial_scalars = {
            "schema_version": 1,
            "study_id": "exp02-action-chunks",
            "qualification_only": True,
            "protocol_revision": "exp02-qualification-v1",
            "condition_id": condition.condition_id,
            "protocol_id": condition.protocol_id,
            "policy_condition": condition.policy_condition,
            "seed": 0,
            "rng_namespace": "exp02-qualification-fixed-v1",
            "latency_ticks": condition.latency_ticks,
            "tick_start": 0,
            "tick_end": 249,
            "units": "normalized_action",
            "frame": "fixture_axis",
            "terminal_state": "EMPTY",
            "validity": "VALID",
            "disposition": condition.expected_disposition,
            "analysis_included": False,
        }
        if any(trial.get(key) != value for key, value in expected_trial_scalars.items()):
            raise QualificationError("trial identity, authority, or disposition is invalid")
        if not isinstance(trial.get("config_sha256"), str) or len(
            trial["config_sha256"]
        ) != 64:
            raise QualificationError("trial config hash is invalid")
        start = trial.get("event_line_start")
        end = trial.get("event_line_end")
        if (
            type(start) is not int
            or type(end) is not int
            or start != previous_end + 1
            or not start <= end <= len(events)
        ):
            raise QualificationError("trial event range is invalid")
        previous_end = end
        selected = events[start - 1 : end]
        _validate_case_events(condition, selected)
        if _sha(_jsonl(selected)) != trial.get("events_sha256"):
            raise QualificationError("trial event hash is invalid")
        expected_reason = (
            "BROKER_INVARIANTS_PASS"
            if condition.expected_disposition == "WORKING"
            else "OBSERVED_QUALIFICATION_FAILURE"
        )
        if disposition != {
            "schema_version": 1,
            "study_id": "exp02-action-chunks",
            "condition_id": condition.condition_id,
            "disposition": condition.expected_disposition,
            "reason": expected_reason,
            "analysis_included": False,
            "trial_sha256": _sha(_canonical(trial)),
        }:
            raise QualificationError("disposition does not bind the scheduled trial")
    if previous_end != len(events):
        raise QualificationError("unreferenced raw events are forbidden")


def _validate_case_events(
    condition: QualificationCondition, events: list[dict[str, Any]]
) -> None:
    if not events:
        raise QualificationError("trial has no raw events")
    issued_values: list[float] = []
    event_types: list[str] = []
    for sequence, event in enumerate(events):
        event_type = event.get("event_type")
        if not isinstance(event_type, str) or event_type not in _EVENT_EXTRA_KEYS:
            raise QualificationError("event type is invalid")
        if set(event) != _EVENT_BASE_KEYS | _EVENT_EXTRA_KEYS[event_type]:
            raise QualificationError("event schema has missing or unknown keys")
        tick = event.get("tick")
        if (
            event.get("schema_version") != 1
            or event.get("study_id") != "exp02-action-chunks"
            or event.get("qualification_only") is not True
            or event.get("condition_id") != condition.condition_id
            or event.get("sequence_id") != sequence
            or type(tick) is not int
            or not 0 <= tick <= 249
        ):
            raise QualificationError("event identity or tick is invalid")
        event_types.append(event_type)
        if event_type == "ACTION_ISSUED":
            value = event.get("value")
            valid_until = event.get("valid_until_tick")
            if (
                type(value) is not float
                or not math.isfinite(value)
                or type(valid_until) is not int
                or tick >= valid_until
                or event.get("units") != "normalized_action"
                or event.get("frame") != "fixture_axis"
            ):
                raise QualificationError("expired, nonfinite, or invalid action issue")
            issued_values.append(value)
            if event.get("issued_prefix_sha256") != _sha(
                _canonical([condition.condition_id, issued_values])
            ):
                raise QualificationError("issued action prefix was not immutable")
        elif event_type in {"POLICY_RESPONDED", "CHUNK_ACCEPTED"}:
            valid_from = event.get("valid_from_tick")
            valid_until = event.get("valid_until_tick")
            proposal = event.get("proposal_values")
            if (
                type(valid_from) is not int
                or type(valid_until) is not int
                or not valid_from < valid_until <= 250
                or not isinstance(proposal, list)
                or len(proposal) != 5
                or any(type(value) is not float or not math.isfinite(value) for value in proposal)
            ):
                raise QualificationError("proposal validity or finite payload is invalid")
            if event_type == "CHUNK_ACCEPTED":
                expected_reconciliation = (
                    "OVERLAP_BLEND" if condition.protocol_id == "F" else "REPLACE"
                )
                expected_beta = (
                    [(index + 1) / 3 for index in range(2)]
                    if condition.protocol_id == "F"
                    else None
                )
                if (
                    event.get("reconciliation") != expected_reconciliation
                    or event.get("blend_beta") != expected_beta
                ):
                    raise QualificationError("protocol reconciliation evidence is invalid")
    if event_types[0] != "POLICY_REQUESTED" or event_types[-1] != "TERMINAL_EMPTY":
        raise QualificationError("case lifecycle is not closed")
    if condition.policy_condition == "DROPPED":
        if (
            event_types != [
                "POLICY_REQUESTED",
                "RESPONSE_DROPPED",
                "SAFE_HOLD_ENTERED",
                "TERMINAL_EMPTY",
            ]
            or issued_values
        ):
            raise QualificationError("dropped response must enter hold without issue")
        observed = "NONWORKING"
    else:
        if (
            event_types[1:3] != ["POLICY_RESPONDED", "CHUNK_ACCEPTED"]
            or "SAFE_HOLD_ENTERED" in event_types
            or not issued_values
        ):
            raise QualificationError("accepted proposal lifecycle is invalid")
        discontinuity = max(
            (abs(right - left) for left, right in zip(issued_values, issued_values[1:])),
            default=0.0,
        )
        observed = "NONWORKING" if discontinuity > 0.25 else "WORKING"
    if observed != condition.expected_disposition:
        raise QualificationError("observed qualification disposition is invalid")


def _derived(raw_dir: Path) -> dict[str, bytes]:
    raw, trials, _, _ = _validated_raw(raw_dir)
    columns = (
        "condition_id",
        "protocol_id",
        "policy_condition",
        "latency_ticks",
        "disposition",
        "terminal_state",
        "analysis_included",
    )
    table_lines = [",".join(columns)]
    for trial in trials:
        table_lines.append(
            ",".join(
                "false" if trial[key] is False else str(trial[key]) for key in columns
            )
        )
    table = ("\n".join(table_lines) + "\n").encode("utf-8")

    samples: list[dict[str, object]] = []
    for trial in sorted(
        trials,
        key=lambda row: (
            str(row["protocol_id"]),
            str(row["policy_condition"]),
            int(row["seed"]),
            str(row["condition_id"]),
        ),
    ):
        observed = str(trial["disposition"])
        samples.append(
            {
                "protocol_id": trial["protocol_id"],
                "policy_condition": trial["policy_condition"],
                "label": observed,
                "condition_id": trial["condition_id"],
                "eligible_denominator": 1,
                "event_line_start": trial["event_line_start"],
                "event_line_end": trial["event_line_end"],
                "command": "python -m experiments.02_action_chunks.src.qualification",
                "raw_events_sha256": _sha(raw["events.jsonl"]),
                "raw_trial_sha256": _sha(_canonical(trial)),
            }
        )
        missing = "NONWORKING" if observed == "WORKING" else "WORKING"
        samples.append(
            {
                "protocol_id": trial["protocol_id"],
                "policy_condition": trial["policy_condition"],
                "label": "CLASS_NOT_OBSERVED",
                "missing_class": missing,
                "condition_id": None,
                "eligible_denominator": 1,
                "event_line_start": None,
                "event_line_end": None,
                "command": "python -m experiments.02_action_chunks.src.qualification",
                "raw_events_sha256": _sha(raw["events.jsonl"]),
                "raw_trial_sha256": None,
            }
        )
    sample_index = _canonical(
        {
            "schema_version": 1,
            "study_id": "exp02-action-chunks",
            "qualification_only": True,
            "selection_rule": "ascending-seed-condition-first-per-class-v1",
            "samples": samples,
        }
    )
    recipe = _canonical(
        {
            "schema_version": 1,
            "study_id": "exp02-action-chunks",
            "qualification_only": True,
            "renderer": "exp02-qualification-v1",
            "renderer_seed": 0,
            "source_hashes": {
                name: _sha(raw[name])
                for name in ("events.jsonl", "trials.jsonl", "dispositions.jsonl")
            },
            "filters": {"analysis_included": False},
            "sort": ["protocol_id", "policy_condition", "seed", "condition_id"],
            "axes": {"x": "latency_ticks", "y": "disposition"},
            "units": {"x": "ticks", "y": "closed_class"},
            "outputs": {
                "trial-table.csv": _sha(table),
                "sample-index.json": _sha(sample_index),
            },
        }
    )
    return {
        "trial-table.csv": table,
        "sample-index.json": sample_index,
        "recipe.json": recipe,
    }


def reconstruct_qualification(raw_dir: Path, clean_dir: Path) -> None:
    if clean_dir.exists() or clean_dir.is_symlink():
        raise QualificationError("reconstruction requires an absent clean directory")
    derived = _derived(Path(raw_dir))
    clean_dir.mkdir(parents=False)
    for name in _DERIVED_NAMES:
        (clean_dir / name).write_bytes(derived[name])


def run_qualification(output_dir: Path) -> None:
    output_dir = Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise QualificationError("qualification output directory must be absent")
    raw_dir = output_dir / "raw"
    derived_dir = output_dir / "derived"
    raw_dir.mkdir(parents=True)
    for name, content in _build_raw().items():
        (raw_dir / name).write_bytes(content)
    reconstruct_qualification(raw_dir, derived_dir)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reconstruct-from", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.reconstruct_from is not None:
        reconstruct_qualification(arguments.reconstruct_from, arguments.output_dir)
    else:
        run_qualification(arguments.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
