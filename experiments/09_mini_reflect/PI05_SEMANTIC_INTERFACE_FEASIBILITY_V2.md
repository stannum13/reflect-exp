# pi0.5 Semantic-Interface Feasibility V2

## Result

`NOT_RUN`

The transport/interface fixture works and is explicitly synthetic. Model
inference did not run. No checkpoint bytes were downloaded, no model or
checkpoint was substituted, no forward inference was performed, and no
physical execution occurred. Consequently this evidence contains no pi0.5
semantic plan or scientific outcome.

V1 is preserved byte-for-byte but classified
`V1_REJECTED_SUPERSEDED_BY_V2`. Its preserved tree SHA-256 is
`628bb6ea2ddbe800eb9b4eae445377909083f0cd9263667299bc94355e9243ed`.

## Correct public interface

At pinned OpenPI commit
`15a9616a00943ada6c20a0f158e3adb39df2ccac`, the source receipts establish this
chain independently from report labels:

1. The `pi05_droid` model config samples an internal 15 x 32 action array.
2. The bound `DroidOutputs` transform returns `actions[..., :8]`.
3. The public `Policy.infer` response is therefore 15 x 8 `actions` plus
   `policy_timing`; transformed output does not retain `state`.
4. The websocket server adds `server_timing`, and the client returns the
   unpacked response.

The allowed websocket response keys are exactly `actions`, `policy_timing`, and
`server_timing`. Static AST receipts find no semantic decoder and no semantic
text, token, or plan output in this public response closure. This is an
interface finding, not a claim about internal representations or ordinary VLA
performance.

## Closure and replay

The pinned closure records byte size, SHA-256, and exact Git blob identity for
17 files, including DROID output policy, base policy, policy config, model and
model config, websocket server and client, training config, both project
metadata files, and `uv.lock`. The closure SHA-256 is
`0fdfd9b11c02a46a2811179ebe6088053766e6db94624fc50e6e7ca82bdf281e`.

Replay enforces exact recursive root/raw/derived schemas; authenticates every
raw and derived member plus both child manifest bytes from the root manifest;
rejects extra files, nested manifests, symlinks, broken symlinks, member
tampering, and coherent label-plus-manifest rehashes; recomputes source,
checkpoint-inventory, and command ancestry; and regenerates derived output from
the pinned static source receipts. A forward result can become `RUN` only from
an exact receipt whose binding hash covers the pinned source closure,
checkpoint inventory, websocket server blob, request hash, response bytes, and
15 x 8 public response schema. Boolean flags, paths, and environment variables
are not forward-pass evidence.

Checkpoint metadata remains inventory-only: 20 safe relative object names,
generations, MD5/CRC32C identities, sizes, 12,429,488,598 total bytes, and
inventory SHA-256
`c20b768e4e38f1627533be6dd83a061bfdf844395edb30b038d7d62c826ec11d`.
All retained command streams and arguments are sanitized. V2 evidence contains
no absolute user path, cloud download/self link, URL, bearer value, API key, or
token.

## Evidence identities

- Raw manifest SHA-256:
  `8b6cc719001dd2c014d61de4610ec9db9f2dc36a31699fbab4ebd96294a1844f`
- Derived manifest SHA-256:
  `863acfefe3c1d0490455a149d95177e712d589ef0b8bc8b02e27994319ab1b9d`
- Root evidence manifest SHA-256:
  `cf380674ffc773697b17b9cfb2cfb607235a4c0c00872f05cfc4f5327fb0c2f0`
- Summary SHA-256:
  `faac69f1735aaef032b116c0d55dfcb938f5ad58493359ccf0813c2dab450c67`
- Source receipt SHA-256:
  `b30d61572494fccc3ac8bd53641d2a8d496062045aa5371474cfcd9c45bd628d`

## TDD record

- RED: 29 failures because the separate V2 backend did not exist.
- First GREEN: 29 focused V2 tests passed.
- Exp09 source/test gate before evidence publication: 37 passed.
- Final combined Exp09 plus source-registry gate: 52 passed.
- Ruff gate: all V2 source and tests passed.
- Clean replay regenerated all four derived files byte-identically.

The published evidence was created locally from the pinned checkout, the
previously captured safe checkpoint inventory, and sanitized offline dependency
receipts. Publication performed no network request or forward inference.
