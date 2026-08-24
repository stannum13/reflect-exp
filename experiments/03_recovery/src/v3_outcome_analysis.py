"""Frozen preregistered V3 outcome pairing, bootstrap, gates, and figures."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .v3_contracts import Architecture, OUTCOME_SEEDS, PRIMARY_CONTROLLER_ID, SCENARIO_IDS, SENSITIVITY_CONTROLLER_ID, canonical_bytes, sha256_bytes
from .v3_evidence import _csv, _diagnostic_png, _diagnostic_svg, _inventory, _tree_bytes, source_closure
from .v3_scorer import score_counterfactual_candidate


BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20261800
DOMAINS = {
    "CONTROL": ("control-impulse", "control-dropout"),
    "MOTION": ("motion-target-shift", "motion-path-infeasible"),
    "SEMANTIC": ("semantic-object-unavailable", "semantic-restriction-change"),
}
REALIZATION_KEYS = {
    "episode_id", "scenario_id", "stage", "seed", "q0", "target_a_xy", "target_b_xy",
    "injection_tick", "impulse_nm", "impulse_ticks", "dropout_ticks", "target_shift_xy",
    "obstacle_xy", "obstacle_radius_m", "damping_multiplier", "semantic_delay_ticks", "parameter_sha256",
}


def _write_expected(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise RuntimeError(f"outcome derived create-only mismatch: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_raw_inventory(output: Path) -> None:
    manifest_path = output / "raw/manifest.json"
    payload = manifest_path.read_bytes()
    manifest = json.loads(payload.decode("ascii"))
    if canonical_bytes(manifest) != payload:
        raise RuntimeError("outcome raw manifest is not canonical")
    actual = []
    for item in manifest.get("files", ()):
        path = output / "raw" / str(item["path"])
        member = path.read_bytes()
        actual.append({"path": str(item["path"]), "bytes": len(member), "sha256": sha256_bytes(member)})
    if actual != manifest.get("files"):
        raise RuntimeError("outcome raw inventory mismatch")


def _domain(scenario: str) -> str:
    return next((domain for domain, scenarios in DOMAINS.items() if scenario in scenarios), "ANCHOR")


def expected_outcome_matrix() -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for architecture in Architecture:
        for scenario in SCENARIO_IDS:
            for seed in OUTCOME_SEEDS:
                episode_id = f"outcome-P6-{architecture.value}-{scenario}-{seed}"
                result[episode_id] = {
                    "episode_id": episode_id, "architecture": architecture.value, "scenario_id": scenario,
                    "template_id": scenario, "domain": _domain(scenario), "seed": seed,
                    "controller_id": PRIMARY_CONTROLLER_ID, "matrix_role": "PRIMARY",
                }
    for scenario in SCENARIO_IDS:
        for seed in OUTCOME_SEEDS[:5]:
            episode_id = f"outcome-P4-R3-{scenario}-{seed}"
            result[episode_id] = {
                "episode_id": episode_id, "architecture": "R3", "scenario_id": scenario,
                "template_id": scenario, "domain": _domain(scenario), "seed": seed,
                "controller_id": SENSITIVITY_CONTROLLER_ID, "matrix_role": "SENSITIVITY",
            }
    if len(result) != 360:
        raise RuntimeError("frozen outcome identity construction failed")
    return result


def matrix_identity_audit(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    expected = expected_outcome_matrix()
    seen: set[str] = set()
    errors: list[dict[str, object]] = []
    approval_hashes: set[str] = set()
    for index, row in enumerate(rows):
        episode_id = str(row.get("episode_id", ""))
        if episode_id in seen:
            errors.append({"index": index, "episode_id": episode_id, "error": "DUPLICATE"})
        seen.add(episode_id)
        identity = expected.get(episode_id)
        if identity is None:
            errors.append({"index": index, "episode_id": episode_id, "error": "EXTRA_OR_SUBSTITUTED_ID"})
            continue
        mismatched = [key for key, value in identity.items() if row.get(key) != value]
        if mismatched:
            errors.append({"index": index, "episode_id": episode_id, "error": "FIELD_SUBSTITUTION", "fields": mismatched})
        precheck_input = row.get("precheck_input")
        receipt = row.get("precheck_receipt")
        if not isinstance(precheck_input, Mapping) or set(precheck_input) != REALIZATION_KEYS:
            errors.append({"index": index, "episode_id": episode_id, "error": "REALIZATION_SCHEMA"})
        elif any((precheck_input.get("episode_id") != episode_id, precheck_input.get("scenario_id") != identity["scenario_id"], precheck_input.get("seed") != identity["seed"], precheck_input.get("stage") != "OUTCOME")):
            errors.append({"index": index, "episode_id": episode_id, "error": "REALIZATION_IDENTITY"})
        if not isinstance(receipt, Mapping) or not receipt.get("architecture_independent") or receipt.get("realization_sha256") != (precheck_input or {}).get("parameter_sha256"):
            errors.append({"index": index, "episode_id": episode_id, "error": "PRECHECK_BINDING"})
        approval = str(row.get("approval_report_sha256", ""))
        if len(approval) != 64:
            errors.append({"index": index, "episode_id": episode_id, "error": "APPROVAL_BINDING"})
        approval_hashes.add(approval)
    missing = sorted(set(expected) - seen)
    if missing:
        errors.append({"error": "MISSING", "count": len(missing), "first": missing[:3]})
    if len(approval_hashes) != 1:
        errors.append({"error": "APPROVAL_SUBSTITUTION", "count": len(approval_hashes)})
    passed = not errors and len(rows) == 360
    return {"passed": passed, "expected_count": 360, "actual_count": len(rows), "paired_count": len(paired_rows(rows)) if passed else 0, "errors": errors}


def _success(row: Mapping[str, object]) -> int:
    return int(row.get("disposition") == "COMPLETE" and row.get("terminal") == "SUCCESS")


def _verified_parameter_use(row: Mapping[str, object]) -> bool:
    receipt = row.get("parameter_use_receipt")
    precheck = row.get("precheck_input")
    if not isinstance(receipt, Mapping) or not isinstance(precheck, Mapping):
        return False
    payload = dict(receipt)
    claimed = payload.pop("receipt_sha256", None)
    if claimed != sha256_bytes(canonical_bytes(payload)):
        return False
    if row.get("parameter_use_sha256") != sha256_bytes(canonical_bytes(receipt)):
        return False
    shared = set(payload) & set(precheck) - {"episode_id", "scenario_id", "stage", "seed", "parameter_sha256"}
    return bool(shared) and all(payload[key] == precheck[key] for key in shared)


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
    seeds = sorted({int(row["seed"]) for row in selected})
    templates = sorted({str(row["scenario_id"]) for row in selected})
    clusters = [{
        "seed": seed,
        "rows": [row for row in selected if int(row["seed"]) == seed],
    } for seed in seeds]
    if len(clusters) != 10 or any(len(cluster["rows"]) != 4 for cluster in clusters):
        raise ValueError("realization bootstrap requires 10 seed clusters carrying four template rows")
    cluster_values = np.asarray([
        np.mean([int(row["r3_success"]) - int(row["r0_success"]) for row in cluster["rows"]])
        for cluster in clusters
    ], dtype=np.float64)
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    indices = rng.integers(0, len(clusters), size=(BOOTSTRAP_DRAWS, len(clusters)))
    draws = np.mean(cluster_values[indices], axis=1)
    template_values = np.asarray([
        np.mean([int(row["r3_success"]) - int(row["r0_success"]) for row in selected if row["scenario_id"] == scenario])
        for scenario in templates
    ], dtype=np.float64)
    template_rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED + 1))
    template_indices = template_rng.integers(0, len(templates), size=(BOOTSTRAP_DRAWS, len(templates)))
    template_draws = np.mean(template_values[template_indices], axis=1)
    return {
        "schema_version": 1,
        "draw_seed": BOOTSTRAP_SEED,
        "draw_count": BOOTSTRAP_DRAWS,
        "effective_n": 10,
        "effective_n_unit": "seed_realization_clusters",
        "effective_n_realizations_per_template": 10,
        "templates_per_domain": 2,
        "input_sha256": sha256_bytes(canonical_bytes(selected)),
        "cluster_inputs": clusters,
        "cluster_indices": indices.tolist(),
        "estimate": float(np.mean(cluster_values)),
        "percentile_2_5": float(np.quantile(draws, 0.025)),
        "percentile_97_5": float(np.quantile(draws, 0.975)),
        "draws": draws.tolist(),
        "template_cluster_sensitivity": {
            "draw_seed": BOOTSTRAP_SEED + 1,
            "cluster_unit": "template_with_all_10_realizations",
            "templates": templates,
            "cluster_indices": template_indices.tolist(),
            "draws": template_draws.tolist(),
            "estimate": float(np.mean(template_values)),
            "percentile_2_5": float(np.quantile(template_draws, 0.025)),
            "percentile_97_5": float(np.quantile(template_draws, 0.975)),
        },
    }


def evaluate_outcome_gates(rows: Sequence[Mapping[str, object]], *, construct_integrity: Mapping[str, bool]) -> dict[str, object]:
    matrix = matrix_identity_audit(rows)
    valid_dispositions = all(
        row.get("disposition") in {"COMPLETE", "NOT_RUN"}
        and isinstance(row.get("precheck_input"), Mapping)
        and isinstance(row.get("precheck_receipt"), Mapping)
        and bool(row["precheck_receipt"].get("architecture_independent"))
        for row in rows
    )
    if not matrix["passed"] or matrix["paired_count"] != 80 or not valid_dispositions or not all(construct_integrity.values()):
        return {
            "scientific_result": "INVALID_EXPERIMENT",
            "gates": [{"gate": index, "passed": False, "status": "NOT_RUN_INVALID_CONSTRUCT" if index < 8 else "FAILED"} for index in range(1, 9)],
            "paired_row_count": 0, "matrix_identity": matrix, "fixed_best_comparator": None,
            "comparator_totals": {}, "counterfactual_events": {"matched": 0, "total": 0},
        }
    pairs = paired_rows(rows)
    primary = [row for row in rows if row["controller_id"] == PRIMARY_CONTROLLER_ID]
    r3 = [row for row in primary if row["architecture"] == "R3"]
    comparators = {arch: [row for row in primary if row["architecture"] == arch] for arch in ("R0", "R1", "R2")}
    violation_keys = ("unsafe", "forbidden", "collision", "invalid_action", "stale", "loop", "reset")
    g1 = bool(construct_integrity.get("positive_controls")) and all(sum(int(row.get(key, 1)) for row in r3) <= sum(int(row.get(key, 1)) for row in values) for values in comparators.values() for key in violation_keys)
    ms = [row for row in pairs if row["scenario_id"] in DOMAINS["MOTION"] + DOMAINS["SEMANTIC"]]
    template_diffs = {scenario: sum(int(row["r3_success"]) - int(row["r0_success"]) for row in ms if row["scenario_id"] == scenario) for scenario in DOMAINS["MOTION"] + DOMAINS["SEMANTIC"]}
    g2 = sum(int(row["r3_success"]) - int(row["r0_success"]) for row in ms) > 0 and all(value >= 0 for value in template_diffs.values())
    semantic = [row for row in pairs if row["scenario_id"] in DOMAINS["SEMANTIC"]]
    g3 = sum(int(row["r3_success"]) - int(row["r1_success"]) for row in semantic) >= 0 and sum(int(row["r3_semantic"]) for row in semantic) < sum(int(row["r1_semantic"]) for row in semantic)
    control = [row for row in pairs if row["scenario_id"] in DOMAINS["CONTROL"]]
    g4 = all(sum(int(row["r3_success"]) - int(row[f"{arch.lower()}_success"]) for row in control) >= 0 for arch in ("R0", "R1", "R2")) and sum(int(row["r3_semantic"]) for row in control) < sum(int(row["r1_semantic"]) for row in control) and sum(int(row["r3_motion"]) for row in control) < sum(int(row["r2_motion"]) for row in control)
    counterfactual = [row for row in r3 if row.get("disposition") == "COMPLETE"]
    event_total = sum(int(row.get("counterfactual_event_audit", {}).get("event_count", 0)) for row in counterfactual)
    event_matched = sum(int(row.get("counterfactual_event_audit", {}).get("matched_event_count", 0)) for row in counterfactual)
    g5 = event_total > 0 and event_matched / event_total >= 0.8 and all(sum(int(row[key]) for row in r3) == 0 for key in ("loop", "reset"))
    comparator_totals = {arch: sum(int(row[f"{arch.lower()}_success"]) for row in pairs if row["scenario_id"] in sum(DOMAINS.values(), ())) for arch in ("R0", "R1", "R2")}
    fixed_best = max(("R0", "R1", "R2"), key=lambda arch: (comparator_totals[arch], -int(arch[1])))
    g6 = all(sum(int(row["r3_success"]) - int(row[f"{fixed_best.lower()}_success"]) for row in pairs if row["scenario_id"] in scenarios) >= 0 for scenarios in DOMAINS.values())
    disturbed = [row for row in r3 if row["scenario_id"] not in ("anchor-nominal", "anchor-slow-policy")]
    diversity = {}
    for scenario in sum(DOMAINS.values(), ()):
        template = [row for row in disturbed if row["scenario_id"] == scenario]
        complete = [row for row in template if row.get("disposition") == "COMPLETE"]
        trace_hashes = {
            str(row["physical_trace_sha256"]) for row in complete
            if isinstance(row.get("physical_trace_sha256"), str) and len(str(row["physical_trace_sha256"])) == 64
        }
        verified_parameter_hashes = {
            str(row["parameter_use_sha256"]) for row in complete if _verified_parameter_use(row)
        }
        diversity[scenario] = {
            "denominator": len(template), "complete": len(complete),
            "distinct_complete_physical_traces": len(trace_hashes),
            "distinct_verified_parameter_uses": len(verified_parameter_hashes),
            "passed": len(template) == 10 and len(complete) >= 8 and len(trace_hashes) >= 8 and len(verified_parameter_hashes) >= 8,
        }
    g7 = all(item["passed"] for item in diversity.values())
    g8 = bool(construct_integrity.get("lifecycle")) and all(construct_integrity.values())
    gates = [g1, g2, g3, g4, g5, g6, g7, g8]
    result = "SUPPORTS_CONSTRUCT_VALID_LAYER_MATCHED_HIERARCHY" if all(gates) else "INVALID_EXPERIMENT" if not g8 else "DOES_NOT_SUPPORT_CONSTRUCT_VALID_LAYER_MATCHED_HIERARCHY"
    return {"scientific_result": result, "gates": [{"gate": index + 1, "passed": value} for index, value in enumerate(gates)], "paired_row_count": len(pairs), "matrix_identity": matrix, "fixed_best_comparator": fixed_best, "comparator_totals": comparator_totals, "counterfactual_events": {"matched": event_matched, "total": event_total}, "diversity": diversity}


def outcome_payloads(rows: Sequence[Mapping[str, object]], *, construct_integrity: Mapping[str, bool]) -> dict[str, bytes]:
    decision = evaluate_outcome_gates(rows, construct_integrity=construct_integrity)
    construct_valid = bool(decision["gates"][7]["passed"])
    pairs = paired_rows(rows) if construct_valid else []
    bootstrap = realization_bootstrap(pairs) if construct_valid else {
        "schema_version": 1, "status": "NOT_RUN_INVALID_CONSTRUCT", "draw_count": 0,
        "effective_n": 0, "cluster_inputs": [], "cluster_indices": [], "draws": [],
        "template_cluster_sensitivity": {"status": "NOT_RUN_INVALID_CONSTRUCT", "draws": []},
    }
    aggregate = []
    for architecture in (("R0", "R1", "R2", "R3") if construct_valid else ()):
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


def _counterfactual_cause_valid(audit: Mapping[str, object]) -> bool:
    """Recompute every candidate/member/score receipt without trusting labels."""
    try:
        events = audit.get("events")
        if not isinstance(events, list) or int(audit.get("event_count", -1)) != len(events):
            return False
        minimal_levels = []
        for event in events:
            candidates = event.get("counterfactual_candidates")
            if not isinstance(candidates, list) or len(candidates) != 3:
                return False
            if [item.get("level") for item in candidates] != ["CONTROL", "MOTION", "SEMANTIC"]:
                return False
            if len({item.get("raw_sha256") for item in candidates}) != 3:
                return False
            recomputed_receipts = []
            for candidate in candidates:
                if candidate.get("event_state_sha256") != event.get("event_state_sha256"):
                    return False
                raw_candidate = json.loads(canonical_bytes(candidate))
                for derived_key in (
                    "safety_passed", "domain_cleared", "content_progress", "scored_terminal",
                    "passed", "independently_scored", "score_receipt",
                ):
                    raw_candidate.pop(derived_key, None)
                receipt = score_counterfactual_candidate(raw_candidate["start_state"], raw_candidate)
                if canonical_bytes(receipt) != canonical_bytes(candidate.get("score_receipt")):
                    return False
                if any(candidate.get(key) != receipt[receipt_key] for key, receipt_key in (
                    ("safety_passed", "safety_passed"),
                    ("domain_cleared", "domain_cleared"),
                    ("content_progress", "content_progress"),
                    ("scored_terminal", "terminal"),
                    ("passed", "passed"),
                    ("independently_scored", "independently_scored"),
                )):
                    return False
                recomputed_receipts.append(receipt)
            minimal = next((item["level"] for item in recomputed_receipts if item["passed"]), None)
            if event.get("minimal_sufficient_level") != minimal:
                return False
            minimal_levels.append(minimal)
        expected_top = next(iter(set(minimal_levels))) if len(set(minimal_levels)) == 1 else None
        return audit.get("lowest_sufficient_level") == expected_top
    except (KeyError, TypeError, ValueError):
        return False


def _derived_construct_integrity(output: Path, rows: Sequence[Mapping[str, object]]) -> dict[str, bool]:
    freeze_payload = (output / "outcome-freeze.json").read_bytes()
    freeze = json.loads(freeze_payload.decode("ascii"))
    header_payload = (output / "HEADERS-SEALED.json").read_bytes()
    header = json.loads(header_payload.decode("ascii"))
    approval_report = (output / "approval/approval-report.json").read_bytes()
    approval_binding = (output / "approval/approval-binding.json").read_bytes()
    report = json.loads(approval_report.decode("ascii"))
    binding = json.loads(approval_binding.decode("ascii"))
    expected_header = canonical_bytes({
        "schema_version": 1,
        "files": _inventory({
            "outcome-freeze.json": freeze_payload,
            "approval/approval-binding.json": approval_binding,
            "approval/approval-report.json": approval_report,
        }),
    })
    approval = freeze.get("approval", {})
    approval_passed = bool(
        isinstance(approval, Mapping)
        and approval.get("reviewer_verdict") == "APPROVED_FOR_OUTCOME"
        and approval.get("approval_report_sha256") == sha256_bytes(approval_report)
        and approval.get("positive_controls_authenticated") is True
        and report.get("verdict") == "APPROVED_FOR_OUTCOME"
        and report.get("critical_findings") == []
        and report.get("important_findings") == []
        and binding.get("approval_report_sha256") == sha256_bytes(approval_report)
        and all(binding.get(key) == approval.get(key) for key in binding if key != "schema_version")
    )
    inventory_passed = bool(
        len(rows) == 360
        and len({str(row.get("episode_id")) for row in rows}) == 360
        and (output / "raw/manifest.json").is_file()
    )
    freeze_passed = bool(
        canonical_bytes(freeze) == freeze_payload
        and canonical_bytes(header) == header_payload
        and header_payload == expected_header
        and freeze.get("source_closure") == source_closure()
        and freeze.get("source_closure_sha256") == sha256_bytes(canonical_bytes(source_closure()))
    )
    causal_rows = [
        row for row in rows
        if row.get("architecture") == "R3" and row.get("controller_id") == PRIMARY_CONTROLLER_ID
        and row.get("disposition") == "COMPLETE"
    ]
    cause_passed = all(
        isinstance(row.get("counterfactual_event_audit"), Mapping)
        and _counterfactual_cause_valid(row["counterfactual_event_audit"])
        for row in causal_rows
    )
    receipt_payload = (output / "derived/reconstruction-receipt.json").read_bytes()
    receipt = json.loads(receipt_payload.decode("ascii"))
    rows_payload = (output / "raw/outcome-rows.jsonl").read_bytes()
    receipt_valid = bool(
        canonical_bytes(receipt) == receipt_payload
        and receipt.get("raw_manifest_sha256") == sha256_bytes((output / "raw/manifest.json").read_bytes())
        and receipt.get("outcome_rows_sha256") == sha256_bytes(rows_payload)
        and receipt.get("raw_tree_sha256") == sha256_bytes(canonical_bytes(_inventory(_tree_bytes(output / "raw"))))
    )
    inventory_passed = inventory_passed and receipt_valid
    replay_passed = receipt_valid and receipt.get("status") == "RAW_REPLAY_MATCHED_RESUMABLE"
    lifecycle_passed = replay_passed and receipt.get("invalid_dispositions") == 0
    return {
        "approval": approval_passed,
        "inventory": inventory_passed,
        "freeze": freeze_passed,
        "cause": cause_passed,
        "replay": replay_passed,
        "reconstruction": replay_passed,
        "positive_controls": bool(approval.get("positive_controls_authenticated") is True),
        "lifecycle": lifecycle_passed,
    }


def analyze_outcomes(output: Path) -> dict[str, object]:
    derived = output / "derived"
    _validate_raw_inventory(output)
    rows = [json.loads(line) for line in (output / "raw/outcome-rows.jsonl").read_text(encoding="ascii").splitlines()]
    construct_integrity = _derived_construct_integrity(output, rows)
    payloads = outcome_payloads(rows, construct_integrity=construct_integrity)
    payloads["reconstruction-receipt.json"] = (derived / "reconstruction-receipt.json").read_bytes()
    manifest_payload = canonical_bytes({"schema_version": 1, "files": _inventory(payloads)})
    manifest_path = derived / "manifest.json"
    if manifest_path.exists():
        if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.read_bytes() != manifest_payload:
            raise RuntimeError("outcome derived sealed manifest mismatch")
        for name, payload in payloads.items():
            path = derived / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise RuntimeError(f"outcome derived sealed member mismatch: {path}")
        return json.loads(payloads["decision.json"])
    for name, payload in sorted(payloads.items()):
        _write_expected(derived / name, payload)
    _write_expected(manifest_path, manifest_payload)
    return json.loads(payloads["decision.json"])


__all__ = ["BOOTSTRAP_DRAWS", "_counterfactual_cause_valid", "analyze_outcomes", "evaluate_outcome_gates", "outcome_payloads", "paired_rows", "realization_bootstrap"]
