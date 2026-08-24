# Exp16 V1 final scientific audit

Date: 2026-08-24

Evidence HEAD: `2ae90cf4c37704e14ae609512dc5f65c49d98f72`

Frozen outcome source: `2c0d69dc0fb387730864c9f51cf8315dabd73598`

Portable pack: `reports/evidence/exp16-route-boundary-replication-v1`

Pack-manifest SHA-256: `d32e2b8ffaad8cb3c07f64f12e597d4790d1eb4b528ecd68f6bf7e83898bf734`

## Verdict

**APPROVE `SUPPORTS_BOUNDED_DIRECT_HIERARCHY_REPLICATION`.**

This disposition is warranted for the exact preregistered MuJoCo experiment:
R3 preserved P6 success and progress relative to the fixed best simpler
comparator R2, while reducing total recovery wakes, across the registered
families, severities, and fresh seed clusters. All registered gates pass, the
540-cell disposition closure is complete, no execution is invalid, one natural
typed route-unavailable outcome followed the preregistered safe-abort boundary,
and the portable statistics and figures reconstruct byte-for-byte.

This is a bounded direct replication claim about these scripted recovery
architectures and controllers in this simulator. It is not evidence for a
lowest-sufficient causal recovery layer, native pi0.5 semantic planning or
memory, a learned VLA hierarchy, real-robot performance, or generalization
beyond the registered mission/disturbance space.

Independent review found zero Critical defects. It found one Important
publication-wording defect and one Minor graph-presentation caveat. Neither
changes a registered value or gate, so neither invalidates the formal
disposition; both require explicit correction in any use of the pack:

1. **Important wording defect:** `derived/REPORT.md` and
   `derived/report.json` say that selected full
   "working/nonworking episodes are portable." That phrase is inaccurate. The
   frozen sample population is PRIMARY/P6/R3, whose 116 complete episodes were
   116/116 successful with zero safety-composite positives. Therefore the pack
   correctly contains one selected working raw episode and an explicit
   `ABSENT` nonworking annotation, but no selected nonworking raw directory.
   P4/R3 sensitivity failures exist in the disposition closure and local raw
   root, but are outside the registered sample population and must not be
   substituted. The authoritative wording is: **one selected working episode
   is portable; the registered nonworking category is explicitly absent.**
2. **Minor presentation caveat:** standalone graphs omit numeric y-axis ticks,
   and the family graph abbreviates
   family names. They must travel with `derived/graphs/plot-data.csv`,
   `derived/graphs/style.json`, `derived/report.json`, and this audit. The
   authenticated data, SVG geometry, PNG bytes, and renderer metadata remain
   sufficient for faithful restyling.

## Lifecycle and authenticated closure

- Linear authority chain: exact source `2c0d69d` -> independent sole-file
  source approval `ae79be4` -> freeze `5dd0327` -> full preflight receipt
  `741ef9f` -> first-50 checkpoint `bfd4bc2` -> independent sole-file
  continuation approval `22aae71` -> the two preregistered ministerial hash
  bindings `c349a9c` -> portable pack `2ae90cf`.
- The freeze SHA-256 is
  `66efee87fc163d45412e05b6474a38704f56f476a4cd894b1815972769e27097`.
  Its 36-member source closure is bound to the exact source commit. The only
  later closure-code change replaces the two preregistered `UNSEALED` constants
  with the freeze and raw-inventory hashes; run, scorer, resampling, gates,
  sample selection, graphs, and narrative-generation logic are unchanged.
- Architecture-blind preflight sealed all 540 cells before outcomes: 524
  `READY`, 16 `NOT_RUN`, and zero `INVALID_PREFLIGHT`. The 16 exclusions are
  four architecture-independent `IK_ERROR_EXCEEDS_TOLERANCE` realizations,
  each repeated symmetrically across R0/R1/R2/R3 with the same parameter hash.
- First-50 execution paused with exactly 50 `COMPLETE` dispositions, zero
  invalids, and no release file. Continuation approval binds the source,
  freeze, and exact disposition-inventory SHA-256 before cell 51.
- Final closure: 540 dispositions = 524 `COMPLETE` + 16 preregistered
  `NOT_RUN` + 0 `INVALID_EXECUTION`. There are 524 matching complete-episode
  manifests.
- Local raw inventory SHA-256 is
  `1daf3b5e3747c80c2587d2b6b98e32ba81461395784e91799a6a7af468655acf`,
  binding 13,663 member files and 2,042,122,299 bytes. The tracked copy is
  byte-identical to the local inventory.
- Portable closure has 1,110 non-self manifest entries totaling 22,629,376
  bytes. Exact allowlisting rejects extra, missing, substituted, malformed, or
  symlinked members. Every compact disposition, complete manifest, preflight
  file, and selected raw member is hash-bound through both the pack manifest
  and local raw inventory.
- Fresh compact verification returned `PASS` and rebuilt every derived byte:
  summary/family/failure tables, 130 seed-cluster rows, 10,000 bootstrap rows,
  plot data, style metadata, four SVGs, and four 760x420 PNGs.

## Independent numerical check

Primary P6 complete-cell summaries independently recomputed from the 540
canonical dispositions are:

| Architecture | n | Mission success | Safety-violation rate | Mean progress | Mean wakes |
|---|---:|---:|---:|---:|---:|
| R0 | 116 | 0.327586 | 0.000000 | 0.379991 | 1.672414 |
| R1 | 116 | 0.758621 | 0.000000 | 0.768898 | 0.939655 |
| R2 | 116 | 1.000000 | 0.000000 | 0.999997913 | 1.784483 |
| R3 | 116 | 1.000000 | 0.000000 | 0.999997903 | 1.112069 |

Here `safety_composite=true` means at least one violation, so the table reports
the safety-violation rate, not a positive safety score.

Equal-seed R3-minus-comparator effects use the actual ten paired seed clusters
and the registered 10,000 PCG64 draws:

| Comparator | Metric | Estimate | 95% interval |
|---|---|---:|---:|
| R0 | success | +0.673333 | [+0.666667, +0.683333] |
| R0 | safety violation | 0.000000 | [0.000000, 0.000000] |
| R0 | progress | +0.621158 | [+0.612152, +0.633112] |
| R0 | total wakes | -0.561667 | [-0.585000, -0.535000] |
| R1 | success | +0.240000 | [+0.205000, +0.265000] |
| R1 | safety violation | 0.000000 | [0.000000, 0.000000] |
| R1 | progress | +0.229780 | [+0.195756, +0.254022] |
| R1 | total wakes | +0.171667 | [+0.140000, +0.203333] |
| R2 | success | 0.000000 | [0.000000, 0.000000] |
| R2 | safety violation | 0.000000 | [0.000000, 0.000000] |
| R2 | progress | -0.000000007 | [-0.000000043, +0.000000036] |
| R2 | total wakes | -0.673333 | [-0.706667, -0.646667] |

All registered primary `n_eff=10` checks pass. Success lower bounds exceed the
`-0.10` margin, safety-violation upper bounds are below `+0.10`, progress lower
bounds exceed `-0.05`, and the R3-minus-R2 wake upper bound is strictly below
zero. Every R3 family/severity success rate is 1.0, so the worst observed
R3-minus-R2 family/severity difference is 0.0, above the `-0.20` gate.

The P4-minus-P6 R3 sensitivity has the preregistered five paired clusters:
success `-0.350000` with interval `[-0.400000,-0.300000]`, and progress
`-0.300132` with interval `[-0.343539,-0.257236]`. P4/R3 completed 60 cells,
with success 0.65 and safety-violation rate 0.05. This is strong controller
sensitivity inside the registered simulator; it is not evidence that P4 is a
general baseline or that P6 will dominate outside this matrix.

## Natural typed route-unavailable boundary

The boundary was exercised naturally once, in
`exp16v1-P4-R3-motion-path-infeasible-high-20262405`. Its retained decision at
tick 713 is exactly one `SAFE_ABORT` with reason
`MOTION_PLANNER_NO_ROUTE`; `budget_after` equals `budget_before`. The scorer
sealed the cell as `COMPLETE`, `terminal=FAILURE`, `mission_success=false`,
`safety_composite=false`, and `aborts=1`. All 2,412 later action-envelope rows
are mode `HOLD` with reason `SAFE_ABORT`. The disposition, episode manifest,
decision trace, and full local raw members are inventory-bound. Thus the event
is a scored task outcome rather than an infrastructure exception, exactly as
preregistered.

## Sample and graph evidence

- The deterministic annotation selects
  `exp16v1-P6-R3-control-dropout-high-20262401` as the first lexicographic
  working PRIMARY/P6/R3 row: success true, safety violation false, progress
  `0.999995262`. Its complete raw episode is included and hash-bound.
- Nonworking PRIMARY/P6/R3 is honestly `ABSENT` because that population is
  116/116 successful and 0/116 safety-positive. This is acceptable under the
  frozen selection rule and prevents post-outcome substitution. It does not
  satisfy a request for a portable raw failure example; the natural P4/R3
  route-abort episode is available in the authenticated local raw root but is
  not copied into the compact selected-sample subtree.
- `plot-data.csv` contains all 26 plotted values; `style.json` fixes canvas,
  renderer, font, and colors. Deterministic reconstruction reproduces the four
  SVG and PNG pairs byte-for-byte, so later thematic reformatting can preserve
  the exact values.

## Approved and forbidden claims

Approved wording:

> In the preregistered Exp16 MuJoCo matrix, the P6 R3 layer-matched recovery
> architecture replicated bounded direct support: it matched the fixed R2
> comparator on success and progress while using fewer total recovery wakes,
> with all registered uncertainty, heterogeneity, lifecycle, and evidence gates
> passing.

Forbidden inferences include:

- that R3 identifies the causal-lowest or lowest-sufficient recovery layer;
- that pi0.5 performed semantic planning, semantic-memory construction,
  memory updates, or hierarchical replanning in this experiment;
- that any learned VLA was evaluated as the semantic layer here;
- that the result demonstrates real-robot safety, manipulation performance, or
  firmware/MPC/PID efficacy;
- that it generalizes across robots, mission spaces, prompts, scenes, materials,
  glass/transparent objects, controllers, or untested disturbances;
- that 10,000 bootstrap draws are 10,000 independent experiments (the primary
  evidence count is ten paired seed clusters, and sensitivity is five); or
- that absence of a nonworking PRIMARY/P6/R3 sample proves failure is impossible.

## Verification record

- Compact verifier: `PASS`; dispositions 524/16/0; exact reconstruction.
- Independent raw-row recomputation: all summaries, effects, intervals,
  sensitivity results, heterogeneity minimum, and gate decisions match.
- Exp16 tests: `41 passed in 118.58s`.
- Relevant lint: `All checks passed!`; `git diff --check` clean before this
  audit artifact was authored.
