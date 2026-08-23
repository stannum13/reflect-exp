"""Frozen preregistered V3 outcome pairing, bootstrap, gates, and figures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .v3_contracts import PRIMARY_CONTROLLER_ID, canonical_bytes, sha256_bytes
from .v3_evidence import _csv, _diagnostic_png, _diagnostic_svg, _inventory, _write


BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20261800
DOMAINS = {
    "CONTROL": ("control-impulse", "control-dropout"),
    "MOTION": ("motion-target-shift", "motion-path-infeasible"),
    "SEMANTIC": ("semantic-object-unavailable", "semantic-restriction-change"),
}


def _success(row: Mapping[str, object]) -> int:
    return int(row.get("disposition") == "TERMINAL" and row.get("terminal") == "SUCCESS")


def paired_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    primary = [row for row in rows if row["controller_id"] == PRIMARY_CONTROLLER_ID]
    grouped: dict[tuple[str, int], dict[str, Mapping[str, object]]] = {}
    for row in primary:
        grouped.setdefault((str(row["scenario_id"]), int(row["seed"])), {})[str(row["architecture"])] = row
    result = []
    for (scenario, seed), architectures in sorted(grouped.items()):
        if set(architectures) != {"R0", "R1", "R2", "R3"}:
            continue
        result.append({
            "scenario_id": scenario,
            "seed": seed,
            **{f"{arch.lower()}_success": _success(architectures[arch]) for arch in ("R0", "R1", "R2", "R3")},
            **{f"{arch.lower()}_semantic": int(architectures[arch].get("semantic_interventions", 0)) for arch in ("R0", "R1", "R2", "R3")},
            **{f"{arch.lower()}_motion": int(architectures[arch].get("motion_interventions", 0)) for arch in ("R0", "R1", "R2", "R3")},
        })
    return result


def realization_bootstrap(pairs: Sequence[Mapping[str, object]]) -> dict[str, object]:
    selected = [row for row in pairs if row["scenario_id"] in DOMAINS["MOTION"] + DOMAINS["SEMANTIC"]]
    values = np.asarray([int(row["r3_success"]) - int(row["r0_success"]) for row in selected], dtype=np.float64)
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    indices = rng.integers(0, len(values), size=(BOOTSTRAP_DRAWS, len(values))) if len(values) else np.zeros((BOOTSTRAP_DRAWS, 0), dtype=np.int64)
    draws = np.zeros(BOOTSTRAP_DRAWS) if not len(values) else np.mean(values[indices], axis=1)
    template_means = {
        scenario: float(np.mean([int(row["r3_success"]) - int(row["r0_success"]) for row in selected if row["scenario_id"] == scenario]))
        for scenario in sorted({str(row["scenario_id"]) for row in selected})
    }
    return {
        "schema_version": 1,
        "draw_seed": BOOTSTRAP_SEED,
        "draw_count": BOOTSTRAP_DRAWS,
        "effective_n_realizations_per_template": 10,
        "templates_per_domain": 2,
        "input_sha256": sha256_bytes(canonical_bytes(selected)),
        "estimate": float(np.mean(values)) if len(values) else 0.0,
        "percentile_2_5": float(np.quantile(draws, 0.025)),
        "percentile_97_5": float(np.quantile(draws, 0.975)),
        "draws": draws.tolist(),
        "template_cluster_sensitivity": template_means,
    }


def evaluate_outcome_gates(rows: Sequence[Mapping[str, object]], *, construct_integrity: Mapping[str, bool]) -> dict[str, object]:
    pairs = paired_rows(rows)
    primary = [row for row in rows if row["controller_id"] == PRIMARY_CONTROLLER_ID]
    r3 = [row for row in primary if row["architecture"] == "R3"]
    comparators = {arch: [row for row in primary if row["architecture"] == arch] for arch in ("R0", "R1", "R2")}
    violation_keys = ("unsafe", "forbidden", "collision", "invalid_action", "stale", "loop", "reset")
    g1 = all(sum(int(row.get(key, 1)) for row in r3) <= sum(int(row.get(key, 1)) for row in values) for values in comparators.values() for key in violation_keys)
    ms = [row for row in pairs if row["scenario_id"] in DOMAINS["MOTION"] + DOMAINS["SEMANTIC"]]
    template_diffs = {scenario: sum(int(row["r3_success"]) - int(row["r0_success"]) for row in ms if row["scenario_id"] == scenario) for scenario in DOMAINS["MOTION"] + DOMAINS["SEMANTIC"]}
    g2 = sum(int(row["r3_success"]) - int(row["r0_success"]) for row in ms) > 0 and all(value >= 0 for value in template_diffs.values())
    semantic = [row for row in pairs if row["scenario_id"] in DOMAINS["SEMANTIC"]]
    g3 = all(int(row["r3_success"]) >= int(row["r1_success"]) for row in semantic) and sum(int(row["r3_semantic"]) for row in semantic) < sum(int(row["r1_semantic"]) for row in semantic)
    control = [row for row in pairs if row["scenario_id"] in DOMAINS["CONTROL"]]
    g4 = all(int(row["r3_success"]) >= max(int(row["r1_success"]), int(row["r2_success"])) for row in control) and sum(int(row["r3_semantic"]) for row in control) < sum(int(row["r1_semantic"]) for row in control) and sum(int(row["r3_motion"]) for row in control) < sum(int(row["r2_motion"]) for row in control)
    counterfactual = [row for row in r3 if row.get("disposition") == "TERMINAL"]
    g5 = bool(counterfactual) and sum(bool(row.get("lowest_sufficient_correct")) for row in counterfactual) / len(counterfactual) >= 0.8 and all(sum(int(row[key]) for row in r3) == 0 for key in ("loop", "reset"))
    g6 = all(sum(int(row["r3_success"]) - max(int(row["r0_success"]), int(row["r1_success"]), int(row["r2_success"])) for row in pairs if row["scenario_id"] in scenarios) >= 0 for scenarios in DOMAINS.values())
    disturbed = [row for row in r3 if row["scenario_id"] not in ("anchor-nominal", "anchor-slow-policy")]
    diversity = all(len({str(row.get("physical_trace_sha256")) for row in disturbed if row["scenario_id"] == scenario}) >= 8 and len({str(row.get("parameter_use_sha256")) for row in disturbed if row["scenario_id"] == scenario}) >= 8 for scenario in sum(DOMAINS.values(), ()))
    g7 = diversity
    valid_dispositions = all(
        row.get("disposition") in {"TERMINAL", "NOT_RUN"}
        and isinstance(row.get("precheck_input"), Mapping)
        and isinstance(row.get("precheck_receipt"), Mapping)
        and bool(row["precheck_receipt"].get("architecture_independent"))
        for row in rows
    )
    g8 = len(rows) == 360 and len({str(row["episode_id"]) for row in rows}) == 360 and valid_dispositions and all(construct_integrity.values())
    gates = [g1, g2, g3, g4, g5, g6, g7, g8]
    result = "SUPPORTS_CONSTRUCT_VALID_LAYER_MATCHED_HIERARCHY" if all(gates) else "INVALID_EXPERIMENT" if not g8 else "DOES_NOT_SUPPORT_CONSTRUCT_VALID_LAYER_MATCHED_HIERARCHY"
    return {"scientific_result": result, "gates": [{"gate": index + 1, "passed": value} for index, value in enumerate(gates)], "paired_row_count": len(pairs)}


def outcome_payloads(rows: Sequence[Mapping[str, object]], *, construct_integrity: Mapping[str, bool]) -> dict[str, bytes]:
    pairs = paired_rows(rows)
    bootstrap = realization_bootstrap(pairs)
    decision = evaluate_outcome_gates(rows, construct_integrity=construct_integrity)
    aggregate = []
    for architecture in ("R0", "R1", "R2", "R3"):
        for domain, scenarios in DOMAINS.items():
            selected = [row for row in rows if row["controller_id"] == PRIMARY_CONTROLLER_ID and row["architecture"] == architecture and row["scenario_id"] in scenarios]
            aggregate.append({"architecture": architecture, "domain": domain, "successes": sum(_success(row) for row in selected), "episodes": len(selected)})
    columns = ("architecture", "domain", "successes", "episodes")
    svg = _diagnostic_svg("V3 paired outcome success by domain", aggregate, columns)
    examples = {
        "working": next((row["episode_id"] for row in rows if _success(row)), None),
        "nonworking": next((row["episode_id"] for row in rows if row.get("terminal") == "FAILURE"), None),
        "not_run": next((row["episode_id"] for row in rows if row.get("disposition") == "NOT_RUN"), None),
        "class_absent": [name for name in ("working", "nonworking", "not_run") if not any((_success(row) if name == "working" else row.get("terminal") == "FAILURE" if name == "nonworking" else row.get("disposition") == "NOT_RUN") for row in rows)],
    }
    return {
        "decision.json": canonical_bytes(decision),
        "construct-integrity.json": canonical_bytes(dict(construct_integrity)),
        "paired-rows.csv": _csv(pairs, tuple(pairs[0]) if pairs else ("scenario_id", "seed")),
        "paired-rows.jsonl": b"".join(canonical_bytes(row) for row in pairs),
        "bootstrap.json": canonical_bytes(bootstrap),
        "bootstrap-inputs.json": canonical_bytes({"seed": BOOTSTRAP_SEED, "rows": pairs}),
        "template-cluster-sensitivity.json": canonical_bytes(bootstrap["template_cluster_sensitivity"]),
        "graph-table.csv": _csv(aggregate, columns),
        "outcome-by-domain.svg": svg,
        "outcome-by-domain.png": _diagnostic_png(svg),
        "examples.json": canonical_bytes(examples),
    }


def analyze_outcomes(output: Path, *, construct_integrity: Mapping[str, bool]) -> dict[str, object]:
    derived = output / "derived"
    if derived.exists():
        raise FileExistsError(derived)
    rows = [json.loads(line) for line in (output / "raw/outcome-rows.jsonl").read_text(encoding="ascii").splitlines()]
    payloads = outcome_payloads(rows, construct_integrity=construct_integrity)
    for name, payload in sorted(payloads.items()):
        _write(derived / name, payload)
    _write(derived / "manifest.json", canonical_bytes({"schema_version": 1, "files": _inventory(payloads)}))
    return json.loads(payloads["decision.json"])


__all__ = ["BOOTSTRAP_DRAWS", "analyze_outcomes", "evaluate_outcome_gates", "outcome_payloads", "paired_rows", "realization_bootstrap"]
