"""Validated durable state for the autonomous research program."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping
from typing import Any

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
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"could not read manifest: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ManifestError("manifest must be a YAML mapping")

    _require_type(raw, "scope", str)
    _require_type(raw, "current_pass", int)
    _require_type(raw, "max_passes", int)
    budgets = _require_mapping(raw, "budgets")
    _require_type(budgets, "cpu_hours_max", int)
    safety = _require_mapping(raw, "safety")
    _require_type(safety, "physical_deployment_allowed", bool)
    _require_type(safety, "remote_enabled", bool)
    stages = _require_mapping(raw, "stages")

    if safety["remote_enabled"] is not False:
        raise ManifestError("remote_enabled must remain false")
    if safety["physical_deployment_allowed"] is not False:
        raise ManifestError("physical_deployment_allowed must remain false")

    manifest = RunManifest(
        scope=raw["scope"],
        current_pass=raw["current_pass"],
        max_passes=raw["max_passes"],
        cpu_hours_max=budgets["cpu_hours_max"],
        physical_deployment_allowed=safety["physical_deployment_allowed"],
        remote_enabled=safety["remote_enabled"],
        stages=dict(stages),
    )
    if manifest.scope not in {"recommended", "p0-p10-only"}:
        raise ManifestError("scope is not recognized")
    if not 0 <= manifest.current_pass <= manifest.max_passes:
        raise ManifestError("current_pass exceeds the approved pass ceiling")
    if manifest.max_passes != 16 or manifest.cpu_hours_max != 240:
        raise ManifestError("global autonomy ceilings differ from the approved design")
    expected_stage_keys = {f"p{i}" for i in range(11)}
    if set(stages) != expected_stage_keys:
        raise ManifestError("stage keys must be exactly p0 through p10")
    for name, state in stages.items():
        if type(state) is not str:
            raise ManifestError(f"stage state {name} has wrong YAML type")
    allowed_states = {"pending", "in_progress", "complete", "blocked", "stopped"}
    if set(manifest.stages.values()) - allowed_states:
        raise ManifestError("stage state is invalid")
    return manifest


def _require_mapping(raw: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = raw.get(field)
    if not isinstance(value, Mapping):
        raise ManifestError(f"{field} must be a YAML mapping")
    return value


def _require_type(raw: Mapping[str, Any], field: str, expected: type) -> None:
    value = raw.get(field)
    if type(value) is not expected:
        raise ManifestError(f"{field} has wrong YAML type")
