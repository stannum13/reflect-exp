from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest


qualification = importlib.import_module(
    "experiments.02_action_chunks.src.qualification"
)


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("ascii")


def _rewrite_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_bytes(b"".join(_canonical(row) for row in rows))


def _reseal_manifest(raw_dir: Path) -> None:
    manifest_path = raw_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [
        {
            "path": path.name,
            "bytes": len(path.read_bytes()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(raw_dir.iterdir())
        if path.name != "manifest.json"
    ]
    manifest_path.write_bytes(_canonical(manifest))


def test_slice_preserves_varied_working_and_nonworking_cases(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    qualification.run_qualification(output)

    trials = _jsonl(output / "raw/trials.jsonl")
    assert {
        (row["protocol_id"], row["policy_condition"], row["latency_ticks"])
        for row in trials
    } == {
        ("A", "SMOOTH", 25),
        ("A", "DROPPED", 150),
        ("D", "TARGET_SHIFT", 25),
        ("D", "DISCONTINUOUS", 150),
        ("F", "ALTERNATIVE", 25),
        ("F", "DROPPED", 150),
    }
    assert {row["disposition"] for row in trials} == {"WORKING", "NONWORKING"}
    assert all(row["qualification_only"] is True for row in trials)
    assert all(row["analysis_included"] is False for row in trials)
    dispositions = _jsonl(output / "raw/dispositions.jsonl")
    assert [row["condition_id"] for row in dispositions] == [
        row["condition_id"] for row in trials
    ]
    assert len(dispositions) == len(trials) == 6

    sample_index = json.loads(
        (output / "derived/sample-index.json").read_text(encoding="utf-8")
    )
    labels = {row["label"] for row in sample_index["samples"]}
    assert {"WORKING", "NONWORKING", "CLASS_NOT_OBSERVED"} <= labels
    observed = [
        row for row in sample_index["samples"] if row["label"] != "CLASS_NOT_OBSERVED"
    ]
    assert all(row["event_line_start"] <= row["event_line_end"] for row in observed)
    assert all(row["raw_events_sha256"] == hashlib.sha256(
        (output / "raw/events.jsonl").read_bytes()
    ).hexdigest() for row in observed)


def test_slice_never_issues_expired_rows_and_preserves_prior_issues(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    qualification.run_qualification(output)
    events = _jsonl(output / "raw/events.jsonl")
    issued = [row for row in events if row["event_type"] == "ACTION_ISSUED"]
    assert issued
    assert all(row["tick"] < row["valid_until_tick"] for row in issued)
    assert len({row["issued_prefix_sha256"] for row in issued}) == len(issued)
    holds = [row for row in events if row["event_type"] == "SAFE_HOLD_ENTERED"]
    assert {row["condition_id"] for row in holds} == {"a-drop-150", "f-drop-150"}

    by_condition: dict[str, list[float]] = {}
    for row in issued:
        values = by_condition.setdefault(str(row["condition_id"]), [])
        values.append(float(row["value"]))
        assert row["issued_prefix_sha256"] == hashlib.sha256(
            _canonical([row["condition_id"], values])
        ).hexdigest()
    smooth_events = [
        row for row in events if row["condition_id"] == "a-smooth-25"
    ]
    response_positions = [
        index
        for index, row in enumerate(smooth_events)
        if row["event_type"] == "POLICY_RESPONDED"
    ]
    first_issue = next(
        index
        for index, row in enumerate(smooth_events)
        if row["event_type"] == "ACTION_ISSUED"
    )
    assert len(response_positions) == 2
    assert first_issue < response_positions[1]
    f_accepts = [
        row
        for row in events
        if row["condition_id"] == "f-alternative-25"
        and row["event_type"] == "CHUNK_ACCEPTED"
    ]
    assert all(row["reconciliation"] == "OVERLAP_BLEND" for row in f_accepts)
    assert all(row["blend_beta"] == [1 / 3, 2 / 3] for row in f_accepts)


def test_discontinuity_is_retained_as_observed_nonworking_case(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    qualification.run_qualification(output)
    trials = {row["condition_id"]: row for row in _jsonl(output / "raw/trials.jsonl")}
    events = _jsonl(output / "raw/events.jsonl")
    issued = [
        float(row["value"])
        for row in events
        if row["condition_id"] == "d-discontinuous-150"
        and row["event_type"] == "ACTION_ISSUED"
    ]
    assert max(abs(right - left) for left, right in zip(issued, issued[1:])) > 0.25
    assert trials["d-discontinuous-150"]["disposition"] == "NONWORKING"


def test_reconstruction_is_byte_exact_in_clean_directory(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    clean = tmp_path / "clean"
    qualification.run_qualification(output)
    qualification.reconstruct_qualification(output / "raw", clean)
    assert _tree_bytes(output / "derived") == _tree_bytes(clean)
    with pytest.raises(qualification.QualificationError, match="absent|clean"):
        qualification.reconstruct_qualification(output / "raw", clean)


def test_reconstruction_ignores_hand_picked_derived_sample_index(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    clean = tmp_path / "clean"
    qualification.run_qualification(output)
    sample_path = output / "derived/sample-index.json"
    sample_path.write_bytes(b'{"samples":[{"label":"HAND_PICKED"}]}\n')
    qualification.reconstruct_qualification(output / "raw", clean)
    assert (clean / "sample-index.json").read_bytes() != sample_path.read_bytes()
    assert b"HAND_PICKED" not in (clean / "sample-index.json").read_bytes()


def test_reconstruction_cli_uses_explicit_clean_output(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    clean = tmp_path / "clean"
    qualification.run_qualification(output)
    assert qualification.main(
        ["--output-dir", str(clean), "--reconstruct-from", str(output / "raw")]
    ) == 0
    assert _tree_bytes(output / "derived") == _tree_bytes(clean)


def test_two_fresh_runs_are_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    qualification.run_qualification(first)
    qualification.run_qualification(second)
    assert _tree_bytes(first) == _tree_bytes(second)


def test_conflicting_or_partial_output_is_rejected(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    output.mkdir()
    (output / "unexpected").write_text("conflict\n", encoding="utf-8")
    with pytest.raises(qualification.QualificationError, match="absent"):
        qualification.run_qualification(output)


def test_duplicate_or_unknown_raw_keys_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate"
    qualification.run_qualification(duplicate)
    trials_path = duplicate / "raw/trials.jsonl"
    first, *rest = trials_path.read_bytes().splitlines()
    duplicate_first = first[:-1] + b',"condition_id":"duplicate"}'
    trials_path.write_bytes(b"\n".join([duplicate_first, *rest]) + b"\n")
    _reseal_manifest(duplicate / "raw")
    with pytest.raises(qualification.QualificationError, match="duplicate"):
        qualification.reconstruct_qualification(duplicate / "raw", tmp_path / "clean-a")

    unknown = tmp_path / "unknown"
    qualification.run_qualification(unknown)
    trials = _jsonl(unknown / "raw/trials.jsonl")
    trials[0]["undeclared"] = True
    _rewrite_jsonl(unknown / "raw/trials.jsonl", trials)
    _reseal_manifest(unknown / "raw")
    with pytest.raises(qualification.QualificationError, match="schema|unknown"):
        qualification.reconstruct_qualification(unknown / "raw", tmp_path / "clean-b")


def test_missing_disposition_is_rejected(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    qualification.run_qualification(output)
    dispositions_path = output / "raw/dispositions.jsonl"
    dispositions = _jsonl(dispositions_path)[:-1]
    _rewrite_jsonl(dispositions_path, dispositions)
    _reseal_manifest(output / "raw")
    with pytest.raises(qualification.QualificationError, match="disposition"):
        qualification.reconstruct_qualification(output / "raw", tmp_path / "clean")


def test_expired_action_row_is_rejected_even_when_hashes_are_resealed(
    tmp_path: Path,
) -> None:
    output = tmp_path / "evidence"
    qualification.run_qualification(output)
    raw_dir = output / "raw"
    events = _jsonl(raw_dir / "events.jsonl")
    trials = _jsonl(raw_dir / "trials.jsonl")
    event = next(row for row in events if row["event_type"] == "ACTION_ISSUED")
    event["tick"] = event["valid_until_tick"]
    trial = next(row for row in trials if row["condition_id"] == event["condition_id"])
    selected = events[
        int(trial["event_line_start"]) - 1 : int(trial["event_line_end"])
    ]
    trial["events_sha256"] = hashlib.sha256(
        b"".join(_canonical(row) for row in selected)
    ).hexdigest()
    _rewrite_jsonl(raw_dir / "events.jsonl", events)
    _rewrite_jsonl(raw_dir / "trials.jsonl", trials)
    _reseal_manifest(raw_dir)
    with pytest.raises(qualification.QualificationError, match="expired|valid"):
        qualification.reconstruct_qualification(raw_dir, tmp_path / "clean")
