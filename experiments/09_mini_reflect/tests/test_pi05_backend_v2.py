from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess

import pytest


PINNED_SHA = "15a9616a00943ada6c20a0f158e3adb39df2ccac"


def _module():
    return importlib.import_module("experiments.09_mini_reflect.src.pi05_backend_v2")


def _official_source() -> Path:
    worktree = Path(__file__).resolve().parents[3]
    common_git = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=worktree, text=True,
    ).strip())
    return common_git.parent / "external" / "openpi"


def _checkpoint() -> dict[str, object]:
    objects = [
        {"name": "checkpoints/pi05_droid/assets/norm.json", "size": 11, "md5_base64": "abc=", "crc32c_base64": "def=", "generation": "7"},
        {"name": "checkpoints/pi05_droid/params/a", "size": 13, "md5_base64": "ghi=", "crc32c_base64": "jkl=", "generation": "8"},
    ]
    backend = _module()
    return {"checkpoint_id": backend.CHECKPOINT_ID, "object_count": 2, "total_bytes": 24,
            "inventory_sha256": backend.sha256_json(objects), "objects": objects}


def _observations(source_receipt: dict[str, object]) -> dict[str, object]:
    backend = _module()
    commands = {
        "runtime_dependency_check": backend.command_receipt(
            ["uv", "sync", "--project", "$OPENPI", "--python", "$PYTHON", "--frozen", "--offline", "--dry-run"],
            exit_code=2, stdout="", stderr="jax-cuda12-plugin has no wheel for macos arm64\n",
        ),
        "client_dependency_check": backend.command_receipt(
            ["uv", "sync", "--project", "$OPENPI/packages/openpi-client", "--python", "$PYTHON", "--frozen", "--offline", "--dry-run"],
            exit_code=0, stdout="", stderr="Would install openpi-client and websockets\n",
        ),
    }
    return {
        "schema_version": 2,
        "source_receipt_sha256": backend.sha256_json(source_receipt),
        "host": {"machine": "arm64", "chip": "Apple M2 Max", "memory": "32 GB", "python": "3.11.13", "cuda_available": False},
        "commands": commands,
        "command_ancestry_sha256": backend.sha256_json(commands),
        "checkpoint": _checkpoint(),
    }


def _publish(tmp_path: Path) -> Path:
    backend = _module()
    receipt = backend.inspect_official_source(_official_source(), expected_commit=PINNED_SHA)
    output = tmp_path / "v2"
    backend.publish_probe_v2(output, source_root=_official_source(), source_receipt=receipt,
                             observations=_observations(receipt), forward_receipt=None)
    return output


def test_source_closure_contains_required_policy_transport_config_model_and_lock() -> None:
    backend = _module()
    paths = set(backend.SOURCE_FILES)
    assert {"src/openpi/policies/droid_policy.py", "src/openpi/policies/policy.py",
            "src/openpi/policies/policy_config.py", "src/openpi/serving/websocket_policy_server.py",
            "packages/openpi-client/src/openpi_client/websocket_client_policy.py",
            "src/openpi/training/config.py", "src/openpi/models/pi0.py",
            "src/openpi/models/pi0_config.py", "pyproject.toml", "uv.lock"} <= paths


def test_source_receipt_has_exact_git_blob_sha256_and_size() -> None:
    backend = _module()
    receipt = backend.inspect_official_source(_official_source(), expected_commit=PINNED_SHA)
    assert set(receipt) == {"schema_version", "source_commit", "files", "closure_sha256", "source_finding"}
    droid = next(row for row in receipt["files"] if row["path"] == "src/openpi/policies/droid_policy.py")
    assert droid["git_blob"] == "55bdb419dd552daa9dd2943638b91c7d580e26fc"
    assert len(droid["sha256"]) == 64 and droid["bytes"] > 0


def test_source_commit_mismatch_fails_closed() -> None:
    backend = _module()
    with pytest.raises(backend.ProbeError, match="commit"):
        backend.inspect_official_source(_official_source(), expected_commit="0" * 40)


def test_source_symlink_fails_closed(tmp_path: Path) -> None:
    backend = _module()
    root = tmp_path / "source"
    root.mkdir()
    (root / "uv.lock").symlink_to(_official_source() / "uv.lock")
    with pytest.raises(backend.ProbeError, match="symlink|closure"):
        backend.inspect_official_source(root, expected_commit=PINNED_SHA)


def test_ast_derives_internal_and_public_droid_shapes() -> None:
    finding = _module().inspect_official_source(_official_source(), expected_commit=PINNED_SHA)["source_finding"]
    assert finding["model_action_shape"] == [15, 32]
    assert finding["public_action_shape"] == [15, 8]
    assert finding["droid_output_slice"] == [0, 8]


def test_ast_derives_policy_response_without_state() -> None:
    finding = _module().inspect_official_source(_official_source(), expected_commit=PINNED_SHA)["source_finding"]
    assert finding["policy_response_keys"] == ["actions", "policy_timing"]
    assert "state" not in finding["policy_response_keys"]


def test_ast_derives_websocket_server_timing_addition() -> None:
    finding = _module().inspect_official_source(_official_source(), expected_commit=PINNED_SHA)["source_finding"]
    assert finding["websocket_response_keys"] == ["actions", "policy_timing", "server_timing"]
    assert finding["server_added_keys"] == ["server_timing"]


def test_ast_receipt_finds_no_semantic_decoder_text_or_plan_output() -> None:
    finding = _module().inspect_official_source(_official_source(), expected_commit=PINNED_SHA)["source_finding"]
    assert finding["semantic_output_keys"] == []
    assert finding["semantic_decoder_present"] is False
    assert finding["interface_kind"] == "ACTION_CHUNK_ONLY"


def test_transport_fixture_is_explicitly_synthetic_and_15_by_8() -> None:
    receipt = _module().synthetic_transport_fixture()
    assert receipt["sample_origin"] == "SYNTHETIC_TRANSPORT_INTERFACE_FIXTURE"
    assert receipt["model_forward_pass"] is False
    assert receipt["output_shape"] == [15, 8]
    assert receipt["response_keys"] == ["actions", "policy_timing", "server_timing"]


def test_checkpoint_reduction_retains_only_safe_object_identities() -> None:
    backend = _module()
    raw = [{"url": "gs://bucket/path/a#7", "metadata": {"name": "checkpoints/pi05_droid/params/a", "size": "11", "md5Hash": "abc=", "crc32c": "def=", "generation": "7", "mediaLink": "https://secret/?token=x", "selfLink": "https://secret/self"}}]
    value = backend.reduce_checkpoint_metadata(json.dumps(raw))
    assert set(value) == {"checkpoint_id", "object_count", "total_bytes", "inventory_sha256", "objects"}
    assert "http" not in json.dumps(value) and "token" not in json.dumps(value)


def test_checkpoint_reduction_rejects_unsafe_or_duplicate_names() -> None:
    backend = _module()
    row = {"metadata": {"name": "../secret", "size": "1", "md5Hash": "a=", "crc32c": "b=", "generation": "1"}}
    with pytest.raises(backend.ProbeError, match="name"):
        backend.reduce_checkpoint_metadata(json.dumps([row]))
    row["metadata"]["name"] = "checkpoints/pi05_droid/a"
    with pytest.raises(backend.ProbeError, match="duplicate"):
        backend.reduce_checkpoint_metadata(json.dumps([row, row]))


def test_command_receipt_rejects_absolute_paths_urls_and_tokens() -> None:
    backend = _module()
    with pytest.raises(backend.ProbeError, match="unsafe"):
        backend.command_receipt(["uv", "--project", "/Users/alice/repo"], exit_code=0, stdout="", stderr="")
    with pytest.raises(backend.ProbeError, match="unsafe"):
        backend.command_receipt(["curl", "https://example.test/?token=x"], exit_code=0, stdout="", stderr="")


def test_command_receipt_sanitizes_streams_before_hashing() -> None:
    backend = _module()
    receipt = backend.command_receipt(["probe"], exit_code=1,
        stdout="file /Users/alice/private/model\n", stderr="https://host/path?token=secret\nBearer abcdef\n")
    encoded = json.dumps(receipt)
    assert "/Users/alice" not in encoded and "https://" not in encoded and "abcdef" not in encoded
    assert receipt["stdout_sha256"] == backend.sha256_bytes(receipt["stdout"].encode())


def test_observation_schema_rejects_extra_nested_fields() -> None:
    backend = _module()
    receipt = backend.inspect_official_source(_official_source(), expected_commit=PINNED_SHA)
    observations = _observations(receipt)
    observations["host"]["serial"] = "secret"
    with pytest.raises(backend.ProbeError, match="schema"):
        backend.validate_observations(observations, receipt)


def test_command_ancestry_rehash_is_rejected() -> None:
    backend = _module()
    receipt = backend.inspect_official_source(_official_source(), expected_commit=PINNED_SHA)
    observations = _observations(receipt)
    observations["commands"]["runtime_dependency_check"]["exit_code"] = 0
    with pytest.raises(backend.ProbeError, match="ancestry"):
        backend.validate_observations(observations, receipt)


def test_checkpoint_inventory_rehash_is_rejected() -> None:
    backend = _module()
    receipt = backend.inspect_official_source(_official_source(), expected_commit=PINNED_SHA)
    observations = _observations(receipt)
    observations["checkpoint"]["objects"][0]["size"] = 12
    with pytest.raises(backend.ProbeError, match="checkpoint"):
        backend.validate_observations(observations, receipt)


def test_preflight_ignores_boolean_path_and_environment_claims() -> None:
    backend = _module()
    receipt = backend.inspect_official_source(_official_source(), expected_commit=PINNED_SHA)
    observations = _observations(receipt)
    observations.update({"forward_pass": True, "checkpoint_path": "/tmp/model", "OPENPI_REMOTE_HOST": "server"})
    summary = backend.evaluate_preflight(observations, source_receipt=receipt, forward_receipt=None)
    assert summary["model_forward_pass"] is False
    assert summary["disposition"] == "NOT_RUN"


def test_unbound_forward_receipt_is_rejected() -> None:
    backend = _module()
    receipt = backend.inspect_official_source(_official_source(), expected_commit=PINNED_SHA)
    observations = _observations(receipt)
    fake = {"model_forward_pass": True, "response_path": "/tmp/response"}
    with pytest.raises(backend.ProbeError, match="forward receipt"):
        backend.evaluate_preflight(observations, source_receipt=receipt, forward_receipt=fake)


def test_raw_manifest_authenticates_every_raw_member_including_static_source_receipts(tmp_path: Path) -> None:
    backend = _module()
    output = _publish(tmp_path)
    manifest = json.loads((output / "raw/raw-manifest.json").read_text())
    paths = {row["path"] for row in manifest["members"]}
    assert "source-receipt.json" in paths
    assert "source-static-receipts.json" in paths
    assert paths == set(backend.RAW_MEMBER_PATHS)


def test_root_manifest_authenticates_raw_and_derived_manifests(tmp_path: Path) -> None:
    output = _publish(tmp_path)
    root_manifest = json.loads((output / "evidence-manifest.json").read_text())
    paths = {row["path"] for row in root_manifest["members"]}
    assert {"raw/raw-manifest.json", "derived/derived-manifest.json"} <= paths


def test_recursive_exact_schema_rejects_extra_root_raw_and_derived_files(tmp_path: Path) -> None:
    backend = _module()
    for relative in ("extra.txt", "raw/extra.txt", "derived/extra.txt", "raw/nested/manifest.json"):
        output = _publish(tmp_path / relative.replace("/", "_"))
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
        with pytest.raises(backend.ProbeError, match="schema"):
            backend.validate_published(output)


def test_recursive_schema_rejects_symlink_and_broken_symlink(tmp_path: Path) -> None:
    backend = _module()
    for target in ("raw/observations.json", "missing"):
        output = _publish(tmp_path / target.replace("/", "_"))
        (output / "raw/link").symlink_to(target)
        with pytest.raises(backend.ProbeError, match="symlink"):
            backend.validate_published(output)


def test_replay_reconstructs_byte_identically_from_authenticated_source_receipts(tmp_path: Path) -> None:
    backend = _module()
    output = _publish(tmp_path)
    replay = tmp_path / "replay"
    backend.reconstruct_v2(output / "raw", replay)
    assert {p.name for p in replay.iterdir()} == {p.name for p in (output / "derived").iterdir()}
    for path in replay.iterdir():
        assert path.read_bytes() == (output / "derived" / path.name).read_bytes()


def test_replay_rejects_coherent_label_and_manifest_rehash(tmp_path: Path) -> None:
    backend = _module()
    output = _publish(tmp_path)
    receipt_path = output / "raw/source-static-receipts.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["droid_output_slice"] = [0, 9]
    receipt["public_action_shape"] = [15, 9]
    receipt_path.write_bytes(backend.canonical_json(receipt))
    backend.rewrite_manifest_for_test(output / "raw")
    with pytest.raises(backend.ProbeError, match="pinned blob"):
        backend.reconstruct_v2(output / "raw", tmp_path / "forged")


def test_replay_rejects_member_tamper_without_manifest_rehash(tmp_path: Path) -> None:
    backend = _module()
    output = _publish(tmp_path)
    (output / "raw/observations.json").write_text("{}\n")
    with pytest.raises(backend.ProbeError, match="manifest"):
        backend.reconstruct_v2(output / "raw", tmp_path / "tampered")


def test_v1_tree_is_unchanged_and_v2_marks_it_rejected_superseded(tmp_path: Path) -> None:
    output = _publish(tmp_path)
    marker = json.loads((output / "SUPERSESSION.json").read_text())
    assert marker["disposition"] == "V1_REJECTED_SUPERSEDED_BY_V2"
    assert marker["preserved_v1_tree_sha256"]


def test_report_never_overclaims_model_or_semantic_plan(tmp_path: Path) -> None:
    output = _publish(tmp_path)
    report = (output / "derived/RESULTS.md").read_text()
    assert "NOT_RUN" in report
    assert "synthetic" in report.lower()
    assert "No model forward pass" in report
    assert "semantic plan" in report.lower()


def test_published_evidence_contains_no_absolute_user_paths_urls_or_tokens(tmp_path: Path) -> None:
    output = _publish(tmp_path)
    for path in output.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert b"/Users/" not in data
            assert b"mediaLink" not in data and b"selfLink" not in data
            assert b"https://" not in data and b"Bearer " not in data


def test_publish_is_create_only(tmp_path: Path) -> None:
    backend = _module()
    output = _publish(tmp_path)
    receipt = backend.inspect_official_source(_official_source(), expected_commit=PINNED_SHA)
    with pytest.raises(backend.ProbeError, match="create-only"):
        backend.publish_probe_v2(output, source_root=_official_source(), source_receipt=receipt,
                                 observations=_observations(receipt), forward_receipt=None)
