# Exp14 Mission-Space Semantic Ceiling Preflight

Status: preregistration and implementation plan. This is explicitly not pi0.5,
not a final capability claim, and not real-world evidence.

## Question and design

In a deterministic state-transition building environment, how do four fixed agents
degrade as mission dependency depth increases and paired route, topology,
constraint, disturbance, intervention, paraphrase, and novelty changes are applied?
Outcomes are derived from environment state, never taxonomy labels supplied by an
agent.

Calibration uses only seeds 7401--7404. The exact held-out matrix is 12 fresh,
disjoint seeds 8401--8412 x 6 missions x 4 horizons x 8 variants x 4
agents = 9,216 episodes. Each baseline is paired within seed, mission, horizon, and
agent with seven one-axis variants. Missions are parcel delivery, retrieve, tool
use, unpack, store, and rearrange. Horizons 4/8/12/16 set both dependency depth and
the action budget.

The environment retains room topology, agent location, object/container/tool
locations, inventory, open/locked state, safety constraints, and scheduled
disturbance/intervention events. Actions have explicit preconditions and deterministic
state transitions. The four frozen agents are open-loop, live-memory only,
lower-loop recovery without semantic replan, and full live+episodic hierarchy.

Primary independent scores are mission completion, safety, and normalized progress.
Secondary scores are retries, semantic replans, memory freshness, steps, and action
cost. Analysis uses paired-seed 10,000-draw bootstrap intervals and reports
heterogeneity by mission, horizon, and perturbation axis. Working/nonworking samples
use the lowest seed satisfying frozen full-hierarchy/open-loop classes.

Every episode retains per-step state-before, action, observation-after, live-memory,
retry, semantic-replan, event, and terminal records. Evidence includes the exact
matrix/config/source/seed closure, raw graph tables, derived episode/contrast tables,
samples, and a recursive file manifest. The result report must use only preflight,
synthetic, deterministic-environment language.

## Implementation plan

Goal: build and immediately execute the smallest deterministic experiment that
answers the preregistered question.

Architecture: one Python module owns immutable matrix construction, the building
transition function, four fixed policies, independent terminal scoring, evidence
serialization, bootstrap analysis, and reconstruction. One test file exercises
state transitions, policy separation, scoring independence, matrix closure, and
tamper-resistant manifests.

- [ ] Write failing tests for the exact matrix and state-transition preconditions.
- [ ] Implement config loading, scenario construction, and deterministic `step`.
- [ ] Write failing tests for independent scoring and the four policy contracts.
- [ ] Implement policies and per-step ledgers without accepting outcome labels.
- [ ] Write failing tests for evidence closure, manifest, and reconstruction.
- [ ] Implement raw/derived serialization and paired bootstrap analysis.
- [ ] Run focused tests and Ruff; atomically commit preregistration, config, source,
      and tests before any held-out outcome execution.
- [ ] Execute the frozen matrix, report first counts/results, verify reconstruction,
      write the bounded result, and commit evidence separately.

Global constraints: one module, one test file, one config; no generic framework;
pure deterministic Python; no network/model inference/physical execution; first
balanced shard must be reportable if the full matrix exceeds 15 minutes.
