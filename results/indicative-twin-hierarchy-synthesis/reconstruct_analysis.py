#!/usr/bin/env python3
"""Reconstruct the indicative hierarchy synthesis from the two frozen runs.

No network access or source-tree code is required.  All generated analysis
artifacts are deterministic for a fixed pair of raw run roots.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


RUNS = ("a", "b")
VARIANTS = ("T0", "T1", "T2", "T3", "T4")
CONTRASTS = (("T3-T2", "T3", "T2"), ("T4-T3", "T4", "T3"))
BOOTSTRAP_DRAWS = 10_000
Z_975 = 1.959963984540054
ROOT_NAME = "indicative-twin-hierarchy-synthesis"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def write_json(path: Path, value: Any) -> None:
    path.write_text(stable_json(value) + "\n", encoding="utf-8")


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def fmt(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}"


def wilson(successes: int, total: int) -> tuple[float, float]:
    if not total:
        return (float("nan"), float("nan"))
    p = successes / total
    den = 1.0 + (Z_975 * Z_975) / total
    center = (p + (Z_975 * Z_975) / (2 * total)) / den
    delta = Z_975 * math.sqrt((p * (1 - p) / total) + (Z_975 * Z_975) / (4 * total * total)) / den
    return (center - delta, center + delta)


def percentile_sorted(values: list[float], p: float) -> float:
    """Linear percentile, matching an explicitly documented deterministic rule."""
    if not values:
        return float("nan")
    index = (len(values) - 1) * p
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def bootstrap_case_mean(deltas: list[int], seed: str) -> tuple[float, float]:
    rng = random.Random(seed)
    size = len(deltas)
    draws = []
    for _ in range(BOOTSTRAP_DRAWS):
        draws.append(sum(deltas[rng.randrange(size)] for _ in range(size)) / size)
    draws.sort()
    return percentile_sorted(draws, 0.025), percentile_sorted(draws, 0.975)


def bootstrap_run_cluster(
    deltas_by_run: dict[str, list[int]], seed: str
) -> tuple[float, float]:
    """Resample runs first, then cases within each selected run.

    This treats the two complete experiment runs as the top-level clusters and
    retains the 400-case within-run cluster size.  With only two clusters this
    interval is descriptive/sensitivity evidence, not robust population inference.
    """
    rng = random.Random(seed)
    labels = sorted(deltas_by_run)
    size = len(deltas_by_run[labels[0]])
    draws = []
    for _ in range(BOOTSTRAP_DRAWS):
        selected_runs = [labels[rng.randrange(len(labels))] for _ in labels]
        total = 0
        for run in selected_runs:
            values = deltas_by_run[run]
            total += sum(values[rng.randrange(size)] for _ in range(size))
        draws.append(total / (len(selected_runs) * size))
    draws.sort()
    return percentile_sorted(draws, 0.025), percentile_sorted(draws, 0.975)


def event_stratum(case: dict[str, Any]) -> str:
    types = sorted(event["event_type"] for event in case["dynamic_events"])
    return "+".join(types) if types else "NONE"


def load_run(project_root: Path, run: str) -> dict[str, Any]:
    root = project_root / "results" / f"indicative-twin-hierarchy-{run}"
    paths = {
        "raw_manifest": root / "raw" / "manifest.json",
        "raw_cases": root / "raw" / "cases.jsonl",
        "raw_outcomes": root / "raw" / "outcomes.jsonl",
        "derived_metrics": root / "derived" / "metrics.json",
        "derived_recipe": root / "derived" / "recipe.json",
        "derived_sample_index": root / "derived" / "sample-index.json",
    }
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    cases = [json.loads(line) for line in paths["raw_cases"].read_text(encoding="utf-8").splitlines()]
    outcomes = [json.loads(line) for line in paths["raw_outcomes"].read_text(encoding="utf-8").splitlines()]
    loaded = {
        "run": run,
        "root": root,
        "paths": paths,
        "manifest": json.loads(paths["raw_manifest"].read_text(encoding="utf-8")),
        "cases": cases,
        "outcomes": outcomes,
        "derived_metrics": json.loads(paths["derived_metrics"].read_text(encoding="utf-8")),
        "recipe": json.loads(paths["derived_recipe"].read_text(encoding="utf-8")),
        "sample_index": json.loads(paths["derived_sample_index"].read_text(encoding="utf-8")),
    }
    validate_run(loaded)
    return loaded


def validate_run(run_data: dict[str, Any]) -> None:
    cases = run_data["cases"]
    outcomes = run_data["outcomes"]
    manifest = run_data["manifest"]
    if len(cases) != manifest["case_count"] or len(outcomes) != manifest["outcome_count"]:
        raise ValueError(f"manifest count mismatch in run {run_data['run']}")
    case_hashes = {case["case_sha256"] for case in cases}
    if len(case_hashes) != len(cases):
        raise ValueError(f"non-unique case SHA in run {run_data['run']}")
    grouped = Counter((outcome["case_sha256"], outcome["variant"]) for outcome in outcomes)
    if set(outcome["case_sha256"] for outcome in outcomes) != case_hashes:
        raise ValueError(f"outcome/case identities disagree in run {run_data['run']}")
    if any(grouped[(case_sha, variant)] != 1 for case_sha in case_hashes for variant in VARIANTS):
        raise ValueError(f"not exactly one outcome per case/variant in run {run_data['run']}")
    recomputed = []
    for variant in VARIANTS:
        rows = [outcome for outcome in outcomes if outcome["variant"] == variant]
        recomputed.append((variant, sum(bool(row["success"]) for row in rows) / len(rows)))
    published = {row["variant"]: row["mission_success_fraction"] for row in run_data["derived_metrics"]["rows"]}
    for variant, success_rate in recomputed:
        if not math.isclose(success_rate, published[variant], abs_tol=1e-12):
            raise ValueError(f"derived success rate mismatch for {run_data['run']} {variant}")


def outcome_lookup(run_data: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["case_sha256"], row["variant"]): row for row in run_data["outcomes"]}


def summarise(rows: list[dict[str, Any]], run: str, variant: str, dimension: str, label: str) -> dict[str, Any]:
    n = len(rows)
    successes = sum(bool(row["success"]) for row in rows)
    low, high = wilson(successes, n)
    return {
        "run": run,
        "variant": variant,
        dimension: label,
        "cases": n,
        "successes": successes,
        "mission_success_fraction": fmt(successes / n if n else float("nan"), 6),
        "success_wilson95_low": fmt(low, 6),
        "success_wilson95_high": fmt(high, 6),
        "forbidden_region_violations": sum(row["forbidden_region_violations"] for row in rows),
        "invalid_affordance_choices": sum(row["invalid_affordance_choices"] for row in rows),
        "invalid_initial_plans": sum(bool(row["invalid_initial_plan"]) for row in rows),
        "replans": sum(bool(row["replanned"]) for row in rows),
        "stale_belief_failures": sum(row["stale_belief_failures"] for row in rows),
        "mean_replanning_latency_us": fmt(mean(row["replanning_latency_us"] for row in rows), 6),
        "mean_route_cost_m": fmt(mean(row["route_cost_m"] for row in rows), 6),
        "mean_context_facts": fmt(mean(row["context_fact_count"] for row in rows), 6),
        "mean_geometry_queries": fmt(mean(row["geometry_query_count"] for row in rows), 6),
        "mean_semantic_queries": fmt(mean(row["semantic_query_count"] for row in rows), 6),
    }


def make_variant_summary(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for data in runs:
        for variant in VARIANTS:
            subset = [outcome for outcome in data["outcomes"] if outcome["variant"] == variant]
            rows.append(summarise(subset, data["run"], variant, "scope", "ALL_CASES"))
    return rows


def make_dimension_summary(runs: list[dict[str, Any]], dimension: str) -> list[dict[str, Any]]:
    rows = []
    for data in runs:
        cases = {case["case_sha256"]: case for case in data["cases"]}
        labels = sorted({case[dimension] if dimension == "mission" else event_stratum(case) for case in data["cases"]})
        for variant in VARIANTS:
            for label in labels:
                subset = [
                    outcome
                    for outcome in data["outcomes"]
                    if outcome["variant"] == variant
                    and (cases[outcome["case_sha256"]][dimension] if dimension == "mission" else event_stratum(cases[outcome["case_sha256"]])) == label
                ]
                rows.append(summarise(subset, data["run"], variant, dimension, label))
    return rows


def make_case_tables(runs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    case_rows: list[dict[str, Any]] = []
    outcome_rows: list[dict[str, Any]] = []
    paired_rows: list[dict[str, Any]] = []
    for data in runs:
        lookups = outcome_lookup(data)
        for case in sorted(data["cases"], key=lambda item: (item["seed"], item["mission"], item["case_sha256"])):
            source = {
                "run": data["run"],
                "seed": case["seed"],
                "mission": case["mission"],
                "case_sha256": case["case_sha256"],
                "event_stratum": event_stratum(case),
                "event_count": len(case["dynamic_events"]),
                "event_types_json": stable_json([event["event_type"] for event in case["dynamic_events"]]),
                "event_payloads_json": stable_json([event["payload"] for event in case["dynamic_events"]]),
                "history_present": str(bool(case["history"])).lower(),
                "history_event_count": len(case["history"]),
                "instruction": case["instruction"],
                "case_source_path": f"results/indicative-twin-hierarchy-{data['run']}/raw/cases.jsonl",
            }
            case_rows.append(source)
            for variant in VARIANTS:
                outcome = lookups[(case["case_sha256"], variant)]
                outcome_rows.append(
                    {
                        **source,
                        "variant": variant,
                        "outcome_sha256": outcome["outcome_sha256"],
                        "success": str(bool(outcome["success"])).lower(),
                        "terminal_reason": outcome["terminal_reason"],
                        "target_id": outcome["target_id"],
                        "invalid_initial_plan": str(bool(outcome["invalid_initial_plan"])).lower(),
                        "forbidden_region_violations": outcome["forbidden_region_violations"],
                        "invalid_affordance_choices": outcome["invalid_affordance_choices"],
                        "replanned": str(bool(outcome["replanned"])).lower(),
                        "stale_belief_failures": outcome["stale_belief_failures"],
                        "replanning_latency_us": outcome["replanning_latency_us"],
                        "route_cost_m": outcome["route_cost_m"],
                        "context_fact_count": outcome["context_fact_count"],
                        "geometry_query_count": outcome["geometry_query_count"],
                        "semantic_query_count": outcome["semantic_query_count"],
                        "planning_operations": outcome["planning_operations"],
                        "initial_route_json": stable_json(outcome["initial_route"]),
                        "final_route_json": stable_json(outcome["final_route"]),
                        "actions_json": stable_json(outcome["actions"]),
                        "outcome_source_path": f"results/indicative-twin-hierarchy-{data['run']}/raw/outcomes.jsonl",
                    }
                )
            for contrast, high_variant, low_variant in CONTRASTS:
                high = lookups[(case["case_sha256"], high_variant)]
                low = lookups[(case["case_sha256"], low_variant)]
                paired_rows.append(
                    {
                        **source,
                        "contrast": contrast,
                        "higher_variant": high_variant,
                        "lower_variant": low_variant,
                        "higher_success": int(bool(high["success"])),
                        "lower_success": int(bool(low["success"])),
                        "paired_success_difference": int(bool(high["success"])) - int(bool(low["success"])),
                        "higher_outcome_sha256": high["outcome_sha256"],
                        "lower_outcome_sha256": low["outcome_sha256"],
                    }
                )
    return case_rows, outcome_rows, paired_rows


def make_paired_summary(paired_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for contrast, high_variant, low_variant in CONTRASTS:
        by_run = {run: [row for row in paired_rows if row["run"] == run and row["contrast"] == contrast] for run in RUNS}
        for run in RUNS:
            rows = by_run[run]
            deltas = [row["paired_success_difference"] for row in rows]
            high_successes = sum(row["higher_success"] for row in rows)
            low_successes = sum(row["lower_success"] for row in rows)
            low, high = bootstrap_case_mean(deltas, f"exp05-{run}-{contrast}-case-bootstrap-v1")
            summaries.append(
                {
                    "scope": f"run_{run}", "contrast": contrast, "higher_variant": high_variant, "lower_variant": low_variant,
                    "cases": len(rows), "runs_clustered": 1, "higher_successes": high_successes, "lower_successes": low_successes,
                    "paired_success_difference": fmt(mean(deltas), 6), "bootstrap95_low": fmt(low, 6), "bootstrap95_high": fmt(high, 6),
                    "bootstrap_draws": BOOTSTRAP_DRAWS, "bootstrap_method": "paired_case_resample_within_run",
                    "bootstrap_seed": f"exp05-{run}-{contrast}-case-bootstrap-v1",
                    "cluster_transparency": "Single frozen run; cases are resampled as matched pairs.",
                }
            )
        pooled_rows = [row for run in RUNS for row in by_run[run]]
        deltas_by_run = {run: [row["paired_success_difference"] for row in by_run[run]] for run in RUNS}
        low, high = bootstrap_run_cluster(deltas_by_run, f"exp05-pooled-{contrast}-run-cluster-bootstrap-v1")
        summaries.append(
            {
                "scope": "pooled_two_runs", "contrast": contrast, "higher_variant": high_variant, "lower_variant": low_variant,
                "cases": len(pooled_rows), "runs_clustered": len(RUNS),
                "higher_successes": sum(row["higher_success"] for row in pooled_rows),
                "lower_successes": sum(row["lower_success"] for row in pooled_rows),
                "paired_success_difference": fmt(mean(row["paired_success_difference"] for row in pooled_rows), 6),
                "bootstrap95_low": fmt(low, 6), "bootstrap95_high": fmt(high, 6), "bootstrap_draws": BOOTSTRAP_DRAWS,
                "bootstrap_method": "two_stage_run_cluster_then_paired_case_resample",
                "bootstrap_seed": f"exp05-pooled-{contrast}-run-cluster-bootstrap-v1",
                "cluster_transparency": "Two frozen runs are resampled with replacement before 400 matched cases within each selected run; n_clusters=2, so this is a descriptive sensitivity interval.",
            }
        )
    return summaries


def choose_examples(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for data in runs:
        lookup = outcome_lookup(data)
        for case in data["cases"]:
            outcomes = {variant: lookup[(case["case_sha256"], variant)] for variant in VARIANTS}
            candidates.append((data, case, outcomes))
    candidates.sort(key=lambda item: (item[0]["run"], item[1]["seed"], item[1]["mission"], item[1]["case_sha256"]))
    conditions = (
        ("WORKING", "First lexicographic case where both T3 and T4 succeed.", lambda o: o["T3"]["success"] and o["T4"]["success"]),
        ("NONWORKING", "First lexicographic case where both T3 and T4 fail.", lambda o: not o["T3"]["success"] and not o["T4"]["success"]),
        ("DISAGREEMENT", "First lexicographic case where T3 and T4 disagree.", lambda o: bool(o["T3"]["success"]) != bool(o["T4"]["success"])),
    )
    examples = []
    for label, selection, predicate in conditions:
        data, case, outcomes = next(candidate for candidate in candidates if predicate(candidate[2]))
        examples.append({
            "label": label, "selection": selection, "run": data["run"], "seed": case["seed"], "mission": case["mission"],
            "instruction": case["instruction"], "event_stratum": event_stratum(case), "case_sha256": case["case_sha256"],
            "case_source_path": f"results/indicative-twin-hierarchy-{data['run']}/raw/cases.jsonl",
            "outcome_source_path": f"results/indicative-twin-hierarchy-{data['run']}/raw/outcomes.jsonl",
            "outcomes": {
                variant: {
                    "outcome_sha256": outcome["outcome_sha256"], "success": outcome["success"],
                    "terminal_reason": outcome["terminal_reason"], "target_id": outcome["target_id"],
                    "actions": outcome["actions"], "final_route": outcome["final_route"],
                }
                for variant, outcome in outcomes.items()
            },
        })
    return examples


def svg_header(width: int, height: int, title: str) -> list[str]:
    return [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f"<title id=\"title\">{title}</title>",
        '<desc id="desc">Deterministic analysis graphic reconstructed from frozen outcomes.</desc>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#172033}.title{font-size:25px;font-weight:700}.label{font-size:15px}.small{font-size:12px}.axis{stroke:#526077;stroke-width:1.5}.grid{stroke:#d7dde7;stroke-width:1}.error{stroke:#172033;stroke-width:2}</style>',
    ]


def write_variant_svg(path: Path, rows: list[dict[str, Any]]) -> None:
    width, height, left, top, right, bottom = 1280, 760, 100, 110, 70, 125
    plot_w, plot_h = width - left - right, height - top - bottom
    colors = {"T0": "#9aa5b5", "T1": "#6fa8dc", "T2": "#7ec8b5", "T3": "#405cf5", "T4": "#e18d38"}
    lines = svg_header(width, height, "Mission success by hierarchy variant")
    lines += ['<text x="100" y="53" class="title">Mission success by hierarchy variant</text>', '<text x="100" y="78" class="label">Bars: exact success fraction; whiskers: Wilson 95% interval; 400 matched cases per run/variant.</text>']
    for tick in range(0, 11, 2):
        y = top + plot_h * (1 - tick / 10)
        lines.append(f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" class="grid"/>')
        lines.append(f'<text x="{left-12}" y="{y+5:.2f}" text-anchor="end" class="small">{tick * 10}%</text>')
    lines += [f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" class="axis"/>', f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" class="axis"/>']
    group_width = plot_w / 2
    bar_width = 68
    for run_i, run in enumerate(RUNS):
        group_center = left + group_width * (run_i + 0.5)
        lines.append(f'<text x="{group_center:.2f}" y="{height-bottom+43}" text-anchor="middle" class="label">Run {run.upper()} (seeds {80 if run == "a" else 160}–{159 if run == "a" else 239})</text>')
        for variant_i, variant in enumerate(VARIANTS):
            row = next(item for item in rows if item["run"] == run and item["variant"] == variant)
            rate, low, high = (float(row[key]) for key in ("mission_success_fraction", "success_wilson95_low", "success_wilson95_high"))
            x = group_center + (variant_i - 2) * (bar_width + 12) - bar_width / 2
            y = top + plot_h * (1 - rate)
            bar_h = plot_h * rate
            err_x = x + bar_width / 2
            err_top = top + plot_h * (1 - high)
            err_bottom = top + plot_h * (1 - low)
            lines += [
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width}" height="{bar_h:.2f}" rx="3" fill="{colors[variant]}"/>',
                f'<line x1="{err_x:.2f}" y1="{err_top:.2f}" x2="{err_x:.2f}" y2="{err_bottom:.2f}" class="error"/>',
                f'<line x1="{err_x-7:.2f}" y1="{err_top:.2f}" x2="{err_x+7:.2f}" y2="{err_top:.2f}" class="error"/>',
                f'<line x1="{err_x-7:.2f}" y1="{err_bottom:.2f}" x2="{err_x+7:.2f}" y2="{err_bottom:.2f}" class="error"/>',
                f'<text x="{err_x:.2f}" y="{y-11:.2f}" text-anchor="middle" class="small">{rate*100:.1f}%</text>',
                f'<text x="{err_x:.2f}" y="{height-bottom+22}" text-anchor="middle" class="small">{variant}</text>',
            ]
    lines += ['<text x="100" y="710" class="small">Source: indicative-twin-hierarchy-a and -b frozen raw outcomes. This is an architectural parallel, not evidence of three-level recovery.</text>', '</svg>']
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_effect_svg(path: Path, rows: list[dict[str, Any]]) -> None:
    width, height, left, top, right, bottom = 1280, 680, 240, 115, 80, 105
    plot_w, plot_h = width - left - right, height - top - bottom
    x_min, x_max = -0.03, 0.48
    def sx(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w
    lines = svg_header(width, height, "Paired mission-success differences")
    lines += ['<text x="100" y="53" class="title">Paired mission-success differences</text>', '<text x="100" y="78" class="label">Point: matched-case mean difference; whisker: deterministic 10,000-draw bootstrap 95% interval.</text>']
    for tick in (0.0, 0.1, 0.2, 0.3, 0.4):
        x = sx(tick)
        lines.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height-bottom}" class="grid"/>')
        lines.append(f'<text x="{x:.2f}" y="{height-bottom+28}" text-anchor="middle" class="small">{tick*100:.0f} pp</text>')
    zero = sx(0.0)
    lines.append(f'<line x1="{zero:.2f}" y1="{top}" x2="{zero:.2f}" y2="{height-bottom}" stroke="#172033" stroke-width="2"/>')
    display = [("T3−T2", "run_a"), ("T3−T2", "run_b"), ("T3−T2", "pooled_two_runs"), ("T4−T3", "run_a"), ("T4−T3", "run_b"), ("T4−T3", "pooled_two_runs")]
    for index, (contrast, scope) in enumerate(display):
        row = next(item for item in rows if item["contrast"].replace("-", "−") == contrast and item["scope"] == scope)
        y = top + (index + 0.5) * (plot_h / len(display))
        estimate, low, high = (float(row[key]) for key in ("paired_success_difference", "bootstrap95_low", "bootstrap95_high"))
        color = "#405cf5" if contrast == "T3−T2" else "#e18d38"
        lines += [
            f'<line x1="{sx(low):.2f}" y1="{y:.2f}" x2="{sx(high):.2f}" y2="{y:.2f}" stroke="{color}" stroke-width="5" stroke-linecap="round"/>',
            f'<circle cx="{sx(estimate):.2f}" cy="{y:.2f}" r="8" fill="{color}"/>',
            f'<text x="{left-18}" y="{y+5:.2f}" text-anchor="end" class="label">{contrast} · {scope.replace("_", " ")}</text>',
            f'<text x="{sx(high)+12:.2f}" y="{y+5:.2f}" class="small">{estimate*100:+.1f} pp [{low*100:+.1f}, {high*100:+.1f}]</text>',
        ]
    lines += ['<text x="240" y="625" class="small">Pooled intervals resample the two runs first, then paired cases within selected runs (n_clusters=2): descriptive sensitivity only.</text>', '</svg>']
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def results_markdown(variant_rows: list[dict[str, Any]], paired: list[dict[str, Any]]) -> str:
    by = {(row["run"], row["variant"]): row for row in variant_rows}
    pa = {(row["scope"], row["contrast"]): row for row in paired}
    lines = [
        "# Indicative Twin-Hierarchy Synthesis",
        "",
        "## Situation",
        "",
        "Two independently completed, frozen 400-case runs (A and B) compare T0–T4 variants of an indicative twin-hierarchy experiment. Each seed-by-mission case is evaluated once per variant, producing matched outcomes.",
        "",
        "## Methodology",
        "",
        "Success fractions are exact counts over 400 cases per run; uncertainty bars use Wilson 95% intervals. T3−T2 and T4−T3 are paired case-level success differences. Each run uses a deterministic 10,000-draw paired-case bootstrap. The pooled interval samples the two runs as clusters, then 400 matched cases within each selected run; with only two clusters it is transparent descriptive sensitivity analysis, not robust population inference.",
        "",
        "Canonical CSV/JSON data and SVG figures are authoritative, byte-stable raw-to-output reconstruction artifacts. The two published PNG figures are frozen, non-authoritative raster companions: their original Pillow rasterizer was not a declared project dependency, so clean reconstruction intentionally does not generate or claim to reproduce them. When the companion files are present in this publication directory, their existing bytes are recorded in `evidence_manifest.json` and `SHA256SUMS`.",
        "",
        "## Objective",
        "",
        "Assess whether the progressively richer representation, live-belief/history, and reactive-replanning layers coincide with better mission execution in these fixed scenarios.",
        "",
        "## Outcome",
        "",
        "| Run | T2 success | T3 success | T4 success | T3−T2 | T4−T3 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for run in RUNS:
        lines.append(f"| {run.upper()} | {float(by[(run, 'T2')]['mission_success_fraction'])*100:.2f}% | {float(by[(run, 'T3')]['mission_success_fraction'])*100:.2f}% | {float(by[(run, 'T4')]['mission_success_fraction'])*100:.2f}% | {float(pa[(f'run_{run}', 'T3-T2')]['paired_success_difference'])*100:+.2f} pp | {float(pa[(f'run_{run}', 'T4-T3')]['paired_success_difference'])*100:+.2f} pp |")
    lines += [
        "",
        f"Pooled matched effects are T3−T2 {float(pa[('pooled_two_runs', 'T3-T2')]['paired_success_difference'])*100:+.2f} pp (cluster bootstrap 95% [{float(pa[('pooled_two_runs', 'T3-T2')]['bootstrap95_low'])*100:+.2f}, {float(pa[('pooled_two_runs', 'T3-T2')]['bootstrap95_high'])*100:+.2f}]) and T4−T3 {float(pa[('pooled_two_runs', 'T4-T3')]['paired_success_difference'])*100:+.2f} pp (95% [{float(pa[('pooled_two_runs', 'T4-T3')]['bootstrap95_low'])*100:+.2f}, {float(pa[('pooled_two_runs', 'T4-T3')]['bootstrap95_high'])*100:+.2f}]).",
        "",
        "## Inference",
        "",
        "Across both completed runs, T3 substantially exceeds T2 in matched mission success, and T4 is modestly higher than T3. The same directional pattern occurs in both independent frozen runs. This supports an indicative architectural parallel: richer representation/live-belief/history and reactive replanning are associated with better execution in this benchmark.",
        "",
        "## Limits",
        "",
        "This is explicitly preliminary engineering evidence from a synthetic, fixed scenario family. It does not establish causal attribution to any individual layer, generalization beyond these missions, or a three-level recovery result. The pooled cluster interval has only two top-level runs. Read `data/`, `data/examples.json`, `evidence_manifest.json`, and the reconstruction script together for traceable detail.",
        "",
    ]
    return "\n".join(lines)


def evidence(project_root: Path, output: Path, runs: list[dict[str, Any]]) -> dict[str, Any]:
    inputs = []
    for data in runs:
        for name, path in sorted(data["paths"].items()):
            inputs.append({"run": data["run"], "role": name, "path": path.relative_to(project_root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    generated_names = {"evidence_manifest.json", "SHA256SUMS", "reconstruct_analysis.py", "test_reconstruct.py"}
    output_files = [
        path for path in sorted(output.rglob("*"))
        if path.is_file() and path.name not in generated_names and path.suffix.lower() != ".png" and "__pycache__" not in path.parts
    ]
    outputs = [{"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in output_files]
    companions = [
        {"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted((output / "graphs").glob("*.png"))
    ]
    return {
        "schema_version": "indicative-twin-hierarchy-synthesis-evidence-v1",
        "analysis_identity": {"script": "reconstruct_analysis.py", "bootstrap_draws": BOOTSTRAP_DRAWS, "bootstrap_interval": "percentile_2.5_to_97.5_linear_interpolation"},
        "inputs": inputs,
        "outputs": outputs,
        "non_authoritative_png_companions": companions,
        "png_reconstruction_policy": "PNG companions are authenticated when present but intentionally excluded from clean reconstruction; canonical data and SVG are the authoritative reproducible graph artifacts.",
        "self_hashing": "evidence_manifest.json is hashed in SHA256SUMS, a non-self-referential sidecar; SHA256SUMS itself is an index rather than a substantive analysis artifact.",
    }


def write_evidence(project_root: Path, output: Path, runs: list[dict[str, Any]]) -> None:
    manifest = evidence(project_root, output, runs)
    write_json(output / "evidence_manifest.json", manifest)
    static_source_names = {"reconstruct_analysis.py", "test_reconstruct.py"}
    all_files = [
        path for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS" and path.name not in static_source_names and "__pycache__" not in path.parts
    ]
    lines = [f"{sha256(path)}  {path.relative_to(output).as_posix()}" for path in all_files]
    (output / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def reconstruct(project_root: Path, output: Path) -> None:
    runs = [load_run(project_root, run) for run in RUNS]
    if output.exists():
        if output.resolve() == (project_root / "results" / ROOT_NAME).resolve():
            for child in ("data", "evidence_manifest.json", "SHA256SUMS", "RESULTS.md"):
                target = output / child
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
        else:
            raise FileExistsError(f"refusing to overwrite non-default output: {output}")
    (output / "data").mkdir(parents=True, exist_ok=True)
    (output / "graphs").mkdir(parents=True, exist_ok=True)
    variant_rows = make_variant_summary(runs)
    mission_rows = make_dimension_summary(runs, "mission")
    event_rows = make_dimension_summary(runs, "event_stratum")
    case_rows, outcome_rows, paired_case_rows = make_case_tables(runs)
    paired_rows = make_paired_summary(paired_case_rows)
    examples = choose_examples(runs)
    summary_fields = ["run", "variant", "scope", "cases", "successes", "mission_success_fraction", "success_wilson95_low", "success_wilson95_high", "forbidden_region_violations", "invalid_affordance_choices", "invalid_initial_plans", "replans", "stale_belief_failures", "mean_replanning_latency_us", "mean_route_cost_m", "mean_context_facts", "mean_geometry_queries", "mean_semantic_queries"]
    write_csv(output / "data" / "variant_summary.csv", summary_fields, variant_rows)
    write_csv(output / "data" / "mission_summary.csv", [*summary_fields[:2], "mission", *summary_fields[3:]], mission_rows)
    write_csv(output / "data" / "event_stratum_summary.csv", [*summary_fields[:2], "event_stratum", *summary_fields[3:]], event_rows)
    paired_fields = ["scope", "contrast", "higher_variant", "lower_variant", "cases", "runs_clustered", "higher_successes", "lower_successes", "paired_success_difference", "bootstrap95_low", "bootstrap95_high", "bootstrap_draws", "bootstrap_method", "bootstrap_seed", "cluster_transparency"]
    write_csv(output / "data" / "paired_differences.csv", paired_fields, paired_rows)
    case_fields = ["run", "seed", "mission", "case_sha256", "event_stratum", "event_count", "event_types_json", "event_payloads_json", "history_present", "history_event_count", "instruction", "case_source_path"]
    write_csv(output / "data" / "cases.csv", case_fields, case_rows)
    outcome_fields = [*case_fields, "variant", "outcome_sha256", "success", "terminal_reason", "target_id", "invalid_initial_plan", "forbidden_region_violations", "invalid_affordance_choices", "replanned", "stale_belief_failures", "replanning_latency_us", "route_cost_m", "context_fact_count", "geometry_query_count", "semantic_query_count", "planning_operations", "initial_route_json", "final_route_json", "actions_json", "outcome_source_path"]
    write_csv(output / "data" / "case_outcomes.csv", outcome_fields, outcome_rows)
    paired_case_fields = [*case_fields, "contrast", "higher_variant", "lower_variant", "higher_success", "lower_success", "paired_success_difference", "higher_outcome_sha256", "lower_outcome_sha256"]
    write_csv(output / "data" / "paired_case_differences.csv", paired_case_fields, paired_case_rows)
    write_json(output / "data" / "canonical_graph_data.json", {"variant_summary": variant_rows, "paired_differences": paired_rows, "mission_summary": mission_rows, "event_stratum_summary": event_rows})
    write_json(output / "data" / "examples.json", {"schema_version": "indicative-twin-hierarchy-synthesis-examples-v1", "examples": examples})
    write_variant_svg(output / "graphs" / "variant_success.svg", variant_rows)
    write_effect_svg(output / "graphs" / "paired_effects.svg", paired_rows)
    (output / "RESULTS.md").write_text(results_markdown(variant_rows, paired_rows), encoding="utf-8")
    write_evidence(project_root, output, runs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    reconstruct(args.project_root.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
