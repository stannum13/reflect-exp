from __future__ import annotations

from importlib import metadata


def test_locked_runtime_has_mujoco_3x() -> None:
    version = metadata.version("mujoco")
    major, minor, *_ = (int(part) for part in version.split("."))
    assert major == 3
    assert minor >= 3
