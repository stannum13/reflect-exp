# pi0.5 Semantic-Interface Feasibility

## Result

`NOT_RUN_NO_CHECKPOINT_BACKEND`

At pinned OpenPI commit `15a9616a00943ada6c20a0f158e3adb39df2ccac`, the
official pi0.5 public inference path does not expose a semantic text/token plan.
It consumes images, prompt tokens, and state, then returns a flow-matched action
chunk. `Policy.infer` constructs `state`, `actions`, and `policy_timing`; the
DROID pi0.5 configuration has a 15 x 32 action shape. The websocket server sends
that policy dictionary unchanged.

This is a negative semantic-interface feasibility result, not a negative result
about pi0.5's internal representations or its ordinary VLA performance.

## Real probes and boundaries

- Executed the pinned official `BasePolicy.infer` class locally with a
  deterministic 15 x 32 transport fixture. This proves the callable official
  API path only. It is explicitly retained as
  `NONWORKING_SEMANTIC_INTERFACE_SAMPLE`, not checkpoint inference.
- Parsed the pinned official policy, pi0.5 model/config, server, client, and
  checkpoint configuration closure. Every inspected source byte is hashed.
- Ran the official full-project frozen/offline dependency dry-run with repository
  CPython 3.11.13. It exited 2 because `jax-cuda12-plugin==0.5.3` has no macOS
  arm64 wheel; its complete stdout/stderr is retained.
- Ran the official lightweight client frozen/offline dry-run. It exited 0 and
  produced a valid 13-package installation plan; it did not install or contact a
  model server.
- Queried metadata only for
  `gs://openpi-assets/checkpoints/pi05_droid`: 20 objects,
  12,429,488,598 bytes (11.58 GiB). Per-object generation, MD5, CRC32C, and size
  form inventory hash
  `c20b768e4e38f1627533be6dd83a061bfdf844395edb30b038d7d62c826ec11d`.
  No checkpoint object was downloaded and the local checkpoint cache was absent.
- The host was Apple M2 Max, arm64, 32 GB, macOS 15.6.1. No `nvcc` or
  `nvidia-smi` was available. No authenticated OpenPI remote host was configured.
- No checkpoint-backed forward pass, semantic plan, motion plan, controller
  action, or outcome row was produced. Action fixture bytes are hashed and
  discarded at the semantic boundary.

The raw command receipts include exact argv, exit status, stdout, stderr, and
stream hashes. Hardware-profiler stdout is deliberately reduced to chip, memory,
model, and processor fields; the evidence contains no serial, UUID, UDID, or API
key.

## Evidence and validation

- Raw manifest SHA-256:
  `94ce651eebffc632a9934ac9ca49e7c359dcaf4874836bfe8161cd3cf2337986`
- Raw observations SHA-256:
  `3b25d49c20076545cd458740d838599ca54918f7ffeaada666dbc49d26afef84`
- Source finding SHA-256:
  `7dbeb31d1d634ffa145491e0a9961d05c6a331e8d58492e0f36426b5f23a407b`
- Derived manifest SHA-256:
  `701d003c7031879ea7eb94121e6340b24ef2bc307b507858bb48e4f58a283efb`
- Derived summary SHA-256:
  `c4000f2e567489fc9780fef112d9cc709ebe70234aae7291173c48001a549c97`
- Deterministic SVG SHA-256:
  `78051984228090ee3f5e49c215087cb24f1650ba2206a294d54bd02a3bffd2bf`

TDD history:

- RED 1: 5 failures because the backend did not exist.
- RED 2: 2 failures for missing checkpoint-metadata and command receipts.
- RED 3: 1 failure for missing collector.
- RED 4: 1 failure because raw hardware stdout retained forbidden identifiers.
- GREEN: `8 passed in 0.22s`.
- Existing source-registry baseline: `15 passed in 0.48s`.
- Final combined Exp09 plus source-registry gate: `23 passed in 0.56s`.
- Clean reconstruction to `/private/tmp/pi05-semantic-replay-20260824`:
  byte-identical (`diff -rq` exit 0).

The create-only probe command was:

```text
/Users/shiva/repos/advaitik/reflect-exp/.venv/bin/python experiments/09_mini_reflect/run_pi05_probe.py --openpi-source /Users/shiva/repos/advaitik/reflect-exp/external/openpi --python /Users/shiva/repos/advaitik/reflect-exp/.venv/bin/python --checkpoint-cache /Users/shiva/.cache/openpi/checkpoints/pi05_droid --output experiments/09_mini_reflect/results/pi05-semantic-interface-feasibility-v1
```

## Next executable route

Use this exact OpenPI commit and checkpoint on a supported NVIDIA Linux host, or
configure an authenticated official OpenPI websocket server that returns an
immutable checkpoint identity and real forward-pass receipt. A separate,
reviewed semantic decoder/interface is still required: the official endpoint's
public response is action chunks, so it cannot directly occupy the preregistered
semantic-only planner boundary.
