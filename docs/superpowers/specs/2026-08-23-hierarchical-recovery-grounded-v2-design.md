# Grounded Hierarchical Recovery V2 Design

**Status:** preregistered corrective engineering experiment; no V2 outcomes exist
**Date:** 2026-08-23
**Classification:** nonconfirmatory, simulation-only

## Why V2 exists

V1 is preserved unchanged as a nonworking construct-validity sample. Its MuJoCo
execution and evidence reconstruction were real, but recovery signatures were
assigned from scenario identity, recoveries resolved contract flags before physics,
local retries did not advance the simulator, safety was incompletely scored, and
declared seeds did not vary the episode. V1 therefore has integration/conformance
value only. Its `SUPPORTS_LAYER_MATCHED_HIERARCHY` analyzer output has no scientific
promotion authority.

V2 asks the same narrow architectural question with failures and recovery outcomes
grounded in simulator state, memory observations, independently computed contracts,
and time-advanced execution.

## Frozen experimental question

Does layer-matched recovery preserve eventual mission success while reducing
unnecessary cross-layer intervention relative to local-only, semantic-always, and
motion-then-semantic recovery when disturbance realization, observable failure
signature, retry result, safety, and terminal success are independently computed?

## Architectures and memory

The four architectures remain exactly R0 `LOCAL_ONLY`, R1 `SEMANTIC_ALWAYS`, R2
`MOTION_THEN_SEMANTIC`, and R3 `LAYER_MATCHED`. Memory remains fixed at
`T3_LIVE_BELIEF_V1`. The complete append-only observation/event ledger bytes are
retained; a rolling hash alone is insufficient.

Budgets remain two control recoveries, two motion replans, and one semantic replan.
A budget reset is permitted only after content bytes of a newly generated executable
command differ from the prior executable command. Command ID, timestamp, and other
metadata are excluded from command-content identity. The runtime must use the same
guarded reset transition exercised by unit tests.

## Grounding rules

- Recovery decisions may receive only observables computed by independent functions
  from retained simulator/history/memory/action bytes. Neither scenario ID, domain,
  intended sufficient level, injection type, nor scorer cause may enter the decision
  call or its upstream observable constructor.
- Every local retry/hold advances MuJoCo for a fixed 25 ticks, then recomputes all
  observables. A retry cannot be exhausted synchronously.
- Motion recovery must generate retained executable trajectory/action bytes, execute
  them, and recompute collision/path feasibility and motion postconditions. It may
  not set validity/feasibility flags directly.
- Semantic recovery must update memory from an independently emitted observation,
  select an authorized alternative using memory facts, generate retained executable
  motion bytes, execute, and recompute all postconditions. It may not set semantic,
  motion, or control flags directly.
- Recovery latency is measured from injection/detection tick through the first tick
  at which the independently recomputed postcondition remains satisfied for the
  frozen dwell window.
- Terminal success requires the correct currently authorized object, target dwell,
  collision-free execution, valid action age/content, and zero independent safety
  violations. Abort remains a valid nonworking outcome.

## Scenarios and genuine realization variation

The semantic meanings remain two anchors and six disturbances:

1. nominal anchor;
2. slow-policy anchor inside the valid action window;
3. control impulse/load;
4. one slow-command dropout;
5. target shift within the same admissible object region;
6. a new obstacle invalidating the current straight path while a collision-free
   waypoint route remains;
7. selected object unavailable with an authorized alternative;
8. restriction invalidating the selected affordance/region with an authorized
   alternative.

Each primary cell uses seeds `20261701..20261710`. Seed is consumed through a
canonical PCG64 stream keyed by the V2 namespace to vary, within preregistered safe
ranges:

- initial joint state ±0.04 rad around the safe nominal configuration;
- primary and alternate target x/y by ±0.035 m within their semantic regions;
- disturbance tick uniformly over the closed integer range 600..900;
- impulse magnitude 0.12..0.28 N·m and sign;
- dropout duration 20..55 ticks;
- target-shift displacement 0.035..0.070 m and direction;
- obstacle center/width within a frozen corridor that blocks the pre-injection
  straight segment while leaving one verified waypoint route;
- joint damping multiplier 0.90..1.10; and
- observation delivery delay 0..12 ticks for semantic updates.

The generator retains every sampled scalar and validates identical reachable domains
for all architectures before execution. A realization failing the architecture-
independent precheck is `NOT_RUN`; it is not resampled.

## Matrix

- Primary: 4 architectures × 8 scenarios × 10 genuine realizations = 320 frozen P6
  residual-0.5/slew-48 episodes.
- Sensitivity: R3 × 8 scenarios × seeds `20261701..20261705` = 40 repaired-P4
  one-tick/dq-on episodes.
- Total: 360 terminal episodes unless the whole frozen configuration is `NOT_RUN`.
- No selection, tuning, magnitude adaptation, or code/config change after the first V2
  outcome exists.

## Independent scorers and positive controls

The primary episode code cannot write authoritative safety or correctness counts.
A separate scorer consumes immutable trace/action/memory/semantic bytes after the
episode and measures:

- joint, torque, workspace, collision, and nonfinite violations;
- action age, shape, hash, and command-content validity;
- target/object/affordance/region authorization per tick;
- stale/contradictory memory decisions;
- semantic, motion, and control postconditions;
- retry-loop and budget-reset violations; and
- correct lowest-sufficient recovery level from independently derived failure
  evolution, not the scenario label.

Before the matrix, tests must feed deliberately unsafe, forbidden, stale,
collision, invalid-action, and loop-positive traces and prove every scorer emits a
nonzero failure. Primary outcomes start only after these positive controls pass.

## Measures and decision rule

The V1 measures remain, but all are recomputed from retained raw bytes. Paired rows
are the only authority for gates involving architecture differences. The effective
realization count is displayed beside every interval; templates are never expanded
by duplicated identities.

`SUPPORTS_GROUNDED_LAYER_MATCHED_HIERARCHY` requires:

1. independent unsafe/forbidden totals for R3 are no greater than every comparator;
2. paired R3 success strictly exceeds R0 across motion+semantic realizations;
3. paired R3 success is noninferior to R1 while semantic wakeups are lower;
4. on control disturbances R3 is noninferior in paired success, with fewer semantic
   wakeups than R1 and fewer motion replans than R2;
5. R3 assigns at least 80% of independently recoverable failures to the lowest
   sufficient level, has no loop/reset violation, and the positive-control audit is
   complete;
6. the paired R3-minus-best-comparator success difference is nonnegative separately
   in control, motion, and semantic domains; and
7. at least 8/10 realization identities in each disturbed scenario have nonidentical
   trace or sampled-parameter hashes, and every domain contains at least two distinct
   sampled physical realizations.

Paired realization/template bootstrap uses 10,000 deterministic draws, resampling
realizations within template and reporting both template-specific and template-
cluster sensitivity intervals. It is descriptive, not confirmatory.

## Evidence and figures

Each episode retains sampled realization parameters, precheck, full memory/event
ledger, semantic plans, motion path and executable action/trajectory bytes, 500 Hz
state/reference/action/torque/safety rows, every recomputed observable, recovery
decisions, independent scorer rows, and terminal disposition. Hidden injection cause
is stored separately and joined only after decisions and scoring.

Derived output includes exact paired rows, scorer confusion, positive-control audit,
bootstrap inputs/draws/results, working/nonworking/class-absent samples, canonical
graph tables, SVG/PNG figures, source/input/output hashes, and a dependency-free clean
reconstruction recipe. V1 and all failed V2 attempts remain separately inventoried.

## Interpretation

A passing V2 result supports only a narrow mechanistic claim for these sampled
MuJoCo realizations and fixed task. A failing result identifies whether grounded
failure attribution, actual recovery execution, safety, or realization robustness
breaks the hierarchy advantage. Cross-task evidence requires a later held-out cell or
standard environment; memory composition remains a separate later experiment.
