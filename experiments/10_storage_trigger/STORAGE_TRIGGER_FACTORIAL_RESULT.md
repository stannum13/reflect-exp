# Experiment 10: Storage x Trigger Factorial Result

Status: **COMPLETE — synthetic engineering evidence only**

This experiment used the explicitly labeled deterministic
`ORACLE_TYPED_SEMANTIC_V1` planner. It did not run pi0.5, another VLA, or a
frontline model. Its claim scope is limited to the behavior of the frozen
storage and trigger implementations in the synthetic task dynamics.

## Frozen execution

- Implementation commit: `f6d4448a0eaef5c7d149bed51459997aad98297b`
- Matrix: 5 storage variants x 5 trigger variants x 4 disturbance families x
  2 severities x 3 mission horizons x 20 paired seeds
- Completed episodes: 12,000 / 12,000 (all identities unique)
- Retained step observations: 120,950 JSONL records
- Seeds: 20264101 through 20264120; bootstrap seed 20264999
- Runtime: 12.19 s wall, 11.60 s user, 0.54 s system on the recorded host
- Overall completion: 8,220 / 12,000 = 0.685

The raw manifest SHA-256 is
`45d5facb9bc3376f5d3b69a9296fdf3e2f404f1acedfb136a1ab524f57b49cb7`.
It binds the frozen config, seeds, 12,000-row episode table, 120,950-row step
stream, implementation commit, implementation-source hash, and exact matrix
identity. The derived manifest SHA-256 is
`0ec41b0c3bb95270671e888b8176d4498a2b5d5d68bfe55a296a05ea7dc64fc7`.

## Directional results

The paired bootstrap resampled the 20 seed clusters 10,000 times, retaining
all factorial rows for each selected seed.

- With `NO_MEMORY`, `HYBRID` improved completion over `PERIODIC_ONLY` by
  +0.3750 (95% bootstrap interval +0.3417 to +0.4083). It also reduced late
  trigger ticks by 1.3750, at +1.3042 cost-proxy units.
- With `LIVE_EPISODIC`, completion exceeded `FIXED_SNAPSHOT` by +0.7500 under
  each active replan trigger (95% interval +0.7500 to +0.7500). The paired
  seed differences are constant in this deterministic design, hence the
  zero-width interval; this is not a population-generalization claim.
- Once live/episodic storage was present, `HYBRID` and `PERIODIC_ONLY` both
  completed every episode. For `LIVE_EPISODIC`, hybrid triggering retained
  that completion while reducing late-trigger ticks by 0.6667 and cost proxy
  by 1.6293 (both paired against periodic-only).
- `FIXED_SNAPSHOT` remained at 0.25 completion for every trigger, while
  `LIVE_BELIEF`, `EPISODIC_ONLY`, and `LIVE_EPISODIC` rose from 0.25 with no
  replanning to 1.00 with every active trigger. The no-memory active triggers
  ranged from 0.4375 (`PERIODIC_ONLY`) to 0.8125 (failure/event/hybrid).
- Completion by disturbance family, averaged over the factorial, was 1.0000
  for `CONTROL_FAILURE`, 0.6133 for `POSE_SHIFT`, and 0.5633 for both
  `AVAILABILITY_LOSS` and `RESTRICTION_CHANGE`. These family summaries are
  descriptive, not separately bootstrapped estimands.

The raw and tidy tables retain completion/progress, stale decisions, repeated
failures, false/late/wasted triggers, semantic/motion/control wake counts and
latency proxies, retries/escalations/aborts, storage reads/writes/bytes/age,
and the declared budget/cost proxy. Canonical annotations retain an observed
working and nonworking example for every cell where both classes occurred,
and explicitly mark absent classes rather than fabricating examples.

## Validation and reconstruction

The independent reconstruction reads only `raw/`, verifies every manifest
member and matrix identity, reconstructs episode metrics from the JSONL step
stream rather than trusting the episode summary, and regenerates all derived
tables, annotations, plots, report, and manifest. Reconstruction into a new
temporary directory produced 10 / 10 files byte-identical to `derived/`.

The committed deterministic SVG and 600 x 360 RGB PNG are generated from the
same tidy storage-trigger summary. `plot-style.json` records plot dimensions,
palette, axis meaning, and series order independent of display theme.

## Inference boundary

These results isolate implementation choices in a deterministic synthetic
oracle experiment. They do not establish pi0.5 interface capabilities,
frontline VLA performance, physical robot performance, or statistical
generalization outside this frozen task generator. The zero-width intervals
on several contrasts expose the intentionally deterministic paired structure;
they must not be read as broad certainty.
