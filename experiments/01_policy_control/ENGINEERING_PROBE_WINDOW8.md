# Experiment 01 engineering probe — window 8

Status: `PRELIMINARY_NON_CONFIRMATORY_PRELOCK_DIRTY_TREE_ENGINEERING_PROBE`.
These observations are an early implementation diagnostic, not pilot, confirmation,
or promotion evidence. They must not be pooled with the preregistered study.

## Outcome

The real MuJoCo 3.12.0 engine completed 18 raw rollouts: all six command stacks on
one common scenario under three materially different timing/fault conditions. All
bundles passed structural validation and reported zero unsafe ticks. However, none
of the 18 rollouts recovered a displacement event inside the recovery window, and
torque saturation occupied 87.7%–99.9% of ticks. Here `valid=true` means evidence and
runtime validity; it does not mean task success.

P5, the 79-candidate predictive stack, is the clearest working relative signal. Across
the three conditions it had the lowest mean p95 error (0.1697 m), lowest mean reference
discontinuity (0.000607), and lowest mean clamp fraction (0.2179). P2 is the clearest
nonworking relative sample: its mean p95 error was 0.2478 m. P3/P4 were similar to one
another and had roughly 3.1x P5's mean jerk p95. P6 tracked P1 closely, so this single
scenario does not show a useful bounded-residual shift.

These are descriptive single-scenario results. They establish neither statistical
superiority nor representation-only causality.

## Exact run identity

- Implementation Git SHA: `1a27ea88e58b047a8c4e3b2b8954ebdfecc7509c`
- Dirty-tree hash: `d2d32c6821959bdf219e97f393226b32e37a69239a2e2a38a438d3a5b2e354cb`
- Source-lock sentinel: `NO_P2_LOCK_ENGINEERING_PROBE`
- Sentinel SHA-256: `d282471e08e1c5120d366d8fd82c714955798cef165dd143c9fc83a1f971305f`
- Task-config SHA-256: `9c4575aec76b98b9b3369db2a93102530f04dbbe4a006f1c37792e4f4a175098`
- Inline arm-model SHA-256: `98d11593fdb03a9834a48c70a73899fe7054212fea973d79f2938d1fb0113918`
- Runtime: CPython 3.11.13, NumPy 2.4.6, MuJoCo 3.12.0, Darwin arm64, no GPU
- Scenario seed: `20260823`
- Scenario identity: `06f5156a3e9e47714b016cd8af2b7d7f127292d53171b2e0cc37f13898c7df8e`
- Scenario proposals: 1 accepted proposal, with one identical scenario used by all stacks

Conditions were (20 Hz, 0 ms, 1 move, no fault), (10 Hz, 300 ms, 2 moves,
no fault), and (5 Hz, 700 ms, 2 moves, out-of-order fault).

## Raw evidence and reconstruction

The ignored local evidence root is
`experiments/01_policy_control/results/engineering-probe-window8/`. It contains 18
validated rollout bundles and `probe-summary.json`. Each bundle retains canonical
events, observations, actions, control references, 3,125 raw 500 Hz metric rows,
metadata, and per-file hashes. Retained bundle bytes total 30,327,471.

`probe-summary.json` is 35,148 bytes with SHA-256
`7ffdc7f1dbe392a2cc3693533d3effa788215872a7daaf400de5cfcd3072d9e7`.
It records every bundle-relative path, every constituent filename/byte count/SHA-256,
the full scalar metrics, conditions, scenario identity, implementation identity, and
the explicit pre-lock disposition. Reconstruct a row by validating its bundle with
`reflect.rollout.validate_rollout`, reading `metrics.raw_500hz`, and recomputing the
scalar metrics through `experiments.01_policy_control.src.evaluate.compute_episode_metrics`.
Any missing bundle, constituent hash mismatch, scenario mismatch, or summary-hash
mismatch invalidates this probe.

## Per-rollout observations

|Condition|Stack|Mean error m|P95 error m|Final error m|Jerk p95|Discontinuity mean|Clamp frac|Saturation frac|Recovery events|Valid|
|-|-:|-:|-:|-:|-:|-:|-:|-:|-:|-:|
|probe-fast-20hz-0ms-1move|P1|0.145617|0.183666|0.188160|1062124.5|0.004192|0.996160|0.999360|0|True|
|probe-fast-20hz-0ms-1move|P2|0.186813|0.224586|0.186761|909031.4|0.003080|0.579520|0.999360|0|True|
|probe-fast-20hz-0ms-1move|P3|0.155376|0.200060|0.202443|2139774.2|0.004086|0.723520|0.999360|0|True|
|probe-fast-20hz-0ms-1move|P4|0.154961|0.200123|0.202545|2137140.6|0.004084|0.708480|0.998720|0|True|
|probe-fast-20hz-0ms-1move|P5|0.142241|0.165181|0.163727|736572.9|0.000889|0.306560|0.999360|0|True|
|probe-fast-20hz-0ms-1move|P6|0.145538|0.183617|0.188115|1062171.1|0.004192|0.996160|0.999360|0|True|
|probe-latency-10hz-300ms-2move|P1|0.143792|0.178895|0.174473|682045.9|0.004144|0.952000|0.950080|0|True|
|probe-latency-10hz-300ms-2move|P2|0.227858|0.263292|0.195765|652655.2|0.003101|0.662400|0.951360|0|True|
|probe-latency-10hz-300ms-2move|P3|0.152893|0.206437|0.208992|2078472.1|0.003986|0.509440|0.951360|0|True|
|probe-latency-10hz-300ms-2move|P4|0.151879|0.205865|0.208551|2082723.2|0.003982|0.495040|0.950720|0|True|
|probe-latency-10hz-300ms-2move|P5|0.138254|0.172024|0.152214|619026.2|0.000431|0.174400|0.951360|0|True|
|probe-latency-10hz-300ms-2move|P6|0.152473|0.197387|0.198656|676249.7|0.004139|0.952000|0.950080|0|True|
|probe-stress-5hz-700ms-2move-ooo|P1|0.129658|0.178800|0.101716|361817.0|0.003448|0.838080|0.879360|0|True|
|probe-stress-5hz-700ms-2move-ooo|P2|0.192435|0.255512|0.187020|314119.8|0.003012|0.724160|0.886720|0|True|
|probe-stress-5hz-700ms-2move-ooo|P3|0.140517|0.199056|0.202142|2062469.7|0.003927|0.444480|0.887360|0|True|
|probe-stress-5hz-700ms-2move-ooo|P4|0.139062|0.197034|0.200162|2063930.4|0.003925|0.453120|0.886720|0|True|
|probe-stress-5hz-700ms-2move-ooo|P5|0.130571|0.172024|0.159107|647106.1|0.000501|0.172800|0.887360|0|True|
|probe-stress-5hz-700ms-2move-ooo|P6|0.134458|0.179187|0.121809|367375.2|0.003444|0.837440|0.876800|0|True|

## Follow-up triggered by this probe

The saturation and zero-recovery pattern is a protocol-level warning. The official
pilot must retain the common-controller saturation gate and P1 hard-stop logic; it
must not tune a representation to hide this result. The preregistered shared PD
candidates, multiple scenario seeds, full condition grid, stationary controls, and
P5-only smoothness candidates are the next valid discriminators. A second engineering
probe is unnecessary unless it tests a materially different hypothesis; the next
priority is the sealed pilot.
