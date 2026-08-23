"""Minimal, nonconfirmatory Experiment 04 memory-architecture screen.

The runner consumes observations only.  Scorer truth is kept in a separate artifact
and is joined only after a variant has emitted its answers and decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np


VARIANTS = ("M0", "M1", "M2", "M3", "M4", "M5", "M6", "H0", "V0")
SEEDS = (20260871, 20260872, 20260873, 20260874)
QUERY_IDS = (
    "LOCATION", "LAST_OBSERVED", "POSE_USABLE", "PRIOR_ATTEMPT",
    "LAST_FAILURE_REASON", "REACHABLE_VALVE", "CHANGES_SINCE",
    "ROUTE_BLOCKER", "DUPLICATE_IDENTITY", "CONFLICTS_UNKNOWN",
)
ACTION_QUERIES = {"POSE_USABLE", "REACHABLE_VALVE", "ROUTE_BLOCKER", "DUPLICATE_IDENTITY"}
IDENTITY_QUERIES = {"REACHABLE_VALVE", "DUPLICATE_IDENTITY"}


class ScreenError(ValueError):
    pass


@dataclass(frozen=True)
class Fact:
    fact_id: str
    subject_id: str
    predicate: str
    value: str
    observed_tick: int
    received_tick: int
    confidence: float
    status: str = "asserted"

    def row(self) -> dict[str, object]:
        return {
            "confidence": self.confidence,
            "fact_id": self.fact_id,
            "observed_tick": self.observed_tick,
            "predicate": self.predicate,
            "received_tick": self.received_tick,
            "source_event_id": f"event/{self.fact_id}",
            "status": self.status,
            "subject_id": self.subject_id,
            "value": self.value,
        }


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _jsonl(rows: Sequence[Mapping[str, object]]) -> bytes:
    return b"".join(_canonical(row) for row in rows)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fact(case: int, suffix: str, subject: str, predicate: str, value: str, observed: int, received: int, confidence: float, status: str = "asserted") -> dict[str, object]:
    return Fact(f"{case:02d}-{suffix}", subject, predicate, value, observed, received, confidence, status).row()


def generate_seed(seed: int) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Return observation rows and isolated scorer truth for one engineering seed."""
    if type(seed) is not int or seed < 0:
        raise ScreenError("seed must be a nonnegative integer")
    rng = np.random.Generator(np.random.PCG64(seed))
    jitter = rng.choice(np.array((-0.05, 0.0, 0.05)), size=10, p=(0.2, 0.6, 0.2))
    delays = rng.choice(np.array((0, 1)), size=10, p=(0.75, 0.25))
    definitions = (
        ("LOCATION", [_fact(0, "base", "tool/0001", "IN", "room/0001", 0, 0, .90)], [], "UNKNOWN", "RESCAN"),
        ("LAST_OBSERVED", [_fact(1, "seen", "valve/0001", "OBSERVED_AT", "tick/0", 0, 0, .90)], [_fact(1, "occ", "valve/0001", "VISIBILITY", "OCCLUDED", 1, 2, .95)], "tick/0", "REPORT"),
        ("POSE_USABLE", [_fact(2, "pose", "asset/0002", "POSE", "10.0,0.0,0.0", 0, 0, .90)], [], "STALE", "RESCAN"),
        ("PRIOR_ATTEMPT", [], [_fact(3, "attempt", "door/0003", "ATTEMPT_OUTCOME", "OPEN_DOOR:FAILED:BLOCKED", 1, 2, .90)], "YES", "REPORT"),
        ("LAST_FAILURE_REASON", [], [_fact(4, "failure", "door/0003", "ATTEMPT_OUTCOME", "OPEN_DOOR:FAILED:BLOCKED", 1, 2, .90)], "BLOCKED", "REPORT"),
        ("REACHABLE_VALVE", [
            _fact(5, "v3", "valve/0001", "IN", "room/0003", 0, 0, .90),
            _fact(5, "v7", "valve/0002", "IN", "room/0004", 0, 0, .90),
        ], [_fact(5, "restrict", "room/0003", "RESTRICTED_BY", "restriction/0001", 1, 2, .90)], "valve/0002", "CHOOSE_ALTERNATIVE"),
        ("CHANGES_SINCE", [], [_fact(6, "placed", "tool/0002", "ON", "asset/0003", 1, 2, .90)], "tool/0002:ON:asset/0003", "REPORT"),
        ("ROUTE_BLOCKER", [_fact(7, "edge", "door/0002", "CONNECTS", "room/0002|room/0003", 0, 0, .90)], [_fact(7, "blocked", "door/0002", "DOOR_STATE", "BLOCKED", 1, 2, .90)], "door/0002", "CHOOSE_ALTERNATIVE"),
        ("DUPLICATE_IDENTITY", [], [
            _fact(8, "a", "valve/0001", "ALIAS", "service valve", 1, 2, .90),
            _fact(8, "b", "valve/0002", "ALIAS", "service valve", 1, 2, .90),
        ], "AMBIGUOUS", "REIDENTIFY"),
        ("CONFLICTS_UNKNOWN", [], [
            _fact(9, "ok", "asset/0001", "OPERATIONAL_STATE", "OPERATIONAL", 1, 2, .55, "asserted"),
            _fact(9, "bad", "asset/0001", "OPERATIONAL_STATE", "FAILED", 1, 2, .55, "contradicted"),
        ], "CONTRADICTED", "REPORT_UNKNOWN"),
    )
    observations: list[dict[str, object]] = []
    truths: list[dict[str, object]] = []
    for index, (query, baseline, delivered, answer, decision) in enumerate(definitions):
        received_tick = 2 + int(delays[index])
        adjusted = []
        for row in delivered:
            copy = dict(row); copy["confidence"] = float(min(1.0, max(0.0, float(copy["confidence"]) + float(jitter[index])))); copy["received_tick"] = received_tick
            adjusted.append(copy)
        observations.append({
            "baseline_facts": baseline,
            "case_id": f"case/{index:02d}",
            "delivered_facts": adjusted,
            "delivery_delay_ticks": int(delays[index]),
            "query_id": query,
            "query_tick": received_tick,
            "schema_version": "exp04-engineering-observation-v1",
            "seed": seed,
        })
        truths.append({
            "case_id": f"case/{index:02d}", "expected_answer": answer,
            "expected_decision": decision, "query_id": query,
            "schema_version": "exp04-engineering-scorer-truth-v1", "seed": seed,
        })
    return tuple(observations), tuple(truths)


def _facts_for(variant_id: str, observation: Mapping[str, object]) -> list[dict[str, object]]:
    baseline = [dict(row) for row in observation["baseline_facts"]]  # type: ignore[union-attr]
    delivered = [dict(row) for row in observation["delivered_facts"]]  # type: ignore[union-attr]
    if variant_id == "M0":
        return delivered
    if variant_id == "M2":
        return [row for row in baseline + delivered if row["predicate"] in {"ATTEMPT_OUTCOME", "ON"}]
    if variant_id == "V0":
        return baseline + delivered
    if variant_id == "M1":
        return baseline + delivered
    if variant_id in {"M3", "M4", "M5", "M6", "H0"}:
        if variant_id == "M3":
            return [row for row in baseline + delivered if row["predicate"] != "ATTEMPT_OUTCOME"]
        return baseline + delivered
    raise ScreenError("unknown variant")


def _answer(variant: str, query: str, facts: Sequence[Mapping[str, object]], now: int) -> tuple[str, str, tuple[str, ...]]:
    predicates: dict[str, list[Mapping[str, object]]] = {}
    for row in facts:
        predicates.setdefault(str(row["predicate"]), []).append(row)
    cited: list[Mapping[str, object]] = []
    answer, decision = "UNKNOWN", "REPORT_UNKNOWN"
    structured = variant in {"M3", "M4", "M5", "M6", "H0"}
    episodic = variant in {"M1", "M2", "M4", "M5", "M6", "H0"}
    confidence_aware = variant in {"M5", "M6"}
    if query == "LOCATION":
        cited = predicates.get("IN", [])
        if cited and not confidence_aware:
            answer, decision = str(cited[-1]["value"]), "ACT"
        else:
            answer, decision = "UNKNOWN", "RESCAN"
    elif query == "LAST_OBSERVED":
        cited = predicates.get("OBSERVED_AT", [])
        if cited: answer, decision = str(cited[-1]["value"]), "REPORT"
    elif query == "POSE_USABLE":
        cited = predicates.get("POSE", [])
        stale = bool(cited) and now - int(cited[-1]["received_tick"]) >= 2
        if cited and not (confidence_aware and stale): answer, decision = "USABLE", "ACT"
        elif stale: answer, decision = "STALE", "RESCAN"
        else: decision = "RESCAN"
    elif query in {"PRIOR_ATTEMPT", "LAST_FAILURE_REASON"}:
        cited = predicates.get("ATTEMPT_OUTCOME", []) if episodic else []
        if cited:
            answer = "YES" if query == "PRIOR_ATTEMPT" else str(cited[-1]["value"]).split(":")[-1]
            decision = "REPORT"
    elif query == "REACHABLE_VALVE":
        locations = predicates.get("IN", []) if structured else []
        restrictions = {str(row["subject_id"]) for row in predicates.get("RESTRICTED_BY", [])}
        candidates = [row for row in locations if str(row["subject_id"]).startswith("valve/") and str(row["value"]) not in restrictions]
        cited = candidates + predicates.get("RESTRICTED_BY", [])
        if candidates: answer, decision = str(candidates[0]["subject_id"]), "CHOOSE_ALTERNATIVE"
    elif query == "CHANGES_SINCE":
        cited = predicates.get("ON", []) if episodic else []
        if cited: answer, decision = f"{cited[-1]['subject_id']}:ON:{cited[-1]['value']}", "REPORT"
    elif query == "ROUTE_BLOCKER":
        cited = predicates.get("DOOR_STATE", []) if structured else []
        if cited: answer, decision = str(cited[-1]["subject_id"]), "CHOOSE_ALTERNATIVE"
    elif query == "DUPLICATE_IDENTITY":
        aliases = predicates.get("ALIAS", [])
        cited = aliases
        if len({row["subject_id"] for row in aliases}) > 1: answer, decision = "AMBIGUOUS", "REIDENTIFY"
    elif query == "CONFLICTS_UNKNOWN":
        states = predicates.get("OPERATIONAL_STATE", [])
        cited = states
        if confidence_aware and {row["status"] for row in states} == {"asserted", "contradicted"}:
            answer, decision = "CONTRADICTED", "REPORT_UNKNOWN"
        elif states:
            answer, decision = str(states[-1]["value"]), "ACT"
    if variant == "V0" and query != "DUPLICATE_IDENTITY":
        return "UNKNOWN", "REPORT_UNKNOWN", ()
    return answer, decision, tuple(str(row["fact_id"]) for row in cited)


def run_variant(variant_id: str, seed: int, observations: Sequence[Mapping[str, object]]) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Execute one architecture without accepting scorer truth."""
    if variant_id not in VARIANTS or type(seed) is not int or len(observations) != 10:
        raise ScreenError("invalid variant execution input")
    compiled: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []
    for observation in observations:
        if observation.get("seed") != seed or observation.get("query_id") not in QUERY_IDS:
            raise ScreenError("observation identity is invalid")
        facts = _facts_for(variant_id, observation)
        compiled.extend({"case_id": observation["case_id"], "variant_id": variant_id, **row} for row in facts)
        answer, decision, cited = _answer(variant_id, str(observation["query_id"]), facts, int(observation["query_tick"]))
        context_bytes = len(_canonical([row for row in facts if str(row["fact_id"]) in cited]))
        decisions.append({
            "answer": answer, "case_id": observation["case_id"], "cited_fact_ids": cited,
            "context_bytes": context_bytes, "decision": decision, "query_id": observation["query_id"],
            "schema_version": "exp04-engineering-query-decision-v1", "seed": seed,
            "variant_id": variant_id,
        })
    return tuple(compiled), tuple(decisions)


def _score(decisions: Sequence[Mapping[str, object]], truths: Sequence[Mapping[str, object]], facts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    truth_by_case = {row["case_id"]: row for row in truths}
    scored = []
    for row in decisions:
        truth = truth_by_case[row["case_id"]]
        correct = row["answer"] == truth["expected_answer"] and row["decision"] == truth["expected_decision"]
        stale = row["query_id"] == "POSE_USABLE" and row["decision"] == "ACT"
        wrong = row["query_id"] in IDENTITY_QUERIES and row["answer"] not in {truth["expected_answer"], "UNKNOWN"}
        scored.append({"case_id": row["case_id"], "correct": correct, "query_id": row["query_id"], "stale_action": stale, "wrong_identity": wrong})
    correct = sum(bool(row["correct"]) for row in scored)
    stale = sum(bool(row["stale_action"]) for row in scored if row["query_id"] in ACTION_QUERIES)
    wrong = sum(bool(row["wrong_identity"]) for row in scored if row["query_id"] in IDENTITY_QUERIES)
    scans = sum(row["decision"] in {"RESCAN", "REIDENTIFY"} for row in decisions)
    ambiguous = next(row for row in scored if row["query_id"] == "DUPLICATE_IDENTITY")
    return {
        "ambiguous_retrieval_rate": float(bool(ambiguous["correct"])), "correct_count": correct,
        "correct_rate": correct / 10.0, "disposition": "COMPLETE", "input_fact_count": len(facts),
        "repeated_scan_count": scans, "schema_version": "exp04-engineering-metrics-v1",
        "stale_action_rate": stale / 4.0, "stale_wrong_composite": 0.5 * stale / 4.0 + 0.5 * wrong / 2.0,
        "wrong_identity_rate": wrong / 2.0,
    }


def _write(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def _bundle_files(variant: str, seed: int, observations: Sequence[Mapping[str, object]], truths: Sequence[Mapping[str, object]]) -> dict[str, bytes]:
    facts, decisions = run_variant(variant, seed, observations)
    metrics = _score(decisions, truths, facts)
    files = {
        "compiled-facts.jsonl": _jsonl(facts), "metrics.json": _canonical(metrics),
        "observation-trace.jsonl": _jsonl(observations), "query-decisions.jsonl": _jsonl(decisions),
        "scorer-truth.jsonl": _jsonl(truths),
    }
    inventory = [{"bytes": len(content), "path": name, "sha256": _sha(content)} for name, content in sorted(files.items())]
    replay = _sha(b"".join(files[name] for name in sorted(files) if name != "metrics.json"))
    manifest = {
        "claim_status": "ENGINEERING_NONCONFIRMATORY", "disposition": "COMPLETE", "files": inventory,
        "observation_trace_sha256": _sha(files["observation-trace.jsonl"]), "replay_sha256": replay,
        "schema_version": "exp04-engineering-bundle-manifest-v1", "seed": seed, "variant_id": variant,
    }
    files["bundle-manifest.json"] = _canonical(manifest)
    return files


def _load_rows(path: Path) -> tuple[dict[str, object], ...]:
    return tuple(json.loads(line) for line in path.read_text(encoding="ascii").splitlines())


def _derive(raw: Path) -> dict[str, bytes]:
    root_manifest_bytes = (raw / "raw-manifest.json").read_bytes()
    root_manifest = json.loads(root_manifest_bytes)
    if _canonical(root_manifest) != root_manifest_bytes:
        raise ScreenError("raw manifest is noncanonical")
    metric_rows: list[dict[str, object]] = []
    samples: list[dict[str, object]] = []
    for entry in root_manifest["bundles"]:
        bundle = raw / "bundles" / entry["bundle_id"]
        manifest_bytes = (bundle / "bundle-manifest.json").read_bytes()
        if _sha(manifest_bytes) != entry["manifest_sha256"]:
            raise ScreenError("bundle manifest hash mismatch")
        manifest = json.loads(manifest_bytes)
        for item in manifest["files"]:
            content = (bundle / item["path"]).read_bytes()
            if len(content) != item["bytes"] or _sha(content) != item["sha256"]:
                raise ScreenError("bundle member hash mismatch")
        observations = _load_rows(bundle / "observation-trace.jsonl")
        truths = _load_rows(bundle / "scorer-truth.jsonl")
        facts, decisions = run_variant(str(manifest["variant_id"]), int(manifest["seed"]), observations)
        if _jsonl(facts) != (bundle / "compiled-facts.jsonl").read_bytes() or _jsonl(decisions) != (bundle / "query-decisions.jsonl").read_bytes():
            raise ScreenError("bundle replay mismatch")
        metrics = _score(decisions, truths, facts)
        if _canonical(metrics) != (bundle / "metrics.json").read_bytes():
            raise ScreenError("metric replay mismatch")
        metric_rows.append({"seed": manifest["seed"], "variant_id": manifest["variant_id"], **metrics})
        truth_by_case = {row["case_id"]: row for row in truths}
        for decision in decisions:
            truth = truth_by_case[decision["case_id"]]
            working = decision["answer"] == truth["expected_answer"] and decision["decision"] == truth["expected_decision"]
            samples.append({
                "answer": decision["answer"], "case_id": decision["case_id"], "class": "WORKING" if working else "NONWORKING",
                "decision": decision["decision"], "expected_answer": truth["expected_answer"],
                "expected_decision": truth["expected_decision"], "query_id": decision["query_id"],
                "seed": manifest["seed"], "variant_id": manifest["variant_id"],
            })
    variants = []
    for variant in VARIANTS:
        rows = [row for row in metric_rows if row["variant_id"] == variant]
        variants.append({
            "ambiguous_retrieval_rate": sum(float(row["ambiguous_retrieval_rate"]) for row in rows) / len(rows),
            "correct_rate": sum(float(row["correct_rate"]) for row in rows) / len(rows),
            "repeated_scan_count": sum(int(row["repeated_scan_count"]) for row in rows) / len(rows),
            "seed_count": len(rows),
            "stale_action_rate": sum(float(row["stale_action_rate"]) for row in rows) / len(rows),
            "stale_wrong_composite": sum(float(row["stale_wrong_composite"]) for row in rows) / len(rows),
            "variant_id": variant,
            "wrong_identity_rate": sum(float(row["wrong_identity_rate"]) for row in rows) / len(rows),
        })
    selected: list[dict[str, object]] = []
    for variant in VARIANTS:
        candidates = sorted((row for row in samples if row["variant_id"] == variant), key=lambda row: (int(row["seed"]), str(row["query_id"])))
        for label in ("WORKING", "NONWORKING"):
            match = next((row for row in candidates if row["class"] == label), None)
            selected.append(match if match is not None else {"class": "CLASS_NOT_OBSERVED", "denominator": len(candidates), "requested_class": label, "variant_id": variant})
    aggregate = {"bundle_count": len(metric_rows), "case_answer_count": len(samples), "claim_status": "ENGINEERING_NONCONFIRMATORY", "schema_version": "exp04-engineering-aggregate-v1", "variants": variants}
    annotations = {"samples": selected, "schema_version": "exp04-engineering-annotations-v1", "selection_rule": "FIRST_CANONICAL_WORKING_AND_NONWORKING_PER_VARIANT_WHEN_OBSERVED"}
    recipe = {
        "code_sha256": _sha(inspect.getsource(inspect.getmodule(run_screen)).encode("utf-8")),
        "inputs": {"raw_manifest_sha256": _sha(root_manifest_bytes)},
        "operation": "validate every bundle hash; replay run_variant from observation-trace without scorer truth; join scorer truth; recompute metrics, aggregate, annotations, and report",
        "schema_version": "exp04-engineering-recipe-v1", "seeds": list(SEEDS), "variants": list(VARIANTS),
    }
    by = {row["variant_id"]: row for row in variants}
    report = (
        "# Experiment 04 Engineering Memory Screen\n\n"
        "Status: ENGINEERING_NONCONFIRMATORY\n\n"
        f"The BASE-only screen completed {len(metric_rows)} bundles and {len(samples)} case answers. "
        f"M4 correctness was {by['M4']['correct_rate']:.3f} versus M0 {by['M0']['correct_rate']:.3f}, "
        f"V0 {by['V0']['correct_rate']:.3f}, and H0 {by['H0']['correct_rate']:.3f}. "
        f"M5 stale/wrong composite was {by['M5']['stale_wrong_composite']:.3f} versus M4 {by['M4']['stale_wrong_composite']:.3f}. "
        f"M6 ambiguous retrieval was {by['M6']['ambiguous_retrieval_rate']:.3f} versus M5 {by['M5']['ambiguous_retrieval_rate']:.3f}.\n\n"
        "These fixed public engineering seeds do not support confirmation, promotion, or a production memory claim.\n"
    ).encode("ascii")
    return {"RESULTS.md": report, "aggregate.json": _canonical(aggregate), "annotations.json": _canonical(annotations), "recipe.json": _canonical(recipe)}


def run_screen(output: Path, *, seeds: Sequence[int]) -> None:
    if output.exists() or tuple(seeds) != SEEDS:
        raise ScreenError("output must be absent and seeds must equal the frozen engineering set")
    bundles = output / "raw" / "bundles"; derived = output / "derived"
    bundles.mkdir(parents=True); derived.mkdir()
    inventory = []
    for variant in VARIANTS:
        for seed in SEEDS:
            observations, truths = generate_seed(seed)
            bundle_id = f"{variant}.seed-{seed}"; destination = bundles / bundle_id; destination.mkdir()
            files = _bundle_files(variant, seed, observations, truths)
            for name, content in files.items(): _write(destination / name, content)
            inventory.append({"bundle_id": bundle_id, "manifest_sha256": _sha(files["bundle-manifest.json"])})
    raw_manifest = {"bundles": inventory, "claim_status": "ENGINEERING_NONCONFIRMATORY", "schema_version": "exp04-engineering-raw-manifest-v1"}
    _write(output / "raw" / "raw-manifest.json", _canonical(raw_manifest))
    for name, content in _derive(output / "raw").items(): _write(derived / name, content)


def reconstruct_screen(raw: Path, clean: Path) -> None:
    if clean.exists() or not raw.is_dir() or raw.is_symlink():
        raise ScreenError("raw input must be regular and clean output absent")
    derived = _derive(raw)
    clean.mkdir()
    for name, content in derived.items(): _write(clean / name, content)
