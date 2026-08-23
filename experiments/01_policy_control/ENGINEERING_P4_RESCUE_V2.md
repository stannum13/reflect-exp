# Experiment 01 P4 Cartesian-trajectory rescue v2

Status: `PRELIMINARY_MECHANISM_RESCUE_V2`; conclusion: `CANDIDATE_FOR_FORMAL_P4_PILOT`, `NO_PROMOTION`, and `NOT_PARITY_WITH_P6`.

## Supersession and outcome

V2 repairs the exact-joint-limit safety defect in v1: outward joint velocity is now suppressed whether the position reference crosses a limit or is already exactly on it, while inward velocity remains allowed. Exact max/min adversarial tests cover both directions. The v1 raw tree remains immutable and authentic but is superseded and inadmissible for current safety-closed or pilot-candidacy claims.

The complete 488-cell v2 rerun produced zero outcome changes. After excluding only declared nondeterministic wall-clock compute timing, the project-canonical per-rollout dynamics/outcome projection was byte-identical between v1 and v2 (`289d75fc8190210317fea1eb8aa67ef00f4549c7c85106735796b25e7ed43125`). This means the frozen matrix did not exercise the repaired exact-limit boundary; it does not reduce the need for the safety repair.

The smallest corrected arm, P4 with one 500 Hz lookahead tick and joint-velocity feed-forward, produced 88/96 working rollouts and recovered 134/144 displacement events on four untouched evaluation seeds across all 24 core conditions. The legacy P4 path produced 0/96 working and recovered 0/144. The strong P6 residual-0.5/slew-48 comparator remained better at 96/96 working and 144/144 recovery.

| Variant | Working | Recovered | Clamp | Discontinuity | p95 error |
|---|---:|---:|---:|---:|---:|
| P4 lookahead=1, dq on | 88/96 | 134/144 | 0.000000 | 0.000366 | 0.058113 m |
| P4 lookahead=12, dq on | 84/96 | 130/144 | 0.000100 | 0.001027 | 0.057230 m |
| Legacy P4 | 0/96 | 0/144 | 0.000000 | 0.000391 | 0.088363 m |
| P6 residual=.5, slew=48 | 96/96 | 144/144 | 0.002593 | 0.000281 | 0.048236 m |

Paired best-P4-minus-P6 working-rate difference remained -0.083333 (95% bootstrap interval [-0.145833, -0.03125]); recovery-fraction difference remained -0.072917 [-0.125, -0.026042]. At 5 and 10 Hz the best P4 arm was 32/32 working with 48/48 recovered at each rate; at 20 Hz it was 24/32 working with 38/48 recovered. All eight nonworking outcomes were recovery-threshold failures.

## Frozen execution and evidence

The tuning matrix remained lookahead {1, 12, 25, 49} by feed-forward {off, on}, three representative conditions, and four tuning seeds: 96 rollouts. Mechanical selection was written before evaluation and again selected lookahead-1/dq-on and lookahead-12/dq-on. Evaluation retained the untouched four-seed, 24-condition domain for those two arms, legacy P4, and P6: 384 rollouts. Separate fault seeds supplied four DROP and four OUT_OF_ORDER cells; all eight worked and recovered 16/16 events. No rollout was unsafe.

The run executed from isolated commit `4307f6eb30504976d8250d240cb2ae9b1c7026b4`, which contains safety repair `18d03fbdbf0b09d30a4262198d3c15bbd778e190`. Every bundle retains raw 500 Hz observations, actions, references, events, metric inputs, safety and disposition evidence, with source/configuration/scenario/replay hashes. Deterministic annotations retain working and nonworking P4 examples; unavailable legacy-working and P6-nonworking classes remain explicitly `CLASS_NOT_OBSERVED` with denominator 96.

Clean reconstruction revalidated all 488 bundles, selection, annotations, and paired analysis and returned manifest SHA-256 `0a0562b71deb6cf94dac2e1c924a3d4df8ef1ebd8c7ccb25d6231c92b17845aa`. The v2 evidence tree has 3,419 files and 1,115,448,712 bytes with project-canonical inventory SHA-256 `072026fc7897fec69e098dca218036c6489c8a7db576e074a38da94426bd4ece`.

This remains a preliminary, nonconfirmatory engineering screen. Its evaluation domain is consumed and cannot become a later holdout. The justified next step is a preregistered formal pilot that retains P6 as the stronger comparator and explicitly targets the unresolved 20 Hz recovery boundary. No deployment, promotion, or final architecture choice follows from v2.
