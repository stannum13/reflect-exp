# Recorded Assumptions

## A-001 — Autonomous scope

Use the recommended scope: complete P0-P10, then continue through every locally
justified canonical gate. The user may replace this with `p0-p10-only` explicitly.

## A-002 — Local interpreter

Use the already installed CPython 3.11.13 because it is compatible with the intended
robotics stack and avoids relying on the host's Python 3.14 environment.

## A-003 — Worktree placement

Use ignored `.worktrees/` paths inside the repository because sibling paths are
outside the writable sandbox. Do not create lane worktrees before P0-P3 complete.

## A-004 — Network and remote resources

Registry-derived HTTPS access is allowed only through audited tooling or an explicit
approval. Remote compute is unavailable unless every `REFLECT_REMOTE_*` guard is
configured with an allowlisted host and positive finite budgets.

## A-005 — Evidence status

Pilot outputs are exploratory. Only an unchanged implementation and frozen protocol
run against newly generated confirmation seeds may produce `SUPPORTED`.

## A-006 — Bootstrap dependencies

uv, hatchling, PyYAML, and pytest are the minimum tooling needed before P2 can
materialize the full registry. Their URLs, modes, and justifications are recorded in
`references/bootstrap-tools.yaml`; P2 must resolve their SHAs and licenses with the
rest of the registry.

## A-007 — P1 artifact storage

Use NumPy/NPZ for observation arrays and genuine PyArrow Parquet for action and
control-reference rows. A custom pseudo-Parquet format or database would weaken
interoperability and is not selected.

## A-008 — Replay boundary

Replay is a deterministic event reducer over saved artifacts. It reconstructs state
but does not rerun physics.

## A-009 — Measured metadata ownership

Rollout metadata callers supply measured environment fields; the artifact writer
validates and preserves them rather than silently probing or inventing values.

## A-010 — Equal event ordering keys

When event timestamp and sequence values are equal, replay preserves original JSONL
order as the final stable ordering key.

## A-011 — Direct-dependency package license evidence

When a direct dependency's pinned GitHub license endpoint reports `NOASSERTION`, an
exact locked wheel's upstream Core Metadata `License-Expression` may authorize only
installation of that artifact. The evidence must bind the normalized package name,
exact version, selected `uv.lock` wheel filename and SHA-256, exact `METADATA` and
`RECORD` hashes, and the complete declared `License-File` inventory. GitHub's
`NOASSERTION` remains recorded; no license text is classified locally. Repository
copying and adapter use remain blocked without repository-level SPDX evidence.
