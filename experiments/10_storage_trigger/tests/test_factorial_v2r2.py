from __future__ import annotations

import csv
import hashlib
import importlib
import json
from pathlib import Path
import subprocess

import pytest


def _module():
    return importlib.import_module("experiments.10_storage_trigger.src.factorial_v2r2")


def _head() -> str:
    return subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()


def _rehash(module, raw: Path, name: str) -> None:
    manifest = json.loads((raw / "raw-manifest.json").read_text(encoding="ascii"))
    payload = (raw / name).read_bytes()
    member = next(row for row in manifest["members"] if row["path"] == name)
    member.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    (raw / "raw-manifest.json").write_bytes(module.canonical_bytes(manifest))


def _fixture(tmp_path: Path):
    module = _module()
    output = tmp_path / "fixture"
    module.run_fixture(output, implementation_git_sha=_head())
    return module, output


def test_v2r2_exact_matrix_identity_and_new_seed_namespace() -> None:
    module = _module()
    rows = module.frozen_matrix()
    assert len(rows) == len({row["episode_id"] for row in rows}) == 12_000
    assert {row["seed"] for row in rows} == set(range(20265301, 20265321))
    assert {row["planner_id"] for row in rows} == {"ORACLE_TYPED_SEMANTIC_V2"}
    assert {row["claim_scope"] for row in rows} == {"SYNTHETIC_WHITE_BOX_ENGINEERING_ORACLE_NOT_VLA"}


@pytest.mark.parametrize("mutation", ["reverse", "duplicate", "gap", "early", "extra"])
def test_v2r2_rejects_noncanonical_tick_domain_and_raw_order(tmp_path: Path, mutation: str) -> None:
    module, output = _fixture(tmp_path)
    raw = output / "raw"
    rows = [json.loads(line) for line in (raw / "steps.jsonl").read_text(encoding="ascii").splitlines()]
    victim_id = rows[0]["episode_id"]
    indexes = [index for index, row in enumerate(rows) if row["episode_id"] == victim_id]
    victim = [rows[index] for index in indexes]
    if mutation == "reverse":
        victim[0], victim[1] = victim[1], victim[0]
    elif mutation == "duplicate":
        victim[1] = victim[0]
    elif mutation == "gap":
        victim[1]["tick"] += 1
    elif mutation == "early":
        victim = victim[:-1]
    else:
        extra = json.loads(json.dumps(victim[-1]))
        extra["tick"] += 1
        victim.append(extra)
    rows[indexes[0]:indexes[-1] + 1] = victim
    (raw / "steps.jsonl").write_bytes(module.jsonl_bytes(rows))
    _rehash(module, raw, "steps.jsonl")
    with pytest.raises(module.FactorialV2R2Error, match="chronology|tick domain|terminal|count"):
        module.reconstruct_fixture(raw, tmp_path / "replay")


def test_v2r2_freeze_authenticates_all_canonical_identity_fields(tmp_path: Path) -> None:
    fields = {
        "study_id": "FORGED_STUDY",
        "schema_version": 99,
        "claim_scope": "FORGED_SCOPE",
        "planner_id": "FORGED_PLANNER",
        "fixture": "yes",
        "configuration_sha256": "0" * 64,
        "seed_manifest_sha256": "0" * 64,
        "matrix_identity_sha256": "0" * 64,
        "source_closure_sha256": "0" * 64,
    }
    for index, (field, value) in enumerate(fields.items()):
        module = _module()
        output = tmp_path / f"fixture-{index}"
        module.run_fixture(output, implementation_git_sha=_head())
        raw = output / "raw"
        freeze = json.loads((raw / "freeze.json").read_text(encoding="ascii"))
        freeze[field] = value
        (raw / "freeze.json").write_bytes(module.canonical_bytes(freeze))
        _rehash(module, raw, "freeze.json")
        with pytest.raises(module.FactorialV2R2Error, match="freeze|identity|schema"):
            module.reconstruct_fixture(raw, tmp_path / f"replay-{index}")


def test_v2r2_closure_includes_transitive_executor_inputs() -> None:
    module = _module()
    paths = {row["path"] for row in module.source_closure()}
    assert {
        "experiments/10_storage_trigger/src/factorial_v2r2.py",
        "experiments/10_storage_trigger/src/factorial_v2.py",
        "experiments/10_storage_trigger/src/factorial_v2_scorer.py",
        "experiments/10_storage_trigger/src/factorial.py",
        "experiments/04_memory/src/unfixed_ablation.py",
        "experiments/10_storage_trigger/configs/storage-trigger-factorial-v2.json",
        "experiments/10_storage_trigger/configs/seeds-v2.json",
        "experiments/10_storage_trigger/configs/storage-trigger-factorial-v1.json",
        "experiments/10_storage_trigger/configs/seeds-v1.json",
        "experiments/10_storage_trigger/configs/storage-trigger-factorial-v2r2.json",
        "experiments/10_storage_trigger/configs/seeds-v2r2.json",
    } <= paths


@pytest.mark.parametrize("relative", ["declared.txt", "nested/extra.txt"])
def test_v2r2_exact_root_and_raw_schema_reject_extras(tmp_path: Path, relative: str) -> None:
    module, output = _fixture(tmp_path)
    extra = output / relative
    extra.parent.mkdir(exist_ok=True)
    extra.write_text("extra\n", encoding="ascii")
    with pytest.raises(module.FactorialV2R2Error, match="result root|schema|inventory"):
        module.validate_result_root(output, allow_fixture=True)


def test_v2r2_raw_schema_rejects_declared_extra_and_symlink(tmp_path: Path) -> None:
    module, output = _fixture(tmp_path)
    raw = output / "raw"
    extra = raw / "extra.txt"
    extra.write_text("extra\n", encoding="ascii")
    manifest = json.loads((raw / "raw-manifest.json").read_text(encoding="ascii"))
    payload = extra.read_bytes()
    manifest["members"].append({"bytes": len(payload), "path": "extra.txt", "sha256": hashlib.sha256(payload).hexdigest()})
    manifest["members"].sort(key=lambda row: row["path"])
    (raw / "raw-manifest.json").write_bytes(module.canonical_bytes(manifest))
    with pytest.raises(module.FactorialV2R2Error, match="schema|allowed"):
        module.reconstruct_fixture(raw, tmp_path / "declared")

    output2 = tmp_path / "fixture-link"
    module.run_fixture(output2, implementation_git_sha=_head())
    (output2 / "raw/config-link.json").symlink_to(output2 / "raw/config.json")
    with pytest.raises(module.FactorialV2R2Error, match="symlink|schema|inventory"):
        module.reconstruct_fixture(output2 / "raw", tmp_path / "linked")


def test_v2r2_retired_invalid_root_has_exact_schema() -> None:
    module = _module()
    retired = module.RETIRED_INVALID_ROOT
    module.validate_retired_invalid_root(retired)
    assert {path.name for path in retired.iterdir()} == {"INVALID_ATTEMPT.json", "raw", "derived"}
    assert not any((retired / "raw").iterdir())
    assert not any((retired / "derived").iterdir())


def test_v2r2_reconstruction_is_byte_exact(tmp_path: Path) -> None:
    module, output = _fixture(tmp_path)
    replay = tmp_path / "replay"
    module.reconstruct_fixture(output / "raw", replay)
    assert {path.name: path.read_bytes() for path in replay.iterdir()} == {
        path.name: path.read_bytes() for path in (output / "derived").iterdir()
    }
    episodes = list(csv.DictReader((output / "raw/episodes.csv").read_text(encoding="ascii").splitlines()))
    assert episodes and len({row["episode_id"] for row in episodes}) == len(episodes)
