from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
import yaml


gate = importlib.import_module("experiments.01_policy_control.src.p3_gate")
runner = importlib.import_module("experiments.01_policy_control.run")


def _fixture(root: Path) -> Path:
    paths = gate.REQUIRED_PATHS
    files = {}
    for key, relative in paths.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if key == "run_manifest":
            body = {"stages": {"p1": "complete", "p2": "complete", "p3": "complete", "p4": "in_progress"}, "safety": {"physical_deployment_allowed": False, "remote_enabled": False}}
            path.write_text(yaml.safe_dump(body), encoding="utf-8")
        elif key == "mujoco_smoke":
            path.write_text(json.dumps({"status": "PASS", "runtime_subject": "package", "package": "mujoco", "version": "3.3.5", "artifact_sha256": "a" * 64}), encoding="utf-8")
        else:
            path.write_text(f"fixture:{key}\n", encoding="utf-8")
        files[key] = gate.EvidenceFile(Path(relative), gate.sha256_file(path))
    evidence = gate.P3GateEvidence(files=files, mujoco_package="mujoco", mujoco_version="3.3.5", mujoco_artifact_sha256="a" * 64)
    destination = root / "gate.yaml"
    gate.dump_p3_gate(evidence, destination)
    return destination


def test_remote_fails_before_import_or_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFLECT_REMOTE_ENABLED", "1")
    output = tmp_path / "output"
    assert runner.main(["--config", "missing", "--p3-gate", "missing", "--phase", "pilot", "--output-dir", str(output), "--headless", "--dry-run"]) == 2
    assert not output.exists()


def test_tampered_source_map_fails(tmp_path: Path) -> None:
    evidence_path = _fixture(tmp_path)
    evidence = gate.load_p3_gate(evidence_path)
    gate.require_p3_gate(tmp_path, evidence)
    (tmp_path / gate.REQUIRED_PATHS["source_map"]).write_text("tamper", encoding="utf-8")
    with pytest.raises(gate.P3GateError, match="source_map hash mismatch"):
        gate.require_p3_gate(tmp_path, evidence)
