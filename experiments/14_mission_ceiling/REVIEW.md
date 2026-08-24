# Exp14 independent evidence review

Reviewed HEAD: `e8b819847970dcf01c0f9fb856c2f7b0226867aa`

Verdict: `REJECTED_EVIDENCE_AUTH`

Disposition: descriptive exploratory raw only. Do not promote Exp14 as qualified
evidence, a semantic-memory result, a lower-loop recovery result, hierarchy-mechanism
causality, mission-space stability, learned-policy evidence, or real-world evidence.
This review makes no changes to experiment code, raw outcomes, derived outcomes, or
the published report.

## Blocking findings

### Critical: qualification does not authenticate evidence semantics or lifecycle

`verify_manifest` is a self-consistency check over the tree it is given
(`experiment.py:384-390`). It does not require the canonical closure schema, status,
source/analysis commits, config hash, matrix hash, 9,216 rows, 12-seed namespace, or
the exact 9,224-entry inventory. Its allowlist applies only to the four immediate
root names, so coherently rehashed nested extras are accepted.

`_derive` consumes the stored `episode["score"]` directly
(`experiment.py:434-440`). `reconstruct` copies raw and closure, derives from those
stored scores, writes another self-consistent manifest, and never replays the ledger,
independently reconstructs terminal state, independently scores completion/safety/
progress, authenticates Git objects, or byte-compares against a canonical result
(`experiment.py:499-508`).

The read-only audit used an isolated temporary root and performed one coherent
attack: replace the declared source and analysis commits, config and matrix hashes,
matrix row count, and seed namespace; flip a ledger acceptance; add fabricated
derived data and `raw/EXTRA_UNALLOWLISTED.txt`; then rewrite the manifest. The
published `verify_manifest` accepted the attacked root. Published `reconstruct`
also accepted it and preserved the corrupt ledger, fake closure, and nested extra.
A symlink attack was correctly rejected. This demonstrates that the current
canonical bytes can be descriptively inspected, but the qualification contract
cannot authenticate them against coherent substitution.

### Important: `lower_recovery` has no distinct recovery behavior

For non-open-loop agents, `run_episode` recomputes a fresh plan from the same full
state (`experiment.py:299-303`). A rejected action becomes a retry label only for
`lower_recovery` and `full_hierarchy` (`experiment.py:304-306`); no alternate
lower-loop recovery action is selected.

Independent pairing of all live-memory and lower-recovery episodes found:

- 2,304/2,304 identical action sequences;
- 2,304/2,304 identical acceptance/reason sequences;
- 2,304/2,304 identical terminal states; and
- 2,304/2,304 scores identical after excluding retry count and action cost.

The report acknowledges that the agents choose the same fresh plan and differ mainly
in retry accounting (`RESULT.md:54-58`), but calling these data a behavioral recovery
comparison would still be unsupported.

### Important: graph, sample, and shard evidence is incomplete

The canonical roots contain 2,304 building-edge records in `raw/graphs.jsonl` and
numerical episode/analysis tables. They contain no SVG, PNG, plotted data table,
layout, style, or chart metadata sufficient to reproduce a published visualization
with visual fidelity. Thus the requested graph evidence is not present as a plotted
or fully specified reconstructable artifact.

`derived/samples.json` contains two summary rows and episode identifiers. It does
not contain annotated working/nonworking traces or explanations of the transition
that produced success or failure, although the corresponding full raw ledgers can
be located by ID.

`ANALYSIS_SUPERSESSION.json:13` declares `results/shard-04-analysis` canonical, and
`RESULT.md:76-77` asserts that this one-seed shard reports effective n=1 with no
interval. That path is absent at reviewed HEAD, as are the invalid shard and
qualification attempts named in `ANALYSIS_SUPERSESSION.json:6-11`. The implementation
and unit test correctly return no interval for n=1 (`experiment.py:393-397`), but the
claimed actual shard and supersession bytes cannot be authenticated.

### Important: preregistered mission heterogeneity was omitted

The preregistration promises heterogeneity by mission, horizon, and perturbation
axis (`PREREGISTRATION.md:28-30`). Derivation emits horizon-by-variant cells only and
does not stratify by mission (`experiment.py:462-468`).

## Defensible exploratory observations

The source/config/preregistration commit is
`23a300fc643da1bc1c65a3bab352448e20b3f8a1`; the seed-cluster analysis correction is
its direct child `d65bb16277158cd08df086a0a994a7abf5a9e0db`; reviewed evidence HEAD is
the correction's direct child `e8b819847970dcf01c0f9fb856c2f7b0226867aa`.
The correction changes bootstrap analysis and tests, not the simulator or controller
outcomes.

The canonical matrix is exactly 9,216 unique rows: 12 held-out seeds x 6 missions x
4 horizons x 8 variants x 4 agents. Its independently recomputed SHA-256 is
`14832be748907356bd215bd3ad81216573fc366affcfb41178bd182dadbfa848`,
matching the closure. The config hash at the source commit is
`f4464d80d28bb6f58f4c8d5922d841dc2aeb14a2bd12fb292d11083430da2523`,
also matching the closure.

Independent replay covered all 9,216 episode files and 80,070 state transitions.
There were zero mismatches in scenario construction, state-before, scheduled event,
action acceptance/reason, observation-after, retry/replan record, terminal flag,
terminal state, or independently recomputed score.

Independent terminal-state scoring reproduced:

| Agent | Completed | Safe | Mean progress |
|---|---:|---:|---:|
| Open loop | 740/2,304 | 2,016/2,304 | 0.491609 |
| Live memory | 990/2,304 | 2,016/2,304 | 0.608218 |
| Lower recovery | 990/2,304 | 2,016/2,304 | 0.608218 |
| Full hierarchy | 1,170/2,304 | 2,304/2,304 | 0.665509 |

Independent 10,000-draw paired seed-cluster bootstraps reproduced:

| Contrast | Estimate | 95% bootstrap interval | Effective n |
|---|---:|---:|---:|
| Full - open | 0.1866319 | [0.1822917, 0.1931424] | 12 seeds |
| Full - live | 0.0781250 | [0.0781250, 0.0781250] | 12 seeds |
| Full - lower | 0.0781250 | [0.0781250, 0.0781250] | 12 seeds |

The zero-width intervals reflect identical seed-aggregate differences in this
deterministic screen, not population certainty. Seeds mainly alter generated
topology. The planner receives the full ground-truth `Scenario` and building state,
the paraphrase condition is directly branched on (`experiment.py:249-251`), and full
hierarchy is directly granted safety/lock handling (`experiment.py:252-258`). These
are deterministic mission-logic policy observations only; they are not evidence for
learned semantic understanding, memory mechanisms, or hierarchy causality.

Both published manifests currently contain 9,224 entries (9,221 files and 3
directories), have SHA-256
`89e4edb50d7945d5aba33f4630d7227f839a28507a43ac2946281fafbd033e5a`,
and their listed qualification/reconstruction bytes match. This is a descriptive
fact about current HEAD, not a substitute for the missing authenticated validator.

## Verification receipts

- Exact reviewed HEAD: `e8b819847970dcf01c0f9fb856c2f7b0226867aa`.
- Focused tests: `10 passed in 0.17s`.
- Repository test suite: `645 passed in 109.42s`.
- Ruff: `All checks passed!` for Exp14 source and tests.
- Pre-review and post-review code/evidence status: clean; only this review artifact
  is authorized for the review commit.

Final decision: keep Exp14 parked as `REJECTED_EVIDENCE_AUTH`. Its replayed raw data
may be cited only as bounded descriptive exploration of these hand-coded deterministic
mission-logic policies. No result should be promoted as qualified evidence or as a
causal mechanism claim.
