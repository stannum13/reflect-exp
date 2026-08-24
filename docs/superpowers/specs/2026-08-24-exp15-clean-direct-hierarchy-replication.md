# Exp15 clean direct-hierarchy replication

**Status:** preregistered and approved for autonomous execution  
**Date:** 2026-08-24  
**Question:** does a fresh, untuned replication confirm or refute the bounded
direct physical hierarchy signal observed exploratorily in Exp13?

## Scientific scope

Exp15 is a replication informed by Exp13, not a newly discovered experiment.
It tests the same observable-only hierarchy in the same MuJoCo manipulation
kernel. It may support or fail to support a bounded direct-outcome hierarchy
signal. It cannot establish causal minimality, prove that a recovery was the
lowest sufficient intervention, demonstrate a learned VLA, or establish
real-world robotic transfer.

The implementation, policy, disturbance doses, controllers, matrix, metrics,
and gates are frozen before outcomes. Outcome-driven tuning is forbidden. The
only post-outcome source edit permitted is inserting already-produced SHA-256
bindings into the portable-pack verifier; that edit cannot change a run,
metric, statistical contrast, gate, sample rule, graph, or narrative rule.

## Frozen reuse contract

Exp15 imports the exact controller, runtime, policy, scorer, and evidence code
used by the final Exp13 implementation at integration commit
`b79b5daa40fc4612c3e2aa7bcf96e64d3594d895`. It copies Exp13's direct adapter
without changing policy behavior or doses. The only intentional changes are:

- experiment and episode IDs use `exp15`;
- the fresh realization namespace is `exp15-direct-hierarchy-replication-v1`;
- primary seeds are `20262201..20262210` and sensitivity seeds are the first
  five of that range;
- lifecycle wording describes a confirmatory replication rather than Exp13's
  formally invalid exploratory chronology.

Architecture, controller, family, severity, and matrix-role values must match
Exp13 cell-for-cell after adding 100 to each Exp13 seed. A source test checks
this parity. The policy receives only `(architecture, observable, budget)`.

## Matrix and outcomes

The primary matrix is `R0/R1/R2/R3 * 6 families * 2 severities * 10 paired
seeds` on `P6-res0p5-slew48`, exactly 480 cells. Sensitivity is R3 over the same
12 family/severity cells and five paired seeds on `P4-lookahead1-dqon`, exactly
60 cells. Total: 540 dispositions.

Families are control impulse, control dropout, motion target shift, motion path
infeasible, semantic object unavailable, and semantic restriction change.
LOW/HIGH doses are copied exactly from Exp13: impulse `0.14/0.26 N.m` for
`5/10` ticks, dropout `25/50` ticks, shift `0.040/0.065 m`, obstacle radius
`0.0375/0.0475 m`, and semantic delivery delay `2/10` ticks.

Authoritative outcomes come from independently scored raw physics: mission
success, safety composite, and final-target progress. Secondary measures are
retry count, control/motion/semantic wakes, recovery latency, aborts, peak/RMS
torque, peak contact force, trajectory length, and action cost.

## Lifecycle

1. Commit this preregistration, source, tests, and portable-pack machinery.
2. Produce and commit a canonical freeze naming that exact source commit.
3. Preflight all 540 cells before outcomes. Store one canonical typed receipt
   per identity and a closed preflight index. Commit the index receipt.
4. Execute create-only, resumable outcomes. The first 50 dispositions are
   reported before continuing to all 540. `NOT_RUN` and `INVALID_EXECUTION`
   are authoritative outcomes and are never silently replaced.
5. Seal a recursive local inventory and publish a compact portable pack with
   all dispositions, every complete-episode manifest, selected full raw
   working/nonworking episodes, derived data, graphs, and reconstruction data.
6. Update only the two ministerial verifier hashes, verify in a clean clone,
   preserve attack regressions, and request independent review. The producing
   agent cannot approve its own evidence.

`execute` is forbidden until all 540 preflight receipts validate against the
frozen source/configuration. It rechecks each receipt before executing its cell.

## Registered analysis and decision

The resampling unit is the paired seed cluster. Ten thousand deterministic
PCG64 bootstrap draws estimate R3 minus R0, R1, and R2 for success, safety,
progress, and total wakes. R2 remains the fixed best simpler comparator chosen
from Exp13 before replication outcomes. P4 minus P6 is a separate five-cluster
sensitivity analysis. Family and severity cells are reported separately.

The replication supports the bounded signal only when evidence/lifecycle gates
pass and all of the following hold:

1. For every simpler comparator, success lower 95% bound is at least `-0.10`.
2. For every simpler comparator, safety upper 95% bound is at most `+0.10`.
3. For every simpler comparator, progress lower 95% bound is at least `-0.05`.
4. Against fixed R2, total-wake upper 95% bound is strictly below zero.
5. No family/severity R3-minus-R2 success difference is below `-0.20`.

Passing yields `SUPPORTS_BOUNDED_DIRECT_HIERARCHY_REPLICATION`; a statistical
gate failure yields `DOES_NOT_SUPPORT_BOUNDED_DIRECT_HIERARCHY_REPLICATION`;
an identity, freeze, scorer, lifecycle, inventory, or reconstruction failure
yields `INVALID_EXPERIMENT`. None permits a causal-lowest claim.

## Portable evidence contract

The compact pack uses an exact root allowlist and exact schemas. It contains the
freeze, preflight index, 540 dispositions, one manifest for every COMPLETE row,
the full local inventory, deterministic selected raw samples, equal-weight
seed-cluster bootstrap inputs and all 10,000 draws, architecture summaries,
family/severity tables, failure taxonomy, gate evaluation, graph tables/style,
and deterministic SVG/PNG graphs. Reconstruction must reproduce every derived
byte. Regression tests cover rehashed disposition substitution, selected-raw
substitution, missing or extra files, symlinks, schema downgrade, disposition
schema injection, annotation swaps, freeze substitution, and preflight removal.
