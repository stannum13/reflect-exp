from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


artifacts = importlib.import_module("experiments.01_policy_control.src.artifacts")


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_completion_marker_is_last(completion: Path) -> None:
    marker_time = completion.stat().st_mtime_ns
    assert marker_time >= max(
        path.stat().st_mtime_ns for path in completion.parent.rglob("*") if path.is_file()
    )


@pytest.fixture
def base_pilot(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    repo = Path(__file__).resolve().parents[3]
    config = Path(__file__).parents[1] / "configs/base.yaml"
    gate = tmp_path / "p3-gate.yaml"
    gate.write_text("schema_version: 1\n", encoding="utf-8")
    implementation_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
    ).strip()
    protocol = tmp_path / "protocol"
    revision = protocol / "revision-manifest.json"
    manifest = protocol / "base-manifest.json"
    artifacts.prepare_manifest(
        "revision", None, revision, config, gate,
        implementation_sha=implementation_sha,
    )
    artifacts.prepare_manifest(
        "base", revision, manifest, config, gate,
        implementation_sha=implementation_sha,
    )
    return manifest, config, gate, "P1:base:000"


def _supervise(
    base_pilot: tuple[Path, Path, Path, str], output: Path, **overrides: object,
) -> str:
    manifest, config, gate, shard_id = base_pilot
    return artifacts.run_supervised_shard(
        manifest, shard_id, output, config, gate, 3,
        repo_root=Path(__file__).resolve().parents[3], **overrides,
    )


def test_private_worker_rejects_missing_or_wrong_pipe_capability_before_inputs(
    tmp_path: Path,
) -> None:
    with pytest.raises(artifacts.ArtifactError, match="capability"):
        artifacts.run_worker_shard(
            tmp_path / "missing-manifest.json", "P1:base:000", tmp_path / "stage",
            tmp_path / "missing-config.yaml", -1, "0" * 64,
        )

    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b"parent-only-capability")
        os.close(write_fd)
        write_fd = -1
        with pytest.raises(artifacts.ArtifactError, match="capability"):
            artifacts.run_worker_shard(
                tmp_path / "missing-manifest.json", "P1:base:000", tmp_path / "stage",
                tmp_path / "missing-config.yaml", read_fd, "f" * 64,
            )
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)
    assert not (tmp_path / "stage").exists()


def test_supervisor_success_bounds_child_output_and_publishes_marker_last(
    base_pilot: tuple[Path, Path, Path, str], tmp_path: Path,
) -> None:
    manifest, config, _, shard_id = base_pilot
    script = (
        "import importlib,sys;"
        "a=importlib.import_module('experiments.01_policy_control.src.artifacts');"
        "print('x'*200000);"
        "raise SystemExit(a.run_worker_shard("
        f"__import__('pathlib').Path({str(manifest)!r}),{shard_id!r},"
        "__import__('pathlib').Path(sys.argv[3]),"
        f"__import__('pathlib').Path({str(config)!r}),int(sys.argv[1]),sys.argv[2]))"
    )
    output = tmp_path / "results"
    assert _supervise(
        base_pilot, output,
        worker_argv=(sys.executable, "-c", script, "{capability_fd}",
                     "{capability_sha256}", "{stage_dir}"),
    ) == "published"

    completion_paths = tuple(output.rglob("completion.json"))
    assert len(completion_paths) == 1
    completion = _json(completion_paths[0])
    shard_dir = completion_paths[0].parent
    ledger = shard_dir / "resource-ledger.jsonl"
    assert completion["state"] == "COMPLETE"
    assert completion["resource_ledger_sha256"] == hashlib.sha256(ledger.read_bytes()).hexdigest()
    assert completion["completed_output_identities"] == completion["expected_output_identities"]
    assert all(path.stat().st_size <= 2 * 65_536 for path in shard_dir.rglob("*output*") if path.is_file())
    _assert_completion_marker_is_last(completion_paths[0])


def test_supervisor_timeout_is_declared_invalid_with_bounded_readable_output(
    base_pilot: tuple[Path, Path, Path, str], tmp_path: Path,
) -> None:
    script = "import sys,time;sys.stdout.write('y'*200000);sys.stdout.flush();time.sleep(60)"
    output = tmp_path / "timeout-results"
    assert _supervise(
        base_pilot, output, deadline_s=0.05, term_grace_s=0.05,
        worker_argv=(sys.executable, "-c", script),
    ) == "declared-invalid"

    completion_paths = tuple(output.rglob("completion.json"))
    assert len(completion_paths) == 1
    completion = _json(completion_paths[0])
    shard_dir = completion_paths[0].parent
    failure = (shard_dir / "failure-disposition.jsonl").read_text(encoding="utf-8")
    assert completion["state"] == "DECLARED_INVALID"
    assert failure.count("\n") == 3
    assert all(json.loads(row)["reason"] == "PROCESS_TIMEOUT" for row in failure.splitlines())
    assert all(path.stat().st_size <= 2 * 65_536 for path in shard_dir.rglob("*output*") if path.is_file())
    _assert_completion_marker_is_last(completion_paths[0])


def test_supervisor_refuses_before_spawn_and_publishes_resource_terminal(
    base_pilot: tuple[Path, Path, Path, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "refused-results"
    sentinel = tmp_path / "worker-ran"
    monkeypatch.setattr(
        artifacts.shutil, "disk_usage",
        lambda _path: SimpleNamespace(total=1, used=1, free=0),
    )
    assert _supervise(
        base_pilot, output,
        worker_argv=(sys.executable, "-c", f"open({str(sentinel)!r},'w').write('ran')"),
    ) == "resource-exhausted"
    assert not sentinel.exists()
    terminal = _json(output / "resource-terminal.json")
    assert terminal["source"] == "PREFLIGHT"
    assert terminal["lifecycle_state"] == "STOPPED"
    assert tuple(output.glob("P*")) == ()


def test_supervisor_reproduces_existing_preflight_before_spawn(
    base_pilot: tuple[Path, Path, Path, str], tmp_path: Path,
) -> None:
    manifest, _, _, _ = base_pilot
    protocol = artifacts.load_protocol_manifest(manifest)
    output = tmp_path / "stale-preflight-results"
    output.mkdir()
    disposition = artifacts.preflight_resources(
        "pilot", 0, 0, 0, 20 * 1024 * 1024 * 1024, 0, 0,
        rollout_count=sum(row["episode_count"] for row in protocol["shards"]),
        revision=1,
    )
    stale = json.loads(disposition.to_json())
    stale["revision"] = 2
    (output / "preflight.json").write_text(
        json.dumps(stale, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    sentinel = tmp_path / "stale-preflight-worker-ran"
    with pytest.raises(artifacts.ArtifactError, match="preflight.*reproduce|revision"):
        _supervise(
            base_pilot, output,
            worker_argv=(sys.executable, "-c", f"open({str(sentinel)!r},'w').write('ran')"),
        )
    assert not sentinel.exists()


def test_worker_exit_three_requires_exact_reproducible_refusal_receipt(
    base_pilot: tuple[Path, Path, Path, str], tmp_path: Path,
) -> None:
    output = tmp_path / "missing-refusal-receipt"
    with pytest.raises(artifacts.ArtifactError, match="refusal receipt"):
        _supervise(
            base_pilot, output,
            worker_argv=(sys.executable, "-c", "raise SystemExit(3)"),
        )
    assert tuple(output.rglob("completion.json")) == ()

    exact_output = tmp_path / "exact-refusal-receipt"
    script = (
        "import json,pathlib,sys;"
        "p=pathlib.Path(sys.argv[1]);"
        "r={'schema_version':1,'study_id':'reflect-lite-policy-control',"
        "'phase':'pilot','revision':1,'shard_id':'P1:base:000',"
        "'retained_bytes':0,'temp_bytes':0,'quarantine_bytes':0,'free_bytes':0,"
        "'wall_seconds':0,'cpu_seconds':0,'reserved_bytes':140509184,"
        "'shard_wall_limit_seconds':3600,'disposition':'REFUSE',"
        "'reasons':['INSUFFICIENT_FREE_BYTES']};"
        "(p/'resource-refusal.json').write_text(json.dumps(r,sort_keys=True,separators=(',',':'))+'\\n');"
        "raise SystemExit(3)"
    )
    assert _supervise(
        base_pilot, exact_output,
        worker_argv=(sys.executable, "-c", script, "{stage_dir}"),
    ) == "resource-exhausted"
    terminal = _json(exact_output / "resource-terminal.json")
    assert terminal["reasons"] == ["INSUFFICIENT_FREE_BYTES"]


def test_worker_refusal_receipt_rejects_invented_reason(
    base_pilot: tuple[Path, Path, Path, str], tmp_path: Path,
) -> None:
    output = tmp_path / "invented-refusal-receipt"
    script = (
        "import json,pathlib,sys;"
        "p=pathlib.Path(sys.argv[1]);"
        "r={'schema_version':1,'study_id':'reflect-lite-policy-control',"
        "'phase':'pilot','revision':1,'shard_id':'P1:base:000',"
        "'retained_bytes':0,'temp_bytes':0,'quarantine_bytes':0,'free_bytes':0,"
        "'wall_seconds':0,'cpu_seconds':0,'reserved_bytes':140509184,"
        "'shard_wall_limit_seconds':3600,'disposition':'REFUSE',"
        "'reasons':['PHASE_BYTES_EXCEEDED']};"
        "(p/'resource-refusal.json').write_text(json.dumps(r,sort_keys=True,separators=(',',':'))+'\\n');"
        "raise SystemExit(3)"
    )
    with pytest.raises(artifacts.ArtifactError, match="refusal receipt"):
        _supervise(
            base_pilot, output,
            worker_argv=(sys.executable, "-c", script, "{stage_dir}"),
        )
    assert tuple(output.rglob("completion.json")) == ()


def test_supervisor_exact_reissue_validates_and_skips_without_spawn(
    base_pilot: tuple[Path, Path, Path, str], tmp_path: Path,
) -> None:
    output = tmp_path / "resume-results"
    assert _supervise(
        base_pilot, output, deadline_s=0.05, term_grace_s=0.05,
        worker_argv=(sys.executable, "-c", "import time;time.sleep(60)"),
    ) == "declared-invalid"
    sentinel = tmp_path / "resume-worker-ran"
    assert _supervise(
        base_pilot, output,
        worker_argv=(sys.executable, "-c", f"open({str(sentinel)!r},'w').write('ran')"),
    ) == "validated-and-skipped"
    assert not sentinel.exists()


def test_supervisor_rejects_deadline_above_frozen_shard_cap(
    base_pilot: tuple[Path, Path, Path, str], tmp_path: Path,
) -> None:
    with pytest.raises(artifacts.ArtifactError, match="3,600|3600|deadline"):
        _supervise(base_pilot, tmp_path / "results", deadline_s=3_600.000_001)


def test_supervisor_records_measured_child_cpu_not_literal_zero(
    base_pilot: tuple[Path, Path, Path, str], tmp_path: Path,
) -> None:
    output = tmp_path / "cpu-results"
    assert _supervise(base_pilot, output) == "published"
    ledger = json.loads(next(output.rglob("resource-ledger.jsonl")).read_text())
    assert type(ledger["cpu_ns"]) is int and ledger["cpu_ns"] > 0


@pytest.mark.parametrize("return_code", (1, 2, 70))
def test_untyped_worker_failure_is_not_published_as_accidental_invalid(
    base_pilot: tuple[Path, Path, Path, str], tmp_path: Path, return_code: int,
) -> None:
    output = tmp_path / f"internal-{return_code}"
    with pytest.raises(artifacts.ArtifactError, match="worker|unsafe|internal"):
        _supervise(
            base_pilot, output,
            worker_argv=(sys.executable, "-c", f"raise SystemExit({return_code})"),
        )
    assert tuple(output.rglob("completion.json")) == ()


def test_real_p1_base_shard_runs_all_three_declared_conditions(
    base_pilot: tuple[Path, Path, Path, str], tmp_path: Path,
) -> None:
    output = tmp_path / "real-results"
    assert _supervise(base_pilot, output) == "published"
    completion_paths = tuple(output.rglob("completion.json"))
    assert len(completion_paths) == 1
    completion = _json(completion_paths[0])
    assert completion["state"] == "COMPLETE"
    assert len(completion["completed_output_identities"]) == 3
    assert len(completion["rollout_sha256s"]) == 3
    assert artifacts.publish_shard_disposition(
        base_pilot[0], base_pilot[3], output,
    ) == "CONTINUE"
    with pytest.raises(artifacts.ArtifactError, match="incomplete"):
        artifacts.publish_stage_disposition(base_pilot[0], output)


def test_terminal_base_vertical_slice_analyzes_freezes_and_reports_without_confirmation_claim(
    base_pilot: tuple[Path, Path, Path, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, config, _, shard_id = base_pilot
    output = tmp_path / "terminal-results"
    assert _supervise(base_pilot, output) == "published"
    monkeypatch.setattr(
        artifacts, "_p1_scientific_failure",
        lambda *_args, **_kwargs: "UNSTABLE_DIVERGENCE",
    )
    assert artifacts.publish_shard_disposition(manifest, shard_id, output) == "TERMINAL_STOPPED"
    assert artifacts.analyze_phase(manifest, output) == 0
    decision = _json(manifest.parent / "pilot-decision.json")
    assert decision["lifecycle_state"] == "STOPPED"
    assert decision["scientific_result"] == "INCONCLUSIVE"
    assert decision["total_episode_count"] == 3
    assert decision["reasons"] == ["UNSTABLE_DIVERGENCE"]

    assert artifacts.freeze_protocol(manifest, output, config) == 0
    frozen = _json(manifest.parents[1] / "configs" / "frozen.yaml")
    assert frozen["confirmation_protocol"]["enabled"] is False
    assert frozen["gates"] is None
    assert artifacts.write_report(manifest, output) == 0
    assert (output / "artifact-digests.json").is_file()
    results = (output / "RESULTS.md").read_text(encoding="utf-8")
    assert "INCONCLUSIVE" in results and "no confirmation" in results.lower()
    assert "physical" in results.lower() and "not validated" in results.lower()
