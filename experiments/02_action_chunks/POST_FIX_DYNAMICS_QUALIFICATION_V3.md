# Experiment 02 post-fix dynamics qualification v3

Status: `QUALIFICATION_ONLY`; `sealed_pilot=false`; no PRIMARY, promotion, or runtime-authority claim.

## Result

The post-audit adapter and broker executed 50 MuJoCo cells: seeds 20 and 21, protocols A--G, no-fault latencies 25/75/150 ticks, plus the frozen DROP, PAUSE, ALTERNATIVE, and DISCONTINUITY probes selected by the qualification runner. Every cell retained 3,125 telemetry ticks, its complete canonical broker/event history, one terminal-empty event, and a finite outcome.

The observed qualification labels were 8 `WORKING` and 42 `NONWORKING`:

| Protocol | Cells | Working | Nonworking | Hold-tick range |
|---|---:|---:|---:|---:|
| A | 8 | 6 | 2 | 3000--3125 |
| B | 6 | 0 | 6 | 570--1000 |
| C | 6 | 0 | 6 | 550--584 |
| D | 8 | 0 | 8 | 550--2875 |
| E | 8 | 0 | 8 | 600--2875 |
| F | 8 | 2 | 6 | 550--2974 |
| G | 6 | 0 | 6 | 550--584 |

By latency, the counts were 4/16 working at 25 ticks, 2/14 at 75 ticks, and 2/20 at 150 ticks. Both ALTERNATIVE cells were working; both DROP, PAUSE, and DISCONTINUITY cells were nonworking. These are retained observations, not protocol-effect estimates.

The event inventory contains 1,494 requested and responded proposals, 1,494 raw/normalized proposal records, 1,912 accepted chunks, 1,456 replacements, 260 derivation recomputations, 456 expiries, 158 safe-hold entries, 64,986 issued hold commands, and exactly 50 terminal-empty events. Every F/G derivation has positive `h`; every derivation sidecar retains its exact revision, parameter, ordered coverages, sorted parent hashes, owner observation, `b/z/h`, and output hash. Hold rows retain the broker-admitted canonical observation identity, latched q, and zero desired dq.

## Evidence

- Implementation Git SHA: `c35e24df30d42aaf2cb7ee1d510ed05142fa897e`.
- MuJoCo: `3.12.0`.
- MuJoCo model SHA-256: `98d11593fdb03a9834a48c70a73899fe7054212fea973d79f2938d1fb0113918`.
- P4 config SHA-256: `ddf9bf3ccdf4901a68865c42bbafdacd78196918124fe0aab4f032ceaf4a8cc4`.
- Raw manifest SHA-256: `06c9b78f99be1c15a37ee862a9646d0456b3434b14eab18a049aea485e9b5cb1`.
- Raw trials SHA-256: `96ea45db19cfe4930b614d99e9f4cbe880d4f37545bdd1840726652439c9b232`.
- Raw events SHA-256: `fe77460382c945474aa7e599e7e98fb62d83cc1632c9d155fb541bb137c965f2`.
- Derived summary SHA-256: `16d395b0c4b1130dbfac38f27859ad09573a8593f42a0c36e8500682e53ff103`.
- Annotated sample index SHA-256: `21ab2d322e18b7bfadc27aff147b53303e41d8536e3c33008fe7ee5331b5f9db`.
- Reconstruction recipe SHA-256: `0319352ee579f2270bb7bbee725b4dd9b173c4acd64268134704d44ca143e75f`.
- Complete root: 56 files, 48,569,679 bytes. SHA-256 of the LF-terminated canonical JSON inventory rows `{path,bytes,sha256}` is `76a3b8577073ce16c7b99cd2f4d8ef17084aa6df78eaab28b0d368e3923c90b2`.

Evidence is retained at `results/post-fix-dynamics-v3`. Reconstruction into the absent sibling `results/post-fix-dynamics-v3-reconstructed` replayed every proposal, broker transition, derived output, issued hold, metric, and telemetry row from the sealed raw members. `diff -rq` between the original and reconstructed derived directories returned no output.

The preregistered annotated examples are:

- Working: `tuning.P4.A.anchor.s20.l150.m51.NONE`, telemetry SHA-256 `3ffa47ae2c2deb6e9e6ab40bf7f99aa92ddefd2613f64588d5048e69a097f0ec`, event-row SHA-256 `1c6ab1ca5f5a6150f657be32360905c9ddf41ec63c7ebd1a390235aec97debdf`.
- Nonworking: `tuning.P4.A.anchor.s20.l150.m51.DROP`, telemetry SHA-256 `4a2a438d3b95d2006df56798dcf375f2c079dbfeb5a32854a17d91e660a38b8f`, event-row SHA-256 `362ae671a11713514ebf0bf86c10f6a8a67103843c9ae3efb45558b23b4c73fb`.

## Interpretation boundary

This run validates the repaired execution and evidence chain, not the approved scientific P5 matrix. It uses one deterministic P4 stack/vector fixture, one target displacement, a simplified nine-knot straight-line proposal generator, a selected rather than exhaustive fault matrix, and no sealed P4 eligibility gate. A's qualification schedule contains one proposal followed by long hold, so its labels are not a recurrent-open-loop baseline estimate.

Seeds 20 and 21 are identity replications only: the current runner has no seed-dependent scene or policy randomness, and corresponding telemetry files are byte-identical across the two seeds. They demonstrate deterministic repeatability, not independent samples or uncertainty reduction. The observed A/F working labels and B/C/D/E/G nonworking labels therefore cannot support causal ranking, generalization, pilot survival, or promotion. The pre-fix v2 root remains byte-preserved and machine-rejected as `INVALID_PRE_FIX`; this v3 root has a distinct identity and does not overwrite it.
