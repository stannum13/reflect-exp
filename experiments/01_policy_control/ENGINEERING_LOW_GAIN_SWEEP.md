# Experiment 01 engineering low-gain sweep

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_LOW_GAIN_SWEEP`.
This is a descriptive discriminator and must not be pooled with the
preregistered pilot or confirmation study.

## Outcome

The sweep completed 72 real MuJoCo 3.12.0 rollouts: P1, P4, and P5 at common
PD gains `(10,1)`, `(20,2)`, `(40,4)`, and `(60,6)`, over three core
conditions and two seeds. P5 retained MPC smoothness `0.02`. Every full
bundle revalidated, all 120 target-displacement events are retained, and no
rollout was unsafe.

The evidence supports the narrow engineering hypothesis. Gains below 40/4
break the persistent 94–95% torque-saturation regime in every paired
condition/seed cell. The largest shift is P5 at 10/1: mean saturation fell
from 0.946027 at 60/6 to 0.107733, a paired mean change of -0.838293. P1 fell
to 0.498027 and P4 to 0.349547 at 10/1. At 20/2, mean saturation was 0.798987,
0.608320, and 0.671200 for P1, P4, and P5 respectively. Gains 40/4 did not
meaningfully change saturation from 60/6.

This is not an absolute working result. All 72 rollouts fail the declared
working rule. Every rollout still exceeds both the 0.05 saturation ceiling
and 0.01 clamp ceiling. P5 at 10/1 recovered 9/10 displacement events, but
one rollout also failed the 0.90 recovery gate; P1 at 10/1 recovered 10/10.
All other variant aggregates recovered 0/10. Low gains identify a useful
controller regime, but further work must address clamp authority and bring
saturation below the absolute ceiling.

## Aggregate rows

Each row contains six rollouts. `Working` is the number satisfying the full
absolute rule; `Recovered` aggregates events over those six rollouts.

| Variant | Working | Recovered | Mean saturation | Mean clamp | Mean p95 error m |
|---|---:|---:|---:|---:|---:|
| P1 10/1 | 0/6 | 10/10 | 0.498027 | 0.646667 | 0.062417 |
| P1 20/2 | 0/6 | 0/10 | 0.798987 | 0.900693 | 0.109028 |
| P1 40/4 | 0/6 | 0/10 | 0.941440 | 0.935360 | 0.145810 |
| P1 60/6 | 0/6 | 0/10 | 0.941280 | 0.940480 | 0.181396 |
| P4 10/1 | 0/6 | 0/10 | 0.349547 | 0.575360 | 0.080635 |
| P4 20/2 | 0/6 | 0/10 | 0.608320 | 0.675147 | 0.195630 |
| P4 40/4 | 0/6 | 0/10 | 0.945067 | 0.795573 | 0.111913 |
| P4 60/6 | 0/6 | 0/10 | 0.945387 | 0.767893 | 0.137479 |
| P5 10/1 sw=.02 | 0/6 | 9/10 | 0.107733 | 0.080000 | 0.051909 |
| P5 20/2 sw=.02 | 0/6 | 0/10 | 0.671200 | 0.171253 | 0.092341 |
| P5 40/4 sw=.02 | 0/6 | 0/10 | 0.945707 | 0.187573 | 0.106323 |
| P5 60/6 sw=.02 | 0/6 | 0/10 | 0.946027 | 0.202880 | 0.135184 |

## Paired shifts from 60/6

Values are gain-minus-60/6 means over the exact same six condition/seed
pairs. The bracketed values are the six saturation differences in canonical
seed-major, condition-within-seed row order retained by the summary.

| Stack and gain | Mean saturation shift | Mean p95-error shift m | Exact saturation shifts |
|---|---:|---:|---|
| P1 10/1 | -0.443253 | -0.118979 | `[-.470720,-.452800,-.404160,-.472640,-.452160,-.407040]` |
| P1 20/2 | -0.142293 | -0.072368 | `[-.164480,-.158400,-.128320,-.117760,-.154880,-.129920]` |
| P1 40/4 | +0.000160 | -0.035586 | `[-.000960,-.003840,-.005120,-.000320,+.001920,+.009280]` |
| P4 10/1 | -0.595840 | -0.056844 | `[-.919360,-.450240,-.422080,-.915520,-.448000,-.419840]` |
| P4 20/2 | -0.337067 | +0.058152 | `[-.463360,-.280000,-.252800,-.480000,-.286720,-.259520]` |
| P4 40/4 | -0.000320 | -0.025565 | `[-.000320,-.000320,-.000320,-.000320,-.000320,-.000320]` |
| P5 10/1 | -0.838293 | -0.083275 | `[-.927040,-.880960,-.816960,-.875200,-.796800,-.732800]` |
| P5 20/2 | -0.274827 | -0.042843 | `[-.274240,-.285440,-.250560,-.279040,-.297920,-.261760]` |
| P5 40/4 | -0.000320 | -0.028861 | `[-.000320,-.000320,-.000320,-.000320,-.000320,-.000320]` |

## Exact design and evidence

- Conditions: `core-20-000-1`, `core-10-300-2`, `core-05-700-2`.
- Seeds: `20260823`, `20260824`.
- Execution Git SHA: `7f5bfe8a81c5c32e6cc0795d4b67f9deea70faae`.
- Runtime-code-ledger SHA-256: `a9c799754f9241aa175e1c0da1ae21e8ed395b3e2ecdc13558efa599621a537f`.
- Runtime: Python 3.11.13, NumPy 2.4.6, MuJoCo 3.12.0, Darwin arm64;
  the simulation-only guard passed and MuJoCo rendering was disabled.
- Full bundles: 72 directories, 504 files, 119,672,516 bytes.
- Canonical final summary: 31,864,099 bytes, SHA-256
  `1d1402bf35d3f75255a5bd98859c9d520dcf5d94ab5a6b213af7d7cf9ac7e006`.
- Complete ignored evidence root: 507 files, 151,592,013 bytes. SHA-256
  `c7bd21ca376cfe501f5e85c01d11a4c977816b6ebc3859b5f0794eb959ccfd19`
  is over the canonical ordered inventory of relative path, byte count, and
  constituent-file SHA-256.

Ignored raw evidence is at
`experiments/01_policy_control/results/engineering-low-gain-sweep/`.
`probe-summary-v2.json` binds every bundle-relative path and constituent file
size/hash, complete scalar and raw 500 Hz metrics, exact scenario/configuration
identities, conditions, seeds, controller values, dependency versions, and the
runtime-code ledger. It is sufficient to reconstruct tables, paired analyses,
plots, and images without this Markdown table.

## Invalid attempt and provenance annotation

The physics pass completed and validated all 72 bundles, but its first summary
annotator incorrectly treated integer displacement/recovery counters as arrays.
That create-only invalid summary is retained as `probe-summary.json`: 42,686
bytes, SHA-256
`c5b36c39cd1284a4937c96862670a9973003241152a9bf242a02d31154566fdd`.
It records 72 `TypeError` annotation attempts and zero result rows; it is not a
second physics sample and is excluded from all analysis above.

A bounded finalizer revalidated every retained rollout, every constituent file,
the unchanged runtime-code ledger, and the single execution Git identity before
publishing `probe-summary-v2.json` create-only. The final summary binds both the
original execution-probe script hash and finalizer script hash, and links the
invalid summary by path, byte count, hash, and failure description.

## Interpretation boundary

The observed shifts are descriptive evidence from two engineering seeds, not
confirmatory estimates or promotion evidence. They isolate common PD gain as a
high-value discriminator: 10/1 is the first tested regime that sharply reduces
saturation and restores recovery for P1 and especially P5. It still fails the
absolute clamp and saturation contracts, so the preregistered pilot gates remain
unchanged.
