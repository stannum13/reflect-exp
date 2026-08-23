"""Black-box reproducibility check for the hierarchy synthesis renderer."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("reconstruct_analysis.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reconstruction_is_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "reconstructed"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(ROOT), "--output", str(output)],
        check=True,
        text=True,
        capture_output=True,
    )
    expected = [
        "data/variant_summary.csv",
        "data/paired_differences.csv",
        "data/mission_summary.csv",
        "data/event_stratum_summary.csv",
        "data/examples.json",
        "graphs/variant_success.svg",
        "graphs/paired_effects.svg",
        "graphs/variant_success.png",
        "graphs/paired_effects.png",
        "evidence_manifest.json",
    ]
    for relative in expected:
        assert (output / relative).is_file(), relative

    second = tmp_path / "reconstructed-second"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(ROOT), "--output", str(second)],
        check=True,
        text=True,
        capture_output=True,
    )
    # SVG/CSV/JSON are intentionally byte-stable. PNGs carry normalized metadata.
    for relative in expected:
        if relative.endswith(".png"):
            continue
        assert digest(output / relative) == digest(second / relative), relative
