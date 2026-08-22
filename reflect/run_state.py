"""Validated durable state for the autonomous research program."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml


class ManifestError(ValueError):
    """Raised when durable run state violates the approved design."""


@dataclass(frozen=True)
class RunManifest:
    scope: str
    current_pass: int
    max_passes: int
    cpu_hours_max: int
    physical_deployment_allowed: bool
    remote_enabled: bool
    stages: Mapping[str, str]


def load_run_manifest(path: Path) -> RunManifest:
    raw = yaml.safe_load(path.read_text())
    manifest = RunManifest(
        scope=str(raw["scope"]),
        current_pass=int(raw["current_pass"]),
        max_passes=int(raw["max_passes"]),
        cpu_hours_max=int(raw["budgets"]["cpu_hours_max"]),
        physical_deployment_allowed=bool(
            raw["safety"]["physical_deployment_allowed"]
        ),
        remote_enabled=bool(raw["safety"]["remote_enabled"]),
        stages=dict(raw["stages"]),
    )
    if manifest.scope not in {"recommended", "p0-p10-only"}:
        raise ManifestError("scope is not recognized")
    if not 0 <= manifest.current_pass <= manifest.max_passes:
        raise ManifestError("current_pass exceeds the approved pass ceiling")
    if manifest.max_passes != 16 or manifest.cpu_hours_max != 240:
        raise ManifestError("global autonomy ceilings differ from the approved design")
    if manifest.physical_deployment_allowed:
        raise ManifestError("physical deployment must remain disabled")
    allowed_states = {"pending", "in_progress", "complete", "blocked", "stopped"}
    if not manifest.stages or set(manifest.stages.values()) - allowed_states:
        raise ManifestError("stage state is missing or invalid")
    return manifest
