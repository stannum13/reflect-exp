# Experiment 04 Fixed-vs-Unfixed Memory Indicative Ablation

Status: `PREREGISTERED_BEFORE_OUTCOMES`

## Question and scope

This bounded synthetic ablation asks whether allowing an existing M5-style
memory to update online improves decisions after pose, availability,
restriction, and attempt-history changes. It also tests whether the semantic
object/geometric store and append-only episodic history make complementary
contributions when kept separate.

This run can establish an indicative causal effect of online memory updates in
this frozen generator and controller. It cannot establish perception quality,
real-robot performance, generalization beyond the synthetic task family, or a
production storage/database choice.

## Frozen matrix

- Seeds: every integer from `20263001` through `20263064`, inclusive.
- Variants, run on byte-identical observation streams within each seed:
  - `FIXED_M5`: confidence/staleness-aware semantic, geometric, and episodic
    stores initialized at tick 0 and then frozen.
  - `LIVE_SEMANTIC`: semantic/geometric stores update online; episodic history
    remains frozen after tick 0.
  - `LIVE_EPISODIC`: episodic history updates online; semantic/geometric stores
    remain frozen after tick 0.
  - `LIVE_SEPARATE`: semantic/geometric stores and episodic history both update
    online through separate interfaces.
- Each seed has three valves, four rooms, and three mutation checkpoints. The
  generator permutes exactly one each of `POSE_MOVE`, `AVAILABILITY_CHANGE`, and
  `RESTRICTION_CHANGE`; it also emits a failed manipulation attempt after the
  first checkpoint. Entity identities, initial rooms/poses, mutation targets,
  failed target/reason, observation delivery, confidence, and event order are
  seed-derived with NumPy `PCG64`.
- All variants receive the same initial snapshot, subsequent observation/event
  stream, controller code, confidence threshold `0.70`, pose TTL `2` ticks,
  and deterministic tie break `(room_id, entity_id)`.
- Queries at each checkpoint are `SELECT_TARGET`, `POSE_ACTION`,
  `RETRY_DECISION`, and `FAILURE_EXPLANATION`: 12 scored decisions per
  variant-seed, 3,072 decisions total over 256 matched runs.
- Runner inputs are only `(variant_id, seed, observation_stream)`. Hidden truth
  is generated into a separate scorer artifact and joined after immutable
  decisions exist.

## Intervention and controller semantics

Semantic/geometric updates replace a field only when the incoming fact has a
newer `(observed_tick, event_id)` key and confidence at least `0.70`; low
confidence facts remain in the raw trace but do not become authoritative.
Episodic updates append attempt outcomes without modifying semantic state.

At a checkpoint the controller selects the lexicographically first remembered
valve whose room is not remembered restricted and whose availability is
`AVAILABLE`. It acts only when the selected pose is no more than two ticks old;
otherwise it requests `RESCAN`. A remembered failure for the selected valve
causes it to choose the next eligible valve (`REPLAN`) or request `RESCAN` if
none exists. Failure explanations come only from episodic history. No variant
may consult hidden scorer truth.

## Frozen endpoints

Primary endpoint: decision correctness over all 12 decisions per episode.

Secondary adverse endpoints:

- stale-action rate: `ACT` on a pose that hidden truth says is not usable;
- invalid-target rate: selected target is unavailable or in a restricted room;
- repeated-failed-target rate: controller selects a target already known in
  hidden truth to have failed;
- unnecessary-scan rate: `RESCAN` when hidden truth contains an eligible target
  with a usable pose;
- failure-explanation accuracy;
- planner context fact count and canonical serialized context bytes.

The adverse composite is the unweighted mean of stale-action,
invalid-target, and repeated-failed-target indicators per episode.

Paired effects are computed as candidate minus comparator per seed. Intervals
are percentile cluster bootstraps over seeds using 20,000 draws from NumPy
`PCG64(20263999)`. Rates are calculated within seed before resampling.

## Frozen indicative gates

The result is `SUPPORTS_ONLINE_SEPARATE_MEMORY` only if all gates pass:

1. `LIVE_SEPARATE - FIXED_M5` correctness has point estimate at least `+0.10`
   and 95% interval lower bound above zero.
2. `LIVE_SEPARATE - FIXED_M5` adverse composite is negative and its 95%
   interval upper bound is below zero.
3. On `POSE_MOVE`, `AVAILABILITY_CHANGE`, and `RESTRICTION_CHANGE` decisions,
   `LIVE_SEPARATE` correctness exceeds `LIVE_EPISODIC` with interval lower
   bound above zero.
4. On `RETRY_DECISION` and `FAILURE_EXPLANATION`, `LIVE_SEPARATE` correctness
   exceeds `LIVE_SEMANTIC` with interval lower bound above zero.
5. On tick-0 control decisions before any mutation, no live variant is more
   than `0.02` below `FIXED_M5` in correctness. These control decisions are
   logged but excluded from the 12 primary decisions.
6. Every raw member hash validates; every decision replays without scorer
   truth; all canonical CSV/JSON/SVG/report artifacts reconstruct byte-for-byte.

If gates 3 or 4 fail, the run may support online updating but not the claim that
the two separate stores are complementary. Any missed integrity gate yields
`INVALID_EVIDENCE`, not a scientific result.

## Required evidence

The committed result root will contain canonical raw JSONL streams, hidden
truth, decisions, and per-decision scores; matched per-seed CSV; endpoint and
paired-effect CSV graph data; deterministic SVG graphs; explicitly annotated
working and nonworking samples; a result report; an evidence manifest and
`SHA256SUMS`; and a stdlib-only reconstruction program. No result PNG is
required because SVG is canonical and lossless.
