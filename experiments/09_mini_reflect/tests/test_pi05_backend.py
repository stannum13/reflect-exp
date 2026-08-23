from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess

import pytest


PINNED_SHA = "15a9616a00943ada6c20a0f158e3adb39df2ccac"


def _module():
    return importlib.import_module("experiments.09_mini_reflect.src.pi05_backend")


def _official_source() -> Path:
    worktree = Path(__file__).resolve().parents[3]
    common_git = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=worktree,
            text=True,
        ).strip()
    )
    return common_git.parent / "external" / "openpi"


def _fixture_observations() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_commit": PINNED_SHA,
        "host": {
            "machine": "arm64",
            "chip": "Apple M2 Max",
            "memory": "32 GB",
            "python": "3.11.13",
        },
        "runtime": {
            "exit_code": 2,
            "stdout": "",
            "stderr": "jax-cuda12-plugin has no wheel for macosx_15_0_arm64",
            "cuda_available": False,
        },
        "client": {
            "exit_code": 0,
            "stdout": "Would install openpi-client and websockets",
            "stderr": "",
        },
        "checkpoint": {
            "uri": "gs://openpi-assets/checkpoints/pi05_droid",
            "object_count": 20,
            "total_bytes": 12_429_488_598,
            "inventory_sha256": "a" * 64,
            "downloaded": False,
        },
        "remote": {"configured": False, "authenticated": False},
    }


def test_official_source_is_exact_and_exposes_action_chunks_not_semantic_text() -> None:
    backend = _module()
    finding = backend.inspect_official_source(_official_source(), expected_commit=PINNED_SHA)
    assert finding["source_commit"] == PINNED_SHA
    assert finding["model_type"] == "PI05_FLOW_MATCHING"
    assert finding["interface_kind"] == "ACTION_CHUNK_ONLY"
    assert finding["policy_output_keys"] == ["actions", "policy_timing", "state"]
    assert finding["action_shapes"] == {"pi05_base": [50, 32], "pi05_droid": [15, 32]}
    assert finding["semantic_output_fields"] == []
    assert finding["semantic_decoder_present"] is False
    assert finding["source_files_sha256"]

    with pytest.raises(backend.ProbeError, match="commit"):
        backend.inspect_official_source(_official_source(), expected_commit="0" * 40)


def test_official_base_policy_path_executes_but_receipt_is_not_model_inference() -> None:
    backend = _module()
    receipt = backend.run_official_base_policy_smoke(_official_source())
    assert receipt["official_code_executed"] is True
    assert receipt["api_method"] == "BasePolicy.infer"
    assert receipt["output_keys"] == ["actions"]
    assert receipt["output_shape"] == [15, 32]
    assert receipt["sample_origin"] == "DETERMINISTIC_TRANSPORT_FIXTURE"
    assert receipt["checkpoint_forward_pass"] is False
    assert receipt["scientific_disposition"] == "NONWORKING_SEMANTIC_INTERFACE_SAMPLE"


def test_action_output_is_discarded_and_cannot_be_promoted_to_semantic_plan() -> None:
    backend = _module()
    action_response = {"actions": [[0.0] * 32 for _ in range(15)], "policy_timing": {"infer_ms": 1.0}}
    classified = backend.classify_response(action_response, checkpoint_forward_pass=True)
    assert classified["interface_kind"] == "ACTION_CHUNK_ONLY"
    assert classified["semantic_plan"] is None
    assert classified["actions_discarded"] is True
    assert classified["discarded_actions_sha256"]

    fabricated_semantic = {
        "object_id": "cup_17",
        "affordance": "side_grasp",
        "subgoals": ["approach", "grasp"],
    }
    rejected = backend.classify_response(fabricated_semantic, checkpoint_forward_pass=False)
    assert rejected["interface_kind"] == "UNAUTHENTICATED_NON_OFFICIAL_RESPONSE"
    assert rejected["semantic_plan"] is None


def test_preflight_requires_real_forward_or_authenticated_remote_backend() -> None:
    backend = _module()
    summary = backend.evaluate_preflight(_fixture_observations())
    assert summary["disposition"] == "NOT_RUN_NO_CHECKPOINT_BACKEND"
    assert summary["checkpoint_forward_pass"] is False
    assert summary["local_runtime_supported"] is False
    assert summary["remote_runtime_supported"] is False
    assert summary["semantic_interface_supported"] is False
    assert summary["blockers"] == [
        "LOCAL_RUNTIME_PLATFORM_UNSUPPORTED",
        "NO_AUTHENTICATED_REMOTE_BACKEND",
        "NO_CHECKPOINT_FORWARD_PASS",
        "OFFICIAL_INTERFACE_ACTION_CHUNKS_ONLY",
    ]


def test_probe_reconstructs_byte_identically_and_tampering_fails_closed(tmp_path: Path) -> None:
    backend = _module()
    output = tmp_path / "probe"
    replay = tmp_path / "replay"
    observations = _fixture_observations()
    backend.publish_probe(
        output,
        source_finding=backend.inspect_official_source(_official_source(), expected_commit=PINNED_SHA),
        observations=observations,
        api_smoke=backend.run_official_base_policy_smoke(_official_source()),
    )
    backend.reconstruct(output / "raw", replay)
    expected = {"summary.json", "interface-table.csv", "interface-flow.svg", "RESULTS.md", "derived-manifest.json"}
    assert expected == {path.name for path in (output / "derived").iterdir()}
    for name in expected:
        assert (output / "derived" / name).read_bytes() == (replay / name).read_bytes()

    raw = output / "raw" / "observations.json"
    payload = json.loads(raw.read_text(encoding="ascii"))
    payload["remote"]["authenticated"] = True
    raw.write_text(json.dumps(payload), encoding="ascii")
    with pytest.raises(backend.ProbeError, match="manifest"):
        backend.reconstruct(output / "raw", tmp_path / "tampered")


def test_checkpoint_metadata_is_reduced_to_content_identity_without_download_urls() -> None:
    backend = _module()
    metadata = [
        {
            "url": "gs://bucket/checkpoints/pi05_droid/params/a#7",
            "type": "cloud_object",
            "metadata": {
                "name": "checkpoints/pi05_droid/params/a",
                "size": "11",
                "md5Hash": "abc=",
                "crc32c": "def=",
                "generation": "7",
                "mediaLink": "https://download.example/secret-capability",
            },
        },
        {
            "url": "gs://bucket/checkpoints/pi05_droid/params/b#8",
            "type": "cloud_object",
            "metadata": {
                "name": "checkpoints/pi05_droid/params/b",
                "size": "13",
                "md5Hash": "ghi=",
                "crc32c": "jkl=",
                "generation": "8",
            },
        },
    ]
    receipt = backend.reduce_checkpoint_metadata(json.dumps(metadata))
    assert receipt["object_count"] == 2
    assert receipt["total_bytes"] == 24
    assert receipt["inventory_sha256"]
    assert [row["name"] for row in receipt["objects"]] == [
        "checkpoints/pi05_droid/params/a",
        "checkpoints/pi05_droid/params/b",
    ]
    assert "mediaLink" not in json.dumps(receipt)


def test_command_receipts_retain_exact_streams_and_environment_is_sanitized() -> None:
    backend = _module()
    receipt = backend.command_receipt(
        ["uv", "sync", "--offline", "--dry-run"],
        exit_code=2,
        stdout="out\n",
        stderr="unsupported platform\n",
    )
    assert receipt == {
        "argv": ["uv", "sync", "--offline", "--dry-run"],
        "exit_code": 2,
        "stdout": "out\n",
        "stderr": "unsupported platform\n",
        "stdout_sha256": backend.sha256_bytes(b"out\n"),
        "stderr_sha256": backend.sha256_bytes(b"unsupported platform\n"),
    }
    host = backend.sanitize_hardware_profile(
        {
            "SPHardwareDataType": [{
                "chip_type": "Apple M2 Max",
                "physical_memory": "32 GB",
                "machine_model": "Mac14,5",
                "number_processors": "proc 12:8:4",
                "serial_number": "must-not-leak",
                "platform_UUID": "must-not-leak",
            }]
        }
    )
    assert host == {
        "chip": "Apple M2 Max",
        "memory": "32 GB",
        "machine_model": "Mac14,5",
        "processors": "proc 12:8:4",
    }


def test_collector_uses_official_dry_runs_and_metadata_only(tmp_path: Path) -> None:
    backend = _module()
    hardware = json.dumps({
        "SPHardwareDataType": [{
            "chip_type": "Apple M2 Max",
            "physical_memory": "32 GB",
            "machine_model": "Mac14,5",
            "number_processors": "proc 12:8:4",
            "serial_number": "must-not-enter-evidence",
            "platform_UUID": "must-not-enter-evidence",
        }]
    })
    metadata = json.dumps([{
        "metadata": {
            "name": "checkpoints/pi05_droid/params/a",
            "size": "11",
            "md5Hash": "abc=",
            "crc32c": "def=",
            "generation": "7",
        }
    }])
    calls: list[list[str]] = []

    def runner(argv: list[str], extra_env: dict[str, str] | None = None):
        calls.append(argv)
        if argv[0] == "system_profiler":
            return 0, hardware, ""
        if argv[:2] == ["uv", "sync"] and "packages/openpi-client" in argv[3]:
            return 0, "Would install official client", ""
        if argv[:2] == ["uv", "sync"]:
            assert extra_env and extra_env["UV_PROJECT_ENVIRONMENT"].startswith("/private/tmp/")
            return 2, "", "jax-cuda12-plugin has no macOS arm64 wheel"
        if argv[:3] == ["gcloud", "storage", "ls"]:
            return 0, metadata, ""
        raise AssertionError(argv)

    observations = backend.collect_observations(
        _official_source(),
        python_executable="/repo/.venv/bin/python",
        checkpoint_cache=tmp_path / "absent-checkpoint",
        environ={},
        runner=runner,
    )
    assert len(calls) == 4
    assert observations["runtime"]["exit_code"] == 2
    assert observations["client"]["exit_code"] == 0
    assert observations["checkpoint"]["total_bytes"] == 11
    assert observations["checkpoint"]["downloaded"] is False
    assert observations["remote"] == {"configured": False, "authenticated": False}
    assert all("download" not in " ".join(call) for call in calls)
    assert "must-not-enter-evidence" not in json.dumps(observations)
