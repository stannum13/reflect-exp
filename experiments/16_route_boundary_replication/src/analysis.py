"""Post-outcome analysis and reconstruction for frozen Exp16 evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess

import numpy as np

from .experiment import canonical_bytes, matrix_specs
from . import compact_evidence as _compact


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_and_verify(root: Path) -> list[dict[str, object]]:
    paths = sorted((root / "raw/dispositions").glob("*.json"))
    expected = {item.episode_id for item in matrix_specs()}
    if {path.stem for path in paths} != expected or len(paths) != 540:
        raise RuntimeError("Exp16 disposition identity mismatch")
    rows = []
    for path in paths:
        payload = path.read_bytes()
        row = json.loads(payload.decode("ascii"))
        if payload != canonical_bytes(row) or row["episode_id"] != path.stem:
            raise RuntimeError(f"noncanonical disposition: {path}")
        if row["disposition"] == "COMPLETE":
            episode = root / "raw/episodes" / path.stem
            manifest_payload = (episode / "manifest.json").read_bytes()
            manifest = json.loads(manifest_payload.decode("ascii"))
            if canonical_bytes(manifest) != manifest_payload or _sha(manifest_payload) != row["episode_manifest_sha256"]:
                raise RuntimeError(f"manifest binding mismatch: {path.stem}")
            actual = []
            for item in manifest["files"]:
                file_payload = (episode / item["path"]).read_bytes()
                actual.append({"path": item["path"], "bytes": len(file_payload), "sha256": _sha(file_payload)})
            if actual != manifest["files"]:
                raise RuntimeError(f"episode inventory mismatch: {path.stem}")
        elif (root / "raw/episodes" / path.stem).exists():
            raise RuntimeError(f"non-COMPLETE disposition has episode evidence: {path.stem}")
        rows.append(row)
    return rows


def _paired_ci(
    rows: list[dict[str, object]],
    comparator: str,
    metric: str,
) -> dict[str, object]:
    values = _compact._cluster_values(rows, "R3", comparator, metric)
    seeds = sorted(values)
    plan = (
        _compact._bootstrap_plan(seeds, size=len(seeds))
        if seeds
        else np.empty((_compact.BOOTSTRAP_DRAWS, 0), dtype=int)
    )
    effect, _ = _compact._effect(values, plan)
    return effect


def _registered_science(rows: list[dict[str, object]]) -> dict[str, object]:
    counts = {
        name: sum(row["disposition"] == name for row in rows)
        for name in ("COMPLETE", "NOT_RUN", "INVALID_EXECUTION")
    }
    effects, sensitivity, _, _ = _compact._registered_effects(rows)
    complete = [
        row for row in rows
        if row["disposition"] == "COMPLETE" and row["matrix_role"] == "PRIMARY"
    ]
    strata = []
    for family in sorted({str(spec.family) for spec in matrix_specs()}):
        for severity in ("LOW", "HIGH"):
            r3 = [
                row for row in complete
                if row["architecture"] == "R3"
                and row["family"] == family
                and row["severity"] == severity
            ]
            r2 = [
                row for row in complete
                if row["architecture"] == "R2"
                and row["family"] == family
                and row["severity"] == severity
            ]
            if r3 and r2:
                strata.append(
                    float(np.mean([row["mission_success"] for row in r3]))
                    - float(np.mean([row["mission_success"] for row in r2]))
                )
    heterogeneity = min(strata) if strata else None

    def lower_pass(effect: dict[str, object], threshold: float) -> bool:
        value = effect["lower_95"]
        return isinstance(value, (int, float)) and float(value) >= threshold

    def upper_pass(
        effect: dict[str, object],
        threshold: float,
        *,
        strict: bool = False,
    ) -> bool:
        value = effect["upper_95"]
        return isinstance(value, (int, float)) and (
            float(value) < threshold if strict else float(value) <= threshold
        )

    gates = {
        "primary_n_eff_exactly_10": all(
            effects[name][metric]["n_eff"] == 10
            for name in ("R0", "R1", "R2")
            for metric in ("mission_success", "safety_composite", "progress", "total_wakes")
        ),
        "sensitivity_n_eff_exactly_5": all(
            sensitivity[metric]["n_eff"] == 5
            for metric in ("mission_success", "progress")
        ),
        "success_noninferiority_all_comparators": all(
            lower_pass(effects[name]["mission_success"], -.10)
            for name in ("R0", "R1", "R2")
        ),
        "safety_noninferiority_all_comparators": all(
            upper_pass(effects[name]["safety_composite"], .10)
            for name in ("R0", "R1", "R2")
        ),
        "progress_noninferiority_all_comparators": all(
            lower_pass(effects[name]["progress"], -.05)
            for name in ("R0", "R1", "R2")
        ),
        "wake_reduction_vs_fixed_R2": upper_pass(
            effects["R2"]["total_wakes"], 0.0, strict=True,
        ),
        "worst_R3_minus_R2_family_severity_success": heterogeneity,
        "heterogeneity_threshold_pass": (
            isinstance(heterogeneity, (int, float)) and heterogeneity >= -.20
        ),
    }
    return {
        "dispositions": counts,
        "effects": effects,
        "controller_sensitivity_P4_minus_P6": sensitivity,
        "registered_gate_evaluation": gates,
        "formal_disposition": _compact._formal_disposition(counts, gates),
    }


def analyze(root: Path) -> dict[str, object]:
    rows = _load_and_verify(root)
    science = _registered_science(rows)
    counts = science["dispositions"]
    complete = [row for row in rows if row["disposition"] == "COMPLETE"]
    summaries = []
    for role in ("PRIMARY", "SENSITIVITY"):
        for architecture in ("R0", "R1", "R2", "R3"):
            selected = [row for row in complete if row["matrix_role"] == role and row["architecture"] == architecture]
            summaries.append({"matrix_role": role, "architecture": architecture, "n": len(selected),
                "success_rate": None if not selected else float(np.mean([row["mission_success"] for row in selected])),
                "safety_rate": None if not selected else float(np.mean([row["safety_composite"] for row in selected])),
                "mean_progress": None if not selected else float(np.mean([row["progress"] for row in selected])),
                "mean_wakes": None if not selected else float(np.mean([row["control_wakes"] + row["motion_wakes"] + row["semantic_wakes"] for row in selected]))})
    report = {"schema_version": 1, "experiment_id": "exp16-route-boundary-replication-v1", "matrix_total": 540,
        "dispositions": counts, "summaries": summaries,
        "paired_seed_cluster_bootstrap_10k": science["effects"],
        "controller_sensitivity_P4_minus_P6": science["controller_sensitivity_P4_minus_P6"],
        "registered_gate_evaluation": science["registered_gate_evaluation"],
        "formal_disposition": science["formal_disposition"],
        "reconstruction": "PASS", "causal_lowest_claim": False}
    analysis_root = root / "analysis"
    analysis_root.mkdir(parents=True, exist_ok=True)
    (analysis_root / "report.json").write_bytes(canonical_bytes(report))
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=tuple(summaries[0]))
    writer.writeheader()
    writer.writerows(summaries)
    (analysis_root / "summary.csv").write_text(stream.getvalue(), encoding="ascii")
    primary = {item["architecture"]: item for item in summaries if item["matrix_role"] == "PRIMARY"}
    svg = _compact._svg(
        "Exp16 primary mission success",
        ["R0", "R1", "R2", "R3"],
        [("success", [primary[a]["success_rate"] for a in ("R0", "R1", "R2", "R3")], "#3568a8")],
    )
    (analysis_root / "primary-success.svg").write_bytes(svg)
    subprocess.run(("rsvg-convert", str(analysis_root / "primary-success.svg"), "-o", str(analysis_root / "primary-success.png")), check=True)
    inventory = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "inventory.json"):
        payload = path.read_bytes()
        inventory.append({"path": path.relative_to(root).as_posix(), "bytes": len(payload), "sha256": _sha(payload)})
    (root / "inventory.json").write_bytes(canonical_bytes({"schema_version": 1, "excludes": ["inventory.json"], "files": inventory}))
    return report


__all__ = ["analyze"]
