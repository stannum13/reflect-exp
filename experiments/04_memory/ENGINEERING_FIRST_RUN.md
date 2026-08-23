# Experiment 04 Engineering First Run

Status: `ENGINEERING_NONCONFIRMATORY`

## Frozen execution

- Implementation commit: `5099d33f61a8789dacd15d6ef1ad0c0bc6d575da`
- Implementation source SHA-256: `1f8544d8caf9c6b79937cc69b04aa637bc2deef17d07c2fec8d781ef87bbdfe4`
- Protocol/config SHA-256: `9cda0bb4abdd3a4dc7069c6e5b05cb98a3269bc6395f8847f2ed6b39e8f4768b`
- Matrix: BASE configuration, variants `M0-M6,H0,V0`, all ten canonical query cases, seeds `20260871-20260874`
- Completed: 36/36 variant-seed bundles and 360/360 case answers

The evaluated runner accepts only `(variant_id, seed, observations)`. Scorer truth is retained in a separate file and joined only after query decisions are immutable. Every seed's observation-trace SHA-256 is byte-identical across all nine variants.

## Result

| Variant | Correct | Stale/wrong composite | Ambiguous retrieval |
|---|---:|---:|---:|
| M0 | 0.200 | 0.000 | 1.000 |
| M1 | 0.500 | 0.125 | 1.000 |
| M2 | 0.400 | 0.000 | 0.000 |
| M3 | 0.400 | 0.125 | 1.000 |
| M4 | 0.700 | 0.125 | 1.000 |
| M5 | 1.000 | 0.000 | 1.000 |
| M6 | 1.000 | 0.000 | 1.000 |
| H0 | 0.700 | 0.125 | 1.000 |
| V0 | 0.100 | 0.000 | 1.000 |

On these hand-authored cases, graph plus episodes improved correctness by 0.50 over current-observation-only and by 0.60 over retrieval-only, while matching the equal-information flat-history control. Adding explicit confidence/staleness handling improved correctness by 0.30 and removed the observed 0.125 stale/wrong composite. The deterministic signed-hash BM25 retrieval channel added no ambiguous-identity gain over M5, so this screen provides no reason to retain it in the runtime path.

These are fixed public engineering seeds and simplified native stores. They do not support confirmation, promotion, a production database choice, or an Experiment 05 prerequisite claim.

## Evidence identities

- Raw manifest: 4,618 bytes, SHA-256 `3ad968c1a68fdac5cf50447e70c4dad26801b53b76f639eca0fa8c1c1bc82796`
- Aggregate: 1,865 bytes, SHA-256 `a30aacc8330f2f3919c61cc54b4239ce02bdc7b0c1cd7131bb7869c28af6b822`
- Annotations: 3,896 bytes, SHA-256 `4cabd08af9f1a332281614c27a8e637f79772958af4f0ab472a2639766b9c523`
- Reconstruction recipe: 513 bytes, SHA-256 `06b7de524f4efa681081efc54e048bd9357ffbdf3f6f2dcf9f4b7ee64f755b0b`
- Generated result: 420 bytes, SHA-256 `0e0a1c8d961ff68337e826bde882dfe057e9beff18a18476e714a30dee69c1c9`
- Complete evidence: 221 files, 542,005 bytes
- Evidence-tree SHA-256: `254ce7d39da43dc2a34aee91f6af3e87e91fcfca38d8276aa28288600638e76e`

The tree digest is SHA-256 over sorted regular-file rows encoded as `relative_path NUL decimal_bytes NUL file_sha256 LF`. Clean-directory reconstruction validated every bundle member, replayed every answer without scorer truth, rejoined truth, and reproduced all four derived files byte-for-byte.

## Next empirical step

Run the approved claim-bearing Exp04 pilot rather than starting Exp05: three frozen memory configurations times nine variants times four tuning seeds (108 bundles), mechanically select one common configuration, then run that configuration on four untouched evaluation seeds (36 bundles). Preserve M4/M0/V0/H0, M5/M4, and M6/M5/V0 contrasts. The present no-gain M6 result makes removal of retrieval the default unless that canonical pilot shows an improvement.
