# Experiment 01 engineering controller sweep

Status: `PRELIMINARY_NON_CONFIRMATORY_CONTROLLER_REGIME_ENGINEERING_SWEEP`.
This is a descriptive diagnostic and must not be pooled with the preregistered pilot
or confirmation study.

## Outcome

The clean retry completed 108 real MuJoCo 3.12.0 rollouts: four representations,
three common PD settings, three MPC smoothness settings for predictive stack P5,
three timing/motion regimes, and two seeds. Every bundle validated and all 180 target
displacement events were retained. None recovered inside the declared window.

The sweep rejects a simple explanation of the first probe's failure: changing PD
gain from 60/6 through 100/10 did not remove the globally saturated regime. Mean
torque-saturation fraction remained between 0.9413 and 0.9460 across variants. Thus
the absolute task remains nonworking and no stack is promotion-eligible.

Within that failed regime there is a consistent, useful relative shift. P5 at 60/6
had the lowest aggregate mean p95 error, 0.135184 m. Against P5 at 80/8, its paired
p95-error differences were `[-0.047921,-0.056858,-0.065280,-0.013094,-0.062219,-0.012041]`
m over the six condition/seed pairs, mean -0.042902 m. Against 100/10 the mean paired
difference was -0.065433 m. P4 at 60/6 improved substantially in four fast/mid cells
but regressed slightly in both 5 Hz/700 ms cells, so its shift is latency-dependent.

Changing P5 MPC smoothness around the 60/6 controller was comparatively negligible:
0.01 minus 0.02 changed mean p95 error by +0.001022 m, and 0.04 minus 0.02 by
+0.001218 m. This points to the common low-level regime, not MPC smoothness, as the
next controller-level discriminator.

## Aggregate rows

Each row averages six rollouts: three exact conditions times two seeds. `Recovered`
is the number of recovered displacement events over ten events.

| Variant | Recovered | Mean p95 error m | Mean saturation | Mean clamp | Mean jerk p95 | Mean discontinuity |
|---|---:|---:|---:|---:|---:|---:|
| P5 60/6 sw=.02 | 0/10 | 0.135184 | 0.946027 | 0.202880 | 556951.3 | 0.000536 |
| P5 60/6 sw=.01 | 0/10 | 0.136206 | 0.946027 | 0.200480 | 550584.1 | 0.000524 |
| P5 60/6 sw=.04 | 0/10 | 0.136402 | 0.946027 | 0.202187 | 552683.7 | 0.000533 |
| P4 60/6 | 0/10 | 0.137479 | 0.945387 | 0.767893 | 2438028.4 | 0.004653 |
| P1 100/10 | 0/10 | 0.177073 | 0.943893 | 0.937493 | 709513.9 | 0.003969 |
| P5 80/8 sw=.01 | 0/10 | 0.177329 | 0.946027 | 0.210293 | 666663.9 | 0.000587 |
| P5 80/8 sw=.04 | 0/10 | 0.177554 | 0.946027 | 0.210613 | 664459.6 | 0.000583 |
| P5 80/8 sw=.02 | 0/10 | 0.178086 | 0.946027 | 0.210187 | 667171.2 | 0.000586 |
| P1 80/8 | 0/10 | 0.179187 | 0.943253 | 0.938773 | 704379.0 | 0.003896 |
| P1 60/6 | 0/10 | 0.181396 | 0.941280 | 0.940480 | 674845.2 | 0.003768 |
| P5 100/10 sw=.04 | 0/10 | 0.200158 | 0.946027 | 0.203147 | 701615.4 | 0.000559 |
| P5 100/10 sw=.01 | 0/10 | 0.200249 | 0.946027 | 0.204320 | 700099.5 | 0.000561 |
| P5 100/10 sw=.02 | 0/10 | 0.200617 | 0.946027 | 0.203627 | 700869.0 | 0.000560 |
| P4 80/8 | 0/10 | 0.203633 | 0.945387 | 0.553813 | 2095928.5 | 0.003998 |
| P4 100/10 | 0/10 | 0.210844 | 0.945547 | 0.539840 | 2010047.1 | 0.003839 |
| P2 100/10 | 0/10 | 0.233888 | 0.944907 | 0.656480 | 632948.9 | 0.003023 |
| P2 80/8 | 0/10 | 0.237656 | 0.944960 | 0.649867 | 625514.0 | 0.003000 |
| P2 60/6 | 0/10 | 0.404878 | 0.946027 | 0.783360 | 653244.3 | 0.003413 |

## Exact design and evidence

- Stacks: P1 joint target, P2 joint trajectory, P4 Cartesian trajectory, P5 MPC objective.
- PD settings: `(60,6)`, `(80,8)`, `(100,10)`.
- P5 smoothness: `0.01`, `0.02`, `0.04`; other stacks retain `0.02`.
- Conditions: `core-20-000-1`, `core-10-300-2`, `core-05-700-2`.
- Seeds: `20260823`, `20260824`.
- Execution Git SHA: `35daed51c54c4754092c8bdf3372f572a684ac7c`.
- Runtime-code-ledger SHA-256: `c0be4f48c5ee2f20dd0775e814b6f6fbd34ca01d10fa11a993c32778be75afba`.
- Raw bundle files: 756 files, 179,677,333 bytes.
- Summary: 47,594,099 bytes, SHA-256 `9814680cac357907a2a3bd45b127418cc982ca8cc6f47a3cac7a2e8877992870`.

Ignored raw evidence is at
`experiments/01_policy_control/results/engineering-controller-sweep-r2/`.
`probe-summary.json` contains every bundle-relative path, every constituent file
size/hash, the complete scalar and raw 500 Hz metrics, scenario hashes, conditions,
seeds, controller values, dependency versions, runtime ledger, and disposition.
Tables, plots, or images can be reconstructed from those rows without reading this
Markdown table.

## Failure and provenance annotations

The first attempt at `engineering-controller-sweep/` produced 108 bundles and then
failed closed because `evaluate.py` changed during execution. Its approximately
177,176 KiB are retained as provenance-invalid negative evidence; it has no summary
and is excluded from every result above.

The clean retry completed all bundles and the stable runtime-ledger end check, then
its initial summary serialization rejected a nested immutable `mappingproxy`. A
bounded finalizer revalidated every bundle, every exact runtime-ledger identity, and
the unique execution Git SHA before publishing the summary. The summary explicitly
records this path as `finalized_after_serialization_failure=true`. Because the runner
file was patched to add the finalizer after execution, the execution-probe script
hash is null and the finalizer script hash is retained. This is an orchestration
provenance limitation and another reason the sweep remains preliminary; raw bundle,
runtime-code, configuration, scenario, and metric provenance remain fully bound.

## Interpretation boundary

“Best” above means lowest descriptive p95 error inside a globally failed controller
regime. It does not mean task success, statistical superiority, or causal isolation.
The official pilot must retain the preregistered common-controller gates. A future
engineering discriminator should change the actuator/controller authority model or
reference-rate interaction rather than continuing to micro-tune MPC smoothness.
