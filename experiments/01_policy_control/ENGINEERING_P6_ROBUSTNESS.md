# Experiment 01 P6 untouched-seed robustness replication

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_P6_ROBUSTNESS`.

## Outcome

P6 residual .5/slew24 fully replicated on eight untouched seeds: 24/24
absolute-working rollouts (Wilson 95% interval 0.862–1.000), 40/40 recovered
events, zero saturation, and mean clamp 0.005973. Every condition/seed cell
passed, including all eight 5 Hz/700 ms/two-move cells.

P5 5/.5/slew12 passed 10/24 (interval 0.245–0.612) and recovered 21/40.
It passed 7/8 fast cells, 3/8 mid cells, and 0/8 slow cells. P2 horizon
.1/slew24 passed 8/24 (interval 0.180–0.533), recovered 38/40, and passed
all fast cells; every mid/slow cell remained clamp-limited.

This rejects the prior P6 6/6 result being merely a two-seed artifact across
the selected three-condition domain. It also establishes a clear distinction:
P6 combines full recovery with an admissible reference stream, P5 is
recovery-limited, and P2 is clamp-limited.

## Configuration and stress strata

| Configuration | Working | Recovered | Saturation | Clamp | p95 error m |
|---|---:|---:|---:|---:|---:|
| P6 residual .5/slew24 | 24/24 | 40/40 | 0 | 0.005973 | 0.045766 |
| P5 5/.5/slew12 | 10/24 | 21/40 | 0 | 0.000360 | 0.071303 |
| P2 horizon .1/slew24 | 8/24 | 38/40 | 0 | 0.018013 | 0.060634 |

| Configuration | 20 Hz/0 ms/1 move | 10 Hz/300 ms/2 moves | 5 Hz/700 ms/2 moves |
|---|---:|---:|---:|
| P6 residual .5/slew24 | 8/8; 8/8 recovered | 8/8; 16/16 | 8/8; 16/16 |
| P5 5/.5/slew12 | 7/8; 7/8 | 3/8; 9/16 | 0/8; 5/16 |
| P2 horizon .1/slew24 | 8/8; 8/8 | 0/8; 16/16 | 0/8; 14/16 |

P5's sole fast failure was seed 20260849. Its mid failures were seeds 47,
49, 51, 52, and 54; all eight slow seeds failed recovery. P2's two missed
events were slow-condition seeds 48 and 53; all 16 mid/slow rows also failed
the clamp gate. P6 has no failure seed or failure reason in this run.

## Reconstructable exemplars

- P6 fast working: `bundles/P6-res0p5-slew24/P6-core-20-000-1-20260847`.
- P6 slow working: `bundles/P6-res0p5-slew24/P6-core-05-700-2-20260854`.
- P5 slow nonworking: `bundles/P5-control-slew12/P5-core-05-700-2-20260854`.
- P2 slow nonworking: `bundles/P2-h0p1-slew24/P2-core-05-700-2-20260853`.

## Evidence identity

- Untouched seeds: `20260847..20260854` inclusive.
- Execution Git SHA: `dbc88b567e4d38f5386e02379fd765e10dbecf74`.
- Runtime-code-ledger SHA-256: `a9c799754f9241aa175e1c0da1ae21e8ed395b3e2ecdc13558efa599621a537f`.
- Probe script SHA-256: `74183eada18b673f1eb1f167d431eedc6325f0e40bb5c7a7d3e1746292b54924`.
- Canonical summary: 32,447,928 bytes, SHA-256
  `30f3d7cdcaee063b126daa36a4c73e8aa1db3331d3fad1b707a231d0ea6dc6a3`.
- Full bundles: 72 directories, 504 files, 120,110,173 bytes.
- Complete ignored evidence: 506 files, 152,568,171 bytes. Canonical inventory
  SHA-256: `1e026a337c679740ddb71679e6c12db2bd2332a4b0a5b6074fcdc4839cfa4dc6`.

Ignored raw evidence is at
`experiments/01_policy_control/results/engineering-p6-robustness/`. It binds
every full 500 Hz bundle and file/configuration/scenario/source hash, all
working/nonworking annotations, and 72 valid attempts with no invalids.
