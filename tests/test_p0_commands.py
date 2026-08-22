from pathlib import Path
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_safety_cli_reports_simulation_only() -> None:
    env = dict(os.environ)
    env["PHYSICAL_DEPLOYMENT_ALLOWED"] = "false"
    env["REFLECT_REMOTE_ENABLED"] = "0"
    completed = subprocess.run(
        [sys.executable, "-m", "reflect.safety", "check"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == (
        '{"simulation_only": true, "remote_enabled": false}'
    )


def test_makefile_exposes_required_p0_targets() -> None:
    makefile = (ROOT / "Makefile").read_text()
    for target in ("install-local:", "test:", "safety-check:", "p0-report:"):
        assert target in makefile


def test_make_safety_check_uses_fail_closed_defaults() -> None:
    env = dict(os.environ)
    env.pop("PHYSICAL_DEPLOYMENT_ALLOWED", None)
    env.pop("REFLECT_REMOTE_ENABLED", None)
    completed = subprocess.run(
        ["make", "safety-check"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip().endswith(
        '{"simulation_only": true, "remote_enabled": false}'
    )


def test_make_safety_check_rejects_physical_enablement() -> None:
    env = dict(os.environ)
    env["PHYSICAL_DEPLOYMENT_ALLOWED"] = "true"
    completed = subprocess.run(
        ["make", "safety-check"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "physical deployment is disabled for this program" in completed.stderr


def test_p0_report_rejects_enabled_remote_before_overwriting_report() -> None:
    report = ROOT / "RUN_REPORT.md"
    before = report.read_bytes()
    env = dict(os.environ)
    env.update(
        {
            "PHYSICAL_DEPLOYMENT_ALLOWED": "false",
            "REFLECT_REMOTE_ENABLED": "1",
            "REFLECT_REMOTE_HOST": "gpu-lab",
            "REFLECT_REMOTE_HOST_ALLOWLIST": "gpu-lab",
            "REFLECT_REMOTE_WORKDIR": "/srv/reflect-lite",
            "REFLECT_REMOTE_GPU_HOURS_MAX": "1",
            "REFLECT_REMOTE_WALL_HOURS_MAX": "1",
            "REFLECT_REMOTE_DOWNLOAD_GB_MAX": "1",
            "REFLECT_REMOTE_ARTIFACT_GB_MAX": "1",
            "PYTEST_ADDOPTS": "-k test_name_that_does_not_exist",
        }
    )
    try:
        completed = subprocess.run(
            [sys.executable, "scripts/write_p0_report.py"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert completed.returncode != 0
        assert "remote execution must be disabled for P0 reporting" in completed.stderr
        assert report.read_bytes() == before
    finally:
        report.write_bytes(before)


def test_p0_report_uses_bounded_network_evidence_wording() -> None:
    generator = (ROOT / "scripts" / "write_p0_report.py").read_text()
    assert (
        "This generator performs no explicit source fetches; subprocess network "
        "activity was not measured."
    ) in generator
