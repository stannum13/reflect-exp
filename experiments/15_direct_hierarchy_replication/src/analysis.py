"""Post-outcome analysis and reconstruction for frozen Exp15 evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess

import numpy as np

from .experiment import canonical_bytes, matrix_specs


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_and_verify(root: Path) -> list[dict[str, object]]:
    paths = sorted((root / "raw/dispositions").glob("*.json"))
    expected = {item.episode_id for item in matrix_specs()}
    if {path.stem for path in paths} != expected or len(paths) != 540:
        raise RuntimeError("Exp15 disposition identity mismatch")
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


def _paired_ci(rows: list[dict[str, object]], comparator: str, metric: str) -> dict[str, float]:
    complete = [row for row in rows if row["disposition"] == "COMPLETE" and row["matrix_role"] == "PRIMARY"]
    lookup = {(row["architecture"], row["family"], row["severity"], row["seed"]): row for row in complete}
    by_seed: dict[int, list[float]] = {}
    for seed in sorted({int(row["seed"]) for row in complete}):
        values = []
        for family in sorted({str(row["family"]) for row in complete}):
            for severity in ("LOW", "HIGH"):
                left = lookup.get(("R3", family, severity, seed))
                right = lookup.get((comparator, family, severity, seed))
                if left is not None and right is not None:
                    values.append(float(left[metric]) - float(right[metric]))
        if values:
            by_seed[seed] = values
    observed = float(np.mean([value for values in by_seed.values() for value in values]))
    rng = np.random.Generator(np.random.PCG64(1313))
    draws = np.empty(10_000)
    active = np.asarray(sorted(by_seed))
    for index in range(len(draws)):
        sampled = rng.choice(active, size=len(active), replace=True)
        draws[index] = np.mean([value for seed in sampled for value in by_seed[int(seed)]])
    return {"estimate": observed, "lower_95": float(np.quantile(draws, .025)), "upper_95": float(np.quantile(draws, .975))}


def analyze(root: Path) -> dict[str, object]:
    rows = _load_and_verify(root)
    counts = {name: sum(row["disposition"] == name for row in rows) for name in ("COMPLETE", "NOT_RUN", "INVALID_EXECUTION")}
    complete = [row for row in rows if row["disposition"] == "COMPLETE"]
    summaries = []
    for role in ("PRIMARY", "SENSITIVITY"):
        for architecture in ("R0", "R1", "R2", "R3"):
            selected = [row for row in complete if row["matrix_role"] == role and row["architecture"] == architecture]
            if selected:
                summaries.append({"matrix_role": role, "architecture": architecture, "n": len(selected),
                    "success_rate": float(np.mean([row["mission_success"] for row in selected])),
                    "safety_rate": float(np.mean([row["safety_composite"] for row in selected])),
                    "mean_progress": float(np.mean([row["progress"] for row in selected])),
                    "mean_wakes": float(np.mean([row["control_wakes"] + row["motion_wakes"] + row["semantic_wakes"] for row in selected]))})
    augmented = [{**row, "total_wakes": row.get("control_wakes", 0) + row.get("motion_wakes", 0) + row.get("semantic_wakes", 0)} for row in rows]
    paired = {comparator: {metric: _paired_ci(rows, comparator, metric) for metric in ("mission_success", "safety_composite", "progress")} for comparator in ("R0", "R1", "R2")}
    paired["R2"]["total_wakes"] = _paired_ci(augmented, "R2", "total_wakes")
    report = {"schema_version": 1, "experiment_id": "exp15-direct-hierarchy-replication-v2", "matrix_total": 540,
        "dispositions": counts, "summaries": summaries, "paired_seed_cluster_bootstrap_10k": paired,
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
    bars = "".join(f'<rect x="{70+i*90}" y="{260-200*primary[a]["success_rate"]:.2f}" width="48" height="{200*primary[a]["success_rate"]:.2f}" fill="#3568a8"/><text x="{94+i*90}" y="280" text-anchor="middle">{a}</text>' for i,a in enumerate(("R0","R1","R2","R3")))
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="500" height="320"><rect width="100%" height="100%" fill="white"/><text x="250" y="30" text-anchor="middle" font-size="18">Exp15 primary mission success</text><line x1="50" y1="260" x2="450" y2="260" stroke="black"/>{bars}</svg>'
    (analysis_root / "primary-success.svg").write_text(svg, encoding="ascii")
    subprocess.run(("rsvg-convert", str(analysis_root / "primary-success.svg"), "-o", str(analysis_root / "primary-success.png")), check=True)
    inventory = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "inventory.json"):
        payload = path.read_bytes()
        inventory.append({"path": path.relative_to(root).as_posix(), "bytes": len(payload), "sha256": _sha(payload)})
    (root / "inventory.json").write_bytes(canonical_bytes({"schema_version": 1, "excludes": ["inventory.json"], "files": inventory}))
    return report


__all__ = ["analyze"]
