# Hierarchical Recovery Grounded V2

Status: `COMPLETE_DOES_NOT_SUPPORT_WITH_IMPLEMENTATION_CONCERNS`
Decision: `DOES_NOT_SUPPORT_GROUNDED_LAYER_MATCHED_HIERARCHY`
Frozen source: `a70b28a164b2406588ac8bcb7ad66beaf45a9a6e`

## Outcome

The exact preregistered matrix completed: 320 primary P6 episodes and 40 R3 P4 sensitivity episodes, with zero invalid attempts. The independent post-episode scorer's positive-control audit produced a nonzero count for each of unsafe, forbidden, stale, collision, invalid-action, and retry-loop corruption.

| Architecture | Anchor | Control | Motion | Semantic | Primary total |
|---|---:|---:|---:|---:|---:|
| R0 | 20/20 | 20/20 | 0/20 | 0/20 | 40/80 |
| R1 | 20/20 | 20/20 | 20/20 | 10/20 | 70/80 |
| R2 | 20/20 | 20/20 | 20/20 | 10/20 | 70/80 |
| R3 | 20/20 | 20/20 | 20/20 | 10/20 | 70/80 |

Gates 2–7 passed mechanically. Gate 1 failed because R3's independent scorer found 324 forbidden-action samples in the semantic domain. The authoritative outcome is therefore `DOES_NOT_SUPPORT_GROUNDED_LAYER_MATCHED_HIERARCHY`. No post-freeze source or configuration change was made.

All six disturbed scenarios had 10/10 distinct parameter hashes. Every local retry/replan qualification advanced MuJoCo by 25 ticks before re-observation. Exact action, trajectory, memory-event, observation, realization, trace, scorer, and terminal bytes are retained per episode.

## Evidence

- Freeze: [freeze.json](../../results/hierarchical-recovery-grounded-v2/freeze.json)
- Raw manifest: [manifest.json](../../results/hierarchical-recovery-grounded-v2/raw/manifest.json)
- Decision: [decision.json](../../results/hierarchical-recovery-grounded-v2/derived/decision.json)
- Graph data: [success-by-domain.csv](../../results/hierarchical-recovery-grounded-v2/derived/success-by-domain.csv)
- Figure: [success-by-domain.svg](../../results/hierarchical-recovery-grounded-v2/derived/success-by-domain.svg)
- Paired bootstrap: [paired-bootstrap.json](../../results/hierarchical-recovery-grounded-v2/derived/paired-bootstrap.json)

A clean reconstruction regenerated all seven derived files byte-for-byte from the immutable raw episode evidence.

## Evidence identities

- Freeze SHA-256: `9bb02098e896b6d955a60752390d87bb8d6b7285afbdbe4736ef951e6d9883ff`
- Raw manifest SHA-256: `f77e8448688791c038e7f95b89a206c25037f8d715213e2dd03cc90566b1376a`
- Derived manifest SHA-256: `fd92065fb88324a5a6f2b1b5dcdbeb3d60d98c60cdf33ed33becc0049828024e`

## Concerns

The frozen run exposed more than an unfavorable Gate 1 result. The retained traces contain invalid-action samples during motion and semantic recovery, while terminal success did not universally require the independent invalid-action count to be zero. Also, the implementation's intervention-level bookkeeping used the external scenario family after observable generation rather than deriving the selected level exclusively from observable content. Those facts prevent promotion of this V2 run as definitive grounded scientific evidence even though its authoritative mechanical decision is negative. The evidence is retained as a nonworking sample; it must not be used to support the hierarchy claim.
