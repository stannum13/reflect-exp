# Experiment 01 actuation-admissibility sweep

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_ACTUATION_ADMISSIBILITY`.

## Outcome

Higher reference slew converts the recovered P6 regime into absolute success.
P6 residual .5 at slew 24 passed 6/6, recovered 10/10, had zero saturation,
and mean clamp 0.005973. The P1 boundary also passed 6/6 at slew 24 with
nearly identical metrics, showing the success is primarily low-gain actuation
admissibility rather than a demonstrated residual advantage.

P2 horizon .1 at slew 24 recovered 10/10 and passed both fast cells, but its
four slower cells remained clamp-limited (mean clamp 0.017547). P5 passed 4/6
at either slew; both slow-condition failures were recovery-only. No rollout
was unsafe and no tested configuration revived torque saturation.

This is the first all-condition/all-seed absolute success in the engineering
sequence, but it is based on two fresh seeds. P6 .5/slew24, P1/slew24, and
P2 horizon .1/slew24 now warrant untouched-seed replication.

## All results

Each row is six rollouts over three conditions and seeds 20260845/46.

| Variant | Working | Recovered | Saturation | Clamp | p95 error m | Failure rows |
|---|---:|---:|---:|---:|---:|---|
| P2 h=.1 slew12 | 0/6 | 10/10 | 0 | 0.037813 | 0.060223 | clamp 6 |
| P2 h=.2 slew12 | 0/6 | 9/10 | 0 | 0.035680 | 0.064683 | clamp 6; recovery 1 |
| P6 residual=.5 slew12 | 2/6 | 10/10 | 0 | 0.014240 | 0.049597 | clamp 4 |
| P1 boundary slew12 | 2/6 | 10/10 | 0 | 0.014027 | 0.049596 | clamp 4 |
| P5 control slew12 | 4/6 | 7/10 | 0 | 0.000107 | 0.070505 | recovery 2 |
| P2 h=.1 slew24 | 2/6 | 10/10 | 0 | 0.017547 | 0.060498 | clamp 4 |
| P2 h=.2 slew24 | 2/6 | 9/10 | 0 | 0.015627 | 0.064793 | clamp 4; recovery 1 |
| P6 residual=.5 slew24 | 6/6 | 10/10 | 0 | 0.005973 | 0.048770 | none |
| P1 boundary slew24 | 6/6 | 10/10 | 0 | 0.006027 | 0.048770 | none |
| P5 control slew24 | 4/6 | 7/10 | 0 | 0.000000 | 0.070505 | recovery 2 |

At P6 slew12, only the two 5 Hz/700 ms cells crossed the clamp gate. At slew
24 all six P6 cells passed: clamp ranged 0.00384–0.00832. P2 horizon .1 at
slew24 passed both 20 Hz cells (clamp .00544/.00640), while 10 Hz and 5 Hz
cells remained between .01888 and .02592.

## Evidence identity

- Common PD: 5/.5; P5 smoothness .02.
- Conditions: `core-20-000-1`, `core-10-300-2`, `core-05-700-2`.
- Fresh seeds: `20260845`, `20260846`.
- Execution Git SHA: `25a7d62edf44ed30cd53bed6b09752d8b671af3d`.
- Runtime-code-ledger SHA-256: `a9c799754f9241aa175e1c0da1ae21e8ed395b3e2ecdc13558efa599621a537f`.
- Probe script SHA-256: `2d3a7080d68b32a529d70b90a6a3b7b8ae8b0e6f390abca0f0de05b9e6549dff`.
- Canonical summary: 27,007,888 bytes, SHA-256
  `c6c064603640fdc5ac662fedd2799646491dc587776dc2a08a30ff0be37a85fc`.
- Full bundles: 60 directories, 420 files, 100,076,409 bytes.
- Complete ignored evidence: 422 files, 127,095,296 bytes. Canonical inventory
  SHA-256: `a9a84faa18dc7c80695ee940bf41e0244414d781f0e9c2333281ec1637c07a25`.

Ignored raw evidence is at
`experiments/01_policy_control/results/engineering-actuation-admissibility/`.
It binds every full 500 Hz bundle, file/configuration/scenario/source hash,
working/nonworking reason, and all 60 valid attempts. There were no invalid
runtime attempts.
