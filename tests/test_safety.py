import pytest

from reflect.safety import RemoteBudget, SafetyConfig, SafetyViolation


def test_defaults_are_simulation_only_and_remote_disabled() -> None:
    config = SafetyConfig.from_mapping({})
    config.require_simulation_only()
    assert config.physical_deployment_allowed is False
    assert config.remote_enabled is False
    assert config.validated_remote_target() is None


def test_physical_deployment_is_rejected() -> None:
    config = SafetyConfig.from_mapping({"PHYSICAL_DEPLOYMENT_ALLOWED": "true"})
    with pytest.raises(SafetyViolation, match="physical deployment"):
        config.require_simulation_only()


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_bind_hosts_are_allowed(host: str) -> None:
    SafetyConfig.from_mapping({}).validate_bind_host(host)


def test_non_loopback_bind_host_is_rejected() -> None:
    with pytest.raises(SafetyViolation, match="loopback"):
        SafetyConfig.from_mapping({}).validate_bind_host("0.0.0.0")


def test_remote_enable_requires_exact_allowlist_and_positive_budgets() -> None:
    values = {
        "REFLECT_REMOTE_ENABLED": "1",
        "REFLECT_REMOTE_HOST": "gpu-lab",
        "REFLECT_REMOTE_HOST_ALLOWLIST": "gpu-lab,backup-gpu",
        "REFLECT_REMOTE_WORKDIR": "/srv/reflect-lite",
        "REFLECT_REMOTE_GPU_HOURS_MAX": "4",
        "REFLECT_REMOTE_WALL_HOURS_MAX": "8",
        "REFLECT_REMOTE_DOWNLOAD_GB_MAX": "5",
        "REFLECT_REMOTE_ARTIFACT_GB_MAX": "10",
    }
    target = SafetyConfig.from_mapping(values).validated_remote_target()
    assert target is not None
    assert target.host == "gpu-lab"
    assert target.workdir == "/srv/reflect-lite"
    assert target.budget == RemoteBudget(4.0, 8.0, 5.0, 10.0)


def test_remote_host_not_in_allowlist_is_rejected() -> None:
    values = {
        "REFLECT_REMOTE_ENABLED": "1",
        "REFLECT_REMOTE_HOST": "unknown-host",
        "REFLECT_REMOTE_HOST_ALLOWLIST": "gpu-lab",
        "REFLECT_REMOTE_WORKDIR": "/srv/reflect-lite",
        "REFLECT_REMOTE_GPU_HOURS_MAX": "1",
        "REFLECT_REMOTE_WALL_HOURS_MAX": "1",
        "REFLECT_REMOTE_DOWNLOAD_GB_MAX": "1",
        "REFLECT_REMOTE_ARTIFACT_GB_MAX": "1",
    }
    with pytest.raises(SafetyViolation, match="allowlist"):
        SafetyConfig.from_mapping(values).validated_remote_target()


def test_remote_nonfinite_budget_is_rejected() -> None:
    values = {
        "REFLECT_REMOTE_ENABLED": "1",
        "REFLECT_REMOTE_HOST": "gpu-lab",
        "REFLECT_REMOTE_HOST_ALLOWLIST": "gpu-lab",
        "REFLECT_REMOTE_WORKDIR": "/srv/reflect-lite",
        "REFLECT_REMOTE_GPU_HOURS_MAX": "nan",
        "REFLECT_REMOTE_WALL_HOURS_MAX": "1",
        "REFLECT_REMOTE_DOWNLOAD_GB_MAX": "1",
        "REFLECT_REMOTE_ARTIFACT_GB_MAX": "1",
    }
    with pytest.raises(SafetyViolation, match="positive and finite"):
        SafetyConfig.from_mapping(values).validated_remote_target()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PHYSICAL_DEPLOYMENT_ALLOWED", "maybe"),
        ("REFLECT_REMOTE_ENABLED", "enabled"),
    ],
)
def test_invalid_boolean_text_is_rejected(name: str, value: str) -> None:
    with pytest.raises(SafetyViolation, match="explicit boolean"):
        SafetyConfig.from_mapping({name: value})


def _valid_remote_values() -> dict[str, str]:
    return {
        "REFLECT_REMOTE_ENABLED": "true",
        "REFLECT_REMOTE_HOST": "gpu-lab",
        "REFLECT_REMOTE_HOST_ALLOWLIST": "gpu-lab",
        "REFLECT_REMOTE_WORKDIR": "/srv/reflect-lite",
        "REFLECT_REMOTE_GPU_HOURS_MAX": "1",
        "REFLECT_REMOTE_WALL_HOURS_MAX": "1",
        "REFLECT_REMOTE_DOWNLOAD_GB_MAX": "1",
        "REFLECT_REMOTE_ARTIFACT_GB_MAX": "1",
    }


def test_relative_remote_workdir_is_rejected() -> None:
    values = _valid_remote_values()
    values["REFLECT_REMOTE_WORKDIR"] = "relative/workdir"
    with pytest.raises(SafetyViolation, match="absolute explicit path"):
        SafetyConfig.from_mapping(values).validated_remote_target()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("REFLECT_REMOTE_GPU_HOURS_MAX", "0"),
        ("REFLECT_REMOTE_WALL_HOURS_MAX", "-1"),
        ("REFLECT_REMOTE_DOWNLOAD_GB_MAX", "inf"),
        ("REFLECT_REMOTE_ARTIFACT_GB_MAX", "-inf"),
    ],
)
def test_nonpositive_or_infinite_remote_budget_is_rejected(
    name: str, value: str
) -> None:
    values = _valid_remote_values()
    values[name] = value
    with pytest.raises(SafetyViolation, match="positive and finite"):
        SafetyConfig.from_mapping(values).validated_remote_target()
