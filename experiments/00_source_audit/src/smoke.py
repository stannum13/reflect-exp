"""One-step, headless MuJoCo package compatibility smoke."""

from __future__ import annotations

import base64
import csv
from importlib import metadata
import hashlib
import importlib.machinery
import io
import platform
from pathlib import Path
import sys
import time
import tomllib
from urllib.parse import urlparse

import mujoco
import numpy as np

from reflect.source_compat import (
    CompatibilityEvidence,
    load_operation_manifest,
    validate_fragment,
)
from reflect.source_evidence import canonical_sha256, ensure_evidence_target_available
from reflect.source_ops import write_fragment_create_only
from reflect.sources import SourceLock, SourceRegistry, validate_lock


SmokeEvidence = CompatibilityEvidence
_OUTPUT = "experiments/00_source_audit/results/fragments/mujoco-package-smoke.json"
_XML = """<mujoco>
  <option timestep="0.002"/>
  <worldbody>
    <geom name="floor" type="plane" size="1 1 .01"/>
    <body name="pendulum" pos="0 0 .3">
      <joint name="hinge" type="hinge" axis="0 1 0"/>
      <geom type="capsule" size=".02 .1" pos="0 0 -.1"/>
    </body>
    <body name="free_body" pos=".2 0 .2">
      <freejoint/>
      <geom type="sphere" size=".03"/>
    </body>
  </worldbody>
  <actuator><motor joint="hinge" gear="1"/></actuator>
</mujoco>"""


def _locked_wheel_identity(lock_path: Path) -> tuple[str, str]:
    raw = tomllib.loads(lock_path.read_text())
    packages = [item for item in raw.get("package", []) if item.get("name") == "mujoco"]
    if len(packages) != 1 or packages[0].get("version") != "3.12.0":
        raise ValueError("uv.lock must contain exactly MuJoCo 3.12.0")
    python_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    machine = platform.machine().lower()
    system = platform.system().lower()
    if system == "darwin":
        platform_tokens = ("macosx", "arm64" if machine in {"arm64", "aarch64"} else "x86_64")
    elif system == "linux":
        platform_tokens = ("manylinux", "aarch64" if machine in {"arm64", "aarch64"} else "x86_64")
    elif system == "windows":
        platform_tokens = ("win", "amd64" if machine in {"amd64", "x86_64"} else machine)
    else:
        raise ValueError("current platform has no audited MuJoCo wheel selector")
    matches = []
    for wheel in packages[0].get("wheels", []):
        filename = Path(urlparse(wheel["url"]).path).name
        if python_tag in filename and all(token in filename for token in platform_tokens):
            matches.append((filename, wheel["hash"]))
    if len(matches) != 1 or not matches[0][1].startswith("sha256:"):
        raise ValueError("uv.lock has no unique current-platform MuJoCo wheel")
    digest = matches[0][1].removeprefix("sha256:")
    if len(digest) != 64:
        raise ValueError("uv.lock MuJoCo wheel hash is invalid")
    return matches[0][0], digest


def _distribution_identity(lock_path: Path) -> tuple[str, str, str, int, int, str, dict[Path, tuple[str, str]]]:
    distribution = metadata.distribution("mujoco")
    version = distribution.version
    if version != "3.12.0":
        raise ValueError("installed MuJoCo version is not the audited 3.12.0")
    wheel_filename, lock_artifact_sha256 = _locked_wheel_identity(lock_path)
    record = distribution.read_text("RECORD")
    if record is None:
        raise ValueError("installed MuJoCo distribution has no RECORD provenance")
    rows = tuple(csv.reader(io.StringIO(record)))
    if not rows or any(len(row) != 3 or not row[0] for row in rows):
        raise ValueError("installed MuJoCo RECORD schema is invalid")
    record_paths = tuple(row[0] for row in rows)
    if len(set(record_paths)) != len(record_paths):
        raise ValueError("installed MuJoCo RECORD contains duplicate paths")
    inventory = tuple(str(item) for item in distribution.files or ())
    if sorted(inventory) != sorted(record_paths):
        raise ValueError("installed MuJoCo RECORD is not the complete distribution inventory")
    disk_bytes = 0
    tree_rows = []
    installed_inventory: dict[Path, tuple[str, str]] = {}
    for relative, encoded_hash, encoded_size in rows:
        path = distribution.locate_file(relative)
        try:
            before = path.lstat()
            if path.is_symlink() or not path.is_file():
                raise ValueError("installed MuJoCo inventory contains a nonregular file")
            data = path.read_bytes()
            after = path.stat()
        except OSError as exc:
            raise ValueError("installed MuJoCo distribution changed during hashing") from exc
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or len(data) != after.st_size:
            raise ValueError("installed MuJoCo file changed during hashing")
        digest_bytes = hashlib.sha256(data).digest()
        digest = digest_bytes.hex()
        is_record = relative.endswith(".dist-info/RECORD")
        if not is_record:
            expected_hash = "sha256=" + base64.urlsafe_b64encode(digest_bytes).decode().rstrip("=")
            if encoded_hash != expected_hash or encoded_size != str(len(data)):
                raise ValueError("installed MuJoCo file does not match RECORD")
        elif encoded_hash or encoded_size:
            raise ValueError("installed MuJoCo RECORD self-entry must be unhashed")
        disk_bytes += len(data)
        tree_rows.append({"path": relative, "sha256": digest, "size": len(data)})
        installed_inventory[path.resolve(strict=True)] = (relative, digest)
    return (
        version,
        canonical_sha256(sorted(tree_rows, key=lambda item: item["path"])),
        lock_artifact_sha256,
        disk_bytes,
        len(tree_rows),
        wheel_filename,
        installed_inventory,
    )


def _executed_origins(installed_inventory: dict[Path, tuple[str, str]]) -> list[dict[str, object]]:
    rows = []
    for name, module in sorted(sys.modules.items()):
        if name != "mujoco" and not name.startswith("mujoco."):
            continue
        origin = getattr(module, "__file__", None)
        if origin is None:
            continue
        path = Path(origin).resolve(strict=True)
        identity = installed_inventory.get(path)
        if identity is None:
            raise ValueError("executed MuJoCo module is outside the verified RECORD inventory")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != identity[1]:
            raise ValueError("executed MuJoCo module changed after RECORD verification")
        rows.append({
            "module": name, "record_path": identity[0], "sha256": digest,
            "native_extension": any(str(path).endswith(suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES),
        })
    names = {row["module"] for row in rows}
    if not {"mujoco", "mujoco._functions", "mujoco._structs"}.issubset(names):
        raise ValueError("executed MuJoCo core module origins are incomplete")
    return rows


def run_mujoco_smoke(
    registry: SourceRegistry,
    lock: SourceLock,
    uv_lock_path: Path | None = None,
) -> SmokeEvidence:
    errors = validate_lock(registry, lock, require_complete=True)
    if errors:
        raise ValueError(f"MuJoCo smoke requires complete P2 lock: {errors[0]}")
    sources = {item.name: item for item in registry.repositories}
    locked = {item.name: item for item in lock.entries}
    source = sources["mujoco"]
    pin = locked["mujoco"]
    version, artifact_sha256, lock_artifact_sha256, disk_bytes, installed_files, wheel_filename, installed_inventory = _distribution_identity(
        uv_lock_path or Path(__file__).resolve().parents[3] / "uv.lock"
    )
    started = time.perf_counter_ns()
    model = mujoco.MjModel.from_xml_string(_XML)
    data = mujoco.MjData(model)
    data.ctrl[0] = 0.125
    mujoco.mj_step(model, data)
    duration_ns = time.perf_counter_ns() - started
    finite_time = bool(np.isfinite(data.time))
    finite_qpos = bool(np.isfinite(data.qpos).all())
    finite_qvel = bool(np.isfinite(data.qvel).all())
    if not (data.time > 0 and finite_time and finite_qpos and finite_qvel):
        raise ValueError("MuJoCo one-step state is not finite and advanced")
    if data.time != model.opt.timestep or data.qpos[0] == 0 or data.qvel[0] == 0:
        raise ValueError("MuJoCo one-step actuated hinge predicate failed")
    executed_origins = _executed_origins(installed_inventory)
    xml_sha256 = hashlib.sha256(_XML.encode()).hexdigest()
    qpos = [float(value).hex() for value in data.qpos]
    qvel = [float(value).hex() for value in data.qvel]
    return CompatibilityEvidence.create(
        registry_sha256=registry.registry_sha256,
        repository="mujoco",
        commit_sha=pin.commit_sha,
        experiment=source.experiments[0],
        selected_path=source.selected_paths[0],
        operation_id="MUJOCO_PACKAGE_SMOKE",
        operation="PACKAGE_RUNTIME",
        platform=f"{platform.system().lower()}-{platform.machine().lower()}",
        python_requirement=">=3.11,<3.12",
        compiler_or_runtime=f"mujoco-{version};python-{platform.python_version()}",
        command=("mujoco", "headless-one-step"),
        exit_status=0,
        disk_bytes=disk_bytes,
        download_bytes=0,
        license_status=pin.license_status.value,
        license_spdx=pin.license_spdx,
        blocker=None,
        notes="published package smoke; P2 Git SHA retained only as registry provenance",
        runtime_subject="package",
        package_name="mujoco",
        package_version=version,
        package_artifact_sha256=artifact_sha256,
        package_lock_artifact_sha256=lock_artifact_sha256,
        patch_artifact_sha256=None,
        findings={
            "duration_ns": duration_ns,
            "artifact": {
                "wheel_filename": wheel_filename,
                "lock_artifact_sha256": lock_artifact_sha256,
                "installed_tree_sha256": artifact_sha256,
                "record_entries": installed_files,
                "installed_files": installed_files,
                "installed_bytes": disk_bytes,
                "executed_origins": executed_origins,
            },
            "dynamics": {
                "xml_sha256": xml_sha256,
                "control": [float(value).hex() for value in data.ctrl],
                "timestep": float(model.opt.timestep).hex(),
                "nq": model.nq, "nv": model.nv, "nu": model.nu,
                "post_step": {
                    "time": float(data.time).hex(), "qpos": qpos, "qvel": qvel,
                    "qpos_sha256": canonical_sha256(qpos),
                    "qvel_sha256": canonical_sha256(qvel),
                },
            },
        },
        content_hashes={"inline-model.xml": xml_sha256},
    )


def write_mujoco_smoke(
    manifest_path: Path,
    registry: SourceRegistry,
    lock: SourceLock,
    project_root: Path,
) -> Path:
    manifest = load_operation_manifest(manifest_path, registry, lock, project_root)
    selector = manifest.mujoco_smoke_output
    if selector.operation_id != "MUJOCO_PACKAGE_SMOKE" or selector.relative_path != _OUTPUT:
        raise ValueError("MuJoCo smoke selector or digest binding is invalid")
    matching = tuple(item for item in manifest.operations if item.operation_id == selector.operation_id)
    if (
        len(matching) != 1
        or matching[0].repository != "mujoco"
        or matching[0].operation != "PACKAGE_RUNTIME"
        or matching[0].runtime_subject != "package"
        or matching[0].relative_output != selector.relative_path
    ):
        raise ValueError("MuJoCo smoke selector has no exact package operation")
    destination = project_root / selector.relative_path
    ensure_evidence_target_available(destination)
    evidence = run_mujoco_smoke(registry, lock, project_root / "uv.lock")
    validate_fragment(evidence.to_dict(), registry, lock, manifest, selector.relative_path)
    write_fragment_create_only(destination, evidence)
    return destination
