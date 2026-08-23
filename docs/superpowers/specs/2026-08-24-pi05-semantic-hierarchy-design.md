# π0.5 Semantic Hierarchy Experiment Design

**Status:** user-approved architecture; preregister before outcome execution
**Date:** 2026-08-24
**Scientific authority:** indicative until checkpoint-backed runs and independent review pass

## Question

Does a frontline π0.5 semantic planner improve task recovery when it consumes a
separate live semantic memory and episodic history, while motion replanning and
MPC/PID retry/retrigger remain independently measurable lower layers?

## Non-negotiable boundary

```text
images + instruction + task-relevant memory projection
                         |
                         v
             π0.5 semantic planner
       semantic plan / semantic replan only
                         |
                         v
               motion/skill planner
       trajectory generation / motion replan
                         |
                         v
             separate MPC/PID executor
      tracking / local retry / controller retrigger
```

π0.5 never emits or executes torque, joint targets, Cartesian setpoints, or an
action chunk in this experiment. Its ordinary VLA action output is ignored and
cannot cross the typed semantic-plan boundary.

## State and memory

Four stores remain distinct:

1. **Metric world:** regions, poses, reachability, obstacles, free space, and
   collision geometry.
2. **Live semantic belief:** stable entity IDs, labels, room/region membership,
   affordances, authorization/restrictions, confidence, provenance, observed
   time, stale/unknown state, and evidence-ledger hash.
3. **Episodic history:** append-only observations, failures, plans, interventions,
   execution receipts, and outcomes.
4. **Controller state:** joints, references, action age, contact, torque, and
   tracking errors; never written into semantic memory as authoritative facts.

The π0.5 context is a deterministic, size-bounded projection containing the
current image(s), instruction, relevant semantic facts, recent causally prior
events, and summarized lower-layer failure receipts. Hidden scenario labels,
expected recovery levels, reward, and future events are forbidden.

## Typed semantic output

The adapter must parse or reject one canonical object:

```json
{
  "object_id": "cup_17",
  "affordance": "side_grasp",
  "destination_region": "tray_A",
  "subgoals": ["approach", "grasp", "transport", "release"],
  "constraints": ["avoid_region_hot", "keep_upright"],
  "reason_codes": ["target_available", "route_authorized"],
  "confidence": 0.83
}
```

Malformed, ungrounded, unauthorized, stale, or unknown references fail closed.
The adapter retains raw model request/response bytes, checkpoint identity,
sampling parameters, parse result, and grounding receipts.

## Comparison zoo

All cells use the same motion planner and the same primary P6 controller; a
repaired P4 sensitivity subset measures controller interaction.

| ID | Semantic planner | Memory | Semantic replan | Motion replan | MPC/PID retry/retrigger |
|---|---|---|---|---|---|
| Z0 | deterministic oracle | live + episodic | yes | yes | yes |
| Z1 | deterministic rule planner | none | yes | yes | yes |
| Z2 | π0.5 | none/stateless | yes | yes | yes |
| Z3 | π0.5 | fixed semantic snapshot | yes | yes | yes |
| Z4 | π0.5 | live semantic only | yes | yes | yes |
| Z5 | π0.5 | episodic only | yes | yes | yes |
| Z6 | π0.5 | live semantic + episodic | no | yes | yes |
| Z7 | π0.5 | live semantic + episodic | yes | no | yes |
| Z8 | π0.5 | live semantic + episodic | yes | yes | no |
| Z9 | π0.5 | live semantic + episodic | yes | yes | yes |

The main scientific contrasts are Z9-Z2 (memory), Z9-Z6 (semantic replanning),
Z9-Z7 (motion replanning), and Z9-Z8 (control retry/retrigger). Z0 is a ceiling,
not the baseline used to claim improvement.

## Environment gradient

Use both task-local manipulation scenes and building-scale semantic contexts:

- room/region changes and access restrictions;
- object unavailable, moved, substituted, or visually ambiguous;
- route/approach blocked after planning;
- motion path infeasible with a valid waypoint alternative;
- command dropout, latency, tracking error, and physical perturbation;
- combined semantic + motion + control faults;
- memory confidence/staleness and event-history length gradients.

Every scenario has multiple magnitudes/delays and at least ten matched
realizations. Scenario identity is hidden from π0.5 and all policies.

## Measures

Retain more than binary success:

- semantic-plan grounding, object/affordance/region correctness, constraint
  satisfaction, parse/refusal rate, calibration, and context-token count;
- stale/unknown usage, semantic query count, episodic retrieval precision,
  provenance coverage, and memory age at decision;
- semantic replan count/latency, motion replan count/latency, MPC/PID retry and
  retrigger count, budget consumption, reset validity, and intervention level;
- first-attempt/eventual success, task time, unnecessary intervention rate,
  lowest-sufficient-level accuracy, wrong-object/forbidden/unsafe actions;
- path length, clearance, tracking error, dwell, jerk, torque/contact, action age,
  and controller hold time;
- π0.5 inference p50/p95, checkpoint/model size, refusal/error classes, and
  performance by scene, disturbance, severity, controller, and memory condition.

Paired seed rows are authoritative. Confidence intervals resample realization
clusters, retaining all zoo cells and scenarios from each selected realization.

## Checkpoint and feasibility gate

Primary model is the official Physical Intelligence π0.5 checkpoint and exact
OpenPI revision recorded in the source registry. The first run is a
checkpoint-backed semantic-interface feasibility probe, not a mocked result.

Before outcomes, retain:

- exact OpenPI commit and checkpoint URI/hash;
- environment, runtime, device, dtype, and inference configuration;
- evidence that an actual checkpoint forward pass occurred;
- evidence that raw action output is discarded and cannot reach motion/control;
- semantic-output parse/grounding positive and negative controls;
- measured memory and latency on the available Apple M2 Max 32 GB host.

If the official checkpoint cannot execute locally, retain the failed attempt and
use the official OpenPI client against an explicitly authenticated remote policy
server. Do not substitute a smaller model while calling it π0.5. Without either a
local or remote checkpoint-backed forward pass, the π0.5 cell is `NOT_RUN`, never
simulated or inferred from a rule planner.

## Evidence and outcome labels

Retain raw requests/responses, projected memory, semantic plans, lower-layer plans,
500 Hz controller traces, event/intervention ledgers, matched rows, bootstrap
inputs/draws, canonical graph tables, deterministic SVG/PNG figures, working and
nonworking examples, manifests, hashes, and clean reconstruction.

Possible labels:

- `PI05_HIERARCHY_SUPPORTED`
- `PI05_MEMORY_SUPPORTED_ONLY`
- `PI05_REPLANNING_SUPPORTED_ONLY`
- `NO_PI05_ADVANTAGE`
- `INVALID_EXPERIMENT`
- `NOT_RUN_NO_CHECKPOINT_BACKEND`

No result may generalize beyond the frozen scenes, checkpoint, embodiment, and
controller stack.
