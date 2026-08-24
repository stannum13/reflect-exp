"""Portable, independently reconstructable compact evidence for Exp13."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Iterable

import numpy as np

from .experiment import canonical_bytes, matrix_specs

EXPECTED_FREEZE_SHA256 = "324e8c4f3b79e0e84447590012cf915db4f1c75f9eb80d7bc1e49941c63ddb3c"
EXPECTED_RAW_INVENTORY_SHA256 = "552cb44e65e5f7cce6580d19a5afa4751a7fa63af45977548b60e2cf1dda1f93"
BOOTSTRAP_SEED = 1313
BOOTSTRAP_DRAWS = 10_000


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _csv_bytes(fieldnames: Iterable[str], rows: Iterable[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=tuple(fieldnames), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("ascii")


def tree_inventory(root: Path, *, exclude_manifest: bool = False) -> list[dict[str, object]]:
    inventory = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"symlink forbidden in compact evidence: {path}")
        if not path.is_file() or (exclude_manifest and path.name == "pack-manifest.json"):
            continue
        payload = path.read_bytes()
        inventory.append({"path": path.relative_to(root).as_posix(), "bytes": len(payload), "sha256": _sha(payload)})
    return inventory


def _rows(pack: Path) -> list[dict[str, object]]:
    paths = sorted((pack / "inputs/dispositions").glob("*.json"))
    expected = {item.episode_id for item in matrix_specs()}
    if len(paths) != 540 or {path.stem for path in paths} != expected:
        raise RuntimeError("compact evidence disposition identity mismatch")
    result = []
    for path in paths:
        payload = path.read_bytes()
        row = json.loads(payload.decode("ascii"))
        if canonical_bytes(row) != payload or row["episode_id"] != path.stem:
            raise RuntimeError(f"invalid compact disposition: {path.name}")
        result.append(row)
    return result


def _bootstrap_plan(seeds: list[int], *, size: int) -> np.ndarray:
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    return rng.choice(np.asarray(seeds), size=(BOOTSTRAP_DRAWS, size), replace=True)


def _cluster_values(rows: list[dict[str, object]], left: str, right: str, metric: str) -> dict[int, list[float]]:
    complete = [row for row in rows if row["disposition"] == "COMPLETE" and row["matrix_role"] == "PRIMARY"]
    lookup = {(row["architecture"], row["family"], row["severity"], int(row["seed"])): row for row in complete}
    values: dict[int, list[float]] = {}
    for seed in sorted({int(row["seed"]) for row in complete}):
        cluster = []
        for family in sorted({str(row["family"]) for row in complete}):
            for severity in ("LOW", "HIGH"):
                a = lookup.get((left, family, severity, seed))
                b = lookup.get((right, family, severity, seed))
                if a is not None and b is not None:
                    cluster.append(float(a[metric]) - float(b[metric]))
        if cluster:
            values[seed] = cluster
    return values


def _sensitivity_values(rows: list[dict[str, object]], metric: str) -> dict[int, list[float]]:
    complete = [row for row in rows if row["disposition"] == "COMPLETE" and row["architecture"] == "R3"]
    values = {}
    for seed in range(20262101, 20262106):
        cluster = []
        for family in sorted({str(row["family"]) for row in complete}):
            for severity in ("LOW", "HIGH"):
                p4 = next((row for row in complete if row["matrix_role"] == "SENSITIVITY" and int(row["seed"]) == seed and row["family"] == family and row["severity"] == severity), None)
                p6 = next((row for row in complete if row["matrix_role"] == "PRIMARY" and int(row["seed"]) == seed and row["family"] == family and row["severity"] == severity), None)
                if p4 is not None and p6 is not None:
                    cluster.append(float(p4[metric]) - float(p6[metric]))
        values[seed] = cluster
    return values


def _effect(values: dict[int, list[float]], plan: np.ndarray) -> tuple[dict[str, object], np.ndarray]:
    observed = float(np.mean([value for cluster in values.values() for value in cluster]))
    draws = np.asarray([np.mean([value for seed in sampled for value in values[int(seed)]]) for sampled in plan])
    return ({"estimate": observed, "lower_95": float(np.quantile(draws, .025)),
             "upper_95": float(np.quantile(draws, .975)), "n_eff": len(values),
             "draws": BOOTSTRAP_DRAWS, "resampling_unit": "seed_cluster"}, draws)


def _svg(title: str, labels: list[str], series: list[tuple[str, list[float], str]], *, y_min: float = 0.0, y_max: float = 1.0) -> bytes:
    width, height = 760, 420
    left, top, plot_w, plot_h = 70, 55, 630, 290
    group_w = plot_w / len(labels)
    bar_w = min(36.0, group_w / (len(series) + 1))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
             '<rect width="100%" height="100%" fill="#ffffff"/>',
             f'<text x="380" y="28" text-anchor="middle" font-family="sans-serif" font-size="18">{title}</text>',
             f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#222"/>']
    for index, label in enumerate(labels):
        center = left + group_w * (index + .5)
        parts.append(f'<text x="{center:.2f}" y="{top+plot_h+24}" text-anchor="middle" font-family="sans-serif" font-size="12">{label}</text>')
        for series_index, (_, values, color) in enumerate(series):
            value = values[index]
            scaled = (value - y_min) / (y_max - y_min)
            bar_h = max(0.0, min(1.0, scaled)) * plot_h
            x = center + (series_index - (len(series) - 1) / 2) * bar_w - bar_w * .42
            parts.append(f'<rect x="{x:.2f}" y="{top+plot_h-bar_h:.2f}" width="{bar_w*.84:.2f}" height="{bar_h:.2f}" fill="{color}"/>')
    for index, (name, _, color) in enumerate(series):
        parts.append(f'<rect x="{left+index*145}" y="390" width="12" height="12" fill="{color}"/><text x="{left+17+index*145}" y="401" font-family="sans-serif" font-size="12">{name}</text>')
    parts.append('</svg>')
    return "".join(parts).encode("ascii")


def reconstruct_derived(pack: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    rows = _rows(pack)
    complete = [row for row in rows if row["disposition"] == "COMPLETE"]
    counts = {name: sum(row["disposition"] == name for row in rows) for name in ("COMPLETE", "NOT_RUN", "INVALID_EXECUTION")}
    summary = []
    for role in ("PRIMARY", "SENSITIVITY"):
        for architecture in ("R0", "R1", "R2", "R3"):
            selected = [row for row in complete if row["matrix_role"] == role and row["architecture"] == architecture]
            if selected:
                summary.append({"matrix_role": role, "architecture": architecture, "n": len(selected),
                    "success_rate": float(np.mean([row["mission_success"] for row in selected])),
                    "safety_rate": float(np.mean([row["safety_composite"] for row in selected])),
                    "mean_progress": float(np.mean([row["progress"] for row in selected])),
                    "mean_wakes": float(np.mean([row["control_wakes"] + row["motion_wakes"] + row["semantic_wakes"] for row in selected]))})
    _write(destination / "tables/architecture-summary.csv", _csv_bytes(tuple(summary[0]), summary))
    family_rows = []
    for family in sorted({str(row["family"]) for row in complete}):
        for severity in ("LOW", "HIGH"):
            for architecture in ("R0", "R1", "R2", "R3"):
                selected = [row for row in complete if row["matrix_role"] == "PRIMARY" and row["family"] == family and row["severity"] == severity and row["architecture"] == architecture]
                family_rows.append({"family": family, "severity": severity, "architecture": architecture, "n": len(selected),
                    "success_rate": float(np.mean([row["mission_success"] for row in selected])) if selected else "",
                    "mean_progress": float(np.mean([row["progress"] for row in selected])) if selected else ""})
    _write(destination / "tables/family-severity.csv", _csv_bytes(tuple(family_rows[0]), family_rows))
    primary_plan = _bootstrap_plan(list(range(20262101, 20262111)), size=10)
    sensitivity_plan = _bootstrap_plan(list(range(20262101, 20262106)), size=5)
    effects = {}
    draw_columns: dict[str, np.ndarray] = {}
    augmented = [{**row, "total_wakes": row.get("control_wakes", 0) + row.get("motion_wakes", 0) + row.get("semantic_wakes", 0)} for row in rows]
    for comparator in ("R0", "R1", "R2"):
        effects[comparator] = {}
        for metric in ("mission_success", "safety_composite", "progress", "total_wakes"):
            effect, draws = _effect(_cluster_values(augmented, "R3", comparator, metric), primary_plan)
            effects[comparator][metric] = effect
            draw_columns[f"R3-{comparator}:{metric}"] = draws
    sensitivity = {}
    for metric in ("mission_success", "progress"):
        effect, draws = _effect(_sensitivity_values(rows, metric), sensitivity_plan)
        sensitivity[metric] = effect
        draw_columns[f"P4-P6:{metric}"] = draws
    cluster_rows = []
    for name, values in [(f"R3-{c}:{m}", _cluster_values(augmented, "R3", c, m)) for c in ("R0","R1","R2") for m in ("mission_success","safety_composite","progress","total_wakes")]:
        for seed, cluster in values.items():
            cluster_rows.append({"comparison_metric": name, "seed": seed, "member_count": len(cluster), "cluster_mean": float(np.mean(cluster)), "members_json": json.dumps(cluster, separators=(",", ":"))})
    for metric in ("mission_success", "progress"):
        for seed, cluster in _sensitivity_values(rows, metric).items():
            cluster_rows.append({"comparison_metric": f"P4-P6:{metric}", "seed": seed, "member_count": len(cluster), "cluster_mean": float(np.mean(cluster)), "members_json": json.dumps(cluster, separators=(",", ":"))})
    _write(destination / "bootstrap/cluster-inputs.csv", _csv_bytes(tuple(cluster_rows[0]), cluster_rows))
    draw_rows = []
    for index in range(BOOTSTRAP_DRAWS):
        row = {"draw_id": index, "primary_sampled_seeds": "|".join(map(str, primary_plan[index])), "sensitivity_sampled_seeds": "|".join(map(str, sensitivity_plan[index]))}
        row.update({name: float(values[index]) for name, values in draw_columns.items()})
        draw_rows.append(row)
    _write(destination / "bootstrap/draws.csv", _csv_bytes(tuple(draw_rows[0]), draw_rows))
    failure_rows = []
    for disposition in ("NOT_RUN", "INVALID_EXECUTION"):
        selected = [row for row in rows if row["disposition"] == disposition]
        groups: dict[tuple[str, str], int] = {}
        for row in selected:
            key = (str(row.get("exception_class", disposition)), str(row.get("exception_message", row.get("precheck_receipt", {}).get("reason", ""))))
            groups[key] = groups.get(key, 0) + 1
        for (failure_class, reason), count in sorted(groups.items()):
            failure_rows.append({"disposition": disposition, "failure_class": failure_class, "reason": reason, "count": count})
    _write(destination / "tables/failure-taxonomy.csv", _csv_bytes(("disposition","failure_class","reason","count"), failure_rows))
    sample_payload = json.loads((pack / "inputs/sample-annotations.json").read_text())
    _write(destination / "tables/annotated-samples.json", canonical_bytes(sample_payload))
    worst = min(family_rows, key=lambda item: float(item["success_rate"]) if item["architecture"] == "R3" else 2.0)
    heterogeneity = min(float(r3["success_rate"]) - float(other["success_rate"]) for r3 in family_rows if r3["architecture"] == "R3" for other in family_rows if other["family"] == r3["family"] and other["severity"] == r3["severity"] and other["architecture"] in ("R0","R1","R2"))
    report = {"schema_version": 2, "scope": "EXPLORATORY_PHYSICAL_HIERARCHY_SIGNAL", "formal_disposition": "INVALID_EXPERIMENT",
        "confirmatory_support": False, "causal_lowest_claim": False, "matrix_total": 540, "dispositions": counts,
        "chronology": {"V1": "202619 seeds; INVALID_PARTIAL after 9 outcomes", "V2": "202620 seeds; INVALID_PARTIAL after 22 dispositions", "V3": "202621 seeds; complete but formally invalid exploratory experiment"},
        "effects": effects, "controller_sensitivity_P4_minus_P6": sensitivity,
        "registered_gate_evaluation": {"success_noninferiority": effects["R2"]["mission_success"]["lower_95"] >= -.10,
            "safety_noninferiority": effects["R2"]["safety_composite"]["upper_95"] <= .10,
            "progress_noninferiority": effects["R2"]["progress"]["lower_95"] >= -.05,
            "wake_reduction": effects["R2"]["total_wakes"]["upper_95"] < 0,
            "worst_family_success_difference": heterogeneity, "heterogeneity_threshold_pass": heterogeneity >= -.20},
        "worst_r3_cell_success_rate": worst, "bootstrap": {"seed": BOOTSTRAP_SEED, "draws": BOOTSTRAP_DRAWS, "primary_n_eff": 10, "sensitivity_n_eff": 5},
        "portability_limit": "The full 1.3G physical tick/contact/command trace root remains local and is not included; its recursive inventory and selected full working/nonworking episodes are portable.",
        "reconstruction_scope": "All compact statistics, tables, bootstrap draws, SVGs and PNGs reconstruct from tracked dispositions; only selected episodes permit raw-physics rescoring."}
    _write(destination / "report.json", canonical_bytes(report))
    markdown = f"# Exp13 exploratory physical hierarchy signal\n\n**Formal disposition: INVALID_EXPERIMENT. This is not confirmatory support.**\n\nThe portable pack contains all 540 dispositions and reconstructs all derived bytes. {report['portability_limit']}\n\nV1 used 202619 seeds and stopped after nine outcomes; V2 used 202620 and stopped after 22 dispositions; V3 used 202621 and completed 540 dispositions. No V1/V2 outcomes were tuned into V3.\n"
    _write(destination / "REPORT.md", markdown.encode("ascii"))
    style = {"schema_version": 1, "renderer": "rsvg-convert", "canvas": [760,420], "font": "sans-serif", "colors": {"R0":"#777777","R1":"#55a868","R2":"#c44e52","R3":"#4c72b0","P4":"#8172b2"}}
    _write(destination / "graphs/style.json", canonical_bytes(style))
    arch = {item["architecture"]: item for item in summary if item["matrix_role"] == "PRIMARY"}
    graph_specs = {
        "success-progress": ("Primary success and progress", ["R0","R1","R2","R3"], [("success",[arch[a]["success_rate"] for a in ("R0","R1","R2","R3")],"#4c72b0"),("progress",[arch[a]["mean_progress"] for a in ("R0","R1","R2","R3")],"#55a868")]),
        "wake-profiles": ("Primary wake profiles", ["R0","R1","R2","R3"], [("mean wakes",[arch[a]["mean_wakes"]/2 for a in ("R0","R1","R2","R3")],"#8172b2")]),
        "family-heterogeneity": ("R3 mission success by family", [name[:10] for name in sorted({r["family"] for r in family_rows})], [(sev,[next(float(r["success_rate"]) for r in family_rows if r["architecture"]=="R3" and r["family"]==fam and r["severity"]==sev) for fam in sorted({r["family"] for r in family_rows})],color) for sev,color in (("LOW","#4c72b0"),("HIGH","#c44e52"))]),
        "controller-sensitivity": ("R3 controller sensitivity", ["success","progress"], [("P4-P6",[sensitivity["mission_success"]["estimate"]+1,sensitivity["progress"]["estimate"]+1],"#8172b2")]),
    }
    for name, (title, labels, series) in graph_specs.items():
        svg = _svg(title, labels, series)
        _write(destination / f"graphs/{name}.svg", svg)
        subprocess.run(("rsvg-convert", str(destination / f"graphs/{name}.svg"), "-o", str(destination / f"graphs/{name}.png")), check=True)


def _raw_inventory_lookup(pack: Path) -> dict[str, dict[str, object]]:
    payload = (pack / "inputs/local-raw-inventory.json").read_bytes()
    if _sha(payload) != EXPECTED_RAW_INVENTORY_SHA256:
        raise RuntimeError("local raw inventory binding mismatch")
    document = json.loads(payload)
    return {item["path"]: item for item in document["files"]}


def reseal_inventory_for_test(pack: Path) -> None:
    manifest = {"schema_version": 1, "external_binding": "git tracked pack plus expected raw inventory hash", "files": tree_inventory(pack, exclude_manifest=True)}
    _write(pack / "pack-manifest.json", canonical_bytes(manifest))


def publish_compact_pack(raw_root: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    (destination / "inputs").mkdir()
    shutil.copyfile(raw_root / "freeze.json", destination / "inputs/freeze.json")
    shutil.copyfile(raw_root / "inventory.json", destination / "inputs/local-raw-inventory.json")
    rows = []
    for path in sorted((raw_root / "raw/dispositions").glob("*.json")):
        target = destination / "inputs/dispositions" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        row = json.loads(path.read_text())
        rows.append(row)
        if row["disposition"] == "COMPLETE":
            source = raw_root / "raw/episodes" / path.stem / "manifest.json"
            target = destination / "inputs/manifests" / f"{path.stem}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    working = next(row for row in rows if row["disposition"] == "COMPLETE" and row["matrix_role"] == "PRIMARY" and row["architecture"] == "R3" and row["mission_success"] and not row["safety_composite"])
    nonworking = next(row for row in rows if row["disposition"] == "COMPLETE" and row["matrix_role"] == "PRIMARY" and row["architecture"] == "R3" and (not row["mission_success"] or row["safety_composite"]))
    annotations = []
    for label, row in (("working", working), ("nonworking", nonworking)):
        shutil.copytree(raw_root / "raw/episodes" / row["episode_id"], destination / "inputs/selected-episodes" / label)
        annotations.append({"label": label, "episode_id": row["episode_id"], "mission_success": row["mission_success"], "safety_composite": row["safety_composite"], "progress": row["progress"], "selection_rule": "first lexicographic primary R3 cell matching label; registered outcomes were not tuned"})
    _write(destination / "inputs/sample-annotations.json", canonical_bytes(annotations))
    reconstruct_derived(destination, destination / "derived")
    reseal_inventory_for_test(destination)


def verify_compact_pack(pack: Path) -> dict[str, object]:
    manifest_payload = (pack / "pack-manifest.json").read_bytes()
    manifest = json.loads(manifest_payload.decode("ascii"))
    if canonical_bytes(manifest) != manifest_payload or manifest["files"] != tree_inventory(pack, exclude_manifest=True):
        raise RuntimeError("compact evidence inventory mismatch")
    freeze_payload = (pack / "inputs/freeze.json").read_bytes()
    if _sha(freeze_payload) != EXPECTED_FREEZE_SHA256:
        raise RuntimeError("compact freeze binding mismatch")
    raw_lookup = _raw_inventory_lookup(pack)
    for path in sorted((pack / "inputs/dispositions").glob("*.json")):
        key = f"raw/dispositions/{path.name}"
        item = raw_lookup.get(key)
        if item is None or item["sha256"] != _sha(path.read_bytes()):
            raise RuntimeError("compact disposition substitution against raw inventory")
    for path in sorted((pack / "inputs/manifests").glob("*.json")):
        key = f"raw/episodes/{path.stem}/manifest.json"
        item = raw_lookup.get(key)
        if item is None or item["sha256"] != _sha(path.read_bytes()):
            raise RuntimeError("compact manifest substitution against raw inventory")
    with tempfile.TemporaryDirectory() as temporary:
        rebuilt = Path(temporary) / "derived"
        reconstruct_derived(pack, rebuilt)
        if tree_inventory(rebuilt) != tree_inventory(pack / "derived"):
            raise RuntimeError("derived reconstruction mismatch")
    counts = {name: sum(row["disposition"] == name for row in _rows(pack)) for name in ("COMPLETE", "NOT_RUN", "INVALID_EXECUTION")}
    return {"status": "PASS", "dispositions": counts, "pack_manifest_sha256": _sha(manifest_payload)}


__all__ = ["canonical_bytes", "publish_compact_pack", "reconstruct_derived", "reseal_inventory_for_test", "tree_inventory", "verify_compact_pack"]
