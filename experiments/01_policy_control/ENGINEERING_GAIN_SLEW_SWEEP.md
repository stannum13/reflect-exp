# Experiment 01 engineering gain × slew sweep

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_GAIN_SLEW_SWEEP`.
This is a descriptive engineering discriminator and must not be pooled with
the preregistered pilot or confirmation study.

## Outcome

The sweep completed 144 real MuJoCo 3.12.0 rollouts: P1 and P5 at four
common PD gains and three reference-slew limits, over the same three core
conditions and two seeds. P5 retained MPC smoothness `0.02`. Every full
bundle validated, all 240 target-displacement events are retained, and no
rollout was unsafe.

The hypothesis is supported for P5. At gains 5/.5, raising reference slew
from 1.5 to 3.0 rad/s reduced mean clamp fraction from 0.020160 to 0.006080,
kept torque saturation at zero, preserved aggregate recovery at 9/10, and
made 5/6 rollouts absolutely working. Slew 6.0 further reduced mean clamp to
0.002187 with the same saturation, recovery, and 5/6 working count. The sole
failure at both higher slews was the same `core-05-700-2`, seed 20260824
rollout, which recovered only one of two displacement events.

P5 at 7.5/.75 shows the same tradeoff less strongly. Slew 6.0 reduced mean
clamp from 0.048267 to 0.005920 and mean saturation from 0.024373 to 0.021173
without changing aggregate recovery of 9/10; 4/6 rollouts passed absolutely.
One remaining failure was clamp (0.013760) and one was recovery (1/2).

P1 is a useful boundary. Gains 5/.5 and 7.5/.75 eliminated or nearly
eliminated saturation and preserved 10/10 recovery at every slew, while
higher slew reduced clamp in every paired cell. Yet even at slew 6.0 its
mean clamp remained 0.032960 and 0.031840 respectively, and all P1 rollouts
failed the 0.01 clamp ceiling. In total, 16/144 rollouts passed the full
absolute rule, all from P5 at gains 5/.5 or 7.5/.75.

## Aggregate rows

Each row contains six rollouts. `Working` is the number satisfying the full
absolute rule; `Recovered` aggregates events over those six rollouts.

| Stack | Gain | Slew rad/s | Working | Recovered | Mean saturation | Mean clamp | Mean p95 error m |
|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | 5/.5 | 1.5 | 0/6 | 10/10 | 0.000000 | 0.168747 | 0.054477 |
| P1 | 5/.5 | 3.0 | 0/6 | 10/10 | 0.000000 | 0.075893 | 0.052204 |
| P1 | 5/.5 | 6.0 | 0/6 | 10/10 | 0.000000 | 0.032960 | 0.049881 |
| P1 | 7.5/.75 | 1.5 | 0/6 | 10/10 | 0.002347 | 0.169653 | 0.052586 |
| P1 | 7.5/.75 | 3.0 | 0/6 | 10/10 | 0.002293 | 0.073973 | 0.049638 |
| P1 | 7.5/.75 | 6.0 | 0/6 | 10/10 | 0.002453 | 0.031840 | 0.046725 |
| P1 | 10/1 | 1.5 | 0/6 | 10/10 | 0.498027 | 0.646667 | 0.062417 |
| P1 | 10/1 | 3.0 | 0/6 | 10/10 | 0.515093 | 0.374080 | 0.061446 |
| P1 | 10/1 | 6.0 | 0/6 | 10/10 | 0.541493 | 0.181067 | 0.061233 |
| P1 | 15/1.5 | 1.5 | 0/6 | 4/10 | 0.664480 | 0.846293 | 0.085213 |
| P1 | 15/1.5 | 3.0 | 0/6 | 6/10 | 0.730987 | 0.648213 | 0.082133 |
| P1 | 15/1.5 | 6.0 | 0/6 | 6/10 | 0.739893 | 0.366240 | 0.079963 |
| P5 | 5/.5 | 1.5 | 1/6 | 9/10 | 0.000000 | 0.020160 | 0.060298 |
| P5 | 5/.5 | 3.0 | 5/6 | 9/10 | 0.000000 | 0.006080 | 0.060228 |
| P5 | 5/.5 | 6.0 | 5/6 | 9/10 | 0.000000 | 0.002187 | 0.060131 |
| P5 | 7.5/.75 | 1.5 | 0/6 | 9/10 | 0.024373 | 0.048267 | 0.060483 |
| P5 | 7.5/.75 | 3.0 | 1/6 | 9/10 | 0.022187 | 0.015787 | 0.060413 |
| P5 | 7.5/.75 | 6.0 | 4/6 | 9/10 | 0.021173 | 0.005920 | 0.060354 |
| P5 | 10/1 | 1.5 | 0/6 | 9/10 | 0.107733 | 0.080000 | 0.051909 |
| P5 | 10/1 | 3.0 | 0/6 | 9/10 | 0.104320 | 0.028480 | 0.052042 |
| P5 | 10/1 | 6.0 | 0/6 | 9/10 | 0.105813 | 0.011520 | 0.051909 |
| P5 | 15/1.5 | 1.5 | 0/6 | 7/10 | 0.428587 | 0.144640 | 0.043314 |
| P5 | 15/1.5 | 3.0 | 0/6 | 7/10 | 0.381120 | 0.062507 | 0.044145 |
| P5 | 15/1.5 | 6.0 | 0/6 | 8/10 | 0.423893 | 0.022773 | 0.043415 |

## Paired slew tradeoffs

Values are higher-slew minus 1.5 rad/s means over the exact same six
condition/seed pairs. `Δ recovered` is the aggregate event-count change.

| Stack | Gain | Slew | Δ saturation | Δ clamp | Δ recovered |
|---|---:|---:|---:|---:|---:|
| P1 | 5/.5 | 3.0 | +0.000000 | -0.092853 | 0 |
| P1 | 5/.5 | 6.0 | +0.000000 | -0.135787 | 0 |
| P1 | 7.5/.75 | 3.0 | -0.000053 | -0.095680 | 0 |
| P1 | 7.5/.75 | 6.0 | +0.000107 | -0.137813 | 0 |
| P1 | 10/1 | 3.0 | +0.017067 | -0.272587 | 0 |
| P1 | 10/1 | 6.0 | +0.043467 | -0.465600 | 0 |
| P1 | 15/1.5 | 3.0 | +0.066507 | -0.198080 | +2 |
| P1 | 15/1.5 | 6.0 | +0.075413 | -0.480053 | +2 |
| P5 | 5/.5 | 3.0 | +0.000000 | -0.014080 | 0 |
| P5 | 5/.5 | 6.0 | +0.000000 | -0.017973 | 0 |
| P5 | 7.5/.75 | 3.0 | -0.002187 | -0.032480 | 0 |
| P5 | 7.5/.75 | 6.0 | -0.003200 | -0.042347 | 0 |
| P5 | 10/1 | 3.0 | -0.003413 | -0.051520 | 0 |
| P5 | 10/1 | 6.0 | -0.001920 | -0.068480 | 0 |
| P5 | 15/1.5 | 3.0 | -0.047467 | -0.082133 | 0 |
| P5 | 15/1.5 | 6.0 | -0.004693 | -0.121867 | +1 |

The summary retains the unrounded condition/seed identities and metrics used
to recompute all six individual differences behind every row.

## Exact design and evidence

- Gains: `(5,.5)`, `(7.5,.75)`, `(10,1)`, `(15,1.5)`.
- Reference slew: `1.5`, `3.0`, `6.0` rad/s.
- Conditions: `core-20-000-1`, `core-10-300-2`, `core-05-700-2`.
- Seeds: `20260823`, `20260824`.
- Execution interval: `2026-08-23T01:48:00.926653+00:00` through
  `2026-08-23T01:55:59.968280+00:00`.
- Execution Git SHA: `0101d8201d5c6fccae4392e51344002d1b18db76`.
- Runtime-code-ledger SHA-256: `a9c799754f9241aa175e1c0da1ae21e8ed395b3e2ecdc13558efa599621a537f`.
- Probe script SHA-256: `14fb0dface25c03be0eec8f4da010cad3957c30fa0cf8f5a65ef3efcc00a8f87`.
- Runtime: Python 3.11.13, NumPy 2.4.6, MuJoCo 3.12.0, Darwin arm64;
  the simulation-only guard passed and MuJoCo rendering was disabled.
- Full bundles: 144 directories, 1,008 files, 238,892,286 bytes.
- Canonical summary: 64,354,689 bytes, SHA-256
  `feb2cb0f9c9db79c6ee269fe5fc0c49e3f004a0f1f60397d3e260c3ad7e279f9`.
- Complete ignored evidence root: 1,011 files, 303,260,594 bytes. SHA-256
  `da328aa58790c29cd26c4fca95d4a83dacc027ca26d537705719d9c73be992c5`
  is over the canonical ordered inventory of relative path, byte count, and
  constituent-file SHA-256.

Ignored raw evidence is at
`experiments/01_policy_control/results/engineering-gain-slew-sweep/`.
`probe-summary.json` binds every bundle-relative path and constituent file
size/hash, complete scalar and raw 500 Hz metrics, exact conditions,
configuration and scenario objects/hashes, seeds, controller values,
dependency versions, source-code ledger, and disposition. Tables, paired
analyses, plots, and images are reconstructable without this Markdown table.

## Invalid attempts and failure annotations

The first invocation stopped before any rollout because its preflight
mistakenly required the runtime's complete 24-condition domain to equal the
three selected condition IDs. The create-only `preflight-invalid.json`
records its exact argv, exit status, error, zero-bundle count, time, and probe
script hash: 431 bytes, SHA-256
`6d091ede716f425376f48ac21aee2ec89e1b32f63278bec2121dcb5d0e8b3e19`.
It contributes no physics sample and is excluded from all analysis.

The successful runner then validated that all three requested IDs belonged
to the closed runtime domain and imposed their requested order. Its attempt
ledger contains 144 `VALID` outcomes and zero runtime-invalid attempts.
Every nonworking rollout carries its exact closed failure-reason list. The
aggregate table reports all configurations; the raw summary retains every
working and nonworking condition/seed identity and unrounded metric.

## Interpretation boundary

This is two-seed descriptive engineering evidence, not a confirmatory
estimate or a basis for changing preregistered gates. It identifies P5 at
gains 5/.5 with reference slew 3.0 or 6.0 as the first tested regime with
replicated absolute success in five of six cells. The repeated slow-condition
failure on seed 20260824 remains a concrete robustness discriminator before
any pilot-controller decision.
