from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "experiments/01_policy_control/ENGINEERING_PROMISING_VALIDATION_BOOTSTRAP.json"
REPORT = ROOT / "experiments/01_policy_control/ENGINEERING_PROMISING_VALIDATION.md"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def test_promising_validation_bootstrap_is_exactly_reconstructable() -> None:
    raw = json.loads(ARTIFACT.read_text())
    assert set(raw) == {
        "schema_version", "artifact_type", "source_summary", "recipe",
        "contrasts", "artifact_sha256",
    }
    assert raw["schema_version"] == 1
    assert raw["artifact_type"] == "PAIRED_BOOTSTRAP_RECONSTRUCTION"
    digest = raw.pop("artifact_sha256")
    assert digest == hashlib.sha256(_canonical(raw)).hexdigest()
    source = raw["source_summary"]
    assert set(source) == {"relative_path", "bytes", "sha256"}
    assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
    summary = ROOT / source["relative_path"]
    if summary.is_file():
        payload = summary.read_bytes()
        assert len(payload) == source["bytes"]
        assert hashlib.sha256(payload).hexdigest() == source["sha256"]

    recipe = raw["recipe"]
    assert recipe == {
        "paired_unit": "ROLLOUT_CELL",
        "cell_order": ["SEED_ASC", "CONDITION_ORDER"],
        "condition_order": ["core-20-000-1", "core-10-300-2", "core-05-700-2"],
        "contrast_order": [
            "P5-5p0-0p5-slew6p0", "P5-7p5-0p75-slew6p0",
            "P1-5p0-0p5-slew6p0",
        ],
        "metric_order": [
            "absolute_working", "clamp_fraction", "saturation_fraction",
            "p95_error_m",
        ],
        "rng": "numpy.random.PCG64",
        "seed": 20260823,
        "resamples": 10000,
        "sample_size": 48,
        "draw_reuse": "ONE_INDEX_MATRIX_PER_CONTRAST_SHARED_ACROSS_METRICS_RNG_STREAM_CONTINUES",
        "endpoint_rule": {
            "method": "SORTED_NEAREST_RANK", "lower_probability": 0.025,
            "upper_probability": 0.975, "lower_index": 249,
            "upper_index": 9749,
        },
    }
    generator = np.random.Generator(np.random.PCG64(recipe["seed"]))
    for contrast in raw["contrasts"]:
        cells = contrast["paired_cells"]
        assert [(row["seed"], row["condition_id"]) for row in cells] == [
            (seed, condition)
            for seed in range(20260825, 20260841)
            for condition in recipe["condition_order"]
        ]
        values = np.asarray([
            [row["differences"][metric] for metric in recipe["metric_order"]]
            for row in cells
        ], dtype=np.float64)
        indexes = generator.integers(
            0, recipe["sample_size"],
            size=(recipe["resamples"], recipe["sample_size"]),
        )
        distributions = np.sort(values[indexes].mean(axis=1), axis=0)
        assert contrast["estimate"] == values.mean(axis=0).tolist()
        assert contrast["lower"] == distributions[recipe["endpoint_rule"]["lower_index"]].tolist()
        assert contrast["upper"] == distributions[recipe["endpoint_rule"]["upper_index"]].tolist()
    assert digest in REPORT.read_text()
