# Experiment 04 Engineering First Run v2

Status: `ENGINEERING_NONCONFIRMATORY`

The original v1 evidence is preserved byte-for-byte but is machine-readably
classified `SUPERSEDED_INVALID_COMPARATORS` in
`ENGINEERING_FIRST_RUN_SUPERSESSION.json`. This v2 run is a distinct execution,
not an amendment of the invalid v1 results.

## Frozen execution

- Implementation commit: `2772147fa45ed4a8622d6d63f21c161d71b6c99c`
- Implementation source SHA-256: `e1bf9c4afd75eb4cb0ce1a76e5ef25bf47adbd03aa990446a1d238624dbe9978`
- Protocol/config SHA-256: `c03e2b6a70f9e005f21f10953ffee9a7cff628f857a558f4d66444a7fbc8c543`
- Seeds: `20260891-20260894`
- Matrix: variants `M0-M6,H0,V0` x four seeds x ten queries
- Completed: 36/36 bundles and 360/360 answers

Scorer truth was derived from each seed's latent world and was never passed to
the runner. The four worlds change entity identities, duplicate-event order,
failure reason, restricted-room choice, pose age across the stale boundary, and
operational-state confidence across the 0.70 threshold. For example, the four
pose truths are `USABLE, STALE, STALE, USABLE`, while conflict truths are
`CONTRADICTED, OPERATIONAL, FAILED, UNKNOWN`.

H0 consumes the same observation trace through an independent append-only flat
event implementation and query path. V0 answers from its actual retrieved
snippets. M6 answers from the closed union of typed, lexical, and signed-hash
vector retrieval; perturbation tests prove that retrieved content changes its
answer.

## Result

| Variant | Correct | Stale/wrong composite | Ambiguous retrieval |
|---|---:|---:|---:|
| M0 | 0.225 | 0.0000 | 1.000 |
| M1 | 0.575 | 0.0625 | 1.000 |
| M2 | 0.425 | 0.0000 | 0.000 |
| M3 | 0.475 | 0.0625 | 1.000 |
| M4 | 0.775 | 0.0625 | 1.000 |
| M5 | 1.000 | 0.0000 | 1.000 |
| M6 | 1.000 | 0.0000 | 1.000 |
| H0 | 0.775 | 0.0625 | 1.000 |
| V0 | 0.775 | 0.0625 | 1.000 |

Confidence/staleness handling improved M5 by 0.225 over M4 and eliminated the
observed stale/wrong composite. M4, the independent H0 flat log, and the honest
V0 retrieval comparator tied at 0.775, so this screen does **not** establish an
advantage for graph-plus-episodes over equal-input flat history or vector
retrieval. M6 added no gain over M5, including on ambiguous identity. Under the
program kill condition, embeddings should therefore remain out of the runtime
path unless later preregistered evidence shows a gain.

The scan-count field counts all `RESCAN`/`REIDENTIFY` decisions, including
correct necessary scans; it must not be interpreted as unnecessary-scan rate.
These public engineering seeds do not support confirmation, production storage
selection, or real-perception claims.

## Evidence identity

- Raw manifest: 4,618 bytes, SHA-256 `033d32fd7d38113b0e048507dfb417a9e0a623d24f7e7816cc248071a28f47d5`
- Aggregate: 1,972 bytes, SHA-256 `3199f23201ec64644943fe19c2631870b11e6eb6fad212fcdcc4f10ff8a1506a`
- Annotations: 3,900 bytes, SHA-256 `68a5d29bf13ce00feff871a2fa8bd9b9fc1f751f397afb411c5a35de931b8fbf`
- Reconstruction recipe: 578 bytes, SHA-256 `6bc4c002e5cccb070b0d1d5cd168790e7eacaf76b506ce58c6a5fd69015c3536`
- Generated result: 423 bytes, SHA-256 `959ab9a77115a35d888a518d6f42ef585d9d8ac5b1bb8fa8a48dbf448ec182a0`
- Complete evidence: 221 files, 553,737 bytes
- Evidence-tree SHA-256: `7d2cb8aa4dfc5b7781294d76b6152a9d49e8c5e7793fbdd40924d93d0e0c295a`

Clean-directory reconstruction validated every member hash, replayed all graph,
flat-log, and retrieval decisions without scorer truth, joined truth only after
replay, and reproduced all four derived artifacts byte-for-byte. The raw bundles
retain every observation, compiled fact or flat event, query decision, metric,
truth row, replay hash, and working/nonworking annotation input.
