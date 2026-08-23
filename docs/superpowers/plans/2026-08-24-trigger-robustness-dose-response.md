# Experiment 11: Trigger Robustness Dose Response

## Scope

Measure trigger-transport engineering under a deterministic typed oracle planner. This is synthetic, independently replayable evidence and is explicitly not VLA evidence. Experiment 10 files and evidence remain immutable.

## Frozen design

- Two stores: `LIVE_BELIEF`, `LIVE_EPISODIC`.
- Four active policies: `PERIODIC_ONLY`, `FAILURE_THRESHOLD`, `EVENT_DRIVEN`, `HYBRID`.
- Ten preregistered transport-quality profiles vary recall, delay, false-positive bursts, duplicate and out-of-order delivery, cooldown, and hysteresis.
- Four disturbance families, two severities, three mission horizons, two prompt envelopes, and twelve paired outcome seeds.
- Every episode executes exactly `horizon + 4` ticks and emits exactly one terminal record. Early completion never truncates the ledger.
- Seed-cluster bootstrap resamples the twelve paired seeds and carries every factorial row for a seed together.

## Integrity gates

1. Frozen matrix identities are exact, unique, and exhaustive.
2. Raw ticks are the exact expected integer domain for every episode; every episode has one terminal at the declared final tick.
3. The independent scorer replays world, transport, store, trigger, plan, action, and metrics from starts/config/seeds, rejecting authored-summary trust.
4. Freeze closure recursively covers every local import and every loaded config/seed plus environment lock inputs.
5. Reconstruction reproduces every raw, derived, graph, and report byte and verifies the content manifest.
6. SVG and PNG are deterministic, data-faithful companions with frozen theme-independent style metadata.

## Execution

First commit the frozen design, RED/GREEN integrity tests, runner, scorer, and calibration evidence. Then execute the frozen outcome matrix once, validate, reconstruct in a fresh directory, and atomically commit raw/derived evidence and report. Any failed validation retires the outcome seed namespace.
