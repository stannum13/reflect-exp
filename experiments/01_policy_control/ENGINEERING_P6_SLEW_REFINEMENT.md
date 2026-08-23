# Experiment 01 P6 full-core slew refinement

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_P6_SLEW_REFINEMENT`.

## Outcome

P6 residual .5 passed all 48 full-core condition/seed cells at each tested
slew: 24, 32, and 48 rad/s. Every setting recovered 72/72 events, produced
zero torque saturation, and had no unsafe or invalid rollout. Higher slew
monotonically widened clamp margin: mean clamp fell from 0.005100 at 24 to
0.003267 at 32 and 0.001773 at 48. Mean p95 error also declined slightly
from 0.051838 to 0.051694 m.

Slew 48 is the selected engineering setting because it has the largest clamp
margin without observed recovery, saturation, error, or safety cost. This is
a parameter-screen selection, not confirmation evidence.

## Full-domain results

| Slew | Working | Recovered | Saturation | Clamp | p95 error m |
|---:|---:|---:|---:|---:|---:|
| 24 | 48/48 | 72/72 | 0 | 0.005100 | 0.051838 |
| 32 | 48/48 | 72/72 | 0 | 0.003267 | 0.051760 |
| 48 | 48/48 | 72/72 | 0 | 0.001773 | 0.051694 |

| Slew | 5 Hz clamp | 10 Hz clamp | 20 Hz clamp |
|---:|---:|---:|---:|
| 24 | 0.003600 | 0.004360 | 0.007340 |
| 32 | 0.002320 | 0.002800 | 0.004680 |
| 48 | 0.001200 | 0.001680 | 0.002440 |

There were zero failure rows across all 144 rollouts.

## Evidence identity

- Domain: all 24 core rate/latency/move-count conditions.
- Fresh seeds: `20260857`, `20260858`.
- Execution Git SHA: `8c6a4ca3e0b4a640db21dfd9f62510cf7629d655`.
- Runtime-code-ledger SHA-256: `a9c799754f9241aa175e1c0da1ae21e8ed395b3e2ecdc13558efa599621a537f`.
- Probe script SHA-256: `da202fae60b2c55bbec22058da43cca728914d3e6c9401b6603ce14967596c80`.
- Canonical summary: 64,875,570 bytes, SHA-256
  `814ff4c3b906720704e1c2f8e80f873c61123ddba7ed0e95475374c4ddd73f0a`.
- Full bundles: 144 directories, 1,008 files, 239,491,111 bytes.
- Complete ignored evidence: 1,010 files, 304,375,042 bytes. Canonical inventory
  SHA-256: `cbb85d8bdcb7b5710bcd465110713e426c7d59dd642839e5c602d089d8a76e65`.

Ignored raw evidence is at
`experiments/01_policy_control/results/engineering-p6-slew-refinement/`.
It binds every full 500 Hz bundle, exact file/configuration/scenario/source
hash, and all 144 valid working annotations.
