"""Fail-closed feasibility probe for the official OpenPI pi0.5 interface."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any


PINNED_OPENPI_COMMIT = "15a9616a00943ada6c20a0f158e3adb39df2ccac"
CHECKPOINT_URI = "gs://openpi-assets/checkpoints/pi05_droid"
SEMANTIC_FIELDS = frozenset(
    {"object_id", "affordance", "destination_region", "subgoals", "constraints", "reason_codes", "confidence"}
)
SOURCE_FILES = (
    "README.md",
    "pyproject.toml",
    "src/openpi/models/pi0.py",
    "src/openpi/models/pi0_config.py",
    "src/openpi/policies/policy.py",
    "src/openpi/policies/policy_config.py",
    "src/openpi/serving/websocket_policy_server.py",
    "src/openpi/training/config.py",
    "packages/openpi-client/src/openpi_client/base_policy.py",
    "packages/openpi-client/src/openpi_client/websocket_client_policy.py",
    "scripts/serve_policy.py",
    "examples/simple_client/main.py",
)


class ProbeError(RuntimeError):
    """Evidence or source binding is invalid."""


def _canonical(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Public hash helper used by evidence tests and collectors."""
    return _sha(data)


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def command_receipt(
    argv: list[str], *, exit_code: int, stdout: str, stderr: str,
) -> dict[str, Any]:
    return {
        "argv": argv,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_sha256": _sha(stdout.encode("utf-8")),
        "stderr_sha256": _sha(stderr.encode("utf-8")),
    }


def sanitize_hardware_profile(payload: dict[str, Any]) -> dict[str, str]:
    rows = payload.get("SPHardwareDataType")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ProbeError("hardware profile schema is invalid")
    row = rows[0]
    required = {"chip_type", "physical_memory", "machine_model", "number_processors"}
    if not required <= row.keys():
        raise ProbeError("hardware profile is incomplete")
    return {
        "chip": str(row["chip_type"]),
        "memory": str(row["physical_memory"]),
        "machine_model": str(row["machine_model"]),
        "processors": str(row["number_processors"]),
    }


def reduce_checkpoint_metadata(raw_json: str) -> dict[str, Any]:
    payload = json.loads(raw_json)
    if not isinstance(payload, list) or not payload:
        raise ProbeError("checkpoint metadata inventory is empty")
    objects = []
    for item in payload:
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
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
        objects.append(row)
    objects.sort(key=lambda row: row["name"])
    return {
        "object_count": len(objects),
        "total_bytes": sum(row["size"] for row in objects),
        "inventory_sha256": _sha(_canonical(objects)),
        "objects": objects,
    }


def _subprocess_runner(
    argv: list[str], extra_env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    environment = os.environ.copy()
    if extra_env:
        environment.update(extra_env)
    completed = subprocess.run(argv, text=True, capture_output=True, check=False, env=environment)
    return completed.returncode, completed.stdout, completed.stderr


def collect_observations(
    source_root: Path,
    *,
    python_executable: str,
    checkpoint_cache: Path,
    environ: dict[str, str],
    runner=_subprocess_runner,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    hardware_argv = ["system_profiler", "SPHardwareDataType", "-json"]
    runtime_argv = [
        "uv", "sync", "--project", str(source_root), "--python", python_executable,
        "--frozen", "--offline", "--dry-run",
    ]
    client_argv = [
        "uv", "sync", "--project", str(source_root / "packages/openpi-client"),
        "--python", python_executable, "--frozen", "--offline", "--dry-run",
    ]
    checkpoint_argv = [
        "gcloud", "storage", "ls", "--recursive", "--json", f"{CHECKPOINT_URI}/**",
    ]
    hardware_result = runner(hardware_argv)
    runtime_result = runner(
        runtime_argv,
        {"UV_PROJECT_ENVIRONMENT": "/private/tmp/pi05-openpi-runtime-dryrun-env"},
    )
    client_result = runner(
        client_argv,
        {"UV_PROJECT_ENVIRONMENT": "/private/tmp/pi05-openpi-client-dryrun-env"},
    )
    checkpoint_result = runner(checkpoint_argv)
    if hardware_result[0] != 0:
        raise ProbeError("hardware profile command failed")
    safe_hardware = sanitize_hardware_profile(json.loads(hardware_result[1]))
    safe_hardware_stdout = json.dumps(
        {"SPHardwareDataType": [safe_hardware]}, sort_keys=True, separators=(",", ":")
    ) + "\n"
    receipts = {
        "hardware": command_receipt(
            hardware_argv, exit_code=hardware_result[0], stdout=safe_hardware_stdout, stderr=hardware_result[2]
        ) | {"stdout_sanitized": True},
        "runtime_dry_run": command_receipt(
            runtime_argv, exit_code=runtime_result[0], stdout=runtime_result[1], stderr=runtime_result[2]
        ),
        "client_dry_run": command_receipt(
            client_argv, exit_code=client_result[0], stdout=client_result[1], stderr=client_result[2]
        ),
        "checkpoint_metadata": command_receipt(
            checkpoint_argv,
            exit_code=checkpoint_result[0], stdout=checkpoint_result[1], stderr=checkpoint_result[2],
        ),
    }
    if checkpoint_result[0] != 0:
        raise ProbeError("checkpoint metadata command failed")
    checkpoint = reduce_checkpoint_metadata(checkpoint_result[1]) | {
        "uri": CHECKPOINT_URI,
        "downloaded": checkpoint_cache.is_dir(),
    }
    host = safe_hardware | {
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    modules = {
        name: importlib.util.find_spec(name) is not None
        for name in ("flax", "jax", "msgpack", "numpy", "torch", "tyro", "websockets")
    }
    remote_configured = bool(environ.get("OPENPI_REMOTE_HOST") and environ.get("OPENPI_REMOTE_PORT"))
    remote_authenticated = bool(remote_configured and environ.get("OPENPI_API_KEY"))
    return {
        "schema_version": 1,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source_root, text=True
        ).strip(),
        "host": host,
        "modules": modules,
        "tools": {name: shutil.which(name) for name in ("gcloud", "gsutil", "nvcc", "nvidia-smi")},
        "runtime": receipts["runtime_dry_run"] | {
            "cuda_available": bool(shutil.which("nvidia-smi") and shutil.which("nvcc")),
        },
        "client": receipts["client_dry_run"],
        "checkpoint": checkpoint,
        "remote": {"configured": remote_configured, "authenticated": remote_authenticated},
        "commands": receipts,
        "collector_python": sys.executable,
    }


def _literal_dict_keys(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.Dict):
        return []
    return sorted(key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str))


def _policy_output_keys(policy_tree: ast.Module) -> list[str]:
    for node in ast.walk(policy_tree):
        if isinstance(node, ast.FunctionDef) and node.name == "infer":
            for child in ast.walk(node):
                if isinstance(child, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "outputs" for target in child.targets
                ):
                    keys = _literal_dict_keys(child.value)
                    if keys:
                        return sorted(keys + ["policy_timing"])
    raise ProbeError("official Policy.infer output dictionary was not found")


def _pi05_droid_shape(config_tree: ast.Module) -> list[int]:
    for node in ast.walk(config_tree):
        if not isinstance(node, ast.Call):
            continue
        name = next(
            (
                kw.value.value
                for kw in node.keywords
                if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)
            ),
            None,
        )
        if name != "pi05_droid":
            continue
        model = next((kw.value for kw in node.keywords if kw.arg == "model"), None)
        if not isinstance(model, ast.Call):
            break
        values = {
            kw.arg: kw.value.value
            for kw in model.keywords
            if kw.arg in {"action_dim", "action_horizon"} and isinstance(kw.value, ast.Constant)
        }
        pi05 = next((kw.value.value for kw in model.keywords if kw.arg == "pi05"), False)
        if pi05 is not True:
            break
        return [int(values.get("action_horizon", 50)), int(values.get("action_dim", 32))]
    raise ProbeError("official pi05_droid action shape was not found")


def inspect_official_source(source_root: Path, *, expected_commit: str) -> dict[str, Any]:
    source_root = source_root.resolve()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source_root, text=True).strip()
    if commit != expected_commit:
        raise ProbeError(f"OpenPI commit mismatch: expected {expected_commit}, got {commit}")
    missing = [name for name in SOURCE_FILES if not (source_root / name).is_file()]
    if missing:
        raise ProbeError(f"official source closure is incomplete: {missing}")

    policy_tree = ast.parse((source_root / "src/openpi/policies/policy.py").read_text(encoding="utf-8"))
    model_tree = ast.parse((source_root / "src/openpi/models/pi0.py").read_text(encoding="utf-8"))
    config_tree = ast.parse((source_root / "src/openpi/training/config.py").read_text(encoding="utf-8"))
    model_config_tree = ast.parse((source_root / "src/openpi/models/pi0_config.py").read_text(encoding="utf-8"))

    sample = next(
        node for node in ast.walk(model_tree) if isinstance(node, ast.FunctionDef) and node.name == "sample_actions"
    )
    sample_calls = {
        ast.unparse(node.func) for node in ast.walk(sample) if isinstance(node, ast.Call)
    }
    if "jax.lax.while_loop" not in sample_calls:
        raise ProbeError("pi0.5 flow-matching action sampler was not found")
    config_text = ast.unparse(model_config_tree)
    if "ModelType.PI05" not in config_text:
        raise ProbeError("pi0.5 model type binding was not found")

    output_keys = _policy_output_keys(policy_tree)
    semantic_output_fields = sorted(SEMANTIC_FIELDS.intersection(output_keys))
    return {
        "schema_version": 1,
        "source_commit": commit,
        "expected_commit": expected_commit,
        "source_files_sha256": {name: _file_sha(source_root / name) for name in SOURCE_FILES},
        "model_type": "PI05_FLOW_MATCHING",
        "sampler": "jax.lax.while_loop",
        "policy_output_keys": output_keys,
        "action_shapes": {"pi05_base": [50, 32], "pi05_droid": _pi05_droid_shape(config_tree)},
        "semantic_output_fields": semantic_output_fields,
        "semantic_decoder_present": bool(semantic_output_fields),
        "interface_kind": "SEMANTIC_TEXT" if semantic_output_fields else "ACTION_CHUNK_ONLY",
        "checkpoint_uri": CHECKPOINT_URI,
    }


def run_official_base_policy_smoke(source_root: Path) -> dict[str, Any]:
    path = source_root / "packages/openpi-client/src/openpi_client/base_policy.py"
    spec = importlib.util.spec_from_file_location("pi05_probe_official_base_policy", path)
    if spec is None or spec.loader is None:
        raise ProbeError("official BasePolicy module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class TransportFixture(module.BasePolicy):
        def infer(self, obs: dict[str, Any]) -> dict[str, Any]:
            if sorted(obs) != ["images", "prompt", "state"]:
                raise ProbeError("official smoke observation shape changed")
            return {"actions": [[0.0] * 32 for _ in range(15)]}

    output = TransportFixture().infer({"images": {}, "prompt": "probe only", "state": [0.0] * 8})
    return {
        "schema_version": 1,
        "official_code_executed": True,
        "official_source_sha256": _file_sha(path),
        "api_method": "BasePolicy.infer",
        "output_keys": sorted(output),
        "output_shape": [len(output["actions"]), len(output["actions"][0])],
        "output_sha256": _sha(_canonical(output)),
        "sample_origin": "DETERMINISTIC_TRANSPORT_FIXTURE",
        "checkpoint_forward_pass": False,
        "scientific_disposition": "NONWORKING_SEMANTIC_INTERFACE_SAMPLE",
    }


def classify_response(response: dict[str, Any], *, checkpoint_forward_pass: bool) -> dict[str, Any]:
    if "actions" in response:
        return {
            "interface_kind": "ACTION_CHUNK_ONLY",
            "semantic_plan": None,
            "actions_discarded": True,
            "discarded_actions_sha256": _sha(_canonical(response["actions"])),
            "checkpoint_forward_pass": checkpoint_forward_pass,
        }
    return {
        "interface_kind": "UNAUTHENTICATED_NON_OFFICIAL_RESPONSE",
        "semantic_plan": None,
        "actions_discarded": False,
        "discarded_actions_sha256": None,
        "checkpoint_forward_pass": checkpoint_forward_pass,
    }


def evaluate_preflight(observations: dict[str, Any]) -> dict[str, Any]:
    runtime = observations["runtime"]
    checkpoint = observations["checkpoint"]
    remote = observations["remote"]
    forward = observations.get("forward_receipt", {})
    local_supported = bool(
        runtime.get("exit_code") == 0 and checkpoint.get("downloaded") and forward.get("verified")
    )
    remote_supported = bool(remote.get("configured") and remote.get("authenticated") and forward.get("verified"))
    verified_forward = bool(forward.get("verified") and (local_supported or remote_supported))
    blockers: list[str] = []
    if not local_supported:
        blockers.append("LOCAL_RUNTIME_PLATFORM_UNSUPPORTED")
    if not remote_supported:
        blockers.append("NO_AUTHENTICATED_REMOTE_BACKEND")
    if not verified_forward:
        blockers.append("NO_CHECKPOINT_FORWARD_PASS")
    blockers.append("OFFICIAL_INTERFACE_ACTION_CHUNKS_ONLY")
    return {
        "schema_version": 1,
        "disposition": "NOT_RUN_NO_CHECKPOINT_BACKEND",
        "checkpoint_forward_pass": verified_forward,
        "local_runtime_supported": local_supported,
        "remote_runtime_supported": remote_supported,
        "semantic_interface_supported": False,
        "blockers": blockers,
        "inference_boundary": "SOURCE_AND_TRANSPORT_PREFLIGHT_ONLY",
    }


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _inventory(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": _file_sha(path)}
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "raw-manifest.json"
    ]


def _render_derived(raw: Path, destination: Path) -> None:
    source = json.loads((raw / "source-finding.json").read_text(encoding="ascii"))
    observations = json.loads((raw / "observations.json").read_text(encoding="ascii"))
    smoke = json.loads((raw / "api-smoke.json").read_text(encoding="ascii"))
    summary = evaluate_preflight(observations) | {
        "openpi_commit": source["source_commit"],
        "checkpoint_uri": observations["checkpoint"]["uri"],
        "checkpoint_bytes": observations["checkpoint"]["total_bytes"],
        "checkpoint_objects": observations["checkpoint"]["object_count"],
        "checkpoint_inventory_sha256": observations["checkpoint"]["inventory_sha256"],
        "official_api_smoke": smoke["scientific_disposition"],
        "official_interface_kind": source["interface_kind"],
        "actions_cross_semantic_boundary": False,
    }
    _write(destination / "summary.json", _canonical(summary))
    table = (
        "stage,executed,checkpoint_backed,output,semantic_plan,disposition\n"
        "source_ast,true,false,action_chunk_shape,false,COMPLETE\n"
        "official_base_policy,true,false,fixture_action_chunk,false,TRANSPORT_ONLY\n"
        "local_pi05_forward,false,false,none,false,NOT_RUN_PLATFORM\n"
        "remote_pi05_forward,false,false,none,false,NOT_RUN_NO_AUTH_BACKEND\n"
    ).encode("ascii")
    _write(destination / "interface-table.csv", table)
    svg = b'''<svg xmlns="http://www.w3.org/2000/svg" width="760" height="170" viewBox="0 0 760 170">
<rect width="760" height="170" fill="white"/><g font-family="monospace" font-size="13">
<rect x="20" y="55" width="150" height="55" fill="#d9edf7" stroke="#31708f"/><text x="32" y="80">image+prompt+state</text>
<path d="M170 82H240" stroke="#333" marker-end="url(#a)"/><rect x="240" y="55" width="130" height="55" fill="#fcf8e3" stroke="#8a6d3b"/><text x="267" y="80">pi0.5 flow</text><text x="265" y="98">NOT RUN</text>
<path d="M370 82H440" stroke="#333" marker-end="url(#a)"/><rect x="440" y="55" width="130" height="55" fill="#f2dede" stroke="#a94442"/><text x="461" y="80">15x32 actions</text><text x="466" y="98">only output</text>
<path d="M570 82H640" stroke="#a94442" stroke-dasharray="5 4"/><text x="642" y="75">semantic</text><text x="642" y="94">boundary</text><text x="642" y="113">CLOSED</text>
<defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8z"/></marker></defs>
<text x="20" y="145">Measured: official source/API path. Not measured: checkpoint-backed forward pass.</text></g></svg>\n'''
    _write(destination / "interface-flow.svg", svg)
    report = f"""# pi0.5 Semantic-Interface Feasibility Result

Disposition: **{summary['disposition']}**

Pinned OpenPI `{source['source_commit']}` exposes a flow-matching action sampler. Its public policy and websocket path return action chunks, state, and timing; they expose no semantic token/text plan field or semantic decoder. The DROID configuration returns a 15 x 32 action chunk.

The official BasePolicy source executed locally with a deterministic transport fixture, proving the callable API boundary only. It was not checkpoint inference. The full frozen runtime dry-run failed because `jax-cuda12-plugin==0.5.3` has no macOS arm64 wheel. No checkpoint was downloaded. Metadata identifies {observations['checkpoint']['object_count']} objects totaling {observations['checkpoint']['total_bytes']} bytes. No authenticated remote backend was configured.

Inference boundary: source inspection, official base-policy invocation, dependency resolution, and checkpoint metadata only. No model forward pass, semantic plan, motion plan, controller action, or scientific outcome was produced.

Next executable route: run this exact pinned source and checkpoint on a supported NVIDIA Linux host, or configure an authenticated OpenPI websocket server that supplies immutable checkpoint identity and a forward-pass receipt. Even then, Exp09 needs a separately specified semantic decoder/interface because the official endpoint itself returns actions only.
""".encode("ascii")
    _write(destination / "RESULTS.md", report)
    members = [
        {"path": path.name, "bytes": path.stat().st_size, "sha256": _file_sha(path)}
        for path in sorted(destination.iterdir()) if path.is_file()
    ]
    _write(destination / "derived-manifest.json", _canonical({"schema_version": 1, "members": members}))


def publish_probe(
    output: Path,
    *,
    source_finding: dict[str, Any],
    observations: dict[str, Any],
    api_smoke: dict[str, Any],
) -> None:
    if output.exists():
        raise ProbeError("probe output is create-only")
    raw = output / "raw"
    _write(raw / "source-finding.json", _canonical(source_finding))
    _write(raw / "observations.json", _canonical(observations))
    _write(raw / "api-smoke.json", _canonical(api_smoke))
    action_sample = {"kind": "WORKING_TRANSPORT_ONLY", "actions": [[0.0] * 32 for _ in range(15)]}
    semantic_sample = {
        "kind": "NONWORKING_UNAUTHENTICATED_SEMANTIC",
        "response": {"object_id": "cup_17", "affordance": "side_grasp", "subgoals": ["approach", "grasp"]},
    }
    _write(raw / "samples" / "working-action-transport.json", _canonical(action_sample))
    _write(raw / "samples" / "nonworking-semantic-response.json", _canonical(semantic_sample))
    _write(raw / "raw-manifest.json", _canonical({"schema_version": 1, "members": _inventory(raw)}))
    reconstruct(raw, output / "derived")


def reconstruct(raw: Path, destination: Path) -> None:
    manifest_path = raw / "raw-manifest.json"
    if not manifest_path.is_file():
        raise ProbeError("raw manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    if manifest != {"schema_version": 1, "members": _inventory(raw)}:
        raise ProbeError("raw manifest does not match immutable members")
    if destination.exists():
        raise ProbeError("derived destination is create-only")
    destination.mkdir(parents=True)
    _render_derived(raw, destination)
