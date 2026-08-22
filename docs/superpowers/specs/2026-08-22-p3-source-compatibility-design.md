# P3 Source Compatibility Design

Date: 2026-08-22

Status: approved under the autonomous-run design; execution remains gated on a
complete P2 lock and passing offline audit.

Canonical input: `Reflect Lite Research Program.md` Sections 7–9, 12, 27, 30,
and 33.

## Outcome

P3 is Experiment 00. It converts P2's factual source lock into bounded decisions
about what can be used on the local M2, what is study-only, what requires a patch or
remote Linux/GPU, what has moved, and what requires license review. P3 does not
change the P2 lock and does not implement Experiments 01–03.

P3 produces:

- `references/licenses.md`;
- `docs/SOURCE_MAP.md`;
- `experiments/00_source_audit/results/compatibility.csv`;
- an Experiment 00 claim/result report and exact command evidence.

## Eligibility and source-use boundary

The initial sparse-checkout set is limited to the eight `SPARSE_REFERENCE` entries
used by Experiments 01–03:

| Experiment | Repositories |
|---|---|
| 01 | `mujoco_mpc`, `mujoco_menagerie`, `mjctrl` |
| 02 | `act`, `lerobot`, `openpi` |
| 03 | `behaviortree_cpp`, `navigation2` |

Only selected paths marked `EXISTS` in the P2 lock are checked out. A `MISSING`
path is reported as `PATH_CHANGED`; no nearby replacement is inferred. Checkouts
are pinned to the locked full SHA, live below ignored `external/`, and never enter
the repository index. Existing dirty or mismatched checkouts are refused.

The initial checkouts are study-only. Python files are parsed without importing;
C++/ROS layouts receive static manifest/header checks rather than broad builds.
No VLA server, ROS 2 stack, CUDA dependency, model, dataset, or training environment
is started. Menagerie assets require their own asset-license observation before one
small XML load may be attempted.

Runtime candidates are separate:

- the published MuJoCo package is the only required local dependency and must pass
  one headless model construction and `mj_step` smoke;
- Mink is an optional thin adapter with at most one install attempt and one
  materially different remedy; a project-local IK baseline remains available;
- Rerun is optional telemetry and is not installed merely to satisfy P3.

## Sparse checkout behavior

P3 extends `scripts/fetch_reference.py` only with explicit source modes:

```text
python scripts/fetch_reference.py --name NAME --sparse-checkout
python scripts/fetch_reference.py --experiment 01_policy_control --sparse-checkout
```

The command first runs the complete offline P2 audit, reads the locked default
branch/SHA, and filters the selector to eligible `SPARSE_REFERENCE` entries. It uses
an isolated fixed Git environment, creates a sibling temporary repository, fetches
the exact SHA with blob filtering and finite timeouts, configures non-cone sparse
patterns from existing requested paths, checks out detached, verifies HEAD and
materialized boundaries, then atomically renames the directory. Root globs such as
`*.py` retain their literal non-cone semantics.

A pre-existing destination is accepted only when it is a Git repository at the
locked SHA, its sparse patterns match, and `git status --porcelain=v1 -z` is empty.
Otherwise the command refuses to overwrite it. It never follows registry-controlled
paths outside the per-repository destination and enforces the autonomous download
ceilings.

## Compatibility evidence

Each checkout/smoke operation writes one immutable machine-readable evidence
fragment under `experiments/00_source_audit/results/fragments/`. A fragment records
repository, commit, experiment, selected path, operation, platform, Python/runtime,
exact command, exit status, bytes downloaded/on disk, license observation, blocker,
and evidence hashes. Report generation consumes fragments; it does not rerun source
operations.

Compatibility classifications are exactly:

```text
WORKS_LOCAL_M2
WORKS_LOCAL_CPU_WITH_PATCH
SOURCE_REFERENCE_ONLY
REMOTE_GPU_REQUIRED
REMOTE_LINUX_REQUIRED
LICENSE_REVIEW_REQUIRED
STALE_OR_ARCHIVED
PATH_CHANGED
NOT_EVALUATED
```

Static parsing alone never earns `WORKS_LOCAL_M2`; study-only references receive
`SOURCE_REFERENCE_ONLY` unless a stronger blocker such as `PATH_CHANGED` or
`LICENSE_REVIEW_REQUIRED` applies. Remote/deferred registry modes are classified
from factual requirements and remain unexecuted.

## Reports

`references/licenses.md` lists `repository@SHA`, reuse mode, root and selected-asset
license evidence, allowed action (`INSTALL`, `SPARSE_STUDY`, `NO_COPY`, `DEFER`),
attribution requirement, decision/blocker, and review date. It is provenance, not
legal advice.

`docs/SOURCE_MAP.md` maps each experiment/local component to the exact upstream
repository/path, intended use, no-copy/adaptation restriction, local fallback, and
attribution record.

The compatibility CSV contains at least:

```text
repository,commit_sha,experiment,reuse_mode,selected_path,path_status,operation,
platform,python_requirement,compiler_or_runtime,smoke_command,smoke_status,
classification,license_status,license_spdx,disk_bytes,download_bytes,blocker,notes
```

Rows are deterministic and cover every repository/path/experiment combination,
including unexecuted remote/deferred entries.

## Gate

P3 stops a nonessential source after one failed attempt and one materially different
remedy, records the exact evidence, classifies it, and continues. Optional adapters,
study-only sources, and missing provisional paths do not block the local baseline.

P3 advances when the complete P2 audit passes, MuJoCo passes its one-step local
smoke, every installed dependency is license-recorded and smoke-tested, eligible
sparse checkouts are pinned and clean, all required outputs validate, no checkout or
model is tracked, and physical/remote execution remains disabled. This opens the
independent P4, P6, P7, and P9 preparation lanes.
