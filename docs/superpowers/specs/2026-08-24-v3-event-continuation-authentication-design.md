# V3 Event-Continuation Authentication Design

## Goal

Close the V3 Gate 5/Gate 8 blocker by measuring the lowest sufficient intervention independently for every retained R3 failure event. No outcome seed may run during implementation or qualification resealing.

## Runtime continuation boundary

Each retained failure event carries a canonical, SHA-256-bound snapshot taken immediately before policy intervention. The snapshot closes the complete continuation state: MuJoCo `qpos`, `qvel`, `ctrl`, applied generalized/body forces, and time; world/object, obstacle, dropout, injection, contact, and mission flags; memory facts, ledger, events, and version; policy budget, reobserve index, abort state, and pending attempt; and active command, controller/executor state, command/action/receipt/reset/trajectory history, hold state, and counters.

`run_counterfactual_continuation` restores only this serialized state, verifies its hash and event identity, forces exactly one of `CONTROL`, `MOTION`, or `SEMANTIC`, and advances the preregistered 25-tick continuation window. It returns canonical raw tick evidence, a terminal record, and state/member/trace hashes. Candidate generation never infers clearance from intervention ordering.

## Independent scoring and Gate 8

`score_counterfactual_candidate` lives in `v3_scorer.py` and consumes only the retained event snapshot plus candidate raw evidence. It independently reconstructs transition integrity, safety, domain clearance, valid content progress, and terminal success, then emits a hash-bound score receipt. The lowest sufficient level is the first passing receipt in `CONTROL`, `MOTION`, `SEMANTIC` order.

Each event retains exactly three candidates. Gate 8 recomputes snapshot, member, trace, terminal, and score-receipt hashes and reruns the independent candidate scorer. It rejects forged labels, pass booleans, missing candidates, duplicated levels, shared/non-restored traces, or any raw/member/receipt tamper.

## Testing and evidence

Tests first prove the current implementation fails exact call-count and independent-score requirements. Regression tests cover full snapshot round-trip, dropout two-event to six-candidate expansion, distinct forced behavior, scorer tampering, and Gate 8 recomputation. After source/tests are committed, only calibration qualification is regenerated, reconstructed byte-exactly, archived, and reported. Held-out seeds `20261801..20261810` and `results/hierarchical-recovery-v3` remain untouched.
