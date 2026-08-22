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
