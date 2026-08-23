from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess

import pytest


run = importlib.import_module("experiments.01_policy_control.run")
artifacts = importlib.import_module("experiments.01_policy_control.src.artifacts")
ROOT = Path(__file__).resolve().parents[3]


def _args(tmp_path, *extra):
    config = tmp_path / "config.yaml"
    gate = tmp_path / "gate.yaml"
    config.write_text("x\n", encoding="utf-8")
    gate.write_text("x\n", encoding="utf-8")
    return [
        "--config", str(config), "--p3-gate", str(gate), "--phase", "pilot",
        "--output-dir", str(tmp_path / "absent-output"), "--headless", *extra,
    ]


def _safe(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("PHYSICAL_DEPLOYMENT_ALLOWED", raising=False)
    monkeypatch.delenv("REFLECT_REMOTE_ENABLED", raising=False)
    monkeypatch.setattr(run, "load_p3_gate", lambda _path: object())
    monkeypatch.setattr(run, "require_p3_gate", lambda _root, _gate: None)


def test_dry_run_is_canonical_and_creates_no_output(monkeypatch, tmp_path, capsys) -> None:
    _safe(monkeypatch, tmp_path)
    args = _args(tmp_path, "--stage", "base", "--prepare-manifest", str(tmp_path / "manifest.json"), "--dry-run")
    assert run.main(args) == 0
    output = capsys.readouterr().out
    assert output.endswith("\n")
    assert output == json.dumps(json.loads(output), sort_keys=True, separators=(",", ":")) + "\n"
    assert '"headless":true' in output and '"stage":"base"' in output
    assert not (tmp_path / "absent-output").exists() and not (tmp_path / "manifest.json").exists()


def test_cli_rejects_nonheadless_conflicting_modes_and_escape(monkeypatch, tmp_path) -> None:
    _safe(monkeypatch, tmp_path)
    assert run.main(_args(tmp_path, "--list-shards", "--preflight")) == 1
    not_headless = _args(tmp_path)
    not_headless.remove("--headless")
    assert run.main(not_headless) == 2
    escaped = _args(tmp_path)
    escaped[escaped.index("--output-dir") + 1] = "/private/tmp/escape"
    assert run.main(escaped) == 2


def test_make_exp01_guard_exits_before_python() -> None:
    environment = dict(os.environ)
    environment.pop("SHARD", None)
    completed = subprocess.run(["make", "exp01"], cwd=ROOT, env=environment, capture_output=True, text=True)
    assert completed.returncode != 0
    assert "SHARD is required" in completed.stderr
    assert "python -m experiments.01_policy_control.run" not in completed.stdout


def test_list_shards_filters_declared_episode_count_and_is_p1_first(
    monkeypatch, tmp_path, capsys,
) -> None:
    _safe(monkeypatch, tmp_path)
    h64 = "a" * 64
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(artifacts, "iter_manifest", lambda _path: iter((
        artifacts.ShardSpec("P2:base:1", "P2", h64, 1, ("a", "b"), 2, ("P2-a-1", "P2-b-1")),
        artifacts.ShardSpec("P1:base:1", "P1", h64, 1, ("a",), 1, ("P1-a-1",)),
    )))
    assert run.main(_args(
        tmp_path, "--manifest", str(manifest_path), "--list-shards", "--max-episodes", "1",
    )) == 0
    assert capsys.readouterr().out == "P1:base:1\n"


@pytest.mark.parametrize("result,expected", (
    ("published", 0),
    ("validated-and-skipped", 0),
    ("declared-invalid", 0),
    ("resource-exhausted", 3),
))
def test_shard_execution_maps_closed_supervisor_result_to_exit_status(
    monkeypatch, tmp_path, result, expected,
) -> None:
    _safe(monkeypatch, tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    observed = {}
    bucket = tmp_path / "resource-bucket"
    predecessor = artifacts.ResourceArtifactPath(
        tmp_path / "prior.json", tmp_path / "prior-results", "pilot", 1,
    )

    def supervise(*positional, **kwargs):
        observed["output_dir"] = positional[2]
        observed.update(kwargs)
        return result

    monkeypatch.setattr(
        artifacts, "resource_execution_context",
        lambda *_args: (bucket, (predecessor,), None),
    )
    monkeypatch.setattr(artifacts, "run_supervised_shard", supervise)
    assert run.main(_args(
        tmp_path, "--manifest", str(manifest), "--shard-id", "P1:base:000",
        "--max-episodes", "3",
    )) == expected
    assert observed == {
        "output_dir": bucket,
        "repo_root": tmp_path,
        "prior_artifacts": (predecessor,),
        "confirmation_wave": None,
    }


def test_shard_execution_maps_unsafe_or_drift_failure_to_exit_two(
    monkeypatch, tmp_path,
) -> None:
    _safe(monkeypatch, tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")

    def unsafe(*_args, **_kwargs):
        raise artifacts.ImplementationDriftError("drift")

    monkeypatch.setattr(
        artifacts, "resource_execution_context",
        lambda *_args: (tmp_path / "bucket", (), None),
    )
    monkeypatch.setattr(artifacts, "run_supervised_shard", unsafe)
    assert run.main(_args(
        tmp_path, "--manifest", str(manifest), "--shard-id", "P1:base:000",
        "--max-episodes", "3",
    )) == 2


@pytest.mark.parametrize("mode,status", (
    ("--shard-disposition", "CONTINUE"),
    ("--stage-disposition", "ADVANCE"),
))
def test_pilot_disposition_commands_print_only_closed_status(
    monkeypatch, tmp_path, capsys, mode, status,
) -> None:
    _safe(monkeypatch, tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        artifacts, "resource_execution_context",
        lambda *_args: (tmp_path / "bucket", (), None),
    )
    monkeypatch.setattr(
        artifacts, "publish_shard_disposition", lambda *_args, **_kwargs: status,
    )
    monkeypatch.setattr(
        artifacts, "publish_stage_disposition", lambda *_args, **_kwargs: status,
    )
    extra = (mode, "P1:base:000") if mode == "--shard-disposition" else (mode,)
    assert run.main(_args(tmp_path, "--manifest", str(manifest), *extra)) == 0
    assert capsys.readouterr().out == f"{status}\n"
