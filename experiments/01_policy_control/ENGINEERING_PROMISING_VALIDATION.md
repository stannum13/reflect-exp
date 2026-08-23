# Experiment 01 promising-regime untouched-seed validation

Status: `PRELIMINARY_NONCONFIRMATORY_ENGINEERING_PROMISING_VALIDATION`.
This 16-seed validation is descriptive engineering evidence, not pilot or
confirmation evidence.

## Outcome

The earlier 5/6 success did not generalize. Across 16 untouched seeds and
three conditions, P5 at gains 5/.5 and slew 3 passed 16/48 rollouts (0.333;
Wilson 95% interval 0.217–0.475). Raising slew to 6 improved this to 26/48
(0.542; Wilson 0.403–0.674). Both configurations retained zero torque
saturation, but event recovery was only 50/80 and 51/80 respectively.

P5 7.5/.75 slew 6 regressed to 14/48 working (0.292; Wilson 0.182–0.432),
43/80 recovered, and mean saturation 0.088053. The P1 comparator recovered
80/80 and had zero saturation, but remained 0/48 working because every cell
exceeded the clamp ceiling.

Thus P5 5/.5 slew 6 is the best tested regime, but it is not robust enough for
promotion. Its gain over slew 3 is a paired +0.2083 working fraction (10
improvements, zero regressions; descriptive paired-bootstrap 95% interval
+0.1042 to +0.3333). The dominant remaining discriminator is recovery under
slower/multi-displacement conditions, not saturation or clamp.

## Configuration results

Each row has 48 rollouts. Intervals are Wilson score 95% intervals for the
absolute-working fraction.

| Configuration | Working | 95% interval | Recovered | Mean saturation | Mean clamp | Mean p95 error m | Failure-row counts |
|---|---:|---:|---:|---:|---:|---:|---|
| P5 5/.5 slew 3 | 16/48 | [0.217, 0.475] | 50/80 | 0.000000 | 0.008687 | 0.069436 | clamp 13; recovery 22 |
| P5 5/.5 slew 6 | 26/48 | [0.403, 0.674] | 51/80 | 0.000000 | 0.003333 | 0.069407 | recovery 22 |
| P5 7.5/.75 slew 6 | 14/48 | [0.182, 0.432] | 43/80 | 0.088053 | 0.009367 | 0.071767 | saturation 21; clamp 11; recovery 27 |
| P1 5/.5 slew 6 | 0/48 | [0.000, 0.074] | 80/80 | 0.000000 | 0.034220 | 0.048564 | clamp 48 |

## Condition and seed failures

Counts are working rollouts out of 16. Lists contain every nonworking seed.

| Configuration | Condition | Working | Recovered | Failed seeds |
|---|---|---:|---:|---|
| P5 5/.5 slew 3 | 20 Hz/0 ms/1 move | 10/16 | 14/16 | 26, 29, 33, 36, 39, 40 |
| P5 5/.5 slew 3 | 10 Hz/300 ms/2 moves | 5/16 | 23/32 | 26–29, 32–34, 36–37, 39–40 |
| P5 5/.5 slew 3 | 5 Hz/700 ms/2 moves | 1/16 | 13/32 | 26–40 |
| P5 5/.5 slew 6 | 20 Hz/0 ms/1 move | 14/16 | 14/16 | 36, 40 |
| P5 5/.5 slew 6 | 10 Hz/300 ms/2 moves | 10/16 | 23/32 | 27–28, 34, 36–37, 40 |
| P5 5/.5 slew 6 | 5 Hz/700 ms/2 moves | 2/16 | 14/32 | 27–40 |
| P5 7.5/.75 slew 6 | 20 Hz/0 ms/1 move | 3/16 | 10/16 | 26–31, 33–34, 36–40 |
| P5 7.5/.75 slew 6 | 10 Hz/300 ms/2 moves | 7/16 | 18/32 | 26–29, 31, 34, 36–37, 40 |
| P5 7.5/.75 slew 6 | 5 Hz/700 ms/2 moves | 4/16 | 15/32 | 26–31, 34, 36–40 |
| P1 5/.5 slew 6 | all three | 0/16 each | 16/16, 32/32, 32/32 | all 16 seeds (clamp only) |

Seed suffixes above mean full seeds `20260825` through `20260840`.

## Paired descriptive uncertainty

Differences are configuration minus P5 5/.5 slew 3 over the same 48
condition/seed cells. Intervals are percentile intervals from 10,000 paired
bootstrap resamples with fixed analysis seed 20260823.

Exact reconstruction recipe: preserve `probe-summary.json` rollout order
(variant, then seed ascending, then the declared condition order), form each
48-element paired difference vector, initialize NumPy 2.4.6
`default_rng(20260823)` (PCG64), draw one shared index matrix with
`rng.integers(0, 48, size=(10000, 48))`, take each resampled row mean, and
apply `numpy.quantile` at `.025` and `.975` with its default `method="linear"`.
The same index matrix is reused for every comparator and metric.

| Comparator | Δ working fraction (95%) | Δ clamp (95%) | Δ saturation (95%) | Δ p95 error m (95%) |
|---|---:|---:|---:|---:|
| P5 5/.5 slew 6 | +0.2083 [+0.1042,+0.3333] | -0.005353 [-0.005980,-0.004740] | 0 [0,0] | -0.000029 [-0.000052,-0.000006] |
| P5 7.5/.75 slew 6 | -0.0417 [-0.1875,+0.1042] | +0.000680 [-0.002207,+0.003907] | +0.088053 [+0.058987,+0.120147] | +0.002332 [-0.000225,+0.005314] |
| P1 5/.5 slew 6 | -0.3333 [-0.4583,-0.2083] | +0.025533 [+0.021840,+0.029280] | 0 [0,0] | -0.020872 [-0.025051,-0.016833] |

## Reconstructable exemplars

- Working: `bundles/P5-5p0-0p5-slew6p0/P5-core-20-000-1-20260825`
  recovered 1/1, saturation 0, clamp 0.00224, p95 error 0.0474975 m.
- Nonworking: `bundles/P5-5p0-0p5-slew6p0/P5-core-05-700-2-20260840`
  recovered 0/2, saturation 0, clamp 0.00032, p95 error 0.1051033 m;
  its sole failure reason is `RECOVERY_FRACTION_BELOW_0.90`.

## Evidence identity

- Conditions: `core-20-000-1`, `core-10-300-2`, `core-05-700-2`.
- Untouched seeds: `20260825..20260840` inclusive.
- Execution Git SHA: `4cbe0dc662f48983773e0f29f2aae954f3ac53cf`.
- Runtime-code-ledger SHA-256: `a9c799754f9241aa175e1c0da1ae21e8ed395b3e2ecdc13558efa599621a537f`.
- Probe script SHA-256: `cdadd079b94b88bbc6fa1727a3e06487408a2022be8212142d08fc0a34f26f00`.
- Canonical summary: 86,442,742 bytes, SHA-256
  `06b8901208ae85d20fa69d98c6bc82821c956dcd290d272ae6cbcfcf13adb833`.
- Full bundles: 192 directories, 1,344 files, 319,488,595 bytes.
- Complete ignored evidence: 1,346 files, 405,943,484 bytes. SHA-256
  `07a6055017b0aa79fe60ca679b50b66bf5c17b8933a5463ce8199d2d9a93cab6`
  covers the canonical ordered inventory of relative path, bytes, and file hash.

Ignored raw evidence is at
`experiments/01_policy_control/results/engineering-promising-validation/`.
The plot-ready summary binds every full 500 Hz bundle/file hash, exact
configuration/scenario/source ledgers, all 192 valid attempts, every
working/nonworking identity, and each closed failure-reason list. There were
no runtime-invalid attempts.
