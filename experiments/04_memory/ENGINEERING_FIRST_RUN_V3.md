# Experiment 04 Engineering First Run v3

Status: `ENGINEERING_NONCONFIRMATORY`

The v2 evidence remains byte-for-byte valid for M5 confidence and staleness
handling. `ENGINEERING_FIRST_RUN_V2_EMBEDDING_SUPERSESSION.json` supersedes only
its embedding-specific interpretation: the v2 ambiguous cases were already at
ceiling through typed lookup and therefore could not discriminate vector value.

## Frozen diagnostic

- Implementation commit: `e558f0c0cea81d702028dfc348ab2fccb05c3440`
- Implementation source SHA-256: `299da95458f192527bc150d5995d1103fbb3af52834cbe948ee87aecd99d8b50`
- Protocol/config SHA-256: `dc3694f40cf89ba42cf41784dd48792fc2712e396ac0bedfb1256a19734826f1`
- Seeds: `20260891-20260894`
- Matrix: variants `M0-M6,H0,V0` x four seeds x ten queries
- Completed: 36/36 bundles and 360/360 answers

Seeds in slots zero and two retain the exact `service valve` aliases. Slots one
and three are fuzzy identity cases. Each fuzzy case has eight primary aliases
with high lexical overlap and 16 alternate aliases generated before scoring by
the fixed rule `sha256("exp04-fuzzy-v3:<zero-based-index>")[:12]`. No token was
replaced after observing retrieval. Typed identity lookup requires the exact
normalized label; lexical top-8 contains only the primary identity in both
fuzzy cases. M5 answers identity from typed plus lexical retrieval. M6 adds the
signed-hash vector channel, and V0 uses that vector channel alone.

## Result

| Variant | Correct | Stale/wrong composite | Ambiguous retrieval | Fuzzy vector hits / candidates |
|---|---:|---:|---:|---:|
| M0 | 0.225 | 0.0000 | 1.000 | not executed |
| M1 | 0.575 | 0.0625 | 1.000 | not executed |
| M2 | 0.425 | 0.0000 | 0.000 | not executed |
| M3 | 0.475 | 0.0625 | 1.000 | not executed |
| M4 | 0.775 | 0.0625 | 1.000 | not executed |
| M5 | 0.950 | 0.0000 | 0.500 | not executed |
| M6 | 0.950 | 0.0000 | 0.500 | 0 / 32 |
| H0 | 0.775 | 0.0625 | 1.000 | not executed |
| V0 | 0.725 | 0.0625 | 0.500 | 0 / 32 |

The vector channel retrieved all four exact alias facts across the two exact
cases, proving ordinary candidate membership on exact lexical identity. It
retrieved zero of the 32 frozen fuzzy alternate candidates. Consequently M6
matched M5 on both fuzzy cases and on the full matrix; vector-only V0 also
missed both fuzzy identities. The ablation test removes the vector candidates
from M6's closed retrieval union and verifies exact candidate membership, but
there is no fuzzy answer-level gain to claim.

This is a negative discriminability result for the current signed-hash vector,
not evidence that learned or semantic embeddings cannot help. It does not
justify adding this vector channel to the runtime. M5 still answered all 36
non-identity cases correctly, retained zero stale/wrong composite, and its valid
v2 confidence/staleness result is unchanged.

## Evidence identity

- Raw manifest: 4,618 bytes, SHA-256 `1af47abbc95eb51a4b325987c84145d685c5830b3f2cc3885727a702978519bb`
- Aggregate: 3,347 bytes, SHA-256 `9aa0fe8f4f6a9aed5d36f615b734912ccc21a27a73e7e69159d67084fb412ff1`
- Annotations: 4,144 bytes, SHA-256 `9174ce9248eb4927eb8bea9d41fdbc4ba3ac5eb6bc2c60b2d8e9693d7b566d13`
- Reconstruction recipe: 578 bytes, SHA-256 `71af12ca7815abbaf1d60f017b535160aaf2a5062d9bac6857958ae7b511f9b2`
- Generated result: 534 bytes, SHA-256 `b6cdd18fcf3c651320fb7932f5503de279f2ec59d9dc2632ee3e886699ee4fe5`
- Complete evidence: 221 files, 741,461 bytes
- Canonical inventory SHA-256: `cb5c97044f6f262fd0a0064feb6d6ce0ac577a137c07355e37030bfa46f17ce4`

The inventory digest is SHA-256 over newline-terminated canonical JSON for the
sorted relative-path, byte-count, and file-SHA inventory. Clean-directory
reconstruction validated every bundle/member hash, replayed all decisions from
the observation trace without scorer truth, joined truth only after replay, and
reproduced all four derived artifacts byte-for-byte.
