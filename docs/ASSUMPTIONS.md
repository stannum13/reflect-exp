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
