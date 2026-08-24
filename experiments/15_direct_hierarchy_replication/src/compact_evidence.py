"""Portable, independently reconstructable compact evidence for Exp15."""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Iterable

import numpy as np

from .experiment import canonical_bytes, matrix_specs

EXPECTED_FREEZE_SHA256 = "UNSEALED_BEFORE_OUTCOME"
EXPECTED_RAW_INVENTORY_SHA256 = "UNSEALED_BEFORE_OUTCOME"
BOOTSTRAP_SEED = 1313
BOOTSTRAP_DRAWS = 10_000
PACK_MANIFEST_KEYS = {"schema_version", "external_binding", "files"}
COMPLETE_KEYS = {"aborts", "action_cost", "architecture", "control_wakes", "controller_id", "disposition", "episode_id", "episode_manifest_sha256", "family", "matrix_role", "mission_success", "motion_wakes", "parameter_sha256", "peak_contact_force_n", "peak_torque_nm", "progress", "recovery_latency_ticks", "retry_count", "rms_torque_nm", "safety_composite", "seed", "semantic_wakes", "severity", "terminal", "trajectory_length_rad"}
NOT_RUN_KEYS = {"architecture", "architecture_independent", "controller_id", "disposition", "episode_id", "family", "matrix_role", "parameter_sha256", "precheck_receipt", "precheck_receipt_sha256", "seed", "severity"}
INVALID_KEYS = {"architecture", "controller_id", "disposition", "episode_id", "exception_class", "exception_message", "execution_stage", "family", "freeze_sha256", "matrix_role", "parameter_sha256", "seed", "severity", "source_commit"}
DERIVED_PATHS = {
    "derived/REPORT.md", "derived/bootstrap/cluster-inputs.csv", "derived/bootstrap/draws.csv",
    "derived/graphs/controller-sensitivity.png", "derived/graphs/controller-sensitivity.svg",
    "derived/graphs/family-heterogeneity.png", "derived/graphs/family-heterogeneity.svg",
    "derived/graphs/plot-data.csv", "derived/graphs/style.json",
    "derived/graphs/success-progress.png", "derived/graphs/success-progress.svg",
    "derived/graphs/wake-profiles.png", "derived/graphs/wake-profiles.svg", "derived/report.json",
    "derived/tables/annotated-samples.json", "derived/tables/architecture-summary.csv",
    "derived/tables/failure-taxonomy.csv", "derived/tables/family-severity.csv",
}


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


def _balanced_sensitivity_plan(seeds: list[int]) -> np.ndarray:
    exhaustive = np.asarray(list(itertools.product(seeds, repeat=len(seeds))))
    supplement = exhaustive[np.linspace(0, len(exhaustive) - 1, BOOTSTRAP_DRAWS - 3 * len(exhaustive), dtype=int)]
    return np.concatenate((exhaustive, exhaustive, exhaustive, supplement))


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
    for seed in range(20262301, 20262306):
        cluster = []
        for family in sorted({str(row["family"]) for row in complete}):
            for severity in ("LOW", "HIGH"):
                p4 = next((row for row in complete if row["matrix_role"] == "SENSITIVITY" and int(row["seed"]) == seed and row["family"] == family and row["severity"] == severity), None)
                p6 = next((row for row in complete if row["matrix_role"] == "PRIMARY" and int(row["seed"]) == seed and row["family"] == family and row["severity"] == severity), None)
                if p4 is not None and p6 is not None:
                    cluster.append(float(p4[metric]) - float(p6[metric]))
        if cluster:
            values[seed] = cluster
    return values


def _effect(values: dict[int, list[float]], plan: np.ndarray) -> tuple[dict[str, object], np.ndarray]:
    if not values:
        return ({"estimate": None, "lower_95": None, "upper_95": None, "n_eff": 0,
                 "draws": 0, "resampling_unit": "seed_cluster",
                 "inferential_status": "NOT_RUN_NO_PAIRED_CLUSTERS"},
                np.asarray([None] * BOOTSTRAP_DRAWS, dtype=object))
    seed_means = {seed: float(np.mean(cluster)) for seed, cluster in values.items()}
    observed = float(np.mean(list(seed_means.values())))
    draws = np.asarray([np.mean([seed_means[int(seed)] for seed in sampled]) for sampled in plan])
    return ({"estimate": observed, "lower_95": float(np.quantile(draws, .025)),
             "upper_95": float(np.quantile(draws, .975)), "n_eff": len(values),
             "draws": BOOTSTRAP_DRAWS, "resampling_unit": "seed_cluster",
             "inferential_status": "RUN_ACTUAL_PAIRED_CLUSTERS"}, draws)


def _descriptive_without_inference(values: dict[int, list[float]], reason: str) -> tuple[dict[str, object], np.ndarray]:
    estimate = None if not values else float(np.mean([np.mean(cluster) for cluster in values.values()]))
    return ({"estimate": estimate, "lower_95": None, "upper_95": None,
             "n_eff": len(values), "draws": 0, "resampling_unit": "seed_cluster",
             "inferential_status": reason},
            np.asarray([None] * BOOTSTRAP_DRAWS, dtype=object))


def _registered_effects(rows: list[dict[str, object]]) -> tuple[dict, dict, dict, dict]:
    effects: dict[str, dict[str, dict[str, object]]] = {}
    sensitivity: dict[str, dict[str, object]] = {}
    draw_columns: dict[str, np.ndarray] = {}
    plan_columns: dict[str, np.ndarray | None] = {}
    augmented = [{**row, "total_wakes": row.get("control_wakes", 0) + row.get("motion_wakes", 0) + row.get("semantic_wakes", 0)} for row in rows]
    for comparator in ("R0", "R1", "R2"):
        effects[comparator] = {}
        for metric in ("mission_success", "safety_composite", "progress", "total_wakes"):
            name = f"R3-{comparator}:{metric}"
            values = _cluster_values(augmented, "R3", comparator, metric)
            seeds = sorted(values)
            plan = _bootstrap_plan(seeds, size=len(seeds)) if seeds else np.empty((BOOTSTRAP_DRAWS, 0), dtype=int)
            effect, draws = _effect(values, plan)
            effects[comparator][metric] = effect
            draw_columns[name] = draws
            plan_columns[name] = plan
    expected_sensitivity_seeds = list(range(20262301, 20262306))
    for metric in ("mission_success", "progress"):
        name = f"P4-P6:{metric}"
        values = _sensitivity_values(rows, metric)
        if sorted(values) == expected_sensitivity_seeds:
            plan = _balanced_sensitivity_plan(expected_sensitivity_seeds)
            effect, draws = _effect(values, plan)
        else:
            plan = None
            effect, draws = _descriptive_without_inference(values, "NOT_RUN_EXPECTED_SENSITIVITY_N_EFF_MISSING")
        sensitivity[metric] = effect
        draw_columns[name] = draws
        plan_columns[name] = plan
    return effects, sensitivity, draw_columns, plan_columns


def _formal_disposition(counts: dict[str, int], gates: dict[str, object]) -> str:
    if sum(counts.values()) != 540 or counts.get("INVALID_EXECUTION", 0) != 0:
        return "INVALID_EXPERIMENT"
    passed = all(
        bool(value)
        for key, value in gates.items()
        if key != "worst_R3_minus_R2_family_severity_success"
    )
    return (
        "SUPPORTS_BOUNDED_DIRECT_HIERARCHY_REPLICATION"
        if passed else "DOES_NOT_SUPPORT_BOUNDED_DIRECT_HIERARCHY_REPLICATION"
    )


def _svg(title: str, labels: list[str], series: list[tuple[str, list[float], str]], *, y_min: float = 0.0, y_max: float = 1.0) -> bytes:
    width, height = 760, 420
    left, top, plot_w, plot_h = 70, 55, 630, 290
    group_w = plot_w / len(labels)
    bar_w = min(36.0, group_w / (len(series) + 1))
    zero_y = top + plot_h - ((0.0 - y_min) / (y_max - y_min)) * plot_h
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
             '<rect width="100%" height="100%" fill="#ffffff"/>',
             f'<text x="380" y="28" text-anchor="middle" font-family="sans-serif" font-size="18">{title}</text>',
             f'<line x1="{left}" y1="{zero_y:.2f}" x2="{left+plot_w}" y2="{zero_y:.2f}" stroke="#222"/>']
    for index, label in enumerate(labels):
        center = left + group_w * (index + .5)
        parts.append(f'<text x="{center:.2f}" y="{top+plot_h+24}" text-anchor="middle" font-family="sans-serif" font-size="12">{label}</text>')
        for series_index, (_, values, color) in enumerate(series):
            value = values[index]
            scaled = (value - y_min) / (y_max - y_min)
            value_y = top + plot_h - max(0.0, min(1.0, scaled)) * plot_h
            bar_h = abs(zero_y - value_y)
            x = center + (series_index - (len(series) - 1) / 2) * bar_w - bar_w * .42
            parts.append(f'<rect x="{x:.2f}" y="{min(zero_y,value_y):.2f}" width="{bar_w*.84:.2f}" height="{bar_h:.2f}" fill="{color}"/>')
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
    augmented = [{**row, "total_wakes": row.get("control_wakes", 0) + row.get("motion_wakes", 0) + row.get("semantic_wakes", 0)} for row in rows]
    effects, sensitivity, draw_columns, plan_columns = _registered_effects(rows)
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
        row = {"draw_id": index}
        row.update({
            f"{name}:sampled_seeds": "" if plan is None else "|".join(map(str, plan[index]))
            for name, plan in plan_columns.items()
        })
        row.update({
            name: "" if values[index] is None else float(values[index])
            for name, values in draw_columns.items()
        })
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
    heterogeneity = min(
        float(r3["success_rate"]) - float(other["success_rate"])
        for r3 in family_rows if r3["architecture"] == "R3"
        for other in family_rows
        if other["family"] == r3["family"]
        and other["severity"] == r3["severity"]
        and other["architecture"] == "R2"
    )
    def lower_pass(effect: dict[str, object], threshold: float) -> bool:
        value = effect["lower_95"]
        return isinstance(value, (int, float)) and float(value) >= threshold

    def upper_pass(effect: dict[str, object], threshold: float, *, strict: bool = False) -> bool:
        value = effect["upper_95"]
        return isinstance(value, (int, float)) and (float(value) < threshold if strict else float(value) <= threshold)

    registered_gates = {
        "primary_n_eff_exactly_10": all(
            effects[name][metric]["n_eff"] == 10
            for name in ("R0", "R1", "R2")
            for metric in ("mission_success", "safety_composite", "progress", "total_wakes")
        ),
        "sensitivity_n_eff_exactly_5": all(
            sensitivity[metric]["n_eff"] == 5 for metric in ("mission_success", "progress")
        ),
        "success_noninferiority_all_comparators": all(
            lower_pass(effects[name]["mission_success"], -.10) for name in ("R0", "R1", "R2")
        ),
        "safety_noninferiority_all_comparators": all(
            upper_pass(effects[name]["safety_composite"], .10) for name in ("R0", "R1", "R2")
        ),
        "progress_noninferiority_all_comparators": all(
            lower_pass(effects[name]["progress"], -.05) for name in ("R0", "R1", "R2")
        ),
        "wake_reduction_vs_fixed_R2": upper_pass(effects["R2"]["total_wakes"], 0.0, strict=True),
        "worst_R3_minus_R2_family_severity_success": heterogeneity,
        "heterogeneity_threshold_pass": heterogeneity >= -.20,
    }
    formal_disposition = _formal_disposition(counts, registered_gates)
    supports = formal_disposition == "SUPPORTS_BOUNDED_DIRECT_HIERARCHY_REPLICATION"
    report = {"schema_version": 3, "scope": "BOUNDED_DIRECT_HIERARCHY_REPLICATION",
        "formal_disposition": formal_disposition,
        "confirmatory_support": supports, "causal_lowest_claim": False, "matrix_total": 540, "dispositions": counts,
        "chronology": {"exploratory_reference": "Exp13 informed this frozen replication", "replication": "fresh 202623 seed namespace; no outcome-driven tuning"},
        "effects": effects, "controller_sensitivity_P4_minus_P6": sensitivity,
        "registered_gate_evaluation": registered_gates,
        "worst_r3_cell_success_rate": worst, "bootstrap": {
            "seed": BOOTSTRAP_SEED, "draws": BOOTSTRAP_DRAWS,
            "primary_n_eff_actual": sorted({effects[name][metric]["n_eff"] for name in effects for metric in effects[name]}),
            "sensitivity_n_eff_actual": sorted({sensitivity[metric]["n_eff"] for metric in sensitivity}),
            "primary_expected_n_eff": 10, "sensitivity_expected_n_eff": 5,
            "primary_plan": "PCG64 seed-cluster bootstrap",
            "sensitivity_plan": "lexicographic 5^5 Cartesian product repeated three times plus integer linspace indices 0..3124 for 625 rows",
        },
        "portability_limit": "The full physical tick/contact/command trace root remains local and is not included; its recursive inventory and selected full working/nonworking episodes are portable.",
        "reconstruction_scope": "All compact statistics, tables, bootstrap draws, SVGs and PNGs reconstruct from tracked dispositions; only selected episodes permit raw-physics rescoring."}
    _write(destination / "report.json", canonical_bytes(report))
    markdown = f"# Exp15 clean direct-hierarchy replication\n\n**Formal disposition: {report['formal_disposition']}. No causal-lowest claim.**\n\nThis preregistered replication was informed by exploratory Exp13 and used a fresh 202623 seed namespace without outcome-driven tuning. The portable pack contains all 540 dispositions and reconstructs every derived byte. {report['portability_limit']}\n"
    _write(destination / "REPORT.md", markdown.encode("ascii"))
    style = {"schema_version": 1, "renderer": "rsvg-convert", "canvas": [760,420], "font": "sans-serif", "colors": {"R0":"#777777","R1":"#55a868","R2":"#c44e52","R3":"#4c72b0","P4":"#8172b2"}}
    _write(destination / "graphs/style.json", canonical_bytes(style))
    arch = {item["architecture"]: item for item in summary if item["matrix_role"] == "PRIMARY"}
    graph_specs = {
        "success-progress": ("Primary success and progress", ["R0","R1","R2","R3"], [("success",[arch[a]["success_rate"] for a in ("R0","R1","R2","R3")],"#4c72b0"),("progress",[arch[a]["mean_progress"] for a in ("R0","R1","R2","R3")],"#55a868")], 0.0, 1.0),
        "wake-profiles": ("Primary wake profiles", ["R0","R1","R2","R3"], [("mean_wakes",[arch[a]["mean_wakes"] for a in ("R0","R1","R2","R3")],"#8172b2")], 0.0, 2.5),
        "family-heterogeneity": ("R3 mission success by family", [name[:10] for name in sorted({r["family"] for r in family_rows})], [(sev,[next(float(r["success_rate"]) for r in family_rows if r["architecture"]=="R3" and r["family"]==fam and r["severity"]==sev) for fam in sorted({r["family"] for r in family_rows})],color) for sev,color in (("LOW","#4c72b0"),("HIGH","#c44e52"))], 0.0, 1.0),
        "controller-sensitivity": ("R3 controller sensitivity (P4 minus P6)", ["success","progress"], [("P4-P6",[sensitivity["mission_success"]["estimate"],sensitivity["progress"]["estimate"]],"#8172b2")], -0.5, 0.1),
    }
    plot_rows = []
    for name, (_, labels, series, _, _) in graph_specs.items():
        for series_name, values, _ in series:
            for label, value in zip(labels, values, strict=True):
                plot_rows.append({"graph": name, "category": label, "series": series_name, "value": value})
    _write(destination / "graphs/plot-data.csv", _csv_bytes(("graph","category","series","value"), plot_rows))
    for name, (title, labels, series, y_min, y_max) in graph_specs.items():
        svg = _svg(title, labels, series, y_min=y_min, y_max=y_max)
        _write(destination / f"graphs/{name}.svg", svg)
        subprocess.run(("rsvg-convert", str(destination / f"graphs/{name}.svg"), "-o", str(destination / f"graphs/{name}.png")), check=True)


def _raw_inventory_lookup(pack: Path) -> dict[str, dict[str, object]]:
    payload = (pack / "inputs/local-raw-inventory.json").read_bytes()
    if _sha(payload) != EXPECTED_RAW_INVENTORY_SHA256:
        raise RuntimeError("local raw inventory binding mismatch")
    document = json.loads(payload)
    return {item["path"]: item for item in document["files"]}


def _selected_annotations(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    population = sorted(
        (
            row for row in rows
            if row["disposition"] == "COMPLETE"
            and row["matrix_role"] == "PRIMARY"
            and row["architecture"] == "R3"
            and row["controller_id"] == "P6-res0p5-slew48"
        ),
        key=lambda row: str(row["episode_id"]),
    )
    predicates = {
        "working": lambda row: bool(row["mission_success"]) and not bool(row["safety_composite"]),
        "nonworking": lambda row: not bool(row["mission_success"]) or bool(row["safety_composite"]),
    }
    annotations = []
    for label, predicate in predicates.items():
        row = next((item for item in population if predicate(item)), None)
        annotations.append({
            "label": label,
            "category_status": "PRESENT" if row is not None else "ABSENT",
            "selection_population": "PRIMARY_P6_R3_COMPLETE",
            "episode_id": None if row is None else row["episode_id"],
            "mission_success": None if row is None else row["mission_success"],
            "safety_composite": None if row is None else row["safety_composite"],
            "progress": None if row is None else row["progress"],
            "selection_rule": "first lexicographic matching PRIMARY P6 R3 COMPLETE row; explicit ABSENT if no match",
        })
    return annotations


def _validate_exact_closure(pack: Path, rows: list[dict[str, object]], manifest: dict[str, object]) -> None:
    if set(manifest) != PACK_MANIFEST_KEYS or manifest.get("schema_version") != 1:
        raise RuntimeError("compact evidence schema mismatch")
    expected_dispositions = {item.episode_id for item in matrix_specs()}
    complete_ids = {str(row["episode_id"]) for row in rows if row["disposition"] == "COMPLETE"}
    manifest_ids = {path.stem for path in (pack / "inputs/manifests").glob("*.json")}
    if manifest_ids != complete_ids:
        raise RuntimeError("compact manifest identity mismatch")
    annotations = json.loads((pack / "inputs/sample-annotations.json").read_text())
    if annotations != _selected_annotations(rows):
        raise RuntimeError("compact deterministic selection mismatch")
    expected = {
        "pack-manifest.json", "inputs/freeze.json", "inputs/preflight-index.json",
        "inputs/local-raw-inventory.json", "inputs/sample-annotations.json", *DERIVED_PATHS,
    }
    expected.update(f"inputs/dispositions/{episode_id}.json" for episode_id in expected_dispositions)
    expected.update(f"inputs/manifests/{episode_id}.json" for episode_id in complete_ids)
    for annotation in annotations:
        if annotation["category_status"] == "ABSENT":
            if annotation["episode_id"] is not None:
                raise RuntimeError("compact absent sample has episode identity")
            continue
        episode_id = annotation["episode_id"]
        episode_manifest = json.loads((pack / "inputs/manifests" / f"{episode_id}.json").read_text())
        if set(episode_manifest) != {"schema_version", "episode_id", "seed", "injection_tick", "files"} or episode_manifest.get("schema_version") != 1:
            raise RuntimeError("compact episode manifest schema mismatch")
        members = {"manifest.json", *(item["path"] for item in episode_manifest["files"])}
        if any(set(item) != {"path", "bytes", "sha256"} for item in episode_manifest["files"]):
            raise RuntimeError("compact episode member schema mismatch")
        expected.update(f"inputs/selected-episodes/{annotation['label']}/{member}" for member in members)
    actual = {item["path"] for item in tree_inventory(pack)}
    if actual != expected:
        raise RuntimeError("compact evidence root allowlist mismatch")


def reseal_inventory_for_test(pack: Path) -> None:
    manifest = {"schema_version": 1, "external_binding": "git tracked pack plus expected raw inventory hash", "files": tree_inventory(pack, exclude_manifest=True)}
    _write(pack / "pack-manifest.json", canonical_bytes(manifest))


def publish_compact_pack(raw_root: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    (destination / "inputs").mkdir()
    shutil.copyfile(raw_root / "freeze.json", destination / "inputs/freeze.json")
    shutil.copyfile(raw_root / "preflight/preflight-index.json", destination / "inputs/preflight-index.json")
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
    annotations = _selected_annotations(rows)
    for annotation in annotations:
        if annotation["category_status"] == "ABSENT":
            continue
        label = annotation["label"]
        row = next(row for row in rows if row["episode_id"] == annotation["episode_id"])
        shutil.copytree(raw_root / "raw/episodes" / row["episode_id"], destination / "inputs/selected-episodes" / label)
    _write(destination / "inputs/sample-annotations.json", canonical_bytes(annotations))
    reconstruct_derived(destination, destination / "derived")
    reseal_inventory_for_test(destination)


def verify_compact_pack(pack: Path) -> dict[str, object]:
    manifest_payload = (pack / "pack-manifest.json").read_bytes()
    manifest = json.loads(manifest_payload.decode("ascii"))
    if canonical_bytes(manifest) != manifest_payload or manifest.get("files") != tree_inventory(pack, exclude_manifest=True):
        raise RuntimeError("compact evidence inventory mismatch")
    rows = _rows(pack)
    expected_keys = {"COMPLETE": COMPLETE_KEYS, "NOT_RUN": NOT_RUN_KEYS, "INVALID_EXECUTION": INVALID_KEYS}
    for row in rows:
        if set(row) != expected_keys[row["disposition"]]:
            raise RuntimeError("compact disposition schema mismatch")
    _validate_exact_closure(pack, rows, manifest)
    freeze_payload = (pack / "inputs/freeze.json").read_bytes()
    if _sha(freeze_payload) != EXPECTED_FREEZE_SHA256:
        raise RuntimeError("compact freeze binding mismatch")
    raw_lookup = _raw_inventory_lookup(pack)
    preflight_payload = (pack / "inputs/preflight-index.json").read_bytes()
    preflight = json.loads(preflight_payload.decode("ascii"))
    if (
        canonical_bytes(preflight) != preflight_payload
        or preflight.get("schema_version") != 1
        or preflight.get("stage") != "FULL_MATRIX_PREFLIGHT_COMPLETE_BEFORE_OUTCOME"
        or preflight.get("total") != 540
        or sum(preflight.get(name, -541) for name in ("READY", "NOT_RUN", "INVALID_PREFLIGHT")) != 540
        or len(preflight.get("files", ())) != 540
    ):
        raise RuntimeError("compact preflight schema mismatch")
    preflight_item = raw_lookup.get("preflight/preflight-index.json")
    if preflight_item is None or preflight_item["sha256"] != _sha(preflight_payload):
        raise RuntimeError("compact preflight substitution against raw inventory")
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
    annotations = json.loads((pack / "inputs/sample-annotations.json").read_text())
    for annotation in annotations:
        if annotation["category_status"] == "ABSENT":
            continue
        label = annotation["label"]
        episode_id = annotation["episode_id"]
        for path in sorted((pack / "inputs/selected-episodes" / label).glob("*")):
            key = f"raw/episodes/{episode_id}/{path.name}"
            item = raw_lookup.get(key)
            if item is None or item["sha256"] != _sha(path.read_bytes()):
                raise RuntimeError("selected raw substitution against raw inventory")
    with tempfile.TemporaryDirectory() as temporary:
        rebuilt = Path(temporary) / "derived"
        reconstruct_derived(pack, rebuilt)
        if tree_inventory(rebuilt) != tree_inventory(pack / "derived"):
            raise RuntimeError("derived reconstruction mismatch")
    counts = {name: sum(row["disposition"] == name for row in rows) for name in ("COMPLETE", "NOT_RUN", "INVALID_EXECUTION")}
    return {"status": "PASS", "dispositions": counts, "pack_manifest_sha256": _sha(manifest_payload)}


__all__ = ["canonical_bytes", "publish_compact_pack", "reconstruct_derived", "reseal_inventory_for_test", "tree_inventory", "verify_compact_pack"]
