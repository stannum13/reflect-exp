# Experiment 05: Typed Digital-Twin Architecture Decision

Status: **PRELIMINARY ENGINEERING EVIDENCE**. This is an independently
reconstructable synthetic benchmark, not a pilot, deployment, or validation on
an industrial facility.

## Decision

Use **T3** as the minimum runtime architecture: durable geometry, explicit
topology, semantics, and a timestamped live-belief layer. Add the bounded T4
episodic failure history when the application can preserve its provenance.
T4 improved final success by two percentage points in this matrix and reduced
invalid initial plans from 46 to 34 (12 cases, 26.1%). That is useful
preliminary evidence, but not evidence that unrestricted memory or a larger
world-model stack is warranted.

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

The validity-repaired v6 matrix contains 40 seeds x 5 missions x 5 variants: 200 distinct
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
| T1 + topology | 39/200 (19.5%) | 14.6-25.5% | 50 | 40 | 40 | 0 |
| T2 + semantics | 77/200 (38.5%) | 32.0-45.4% | 64 | 40 | 40 | 8 |
| T3 + live belief | 152/200 (76.0%) | 69.6-81.4% | 46 | 0 | 61 | 0 |
| T4 + episodic history | 156/200 (78.0%) | 71.8-83.2% | 34 | 0 | 55 | 0 |

T3 and T4 improve success by 37.5 and 39.5 percentage points over T2 in this benchmark.
The strongest result is not merely aggregate success: only T3/T4 respond to
runtime restriction and instruction events without a forbidden-region
violation. They complete 32/40 restriction missions after the new instruction
constraint makes eight cases infeasible. T4 improves both outcome rate and
first-plan quality in this matrix.

The planner boundary is construction-enforced in v6. `T0View` exposes only
geometry and instruction; T1 adds topology, T2 semantics, T3 live belief, and
T4 bounded history. Planning accepts only these immutable view types. Hidden
actual facts exist solely in the execution/scoring seam, which reveals only
encountered events and outcomes. Poison-layer tests fail on any forbidden read.
All 40 `INSTRUCTION_CHANGED` inputs carry a typed payload, authority, and tick;
T1-T4 encounter the change, apply its route constraint, and produce a causally
different plan trace from the exact no-change counterfactual.

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

The sole reportable layer-effect root is `results/engineering-twin-v6`. Earlier
v1-v4 exploratory roots are superseded. V5 is preserved byte-for-byte but
machine-marked `INVALID_FOR_LAYER_EFFECT_CLAIMS` by
`results/engineering-twin-v5-invalid.json`: its planner capability boundary was
not enforced at construction, hidden truth shared the evaluation function, and
instruction-change events were noncausal. The v6 root contains every typed layer input, hidden actual fact, dynamic event,
initial/final plan, action, observed event, outcome, and disposition.

- Cases: `22286ed0bcf74349214dc809f2a6b61bc33ee7b2cadf10c20923bfc3c56c5961`
- Outcomes: `dfc2a17f1b7efbe420cc79619d1de4f495176fea0774c1bbed96f4360df95542`
- Raw manifest: `c9ebd482915fa31698053e4f56822b464ffd88f1d4b23ce2a2b2fe4824ab6e8c`
- Aggregate metrics: `28f3bd059999ad49a51731e379d9cd308def8951b35bac03b8615a0d2b99000c`
- Annotated sample index: `e1313987c136fc3af3bc59a72bdd2d9a836e81507f1e16ecf127c377919f03c1`
- Reconstruction recipe: `a7a2bcdd3e3bb666c6562942a9e2e9bbb4f09a2a055af07cdfc61e546fd7a398`
- Canonical six-file inventory: 1,985,647 bytes,
  `5f2568e001241f8192760963b71f76ea10d9033ef737a5a5c0635815579c6614`

The preregistered-style sample index identifies one working and one nonworking
T3 case using deterministic first-canonical selection:

- WORKING: seed 0, nearest-coolant mission, case
  `4b000e5cde71deecefa1b815413894ab22899d49df270363471b8e2e1017ee16`,
  outcome `251663a38f6854ba1f908971bd861522012e794dfcedd4fc4e4eb12a94ae5153`.
- NONWORKING: seed 6, same mission, case
  `a7ffd46ef818aa68f32007153ba12c05fe9f04bfcb8ffce2fa7d3efe14f77bd6`,
  outcome `5aa456b643d87cdfb0b647e27e69371f4c0d49e0725a1fd8341214d89c6adb76`.

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
