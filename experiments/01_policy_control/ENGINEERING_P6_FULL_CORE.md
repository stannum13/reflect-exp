# Experiment 01 P6 full-core condition breadth

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_P6_FULL_CORE`.

## Outcome

Across the complete 24-condition core timing/move-count domain, P6 residual
.5/slew24 passed 44/48 rollouts, recovered 72/72 events, had zero saturation,
and mean clamp 0.006473. All four misses were clamp-only: seed 20260855 at
20 Hz/two moves for latencies 0, 100, 300, and 700 ms. Their clamp fractions
were 0.01120, 0.01152, 0.01184, and 0.01248. Every 5 Hz and 10 Hz row, every
one-move row, and all 24 seed56 rows passed.

P5 passed 18/48 and recovered 27/72; failures were recovery-only. P2 passed
19/48 and recovered 65/72; it remained predominantly clamp-limited and lost
seven events at 20 Hz. P6 therefore retains the clear breadth advantage, with
a small, mechanically isolated high-rate/two-move clamp boundary.

The core domain contains `fault_id=NONE`; DROP and OUT_OF_ORDER probes are a
separate domain and are not claimed as part of these 144 rollouts.

## Aggregate and rate strata

| Configuration | Working | Recovered | Saturation | Clamp | p95 error m |
|---|---:|---:|---:|---:|---:|
| P6 residual .5/slew24 | 44/48 | 72/72 | 0 | 0.006473 | 0.049980 |
| P5 5/.5/slew12 | 18/48 | 27/72 | 0 | 0.000240 | 0.075072 |
| P2 horizon .1/slew24 | 19/48 | 65/72 | 0 | 0.018953 | 0.059932 |

| Configuration | 5 Hz | 10 Hz | 20 Hz |
|---|---:|---:|---:|
| P6 | 16/16; 24/24 recovered; clamp .004720 | 16/16; 24/24; .005760 | 12/16; 24/24; .008940 |
| P5 | 6/16; 9/24; .000240 | 6/16; 9/24; .000240 | 6/16; 9/24; .000240 |
| P2 | 9/16; 24/24; .010940 | 6/16; 24/24; .018360 | 4/16; 17/24; .027560 |

## Reconstructable boundary exemplars

- P6 passing counterpart: `bundles/P6-res0p5-slew24/P6-core-20-000-2-20260856`.
- P6 narrow failure: `bundles/P6-res0p5-slew24/P6-core-20-000-2-20260855`.
- Highest-clamp P6 failure: `bundles/P6-res0p5-slew24/P6-core-20-700-2-20260855`.

## Evidence identity

- Domain: rates 5/10/20 Hz × latency 0/100/300/700 ms × moves 1/2.
- Fresh seeds: `20260855`, `20260856`.
- Execution Git SHA: `16c93167bca37957079fa615d5e3652738fffcc7`.
- Runtime-code-ledger SHA-256: `a9c799754f9241aa175e1c0da1ae21e8ed395b3e2ecdc13558efa599621a537f`.
- Probe script SHA-256: `2ba503a701e37e1d54fc62c2823acefb98798ce7d3f58944f3cc18ccb8161164`.
- Canonical summary: 65,336,943 bytes, SHA-256
  `2a0b6de0200353c32254b4561939d9d6384400f64a87cae0087c5c70e688922d`.
- Full bundles: 144 directories, 1,008 files, 240,975,555 bytes.
- Complete ignored evidence: 1,010 files, 306,321,633 bytes. Canonical inventory
  SHA-256: `fb77a81dbb7717efb6723ebdfa3d0946c26b9a8dd32a83db0d4611e6bda1503b`.

Ignored raw evidence is at
`experiments/01_policy_control/results/engineering-p6-full-core/`. It binds
every full 500 Hz bundle and file/configuration/scenario/source hash, all
working/nonworking annotations, and 144 valid attempts with no invalids.
