# Experiment 05: Typed Digital-Twin Architecture Decision

Status: **PRELIMINARY ENGINEERING EVIDENCE**. This is an independently
reconstructable synthetic benchmark, not a pilot, deployment, or validation on
an industrial facility.

## Decision

Use **T3** as the minimum runtime architecture: durable geometry, explicit
topology, semantics, and a timestamped live-belief layer. Add the bounded T4
episodic failure history when the application can preserve its provenance.
T4 did not improve final success in this matrix, but it reduced invalid initial
plans from 46 to 34 (12 cases, 26.1%) and avoided four reactive replans. That is
useful operational evidence, but not evidence that unrestricted memory or a
larger world-model stack is warranted.

Do not add an embedding store, language model, production USD/IFC adapter, or
generic evidence framework until a concrete mission requires one. The current
typed layers and raw case/outcome records are sufficient for the question this
experiment asks.

## Layer ownership

| Layer | Owns | Must not claim |
|---|---|---|
| BIM/IFC durable source | Facility hierarchy, room and nominal door/asset identities, durable properties and policies, source revision/provenance | Current door availability, live operational state, or robot belief |
| USD/geometric twin | Frames, metric poses and bounds, collision/occupancy geometry, visual hierarchy | Traversability or operational authority |
| Runtime scene graph | Current room/asset/door nodes, containment, topology and semantic relations, query projections linked to durable IDs | Authority to rewrite durable source facts |
| Live belief | Timestamped/confidence-bearing door availability, dynamic restrictions, operational state, battery, blockers, pose freshness, visibility, and observation provenance | Silent promotion of inference into durable truth |
| Episodic history | Append-only attempts, failures, observed changes and their provenance | Unbounded memory, deletion of contrary evidence, or durable-fact mutation |

Durable geometry, topology, policies, and their version are authoritative from
their BIM/IFC source. Signed/current sensors are authoritative for operational
observations within their validity window; task instructions are authoritative
for task constraints. Routes, reachability, stale projections, and confidence
are inferred. An inference never overwrites its source observation.

Stale belief is retained with timestamp, confidence, provenance, and an
explicit stale disposition. It is never silently deleted. T3/T4 either refresh
the fact or plan around its uncertainty. A semantic agent may query typed
identity, affordance, restriction, topology, live-confidence, and bounded
history relations. It may append observations/events or propose a plan; it may
not mutate durable geometry/topology/policy, forge sensor provenance, or erase
evidence.

## Executed matrix

The v5 matrix contains 40 seeds x 5 missions x 5 variants: 200 distinct
seed-by-mission cases and 1,000 outcomes. Cases vary geometry, door state,
battery, pose freshness, storage availability, blockers, instruction changes,
belief confidence, and episodic history. Dynamic inputs include 70
`ROUTE_BLOCKED`, 40 `ROOM_RESTRICTED`, and 40 `INSTRUCTION_CHANGED` events.

The five missions were:

1. inspect the nearest coolant asset;
2. reach Pump2 while satisfying recharge requirements;
3. inspect Valve7 using an authorized alternate route;
4. store a carried tool in a compatible location;
5. replan after a runtime room restriction.

| Variant | Success | Wilson 95% | Invalid initial plans | Forbidden-region violations | Reactive replans | Stale-belief failures |
|---|---:|---:|---:|---:|---:|---:|
| T0 geometry only | 0/200 (0.0%) | 0.0-1.9% | 120 | 0 | 0 | 0 |
| T1 + topology | 39/200 (19.5%) | 14.6-25.5% | 68 | 40 | 0 | 0 |
| T2 + semantics | 77/200 (38.5%) | 32.0-45.4% | 82 | 40 | 0 | 8 |
| T3 + live belief | 166/200 (83.0%) | 77.2-87.6% | 46 | 0 | 44 | 0 |
| T4 + episodic history | 166/200 (83.0%) | 77.2-87.6% | 34 | 0 | 40 | 0 |

T3/T4 improve success by 44.5 percentage points over T2 in this benchmark.
The strongest result is not merely aggregate success: only T3/T4 complete all
40 dynamic-restriction missions, and neither produces a forbidden-region
violation. T4 preserves T3's outcome rate while improving first-plan quality.

T0's zero is a property of this deliberately separated benchmark: geometry
provides no multi-room traversability or semantic affordances, and direct paths
through walls are invalid. It is not a claim that every geometry-only planner
must fail. Likewise, the Wilson intervals are descriptive uncertainty across
these synthetic seed-by-mission cases, not a sampled real-world population.

The reported replanning latency is deterministic operation-derived virtual
latency, not wall-clock performance. Seeds are domain-separated by mission;
the same numeric seed across two missions is not asserted to describe the same
building realization.

## Evidence and reconstruction

The sole reportable root is `results/engineering-twin-v5`. Earlier ignored
v1-v4 exploratory roots are superseded and are not evidence for this decision.
The v5 root contains every typed layer input, hidden actual fact, dynamic event,
initial/final plan, action, observed event, outcome, and disposition.

- Cases: `935186de2fa56d866702e50fb9cdbb2f5c3a44cb82447bf2a00d9381b8c9aa1a`
- Outcomes: `1cd3cc57d8c3c446df80b22a1cb3184423bd2a16401c317449d37aa3f24a956c`
- Raw manifest: `50ea596954d74d4a8a01fb5fa5298b7bd146c473863f50462743cd3be87af6e4`
- Aggregate metrics: `2b15cb12dcedcb1ce549a426693da2083a7643cd2528c4d5ea00a7fa8c5281f5`
- Annotated sample index: `3ecb50ea1375333c2681fbb32d364c3cf52148768b021631a491d522932e6719`
- Reconstruction recipe: `6ef7bbc12cd3fb7e308852f05792340593a92760ad80bfcd5668a9f4f9a13828`
- Canonical six-file inventory: 1,923,387 bytes,
  `c7743ab843e9a2baa1a612d4697d3531e57c9cd1368fb5d882ec89f968d3b1f6`

The preregistered-style sample index identifies one working and one nonworking
T3 case using deterministic first-canonical selection:

- WORKING: seed 0, nearest-coolant mission, case
  `b6ad50b09b125134e87e087992a67d20b9cf7fca582088fca2a24e0d148f68f8`,
  outcome `b717c3ccc952b09079a311e5db7151cde598b044268643c6ec8d6c9d666bd4c0`.
- NONWORKING: seed 6, same mission, case
  `1195499fc2a511dd672ceb5e0083caf174601d2f80beb64f218752f25b552651`,
  outcome `7de284fa98de3be6390fdec8d72b70af16e39746a66341220cb4c58e46c885a5`.

Reconstruction reloads and hashes the raw files, regenerates all cases and all
five plans/outcomes per case, and then regenerates the metrics, recipe, and
sample index byte-for-byte. It rejects a changed input, plan, event, outcome,
or derived byte.

## Limits and next empirical question

This experiment does not test sensor-to-asset identity mapping, a real IFC or
USD corpus, industrial map scale, distributed updates, general language
grounding, learned perception, or an LLM planner. The next useful experiment is
a bounded real-format adapter test on one versioned facility slice, with stale
sensor observations injected at the T2/T3 boundary. It should test whether the
T3 advantage and T4 first-plan reduction survive real identifiers, geometry,
and observation provenance before either is called pilot-ready.
