# Experiment 01 P6 residual-authority dose response

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_P6_RESIDUAL_DOSE`.

## Outcome

The smallest tested P6 component limit that passed the preregistered rule in
all 20 paired cells was **0.5 rad**. The same threshold applies separately to
the three core conditions (12/12) and two fault conditions (8/8): neither
0.375 nor 0.425 passed seed `20260870`. This is a result on the four tested
doses only; no value between doses is interpolated or imputed.

The failure transition was entirely recovery-driven. All doses had zero
torque saturation, no unsafe/invalid rollout, and mean clamp below 0.003.
Limits 0.375 and 0.425 produced identical working and recovery counts,
although their bound-hit counts differed. Raising authority to 0.5 recovered
the second event for seed `20260870` in every core and fault condition.

## Dose response

| Limit rad | All working | Core working | Fault working | Recovered | Clamp | Bound chunks | Bound components | Axis hits 0/1/2 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| .250 | 10/20 | 6/12 | 4/8 | 25/40 | .001840 | 392 | 756 | 283/392/81 |
| .375 | 15/20 | 9/12 | 6/8 | 35/40 | .002064 | 174 | 174 | 0/174/0 |
| .425 | 15/20 | 9/12 | 6/8 | 35/40 | .002064 | 164 | 164 | 0/164/0 |
| .500 | 20/20 | 12/12 | 8/8 | 40/40 | .002160 | 87 | 87 | 0/87/0 |

The per-seed smallest passing tested dose was .25 for seeds `20260867` and
`20260868`, .375 for `20260869`, and .5 for `20260870`. At .25, seeds 69 and
70 failed all five cells; at .375/.425 only seed 70 failed all five; at .5
every seed-condition cell passed. Each nonworking row failed only the 0.90
recovery rule.

| Limit | 5 Hz/700 ms | 10 Hz/300 ms | 20 Hz/700 ms | DROP | OUT_OF_ORDER |
|---:|---:|---:|---:|---:|---:|
| .250 | 2/4 | 2/4 | 2/4 | 2/4 | 2/4 |
| .375 | 3/4 | 3/4 | 3/4 | 3/4 | 3/4 |
| .425 | 3/4 | 3/4 | 3/4 | 3/4 | 3/4 |
| .500 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 |

## Mechanism evidence

All 174, 164, and 87 bound chunks at .375, .425, and .5 respectively were
generated after the second target move and bound only joint axis 1. At .25,
166 bound chunks occurred after move one and 226 after move two; all three
axes bound. Two .25 chunks were the deliberately rejected out-of-order
responses, while every other bound chunk was accepted. These facts come from
the retained chunk-level generated/request/response/move ticks and scheduler
dispositions, rather than reconstructed aggregate metrics.

Post-slew reference-clamp ticks over the active chunk intervals were 115,
129, 129, and 135 as authority increased. The corresponding episode-level
clamp fractions all remained comfortably under 0.01. Greater authority thus
solved the hard seed through recovery, not by reducing slew clamping.

Each rollout retains every emitted residual vector, exact per-axis equality
to the configured bound, per-chunk hit count, active interval, generated and
source-request/response ticks, latest-move relation, scheduler disposition,
and post-slew clamp-tick count. Full 500 Hz raw rows and recovery annotations
remain in each lossless bundle.

## Scope and evidence identity

Common configuration was P6 only, PD gains 5/0.5, reference slew 48 rad/s,
smoothness 0.02, and one-second nominal duration. The fresh paired seeds were
`20260867`–`20260870`. The absolute rule was frozen before execution: valid,
unsafe count zero, at least 90% event recovery, saturation at most 0.05, and
clamp at most 0.01. This is descriptive engineering evidence, not pilot or
confirmation evidence.

- Execution Git SHA: `4eca2c19722a9574c9e90da83ec3f5646bab5475`.
- Runtime: Python 3.11.13, NumPy 2.4.6, MuJoCo 3.12.0, Darwin arm64.
- Runtime-code-ledger SHA-256:
  `a9c799754f9241aa175e1c0da1ae21e8ed395b3e2ecdc13558efa599621a537f`.
- Probe script SHA-256:
  `9d8502a0d5ca71d2eeb28012a925e79886b7b73a7e85f783f232ab2052532d07`.
- Canonical summary: 38,009,642 bytes, SHA-256
  `c94d1c2d0a84138404c19e69f0b5623272d9fd5beeb8463f8a07f6cbe41bf829`.
- Full bundles: 80 directories, 560 files, 131,643,661 bytes.
- Complete ignored evidence: 563 files, 169,692,262 bytes. Canonical inventory
  SHA-256: `83d7fc6033b5277fa2435baf700f68f631f2b20eaff4a3cfac44b5134c366a3f`.

Ignored raw evidence is at
`experiments/01_policy_control/results/engineering-p6-residual-dose/`.
