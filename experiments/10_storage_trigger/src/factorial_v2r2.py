"""Hardened, reconstructible Experiment 10 V2R2 evidence pipeline."""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
from pathlib import Path
import platform
import subprocess
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from . import factorial_v2 as v2
from .factorial_v2r2_scorer import LedgerScoreError, PLANNER_ID, score_episode


ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "configs/storage-trigger-factorial-v2r2.json"
SEEDS_PATH = ROOT / "configs/seeds-v2r2.json"
RETIRED_INVALID_ROOT = ROOT / "results/storage-trigger-factorial-v2-invalid-attempt-d21aab1"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="ascii"))
SEED_MANIFEST = json.loads(SEEDS_PATH.read_text(encoding="ascii"))
STORAGE_VARIANTS = tuple(CONFIG["storage_variants"])
TRIGGER_VARIANTS = tuple(CONFIG["trigger_variants"])
DISTURBANCE_FAMILIES = tuple(CONFIG["disturbance_families"])
SEVERITIES = tuple(CONFIG["severities"])
HORIZONS = tuple(CONFIG["mission_horizons"])
SEEDS = tuple(SEED_MANIFEST["seeds"])
CLAIM_SCOPE = "SYNTHETIC_WHITE_BOX_ENGINEERING_ORACLE_NOT_VLA"
SCHEMA_VERSION = 3
RAW_FILES = frozenset({
    "config.json", "episodes.csv", "freeze.json", "raw-manifest.json",
    "seeds.json", "starts.jsonl", "steps.jsonl",
})
DERIVED_FILES = frozenset({
    "RESULTS.md", "annotations.json", "cell-summary.csv", "contrasts.csv",
    "derived-manifest.json", "heterogeneity.csv", "plot-style.json",
    "storage-trigger-summary.csv", "storage-trigger.png", "storage-trigger.svg",
    "trigger-profile.csv",
})
SOURCE_PATHS = (
    "experiments/__init__.py",
    "experiments/10_storage_trigger/__init__.py",
    "experiments/10_storage_trigger/src/__init__.py",
    "experiments/10_storage_trigger/src/factorial_v2r2.py",
    "experiments/10_storage_trigger/src/factorial_v2r2_scorer.py",
    "experiments/10_storage_trigger/src/factorial_v2.py",
    "experiments/10_storage_trigger/src/factorial_v2_scorer.py",
    "experiments/10_storage_trigger/src/factorial.py",
    "experiments/04_memory/__init__.py",
    "experiments/04_memory/src/__init__.py",
    "experiments/04_memory/src/unfixed_ablation.py",
    "experiments/10_storage_trigger/configs/storage-trigger-factorial-v2r2.json",
    "experiments/10_storage_trigger/configs/seeds-v2r2.json",
    "experiments/10_storage_trigger/configs/storage-trigger-factorial-v2.json",
    "experiments/10_storage_trigger/configs/seeds-v2.json",
    "experiments/10_storage_trigger/configs/storage-trigger-factorial-v1.json",
    "experiments/10_storage_trigger/configs/seeds-v1.json",
)


class FactorialV2R2Error(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_bytes(row) for row in rows)


def csv_bytes(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    writer.writerows({field: row[field] for field in fields} for row in rows)
    return output.getvalue().encode("ascii")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _head() -> str:
    return subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=REPO, text=True).strip()


def _episode_id(storage: str, trigger: str, family: str, severity: str, horizon: int, seed: int) -> str:
    return f"{storage}__{trigger}__{family}__{severity}__H{horizon}__S{seed}"


def frozen_matrix() -> tuple[dict[str, Any], ...]:
    return tuple({
        "claim_scope": CLAIM_SCOPE,
        "disturbance_family": family,
        "episode_id": _episode_id(storage, trigger, family, severity, horizon, seed),
        "horizon": horizon,
        "planner_id": PLANNER_ID,
        "seed": seed,
        "severity": severity,
        "storage_variant": storage,
        "trigger_variant": trigger,
    } for storage, trigger, family, severity, horizon, seed in itertools.product(
        STORAGE_VARIANTS, TRIGGER_VARIANTS, DISTURBANCE_FAMILIES, SEVERITIES, HORIZONS, SEEDS,
    ))


def fixture_matrix() -> tuple[dict[str, Any], ...]:
    rows = []
    for storage, trigger, family, horizon, seed in itertools.product(
        ("NO_MEMORY", "FIXED_SNAPSHOT", "LIVE_EPISODIC"),
        ("NO_REPLAN", "PERIODIC_ONLY", "HYBRID"),
        ("POSE_SHIFT", "CONTROL_FAILURE"), (4, 8), tuple(CONFIG["calibration_seeds"]),
    ):
        rows.append({
            "claim_scope": CLAIM_SCOPE, "disturbance_family": family,
            "episode_id": _episode_id(storage, trigger, family, "HIGH", horizon, seed),
            "horizon": horizon, "planner_id": PLANNER_ID, "seed": seed, "severity": "HIGH",
            "storage_variant": storage, "trigger_variant": trigger,
        })
    return tuple(rows)


def run_episode(cell: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    episode, start, ticks = v2.run_episode(cell)
    try:
        independently_scored = score_episode(start, ticks, CONFIG)
    except LedgerScoreError as exc:
        raise FactorialV2R2Error(str(exc)) from exc
    if episode != independently_scored:
        raise FactorialV2R2Error("executor/independent scorer disagreement")
    return independently_scored, start, ticks


def source_closure() -> list[dict[str, Any]]:
    return [{
        "bytes": (REPO / path).stat().st_size,
        "path": path,
        "sha256": _sha((REPO / path).read_bytes()),
    } for path in SOURCE_PATHS]


def _git_blob(commit: str, path: str) -> bytes:
    try:
        return subprocess.check_output(("git", "show", f"{commit}:{path}"), cwd=REPO)
    except subprocess.CalledProcessError as exc:
        raise FactorialV2R2Error("implementation source commit closure mismatch") from exc


def _identities(cells: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(str(row["episode_id"]) for row in cells)


def _freeze(cells: Sequence[Mapping[str, Any]], commit: str, *, fixture: bool) -> dict[str, Any]:
    closure = source_closure()
    ids = _identities(cells)
    return {
        "claim_scope": CLAIM_SCOPE,
        "configuration_sha256": _sha(CONFIG_PATH.read_bytes()),
        "environment": {
            "numpy": np.__version__, "platform": platform.platform(), "python": platform.python_version(),
        },
        "episode_ids": ids,
        "fixture": fixture,
        "implementation_git_sha": commit,
        "matrix_identity_sha256": _sha(canonical_bytes(ids)),
        "planner_id": PLANNER_ID,
        "schema_version": SCHEMA_VERSION,
        "seed_manifest_sha256": _sha(SEEDS_PATH.read_bytes()),
        "source_closure": closure,
        "source_closure_sha256": _sha(canonical_bytes(closure)),
        "study_id": CONFIG["study_id"],
    }


def _validate_freeze(freeze: Mapping[str, Any], *, allow_fixture: bool) -> None:
    if type(freeze.get("fixture")) is not bool:
        raise FactorialV2R2Error("freeze identity fixture flag is not canonical")
    fixture = bool(freeze["fixture"])
    if fixture and not allow_fixture:
        raise FactorialV2R2Error("fixture evidence is not an authorized outcome")
    cells = fixture_matrix() if fixture else frozen_matrix()
    commit = str(freeze.get("implementation_git_sha", ""))
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise FactorialV2R2Error("freeze implementation identity is invalid")
    expected = _freeze(cells, commit, fixture=fixture)
    if dict(freeze) != expected:
        raise FactorialV2R2Error("freeze canonical identity mismatch")
    if commit != _head():
        try:
            subprocess.check_call(("git", "merge-base", "--is-ancestor", commit, "HEAD"), cwd=REPO)
        except subprocess.CalledProcessError as exc:
            raise FactorialV2R2Error("freeze implementation commit is not an ancestor") from exc
    if not fixture:
        for member in source_closure():
            if _sha(_git_blob(commit, str(member["path"]))) != member["sha256"]:
                raise FactorialV2R2Error("implementation source commit closure mismatch")


def _inventory(root: Path, *, exclude: Sequence[str] = ()) -> list[dict[str, Any]]:
    excluded = set(exclude)
    rows = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        if path.is_symlink():
            raise FactorialV2R2Error("symlink is forbidden by evidence schema")
        if path.is_file():
            payload = path.read_bytes()
            rows.append({"bytes": len(payload), "path": relative, "sha256": _sha(payload)})
        elif not path.is_dir():
            raise FactorialV2R2Error("non-regular evidence member")
    return rows


def _exact_files(root: Path, allowed: frozenset[str], *, label: str) -> None:
    if root.is_symlink() or not root.is_dir():
        raise FactorialV2R2Error(f"{label} must be a regular directory")
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise FactorialV2R2Error(f"{label} symlink is forbidden")
        if path.is_dir():
            raise FactorialV2R2Error(f"{label} nested directory is outside allowed schema")
        if not path.is_file():
            raise FactorialV2R2Error(f"{label} non-regular member")
        actual.add(path.relative_to(root).as_posix())
    if actual != set(allowed):
        raise FactorialV2R2Error(f"{label} allowed schema mismatch")


def _validate_inventory(root: Path, manifest: Mapping[str, Any]) -> None:
    members = manifest.get("members")
    if not isinstance(members, list):
        raise FactorialV2R2Error("raw inventory is invalid")
    paths = [str(row.get("path")) for row in members]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise FactorialV2R2Error("raw inventory path order/duplicates invalid")
    if set(paths) != set(RAW_FILES - {"raw-manifest.json"}):
        raise FactorialV2R2Error("raw declared members exceed exact allowed schema")
    if _inventory(root, exclude=("raw-manifest.json",)) != members:
        raise FactorialV2R2Error("raw recursive inventory mismatch")


def validate_retired_invalid_root(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise FactorialV2R2Error("retired-invalid root must be a regular directory")
    children = {path.name: path for path in root.iterdir()}
    if set(children) != {"INVALID_ATTEMPT.json", "raw", "derived"}:
        raise FactorialV2R2Error("retired-invalid exact schema mismatch")
    if any(path.is_symlink() for path in children.values()):
        raise FactorialV2R2Error("retired-invalid symlink is forbidden")
    if not children["INVALID_ATTEMPT.json"].is_file():
        raise FactorialV2R2Error("retired-invalid disposition must be regular")
    for name in ("raw", "derived"):
        if not children[name].is_dir() or any(children[name].iterdir()):
            raise FactorialV2R2Error("retired-invalid empty directory schema mismatch")
    payload = (root / "INVALID_ATTEMPT.json").read_bytes()
    record = json.loads(payload)
    if canonical_bytes(record) != payload or record.get("scientific_disposition") != "INVALID_ATTEMPT_NO_RESULT":
        raise FactorialV2R2Error("retired-invalid schema closure mismatch")


def _read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="ascii"))))


def _validate_raw(raw: Path, *, allow_fixture: bool) -> list[dict[str, Any]]:
    _exact_files(raw, RAW_FILES, label="raw")
    manifest_payload = (raw / "raw-manifest.json").read_bytes()
    manifest = json.loads(manifest_payload)
    if canonical_bytes(manifest) != manifest_payload or manifest.get("schema_version") != SCHEMA_VERSION:
        raise FactorialV2R2Error("raw manifest schema is not canonical")
    _validate_inventory(raw, manifest)
    if (raw / "config.json").read_bytes() != CONFIG_PATH.read_bytes():
        raise FactorialV2R2Error("frozen config mismatch")
    if (raw / "seeds.json").read_bytes() != SEEDS_PATH.read_bytes():
        raise FactorialV2R2Error("frozen seeds mismatch")
    freeze_payload = (raw / "freeze.json").read_bytes()
    freeze = json.loads(freeze_payload)
    if canonical_bytes(freeze) != freeze_payload:
        raise FactorialV2R2Error("freeze is not canonical")
    _validate_freeze(freeze, allow_fixture=allow_fixture)
    episodes = _read_csv(raw / "episodes.csv")
    starts = [json.loads(line) for line in (raw / "starts.jsonl").read_text(encoding="ascii").splitlines()]
    ticks = [json.loads(line) for line in (raw / "steps.jsonl").read_text(encoding="ascii").splitlines()]
    expected_cells = fixture_matrix() if freeze["fixture"] else frozen_matrix()
    expected_ids = _identities(expected_cells)
    if [row["episode_id"] for row in episodes] != expected_ids:
        raise FactorialV2R2Error("episode matrix identity/order mismatch")
    if [row["cell"]["episode_id"] for row in starts] != expected_ids:
        raise FactorialV2R2Error("start matrix identity/order mismatch")
    expected_by_id = {row["episode_id"]: row for row in expected_cells}
    starts_by_id = {row["cell"]["episode_id"]: row for row in starts}
    if len(starts_by_id) != len(starts):
        raise FactorialV2R2Error("duplicate start identity")
    tick_ids = [str(row.get("episode_id")) for row in ticks]
    if tick_ids != sorted(tick_ids):
        raise FactorialV2R2Error("raw ledger chronology/order mismatch")
    grouped: dict[str, list[dict[str, Any]]] = {episode_id: [] for episode_id in expected_ids}
    for row in ticks:
        episode_id = str(row.get("episode_id"))
        if episode_id not in grouped:
            raise FactorialV2R2Error("tick matrix identity mismatch")
        grouped[episode_id].append(row)
    scored = []
    for episode, episode_id in zip(episodes, expected_ids, strict=True):
        cell = expected_by_id[episode_id]
        start = starts_by_id[episode_id]
        if start.get("cell") != cell:
            raise FactorialV2R2Error("canonical start cell identity mismatch")
        expected_initial = v2._legacy().initial_task(int(cell["seed"]))
        if start.get("initial_world") != {
            "entities": expected_initial["entities"], "restrictions": expected_initial["restrictions"],
        }:
            raise FactorialV2R2Error("initial generator identity mismatch")
        try:
            score = score_episode(start, grouped[episode_id], CONFIG)
        except LedgerScoreError as exc:
            raise FactorialV2R2Error(str(exc)) from exc
        for field in v2.EPISODE_FIELDS:
            expected = str(score[field])
            actual = episode[field]
            if field not in {
                "episode_id", "storage_variant", "trigger_variant", "disturbance_family",
                "severity", "planner_id", "claim_scope",
            }:
                equal = float(actual) == float(expected)
            else:
                equal = actual == expected
            if not equal:
                raise FactorialV2R2Error(f"independent score mismatch for {field}")
        scored.append(score)
    if manifest.get("episode_count") != len(scored) or manifest.get("step_count") != len(ticks):
        raise FactorialV2R2Error("raw manifest count mismatch")
    return scored


def _derived(rows: Sequence[Mapping[str, Any]]) -> dict[str, bytes]:
    files = v2._derive(rows)
    files["RESULTS.md"] = (
        "# Experiment 10 Storage x Trigger Factorial V2R2\n\n"
        "Status: SYNTHETIC_WHITE_BOX_ENGINEERING_RESULT\n\n"
        f"Independently reconstructed {len(rows)} deterministic episodes. This strict synthetic-white-box result "
        "is not VLA, physical-robot, or population-generalization evidence.\n"
    ).encode("ascii")
    return files


def _write_derived(destination: Path, scored: Sequence[Mapping[str, Any]]) -> None:
    destination.mkdir()
    for name, payload in _derived(scored).items():
        (destination / name).write_bytes(payload)
    manifest = {"members": _inventory(destination), "schema_version": SCHEMA_VERSION}
    (destination / "derived-manifest.json").write_bytes(canonical_bytes(manifest))


def validate_result_root(root: Path, *, allow_fixture: bool = False) -> None:
    if root.is_symlink() or not root.is_dir():
        raise FactorialV2R2Error("result root must be a regular directory")
    children = {path.name for path in root.iterdir()}
    if children != {"raw", "derived"} or any(path.is_symlink() for path in root.iterdir()):
        raise FactorialV2R2Error("result root exact schema mismatch")
    _validate_raw(root / "raw", allow_fixture=allow_fixture)
    _exact_files(root / "derived", DERIVED_FILES, label="derived")
    replay_manifest = json.loads((root / "derived/derived-manifest.json").read_text(encoding="ascii"))
    if replay_manifest.get("schema_version") != SCHEMA_VERSION:
        raise FactorialV2R2Error("derived manifest schema mismatch")
    if _inventory(root / "derived", exclude=("derived-manifest.json",)) != replay_manifest.get("members"):
        raise FactorialV2R2Error("derived inventory mismatch")


def _publish(output: Path, cells: Sequence[Mapping[str, Any]], *, implementation_git_sha: str, fixture: bool) -> None:
    if output.exists():
        raise FactorialV2R2Error("result root must be absent")
    if implementation_git_sha != _head():
        raise FactorialV2R2Error("implementation commit must equal current HEAD")
    if not fixture:
        for member in source_closure():
            if _sha(_git_blob(implementation_git_sha, str(member["path"]))) != member["sha256"]:
                raise FactorialV2R2Error("implementation source is not committed")
    raw = output / "raw"
    raw.mkdir(parents=True)
    episodes, starts, ticks = [], [], []
    for cell in cells:
        episode, start, episode_ticks = run_episode(cell)
        episodes.append(episode)
        starts.append(start)
        ticks.extend(episode_ticks)
    episodes.sort(key=lambda row: row["episode_id"])
    starts.sort(key=lambda row: row["cell"]["episode_id"])
    ticks.sort(key=lambda row: (row["episode_id"], row["tick"]))
    (raw / "config.json").write_bytes(CONFIG_PATH.read_bytes())
    (raw / "episodes.csv").write_bytes(csv_bytes(episodes, v2.EPISODE_FIELDS))
    (raw / "freeze.json").write_bytes(canonical_bytes(_freeze(cells, implementation_git_sha, fixture=fixture)))
    (raw / "seeds.json").write_bytes(SEEDS_PATH.read_bytes())
    (raw / "starts.jsonl").write_bytes(jsonl_bytes(starts))
    (raw / "steps.jsonl").write_bytes(jsonl_bytes(ticks))
    (raw / "raw-manifest.json").write_bytes(canonical_bytes({
        "episode_count": len(episodes), "members": _inventory(raw),
        "schema_version": SCHEMA_VERSION, "step_count": len(ticks),
    }))
    scored = _validate_raw(raw, allow_fixture=fixture)
    _write_derived(output / "derived", scored)
    validate_result_root(output, allow_fixture=fixture)


def run_fixture(output: Path, *, implementation_git_sha: str) -> None:
    _publish(output, fixture_matrix(), implementation_git_sha=implementation_git_sha, fixture=True)


def run_frozen(output: Path, *, implementation_git_sha: str) -> None:
    _publish(output, frozen_matrix(), implementation_git_sha=implementation_git_sha, fixture=False)


def _reconstruct(raw: Path, destination: Path, *, allow_fixture: bool) -> None:
    if destination.exists():
        raise FactorialV2R2Error("reconstruction destination must be absent")
    scored = _validate_raw(raw, allow_fixture=allow_fixture)
    _write_derived(destination, scored)


def reconstruct(raw: Path, destination: Path) -> None:
    _reconstruct(raw, destination, allow_fixture=False)


def reconstruct_fixture(raw: Path, destination: Path) -> None:
    _reconstruct(raw, destination, allow_fixture=True)


__all__ = [
    "FactorialV2R2Error", "RETIRED_INVALID_ROOT", "canonical_bytes", "csv_bytes",
    "fixture_matrix", "frozen_matrix", "jsonl_bytes", "reconstruct", "reconstruct_fixture",
    "run_episode", "run_fixture", "run_frozen", "source_closure", "validate_result_root",
    "validate_retired_invalid_root",
]
