# Indicative Twin-Hierarchy Synthesis

## Situation

Two independently completed, frozen 400-case runs (A and B) compare T0–T4 variants of an indicative twin-hierarchy experiment. Each seed-by-mission case is evaluated once per variant, producing matched outcomes.

## Methodology

Success fractions are exact counts over 400 cases per run; uncertainty bars use Wilson 95% intervals. T3−T2 and T4−T3 are paired case-level success differences. Each run uses a deterministic 10,000-draw paired-case bootstrap. The pooled interval samples the two runs as clusters, then 400 matched cases within each selected run; with only two clusters it is transparent descriptive sensitivity analysis, not robust population inference.

Canonical CSV/JSON data and SVG figures are authoritative, byte-stable raw-to-output reconstruction artifacts. The two published PNG figures are frozen, non-authoritative raster companions: their original Pillow rasterizer was not a declared project dependency, so clean reconstruction intentionally does not generate or claim to reproduce them. When the companion files are present in this publication directory, their existing bytes are recorded in `evidence_manifest.json` and `SHA256SUMS`.

## Objective

Assess whether the progressively richer representation, live-belief/history, and reactive-replanning layers coincide with better mission execution in these fixed scenarios.

## Outcome

| Run | T2 success | T3 success | T4 success | T3−T2 | T4−T3 |
|---|---:|---:|---:|---:|---:|
| A | 40.25% | 77.50% | 80.75% | +37.25 pp | +3.25 pp |
| B | 41.25% | 79.00% | 81.00% | +37.75 pp | +2.00 pp |

Pooled matched effects are T3−T2 +37.50 pp (cluster bootstrap 95% [+34.12, +40.88]) and T4−T3 +2.62 pp (95% [+1.38, +4.12]).

## Inference

Across both completed runs, T3 substantially exceeds T2 in matched mission success, and T4 is modestly higher than T3. The same directional pattern occurs in both independent frozen runs. This supports an indicative architectural parallel: richer representation/live-belief/history and reactive replanning are associated with better execution in this benchmark.

## Limits

This is explicitly preliminary engineering evidence from a synthetic, fixed scenario family. It does not establish causal attribution to any individual layer, generalization beyond these missions, or a three-level recovery result. The pooled cluster interval has only two top-level runs. Read `data/`, `data/examples.json`, `evidence_manifest.json`, and the reconstruction script together for traceable detail.
