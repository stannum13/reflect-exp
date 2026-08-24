"""Fail-closed, replayable pi0.5 public-interface feasibility probe V2."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Any


PINNED_OPENPI_COMMIT = "15a9616a00943ada6c20a0f158e3adb39df2ccac"
CHECKPOINT_ID = "openpi-assets/checkpoints/pi05_droid"
SOURCE_BLOBS = {
    "README.md": "d16e43d4790c60d9e22e67c58a407594fa6fb772",
    "packages/openpi-client/pyproject.toml": "160db378bd13e3e501ad3c7fa8aa4a2637ae5210",
    "packages/openpi-client/src/openpi_client/base_policy.py": "2f4290651b1b7bab3bd9549b47876838f5b51629",
    "packages/openpi-client/src/openpi_client/msgpack_numpy.py": "007f755edf54565579376b077eec7f7f715e1b96",
    "packages/openpi-client/src/openpi_client/websocket_client_policy.py": "466685e00d004ff8c7dd5694636a8ec3e6439d11",
    "pyproject.toml": "5377e3dac52aeedfae61e6c466b2bd260860c643",
    "scripts/serve_policy.py": "30f121a60ba6af3d21c287e5c5582da54072ea62",
    "src/openpi/models/model.py": "29618b49453742266fe6e4a5815ceee06d815f3b",
    "src/openpi/models/pi0.py": "ae7c4590f330f160aa9baa713d5b77fc060120de",
    "src/openpi/models/pi0_config.py": "584d83f199e092203b59861a861c64768a4e0300",
    "src/openpi/policies/droid_policy.py": "55bdb419dd552daa9dd2943638b91c7d580e26fc",
    "src/openpi/policies/policy.py": "b9b708bdcaffa086be4b22b84a29b8cc00c710e4",
    "src/openpi/policies/policy_config.py": "6570df05ed068f297d48326990a1cd10ee68ac5a",
    "src/openpi/serving/websocket_policy_server.py": "bdefa98b879323aca449550bf1985ae877eddd83",
    "src/openpi/training/config.py": "4ca47e1286534c4ee7a919ccc38462f8f38bdd60",
    "src/openpi/transforms.py": "272375ea95a5e43a42a6c0ff14cf89d34da76a45",
    "uv.lock": "d7c9e410b1fc23dd51e8dc4599dda660029aac8c",
}
SOURCE_FILES = tuple(SOURCE_BLOBS)
RAW_MEMBER_PATHS = (
    "forward-receipt.json",
    "observations.json",
    "source-receipt.json",
    "source-static-receipts.json",
    "transport-fixture.json",
)
DERIVED_MEMBER_PATHS = ("RESULTS.md", "interface-table.csv", "summary.json")
SEMANTIC_KEYS = frozenset({"semantic_plan", "plan", "text", "tokens", "subgoals", "affordance"})
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_URL = re.compile(r"(?:https?|wss?|file|gs)://[^\s\"']+")
_USER_PATH = re.compile(r"/(?:Users|home)/[^\s\"']+")
_BEARER = re.compile(r"(?i)(?:Bearer|Api-Key)\s+[^\s\"']+")


class ProbeError(RuntimeError):
    """Raised when source or evidence does not satisfy the closed contract."""


def canonical_json(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(payload: Any) -> str:
    return sha256_bytes(canonical_json(payload))


def _git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()  # noqa: S324


def file_identity(path: Path, *, relative_path: str) -> dict[str, Any]:
    data = path.read_bytes()
    return {"path": relative_path, "bytes": len(data), "sha256": sha256_bytes(data), "git_blob": _git_blob(data)}


def _exact(value: Any, keys: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ProbeError(f"{label} schema is not exact")


def _safe_relative(value: str, *, prefix: str | None = None) -> bool:
    path = PurePosixPath(value)
    return bool(value and not path.is_absolute() and ".." not in path.parts and not value.startswith(".")) and (
        prefix is None or value.startswith(prefix)
    )


def _sanitize_stream(value: str) -> str:
    value = _USER_PATH.sub("$REDACTED_PATH", value)
    value = _URL.sub("$REDACTED_URL", value)
    return _BEARER.sub("$REDACTED_AUTH", value)


def command_receipt(argv: list[str], *, exit_code: int, stdout: str, stderr: str) -> dict[str, Any]:
    if not argv or any(_URL.search(arg) or _USER_PATH.search(arg) or (arg.startswith("/") and not arg.startswith("/private/tmp/")) for arg in argv):
        raise ProbeError("unsafe command argv")
    safe_stdout = _sanitize_stream(stdout)
    safe_stderr = _sanitize_stream(stderr)
    return {
        "argv": argv,
        "exit_code": int(exit_code),
        "stdout": safe_stdout,
        "stderr": safe_stderr,
        "stdout_sha256": sha256_bytes(safe_stdout.encode("utf-8")),
        "stderr_sha256": sha256_bytes(safe_stderr.encode("utf-8")),
    }


def reduce_checkpoint_metadata(raw_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ProbeError("checkpoint metadata is invalid JSON") from exc
    if not isinstance(payload, list) or not payload:
        raise ProbeError("checkpoint metadata inventory is empty")
    objects: list[dict[str, Any]] = []
    names: set[str] = set()
    for item in payload:
        metadata = item.get("metadata") if isinstance(item, dict) else None
        try:
            row = {
                "name": str(metadata["name"]),
                "size": int(metadata["size"]),
                "md5_base64": str(metadata["md5Hash"]),
                "crc32c_base64": str(metadata["crc32c"]),
                "generation": str(metadata["generation"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ProbeError("checkpoint object metadata is incomplete") from exc
        if not _safe_relative(row["name"], prefix="checkpoints/pi05_droid/"):
            raise ProbeError("checkpoint object name is unsafe")
        if row["name"] in names:
            raise ProbeError("duplicate checkpoint object name")
        if row["size"] < 0:
            raise ProbeError("checkpoint object size is invalid")
        names.add(row["name"])
        objects.append(row)
    objects.sort(key=lambda row: row["name"])
    return {
        "checkpoint_id": CHECKPOINT_ID,
        "object_count": len(objects),
        "total_bytes": sum(row["size"] for row in objects),
        "inventory_sha256": sha256_json(objects),
        "objects": objects,
    }


def _literal_dict_keys(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.Dict):
        return []
    return [key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name]
    if not matches:
        raise ProbeError(f"source function {name} was not found")
    return matches[0]


def _derive_static_receipts(root: Path) -> dict[str, Any]:
    config_tree = ast.parse((root / "src/openpi/training/config.py").read_text(encoding="utf-8"))
    policy_tree = ast.parse((root / "src/openpi/policies/policy.py").read_text(encoding="utf-8"))
    droid_tree = ast.parse((root / "src/openpi/policies/droid_policy.py").read_text(encoding="utf-8"))
    server_tree = ast.parse((root / "src/openpi/serving/websocket_policy_server.py").read_text(encoding="utf-8"))
    client_tree = ast.parse((root / "packages/openpi-client/src/openpi_client/websocket_client_policy.py").read_text(encoding="utf-8"))
    model_tree = ast.parse((root / "src/openpi/models/pi0.py").read_text(encoding="utf-8"))

    horizon = action_dim = None
    pi05_bound = False
    droid_transform_bound = False
    for node in ast.walk(config_tree):
        if not isinstance(node, ast.Call):
            continue
        name = next((kw.value.value for kw in node.keywords if kw.arg == "name" and isinstance(kw.value, ast.Constant)), None)
        if name != "pi05_droid":
            continue
        model = next((kw.value for kw in node.keywords if kw.arg == "model"), None)
        if isinstance(model, ast.Call):
            values = {kw.arg: kw.value.value for kw in model.keywords if isinstance(kw.value, ast.Constant)}
            horizon = int(values.get("action_horizon", 50))
            action_dim = int(values.get("action_dim", 32))
            pi05_bound = values.get("pi05") is True
        droid_transform_bound = "DroidOutputs" in ast.unparse(node)
        break
    if not (pi05_bound and droid_transform_bound and horizon and action_dim):
        raise ProbeError("pi05_droid config and output transform were not found")

    droid_class = next(
        node for node in droid_tree.body if isinstance(node, ast.ClassDef) and node.name == "DroidOutputs"
    )
    droid_call = next(
        node for node in droid_class.body if isinstance(node, ast.FunctionDef) and node.name == "__call__"
    )
    droid_keys: list[str] = []
    upper = None
    for node in ast.walk(droid_call):
        if isinstance(node, ast.Return):
            droid_keys = _literal_dict_keys(node.value)
            for child in ast.walk(node.value):
                if isinstance(child, ast.Slice) and isinstance(child.upper, ast.Constant) and child.upper.value == 8:
                    upper = 8
    if droid_keys != ["actions"] or upper != 8:
        raise ProbeError("DroidOutputs public action slice was not found")

    infer = _function(policy_tree, "infer")
    internal_keys: list[str] = []
    added_policy: list[str] = []
    for node in ast.walk(infer):
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "outputs" for target in node.targets):
                keys = _literal_dict_keys(node.value)
                if keys:
                    internal_keys = keys
            for target in node.targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == "outputs" and isinstance(target.slice, ast.Constant):
                    added_policy.append(str(target.slice.value))
    if set(internal_keys) != {"state", "actions"} or added_policy != ["policy_timing"]:
        raise ProbeError("Policy.infer output receipt changed")

    handler = next(node for node in ast.walk(server_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_handler")
    server_added: list[str] = []
    for node in ast.walk(handler):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == "action" and isinstance(target.slice, ast.Constant):
                    server_added.append(str(target.slice.value))
    server_added = sorted(set(server_added))
    if server_added != ["server_timing"]:
        raise ProbeError("websocket server response mutation changed")
    client_infer = _function(client_tree, "infer")
    if "msgpack_numpy.unpackb(response)" not in ast.unparse(client_infer):
        raise ProbeError("websocket client response return changed")
    sample = _function(model_tree, "sample_actions")
    sampler_calls = sorted({ast.unparse(n.func) for n in ast.walk(sample) if isinstance(n, ast.Call)})
    if "jax.lax.while_loop" not in sampler_calls:
        raise ProbeError("pi0.5 sampler receipt changed")

    policy_keys = sorted(droid_keys + added_policy)
    websocket_keys = sorted(policy_keys + server_added)
    identifiers = {n.name.lower() for tree in (droid_tree, policy_tree, server_tree) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    semantic_decoder = any("semantic" in name or "plandecoder" in name for name in identifiers)
    semantic_output = sorted(SEMANTIC_KEYS.intersection(websocket_keys))
    return {
        "schema_version": 2,
        "config_name": "pi05_droid",
        "model_type": "PI05_FLOW_MATCHING",
        "sampler_call": "jax.lax.while_loop",
        "model_action_shape": [horizon, action_dim],
        "droid_output_transform": "DroidOutputs",
        "droid_output_slice": [0, upper],
        "public_action_shape": [horizon, upper],
        "policy_internal_keys_before_output_transform": sorted(internal_keys),
        "policy_response_keys": policy_keys,
        "server_added_keys": server_added,
        "websocket_response_keys": websocket_keys,
        "semantic_output_keys": semantic_output,
        "semantic_decoder_present": semantic_decoder,
        "interface_kind": "SEMANTIC_TEXT" if semantic_output or semantic_decoder else "ACTION_CHUNK_ONLY",
    }


def inspect_official_source(source_root: Path, *, expected_commit: str) -> dict[str, Any]:
    root = source_root.resolve()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProbeError("source closure is not the pinned Git checkout") from exc
    if commit != expected_commit or expected_commit != PINNED_OPENPI_COMMIT:
        raise ProbeError(f"OpenPI commit mismatch: expected {expected_commit}, got {commit}")
    rows: list[dict[str, Any]] = []
    for relative in SOURCE_FILES:
        path = root / relative
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError as exc:
            raise ProbeError(f"source closure is incomplete: {relative}") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise ProbeError(f"source closure contains symlink or non-file: {relative}")
        row = file_identity(path, relative_path=relative)
        if row["git_blob"] != SOURCE_BLOBS[relative]:
            raise ProbeError(f"source does not match pinned blob: {relative}")
        rows.append(row)
    finding = _derive_static_receipts(root)
    return {"schema_version": 2, "source_commit": commit, "files": rows,
            "closure_sha256": sha256_json(rows), "source_finding": finding}


def synthetic_transport_fixture() -> dict[str, Any]:
    response = {"actions": [[0.0] * 8 for _ in range(15)], "policy_timing": {"infer_ms": 0.0},
                "server_timing": {"infer_ms": 0.0}}
    return {"schema_version": 2, "sample_origin": "SYNTHETIC_TRANSPORT_INTERFACE_FIXTURE",
            "model_forward_pass": False, "response_keys": sorted(response), "output_shape": [15, 8],
            "response_sha256": sha256_json(response)}


def _validate_source_receipt(receipt: dict[str, Any]) -> None:
    _exact(receipt, {"schema_version", "source_commit", "files", "closure_sha256", "source_finding"}, "source receipt")
    if receipt["schema_version"] != 2 or receipt["source_commit"] != PINNED_OPENPI_COMMIT:
        raise ProbeError("source receipt commit is not pinned")
    if not isinstance(receipt["files"], list) or [row.get("path") for row in receipt["files"]] != list(SOURCE_FILES):
        raise ProbeError("source receipt closure schema is not exact")
    for row in receipt["files"]:
        _exact(row, {"path", "bytes", "sha256", "git_blob"}, "source file receipt")
        if row["git_blob"] != SOURCE_BLOBS[row["path"]] or not _HEX40.fullmatch(row["git_blob"]):
            raise ProbeError(f"source receipt violates pinned blob: {row['path']}")
        if not isinstance(row["bytes"], int) or row["bytes"] <= 0 or not _HEX64.fullmatch(row["sha256"]):
            raise ProbeError("source file receipt identity is invalid")
    if receipt["closure_sha256"] != sha256_json(receipt["files"]):
        raise ProbeError("source closure hash mismatch")
    if receipt["source_finding"] != _expected_static_receipts():
        raise ProbeError("source static receipts do not match pinned source")


def _expected_static_receipts() -> dict[str, Any]:
    return {
        "schema_version": 2, "config_name": "pi05_droid", "model_type": "PI05_FLOW_MATCHING",
        "sampler_call": "jax.lax.while_loop", "model_action_shape": [15, 32],
        "droid_output_transform": "DroidOutputs", "droid_output_slice": [0, 8],
        "public_action_shape": [15, 8],
        "policy_internal_keys_before_output_transform": ["actions", "state"],
        "policy_response_keys": ["actions", "policy_timing"], "server_added_keys": ["server_timing"],
        "websocket_response_keys": ["actions", "policy_timing", "server_timing"],
        "semantic_output_keys": [], "semantic_decoder_present": False, "interface_kind": "ACTION_CHUNK_ONLY",
    }


def _validate_command(value: Any) -> None:
    _exact(value, {"argv", "exit_code", "stdout", "stderr", "stdout_sha256", "stderr_sha256"}, "command receipt")
    if command_receipt(value["argv"], exit_code=value["exit_code"], stdout=value["stdout"], stderr=value["stderr"]) != value:
        raise ProbeError("command receipt hashes are invalid")


def _validate_checkpoint(value: Any) -> None:
    _exact(value, {"checkpoint_id", "object_count", "total_bytes", "inventory_sha256", "objects"}, "checkpoint")
    if value["checkpoint_id"] != CHECKPOINT_ID or not isinstance(value["objects"], list):
        raise ProbeError("checkpoint identity is invalid")
    names: set[str] = set()
    for row in value["objects"]:
        _exact(row, {"name", "size", "md5_base64", "crc32c_base64", "generation"}, "checkpoint object")
        if not _safe_relative(row["name"], prefix="checkpoints/pi05_droid/") or row["name"] in names:
            raise ProbeError("checkpoint object name is invalid")
        names.add(row["name"])
    if (value["inventory_sha256"] != sha256_json(value["objects"])
            or value["object_count"] != len(value["objects"])
            or value["total_bytes"] != sum(row["size"] for row in value["objects"])):
        raise ProbeError("checkpoint inventory ancestry is invalid")


def validate_observations(observations: dict[str, Any], source_receipt: dict[str, Any]) -> None:
    _exact(observations, {"schema_version", "source_receipt_sha256", "host", "commands", "command_ancestry_sha256", "checkpoint"}, "observations")
    _exact(observations["host"], {"machine", "chip", "memory", "python", "cuda_available"}, "host")
    if observations["schema_version"] != 2 or observations["source_receipt_sha256"] != sha256_json(source_receipt):
        raise ProbeError("observations source ancestry is invalid")
    _exact(observations["commands"], {"runtime_dependency_check", "client_dependency_check"}, "commands")
    for value in observations["commands"].values():
        _validate_command(value)
    if observations["command_ancestry_sha256"] != sha256_json(observations["commands"]):
        raise ProbeError("command ancestry is invalid")
    _validate_checkpoint(observations["checkpoint"])


def _verify_forward_receipt(value: Any, source: dict[str, Any], checkpoint: dict[str, Any]) -> bool:
    keys = {"schema_version", "execution_kind", "source_closure_sha256", "checkpoint_inventory_sha256",
            "server_source_blob", "request_sha256", "response_sha256", "response", "binding_sha256"}
    _exact(value, keys, "forward receipt")
    bound = {key: value[key] for key in sorted(keys - {"binding_sha256"})}
    if (value["schema_version"] != 2 or value["execution_kind"] != "REAL_CHECKPOINT_SERVER_FORWARD"
            or value["source_closure_sha256"] != source["closure_sha256"]
            or value["checkpoint_inventory_sha256"] != checkpoint["inventory_sha256"]
            or value["server_source_blob"] != SOURCE_BLOBS["src/openpi/serving/websocket_policy_server.py"]
            or value["response_sha256"] != sha256_json(value["response"])
            or value["binding_sha256"] != sha256_json(bound)):
        raise ProbeError("forward receipt is not cryptographically bound")
    response = value["response"]
    _exact(response, {"actions", "policy_timing", "server_timing"}, "forward response")
    if len(response["actions"]) != 15 or any(not isinstance(row, list) or len(row) != 8 for row in response["actions"]):
        raise ProbeError("forward response public shape is invalid")
    return True


def evaluate_preflight(observations: dict[str, Any], *, source_receipt: dict[str, Any], forward_receipt: Any) -> dict[str, Any]:
    _validate_source_receipt(source_receipt)
    clean = {key: observations[key] for key in ("schema_version", "source_receipt_sha256", "host", "commands", "command_ancestry_sha256", "checkpoint") if key in observations}
    validate_observations(clean, source_receipt)
    executed = False if forward_receipt is None else _verify_forward_receipt(forward_receipt, source_receipt, clean["checkpoint"])
    finding = source_receipt["source_finding"]
    return {"schema_version": 2, "disposition": "ACTION_INTERFACE_ONLY" if executed else "NOT_RUN",
            "model_forward_pass": executed, "semantic_plan_produced": False,
            "transport_fixture_status": "WORKING_SYNTHETIC",
            "model_inference_status": "RUN" if executed else "NOT_RUN",
            "public_action_shape": finding["public_action_shape"],
            "policy_response_keys": finding["policy_response_keys"],
            "websocket_response_keys": finding["websocket_response_keys"],
            "interface_kind": finding["interface_kind"],
            "checkpoint_inventory_sha256": clean["checkpoint"]["inventory_sha256"],
            "source_closure_sha256": source_receipt["closure_sha256"]}


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _walk_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in dirnames + filenames:
            path = base / name
            if stat.S_ISLNK(path.lstat().st_mode):
                raise ProbeError(f"evidence contains symlink: {path.relative_to(root)}")
        paths.extend(base / name for name in filenames)
    return sorted(paths)


def _member(path: Path, root: Path) -> dict[str, Any]:
    return {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_bytes(path.read_bytes())}


def _manifest(root: Path, allowed: tuple[str, ...]) -> dict[str, Any]:
    return {"schema_version": 2, "members": [_member(root / name, root) for name in allowed]}


def rewrite_manifest_for_test(raw: Path) -> None:
    """Test helper: model an attacker coherently rehashing a modified raw member."""
    _write(raw / "raw-manifest.json", canonical_json(_manifest(raw, RAW_MEMBER_PATHS)))


def _validate_manifest(root: Path, name: str, allowed: tuple[str, ...]) -> None:
    manifest_path = root / name
    try:
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProbeError(f"{name} manifest is invalid") from exc
    _exact(manifest, {"schema_version", "members"}, name)
    if manifest != _manifest(root, allowed):
        raise ProbeError(f"{name} manifest does not match immutable members")


def _validate_raw_schema(raw: Path) -> None:
    actual = {path.relative_to(raw).as_posix() for path in _walk_files(raw)}
    expected = set(RAW_MEMBER_PATHS) | {"raw-manifest.json"}
    if actual != expected:
        raise ProbeError("raw recursive schema is not exact")
    _validate_manifest(raw, "raw-manifest.json", RAW_MEMBER_PATHS)


def _render_derived(raw: Path, destination: Path) -> None:
    source = json.loads((raw / "source-receipt.json").read_text(encoding="ascii"))
    static = json.loads((raw / "source-static-receipts.json").read_text(encoding="ascii"))
    observations = json.loads((raw / "observations.json").read_text(encoding="ascii"))
    forward = json.loads((raw / "forward-receipt.json").read_text(encoding="ascii"))
    _validate_source_receipt(source)
    if static != source["source_finding"] or static != _expected_static_receipts():
        raise ProbeError("source static receipt violates pinned blob-derived facts")
    summary = evaluate_preflight(observations, source_receipt=source, forward_receipt=forward)
    _write(destination / "summary.json", canonical_json(summary))
    table = (
        "stage,kind,status,output_shape,semantic_plan\n"
        "source_ast,pinned_static,COMPLETE,15x8,false\n"
        "transport_fixture,synthetic,WORKING,15x8,false\n"
        f"checkpoint_forward,model,{summary['model_inference_status']},none,false\n"
    ).encode("ascii")
    _write(destination / "interface-table.csv", table)
    report = f"""# pi0.5 Semantic-Interface Feasibility V2

Disposition: **{summary['disposition']}**. Model inference: **{summary['model_inference_status']}**.

Pinned source receipts independently derive a 15 x 32 internal model action array followed by the DROID public output transform `[..., :8]`. The public policy response is therefore 15 x 8 `actions` plus `policy_timing`; `server_timing` is added only by the websocket server. `state` is not in the public DROID response.

The transport/interface fixture is synthetic and working. It proves serialization shape only. No model forward pass was run, no checkpoint bytes were downloaded, and no physical execution occurred. No semantic decoder, text output, or semantic plan output exists in the inspected public response closure; no semantic plan was produced.

V1 is retained byte-for-byte but rejected and superseded because it conflated the internal 15 x 32 model shape with the transformed public interface, retained unsafe receipt material, and did not close replay against coherent rehashing.
""".encode("ascii")
    _write(destination / "RESULTS.md", report)
    _write(destination / "derived-manifest.json", canonical_json(_manifest(destination, DERIVED_MEMBER_PATHS)))


def reconstruct_v2(raw: Path, destination: Path) -> None:
    _validate_raw_schema(raw)
    if destination.exists():
        raise ProbeError("derived destination is create-only")
    destination.mkdir(parents=True)
    _render_derived(raw, destination)


def _tree_sha(root: Path) -> str:
    rows = [_member(path, root) for path in _walk_files(root)]
    return sha256_json(rows)


def publish_probe_v2(output: Path, *, source_root: Path, source_receipt: dict[str, Any],
                     observations: dict[str, Any], forward_receipt: Any) -> None:
    if output.exists():
        raise ProbeError("probe output is create-only")
    live = inspect_official_source(source_root, expected_commit=PINNED_OPENPI_COMMIT)
    if live != source_receipt:
        raise ProbeError("source receipt does not match live pinned source")
    _validate_source_receipt(source_receipt)
    validate_observations(observations, source_receipt)
    raw = output / "raw"
    _write(raw / "source-receipt.json", canonical_json(source_receipt))
    _write(raw / "source-static-receipts.json", canonical_json(source_receipt["source_finding"]))
    _write(raw / "observations.json", canonical_json(observations))
    _write(raw / "transport-fixture.json", canonical_json(synthetic_transport_fixture()))
    _write(raw / "forward-receipt.json", canonical_json(forward_receipt))
    _write(raw / "raw-manifest.json", canonical_json(_manifest(raw, RAW_MEMBER_PATHS)))
    reconstruct_v2(raw, output / "derived")
    v1 = Path(__file__).resolve().parents[1] / "results/pi05-semantic-interface-feasibility-v1"
    supersession = {"schema_version": 2, "disposition": "V1_REJECTED_SUPERSEDED_BY_V2",
                    "preserved_v1_tree_sha256": _tree_sha(v1),
                    "replacement": "results/pi05-semantic-interface-feasibility-v2"}
    _write(output / "SUPERSESSION.json", canonical_json(supersession))
    root_members = tuple(sorted(
        [f"raw/{name}" for name in RAW_MEMBER_PATHS + ("raw-manifest.json",)]
        + [f"derived/{name}" for name in DERIVED_MEMBER_PATHS + ("derived-manifest.json",)]
        + ["SUPERSESSION.json"]
    ))
    _write(output / "evidence-manifest.json", canonical_json(_manifest(output, root_members)))
    validate_published(output)


def validate_published(root: Path) -> None:
    files = {path.relative_to(root).as_posix() for path in _walk_files(root)}
    expected = (set(f"raw/{name}" for name in RAW_MEMBER_PATHS + ("raw-manifest.json",))
                | set(f"derived/{name}" for name in DERIVED_MEMBER_PATHS + ("derived-manifest.json",))
                | {"SUPERSESSION.json", "evidence-manifest.json"})
    if files != expected:
        raise ProbeError("published recursive schema is not exact")
    _validate_raw_schema(root / "raw")
    derived_actual = {path.relative_to(root / "derived").as_posix() for path in _walk_files(root / "derived")}
    if derived_actual != set(DERIVED_MEMBER_PATHS) | {"derived-manifest.json"}:
        raise ProbeError("derived recursive schema is not exact")
    _validate_manifest(root / "derived", "derived-manifest.json", DERIVED_MEMBER_PATHS)
    root_allowed = tuple(sorted(files - {"evidence-manifest.json"}))
    _validate_manifest(root, "evidence-manifest.json", root_allowed)
