# Hierarchical Recovery Microexperiment Design

**Status:** architecture approved; written specification awaiting review  
**Date:** 2026-08-23  
**Classification:** engineering, nonconfirmatory, simulation-only

## Purpose

Test the Reflect-v1-style separation between three manipulation and reasoning
loops without building a general robot stack:

1. a fast control/execution loop that absorbs small continuous errors;
2. a motion/skill loop that refreshes or replans geometric execution; and
3. a semantic/task loop that replans when task meaning or preconditions change.

Memory is a separate shared plane, not a fourth recovery level. The first
experiment holds memory fixed so that differences are attributable to recovery
architecture. A later experiment may freeze the selected recovery architecture
and vary memory composition.

The primary question is:

> Does layer-matched recovery improve eventual task success and reduce unnecessary
> cross-layer intervention
> over local-only, semantic-only, and motion-first recovery while preserving safety
> and avoiding retry loops?

## Scope and non-goals

The experiment uses one small semantic manipulation cell connected to the existing
MuJoCo planar-arm execution path. It does not add ROS, MJPC, a database, a language
model, learned failure classification, a generalized orchestration framework, or a
new simulator.

The result is bounded to the frozen task, disturbances, recovery rules, and seeds.
It cannot establish physical-robot safety, general semantic planning, or a universal
three-level architecture.

## System under test

### Fixed memory plane

All recovery variants receive the same `T3_LIVE_BELIEF_V1` memory view:

- durable object identity, semantic label, affordance, and task restriction;
- last observed pose and availability;
- observation timestamp, confidence, and provenance;
- explicit stale/unknown dispositions; and
- an append-only evidence event ledger that is not itself planner authority.

Retry counters and in-flight controller state remain operational state rather than
durable semantic memory. No variant receives hidden disturbance cause or scorer
truth. A later memory experiment will vary this plane.

### Three recovery levels

| Level | Owns | May do | Must escalate when |
|---|---|---|---|
| Control/execution | current reference tracking, bounded transient error, safe hold | continue or make a bounded local retry | error persists, reference becomes invalid, or a safety/feasibility contract fails |
| Motion/skill | target geometry, trajectory/action validity, local feasibility | refresh the action, replan motion, or retrigger the same semantic skill | semantic target, affordance, or precondition is invalid |
| Semantic/task | goal meaning, object selection, restrictions, task preconditions | select another valid object/skill or declare the mission infeasible | no authorized feasible task plan exists |

Escalation is monotonic for one failure episode: control to motion to semantic to safe
abort. The frozen budgets are two control recoveries, two motion refresh/replans, and
one semantic replan. A successful command generation with a new command hash starts a
new episode; repeating the same command cannot reset a budget. This prevents unbounded
cross-level retry loops.

### Minimal integration seam

The semantic layer emits a typed skill request containing target identity,
affordance, admissible target region, restrictions, memory version, and success
predicate. The motion layer resolves that request into the existing Cartesian
target/constraint representation. The existing differential-IK/velocity-aware P4
and strong P6 controller code provide continuous execution; the experiment does not
retune either controller.

The adapter is experiment-local under `experiments/03_recovery`. It performs only
typed validation and coordinate conversion. It cannot query hidden truth or mutate
durable semantic facts.

## Recovery architectures

All four variants see identical observations and fixed memory bytes.

| ID | Architecture | Rule |
|---|---|---|
| R0 | `LOCAL_ONLY` | Every detected failure receives bounded control-level retries, then safe abort. |
| R1 | `SEMANTIC_ALWAYS` | Every detected failure immediately invokes semantic replanning. |
| R2 | `MOTION_THEN_SEMANTIC` | Every failure first refreshes/replans motion, then invokes semantics if motion cannot proceed. |
| R3 | `LAYER_MATCHED` | Observable contract state selects control continuation, motion refresh/replan, or semantic replan; escalation is monotonic and bounded. |

R3 uses transparent deterministic rules, not a learned classifier. The rules may
inspect tracking persistence, controller/safety state, action validity, geometric
feasibility, and semantic-precondition validity. They may not inspect injected cause.

## Task and disturbances

The fixed mission requests interaction with an object by semantic label and
affordance inside a small tabletop/building-cell abstraction. The semantic layer
selects an authorized object and interaction target; the motion layer reaches it;
the control loop executes the reference. The mission succeeds only if the correct
currently authorized object is reached within tolerance.

Each architecture runs the same two nominal anchors and six disturbances:

| Domain | Disturbance | Intended lowest sufficient response |
|---|---|---|
| Anchor | no disturbance | no recovery |
| Anchor | ordinary slow-policy delay within the valid action window | ordinary continuation |
| Control | bounded impulse/load | local continuation |
| Control | one slow-command dropout | safe local continuation/hold |
| Motion | target shifts within the same object's admissible region | motion refresh/replan |
| Motion | current path becomes locally infeasible while the skill remains valid | motion replan or retrigger |
| Semantic | selected object becomes unavailable or moves outside its valid semantic location | semantic replan |
| Semantic | a task restriction invalidates the selected affordance/region while one authorized alternative remains | semantic replan |

Disturbance magnitudes are frozen from already-safe Experiment 01 and Experiment 05
domains. Each disturbance event is injected at controller tick 750, after ordinary
motion has begun; anchor schedules contain no injected event. A single pre-outcome
feasibility check evaluates scenario geometry without
executing any recovery architecture. If one architecture would receive a different
reachable domain, the whole scenario configuration is `NOT_RUN`; magnitudes and event
times cannot adapt after architecture outcomes exist.

## Experimental matrix

- Four recovery architectures.
- Eight scenario domains: two anchors plus six disturbances.
- Eight fresh deterministic seeds per cell: `20261601` through `20261608` under the
  `exp03-hierarchy-v1` namespace.
- The 256-episode primary matrix uses the already-strong P6 residual-0.5/slew-48
  controller fixed before outcomes.
- A 32-episode representation-sensitivity slice runs R3 only with the repaired P4
  one-tick/dq-on controller across all eight domains and seeds `20261601` through
  `20261604`. It is not a controller-tuning grid and has no selection authority.
- Total: 288 episodes.
- Seed namespaces do not overlap prior engineering, formal-pilot, or memory/twin
  evidence.
- No parameter selection occurs from the primary matrix.

If the fixed controller fails the nominal feasibility precheck, the experiment is
`NOT_RUN`; it is not silently replaced. Every started episode receives a terminal
disposition.

## Measures and decision rule

Primary measures:

- eventual mission success;
- forbidden or unsafe action count;
- correct lowest-sufficient recovery level;
- recovery latency;
- semantic replans and unnecessary semantic wakeups;
- motion replans, action refreshes, and retriggers;
- bounded local recoveries;
- repeated-state/retry-loop detection; and
- stale or contradictory memory decisions.

Secondary continuous measures retain tracking error, saturation, clamp,
discontinuity, target error, action age, and safe-hold duration.

`SUPPORTS_LAYER_MATCHED_HIERARCHY` requires all of the following on the frozen
matrix:

1. R3 has no more unsafe/forbidden outcomes than every comparator;
2. R3 strictly improves eventual success over R0 in the combined motion+semantic
   disturbance domain;
3. R3 strictly reduces semantic wakeups versus R1 while not reducing eventual
   success;
4. on control disturbances, R3 uses fewer semantic wakeups than R1 and fewer motion
   replans than R2 without lower eventual success;
5. R3 assigns at least 80% of recoverable disturbances to the lowest sufficient
   level and has no unbounded retry loop; and
6. R3's paired eventual-success difference versus the best of R0, R1, and R2 is not
   negative in any of the control, motion, or semantic domains.

Paired architecture contrasts use complete seed-scenario pairs and deterministic
10,000-draw bootstrap intervals. Because this is an engineering screen, intervals
are descriptive and no deployment or confirmatory authority follows. Failure of any
gate produces `NOT_SUPPORTED` or `INCONCLUSIVE`, never adaptive threshold changes.

## Evidence and reconstruction

Each episode retains:

- scenario, seed, injected-event, config, source, and replay identities;
- semantic request and every semantic plan;
- memory snapshot/version before and after each observation update;
- motion target, feasibility decision, action/trajectory bytes, and replans;
- 500 Hz observation, reference, action, torque, safety, and metric-input rows;
- every recovery decision with observable inputs, selected level, reason, and budget;
- the hidden cause in a scorer-only record joined after the decision;
- terminal disposition and all metric components.

Derived evidence includes paired rows, bootstrap inputs/results, per-domain confusion
tables, aggregate metrics, and deterministic working/nonworking examples for every
architecture and disturbance domain. If a class is absent, the sample index records
`CLASS_NOT_OBSERVED` with its denominator.

Reconstruction starts from sealed raw evidence, replays semantic and recovery
decisions without scorer truth, replays the motion/controller episode, and reproduces
all derived files byte-for-byte. Invalid and aborted attempts remain separately
inventoried and cannot contribute to selection or analysis.

## Error handling and safety

- Missing, stale, contradictory, or unauthorized semantic facts fail closed.
- Nonfinite motion/controller state triggers safe hold and terminal invalid evidence.
- Resource exhaustion preserves a terminal disposition and completed raw members.
- A recovery budget cannot reset without a successful new command generation.
- Semantic replan cannot mutate durable geometry or erase contrary observations.
- No architecture may use the injected disturbance label as an input.

## Open-source reuse boundary

The immediate probe reuses the existing open-source MuJoCo runtime and the already
validated local P6 controller, with repaired P4 used only for the declared sensitivity
slice. It also keeps the experiment-local Cartesian skill representation, explicit
Python recovery state machine, and sealed JSON/JSONL/Parquet evidence path. Adding a
new robotics framework here would change the execution system at the same time as the
recovery architecture and would make the causal comparison harder to interpret.

No new runtime package is therefore required for the 288 primary/sensitivity episodes.
Open-source projects are introduced one layer at a time only in later replication:

- Gymnasium-Robotics Fetch tasks provide the first standard MuJoCo environment transfer;
- Mink may replace only the differential-IK component when a higher-DoF model requires it;
- py_trees may replace only the orchestration state machine after two tasks exhibit the
  same recovery structure; and
- DuckDB may index the append-only memory/event ledger for the unfixed-memory study,
  while immutable JSON/Parquet evidence remains authoritative.

MoveIt, ROS 2 control, BehaviorTree.CPP, MuJoCo MPC, Isaac/ManiSkill, and generalized
scene-graph frameworks remain reference implementations rather than immediate
dependencies. Their integration surface is larger than this probe and would introduce
middleware, controller, engine, or perception changes unrelated to the three recovery
levels being tested. Any later dependency is revision-pinned, license-checked, and
hidden behind the existing typed recovery interface.

## Parallel execution plan

After implementation is frozen, run three independent evidence shards in parallel:

1. anchors plus control disturbances;
2. motion disturbances; and
3. semantic disturbances.

The shards share only the frozen implementation/config and write disjoint episode
identities. Aggregation starts only after all shard manifests validate. A fourth
read-only agent independently reconstructs and audits the merged evidence.

## Later unfixed-memory experiment

After the recovery architecture is frozen, a separate fresh-seed experiment may
cross it with:

- stateless observation;
- semantic facts without live confidence;
- `T3_LIVE_BELIEF_V1`; and
- live belief plus bounded episodic failure history.

That experiment will ask whether memory quality changes correct escalation, repeated
work, stale decisions, and recovery success. It will not reuse the present outcome
domain as a holdout or retune the selected recovery rules. Keeping this as a second
stage prevents memory and recovery architecture from becoming an uninterpretable
factorial confound.

## Expected interpretation

A positive result would support the narrow claim that explicit control, motion, and
semantic recovery responsibilities compose usefully on this task with a fixed memory
plane. A negative result would identify whether the extra layer fails through poor
attribution, excess cross-layer intervention, or no success benefit. Either outcome is more
informative than adding another generalized framework or controller baseline.
