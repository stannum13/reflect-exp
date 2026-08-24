"""Deterministic analysis, decision gates, graph data, and figures."""

from __future__ import annotations

from collections import defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import struct
import zlib
from typing import Iterable, Mapping, Sequence

import numpy as np

from .contracts import Architecture, ScenarioDomain, canonical_bytes


def _eligible_primary(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [
        item for item in rows
        if not item.get("sensitivity", False)
        and item.get("controller_id") == "P6-res0p5-slew48"
        and item.get("attempt_outcome", "VALID") == "VALID"
        and item.get("terminal_disposition") != "INVALID_EVIDENCE"
    ]


def _rate(rows: Sequence[Mapping[str, object]], key: str = "eventual_success") -> float:
    return float(np.mean([float(bool(item[key])) for item in rows])) if rows else float("nan")


def evaluate_gates(rows: Sequence[Mapping[str, object]], *, expected_primary_count: int = 256) -> dict[str, object]:
    primary = _eligible_primary(rows)
    by_arch = {arch.value: [item for item in primary if item["architecture"] == arch.value] for arch in Architecture}
    r3 = by_arch["R3"]
    comparators = ("R0", "R1", "R2")

    def interventions(domain: Sequence[Mapping[str, object]], key: str) -> int:
        return sum(int(item.get(key, 0)) for item in domain)

    unsafe = {arch: interventions(domain, "unsafe_count") + interventions(domain, "forbidden_action_count") for arch, domain in by_arch.items()}
    g1 = all(unsafe["R3"] <= unsafe[item] for item in comparators)
    motion_semantic_r3 = [item for item in r3 if item["scenario_domain"] in {"MOTION", "SEMANTIC"}]
    motion_semantic_r0 = [item for item in by_arch["R0"] if item["scenario_domain"] in {"MOTION", "SEMANTIC"}]
    g2 = _rate(motion_semantic_r3) > _rate(motion_semantic_r0)
    g3 = interventions(r3, "semantic_replans") < interventions(by_arch["R1"], "semantic_replans") and _rate(r3) >= _rate(by_arch["R1"])
    control = {arch: [item for item in domain if item["scenario_domain"] == "CONTROL"] for arch, domain in by_arch.items()}
    g4 = (
        interventions(control["R3"], "semantic_replans") < interventions(control["R1"], "semantic_replans")
        and interventions(control["R3"], "motion_replans") < interventions(control["R2"], "motion_replans")
        and _rate(control["R3"]) >= max(_rate(control[item]) for item in comparators)
    )
    recoverable = [item for item in r3 if item["scenario_domain"] in {"CONTROL", "MOTION", "SEMANTIC"}]
    correct_fraction = _rate(recoverable, "lowest_sufficient_correct")
    loops = sum(int(bool(item.get("repeated_state_retry_loop"))) for item in r3)
    g5 = bool(recoverable) and correct_fraction >= 0.8 and loops == 0
    domain_differences: dict[str, dict[str, object]] = {}
    g6 = True
    for domain in ("CONTROL", "MOTION", "SEMANTIC"):
        r3_rate = _rate([item for item in r3 if item["scenario_domain"] == domain])
        comparator_rates = {
            arch: _rate([item for item in by_arch[arch] if item["scenario_domain"] == domain])
            for arch in comparators
        }
        best = sorted(comparator_rates, key=lambda arch: (-comparator_rates[arch], arch))[0]
        difference = r3_rate - comparator_rates[best]
        domain_differences[domain] = {"best_comparator": best, "r3_rate": r3_rate, "comparator_rate": comparator_rates[best], "difference": difference}
        g6 = g6 and difference >= 0.0

    complete = len(primary) == expected_primary_count
    gates = [
        {"gate": 1, "passed": g1, "evidence": {"unsafe_or_forbidden": unsafe}},
        {"gate": 2, "passed": g2, "evidence": {"r3_success": _rate(motion_semantic_r3), "r0_success": _rate(motion_semantic_r0)}},
        {"gate": 3, "passed": g3, "evidence": {"r3_semantic_wakeups": interventions(r3, "semantic_replans"), "r1_semantic_wakeups": interventions(by_arch["R1"], "semantic_replans"), "r3_success": _rate(r3), "r1_success": _rate(by_arch["R1"])}},
        {"gate": 4, "passed": g4, "evidence": {"r3_semantic_wakeups": interventions(control["R3"], "semantic_replans"), "r1_semantic_wakeups": interventions(control["R1"], "semantic_replans"), "r3_motion_replans": interventions(control["R3"], "motion_replans"), "r2_motion_replans": interventions(control["R2"], "motion_replans"), "success_rates": {arch: _rate(domain) for arch, domain in control.items()}}},
        {"gate": 5, "passed": g5, "evidence": {"correct_lowest_sufficient_fraction": correct_fraction, "r3_retry_loops": loops, "denominator": len(recoverable)}},
        {"gate": 6, "passed": g6, "evidence": domain_differences},
    ]
    outcome = "INCONCLUSIVE" if not complete else "SUPPORTS_LAYER_MATCHED_HIERARCHY" if all(item["passed"] for item in gates) else "NOT_SUPPORTED"
    return {"outcome": outcome, "primary_episode_count": len(primary), "expected_primary_episode_count": expected_primary_count, "complete": complete, "gates": gates}


def paired_case_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    primary = _eligible_primary(rows)
    index = {(str(item["architecture"]), str(item["scenario_id"]), int(item["seed"])): item for item in primary}
    result: list[dict[str, object]] = []
    for comparator in ("R0", "R1", "R2"):
        keys = sorted((scenario, seed) for arch, scenario, seed in index if arch == "R3")
        for scenario, seed in keys:
            r3 = index[("R3", scenario, seed)]
            other = index.get((comparator, scenario, seed))
            if other is None or r3["scenario_domain"] == "ANCHOR":
                continue
            result.append({
                "comparator": comparator,
                "scenario_domain": r3["scenario_domain"],
                "scenario_id": scenario,
                "seed": seed,
                "r3_success": int(bool(r3["eventual_success"])),
                "comparator_success": int(bool(other["eventual_success"])),
                "difference": int(bool(r3["eventual_success"])) - int(bool(other["eventual_success"])),
            })
    return result


def bootstrap_contrasts(paired: Sequence[Mapping[str, object]], *, draws: int = 10_000) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if draws != 10_000:
        raise ValueError("Experiment 03 uses exactly 10,000 bootstrap draws")
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for item in paired:
        grouped[(str(item["comparator"]), str(item["scenario_domain"]))].append(item)
    results: list[dict[str, object]] = []
    draw_rows: list[dict[str, object]] = []
    for group_index, key in enumerate(sorted(grouped)):
        domain = sorted(grouped[key], key=lambda item: (int(item["seed"]), str(item["scenario_id"])))
        values = np.asarray([float(item["difference"]) for item in domain], dtype=np.float64)
        estimates = np.empty(draws, dtype=np.float64)
        for draw_index in range(draws):
            draw_seed = 202616000000 + group_index * draws + draw_index
            indices = np.random.default_rng(draw_seed).integers(0, len(values), size=len(values))
            estimate = float(np.mean(values[indices]))
            estimates[draw_index] = estimate
            draw_rows.append({"comparator": key[0], "scenario_domain": key[1], "draw_index": draw_index, "draw_seed": draw_seed, "estimate": estimate})
        ordered = np.sort(estimates)
        results.append({
            "comparator": key[0],
            "scenario_domain": key[1],
            "pairs": len(values),
            "estimate": float(np.mean(values)),
            "lower": float(ordered[249]),
            "upper": float(ordered[9749]),
            "draws": draws,
            "draw_rows_sha256": hashlib.sha256(b"".join(canonical_bytes(item) for item in draw_rows[-draws:])).hexdigest(),
        })
    return results, draw_rows


def lowest_sufficient_confusion(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for item in _eligible_primary(rows):
        if item["architecture"] == "R3" and item["scenario_domain"] != "ANCHOR":
            counts[(str(item["lowest_sufficient_level"]), str(item["first_recovery_level"]))] += 1
    return [
        {"expected_level": expected, "selected_level": selected, "count": count}
        for (expected, selected), count in sorted(counts.items())
    ]


def sample_index(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    primary = _eligible_primary(rows)
    result = []
    for architecture in ("R0", "R1", "R2", "R3"):
        for domain in ("CONTROL", "MOTION", "SEMANTIC"):
            population = sorted(
                [item for item in primary if item["architecture"] == architecture and item["scenario_domain"] == domain],
                key=lambda item: (int(item["seed"]), str(item["scenario_id"])),
            )
            for requested, success in (("WORKING", True), ("NONWORKING", False)):
                selected = next((item for item in population if bool(item["eventual_success"]) is success), None)
                result.append({
                    "architecture": architecture,
                    "scenario_domain": domain,
                    "requested_class": requested,
                    "observed_class": requested if selected is not None else "CLASS_NOT_OBSERVED",
                    "denominator": len(population),
                    "episode_id": None if selected is None else selected["episode_id"],
                })
    return result


def _aggregates(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, object]]] = defaultdict(list)
    for item in rows:
        groups[(str(item["controller_id"]), str(item["architecture"]), str(item["scenario_domain"]))].append(item)
    result = []
    for (controller, architecture, domain), group in sorted(groups.items()):
        result.append({
            "controller_id": controller,
            "architecture": architecture,
            "scenario_domain": domain,
            "episodes": len(group),
            "success_rate": _rate(group),
            "unsafe_or_forbidden": sum(int(item.get("unsafe_count", 0)) + int(item.get("forbidden_action_count", 0)) for item in group),
            "semantic_replans": sum(int(item.get("semantic_replans", 0)) for item in group),
            "motion_replans": sum(int(item.get("motion_replans", 0)) for item in group),
            "local_recoveries": sum(int(item.get("bounded_local_recoveries", 0)) for item in group),
        })
    return result


def _jsonl(rows: Iterable[object]) -> bytes:
    return b"".join(canonical_bytes(item) for item in rows)


def _csv_bytes(rows: Sequence[Mapping[str, object]], columns: Sequence[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(columns), lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name) for name in columns})
    return stream.getvalue().encode("ascii")


def _success_svg(aggregates: Sequence[Mapping[str, object]]) -> bytes:
    primary = [item for item in aggregates if item["controller_id"] == "P6-res0p5-slew48"]
    colors = {"R0": "#9e9e9e", "R1": "#e76f51", "R2": "#2a9d8f", "R3": "#264653"}
    domains = ("ANCHOR", "CONTROL", "MOTION", "SEMANTIC")
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="800" height="460" viewBox="0 0 800 460">', '<rect width="800" height="460" fill="white"/>', '<text x="400" y="28" text-anchor="middle" font-family="sans-serif" font-size="18">Eventual mission success by recovery layer</text>', '<line x1="70" y1="390" x2="760" y2="390" stroke="black"/><line x1="70" y1="50" x2="70" y2="390" stroke="black"/>']
    lookup = {(item["architecture"], item["scenario_domain"]): float(item["success_rate"]) for item in primary}
    for domain_index, domain in enumerate(domains):
        base_x = 100 + domain_index * 165
        parts.append(f'<text x="{base_x + 54}" y="420" text-anchor="middle" font-family="sans-serif" font-size="12">{domain}</text>')
        for arch_index, architecture in enumerate(("R0", "R1", "R2", "R3")):
            value = lookup.get((architecture, domain), 0.0)
            height = round(320 * value, 6)
            x = base_x + arch_index * 27
            y = 390 - height
            parts.append(f'<rect x="{x}" y="{y}" width="22" height="{height}" fill="{colors[architecture]}"/><text x="{x + 11}" y="438" text-anchor="middle" font-family="sans-serif" font-size="10">{architecture}</text>')
    parts.append('</svg>\n')
    return "".join(parts).encode("ascii")


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _success_png(aggregates: Sequence[Mapping[str, object]]) -> bytes:
    width, height = 640, 360
    pixels = bytearray([255] * width * height * 3)
    colors = {"R0": (158, 158, 158), "R1": (231, 111, 81), "R2": (42, 157, 143), "R3": (38, 70, 83)}
    lookup = {(item["architecture"], item["scenario_domain"]): float(item["success_rate"]) for item in aggregates if item["controller_id"] == "P6-res0p5-slew48"}
    for domain_index, domain in enumerate(("ANCHOR", "CONTROL", "MOTION", "SEMANTIC")):
        for arch_index, architecture in enumerate(("R0", "R1", "R2", "R3")):
            x0 = 55 + domain_index * 145 + arch_index * 27
            x1 = x0 + 20
            bar_height = int(round(280 * lookup.get((architecture, domain), 0.0)))
            y0 = 320 - bar_height
            for y in range(max(0, y0), 320):
                for x in range(x0, min(width, x1)):
                    offset = (y * width + x) * 3
                    pixels[offset:offset + 3] = bytes(colors[architecture])
    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3:(y + 1) * width * 3]) for y in range(height))
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + _png_chunk(b"IDAT", zlib.compress(raw, 9)) + _png_chunk(b"IEND", b"")


def _write_create(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def analyze(raw_root: Path, derived_root: Path, *, expected_primary_count: int = 256) -> dict[str, object]:
    from .evidence import load_merged_rows

    if derived_root.exists():
        raise FileExistsError(derived_root)
    rows = load_merged_rows(raw_root)
    decision = evaluate_gates(rows, expected_primary_count=expected_primary_count)
    paired = paired_case_rows(rows)
    bootstrap_results, bootstrap_draws = bootstrap_contrasts(paired)
    confusion = lowest_sufficient_confusion(rows)
    samples = sample_index(rows)
    aggregates = _aggregates(rows)
    success_rows = [
        {"controller_id": item["controller_id"], "architecture": item["architecture"], "scenario_domain": item["scenario_domain"], "episodes": item["episodes"], "success_rate": item["success_rate"]}
        for item in aggregates
    ]
    intervention_rows = [
        {"controller_id": item["controller_id"], "architecture": item["architecture"], "scenario_domain": item["scenario_domain"], "semantic_replans": item["semantic_replans"], "motion_replans": item["motion_replans"], "local_recoveries": item["local_recoveries"]}
        for item in aggregates
    ]
    success_csv = _csv_bytes(success_rows, ("controller_id", "architecture", "scenario_domain", "episodes", "success_rate"))
    interventions_csv = _csv_bytes(intervention_rows, ("controller_id", "architecture", "scenario_domain", "semantic_replans", "motion_replans", "local_recoveries"))
    raw_manifest_sha = hashlib.sha256((raw_root / "manifest.json").read_bytes()).hexdigest()
    result_lines = [
        "# Hierarchical Recovery V1 Results",
        "",
        f"Decision: `{decision['outcome']}`.",
        "",
        f"Eligible primary episodes: {decision['primary_episode_count']} / {decision['expected_primary_episode_count']}.",
        "",
        "## Decision gates",
        "",
        "| Gate | Passed |",
        "|---:|:---:|",
    ]
    result_lines.extend(f"| {item['gate']} | {'YES' if item['passed'] else 'NO'} |" for item in decision["gates"])
    result_lines.extend(["", "## Evidence", "", f"Raw manifest SHA-256: `{raw_manifest_sha}`.", "", "Canonical graph tables: `success-by-domain.csv` and `interventions-by-domain.csv`.", ""])
    payloads: dict[str, bytes] = {
        "episode-metrics.jsonl": _jsonl(rows),
        "aggregates.jsonl": _jsonl(aggregates),
        "paired-cases.jsonl": _jsonl(paired),
        "bootstrap-inputs.json": canonical_bytes({"draws_per_contrast": 10_000, "paired_cases": paired}),
        "bootstrap-results.jsonl": _jsonl(bootstrap_results),
        "bootstrap-draws.jsonl": _jsonl(bootstrap_draws),
        "lowest-sufficient-confusion.jsonl": _jsonl(confusion),
        "sample-index.jsonl": _jsonl(samples),
        "decision.json": canonical_bytes(decision),
        "success-by-domain.csv": success_csv,
        "interventions-by-domain.csv": interventions_csv,
        "success-by-domain.svg": _success_svg(aggregates),
        "success-by-domain.png": _success_png(aggregates),
        "RESULTS.md": ("\n".join(result_lines)).encode("ascii"),
    }
    payloads["graph-sources.json"] = canonical_bytes({
        "renderer": "EXP03_STDLIB_SVG_PNG_V1",
        "renderer_sha256": hashlib.sha256(b"EXP03_STDLIB_SVG_PNG_V1").hexdigest(),
        "sources": {name: hashlib.sha256(payloads[name]).hexdigest() for name in ("success-by-domain.csv", "interventions-by-domain.csv")},
    })
    manifest = {
        "schema_version": 1,
        "raw_manifest_sha256": raw_manifest_sha,
        "files": [
            {"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
            for name, payload in sorted(payloads.items())
        ],
    }
    payloads["manifest.json"] = canonical_bytes(manifest)
    derived_root.mkdir(parents=True)
    for name, payload in sorted(payloads.items()):
        _write_create(derived_root / name, payload)
    return decision


__all__ = [
    "analyze", "bootstrap_contrasts", "evaluate_gates", "lowest_sufficient_confusion",
    "paired_case_rows", "sample_index",
]
