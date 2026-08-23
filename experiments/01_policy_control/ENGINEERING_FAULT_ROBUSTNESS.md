# Experiment 01 selected-controller fault robustness

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_FAULT_ROBUSTNESS`.

## Outcome

P6 with residual limit 0.5 rad and reference slew 48 rad/s passed all 16
fresh-seed fault cells: 8/8 under a dropped response and 8/8 under an
out-of-order response. It recovered 32/32 displacement events, had zero
torque saturation, and retained a mean clamp fraction of 0.002680.

The comparison separates recovery from admissibility. P2 with horizon 0.1 s
and slew 24 recovered the same 32/32 events, but failed all 16 cells because
its mean clamp fraction was 0.024280, above the predeclared 0.01 ceiling. P5
with gains 5/0.5 and slew 12 passed only 4/16 cells and recovered 16/32 events,
despite negligible clamp and no saturation. Thus the selected P6 setting is
the only tested controller that combined fault-cell recovery with the
absolute actuation limits.

## Fault-stratified results

| Controller | Fault | Working | Recovered | Saturation | Clamp | p95 error m |
|---|---|---:|---:|---:|---:|---:|
| P6 residual .5, slew 48 | DROP | 8/8 | 16/16 | 0 | 0.002680 | 0.060049 |
| P6 residual .5, slew 48 | OUT_OF_ORDER | 8/8 | 16/16 | 0 | 0.002680 | 0.060049 |
| P2 horizon .1, slew 24 | DROP | 0/8 | 16/16 | 0 | 0.024280 | 0.061502 |
| P2 horizon .1, slew 24 | OUT_OF_ORDER | 0/8 | 16/16 | 0 | 0.024280 | 0.061502 |
| P5 gains 5/.5, slew 12 | DROP | 2/8 | 8/16 | 0 | 0.000400 | 0.074411 |
| P5 gains 5/.5, slew 12 | OUT_OF_ORDER | 2/8 | 8/16 | 0 | 0.000400 | 0.074411 |

Each DROP rollout records exactly one injected dropped request; each
OUT_OF_ORDER rollout records exactly one rejected out-of-order chunk. Across
the 24 rollouts in each fault stratum, this is 24 recorded injections and 24
recorded rejections respectively. The paired numeric outcomes happen to be
identical between fault types for every controller and seed in this run; the
event traces nevertheless prove that the two distinct scheduler paths ran.

P5 worked only for seeds `20260862` and `20260864` under either fault. Every
P2 row failed only the clamp ceiling. Every nonworking P5 row failed only the
0.90 recovery-fraction rule. Representative lossless bundles are
`bundles/P6-res0p5-slew48/P6-probe-drop-20260859` (working),
`bundles/P2-h0p1-slew24/P2-probe-out-of-order-20260859` (clamp failure), and
`bundles/P5-control-slew12/P5-probe-drop-20260861` (recovery failure).

## Scope and evidence identity

This is a fresh-seed descriptive engineering test, not pilot or confirmation
evidence. The seeds are `20260859` through `20260866`. The absolute working
rule was frozen before execution: valid, no unsafe event, at least 90% event
recovery, saturation at most 0.05, and clamp at most 0.01. A stationary
negative control was not run because a zero-displacement episode requires a
different predicate and was outside the predeclared 48-rollout matrix.

- Execution Git SHA: `f4745020c87bece4ae389a35e457d02c7a125c82`.
- Runtime: Python 3.11.13, NumPy 2.4.6, MuJoCo 3.12.0, Darwin arm64.
- Runtime-code-ledger SHA-256:
  `a9c799754f9241aa175e1c0da1ae21e8ed395b3e2ecdc13558efa599621a537f`.
- Probe script SHA-256:
  `3d81688a5684a48de8c96b0264a0b5b8e501be18c3e9cf13e5c19bb5c6f6786b`.
- Canonical summary: 21,632,690 bytes, SHA-256
  `13703de3663dc6c28596a7d6096f2d13117daebb4c5d9f3a62413d05e654f963`.
- Full bundles: 48 directories, 336 files, 79,096,583 bytes.
- Complete ignored evidence: 338 files, 100,738,186 bytes. Canonical inventory
  SHA-256: `02390b5441a562592c0dd43b5218bc1a02db46c872dd38dc1137b4805cecd669`.

Ignored raw evidence is at
`experiments/01_policy_control/results/engineering-fault-robustness/`. It
retains all 500 Hz bundles, exact source/configuration/scenario/file hashes,
fault-event traces, invalid-attempt ledger (empty), and plot-ready per-rollout
annotations.
