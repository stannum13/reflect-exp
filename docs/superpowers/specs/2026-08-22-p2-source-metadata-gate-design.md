# P2 Source Metadata Gate Design

Date: 2026-08-22

Status: approved under the autonomous-run authority in
`2026-08-22-reflect-lite-autonomous-run-design.md`.

Canonical input: `Reflect Lite Research Program.md` Sections 7, 8, 9, and 12.

## Outcome

P2 creates a complete, mechanically auditable source registry and a factual lock for
all 39 canonical repositories plus the six bootstrap dependencies already used by
the project. It performs live metadata resolution without cloning, installing,
importing, building, copying, or judging upstream source.

P2 is complete only when all 45 unique entries have a current default branch, a
full commit SHA, a license observation, and an `EXISTS` or `MISSING` result for
every selected path. A partial live pass may update the ignored metadata cache but
must leave the tracked lock byte-identical.

## Boundary with P3

P2 owns:

- `references/repos.yaml`;
- metadata-only resolution in `scripts/fetch_reference.py`;
- the factual `references/repos.lock.yaml`;
- offline structural validation in `scripts/audit_references.py`;
- offline fixtures, tests, and `make source-metadata-audit`.

P3 owns source checkout and Experiment 00 interpretation:

- sparse clones for active Experiments 01–03;
- import/build smoke checks;
- `references/licenses.md`;
- `docs/SOURCE_MAP.md`;
- `experiments/00_source_audit/results/compatibility.csv`;
- compatibility classifications and platform recommendations.

This cut makes P2 a bounded provenance gate and prevents compatibility work from
delaying the start of independent local baselines after P3.

## Registry and lock contracts

`repos.yaml` preserves the canonical URL, reuse mode, experiments, selected paths,
use, and caveat text. Bootstrap entries preserve their justifications. It contains
no mutable resolution result.

`repos.lock.yaml` records:

- a SHA-256 digest of the exact registry bytes;
- a UTC generation timestamp;
- name and URL;
- discovered default branch and 40-character lowercase commit SHA;
- retrieval timestamp and exact metadata evidence endpoints;
- upstream license SPDX observation, status, and evidence URL;
- every requested path verbatim with `EXISTS` or `MISSING` and evidence URL;
- `RESOLVED`, `BLOCKED_NETWORK`, or `INVALID` metadata status.

GitHub's license metadata is evidence, not legal approval. `UNKNOWN` or
`NOASSERTION` prevents adapter approval and future copying. It also prevents direct
dependency approval unless the exact installed distribution independently satisfies
the artifact-scoped exception below. This exception does not add a reuse mode or
turn package metadata into repository-copy authority. Globs such as `mjctrl`'s
`*.py` are matched only against root tree entries and remain recorded verbatim.

### Exact-wheel install evidence for direct dependencies

A `DIRECT_DEPENDENCY` whose pinned GitHub repository-license response is
`NOASSERTION` may be approved for installation only when P2 validates the upstream
Core Metadata from the exact wheel selected for the current locked interpreter and
platform. The wheel must be a `uv.lock` artifact for the same normalized package
name and exact version. P2 downloads that exact HTTPS artifact without installing
or importing it, enforces the metadata-response size bound, and verifies its full
SHA-256 before opening it as a ZIP archive.

The wheel must contain exactly one matching `{distribution}-{version}.dist-info`
directory, `METADATA`, and `RECORD`. `METADATA` must declare the same package name
and version, exactly one nonempty `License-Expression`, and one or more distinct,
safe `License-File` values. Every declared license file must exist below the same
dist-info `licenses/` directory. P2 verifies the SHA-256 and size recorded by
`RECORD` for `METADATA` and every declared license file, requires one record for
each, rejects duplicate/archive-unsafe names and unlisted declared files, and hashes
the exact `METADATA`, `RECORD`, and complete declared license-file inventory.
`RECORD` itself may have the wheel-standard empty digest and size because the
already-verified wheel digest authenticates its bytes.

The lock preserves the GitHub observation as `UNKNOWN` with its original evidence
URL. Closed `artifact_license.*` namespaced string fields in `metadata_evidence`
additionally bind package name, version, exact wheel filename and URL, wheel
SHA-256, `METADATA` and `RECORD` paths and SHA-256 values, the full
`License-Expression`, the canonical sorted complete license-file path/SHA-256
inventory, and authority `EXACT_WHEEL_INSTALL_ONLY`. These values are factual
upstream assertions; P2 performs no SPDX inference and does not reduce a compound
expression to a preferred component. Only a direct-dependency install may consume
this authority. Adapters, sparse/reference source use, copied code, and attribution
markers continue to require discovered repository-level SPDX evidence. P3's report
renderer must later learn this separate install-only authority before it may remove
the direct package's review blocker; P2 does not overload `license_status` to make
that downstream change implicitly.

## Resolver architecture

The fetch command accepts exactly one selector in P2:

```text
python scripts/fetch_reference.py --all-metadata-only
python scripts/fetch_reference.py --name NAME --metadata-only
```

Repository URLs are parsed as exact `https://github.com/OWNER/REPO` identities.
The resolver derives only documented GitHub HTTPS API/raw endpoints from that
identity. It follows no arbitrary host supplied by response data and sends no
credentials by default.

For each entry it runs read-only `git ls-remote --symref URL HEAD` to resolve the
default branch and branch-head SHA, resolves the commit's tree SHA through the
documented Git commit endpoint, retrieves the pinned recursive tree for path
verification and root license discovery, and queries GitHub's repository-license
endpoint at the pinned commit. If GitHub marks a recursive tree truncated, the
resolver traverses only the requested path prefixes and root license candidates
through non-recursive tree calls; it never guesses from incomplete data. Raw
responses and request metadata are cached below ignored
`external/.metadata/` using checksummed, repository-scoped files. A valid dated cache
may resume an interrupted pass, but the final lock is published through a
same-directory temporary file and atomic rename only after the selected set is
complete and passes structural validation.

Git executes from a fresh non-repository directory with repository discovery,
system/global configuration, redirects, credentials, and terminal prompting
disabled, and credential, askpass, proxy, trace, and ambient `GIT_CONFIG_*`
environment removed. The output parser is
order-independent, requires exactly one symbolic HEAD and matching full SHA, accepts
slashes in branch names, and treats detached, unborn, missing, malformed, SHA-256,
or ambiguous HEAD results as explicit unsupported/invalid metadata rather than
silently guessing.

Unauthenticated GitHub REST resolution is serialized and resumable because the
documented public limit is 60 requests per hour and the documented commit, tree, and
license sequence needs more than one window for 45 repositories. On exhaustion,
the process stores validated partial cache entries, reports the reset timestamp, and
exits without publishing the lock. A later invocation resumes from cache; it does
not sleep for an unbounded interval or issue immediate forbidden retries.

The resolver uses an injectable command runner, direct HTTPS transport with ambient
proxies disabled, and clock. Git
execution/parsing, bounded HTTPS, checksummed caching/atomic publication, and
resolution orchestration live in separate focused modules while
`reflect.source_fetch` retains the small public facade. It
accepts only derived `api.github.com` endpoint paths and rejects redirects that
change the canonical owner/repository or pinned object identity. Unit
tests use checked-in fixtures and make no network request. Network errors include
endpoint or command, status/return code or exception class, and rate-limit
observations without secrets.

The cache is anchored by a no-follow directory descriptor. All child creation,
reads, replacements, and rate-limit marker operations are relative to retained
descriptors; a symlink at the cache root or any intermediate component is rejected.

License classification is not reimplemented locally. GitHub's pinned license API
SPDX result is recorded as factual upstream metadata and checked against the
tree-discovered root license path/blob when supplied. `NOASSERTION`, absent,
malformed, conflicting, or ambiguous results remain `UNKNOWN`; they never authorize
repository copying or an adapter. A GitHub `NOASSERTION` may cross only the exact
wheel install boundary above, using the wheel publisher's complete
`License-Expression` verbatim. Conventional root filenames, including suffixed or
multiple license files, remain recorded for P3 review rather than being collapsed
into a locally inferred legal conclusion.

## Audit behavior

The offline audit rejects:

- registry name collisions, unknown reuse modes, or non-GitHub HTTPS URLs;
- a registry/lock digest mismatch or missing/extra lock entry;
- a non-full SHA or missing default branch/retrieval timestamp;
- selected paths that were substituted, dropped, or lack a factual status;
- missing license observations for direct and adapter dependencies;
- adapter entries with an unknown repository license status;
- direct entries with neither discovered repository SPDX evidence nor complete,
  exact-wheel `EXACT_WHEEL_INSTALL_ONLY` evidence;
- artifact evidence on a non-direct entry, a wheel absent from `uv.lock`, a
  package/version/platform mismatch, an unverified wheel digest, malformed Core
  Metadata/RECORD, an incomplete license-file inventory, or any attempt to use
  artifact authority for copied/adapted source;
- upstream source copied into `reflect/` without explicit attribution metadata;
- a tracked model/checkpoint artifact or a created source checkout.

Metadata mode calls the existing simulation-only safety guard before any I/O and
never enables remote execution or physical communication.

## Failure and completion behavior

A failed request is retried once only when the retry is materially different (for
example, a valid cached response after a live rate limit). Otherwise the command
reports an explicit per-entry blocker, preserves exact evidence in the ignored
cache, and exits nonzero without replacing the lock.

P2 advances only after the live complete command, offline audit, full test suite,
safety checks, repository-boundary checks, and deterministic fixture checks pass.
The run report is then bound to the clean implementation commit, P2 becomes
`complete`, and P3 becomes `in_progress`.
