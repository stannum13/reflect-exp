"""Black-box reproducibility check for the hierarchy synthesis renderer."""

from __future__ import annotations

import hashlib
import json
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
        "data/canonical_graph_data.json",
        "data/case_outcomes.csv",
        "data/cases.csv",
        "data/variant_summary.csv",
        "data/paired_differences.csv",
        "data/paired_case_differences.csv",
        "data/mission_summary.csv",
        "data/event_stratum_summary.csv",
        "data/examples.json",
        "graphs/variant_success.svg",
        "graphs/paired_effects.svg",
        "RESULTS.md",
        "evidence_manifest.json",
        "SHA256SUMS",
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
    # Canonical data, SVG, report, and evidence are byte-stable reconstruction outputs.
    # The publication PNGs are frozen non-authoritative companions and are intentionally
    # excluded from a clean reconstruction because their original rasterizer is undeclared.
    for relative in expected:
        assert digest(output / relative) == digest(second / relative), relative
    assert not (output / "graphs" / "variant_success.png").exists()
    assert not (output / "graphs" / "paired_effects.png").exists()
    manifest = json.loads((output / "evidence_manifest.json").read_text(encoding="utf-8"))
    assert manifest["non_authoritative_png_companions"] == []
