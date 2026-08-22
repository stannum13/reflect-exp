"""One-step, headless MuJoCo package compatibility smoke."""

from __future__ import annotations

from importlib import metadata
import hashlib
import platform
from pathlib import Path
import time

import mujoco
import numpy as np

from reflect.source_compat import (
    CompatibilityEvidence,
    OperationManifest,
    source_lock_sha256,
)
from reflect.source_evidence import ensure_evidence_target_available
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


def _distribution_identity() -> tuple[str, str, int]:
    distribution = metadata.distribution("mujoco")
    version = distribution.version
    record = distribution.read_text("RECORD")
    if record is None:
        raise ValueError("installed MuJoCo distribution has no RECORD provenance")
    digest = hashlib.sha256(record.encode("utf-8")).hexdigest()
    disk_bytes = 0
    for item in distribution.files or ():
        path = distribution.locate_file(item)
        try:
            if path.is_file() and not path.is_symlink():
                disk_bytes += path.stat().st_size
        except OSError as exc:
            raise ValueError("installed MuJoCo distribution changed during hashing") from exc
    return version, digest, disk_bytes


def run_mujoco_smoke(registry: SourceRegistry, lock: SourceLock) -> SmokeEvidence:
    errors = validate_lock(registry, lock, require_complete=True)
    if errors:
        raise ValueError(f"MuJoCo smoke requires complete P2 lock: {errors[0]}")
    sources = {item.name: item for item in registry.repositories}
    locked = {item.name: item for item in lock.entries}
    source = sources["mujoco"]
    pin = locked["mujoco"]
    version, artifact_sha256, disk_bytes = _distribution_identity()
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
    return CompatibilityEvidence.create(
        registry_sha256=registry.registry_sha256,
        repository="mujoco",
        commit_sha=pin.commit_sha,
        experiment=source.experiments[0],
        selected_path=source.selected_paths[0],
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
        patch_artifact_sha256=None,
        findings={
            "duration_ns": duration_ns,
            "finite_qpos": finite_qpos,
            "finite_qvel": finite_qvel,
            "finite_time": finite_time,
            "simulation_time": float(data.time),
        },
        content_hashes={"inline-model.xml": hashlib.sha256(_XML.encode()).hexdigest()},
    )


def write_mujoco_smoke(
    manifest: OperationManifest,
    registry: SourceRegistry,
    lock: SourceLock,
    project_root: Path,
) -> Path:
    selector = manifest.mujoco_smoke_output
    if (
        manifest.registry_sha256 != registry.registry_sha256
        or manifest.lock_sha256 != source_lock_sha256(lock)
        or selector.operation_id != "MUJOCO_PACKAGE_SMOKE"
        or selector.relative_path != _OUTPUT
    ):
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
    evidence = run_mujoco_smoke(registry, lock)
    write_fragment_create_only(destination, evidence)
    return destination
