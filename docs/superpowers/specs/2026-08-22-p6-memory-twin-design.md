# P6 Memory and Semantic-Twin Experimental Design

**Date:** 2026-08-22

**Status:** Approved design; no implementation plan

**Scope:** Reflect Lite Experiments 04 and 05

## 1. Decision

P6 will use a frozen, pure-Python world-trace kernel shared by Experiments 04 and
05. Experiment 04 establishes the memory interface and freezes the smallest
useful composition. Experiment 05 consumes that frozen interface and evaluates
semantic-twin layers. Evidence collection is therefore serial, Exp04 then Exp05,
while implementation preparation that does not depend on Exp04's result may run
in parallel.

The initial benchmark uses standard-library data structures, `dataclasses`,
`heapq`, and the repository's existing NumPy and artifact support. It does not
introduce a database, scene graph, vector database, USD, IFC, Hydra,
ConceptGraphs, or an external LLM. Those are adapter candidates only after a
measured limitation justifies them.

This follows the program's requirement to start locally and minimally and not
install Hydra or ConceptGraphs before a hand-authored benchmark proves the
interface useful (`Reflect Lite Research Program.md:1596-1612`). It also follows
the autonomous-run dependency order: Experiment 04 precedes 05, and 05 starts
only after the 04 interface freezes
(`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:97-113`).

## 2. Alternatives and trade-offs

### A. Independent experiments, strictly serial

Exp04 and Exp05 would each define their own world, event model, scoring, and
artifacts. This gives the cleanest experimental isolation, but duplicates the
most error-prone fixture logic and makes cross-experiment disagreements hard to
attribute. It also encourages the twin experiment to reinterpret memory facts.

### B. One combined memory-and-twin framework

A single extensible framework would maximize reuse and allow both experiments to
run together. It is rejected because it couples two claims before either is
established, makes result-dependent interfaces difficult to freeze, and risks
building the database or scene-graph platform that the program explicitly defers.

### C. Frozen shared trace kernel, serial evidence — selected

Both experiments read identical immutable truth and observation traces through
small experiment-local projections. Exp04 alone decides the promoted memory
view. Exp05 is prepared against a narrow protocol but runs confirmation only
after that view is frozen. This preserves common causes and deterministic
comparisons without treating the experimental implementations as a platform.
The cost is a deliberate checkpoint between the experiments; that cost is useful
because it prevents Exp05 results from changing Exp04's interface after the fact.

## 3. Scientific boundaries

Experiment 04 tests task-relevant query and decision performance under stale,
occluded, and changing state. It cannot establish real perception quality,
building-scale mapping, or an optimal production database
(`Reflect Lite Research Program.md:1580-1594`). Experiment 05 tests the
representational value of geometry, topology, semantics, and live belief in a
small hand-authored building. It cannot establish raw-sensor mapping, industrial
BIM interoperability, photorealistic simulation value, or general language
grounding (`Reflect Lite Research Program.md:1743-1758`).

The benchmark is deterministic and rule-based. An LLM is not used in evidence-
bearing runs; this is stricter than the program's optional, environment-gated LLM
extension (`Reflect Lite Research Program.md:1860-1866`).

## 4. Shared frozen world-trace kernel

### 4.1 World

The canonical world contains five rooms, six doors, ten assets, two valves, two
tools, one charger, one restricted room, and one robot, matching the Exp04 fixture
contract (`Reflect Lite Research Program.md:1636-1645`). The same entities are
projected into the Exp05 building hierarchy: Lobby, CorridorA, PumpRoom,
ElectricalRoom, and RestrictedLab (`Reflect Lite Research Program.md:1801-1812`).
Every entity has one stable, opaque ID. Human-readable labels are not identities.

Relations use the closed vocabulary `IN`, `ON`, `NEAR`, `BLOCKS`, `CONNECTS`,
`HELD_BY`, `REACHABLE`, `RESTRICTED_BY`, and `OBSERVED_AT`, as specified by the
program (`Reflect Lite Research Program.md:1647-1659`). Geometry is bounded 2D
pose and extent data; topology is room/door connectivity and route cost;
semantics is identity, class, aliases, affordances, and restrictions; live belief
is timestamped operational state, confidence, provenance, visibility, and
uncertainty. These remain typed layers, never a single untyped mapping.

### 4.2 Hidden truth and observations

The kernel has two disjoint timelines:

- `TruthFrame` is authoritative simulator state. Only the generator and scorer
  can read it.
- `ObservationFrame` contains the facts delivered to an architecture at a given
  virtual time, including stable IDs where the observation resolves identity,
  confidence, provenance, and explicit unknowns.

Architectures, queries, and planners receive only observations and the records
they derived from earlier observations. Scoring joins their answers or actions to
hidden truth after execution. Test-only capability objects enforce this boundary;
no architecture callback receives a truth store or truth-derived relation.

The kernel uses a virtual monotonic nanosecond clock and named, independently
seeded random streams for layout, event choice, observation noise, query order,
and mission order. Adding draws to one stream cannot perturb another. A trace is
identified by schema version, generator version, seed, configuration hash, and
content hash. Pilot and confirmation seed sets are disjoint.

### 4.3 Deterministic event suite

Each trace includes all ten canonical event classes in a frozen balanced order:

1. an object moves while unobserved;
2. an object is temporarily occluded;
3. a door opens or closes;
4. a remembered pose crosses its freshness boundary;
5. a task attempt fails with a recorded reason;
6. two assets expose the same label;
7. a contradictory observation arrives;
8. a room becomes restricted;
9. an object is picked up or placed; and
10. an instruction refers to an earlier encounter.

The first nine come directly from the Exp04 event set and the tenth completes its
history-dependent case (`Reflect Lite Research Program.md:1661-1672`). Exp05
projects these into door, restriction, operational-state, blocker, topology,
battery, and instruction changes (`Reflect Lite Research Program.md:1819-1832`).
Every mutation has `event_id`, virtual time, affected IDs, precondition, truth
delta, observation policy, and expected query/mission consequences.

## 5. Experiment 04: memory decomposition

### 5.1 Architectures and controls

All variants receive byte-identical observation sequences, have the same allowed
fact budget, and answer through the same `MemoryView` protocol.

- **M0 — current observation only:** discards each prior frame when the next
  arrives.
- **M1 — recent-state buffer:** a bounded chronological deque of recent
  observations, robot state, actions, and controller events.
- **M2 — episodic log only:** append-only normalized events with entity IDs,
  outcomes, failures, interventions, and world changes.
- **M3 — semantic graph only:** current entity beliefs and typed adjacency,
  updated from observations, without event history.
- **M4 — graph plus episodes:** M3 and M2 queried together.
- **M5 — confidence-aware M4:** M4 plus explicit freshness, confidence,
  provenance, contradiction, and unknown-state policy.
- **M6 — retrieval-aided M5:** M5 plus deterministic hash-derived vectors attached
  to stable entity/event IDs. Vector results are candidates only and never truth.
- **H0 — flat equal-information history:** a chronological flat record containing
  every fact available to M5, with identical retention and fact budget but no
  typed graph or retrieval organization.
- **V0 — vector-only equal-input control:** deterministic embeddings over the same
  observed records available to M5, without an authoritative graph or episodic
  index. Returned snippets must be interpreted directly.

M0-M6 are the program's required ablations
(`Reflect Lite Research Program.md:1674-1684`). H0 satisfies the autonomous-run
equal-information control requirement
(`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:183-198`);
V0 makes the hypothesis's vector-only comparison explicit.

`MemoryView` exposes only `where(entity)`, `last_observed(entity)`,
`pose_usable(entity, now)`, `attempt_history(entity, action)`,
`changes_since(location, time)`, `conflicts(entity)`, and
`route_facts(destination)`. Results are sorted typed records with source IDs,
observation times, confidence, provenance, and explicit unknown reasons.

### 5.2 Query and decision suite

Every trace asks the ten program queries in a seed-derived but frozen order:
location, last observation, pose usability, prior attempt, last failure reason,
reachable valve under restriction, changes since the last Room 2 visit, route
blocker, duplicate-label identity, and conflicting observations/remaining
unknowns (`Reflect Lite Research Program.md:1686-1697`). Each query has a
machine-readable answer key against hidden truth and a decision form where
applicable: act, rescan, re-identify, choose an alternative, or report unknown.

### 5.3 Metrics

The primary metric is seed-level correct task-relevant answer/decision rate under
changed and stale state, exactly the program's primary outcome
(`Reflect Lite Research Program.md:1699-1703`). Secondary metrics are
stale-belief action rate, wrong-identity rate, repeated-observation requests,
failure-explanation accuracy, Brier score for confidence calibration, query
latency, stored bytes, and context facts supplied to the planner. Rates use fixed
denominators from the frozen trace manifest; abstention is incorrect unless the
answer key is explicitly unknown. Latency is descriptive and measured in a
separate serial run; it is not mixed with deterministic functional evidence.

### 5.4 Preregistered joint advance rule

The singular primary outcome and the program's multi-condition advance statement
are resolved by a hierarchical joint rule. First, the primary scientific claim
must pass: M4's paired correctness improvement over both M0 and V0 must exceed
the frozen minimum effect, using a two-contrast Bonferroni family. Only then is
promotion considered. Promotion requires all operational guardrails to pass:

1. M4 improves stale-action rate and wrong-identity rate over M0 by their frozen
   minimum effects;
2. M4 reduces repeated scans over M0 by its frozen minimum effect;
3. M4 remains within the frozen context-fact and stored-byte ceilings;
4. M4 is non-inferior to equal-information H0 on correctness, proving that any
   gain is not merely extra information;
5. M5 improves the frozen stale/wrong composite over M4 without violating the
   correctness, scan, context, or byte non-inferiority margins; and
6. all integrity, oracle-separation, determinism, and artifact checks pass.

Thus correctness remains the sole primary metric for the scientific claim, while
stale/wrong decisions, scans, and planner burden are mandatory promotion
guardrails. Passing only one side cannot advance. M6 is promoted only if it also
improves ambiguous-identity retrieval over both M5 and V0 within all budgets;
otherwise embeddings are removed from the runtime path, matching the program's
kill condition (`Reflect Lite Research Program.md:1719-1723`). The selected
composition is the simplest passing member; ties choose the lower numbered
architecture.

## 6. Experiment 05: semantic twin and building planner

### 6.1 Frozen input and ablations

Exp05 receives the frozen Exp04 `MemoryView`; it may not inspect or special-case
the winning implementation. Every twin receives the same truth-independent input
facts allowed by its layer definition.

- **T0 — geometry only:** metric poses, extents, collision data, and frames.
- **T1 — geometry plus topology:** T0 plus rooms, doors, connectivity,
  traversability, containment, and route costs.
- **T2 — topology plus semantics:** T1 plus identity, aliases, affordances,
  policies, restrictions, and task properties.
- **T3 — semantic twin plus live belief:** T2 plus operational state, confidence,
  timestamp, provenance, visibility, and uncertainty.
- **T4 — belief twin plus episodes:** T3 plus the frozen Exp04 episodic-history
  interface.
- **TM — monolithic same-facts control:** one untyped flat record containing
  exactly the facts visible to T4, with identical update times and context budget.

T0-T4 are the required program ablations
(`Reflect Lite Research Program.md:1834-1842`). TM satisfies the autonomous-run
same-facts control requirement. Fact-set manifests prove T4/TM equality before
each mission; ordering and representation may differ, facts may not.

### 6.2 Planner and mission suite

A deterministic rule planner issues typed queries, filters forbidden or
inapplicable goals, and uses `heapq` Dijkstra over currently available topology.
It receives compact query results, never the entire twin. Plans are sequences of
typed route and interaction steps with fact provenance and a precondition for
each step. A dynamic event invalidates affected preconditions and causes a bounded
replan.

The suite contains the five canonical missions:

1. inspect the nearest coolant valve without entering a restricted room;
2. reach Pump 2, recharging first if the battery estimate is insufficient;
3. inspect Valve 7 via an alternate route when Door 3 is unavailable;
4. place a carried tool at a safe location; and
5. replan when a room becomes restricted during execution.

These are fixed by the program (`Reflect Lite Research Program.md:1813-1817`). A
plan is invalid if it enters a forbidden region, traverses a closed/unavailable
edge, chooses an unsupported affordance, uses a stale pose beyond policy, assumes
insufficient energy, targets the wrong duplicate identity, or continues after a
precondition-changing event.

### 6.3 Metrics and gate

Metrics are mission success, invalid-plan rate, forbidden-region violations,
invalid-affordance choices, stale-belief failures, route cost, replan count and
latency, semantic and geometry query counts, and planner context size. Invalid-
plan rate is the primary metric because it directly resolves the stated advance
condition (`Reflect Lite Research Program.md:1882-1884`). Mission success is a
mandatory guardrail; forbidden-region violations are a hard safety failure.

T3 advances only when its paired invalid-plan reduction exceeds the frozen
minimum effect against each of T0, T1, and T2 in a three-contrast Bonferroni
family; mission success is non-inferior to the best of T0-T2; route cost, query
count, and context remain within frozen ceilings; and forbidden-region violations
are zero. T4 advances over T3 only if the history-dependent mission subset gains
the frozen minimum effect without violating those guards. T4 must also be
non-inferior to same-facts TM on invalid plans and mission success. The simplest
passing layer is selected. Any safety violation, oracle leak, unequal fact set,
or invalid artifact makes the result `INVALID`, not a failure that can be averaged
away.

## 7. Pilot, freeze, confirmation, and numeric parameters

The lifecycle has three strictly separated stages.

1. **Pilot:** generator bugs, ceiling feasibility, and metric distributions are
   measured on pilot-only seeds. Architecture semantics, query answers, and gate
   direction may not be tuned to favor a variant.
2. **Freeze:** one canonical configuration records every numeric value below,
   seed lists, trace hashes, schemas, architecture versions, metric formulas,
   bootstrap procedure, multiplicity families, missing-data rules, resource
   ceilings, and implementation SHA. Its digest becomes part of every artifact.
3. **Confirmation:** untouched seeds run once on the unchanged implementation.
   Mechanical validation and gate evaluation produce `ADVANCE`, `DO_NOT_ADVANCE`,
   or `INVALID`. Confirmation results never revise thresholds.

Paired seed-level contrasts use a deterministic 10,000-resample percentile
bootstrap. Each superiority or non-inferiority family uses Bonferroni-adjusted
95% simultaneous intervals, as required by the autonomous protocol
(`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:145-181`).
A superiority lower bound must be strictly greater than its frozen margin; a
non-inferiority lower bound must be at least the negative frozen margin. Exact
boundary equality fails superiority and passes non-inferiority.

The following evidence-dependent numeric values are mandatory freeze fields; none
is silently defaulted:

1. Exp04 correctness minimum improvement, in percentage points;
2. Exp04 stale-action minimum reduction, in percentage points;
3. Exp04 wrong-identity minimum reduction, in percentage points;
4. Exp04 repeated-scan minimum reduction, in scans per episode;
5. Exp04 M4-versus-H0 correctness non-inferiority margin;
6. Exp04 M5-versus-M4 correctness and scan non-inferiority margins;
7. Exp04 M5 stale/wrong composite minimum improvement and fixed component weights;
8. Exp04 M6 ambiguous-retrieval minimum improvement;
9. Exp04 per-query context-fact ceiling and per-episode byte ceiling;
10. Exp04 recent-buffer duration, freshness time-to-live by fact class,
    confidence acceptance threshold, contradiction threshold, and maximum retained
    events;
11. M6 hash-vector dimension and retrieval candidate count;
12. Exp05 invalid-plan minimum reduction for T3 and for T4;
13. Exp05 mission-success non-inferiority margin;
14. Exp05 route-cost, semantic-query, geometry-query, context-fact, and replan
    ceilings;
15. Exp05 battery reserve, route-unavailable cost, and maximum replans;
16. bootstrap random seed, confirmation seed count, per-seed episode count, and
    timeout/resource ceilings.

Pilot chooses these values through a recorded mechanical procedure: resource
ceilings are the smallest engineering budgets that permit the reference control
to complete all pilot cases plus a fixed recorded headroom ratio; meaningful-
effect and non-inferiority margins are selected from task-unit resolution and
pilot control variability, rounded outward to the next representable task unit;
TTL, confidence, retrieval, energy, and replan parameters are chosen only from a
finite candidate grid declared before pilot execution. The freeze artifact stores
the candidate grids, observations, selection trace, selected numbers, and
rationale. Because these quantities depend on empirical timing, memory size,
noise, and control variability not yet measured in this repository, inventing
numbers in this design would be false precision. The selection algorithm and the
requirement to freeze exact values before confirmation are fully specified.

## 8. Artifact and data contracts

Each run directory is immutable after finalization and contains:

```text
metadata.json
config.json
metrics.json
events.jsonl
observations.parquet
actions.parquet
memory_snapshots.jsonl
summary.md
manifest.json
```

Exp05 additionally writes `plans.parquet`, `route_candidates.parquet`, and
`twin_snapshots.jsonl`. This extends the program's common artifact contract rather
than replacing it (`Reflect Lite Research Program.md:2904-2969`).

- `metadata.json`: experiment, variant, run/trace IDs, implementation SHA,
  platform, dependency versions, virtual-clock origin, generator/config/source
  hashes, pilot-or-confirmation label, and clean-tree evidence.
- `config.json`: exact frozen parameters, seeds, architecture version, allowed
  fact budget, query/mission manifest hashes, and safety/resource ceilings.
- `metrics.json`: exact numerator, denominator, unit, aggregation level, missing
  count, per-seed values, contrasts, intervals, multiplicity family, and gate
  result for every metric.
- `events.jsonl`: ordered world-observation-memory-plan event envelopes using the
  shared execution-event vocabulary where applicable. The existing event system
  already defines memory updates and semantic replans and enforces monotonic event
  order (`reflect/events.py:18-35`, `reflect/events.py:143-158`).
- `observations.parquet`: one row per delivered entity observation, including
  source/receive times, stable ID or unresolved token, pose/state confidence,
  provenance, visibility, and contradiction group.
- `actions.parquet`: query answers, decisions, scans, route steps, and outcomes,
  with supporting fact/event IDs.
- `memory_snapshots.jsonl`: canonical architecture-visible state after each
  mutation, never hidden truth.
- `plans.parquet`: mission plan steps, preconditions, fact provenance, cost, and
  invalidation reason.
- `route_candidates.parquet`: candidate paths, excluded edges/regions, costs, and
  selection result.
- `twin_snapshots.jsonl`: separately keyed geometry, topology, semantics, and live
  belief views.
- `manifest.json`: relative path, media type, byte count, and SHA-256 for every
  artifact; it is written last by atomic rename after all validation.

JSON is canonical UTF-8 with sorted keys and no NaN/Infinity. JSONL has one
canonical object per newline. Parquet schemas, column order, nullability, and sort
keys are versioned and frozen. `ObjectBelief` supplies stable entity identity,
confidence, timestamps, and provenance (`reflect/types.py:231-249`), while
`SceneRelation` supplies typed edges with confidence and observation time
(`reflect/types.py:329-343`); experiment-local records adapt these contracts
without weakening them.

## 9. Verification design

Tests are deterministic, offline, and divided into contract, generator,
architecture, planner, scoring, artifact, and command layers.

- Golden trace tests assert byte-identical output for the same config and seed.
- RNG-independence tests add draws to one named stream and prove other streams and
  trace identities do not change.
- Oracle-boundary tests use hostile architecture callbacks and prove hidden truth
  is unreachable; all scores are computed after outputs are sealed.
- World invariants cover stable unique IDs, valid relation endpoints, symmetric
  door connectivity, legal containment, monotonic time, and mutation
  preconditions.
- Event tests cover every canonical event and non-overlapping chronology.
- Query golden tests cover all ten queries, explicit unknowns, stale poses,
  conflicting evidence, duplicate labels, prior failures, and restricted routes.
- M0-M6/H0/V0 tests prove retention semantics, M5 freshness/confidence behavior,
  equal delivered observations, H0/M5 fact-set equality, V0 non-authority, and M6
  kill-gate behavior.
- Mission golden tests cover all five missions and every invalid-plan reason.
- T0-T4/TM tests prove layer visibility, T4/TM fact-set equality, zero implicit
  semantics in lower layers, Dijkstra tie ordering, bounded replanning, and safety
  rejection before motion.
- Metric tests cover denominators, abstention, composites, Brier score, pairing,
  bootstrap determinism, multiplicity, exact threshold boundaries, and all three
  decision states.
- Artifact tests validate exact schemas, canonical serialization, hashes,
  cross-file IDs, finalization order, corruption rejection, and replay without the
  simulator.
- CLI tests cover deterministic pilot/freeze/confirmation modes, forbidden
  network/LLM state, dirty implementation state, config mismatch, resource
  exhaustion, and refusal to overwrite a finalized run.
- Small property loops enumerate seeds, event permutations, stale boundaries,
  confidence boundaries, route ties, and fact-budget limits without adding a new
  property-testing dependency.

## 10. Dependency seams and promotion boundaries

The first implementation remains pure Python plus current repository dependencies:
NumPy for numeric records, PyArrow for required Parquet artifacts, and PyYAML only
for configuration (`pyproject.toml:5-14`). Topology uses a typed adjacency mapping
and `heapq`; events and snapshots are append-only files/in-memory tuples.

Experiment-local protocols isolate future substitutions:

- `EventStore.append/scan`
- `RelationStore.upsert/neighbors`
- `RetrievalIndex.add/search`
- `RoutePlanner.shortest_path`
- `TwinExporter.export`

SQLite/DuckDB is considered only if measured retained-event size or query latency
exceeds the frozen ceiling. NetworkX is considered only if graph algorithm
complexity expands beyond the frozen Dijkstra/neighbor operations. A vector
library is considered only if M6 passes and the deterministic index cannot meet
its frozen budget. USD/IFC/Spark-DSG adapters are considered only after Exp05
passes and export/interchange becomes a separately stated claim. No adapter may
change evidence-bearing semantics.

Only stable, experimentally validated contracts may move into `reflect/`; world
generators, policies, memory implementations, planners, scoring thresholds, and
fixtures stay under experiment-local modules, matching the program's promotion
boundary (`Reflect Lite Research Program.md:348`). Promotion requires a passing
confirmation artifact, frozen protocol and hashes, full tests, explicit interface
diff, and a decision record. Exp04 may promote only the useful `MemoryView` types
and semantics. Exp05 may promote only the layer/query contracts justified by its
gate. Rejected variants and optional adapters remain research artifacts.

## 11. Parallel-safe decomposition

Preparation may proceed in five ownership-isolated workstreams:

1. **Fixture and protocol owner:** shared truth/observation records, named RNG,
   trace generator, event templates, schemas, and golden fixtures.
2. **Exp04 memory owner:** M0-M6, H0, V0, and `MemoryView`, consuming only frozen
   observations.
3. **Exp04 evaluation owner:** queries, answer keys, metrics, bootstrap, and gate,
   with no access from architecture code to the scorer.
4. **Exp05 preparation owner:** T0-T4/TM projections, deterministic planner,
   missions, and metric implementation against a stub `MemoryView` conformance
   fixture. This owner may not run evidence or select the actual Exp04 view early.
5. **Artifact and verification owner:** CLI modes, canonical writers, replay,
   manifests, resource/safety checks, and cross-experiment conformance tests.

The fixture schema, observation contract, virtual clock, and stub `MemoryView`
conformance cases freeze before parallel preparation begins. Exp04 pilot, freeze,
confirmation, and promotion are serial. Exp05 then replaces its stub with the
promoted conforming view, reruns all tests, freezes its own protocol, and performs
pilot and confirmation serially. Neither experiment reuses pilot seeds for
confirmation, and Exp05 evidence never feeds back into the Exp04 decision.

## 12. Decision outputs

Exp04 produces `MEMORY_ARCHITECTURE_DECISION.md`, assigning every retained fact to
`FAST_STATE`, `EPISODIC_LOG`, `SEMANTIC_GRAPH`, `GEOMETRIC_STATE`,
`EMBEDDING_INDEX`, or `LEARNED_LATENT`, as required by the program
(`Reflect Lite Research Program.md:1710-1717`). Exp05 produces
`TWIN_ARCHITECTURE_DECISION.md`, stating authority and mutation rules for BIM/IFC,
geometric export, runtime graph, and live belief
(`Reflect Lite Research Program.md:1868-1879`). Each decision links its immutable
confirmation manifest, reports every gate component, and records rejected layers
and adapters so a failed gate cannot be reframed as promotion.
