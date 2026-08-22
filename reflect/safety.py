"""Fail-closed safety configuration for autonomous research runs."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import ipaddress
import json
import math
import os
from typing import Mapping, Sequence


class SafetyViolation(RuntimeError):
    """Raised when requested execution exceeds the simulation-only envelope."""


def _boolean(values: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = values.get(name, "1" if default else "0").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    raise SafetyViolation(f"{name} must be an explicit boolean")


def _positive_float(values: Mapping[str, str], name: str) -> float:
    try:
        result = float(values.get(name, "0"))
    except ValueError as exc:
        raise SafetyViolation(f"{name} must be numeric") from exc
    if result <= 0 or not math.isfinite(result):
        raise SafetyViolation(f"{name} must be positive and finite")
    return result


@dataclass(frozen=True)
class RemoteBudget:
    gpu_hours: float
    wall_hours: float
    download_gb: float
    artifact_gb: float


@dataclass(frozen=True)
class RemoteTarget:
    host: str
    workdir: str
    budget: RemoteBudget


@dataclass(frozen=True)
class SafetyConfig:
    physical_deployment_allowed: bool
    remote_enabled: bool
    values: Mapping[str, str]

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "SafetyConfig":
        copied = dict(values)
        return cls(
            physical_deployment_allowed=_boolean(
                copied, "PHYSICAL_DEPLOYMENT_ALLOWED", default=False
            ),
            remote_enabled=_boolean(copied, "REFLECT_REMOTE_ENABLED", default=False),
            values=copied,
        )

    def require_simulation_only(self) -> None:
        if self.physical_deployment_allowed:
            raise SafetyViolation("physical deployment is disabled for this program")

    def validate_bind_host(self, host: str) -> None:
        if host == "localhost":
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        raise SafetyViolation("experimental services must bind to loopback")

    def validated_remote_target(self) -> RemoteTarget | None:
        if not self.remote_enabled:
            return None
        host = self.values.get("REFLECT_REMOTE_HOST", "").strip()
        allowlist = {
            item.strip()
            for item in self.values.get("REFLECT_REMOTE_HOST_ALLOWLIST", "").split(",")
            if item.strip()
        }
        if not host or host not in allowlist:
            raise SafetyViolation("remote host must exactly match the explicit allowlist")
        workdir = self.values.get("REFLECT_REMOTE_WORKDIR", "").strip()
        if not workdir.startswith("/"):
            raise SafetyViolation("remote workdir must be an absolute explicit path")
        return RemoteTarget(
            host=host,
            workdir=workdir,
            budget=RemoteBudget(
                gpu_hours=_positive_float(self.values, "REFLECT_REMOTE_GPU_HOURS_MAX"),
                wall_hours=_positive_float(self.values, "REFLECT_REMOTE_WALL_HOURS_MAX"),
                download_gb=_positive_float(
                    self.values, "REFLECT_REMOTE_DOWNLOAD_GB_MAX"
                ),
                artifact_gb=_positive_float(
                    self.values, "REFLECT_REMOTE_ARTIFACT_GB_MAX"
                ),
            ),
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["check"])
    args = parser.parse_args(argv)
    config = SafetyConfig.from_mapping(os.environ)
    config.require_simulation_only()
    target = config.validated_remote_target()
    print(json.dumps({"simulation_only": True, "remote_enabled": target is not None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
