# P6 Memory and Semantic-Twin Experimental Design

**Date:** 2026-08-22

**Status:** Approved design; no implementation plan

**Scope:** Reflect Lite Experiments 04 and 05

## 1. Decision and claim boundary

P6 uses a frozen pure-Python world-trace kernel shared by Experiments 04 and 05.
Experiment 04 establishes a minimal memory interface; Experiment 05 consumes that
frozen interface to test semantic-twin layers. Evidence is serial, Exp04 then
Exp05. Contract and fixture preparation may proceed in parallel, but Exp05 may not
select or inspect the winning Exp04 implementation before Exp04 promotion.

The benchmark uses standard-library data structures, `dataclasses`, `heapq`, and
the repository's current NumPy/PyArrow artifact stack. It does not introduce a
database, scene-graph framework, vector database, USD, IFC, Hydra, ConceptGraphs,
or an LLM. The program explicitly requires a local hand-authored benchmark before
Hydra or ConceptGraphs (`Reflect Lite Research Program.md:1596-1612`).

Exp04 can establish task-relevant memory query and decision performance under
stale, occluded, and changing state, not real perception, building-scale mapping,
or a production database (`Reflect Lite Research Program.md:1580-1594`). Exp05 can
establish the representational value of typed twin layers in one small building,
not raw-sensor mapping, industrial BIM interoperability, photorealistic simulation,
or general language grounding (`Reflect Lite Research Program.md:1743-1758`).

## 2. Alternatives and trade-offs

### A. Independent strictly serial experiments

Each experiment could define its own world, event model, scorer, and artifacts.
This maximizes isolation but duplicates the most error-prone fixture logic and
makes cross-experiment disagreements hard to attribute.

### B. One combined memory/twin framework

A single extensible framework would maximize reuse. It is rejected because it
couples two claims before either is established, permits Exp05 outcomes to reshape
Exp04's interface, and encourages premature database/scene-graph scaffolding.

### C. Frozen trace kernel with isolated runners — selected

The generator creates physically separate truth and observation traces from one
scenario definition. Every variant runs in a fresh process-like boundary over a
freshly decoded observation trace. Exp04 freezes the smallest passing memory view;
Exp05 then consumes only its promoted protocol. This preserves common causes and
equal information while keeping hidden truth out of evaluated code. Its deliberate
serial promotion checkpoint follows the autonomous lane order
(`docs/superpowers/specs/2026-08-22-reflect-lite-autonomous-run-design.md:97-113`).

## 3. World, IDs, relations, and time

### 3.1 Canonical world

The world contains five rooms, six doors, ten assets, two valves, two tools, one
charger, one restricted room, and one robot, matching Exp04
(`Reflect Lite Research Program.md:1636-1645`). The Exp05 projection uses Lobby,
CorridorA, PumpRoom, ElectricalRoom, and RestrictedLab
(`Reflect Lite Research Program.md:1801-1812`).

Stable IDs are opaque canonical strings: `room/0001`, `door/0001`, `asset/0001`,
`robot/0001`, `event/00000001`, and `observation/00000001`. Labels and aliases are
facts, never identities. IDs are assigned by sorted generator role before any
variant runs; a variant cannot mint a world-entity ID.

### 3.2 Frozen relation vocabulary

The only world-relation predicates are:

```text
IN
ON
NEAR
BLOCKS
CONNECTS
HELD_BY
REACHABLE
RESTRICTED_BY
OBSERVED_AT
```

This is the program's complete vocabulary
(`Reflect Lite Research Program.md:1647-1659`). Direction, inverse semantics,
allowed subject/object kinds, symmetry, and cardinality are frozen per predicate.
Unknown predicates fail trace validation rather than becoming strings in an
untyped graph.

### 3.3 Virtual time and total order

A virtual monotonic nanosecond clock is the only decision time. Each record has
`monotonic_time_ns`, `source_sequence`, and stable `event_id`. Coincident records
use this total order:

1. truth mutation;
2. observation delivery;
3. memory update;
4. query or mission request;
5. query response;
6. decision or plan publication;
7. action issuance;
8. action execution;
9. simulator truth outcome; and
10. scorer publication.

Within one rank, `source_sequence` then `event_id` orders records. Time may remain
equal but never regress. Architecture-visible events use the existing shared
`ExecutionEventType` when applicable; P6's `event_subtype` is a validated payload
field and never expands the shared enum implicitly.

The canonical mapping is exact:

| Rank | P6 record | Shared event mapping | Required payload |
|---:|---|---|---|
| 1 | truth mutation | scorer-private truth event only | `event_subtype`, `truth_event_id` |
| 2 | observation delivery | `OBSERVATION_RECEIVED` | `observation_id`, `event_subtype` |
| 3 | compiled memory mutation | `MEMORY_UPDATED` | `mutation_id`, `event_subtype=MEMORY_STATE_UPDATED` |
| 4 | query/mission request | P6 query/mission sidecar only | `event_subtype=QUERY_REQUESTED` or `MISSION_REQUESTED` |
| 5 | query response | P6 query sidecar only | `event_subtype=QUERY_RESPONDED` |
| 6 | decision/initial plan | P6 decision/plan sidecar only | `event_subtype=DECISION_PUBLISHED` or `PLAN_PUBLISHED` |
| 6 | replacement plan | `SEMANTIC_REPLAN` plus plan sidecar | `event_subtype=PLAN_REPLACED`, `plan_id`, canonical `mission_state` object |
| 7 | issued physical chunk, if any | `POLICY_RESPONDED` | canonical `source_chunk_id`, `event_subtype=ACTION_ISSUED` |
| 8 | executed physical chunk, if any | `ACTION_EXECUTED` | canonical `source_chunk_id`, `event_subtype=PHYSICAL_ACTION_EXECUTED` |
| 9 | simulator truth outcome | scorer-private truth event only | `event_subtype=SIMULATOR_OUTCOME_RECORDED`, `truth_event_id` |
| 10 | scorer publication | sealed scorer artifact only | `event_subtype=OUTCOME_SCORED`, `score_record_id` |

P6 never uses `POLICY_RESPONDED` for a query; it appears only when a stored canonical
`ActionChunk` is actually issued, because the current rollout validator binds those
records. Issuance does not prove execution, execution does not contain simulator truth,
and neither substitutes for scorer publication. `SEMANTIC_REPLAN.mission_state` is the
canonical structured mission-state object required by the shared validator, not an ID,
string summary, or P6-local substitute. Every P6-emitted shared event includes
`event_subtype` in addition to the canonical fields required by its shared type.

The frozen local subtype vocabulary is:

```text
OBJECT_MOVED_UNOBSERVED
OBJECT_OCCLUDED
DOOR_STATE_CHANGED
POSE_BECAME_STALE
TASK_ATTEMPT_FAILED
DUPLICATE_LABEL_OBSERVED
CONTRADICTORY_OBSERVATION
ROOM_RESTRICTION_CHANGED
OBJECT_PICKED_OR_PLACED
EARLIER_ENCOUNTER_REFERENCED
ASSET_OPERATIONAL_STATE_CHANGED
ROUTE_BLOCKED
TOPOLOGY_EDGE_CHANGED
BATTERY_ESTIMATE_CHANGED
INSTRUCTION_CHANGED
MEMORY_STATE_UPDATED
QUERY_REQUESTED
MISSION_REQUESTED
QUERY_RESPONDED
DECISION_PUBLISHED
PLAN_PUBLISHED
PLAN_REPLACED
ACTION_ISSUED
PHYSICAL_ACTION_EXECUTED
SIMULATOR_OUTCOME_RECORDED
OUTCOME_SCORED
```

The first ten cover Exp04's event suite
(`Reflect Lite Research Program.md:1661-1672`); the next five cover additional Exp05
dynamics (`Reflect Lite Research Program.md:1819-1832`); the remaining closed values
are frozen runner/truth/scorer lifecycle subtypes used by the mapping table.

Subtype storage and shared-event waivers are exact. `queries.parquet` has
`request_event_subtype=QUERY_REQUESTED` and
`response_event_subtype=QUERY_RESPONDED`; `decisions.parquet` has
`publication_event_subtype=DECISION_PUBLISHED`; `plans.parquet` has
`publication_event_subtype=PLAN_PUBLISHED | PLAN_REPLACED`. These four local
request/response/publication subtypes are explicitly waived from a shared event because
no compatible shared enum exists. `MEMORY_STATE_UPDATED`, `PLAN_REPLACED`,
`ACTION_ISSUED`, and `PHYSICAL_ACTION_EXECUTED` require their mapped shared event and
may not use the waiver. Generator-only world subtypes appear only in the observation
or private truth trace as declared by the observation policy.
`SIMULATOR_OUTCOME_RECORDED` is truth-only and `OUTCOME_SCORED` scorer-only; both are
forbidden from runner rollouts and sidecars. Any other subtype/location combination,
missing required shared event, or extra shared event is invalid.

## 4. Physical and API oracle separation

### 4.1 Separate immutable traces

The generator writes two sibling artifacts through separate descriptors:

- `truth/trace.jsonl` contains authoritative state transitions and outcome fields.
- `observations/trace.jsonl` contains only delivered observations, confidence,
  provenance, visibility, contradictions, and explicit unknowns.

`TruthTrace` and `ObservationTrace` have distinct schemas, loader modules, and
capability types. `TruthTrace` cannot be converted to `ObservationTrace` by a cast;
the generator alone applies the frozen observation policy. The observation artifact
contains no truth path, truth hash, hidden entity pose, injection identity, future
outcome, or oracle cause label. The public scenario identity is a random run ID that
cannot be joined to a truth filename by a runner.

Truth files reside outside every variant working directory. A variant invocation
receives only an already-open observation descriptor or copied observation bytes,
the protocol, and its output directory. Its environment and arguments contain no
truth location. Hostile-runner tests enumerate descriptors, arguments, environment,
imports, and working-directory files and prove truth is unreachable.

### 4.2 Fresh immutable execution

Every `(experiment, variant, seed)` starts from the canonical observation bytes,
verifies their manifest hash, freshly deserializes them into immutable records, and
runs a fresh fact compiler and architecture instance. No decoded object, compiler
cache, memory state, planner state, or output buffer is shared between variants.
After execution, the runner canonicalizes, hashes, fsyncs, and atomically seals its
output. The scorer refuses a writable, incomplete, or hash-mismatched output.

Canonical `Observation` objects are an artifact-ingestion format only. Immediately
after each observation is validated, the boundary compiler copies its values into a
tuple of experiment-local frozen `FactRecord`s, recursively converts JSON lists to
tuples and mappings to new read-only mapping proxies, and releases all callback-
reachable references to the `Observation`. Numeric callback values use tuples of
Python `int`/`float` by default. A vectorized `FactBatch` may instead expose a
C-contiguous NumPy view created with `numpy.frombuffer(immutable_bytes, dtype=...)`:
its base is immutable `bytes`, `OWNDATA` is false, and `WRITEABLE` is false, so both
element assignment and `setflags(write=True)` fail. An owning array whose write flag
could be re-enabled is forbidden, even if initially read-only. Architecture, query,
and planner callbacks accept only frozen `FactRecord` tuples or those immutable-bytes-
backed `FactBatch` views. They never receive an `Observation`, mutable payload, loader,
descriptor, or artifact path. Callback-returned references are retained by a hostile
test harness and attacked again after later callbacks and after variant completion;
the canonical fact bytes and the next fresh variant must remain unchanged.

Only after sealing does the orchestrator launch scorers with separate read-only
descriptors for sealed output, observation trace, and—where allowed—truth trace.
Evaluated architecture code is not imported into the scorer process.

### 4.3 Two distinct oracles

The **epistemic answer oracle** reads only the observation prefix available at the
query time. It determines the answer a correct reasoner can justify: a known fact,
last-known stale fact, contradiction, or explicit unknown. It scores location,
identity, history, explanation, conflict, and confidence answers. An unseen move
does not make the hidden new location a knowable query answer.

The **outcome/safety oracle** reads `TruthTrace` only after outputs are sealed. It
scores whether a proposed act, route, or plan would use the wrong identity, stale
pose, forbidden room, unavailable edge, insufficient energy, invalid affordance,
or changed precondition. It never supplies an answer or feature to a runner.

This separation prevents epistemic correctness from being conflated with lucky
hidden-truth guesses and prevents safety scoring from leaking authoritative state.

## 5. Canonical observation-to-fact compiler

### 5.1 Fact schema and identity

One frozen pure compiler converts an ordered `ObservationTrace` prefix to ordered
`FactRecord`s. Every variant uses the same compiler version. A fact contains:

```text
fact_id
fact_kind
subject_id
predicate
object_id_or_canonical_value
source_event_id
observed_at_ns
received_at_ns
valid_from_ns
expires_at_ns
confidence
provenance
status = asserted | contradicted | unknown
```

`fact_kind` and `predicate` form one closed tagged union. Relation names never share
the attribute/scalar/event namespace:

| `fact_kind` | Closed `FactPredicate` members | Subject type | Object/value type | Base TTL |
|---|---|---|---|---|
| `RELATION` | `IN`, `ON`, `NEAR`, `BLOCKS`, `CONNECTS`, `HELD_BY`, `REACHABLE`, `RESTRICTED_BY`, `OBSERVED_AT` | stable entity ID allowed by the relation table below | stable entity ID allowed by the relation table | predicate-specific below |
| `ATTRIBUTE` | `LABEL`, `ALIAS`, `ENTITY_CLASS`, `AFFORDANCE`, `VISIBILITY`, `DOOR_STATE`, `OPERATIONAL_STATE` | stable entity ID | the exact enum/string type below | predicate-specific below |
| `SCALAR` | `POSE`, `BATTERY_LEVEL` | stable entity ID | the exact numeric tuple/scalar below | predicate-specific below |
| `EVENT` | `ATTEMPT_OUTCOME` | robot or acted-on entity ID | exact `AttemptOutcomeValue` tuple below | immutable |

There is no generic string predicate or generic event fact. The nine relation
predicates use these exact subject/object domains: `IN(entity, room-or-container)`,
`ON(asset-or-tool, asset-or-room-support)`, `NEAR(physical-entity,
physical-entity)`, `BLOCKS(door-or-asset-or-obstacle, door-or-room-or-edge)`,
`CONNECTS(door-or-edge, room)`, `HELD_BY(asset-or-tool, robot)`,
`REACHABLE(robot, physical-entity-or-room)`, `RESTRICTED_BY(room-or-door,
restriction-policy)`, and `OBSERVED_AT(physical-entity, room-or-anchor)`. Self-relations
are forbidden except `NEAR`; symmetric `NEAR` is stored once with the smaller entity
ID first. `CONNECTS` stores one fact for each endpoint room. All other relations are
directed. Entity kinds are the closed enum `ROOM | DOOR | ASSET | VALVE | TOOL |
CHARGER | ROBOT | OBSTACLE | TOPOLOGY_EDGE | RESTRICTION_POLICY | ANCHOR`.

Attribute/scalar/event values are exact:

- `LABEL` and `ALIAS` are nonempty NFKC strings; `LABEL` preserves display case and
  `ALIAS` stores its casefolded lookup form. Both are immutable identity facts.
- `ENTITY_CLASS` is one `EntityKind`; `AFFORDANCE` is one of `NAVIGABLE | OPENABLE |
  CLOSEABLE | OPERABLE | PICKABLE | PLACEABLE | CHARGEABLE`. Both are immutable.
- `POSE` is a seven-float tuple `(x_m, y_m, z_m, qw, qx, qy, qz)` with finite values
  and a unit quaternion under the frozen tolerance. Its TTL is two event intervals.
- `VISIBILITY` is `VISIBLE | OCCLUDED | NOT_OBSERVED`, with two-interval TTL.
- `DOOR_STATE` is `OPEN | CLOSED | BLOCKED | UNKNOWN`, with one-interval TTL.
- `BATTERY_LEVEL` is a finite float in `[0,1]`, with one-interval TTL.
- `OPERATIONAL_STATE` is `OPERATIONAL | DEGRADED | FAILED | UNKNOWN`, with
  one-interval TTL.
- `ATTEMPT_OUTCOME` is the frozen tuple `(action: ActionEnum, target_id: EntityId,
  outcome: SUCCEEDED | FAILED | ABORTED, reason: AttemptReason, attempt_id: EventId)`;
  it is immutable. `ActionEnum` is `NAVIGATE | INSPECT | OPEN_DOOR | CLOSE_DOOR |
  OPERATE | PICK | PLACE | RECHARGE | RESCAN | REIDENTIFY | HOLD`; every attempt uses
  the stable entity most directly acted on as its non-null target. `AttemptReason` is
  `NONE | STALE_POSE | WRONG_IDENTITY |
  UNREACHABLE | RESTRICTED | BLOCKED | INSUFFICIENT_BATTERY | NOT_OPERATIONAL |
  AFFORDANCE_MISMATCH | CONTROLLER_FAILURE`.

Relation TTLs are two intervals for `IN`, `ON`, `NEAR`, `HELD_BY`, and `OBSERVED_AT`;
one interval for `BLOCKS`, `CONNECTS`, `REACHABLE`, and `RESTRICTED_BY`. Thus labels,
aliases, classes, affordances, and attempt outcomes are immutable; pose, visibility,
door, battery, operational, and all nine relation predicates have exactly the finite
TTLs stated here. `status=unknown` retains the predicate's tagged value type by using
the one canonical `null` sentinel; no untyped substitute is permitted.

`fact_id` is lowercase SHA-256 of canonical JSON over all fields except `fact_id`.
Canonical values use sorted UTF-8 JSON with no NaN/Infinity and normalized strings.
Fact byte size is the length of that canonical UTF-8 record including its terminating
newline. Time validity is half-open `[valid_from_ns, expires_at_ns)`; immutable facts
are never rewritten. A correction creates a new fact linked by provenance.

`valid_from_ns` equals delivery time. `expires_at_ns` equals delivery time plus the
frozen predicate-specific TTL, or the maximum signed 64-bit value for immutable
identity/class facts. At exact expiry the fact is stale. Contradictory facts coexist;
confidence/staleness policy may resolve or abstain but cannot delete history.

### 5.2 Budgets, retention, and context

The compiler produces a canonical candidate stream before architecture-specific
organization. For equal-information controls, the frozen retention filter sorts
eligible facts by `(received_at_ns descending, fact_id ascending)`, admits records
until both the fact-count and canonical-input-byte budgets would be exceeded, and
then restores admitted facts to chronological order. A fact that individually
exceeds the byte budget is infeasible and makes the configuration invalid.

Storage bytes measure each architecture's actual canonical snapshot and index files;
they are not forced equal. Planner context is separately bounded by exact fact count
and canonical result-byte length. A query result that would exceed either budget is
deterministically truncated by `(relevance descending, received_at_ns descending,
fact_id ascending)` and records the omitted count.

### 5.3 Stepwise equality proofs

After every observation event and before every query or mission:

- H0 and M5 receive identical retained `FactRecord` IDs, bytes, arrival times,
  expiry times, confidence, and provenance. Only organization differs.
- V0 receives the identical retained fact inputs as M5. It may expose only retrieved
  snippets and has no typed/graph authority.
- T4 and TM receive identical retained facts, update times, expiry decisions, and
  context budgets. Only typed layering versus one flat record differs.

The runner emits a stepwise fact-set hash and canonical byte count. Equality means
exact ordered ID and byte equality, not set cardinality or semantic approximation.
A mismatch invalidates the paired seed before scientific aggregation.

## 6. Experiment 04 memory architectures

All variants receive freshly decoded byte-identical observation traces and answer
through the same typed `MemoryView`:

```text
where(entity)
last_observed(entity)
pose_usable(entity, now)
attempt_history(entity, action)
changes_since(location, time)
conflicts(entity)
route_facts(destination)
```

Results are sorted typed records with fact/source IDs, observation/receipt time,
confidence, provenance, staleness, omitted count, and explicit unknown reason.

- **M0 — current observation only:** retains only facts from the latest delivered
  frame.
- **M1 — recent-state buffer:** retains the canonical bounded recent window of
  observations, robot state, actions, and controller events.
- **M2 — episodic log only:** append-only normalized attempt, outcome, failure,
  intervention, and change facts.
- **M3 — semantic graph only:** latest entity beliefs and typed relations without
  event history.
- **M4 — graph plus episodes:** M3 and M2 over the same compiler output.
- **M5 — confidence-aware M4:** M4 plus frozen freshness, confidence,
  contradiction, provenance, and explicit-unknown policy.
- **M6 — retrieval-aided M5:** M5 plus the frozen hashed retrieval aid below.
- **H0 — flat equal-information history:** every retained M5 input in one sorted
  flat log with identical input/context budgets and no graph/index organization.
- **V0 — vector-only equal-input control:** every retained M5 input in the hashed
  index, with retrieval snippets as its only answer source and no authoritative
  typed lookup.

M0-M6 are the required ablations (`Reflect Lite Research Program.md:1674-1684`).
H0 is the autonomous equal-information baseline and V0 makes the program's
vector-only comparison explicit.

### 6.1 Feasible M6 retrieval

M5's non-vector retrieval is the strong baseline: exact stable-ID lookup, exact
predicate filter, normalized alias lookup, and a deterministic lexical inverted
index.

One fact is one retrieval document. Its field sequence is exactly `subject_id`,
`predicate`, canonical JSON `object_id_or_canonical_value`, then sorted provenance.
Each field is prefixed with the literal marker `subject`, `predicate`, `object`, or
`provenance`. Tokenization applies Unicode NFKC then `casefold`, replaces each maximal
run of non-alphanumeric code points with one space, splits on spaces, removes empty
tokens, and retains repetitions. Adjacent unigrams within a field add a bigram token
joined by one underscore; bigrams never cross fields. There is no stemming, stop-word
removal, or synonym expansion.

A query document starts with the exact lowercase query-ID token below. Argument fields
then sort by field name and emit the field-name marker followed by the canonical JSON
value through the same tokenizer. Finally, each expansion predicate is appended as
two tokens, literal `predicate` then its lowercase enum name, in the listed order.
These are all measured Exp04 query IDs; no query name is inferred or aliased:

| Query ID / name token | Exact argument fields | Ordered predicate expansion |
|---|---|---|
| `LOCATION` / `location` | `entity_id` | `IN, ON, NEAR, HELD_BY, OBSERVED_AT` |
| `LAST_OBSERVED` / `last_observed` | `entity_id` | `OBSERVED_AT, POSE, VISIBILITY` |
| `POSE_USABLE` / `pose_usable` | `entity_id, now_ns` | `POSE, VISIBILITY, OBSERVED_AT` |
| `PRIOR_ATTEMPT` / `prior_attempt` | `entity_id, action` | `ATTEMPT_OUTCOME` |
| `LAST_FAILURE_REASON` / `last_failure_reason` | `entity_id, action` | `ATTEMPT_OUTCOME` |
| `REACHABLE_VALVE` / `reachable_valve` | `robot_id, valve_class` | `REACHABLE, RESTRICTED_BY, BLOCKS, CONNECTS, AFFORDANCE, OPERATIONAL_STATE` |
| `CHANGES_SINCE` / `changes_since` | `location_id, since_ns` | `OBSERVED_AT, IN, ON, BLOCKS, CONNECTS, REACHABLE, RESTRICTED_BY, POSE, VISIBILITY, DOOR_STATE, BATTERY_LEVEL, OPERATIONAL_STATE, ATTEMPT_OUTCOME` |
| `ROUTE_BLOCKER` / `route_blocker` | `robot_id, destination_id` | `CONNECTS, BLOCKS, REACHABLE, RESTRICTED_BY, DOOR_STATE` |
| `DUPLICATE_IDENTITY` / `duplicate_identity` | `label` | `LABEL, ALIAS, ENTITY_CLASS, OBSERVED_AT, VISIBILITY` |
| `CONFLICTS_UNKNOWN` / `conflicts_unknown` | `entity_id` | `IN, ON, NEAR, BLOCKS, CONNECTS, HELD_BY, REACHABLE, RESTRICTED_BY, OBSERVED_AT, LABEL, ALIAS, ENTITY_CLASS, AFFORDANCE, VISIBILITY, DOOR_STATE, OPERATIONAL_STATE, POSE, BATTERY_LEVEL, ATTEMPT_OUTCOME` |

Names, argument fields, and expansions are schema constants shared by M5, M6, V0,
the epistemic oracle, and replay. An unknown/missing/extra query argument invalidates
the row rather than changing its retrieval document.

Normalized aliases are appended only when an exact retained alias fact refers to the
query's stable entity ID; alias facts are sorted by fact ID. Query construction never
reads truth or a future observation.

The lexical score is frozen BM25. With `k1=1.2`, `b=0.75`, retained-document count
`N`, document frequency `df_t`, document term frequency `tf_td`, document length `dl`,
and retained average document length `avgdl`, token `t` contributes

```text
idf_t = ln(1 + (N - df_t + 0.5) / (df_t + 0.5))
bm25_td = idf_t * tf_td * (k1 + 1)
           / (tf_td + k1 * (1 - b + b * dl / avgdl))
```

The lexical score sums `bm25_td` once for each distinct query token present in the
document. An empty corpus/query returns no lexical hit. Statistics are recomputed from
the current retained facts. Lexical order is `(score descending, received_at_ns
descending, fact_id ascending)`.

M6 adds no library or model. Each token and bigram's UTF-8 bytes are SHA-256 hashed and
the digest is interpreted as one unsigned big-endian integer. Because every allowed
`D` is a power of two, the low `log2(D)` bits select the dimension and the immediately
next bit selects sign (`0 -> +1`, `1 -> -1`). For document `d`, every token component
is exactly `signed_bm25_td = sign_t * bm25_td`. For query `q`, it is
`signed_query_t = sign_t * idf_t * tf_tq`. All colliding token components are summed
algebraically in their selected dimension before the full vector is L2-normalized.
An empty or zero-norm vector stays all-zero. Cosine is the dot product of normalized
vectors; a zero vector has no vector hits. Vector order is `(cosine descending,
received_at_ns descending, fact_id ascending)` and only the first `R` are retained.

The final candidate union is deterministic: authoritative typed matches first in
`(predicate expansion order, received_at_ns descending, fact_id ascending)`, then
lexical hits in lexical order, then vector hits in vector order. First occurrence of a
fact ID wins and records every channel/score that also found it. The common context
fact/byte truncation runs only after union. Vector hits remain non-authoritative.
The index rebuilds from canonical retained fact bytes after every retention change.

V0 uses the same hash dimension, tokenization, IDF, and top-R rule but cannot use
typed/lexical authoritative lookup. This makes M6 feasible, reproducible, and a
true additive retrieval test rather than a disguised embedding service.

A hand fixture freezes collision behavior. With `D=8`, token `valve` hashes to exact
digest `c9af477d19b132dbcda4ebbaa61c923d29ef65c44636b929da54acd23f4e40eb`,
dimension `3`, sign `-1`; token `where` hashes to
`b48111c10c65fc119368edafb19f97451759ee90b3f44647368135ca47aa4753`,
dimension `3`, sign `+1`; token `room` hashes to
`1f1c5b2fad778434024f1537986346927917f4755a6e7d3fd91f22653b7c3132`,
dimension `2`, sign `+1`; and token `valve_valve` hashes to
`fc28d41e794aea83e56def0612984eeda33fdb1a6ca54b5435d748c772b79fbd`,
dimension `5`, sign `-1`.

The equal-BM25 micro-fixture has `N=1`, one document and one query whose complete
token sequences are both `[valve, where]`, `tf=1`, `df=1`, `dl=avgdl=2`. Each token
therefore has `idf=ln(4/3)` and `bm25=idf`; the equal opposite-signed components sum
to exactly zero in dimension 3 for both document and query before normalization, so
the vector channel returns no hit. This component fixture bypasses fact field markers
deliberately; a separate full-record fixture covers the specified document/query
compiler. Golden tests recompute every full digest, BM25 component, collision sum,
norm, cosine, union ordering, deduplication, and context truncation by hand.

### 6.2 Queries, decisions, and metrics

Every trace asks the ten program queries: location, last observation, pose safety,
prior attempt, failure reason, reachable valve under restriction, changes since a
room visit, route blocker, duplicate-label identity, and conflicting observations/
unknowns (`Reflect Lite Research Program.md:1686-1697`). Applicable queries also
require a sealed decision: act, rescan, re-identify, choose an alternative, or
report unknown.

The primary metric is seed-level epistemic answer/decision correctness under changed
and stale state (`Reflect Lite Research Program.md:1699-1703`). Outcome-oracle safety
metrics are stale-belief action rate and wrong-identity rate. Other secondary metrics
are repeated scans, explanation accuracy, Brier calibration, query latency, actual
storage bytes, input fact count/bytes, and emitted context count/bytes. Abstention is
correct only when the epistemic oracle says unknown or unresolved contradiction.

Endpoint denominators are fixed before generation. Exp04 correctness and Brier score
use all ten query IDs per seed. Stale-action rate uses the four action-eligible query
IDs `POSE_USABLE`, `REACHABLE_VALVE`, `ROUTE_BLOCKER`, and `DUPLICATE_IDENTITY`.
Wrong-identity rate uses `REACHABLE_VALVE` and `DUPLICATE_IDENTITY`. Ambiguous-
retrieval accuracy uses `DUPLICATE_IDENTITY`. Explanation accuracy uses
`LAST_FAILURE_REASON`. Repeated scans is a count over the complete ten-query trace,
not a rate. A missing required answer keeps the fixed denominator and scores incorrect;
a malformed/missing row makes the shard invalid rather than changing a denominator.

### 6.3 Nested scientific and promotion rule

M4 establishes the primary claim only if both correctness contrasts against M0 and
V0 clear the frozen minimum effect. M4 is promotion-eligible only if it also clears
the simultaneous stale-action, wrong-identity, and repeated-scan improvements versus
M0; is non-inferior to equal-information H0 on correctness; remains inside input,
context, storage, and latency ceilings; and passes every integrity/oracle guard.

The M5 stale/wrong composite is exactly
`0.5 * stale_action_rate + 0.5 * wrong_identity_rate`. M5 advances over M4 only if
the composite reduction clears its frozen margin and correctness and repeated scans
are simultaneously non-inferior, while all M4 resource/integrity guards remain true.

M6 advances over M5 only if ambiguous-identity retrieval improves over both M5 and
V0 by the frozen margin, correctness remains non-inferior to M5, and context, storage,
and latency remain within their frozen ceilings. Otherwise the hash index is removed
from the runtime path, matching the program's embedding kill condition
(`Reflect Lite Research Program.md:1719-1723`). The simplest eligible architecture
wins; an exact tie uses M0 through M6 order.

## 7. Experiment 05 semantic twin

Exp05 consumes only the promoted Exp04 `MemoryView` protocol and conformance fixture.
It receives no implementation type or winner-specific escape hatch.

- **T0 — geometry only:** metric poses, extents, collision data, and frames.
- **T1 — geometry plus topology:** T0 plus rooms, doors, connectivity,
  traversability, containment, and route costs.
- **T2 — T1 plus semantics:** identity, aliases, affordances, restrictions, and
  task properties.
- **T3 — T2 plus live belief:** operational state, confidence, timestamps,
  provenance, visibility, and uncertainty.
- **T4 — T3 plus episodes:** frozen Exp04 history queries.
- **TM — monolithic same-facts control:** one flat untyped record containing exactly
  T4's facts, times, expiry, and budgets.

T0-T4 are required by the program (`Reflect Lite Research Program.md:1834-1842`).
The deterministic planner filters forbidden/inapplicable goals and uses `heapq`
Dijkstra with ties ordered by `(total_cost, path_entity_ids)`. It receives compact
query results, not the full twin. A plan contains typed steps, preconditions, fact
provenance, expected cost, and invalidation reasons.

The five missions are: inspect the nearest coolant valve without restricted entry;
reach Pump 2 with a recharge if needed; reach Valve 7 around unavailable Door 3;
place a carried tool safely; and replan when a room becomes restricted
(`Reflect Lite Research Program.md:1813-1817`). A plan is invalid if it enters a
forbidden region, traverses a closed edge, chooses an unsupported affordance, uses
an expired pose, assumes insufficient energy, selects the wrong duplicate identity,
or continues after a precondition change.

The primary metric is seed-level invalid-plan rate. Secondary/guard metrics are
mission success, forbidden-region violations, invalid affordances, stale-belief
failures, route cost, replans, semantic/geometry query counts, context size, and
latency. Any forbidden-region violation is a safety failure.

Exp05 invalid-plan rate and mission success use all five mission IDs per seed. The
history-dependent T4 contrast uses exactly `ALTERNATE_DOOR_AFTER_FAILURE` and
`REPLAN_AFTER_RESTRICTION`, denominator two. Forbidden-region and invalid-affordance
rates use all five missions; route cost averages only successful missions but also
reports the fixed successful-count denominator. Zero successful missions yields a
missing required route-cost guard and makes that variant-seed invalid.

### 7.1 Fixed comparator rule

T3's invalid-plan superiority contrasts against T0, T1, and T2 form one simultaneous
three-contrast Bonferroni family. Mission-success non-inferiority is also required
simultaneously against each of T0, T1, and T2 in a separate three-contrast family.
There is no post-confirmation “best baseline” selection. T3 must clear every bound,
all resource guards, and zero forbidden violations.

T4's history-subset invalid-plan contrast against T3 is tested only after T3 passes.
T4/TM equal-facts non-inferiority on invalid plans and mission success is a two-endpoint
Bonferroni family. T4 advances only if it improves the frozen history-dependent
subset over T3 and clears both TM bounds and all T3 guards. The simplest passing
layer wins; ties use T0 through T4 order.

## 8. Lifecycle and exact statistical protocol

### 8.1 Separate state machines

The experimental lifecycle is:

```text
DRAFT -> PILOT -> FROZEN -> CONFIRMATION -> DECISION -> PROMOTED | STOPPED
```

Artifact validity is independently `VALID` or `INVALID`. The scientific result is
independently `SUPPORTED`, `NOT_SUPPORTED`, or `INCONCLUSIVE`. A prerequisite or
resource state is independently `READY` or `BLOCKED` with a machine-readable reason.
`INVALID` evidence cannot yield a scientific result. `BLOCKED` is not evidence.
Only `VALID + SUPPORTED + READY` may promote; `VALID + NOT_SUPPORTED` stops cleanly;
valid but underpowered/resource-exhausted evidence is `INCONCLUSIVE` and stops without
promotion.

### 8.2 Draft, pilot, and freeze

Draft completes when trace separation, compilers, variants, scorers, sidecar replay,
commands, and validation tests exist. Draft carries no claim.

Each experiment uses eight paired pilot seeds from a checked-in pilot root. Seeds
0-3 are tuning; seeds 4-7 are one untouched pilot evaluation. No decision reads
evaluation seeds before one common configuration for the experiment is selected.
That configuration applies unchanged to every variant, including H0/M5, V0/M5, and
T4/TM equality pairs. Evaluation cannot trigger retuning; a change begins a new
protocol revision with eight new pilot seeds. At most two pilot revisions and the
three configurations below per revision are allowed.

The three complete configurations are fixed before pilot:

- **BASE:** TTL multiplier `1.0`, confidence threshold `0.70`, contradiction delta
  `0.20`, retained-event cap `128`, retained-input cap `256` facts/`65536` bytes,
  context cap `16` facts/`4096` bytes, hash dimension `256`, retrieval R `8`, battery
  reserve `0.20`, and replan cap `2`.
- **CONSERVATIVE:** multiplier `0.5`, threshold `0.85`, delta `0.10`, event cap `64`,
  retained input `128`/`32768`, context `8`/`2048`, dimension `128`, R `4`, reserve
  `0.30`, replans `1`.
- **PERMISSIVE:** multiplier `2.0`, threshold `0.55`, delta `0.30`, event cap `256`,
  retained input `512`/`131072`, context `32`/`8192`, dimension `512`, R `16`, reserve
  `0.10`, replans `3`.

Let `event_interval_ns` be the fixed generator interval. The compiler applies the
predicate-by-predicate TTL table in Section 5.1: two intervals for `POSE`, `VISIBILITY`,
`IN`, `ON`, `NEAR`, `HELD_BY`, and `OBSERVED_AT`; one interval for `DOOR_STATE`,
`BATTERY_LEVEL`, `OPERATIONAL_STATE`, `BLOCKS`, `CONNECTS`, `REACHABLE`, and
`RESTRICTED_BY`; and maximum signed 64-bit time for `LABEL`, `ALIAS`, `ENTITY_CLASS`,
`AFFORDANCE`, and `ATTEMPT_OUTCOME`. The selected TTL multiplier applies only to
finite TTLs before upward rounding to one virtual-clock tick; immutable maximum-time
facts remain unchanged. Physical energy units and task timeouts are fixed
in `base.yaml`; the three complete configurations above are the only pilot choices.
A configuration that exceeds an inherited resource cap, cannot encode one fact,
produces nonfinite output, violates stepwise equality, or fails artifact validation
is infeasible and cannot be selected.

Every configuration runs every variant on the four tuning seeds. A configuration is
eligible only if every canonical variant is artifact-valid, stepwise equality holds,
and all inherited resource/safety caps pass. Exp04 selects eligible configurations
lexicographically by highest equal-variant-weight mean correctness, lowest mean
stale/wrong composite, lowest repeated scans, lowest context bytes, lowest storage
bytes, then BASE before CONSERVATIVE before PERMISSIVE. Exp05 uses lowest equal-
variant-weight mean invalid-plan rate, highest mission success, lowest route cost,
lowest context bytes, lowest storage bytes, then the same fixed configuration order.
Seeds and variants have equal weight. Exact numerical ties proceed to the next key.
If no configuration is eligible, the experiment is `INCONCLUSIVE` and `STOPPED`.
The selected common configuration runs once on seeds 4-7; failures affect pilot
disposition but never cause retuning.

For each configuration before ranking, candidate resource ceilings use
`ceil_to_unit(1.25 * maximum_usage)` across every canonical variant and tuning seed in
that configuration. Fact/context counts round upward to one fact, bytes to
1024 bytes, and serial nearest-rank p95 latency to 0.1 ms. If a resulting ceiling
exceeds an inherited cap, that configuration is infeasible. The selected
configuration's candidate ceilings become the frozen ceilings. Minimum-effect margins are
`ceil_to_task_unit(max(one_task_unit, 0.5 * sample_SD_of_paired_tuning_seed_contrast))`;
sample SD uses denominator `n-1`, and
`ceil_to_task_unit(x) = ceil(x / one_task_unit) * one_task_unit`. Non-inferiority
margins use the same formula. Zero SD still yields one task unit.
Rate task unit is one outcome divided by the fixed tuning denominator; count unit is
one event; byte unit is one byte; time unit is one virtual-clock tick. Outward rounding
means superiority margins round away from zero and non-inferiority widths round up.
A derived margin outside the metric's attainable range makes the result
`INCONCLUSIVE`; it is never clipped to manufacture a feasible gate.

Freeze records implementation/config/source/schema hashes, generator version and RNG
algorithm, confirmation seed **count**, all compiler/event/relation semantics, selected
configurations, exact formulas and resulting margins, multiplicity families, missing
rules, budgets, and pilot manifests. It does **not** contain confirmation seeds,
scenarios, trace hashes, or outcomes.

After the protocol and implementation hashes freeze, the orchestrator creates a new
recorded confirmation RNG root, generates the complete scenario/seed manifest, hashes
it, and only then permits a variant to run. Confirmation data did not exist during
implementation, pilot, or protocol freeze. Any change returns to Draft and requires a
new protocol revision and a new unseen confirmation root.

### 8.3 Confirmation and multiplicity

Each experiment confirms on 32 paired seeds. A seed contains all ten Exp04 queries or
all five Exp05 missions and all frozen event subtypes relevant to that experiment.
One validly declared timeout or resource-interrupted variant-seed may be absent and is
reported; that seed is removed from every contrast involving that variant. A second
such loss or systematic variant-specific noncompletion makes the scientific result
`INCONCLUSIVE`. A malformed/corrupt/hash-mismatched shard, stepwise equality mismatch,
scorer/oracle breach, missing required safety output, or undeclared exclusion makes
the artifact set `INVALID` and no scientific result is computed. Nothing is imputed.

All contrasts use seed-level paired differences and a deterministic 10,000-resample
percentile bootstrap. For each contrast, complete paired seed IDs are sorted ascending.
The NumPy `PCG64` seed is the first 128 bits, interpreted big-endian, of SHA-256 over
canonical UTF-8 JSON array
`[protocol_hash, experiment_id, family_id, contrast_id, "bootstrap-v1"]`. Each
resample draws exactly the paired-seed count indices with replacement. Bootstrap
statistics are sorted ascending; percentile endpoint `p` uses nearest rank
`max(0, ceil(p * 10000) - 1)` with no interpolation. Identical bootstrap values are
retained, not deduplicated. Exact equality to a superiority margin fails; exact
equality to a non-inferiority boundary passes. If promotion/ranking values are exactly
tied after all bounds, the fixed architecture orders M0-M6 then T0-T4 break the tie.
Families and marginal intervals are:

- Exp04 M4 correctness versus M0 and V0: two contrasts, 97.5% intervals.
- Exp04 M4 stale action, wrong identity, and scans versus M0: three contrasts,
  98.333333% intervals.
- Exp04 M5 stale/wrong composite versus M4 plus correctness and scan non-inferiority:
  three contrasts, 98.333333% intervals.
- Exp04 M4 versus H0 correctness non-inferiority: one 95% interval.
- Exp04 M6 ambiguous retrieval versus M5 and V0: two contrasts, 97.5% intervals.
- Exp04 M6 correctness non-inferiority versus M5: one 95% interval.
- Exp05 T3 invalid plans versus T0/T1/T2: three contrasts, 98.333333% intervals.
- Exp05 T3 mission-success non-inferiority versus T0/T1/T2: three contrasts,
  98.333333% intervals.
- Exp05 T4 history subset versus T3: one 95% interval.
- Exp05 T4/TM invalid-plan and mission-success non-inferiority: two endpoints,
  97.5% intervals.

These Bonferroni marginal intervals give a 95% simultaneous family. A superiority
lower bound must be strictly greater than its frozen margin. A non-inferiority lower
bound equal to the negative margin passes. Secondary metrics are descriptive unless
listed in a family or absolute gate. Variant selection is hierarchical in the order
written; a later family is evaluated only if its prerequisite passes.

Exp04 is `SUPPORTED` only if M4 clears its primary family and all operational/equal-
information guards; M5/M6 promotion then follows their nested gates. Otherwise it is
`NOT_SUPPORTED` only when valid intervals exclude the frozen minimum effects;
remaining valid uncertainty is `INCONCLUSIVE`. Exp05 uses the equivalent T3/T4 rule.

## 9. Bounded shards, resume, and maxima

One evidence-bearing command runs exactly one declared shard keyed by
`(experiment, protocol_revision, phase, variant, configuration, seed)`. Valid phases
are `pilot-tuning`, `pilot-evaluation`, and `confirmation`. The canonical textual key
is, for example, `exp04:r1:confirmation:M5:BASE:00000017`; every component is parsed
and compared with the protocol and trace manifest. A shard executes one complete
trace: ten queries for Exp04 or five missions for Exp05. It has a 60-minute wall-clock
ceiling and 4 MiB runner-artifact ceiling. `--max-cases` is smoke-only unless it equals
10 for Exp04 or 5 for Exp05.

The launcher requires `cwd` to equal the physical project root returned by
`git rev-parse --show-toplevel` after resolving symlinks; it refuses any other working
directory. Every path below is therefore executable and project-root-relative, and the
runner rejects an absolute path or any `..` component. The exact command shapes are:

```text
uv run python experiments/04_memory/run.py \
  --protocol experiments/04_memory/configs/frozen.yaml \
  --shard-id exp04:r1:confirmation:M5:BASE:00000017 \
  --observation-trace experiments/04_memory/manifests/exp04-confirmation/00000017.json \
  --output-root results/04_memory --headless --max-cases 10

uv run python experiments/05_semantic_twin/run.py \
  --protocol experiments/05_semantic_twin/configs/frozen.yaml \
  --shard-id exp05:r1:confirmation:T3:BASE:00000017 \
  --observation-trace experiments/05_semantic_twin/manifests/exp05-confirmation/00000017.json \
  --output-root results/05_semantic_twin --headless --max-cases 5
```

Pilot uses the identical command shape with the corresponding project-relative
`experiments/<experiment>/configs/base.yaml`, a pilot phase in the shard ID, and its
declared configuration/seed. An evidence command rejects a wrong cwd, absolute or
parent-traversing path, duplicate phase/configuration flag, missing `--headless`,
mismatched case count, unknown shard, truth argument/environment variable, or output
path not derived from the shard key. Reissuing the exact command is the only resume
operation and must validate-and-skip.

Per revision, Exp04 has at most
`9 variants * (3 configurations * 4 tuning seeds + 1 selected configuration * 4
evaluation seeds) = 144` pilot shards; Exp05 has at most
`6 * (3 * 4 + 1 * 4) = 96`. Confirmation has at most
`9 * 32 = 288` Exp04 and `6 * 32 = 192` Exp05 variant-seed shards, 480 total before
any killed-variant reduction.

The retained maximum covers both permitted pilot revisions and confirmation, not one
pass in isolation:

```text
pilot runner shards:        480 * 4 MiB = 1,920 MiB
confirmation runner shards: 480 * 4 MiB = 1,920 MiB
pilot truth+observation:      32 * 4 MiB =   128 MiB
confirmation truth+obs:       64 * 4 MiB =   256 MiB
pilot scorer artifacts:      480 * 1 MiB =   480 MiB
confirmation scorer:         480 * 1 MiB =   480 MiB
two pilot aggregate areas:     2 * 128 MiB = 256 MiB
confirmation/cross-phase aggregate allowance = 512 MiB
------------------------------------------------------
maximum retained P6 total                  = 5,952 MiB
```

The 32 pilot trace pairs are two revisions times eight seeds times two experiments;
the 64 confirmation pairs are 32 seeds times two experiments. A truth+observation
pair shares one 4 MiB ceiling, and each sealed scorer output has a separate 1 MiB
ceiling. Temporary sibling directories count against the 512 MiB allowance and must
be absent before a new phase. `5,952 MiB` is below the inherited 10 GiB ceiling. Phase
preflight sums all retained files plus the complete declared next-phase maximum and
refuses to start unless both total budget and free disk cover it. Retention is
create-only through final decision; no favorable shard may replace an unfavorable one.

Destinations derive from experiment/protocol-revision/phase/variant/configuration/seed
plus protocol and observation-trace hashes.
Writes are create-only through sibling temporary directories, fsync, and atomic
rename. Resume validates every canonical rollout and P6 sidecar, checks all schema,
protocol, source, observation, equality, and content hashes, and skips only an exact
complete match. Missing/extra files, interrupted temporary directories, oversize,
hash mismatch, or invalid replay fail the shard; nothing is overwritten or repaired
in place. A create-only shard completion manifest is written only after every case
validates.

## 10. Canonical rollout and P6 sidecars

P6 wraps the existing `RolloutWriter`; it does not redefine its core. Every shard
contains:

```text
rollout/
  metadata.json
  config.json
  metrics.json
  events.jsonl
  observations.npz
  actions.parquet
  summary.md
p6/
  queries.parquet
  decisions.parquet
  plans.parquet
  memory_snapshots.jsonl
  fact_sets.jsonl
  replay.json
artifact-manifest.json
```

`observations.npz` remains the canonical repository observation artifact. Its
`Observation` values exist only at the ingestion/replay boundary and are compiled
immediately into deeply frozen P6 fact tuples before any architecture callback.
`actions.parquet` remains canonical `ActionChunk`/`ControlReference` data and is never
repurposed for queries or plans; it is a valid empty canonical table when the benchmark
executes no physical chunk. Canonical shared events retain their existing lifecycle
meanings.

P6-local sidecars have exact versioned schemas:

- `queries.parquet`: query ID/time/type, canonical arguments, epistemic answer,
  confidence, cited fact IDs, omitted count, latency,
  `request_event_subtype=QUERY_REQUESTED`, and
  `response_event_subtype=QUERY_RESPONDED`.
- `decisions.parquet`: decision ID/query ID/time, closed decision enum, entity/route
  IDs, cited facts, uncertainty, and
  `publication_event_subtype=DECISION_PUBLISHED`. It contains no outcome or
  truth-derived column; the scorer writes outcome metrics elsewhere and never mutates
  this file.
- `plans.parquet`: plan ID/mission ID, ordered step index, action enum, entity/edge,
  precondition fact IDs, predicted cost, and runner-authored
  `predicted_invalidation_reason`, plus `publication_event_subtype=PLAN_PUBLISHED |
  PLAN_REPLACED`. The reason uses a closed prediction enum and may be `NONE`; there is
  no actual-validity or truth-derived reason column. Every `PLAN_REPLACED` row
  cross-links one `SEMANTIC_REPLAN` whose payload carries the canonical structured
  `mission_state` object.
- `memory_snapshots.jsonl`: variant-visible canonical state after each update, actual
  serialized byte count, input/context budget, hash, and
  `event_subtype=MEMORY_STATE_UPDATED`; each row cross-links one `MEMORY_UPDATED`.
- `fact_sets.jsonl`: compiler step, ordered fact IDs, canonical input-byte count,
  expiry decisions, and equality-group hash.
- `replay.json`: sidecar schema hashes, counts, terminal query/decision/plan IDs,
  equality proof, predicted invalidations, and truth-free replay result.

A P6 sidecar validator rejects extra/missing columns, duplicate IDs/keys, nonfinite
values, time regression, unknown enums/relations/subtypes, dangling fact references,
budget violations, outcome/truth columns in runner files, and hash mismatch. Sidecar
replay reconstructs fact compilation, memory mutations, queries, decisions, plans,
and **predicted** invalidations from `observations.npz`, shared events, and sidecars
without the generator or truth. It does not claim actual plan validity.

`artifact-manifest.json` lists the relative path, media type, byte count, and SHA-256
of every immutable file under `rollout/` and `p6/`. It excludes itself and any temporary
file, is canonicalized, fsynced, and atomically created last. Validation recomputes the
listed set exactly, so a self-hash recursion or unlisted file is impossible.

Truth traces and scorer outputs are separate orchestrator artifacts with their own
manifests. The sealed scorer bundle alone may contain actual plan validity and
`actual_invalidation_reason`, cross-linked by plan/mission/step ID. These files are
never copied under or used to replay a runner shard.

## 11. Verification design

Tests cover:

- byte-identical truth/observation generation and named-RNG independence;
- physical descriptor/path/import/environment isolation of truth from hostile runners;
- fresh observation decode, immutable records, per-variant rehash, and zero shared
  caches/state;
- hostile callbacks that attempt array writes, `setflags(write=True)`, mapping/list
  mutation, object-field replacement, and retained-reference mutation both during and
  after later callbacks, plus `Observation` discovery, with no mutation visible to a
  later callback or freshly decoded variant;
- sealing before scorer launch and scorer refusal of writable/incomplete output;
- epistemic-oracle unknown/stale/conflict answers versus outcome-oracle hidden-truth
  safety decisions;
- stable IDs, the closed fact-kind/predicate/value/TTL domain, exact relation/subtype
  vocabularies and sidecar waivers, structured `SEMANTIC_REPLAN.mission_state`,
  separate action issuance/execution/truth/scoring, total coincident-event order, and
  monotonic chronology;
- fact-ID/byte/time/TTL/expiry golden fixtures, exact-budget boundaries, deterministic
  truncation, and contradiction preservation;
- stepwise H0/M5, V0/M5, and T4/TM input/equality hashes after every update and before
  every query/mission;
- M0-M6/H0/V0 retention semantics and MemoryView conformance;
- BM25 tokenization/scoring, signed SHA-256 feature hashing, zero vectors, cosine/top-R
  ties, algebraic collision summation, the frozen hand fixture, typed/lexical/vector
  union/dedup order, rebuild after expiry, M6 typed authority, and V0 non-authority;
- all ten query answers/decisions and five missions/invalid-plan reasons;
- Dijkstra cost/tie ordering, bounded replan, and safety rejection before action;
- exact pilot configurations, selection keys/ties, infeasibility, 25% headroom,
  rounding, task units, derived margins, and no pilot-evaluation retuning;
- post-freeze confirmation generation and rejection of a preexisting/reused seed or
  scenario manifest;
- paired bootstrap, every multiplicity family, hierarchy, equality boundaries,
  exact hash-derived PCG64 seeds, nearest-rank endpoints, retained ties, fixed endpoint
  denominators, missing rules, and lifecycle/artifact/scientific/blocker/promotion
  state separation;
- canonical RolloutWriter compatibility with `observations.npz` and empty/nonempty
  canonical actions;
- exact sidecar schemas, predicted-only runner plan fields/replay, scorer-only actual
  validity/reasons, manifest self-exclusion, extra-file rejection, corruption
  rejection, and truth absence;
- exact six-component shard identity and CLI examples, case limits, wall/byte ceilings,
  two-revision 5,952 MiB arithmetic, full-next-phase preflight, create-only atomic
  publication, validate-and-skip resume, and mismatch refusal; and
- offline/network/LLM/physical/remote guards, clean implementation state, full tests,
  secret scan, artifact sizes, and diff checks.

## 12. Dependency and promotion boundaries

The first implementation remains pure Python plus current repository dependencies:
NumPy for numeric records, PyArrow for canonical Parquet, and PyYAML for configuration
(`pyproject.toml:5-14`). Typed adjacency plus `heapq` is sufficient for topology.

Experiment-local seams isolate future adapters:

```text
EventStore.append/scan
RelationStore.upsert/neighbors
RetrievalIndex.add/search
RoutePlanner.shortest_path
TwinExporter.export
```

SQLite/DuckDB is considered only if measured retained-event size or query latency
exceeds the frozen ceiling. NetworkX is considered only if graph algorithms expand
beyond neighbor lookup and Dijkstra. A vector library is considered only if M6 passes
and the deterministic hash index misses its budget. USD/IFC/Spark-DSG adapters require
a later independent interchange claim. No adapter may change evidence semantics.

Only a `VALID + SUPPORTED + READY` confirmation may propose promotion. Exp04 may
promote only the smallest useful `MemoryView` records and semantics. Exp05 may promote
only layer/query contracts justified by its gates. The generator, truth schema,
experiment-specific memory stores, planner, fixtures, thresholds, BM25/hash index,
plots, and sidecars remain experiment-local. Promotion is a separate commit with
compatibility tests and an explicit interface diff, matching the program boundary
(`Reflect Lite Research Program.md:3153-3181`).

## 13. Parallel-safe preparation

Preparation may use five ownership-isolated workstreams:

1. fixture/protocol: separated traces, IDs, RNG, fact compiler, vocabularies, schemas;
2. Exp04 memory: M0-M6/H0/V0 and MemoryView over observation-only fixtures;
3. Exp04 evaluation: epistemic/outcome scorers, queries, metrics, and gates;
4. Exp05 preparation: T0-T4/TM, planner, missions, and stub MemoryView conformance;
5. artifact/verification: canonical rollout wrapper, sidecars, replay, shards, and
   validation.

Trace schemas, observation API, fact compiler, total order, sidecar schemas, and the
stub MemoryView fixture freeze before parallel preparation. Exp04 pilot, freeze,
post-freeze confirmation generation, confirmation, decision, and promotion are serial.
Exp05 then consumes the promoted protocol, reruns conformance, and follows its own
serial lifecycle. No Exp05 result feeds back into the Exp04 decision.

## 14. Required decisions

Exp04 produces `MEMORY_ARCHITECTURE_DECISION.md`, assigning retained information to
`FAST_STATE`, `EPISODIC_LOG`, `SEMANTIC_GRAPH`, `GEOMETRIC_STATE`,
`EMBEDDING_INDEX`, or `LEARNED_LATENT` as required
(`Reflect Lite Research Program.md:1710-1717`). Exp05 produces
`TWIN_ARCHITECTURE_DECISION.md`, recording authority and mutation rules for BIM/IFC,
geometric export, runtime graph, and live belief
(`Reflect Lite Research Program.md:1868-1879`).

Each decision links valid immutable manifests, names its lifecycle/artifact/scientific/
blocker/promotion states separately, reports every family and guard, and records
rejected layers/adapters. A stopped or blocked component cannot be reframed as a
promotion.
