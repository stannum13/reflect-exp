# Hierarchical Recovery V3 Preregistered Construct-Valid Experiment

**Status:** preregistered; implementation and outcome matrix not yet authorized
**Date:** 2026-08-23
**Authority:** nonconfirmatory engineering screen only

## Supersession

V1 remains immutable integration/conformance evidence. V2 remains immutable failed
qualification evidence. Neither supports nor refutes the hierarchy hypothesis. V3 is
a new experiment with fresh source, namespace, evidence root, and outcome authority.

## Question and fixed comparison

On genuinely varied MuJoCo manipulation realizations, does R3 layer-matched recovery
retain success while reducing unnecessary interventions relative to R0 local-only,
R1 semantic-always, and R2 motion-then-semantic recovery?

Memory is fixed at `T3_LIVE_BELIEF_V1`. Budgets are fixed at two local attempts, two
motion replans, and one semantic replan. The primary controller is the existing P6
residual-0.5/slew-48 implementation; the sensitivity controller is the existing
repaired P4 one-tick/dq-on implementation. Their call paths and output bytes must be
demonstrably distinct on at least one pre-outcome qualification case.

## Hard outcome-start gate

No V3 outcome seed may run until a fresh read-only construct reviewer approves all
items below on calibration-only seeds `20261891..20261894`. A failed qualification
may change implementation and tests, but after approval the source/config is frozen
and cannot change until all V3 outcomes are sealed.

Qualification must prove:

1. sampled injection tick is actually reached and equals the retained injection row;
2. every disturbance changes retained physical/action/memory bytes relative to its
   matched anchor in the intended way;
3. R0/R1/R2/R3 execute distinct retained decision/intervention sequences where their
   rules differ;
4. P6 and repaired P4 enter their real existing executor/controller paths and emit
   different bound controller identities/action bytes;
5. every retry/replan advances MuJoCo, consumes a budget, re-observes, and cannot reset
   without successful execution of different command-content bytes;
6. no policy/inference call chain can receive scenario ID/domain/cause/expected level;
7. a separate scorer reconstructs every authoritative metric from immutable raw
   state/action/semantic/world bytes, never executor-authored result booleans;
8. unsafe, forbidden, collision, stale, invalid-action, wrong-object, missed-dwell,
   and loop/reset positive controls each independently force terminal failure;
9. full raw replay regenerates decisions, MuJoCo traces, scorer rows, terminal, and
   derived qualification output byte-for-byte; and
10. architecture-independent feasibility prechecks run before each realization and
    can produce a retained `NOT_RUN` positive-control example.

The approval report and exact frozen qualification hashes are retained beside the V3
freeze record.

## Environment and realized disturbances

The experiment uses the existing planar-arm MuJoCo model plus experiment-local task
objects and obstacle geoms. Semantic/task entities are represented by immutable IDs,
authorization facts, affordances, regions, and target poses. Full state, contact,
reference, action, torque, and command-envelope rows are sampled at 500 Hz.

Scenarios remain two anchors and six disturbances:

- nominal anchor;
- slow-policy anchor whose delay remains inside the action-age contract;
- torque impulse/load applied in N·m to the MuJoCo actuator/generalized force path;
- command dropout that withholds/holds the command for the sampled duration;
- target pose shift in Cartesian metres inside the same object's admissible region;
- a real MuJoCo/geometric obstacle that invalidates the active straight segment while
  a verified collision-free waypoint path exists;
- object-unavailable observation delivered after the sampled delay, with one
  independently authorized alternative;
- restriction observation delivered after the sampled delay, invalidating the active
  object/affordance/region while one independently authorized alternative remains.

The semantic clock is causal: future events are invisible until delivery tick. The
first invalidation tick transitions immediately to an objectless safe hold. No
forbidden/invalid object command may execute while waiting for semantic delivery or
replanning.

## Genuine variation and matrix

Fresh outcome seeds are `20261801..20261810`. A canonical seed stream varies initial
joints, damping, target/alternate poses, injection tick 600..900, impulse, dropout,
target shift, obstacle, and semantic delivery delay within the V2-preregistered safe
ranges. Every sampled quantity must be used in execution and audited by parameter-use
receipts.

- Primary: 4 architectures × 8 scenarios × 10 seeds = 320 P6 episodes.
- Sensitivity: R3 × 8 scenarios × seeds `20261801..20261805` = 40 repaired-P4
  episodes.
- Total: 360 terminal or preregistered `NOT_RUN` dispositions.

Each disturbed template must have at least 8/10 distinct executed physical trace
hashes and parameter-use receipts; each domain must contain at least two distinct
physical realizations. Identity-only or unused-parameter variation fails the matrix.

## Policy, executor, and budget boundaries

- Injector retains hidden cause separately and mutates only world/physics/event
  inputs.
- Observable builder consumes retained past/present trace, command, geometry, and
  delivered-memory bytes only.
- Policy receives typed observables, architecture, and budget only.
- Executor runs the selected existing controller/representation against exact
  retained commands/trajectories.
- Scorer runs after execution using immutable action envelopes and independent world
  truth. It cannot import executor result flags.

Every per-tick action envelope retains tick, controller ID, mode, object ID or none,
affordance, command-content hash, generation tick, action age, Cartesian/joint
reference, executed actuator/torque command, and hold reason. All generated commands
and trajectories are retained, not only the final one.

Command-content identity hashes executable target/path/controller content only;
metadata cannot create a new identity. A budget reset event must bind old/new content
hashes and the scorer-verified successful execution receipt.

## Independent terminal and safety scorer

Terminal success is scorer-only and requires all of:

- correct currently authorized object/affordance/region;
- target error below frozen tolerance for the complete dwell;
- zero forbidden, collision, invalid-action, unsafe, nonfinite, stale-decision,
  wrong-object, loop, or reset violations;
- valid command age/shape/hash/content on every non-hold tick;
- all joint, torque, contact, and workspace contracts satisfied; and
- mission postcondition satisfied after the final recovery.

The scorer recomputes these from full trace/action/semantic/world bytes. Executor
booleans are non-authoritative debug fields and may be omitted entirely.

## Predeclared gates

`SUPPORTS_CONSTRUCT_VALID_LAYER_MATCHED_HIERARCHY` requires:

1. R3's paired unsafe/forbidden/collision/invalid/stale/loop/reset totals are no
   greater than every comparator, and all scorer positive controls passed;
2. paired R3 success strictly exceeds R0 across motion+semantic realizations both in
   the combined estimator and without a negative template-specific difference;
3. R3 success is noninferior to R1 at frozen binary margin 0.00 while retained
   semantic intervention count is strictly lower;
4. on control disturbances R3 success is noninferior at margin 0.00, semantic
   interventions are lower than R1, and motion interventions are lower than R2;
5. independently counterfactual-scored lowest-sufficient assignment is at least 80%,
   with zero loop/reset violations;
6. paired R3-minus-best-comparator success is nonnegative separately for control,
   motion, and semantic domains;
7. parameter-use and executed-trace diversity requirements above pass; and
8. qualification approval, exact 360 disposition inventory, source/config freeze,
   cause-boundary audit, raw replay, and clean reconstruction all pass.

All architecture comparisons consume retained paired rows, never marginal summaries.
Intervention counts consume retained decision events, never architecture/domain
formulas. Lowest-sufficient truth comes from an architecture-independent
counterfactual sufficiency scorer over observable histories, not scenario taxonomy.

## Analysis and evidence

Retain template-specific paired rows and 10,000-draw realization bootstraps plus a
template-cluster sensitivity analysis. Report effective `n=10 realizations per
template` and `2 templates per domain`; draw count is never presented as evidence
count. Bootstrap inputs, draw seeds, draws, and results are canonical raw-enough
files.

Every episode retains realization and parameter-use receipt, precheck, semantic/world
truth, complete T3 memory/event ledger, observations, all plans/commands/trajectories,
decision/budget/reset events, 500 Hz trace/action envelopes, hidden cause, independent
scorer rows, and terminal disposition. Manifests authenticate every member. Invalid
and `NOT_RUN` attempts remain inventoried.

Figures ship as deterministic SVG plus authenticated PNG companions, canonical graph
tables, reconstruction code, hashes, and working/nonworking/class-absent examples.

## Interpretation

A pass supports only a narrow nonconfirmatory mechanistic result on this sampled cell.
A fail is reported as a genuine hierarchy-negative result only if Gate 8 proves the
construct. Any construct, scorer, freeze, or replay failure is `INVALID_EXPERIMENT`,
not evidence for or against the hierarchy.
