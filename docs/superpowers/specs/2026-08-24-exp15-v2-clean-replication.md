# Exp15 V2 clean direct-hierarchy replication

**Status:** awaiting independent source/record audit; not approved to freeze or run
**Date:** 2026-08-24
**Predecessor:** V1 is permanently `INVALID_EARLY_AUDIT` after 32 sealed
dispositions. No V1 outcome payload informed this design.

V2 asks whether the bounded exploratory Exp13 direct-outcome signal replicates
without tuning. It makes no learned-VLA, real-world-transfer, causal-minimality,
or lowest-sufficient-recovery claim. Runtime, observable-only policy, scorer,
P6/P4 controllers, disturbance families/doses, 540-cell matrix, metrics, and
scientific gates remain exactly those preregistered for V1. Only audit/lifecycle
defects are corrected.

## Fresh identity and matrix

- Experiment: `exp15-direct-hierarchy-replication-v2`; episode prefix `exp15v2`.
- P6 primary seeds: exactly `20262301..20262310`.
- P4 R3 sensitivity seeds: exactly `20262301..20262305`.
- Primary: `4 architectures * 6 families * 2 severities * 10 seeds = 480`.
- Sensitivity: `R3 * 6 families * 2 severities * 5 seeds = 60`.
- Total dispositions: 540; R2 is the fixed best simpler comparator.

The exact doses remain impulse `0.14/0.26 N.m` for `5/10` ticks, dropout
`25/50` ticks, target shift `0.040/0.065 m`, obstacle radius
`0.0375/0.0475 m`, and semantic delivery delay `2/10` ticks. The physical
kernel and policy call `(architecture, observable, budget)` are unchanged.

## Audit and execution gates

Source, tests, analysis, and pack verifier are committed first. Freeze requires
a separate canonical `APPROVE` receipt naming the exact 40-character source
commit and experiment ID. The receipt must be the sole file in a separate Git
commit whose parent is the approved source commit; the runner resolves its exact
bytes with `git show`. The approval is not part of the outcome-generating source
closure. Freeze additionally proves every current closure byte and exact closure
path against the approved source commit tree. A 540-cell architecture-blind
preflight must seal before outcomes.

Execution is create-only and resumable. Without a separate first-50 release,
the runner can seal at most 50 dispositions and then must pause. Release requires
a canonical independent `APPROVE` receipt bound to the source, freeze, and exact
50-disposition inventory. It is likewise the sole file in a separate Git commit,
and the runtime reloads its exact bytes from that commit on every continuation.
All first-50 disposition schemas and complete raw manifests are independently
validated. No cell 51 can execute without it. `NOT_RUN`,
`INVALID_EXECUTION`, and interrupted attempts remain preserved.

## Exact resampling and effective sample size

Primary contrasts use 10,000 PCG64 seed-cluster bootstrap draws with seed 1313.
Each draw samples `n_eff` entries with replacement from the sorted actual set of
paired primary seed clusters (ten entries in the complete registered case).
Each cluster mean equally weights every available paired family/severity member
within that seed. Missing primary clusters therefore produce an `n_eff`-sized
descriptive/non-support bootstrap rather than a KeyError or configured-size
pseudoreplication.

P4-minus-P6 sensitivity is not PCG64. Its exact preregistered deterministic plan
starts from the lexicographically ordered Cartesian product
`product([20262301,...,20262305], repeat=5)`, containing 3,125 five-seed tuples.
The 10,000 draws are three complete copies of that order (9,375 draws), followed
by the 625 rows at integer indices produced by
`linspace(0, 3124, 625, dtype=int)` from a fourth copy. Each sampled tuple
equally weights its five sampled seed-cluster means. This inferential plan runs
only when all five expected paired clusters exist. With fewer than five, the
report gives the actual descriptive estimate and `n_eff`, records zero
inferential draws and null interval bounds, and the support gate is false.

Every effect reports `n_eff` from the actual number of paired seed clusters,
never a configured constant. Scientific support additionally requires every
primary architecture/metric contrast to have `n_eff=10` and both sensitivity
metrics to have `n_eff=5`. Any `INVALID_EXECUTION` invalidates support.

## Registered scientific gates

Using 10,000 registered draws, R3 minus each of R0/R1/R2 must have success lower
95% bound at least `-0.10`, safety upper bound at most `+0.10`, and progress
lower bound at least `-0.05`. R3 minus fixed R2 must have total-wake upper bound
strictly below zero. Every observed R3-minus-R2 family/severity success
difference must be at least `-0.20`. Passing gives
`SUPPORTS_BOUNDED_DIRECT_HIERARCHY_REPLICATION`; statistical failure gives
`DOES_NOT_SUPPORT_BOUNDED_DIRECT_HIERARCHY_REPLICATION`; lifecycle/evidence
failure gives `INVALID_EXPERIMENT`.

## Portable evidence and sample semantics

The pre-outcome compact contract is fixed: exact allowlist/schema, freeze,
preflight index, 540 dispositions, all applicable complete-episode manifests,
full local inventory, bootstrap cluster inputs and 10,000 draws,
family/severity and gate tables, graph data/style, deterministic SVG/PNG, and
selected raw episodes. Raw episode payloads retain
`failure-event-states.jsonl`; selected episodes therefore support the same raw
rescoring scope as the local evidence.

Working and nonworking annotations each target the primary P6 R3 population.
Selection is the first lexicographic matching complete row. If a legitimate
category is absent, the annotation explicitly records `category_status=ABSENT`,
`episode_id=null`, and no selected-episode directory; it never substitutes a
different architecture/role or crashes. All derived bytes reconstruct exactly.
Only the two preregistered ministerial expected-hash constants may change after
outcomes; no run, score, resampling, gate, selection, graph, or narrative logic
may change.
