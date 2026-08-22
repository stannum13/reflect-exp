# P9 Unitree R1 Static Source and Joint-Mapping Audit Design

**Date:** 2026-08-22

**Status:** Approved autonomous design; implementation is gated on complete,
hash-matched P2 and P3 evidence

**Scope:** P9 / Experiment 08 Phase 0 only; no simulator execution or deployment

## 1. Decision and non-deployment boundary

P9 answers one bounded question: can every R1 actuator and observation/action position
declared by the pinned official sources be mapped to the expected SDK motor-slot domain
with explicit sign, offset, limits, gains, provenance, and isolation tests, while the
same pinned static evidence closes the mandatory Stage-0 contracts for units, named
coordinate frames, simulator/control rates, timestamp clock semantics, and versioned
observation/action schemas? Schema carriage by an exported model is recorded separately
as `NO_EXPORTS_IN_SCOPE`; it is not claimed as verified until a later phase actually
creates or admits an export.

It does not install or import Unitree packages, register tasks, load a checkpoint, run
Isaac/MJLab, open DDS, enumerate a network interface, use remote compute, or
communicate with hardware. The only network exception is the bounded P3 Git subprocess
specified in Sections 3-4 for fetching pinned inert source; audit, freeze, report,
check, and tests create no socket. Experiment 08 Phases 1-3 remain separate remote
gates. A static mapping pass cannot establish R1 runtime compatibility or safety.

## 2. Alternatives and selected approach

- **Manual prose table:** fast but not reproducible and cannot catch duplicate/order
  errors.
- **Import upstream code and inspect runtime registries:** precise when dependencies
  work, but can execute arbitrary initialization and deployment communication.
- **Selected: bounded static evidence extractor plus reviewed freeze and pure mapping
  tests.** Files are parsed as inert bytes/data; every value retains a pinned source
  span. A second validator rebuilds the permutation from the frozen manifest without
  executing upstream code.

## 3. Authoritative inputs and source lanes

P9 requires a complete passing P2 lock/audit and a complete passing P3 gate. The P9
protocol binds the exact file hashes for `references/repos.yaml`,
`references/repos.lock.yaml`, immutable historical P2 and P3 phase records, both
phases' clean evidence-base Git SHAs and report-only commit/blob/hash identities, P3's
`experiments/00_source_audit/configs/operation-manifest.yaml`,
`experiments/00_source_audit/results/compatibility.csv`, `references/licenses.md`,
`docs/SOURCE_MAP.md`, `docs/MATURITY_LEDGER.md`, `experiments/00_source_audit/RESULTS.md`,
`experiments/00_source_audit/INTERFACE_FINDINGS.md`, and the exact MuJoCo-smoke
fragment path/hash named by P3's operation manifest. Missing, dirty, incomplete, or
hash-mismatched evidence blocks P9 before checkout or output creation.

The current `docs/RUN_MANIFEST.yaml` must contain closed immutable records at
`phase_records.p2` and `phase_records.p3`. Each `PhaseEvidenceRecord` has exactly
`phase_id, lifecycle_state, implementation_evidence_git_sha, report_commit_git_sha,
report_path, report_git_blob_id, report_sha256, bound_evidence_git_sha,
artifact_ledger_sha256`; `phase_id` is the matching phase, state is `complete`, report
path is exactly `RUN_REPORT.md`, the report commit changes exactly that path, and its
only parent is exactly `implementation_evidence_git_sha`. The report's validated bytes
must bind that same SHA, so `bound_evidence_git_sha` and
`implementation_evidence_git_sha` are byte-identical lowercase 40-hex values. The gate reads both
reports with `git show <report_commit>:RUN_REPORT.md`; it never treats current working-
tree `RUN_REPORT.md` bytes as either historical phase report.
Each record is added only after its report-only commit already exists, in a dedicated
run-manifest state-index commit whose changed-path set is exactly
`docs/RUN_MANIFEST.yaml`; the record does not contain that later indexing commit and has
no self-hash. Subsequent run-manifest commits must preserve its canonical record.

Here and below, record equality is canonical-record equality, not textual YAML-subtree
equality. A strict duplicate-key-rejecting YAML loader converts the closed record to the
JSON data domain. `CanonicalRecordBytes(value)` is UTF-8 JSON from
`json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
allow_nan=False)`, with no BOM and no trailing newline. Strings must already be NFKC,
integers may not be booleans, and floats are not permitted in a phase record or artifact
ledger. `p2_phase_record_sha256` and `p3_phase_record_sha256` are lowercase SHA-256 of
these exact canonical bytes. A later whole-file YAML rerender may change whitespace,
comments, or key presentation but must parse to the same closed record and therefore the
same canonical bytes and hash.

`artifact_ledger_sha256` is not a path or a hash of the state-index commit. It is the
lowercase SHA-256 of `CanonicalRecordBytes(ArtifactLedger)`, reconstructed from Git. An
`ArtifactLedger` has exactly `schema_version=1, phase_id,
implementation_evidence_git_sha, report_commit_git_sha, members`. `members` is an array
sorted by unsigned UTF-8 path bytes; each member has exactly `path,
source_commit_git_sha, git_blob_id, sha256`. For every non-report member,
`source_commit_git_sha` is the implementation/evidence SHA; for `RUN_REPORT.md` it is
the report commit SHA. The validator obtains each blob with
`git rev-parse <source_commit>:<path>` and its exact bytes with
`git cat-file blob <blob-id>`, then hashes those bytes independently. The exact P2
member set is:

```text
references/repos.yaml
references/repos.lock.yaml
references/p2-live-attempts.yaml
RUN_REPORT.md
```

The exact P3 member set is:

```text
experiments/00_source_audit/configs/operation-manifest.yaml
experiments/00_source_audit/results/compatibility.csv
references/licenses.md
docs/SOURCE_MAP.md
docs/MATURITY_LEDGER.md
experiments/00_source_audit/RESULTS.md
experiments/00_source_audit/INTERFACE_FINDINGS.md
<the single MuJoCo-smoke fragment path selected by the operation manifest>
RUN_REPORT.md
```

The manifest-selected fragment must be a distinct normalized repository-relative path
beneath `experiments/00_source_audit/results/fragments`; collision with another member
or path escape is invalid. The ledger excludes `docs/RUN_MANIFEST.yaml`, the phase
record, its later state-index commit, caches/checkouts, untracked files, and every path
not in the applicable exact list. Consequently neither the record hash nor ledger hash
can depend on the commit that publishes the record.

P2 creates and P3 reuses one shared command surface:

```text
uv run python scripts/publish_phase_record.py publish --phase p2|p3 \
  --implementation-evidence-git-sha <SHA> --report-commit-git-sha <SHA> \
  --run-manifest docs/RUN_MANIFEST.yaml
uv run python scripts/publish_phase_record.py validate --phase p2|p3 \
  --state-index-commit <SHA> --run-manifest docs/RUN_MANIFEST.yaml
```

`publish` requires a clean tree at the supplied report commit, verifies that commit's
single changed path and single parent, validates the report's bound SHA, reconstructs the applicable
ledger, derives every record field, and refuses a caller-supplied hash/blob/path. It is
create-only at `phase_records.<phase>`: an absent record may be added through one
descriptor-anchored atomic replacement of the manifest; a present canonical-equal
record is validation-only and a different record is refused. All other manifest data
and every earlier phase record must remain canonically equal. `validate` is read-only,
requires the state-index commit's only parent to be the report commit and its changed-
path set to be exactly `docs/RUN_MANIFEST.yaml`, reconstructs both record and ledger
from historical Git objects, and rejects any self-reference or later-commit member.
The P2 and P3 plans each require this exact third commit immediately after their
report-only commit and its postcommit validation.

`P3GateEvidence` is the closed JSON object `schema_version, p2_state, p3_state,
registry_sha256, p2_lock_sha256, run_manifest_capture_git_sha,
run_manifest_capture_git_blob_id, p2_phase_record_sha256, p3_phase_record_sha256,
p2_evidence_base_git_sha, p2_report_commit_git_sha, p2_report_git_blob_id,
p2_report_sha256, p2_state_index_commit_git_sha,
p2_state_index_run_manifest_git_blob_id, p3_implementation_evidence_git_sha,
p3_report_commit_git_sha, p3_report_git_blob_id, p3_report_sha256,
p3_state_index_commit_git_sha, p3_state_index_run_manifest_git_blob_id,
p3_operation_manifest_sha256, p3_compatibility_sha256, licenses_sha256,
source_map_sha256, p3_maturity_ledger_sha256, p3_results_sha256,
p3_interface_findings_sha256,
p3_mujoco_smoke_relative_path, p3_mujoco_smoke_sha256, p3_local_lane_open,
physical_deployment_allowed, remote_execution_allowed, runtime_network_allowed`.
`p2_evidence_base_git_sha`, `p2_report_commit_git_sha`,
`p2_report_git_blob_id`, and `p2_report_sha256` must equal the corresponding P2 record
values (`implementation_evidence_git_sha`, `report_commit_git_sha`,
`report_git_blob_id`, and `report_sha256`); the four P3 fields must equal the same four
corresponding P3 record values. The gate independently requires each record's
`bound_evidence_git_sha` to equal its implementation field and reconstructs its
`artifact_ledger_sha256` rather than copying either value without validation.
The remaining state and authority values are also derived, never caller supplied. From
the manifest blob at `run_manifest_capture_git_sha`, `p2_state` is exactly
`stages.p2`, `p3_state` is exactly `stages.p3`, and `p3_local_lane_open` is true only
when `lanes.platform == "in_progress"`; any other capture value is rejection.
`physical_deployment_allowed` is exactly
`safety.physical_deployment_allowed`, while `remote_execution_allowed` is the renamed
gate projection of `safety.remote_enabled`. Both must be the JSON boolean false.
`runtime_network_allowed` is not read from an absent run-manifest field: it is a
schema-fixed false literal describing every P9 runtime/audit command. The distinct
`source_checkout_network_allowed=true` capability exists only in the later sealed P9
operation manifest and can authorize only `fetch_sources.py`.
The four state-index fields are derived rather than caller supplied. Starting at
`run_manifest_capture_git_sha`, the gate walks at most 4,096 commits along the sole
first-parent chain using the fixed local Git read surface. For each phase it must find
exactly one chain commit whose only parent is that phase's report commit; that child is
the state-index commit. Reaching a merge, the root, or the ceiling before finding both
children is rejection, as is finding either report commit outside the capture ancestry.
The derived child must change exactly `docs/RUN_MANIFEST.yaml`. Its recorded manifest
blob ID is obtained from that child, and the blob is read and parsed with the same
duplicate-key-rejecting loader used for the current manifest.

For P2, the report-parent manifest must have no `phase_records.p2`, the state-index blob
must introduce exactly the reconstructed canonical P2 record, and every other parsed
manifest value must remain canonically equal. For P3, the report-parent manifest must
have no `phase_records.p3`, its canonical P2 record must already equal the sealed P2
record, the state-index blob must add exactly the reconstructed canonical P3 record, and
every other value must remain canonically equal. Thus neither a later insertion nor a
multi-path/nonadjacent commit can masquerade as the required index operation. These
later P9-gate fields do not enter either phase record or artifact ledger and therefore
introduce no self-reference.
States must be `complete`, the lane boolean true, and all three authority booleans
false. File hashes are lowercase 64-hex, Git SHAs lowercase 40-hex, and Git blob IDs
the repository's validated object format. The P9 factory
rehashes every immutable named artifact rather than trusting this summary. The smoke path must be the
single MuJoCo-smoke fragment identity selected from the hash-matched P3 operation
manifest, be relative beneath P3's fragment root, and hash to the recorded value.
The `p3_maturity_ledger_sha256` is computed from the `docs/MATURITY_LEDGER.md` blob at
`p3_implementation_evidence_git_sha`, not from the later current worktree ledger. The
`--p3-maturity-ledger` argument supplies only that normalized historical path identity;
the gate obtains its blob and bytes through the sealed P3 evidence commit. Every
P9 subcommand, including authoring, validation, fetch, inventory, discovery, issue,
freeze, report, check, state publication, and the umbrella command, reruns this complete
historical gate before it reads a checkout or creates output.

Gate creation records the clean capture commit and Git blob of
`docs/RUN_MANIFEST.yaml`, extracts both historical phase records, derives and seals both
state-index commit/manifest-blob pairs by the bounded procedure above, and validates
every named Git commit/blob/content identity. Later commands validate the committed
`p3-gate.json` seal, rederive both state-index pairs from the sealed capture ancestry,
and revalidate those historical objects. They also perform a separate
current-state non-regression check: the current run manifest must still contain
canonical-record-equivalent P2/P3 phase records, `stages.p2 == stages.p3 == complete`,
`safety.physical_deployment_allowed == false`, and `safety.remote_enabled == false`.
The platform lane may be only `in_progress | complete`; later `current_pass`, other
stage/lane, P9, maturity, and report fields may advance. The sealed
`runtime_network_allowed=false` literal is revalidated independently. Current
`RUN_REPORT.md` is deliberately outside this non-regression identity. Therefore a P4-P8
pass or P9's own maturity/state/report commit cannot invalidate or be misidentified as P3
evidence, and the two historical reports cannot alias merely because they reused one
pathname.

P9 reuses only P3's reviewed low-level `CheckoutSpec`, `checkout_sparse`, and
create-only checkout-evidence writer through a P9-owned static-audit launcher. It
does not call or modify `eligible_checkout_specs`, `scripts/fetch_reference.py`, or
the P3 CLI. P3's CLI remains restricted to the original eight `SPARSE_REFERENCE`
repositories used by Experiments 01-03.

The sole P9 authority constructor is:

```text
p9_checkout_specs(
    registry: SourceRegistry,
    lock: SourceLock,
    p3_gate: P3GateEvidence,
    manifest: R1SourceOperationManifest,
) -> tuple[CheckoutSpec, ...]
```

`R1SourceOperationManifest` is a closed object with `schema_version,
experiment_id=08_unitree_r1, registry_sha256, p2_lock_sha256,
p3_gate_evidence_sha256, implementation_git_sha, max_source_bytes=2147483648,
max_total_bytes=5368709120, command_timeout_s=3600,
physical_deployment_allowed=false, remote_execution_allowed=false,
runtime_network_allowed=false, source_checkout_network_allowed=true,
repository_operations`. The final boolean authorizes only Section 4's low-level Git
subprocess and is rejected by every other command. Each of the exactly five
repository rows has `name, url, reuse_mode, commit_sha, license_status, license_spdx,
ordered_selected_paths, ordered_missing_paths, allowed_formats,
disposition=STATIC_SOURCE_INSPECTION_ONLY`. Extra fields, rows, modes, or operations
are invalid.

It constructs specs only for the following exact five
registry entries whose Experiment 08 modes explicitly permit source inspection, and
binds them in a new `08_unitree_r1` operation manifest:

| role | repository | allowed use |
|---|---|---|
| primary R1 training/simulation | `unitree_rl_mjlab` | static selected-path inspection |
| simulator/model cross-check | `unitree_mujoco` | static selected-path inspection |
| physical message contract | `unitree_sdk2` | static inspection only; never import/build/run |
| VLA deployment-order cross-check | `unifolm_vla` | static selected-path inspection only |
| WMA deployment-order cross-check | `unifolm_wma` | static selected-path inspection only |

All spec fields are derived afresh from the validated registry/lock, never accepted
from caller text. The name must be in the literal table, `08_unitree_r1` must be in
its registry experiments, URL/mode/40-hex SHA/license must exactly match the complete
lock, and sparse patterns are the registry's ordered selected paths filtered only by
locked `EXISTS`. The operation manifest may narrow operations within those materialized
paths but cannot add, rename, glob-expand, or substitute a path. A locked `MISSING`
path is recorded, never
silently widened to a full checkout. Git submodules, LFS payloads, binaries, archives,
checkpoints, and generated caches are not materialized. Individual files above 4 MiB
may exist inside a selected sparse directory but are inventoried and rejected from
parsing; the inherited checkout-wide byte cap still applies.

The pre-fetch operation manifest binds registry bytes/hash, the complete closed P2/P3
gate object/hash, each
exact commit and license status, selected patterns, exact expected Git command vectors,
timeouts/byte caps, and the fixed disposition `STATIC_SOURCE_INSPECTION_ONLY`. The
post-fetch fragments bind actual command results, file inventories, checkout bytes,
and content hashes. Fragments retain P3's exact `CHECKOUT` schema and writer; P9 adds
no evidence subtype. They live only beneath the P9 fragment root and are enumerated by
the P9 manifest. P3 consolidation accepts only fragment identities sealed by P3's own
all-45 operation manifest, so it rejects these P9 identities. They can never change a
P3 compatibility classification or make a `REMOTE_ONLY` repository locally runnable.

P9 treats `unitree_rl_mjlab` as primary. Supporting sources may corroborate or expose a
conflict but cannot silently replace a missing primary R1 definition. G1 or H1 symbols
are never relabelled as R1.

The constructor and launcher reject any sixth name, registry mode outside `REMOTE_ONLY |
PAPER_AND_CODE_REFERENCE | SPARSE_REFERENCE`, experiment mismatch, unobserved license
evidence, missing P2 path, or request to build/import/run. It adds no new shared reuse
mode and cannot be invoked for a different experiment. Tests prove the P9 factory
cannot authorize another repository or path and that the unchanged P3 selector/CLI
still returns only its original eight repositories.

## 4. Static-reader safety

`StaticSourceReader` opens the checkout root and every path descriptor-relatively with
no-follow semantics, requires regular files under the manifest inventory, verifies
size and SHA-256 before parsing, and exposes immutable bytes plus line offsets. It
rejects symlinks at every component, hard-link count other than one, device/FIFO/socket
files, changed inode/size/hash, NUL-containing text, DTD/entity XML, unsafe YAML tags,
duplicate mapping keys, nonfinite numbers, and path escape.

Allowed inert formats are bounded UTF-8 Python/C/C++/Markdown text, JSON, YAML through
`yaml.safe_load`, and XML/MJCF/URDF through a no-DTD standard-library streaming pull
parser after an explicit byte-level `<!DOCTYPE`/`<!ENTITY` rejection. Python first runs
a bounded `tokenize` pre-pass that aborts on more than 250,000 tokens, bracket/indent
nesting above 64, invalid tokenization, or a scalar-token payload above 1 MiB; only then
may it call `ast.parse`, followed by the node/depth checks. XML counts live open depth,
nodes, attributes, and accumulated text while feeding at most 64-KiB chunks and clears
closed elements immediately. Its exact live ceilings are depth 64, 100,000 elements,
10,000 attributes on one element, 100,000 attributes total, and 1 MiB text for one
scalar; it aborts at a ceiling before a full tree can grow. C/C++
constants use a closed token grammar, not compilation or a general preprocessor.
Every parser additionally enforces the Section 5 node/depth/alias/scalar ceilings
before materializing a value. No upstream module is imported.

`audit.py`, `freeze`, `report`, `check`, and tests reject network, LLM, remote,
physical, or deployment enablement before checkout reading or output creation. The
sole exception is `fetch_sources.py`, which invokes only P3's low-level
`checkout_sparse` with the P9 factory's specs. That subprocess retains P3's exact
credential-free, prompt-free, proxy-free, redirect-disabled Git environment, local
hook/fsmonitor neutralization, detached locked-SHA verification, dirty/mismatched
checkout refusal, descriptor-anchored no-follow publication, and finite timeouts.
It may contact only the five exact registry-derived GitHub origins. Actual bytes must be
`<= 2147483648` per repository and `<= 5368709120` cumulatively; equality is valid and
only `>` is refusal. Before each checkout the supervisor obtains an immutable reservation
bounded by both the per-source cap and remaining cumulative allowance, records it before
launch, and refuses to launch unless the requested reservation is positive and covers
the checkout's declared maximum. Completion atomically converts reserved to actual bytes;
failure releases only that checkout's reservation while retaining its attempt evidence.
Fetch evidence records attempted and actual download/disk bytes. Exceeding either cap
is `BLOCKED_RESOURCE`, never compatibility or mapping evidence. No issue URL or other
endpoint is fetched by this exception, and it never enables runtime/deployment
networking.

## 5. Discovery and reviewed freeze

Discovery is a deterministic two-step static process. `inventory` walks repositories
in the literal Section 3 table order and paths by unsigned UTF-8 POSIX bytes. It uses
descriptor-relative no-follow traversal, inventories every entry, and parses only
regular files within locked `EXISTS` roots whose extension is in the closed format
set. Per repository it permits at most 25,000 inventory entries, 10,000 parseable
files, and 512 MiB of eligible text; the whole five-repository pass permits at most
50,000 parseable files and 2 GiB of eligible text. An excess produces
`BLOCKED_RESOURCE` without a partial fact set. A file is read once into at most
4 MiB immutable bytes and rehashed against the inventory immediately before parse.

The neutral inventory records `(repository, relative_path, file_sha256, byte_count,
format, ordered structural_symbols)` but no mapping value. From that inventory a
reviewed, create-only `extraction-rules.yaml` freezes exact rules before fact discovery.
Each rule has exactly `rule_id, repository, relative_path, file_sha256, format,
selector, fact_kind, expected_cardinality, model_rule_ids`. `MODEL_ID` rules require
`model_rule_ids=()`; every other potentially authoritative rule cites one or more
same-repository `MODEL_ID` rule IDs. Rules sort by `rule_id`; IDs are unique
NFKC ASCII identifiers. A selector is one of:

```text
PY_SYMBOL(module_assignment_name, nested_key_or_index_path)
YAML_PATH(key_or_index_path)
JSON_PATH(key_or_index_path)
XML_ATTR(element_path, attribute_name)
CPP_ENUM(enum_name, enumerator_name)
CPP_CONST(qualified_name)
TEXT_LITERAL(line_number, token_number)
```

Paths and selectors must resolve exactly once unless the positive integer
`expected_cardinality` says otherwise. A rule cannot contain a candidate value,
fallback selector, regex, executable expression, or source path absent from the
neutral inventory. Missing, extra, ambiguous, or changed resolution emits
`MISSING | CONFLICT | UNSUPPORTED_EXPRESSION`; it never searches nearby text.

Inventory completes at a clean implementation SHA. Extraction rules are then reviewed,
validated, committed alone create-only, and bind the inventory hash plus that clean base
SHA before `discover` may run; modifying a rule requires a new inventory/rules revision.
After discovery, `reviewed-mapping.yaml` may select only existing fact IDs and closed
rationale enums. It binds discovery/rules hashes and the clean review-base SHA. Because
a file cannot contain the SHA of the commit containing itself, downstream stages bind
each operation manifest, extraction rules file, and reviewed mapping by all three of its
sealing commit SHA, Git blob ID, and SHA-256 content hash. No stage may rewrite an
earlier artifact or reuse a later-stage file as an earlier input.

The expression grammar is closed. Python permits `Constant` values limited to null,
bool, UTF-8 string, integer, or finite binary64; list/tuple; string-key dict; unary
`+/-` numeric; and binary numeric `+,-,*,/` with division by zero rejected. Names,
attributes, calls, comprehensions, subscripts outside the selector path, f-strings,
imports, and control flow are unsupported. JSON/YAML values use the same scalar/list/
string-key mapping domain. C/C++ permits decimal/hex integers, finite decimal floats,
quoted strings, unary sign, and explicit enum auto-increment from a sourced integer;
macros, casts, templates, conditionals, includes, and general preprocessing are
unsupported. XML supplies only literal attributes and element order.

Parser ceilings are per file: 250,000 lexical tokens, 100,000 syntax/data nodes,
maximum depth 64, maximum scalar UTF-8 payload 1 MiB, maximum collection width
10,000, and maximum 32 YAML anchors plus 32 alias uses. JSON nesting is counted by a
string-aware pre-scan before `json.loads`; YAML tokens/aliases and the acyclic composed
node graph are bounded before `safe_load`; Python uses the bounded tokenize pre-pass
before AST allocation and an explicit-stack AST check afterward; XML uses the live
streaming ceilings in Section 4 without retaining a complete tree. Remaining data graphs
use an explicit stack and the same node/depth ceilings. Cycles, duplicate keys, or an alias
expanded-node visit count above 250,000 are rejected. Discovery emits at most 20,000
facts per repository and 50,000 total; Section 8's tracked-evidence byte cap remains
the stricter bound.

Discovery emits facts, not an approved mapping. A `SourceFact` contains:

```text
fact_id
repository
commit_sha
relative_path
file_sha256
line_start
line_end
symbol
fact_kind
canonical_value
parser_rule_id
extraction_rules_sha256
model_fact_ids
```

`canonical_value` is sorted canonical UTF-8 JSON with no NaN/Infinity and NFKC
strings. `fact_id` is lowercase SHA-256 of canonical JSON over every field except
`fact_id`, including the extraction-rules SHA-256. Line spans are one-based inclusive;
XML/JSON/YAML selectors also retain the parser-computed byte span. Facts sort by
`(repository, relative_path, line_start, line_end, parser_rule_id, fact_id)` and are
written once. Re-running validates and skips byte-identical output only.
`MODEL_ID` facts have `model_fact_ids=()`; every other potentially authoritative fact
must cite the sorted facts produced by its frozen `model_rule_ids`. A missing,
ambiguous, non-R1, or cross-repository model link is non-authoritative
and classified `NON_R1` rather than inferred from repository identity.

Closed fact kinds are `MODEL_ID`, `SIM_ACTUATOR_SEQUENCE`, `SDK_SLOT_DOMAIN`,
`SIM_OBSERVATION_SCHEMA`, `TRAINING_OBSERVATION_SCHEMA`,
`TRAINING_ACTION_SEQUENCE`, `DEPLOYMENT_ACTION_SEQUENCE`, `JOINT_NAME`,
`ACTUATOR_NAME`, `SIM_INDEX`,
`OBSERVATION_COMPONENT_NAME`, `SIM_OBSERVATION_INDEX`,
`TRAINING_OBSERVATION_INDEX`, `OBSERVATION_SCALE`, `OBSERVATION_OFFSET`,
`TRAINING_ACTION_INDEX`, `TRAINING_ACTION_SCALE`, `TRAINING_ACTION_OFFSET`,
`DEPLOYMENT_ACTION_INDEX`, `SDK_JOINT_NAME`,
`SDK_MOTOR_SLOT`, `COMMAND_SIGN`, `STATE_SIGN`, `POSITION_OFFSET`, `LOWER_LIMIT`,
`UPPER_LIMIT`, `EFFORT_LIMIT`, `KP`, `KD`, `SKIPPED_SLOT`, `UNIT_SCHEMA`,
`QUANTITY_UNIT`, `COORDINATE_FRAME_SCHEMA`, `COORDINATE_FRAME`, `FRAME_PARENT`,
`FRAME_HANDEDNESS`, `FRAME_TRANSLATION_UNIT`, `FRAME_ROTATION_REPRESENTATION`,
`FRAME_TRANSFORM_DIRECTION`, `SIGNAL_QUANTITY`, `SIGNAL_FRAME`,
`SIMULATION_RATE`, `CONTROL_RATE`,
`CONTROL_DECIMATION`, `TIMESTAMP_CLOCK`, `TIMESTAMP_UNIT`,
`OBSERVATION_SCHEMA_VERSION`, and `ACTION_SCHEMA_VERSION`.
The seven sequence/schema collection facts have canonical value exactly
`{"size": nonnegative_integer, "ordered_ids": [NFKC_ASCII_string, ...]}` with array
length equal to `size` and unique IDs. `SDK_SLOT_DOMAIN` has canonical value exactly
`{"size": nonnegative_integer, "ordered_slots": [nonnegative_integer, ...]}`, with
unique strictly increasing slots and array length equal to `size`. These whole-collection
facts must come from source-declared collection definitions; discovery may not synthesize
them by grouping element facts. The two added collections are `UNIT_SCHEMA`, whose IDs
name every quantity appearing in the simulator/training/deployment action and observation
schemas plus limits/gains/timestamps, and `COORDINATE_FRAME_SCHEMA`, whose IDs name every
frame referenced by those schemas. An omitted referenced quantity or frame is a whole-
collection gap, not permission to infer a default.

Rate facts use canonical JSON `{"denominator": positive_integer,
"numerator_hz": positive_integer}` reduced to lowest terms. `CONTROL_DECIMATION` is a
positive integer and must prove `simulation_rate / control_rate` exactly; a nonintegral
ratio is `CONFLICT`. Unit facts contain exactly `quantity_id, unit, scale_to_si,
offset_to_si`, with finite binary64 scale/offset, nonzero scale, and unit from
`RADIAN | RADIAN_PER_SECOND | METER | METER_PER_SECOND | NEWTON_METER | SECOND |
NANOSECOND | HERTZ | DIMENSIONLESS | NEWTON_METER_PER_RADIAN |
NEWTON_METER_SECOND_PER_RADIAN`. No dimensional conversion is inferred from a variable
name. Frame facts contain only the closed literals defined in Section 6 and an exact
parent identity; they do not compute kinematics.

`SIGNAL_QUANTITY` has canonical value exactly `{"signal_id": string,
"quantity_id": string}`. `SIGNAL_FRAME` has canonical value exactly
`{"disposition": "NAMED_FRAME" | "NOT_FRAME_BEARING", "frame_id": string | null,
"signal_id": string}`; `frame_id` is nonnull exactly for `NAMED_FRAME`. Both facts
must resolve from an exact primary R1 source span, and a crossing-boundary signal also
requires consistent exact R1-tagged simulator/SDK/deployment evidence. A reviewed
decision cannot manufacture either association from a variable name, common robotics
practice, or another signal's dimensions.

The complete deterministic `signal_id` domain is generated from the accepted whole-
collection facts, never from the association rows themselves. It contains every element
of the simulator and training observation schemas; every element of the simulator,
training, and deployment action sequences; each row's simulator command/state and SDK
command/state value; and the row fields `training_action_scale,
training_action_offset, command_sign, state_sign, position_offset, lower_limit,
upper_limit, effort_limit, kp, kd`. It additionally contains simulation rate, control
rate, control decimation, timestamp, and every
source-declared normalization scale/offset. IDs are canonical ASCII namespaced as
`<domain>:<source-declared-member-id>` or
`row:<canonical-joint-name>:<closed-field-name>`. An association may use
`NOT_FRAME_BEARING`, but that disposition itself requires exact source provenance.

`TIMESTAMP_CLOCK` is exactly `MONOTONIC | WALL | UNDECLARED`; only exact static evidence
for `MONOTONIC` passes. Observation/action schema versions may be exact upstream
NFKC-ASCII identifiers or deterministic P9 identifiers
`r1obs-sha256:<64-lower-hex>` and `r1act-sha256:<64-lower-hex>`. A P9 identifier is the
SHA-256 of canonical JSON over the complete ordered collection facts and every accepted
fact ID referenced by the corresponding observation components or action/mapping rows,
including names, indices/slots, signs, scales, offsets, units, quantity/frame
associations, and ordering. It assigns no new semantics;
it gives later exports a reproducible identifier for the exact pinned source schema.

The discovery report groups facts by canonical source symbol and emits
`CONSISTENT | MISSING | CONFLICT | NON_R1 | UNSUPPORTED_EXPRESSION`. It never chooses
between conflicting facts. A reviewed freeze may approve a row only when the primary
R1 source and SDK evidence are each exact and every applicable R1-tagged supporting
order fact is consistent.
Every resolution records all candidate fact IDs, the selected fact IDs, one rationale
from `PRIMARY_AND_SDK_AGREE | PRIMARY_AND_SUPPORTING_AGREE |
PRIMARY_ONLY_NONCROSSBOUNDARY | NON_R1_CONTEXT_EXCLUDED | MISSING_PRIMARY |
CONFLICTING_R1_FACTS | UNSUPPORTED_EXPRESSION`, and `review_base_git_sha`. The review
base is the clean commit that precedes creation of `reviewed-mapping.yaml`; it is not the
later sealing commit and therefore creates no self-reference. Free-text rationale cannot
create a value.
Stage-0 resolutions require an exact primary R1 fact for every source-declared contract;
SDK or simulator supporting facts are required when that contract crosses the
simulation/deployment boundary, and any applicable exact R1-tagged disagreement is
`CONFLICT`. A deterministic schema digest selects the complete validated fact set rather
than a reviewer-authored value.
Only a supporting fact whose own `MODEL_ID` provenance resolves exactly to `R1` may
corroborate, conflict with, or gate an R1 row/order. `NON_R1` G1/H1/unknown-model facts
remain visible context but have zero authority and cannot block or support verification.

P9 does not fetch issue 52. The default issue record contains the canonical program
file SHA-256, cited line span, URL/number, pinned primary-source commit, and
`status=ISSUE_CONTEXT_NOT_RETRIEVED`, and makes no current-state claim. If the pinned
source itself contains an exact issue/fix reference, its SourceFact IDs and referenced
fix commit may be recorded as `SOURCE_REFERENCES_FIX`; this still makes no claim about
the live issue state. A separately authorized future metadata process may supply a
response hash/timestamp, but it is outside P9 and cannot affect verification. The issue
is context only and regression tests remain mandatory.

## 6. Frozen manifest contract

The lifecycle is
`DRAFT -> INVENTORIED -> RULES_FROZEN -> DISCOVERED -> REVIEWED -> FROZEN ->
VERIFIED | STOPPED`. Independently, prerequisites are `READY | BLOCKED`, artifact
validity is `VALID | INVALID`, the audit result is `VERIFIED | CONFLICT |
MISSING_R1_SOURCE | INCOMPLETE`, and advancement is `READY | STOPPED`. A prerequisite
block creates no evidence. Malformed/hash-mismatched evidence is artifact `INVALID`
and yields no audit result. A complete, well-formed conflict/missing/incomplete audit
is `VALID` and publishable but has advancement `STOPPED`. Only
`READY + VALID + VERIFIED + READY` advances to Phase 1; it still does not authorize
remote work without that phase's separate gate.

`r1_joint_mapping_manifest.yaml` contains:

```text
schema_version
model_id = R1
registry_sha256
p2_lock_sha256
p2_evidence_base_git_sha
p2_report_commit_git_sha
p3_gate_evidence_sha256
p3_implementation_evidence_git_sha
p3_report_commit_git_sha
operation_manifest_sha256
operation_manifest_sealing_git_sha
operation_manifest_git_blob_id
checkout_fragment_manifest_sha256
source_commits
source_inventory_sha256
extraction_rules_sha256
extraction_rules_sealing_git_sha
extraction_rules_git_blob_id
discovery_manifest_sha256
source_facts_sha256
reviewed_decisions_sha256
reviewed_decisions_sealing_git_sha
reviewed_decisions_git_blob_id
audit_implementation_git_sha
issue_52_context_sha256
simulator_actuator_count
simulator_actuator_sequence_fact_id
simulator_action_size
sdk_slot_domain
sdk_slot_domain_fact_id
skipped_sdk_slots
sdk_commanded_mask
simulator_observation_size
simulator_observation_schema_fact_id
training_observation_size
training_observation_schema_fact_id
observation_components
training_action_size
training_action_sequence_fact_id
training_observation_order
training_action_order
deployment_action_size
deployment_action_sequence_fact_id
deployment_action_order
unit_schema_fact_id
units
coordinate_frame_schema_fact_id
coordinate_frames
signal_quantity_bindings
signal_frame_bindings
simulation_rate
simulation_rate_fact_ids
control_rate
control_rate_fact_ids
control_decimation
control_decimation_fact_ids
timestamp_clock
timestamp_clock_fact_ids
timestamp_unit
timestamp_unit_fact_ids
observation_schema_version
observation_schema_version_origin
observation_schema_version_fact_ids
action_schema_version
action_schema_version_origin
action_schema_version_fact_ids
export_inventory
export_schema_carriage_status
collection_field_status
stage0_field_status
rows
lifecycle_state
prerequisite_state
artifact_state
audit_result
advancement_state
```

Each row has exact `canonical_joint_name`, `mjcf_joint`, `mjcf_actuator`,
`simulator_index`, `training_action_index`, `deployment_action_index`,
`training_action_scale`, `training_action_offset`, `sdk_joint_name`, `sdk_motor_slot`,
`command_sign`, `state_sign`, `position_offset`,
`lower_limit`, `upper_limit`, `effort_limit`, `kp`, `kd`, and a nonempty sorted
`source_fact_ids` tuple plus `field_status`, an exact mapping from every sourced field
name to `CONSISTENT | MISSING | CONFLICT`. Numeric values are finite float64; signs are
exactly `-1` or `+1`; limits require lower < upper; indices/slots are nonnegative
integers; `training_action_scale` is nonzero. A value absent from source is null with
status `MISSING`, never zero/default.
Lower/upper limits are simulator-state limits; SDK-state boundary goldens apply the
state formula and reverse endpoints when `state_sign=-1`. Effort limits and gains
remain positive source values and are not sign-flipped.

`sdk_slot_domain` is the exact strictly increasing contiguous tuple beginning at zero
and ending at the greatest exact R1-tagged SDK-domain slot. `skipped_sdk_slots` is a
strictly increasing subset. Row slots are unique, and row slots plus skipped slots are
an exact disjoint partition of the domain. `sdk_commanded_mask` is a boolean tuple of
domain length and is true exactly at row slots; numeric SDK arrays remain float64 and
never contain an object sentinel. `NOT_COMMANDED` is the name of mask=false in reports,
not an array value.

Each `observation_components` row has exactly:

```text
component_id
source_kind = SIM_JOINT_POSITION | SIM_JOINT_VELOCITY | BASE_ANGULAR_VELOCITY |
              PROJECTED_GRAVITY | COMMAND | CLOCK | OTHER_SOURCE_DECLARED
source_start
source_stop
training_start
training_stop
element_names
source_to_training_permutation
scale
offset
source_fact_ids
```

Ranges are half-open nonnegative integers, widths are equal and positive,
`element_names` has that width, the permutation is a bijection over `0..width-1`, and
scale/offset are finite float64 tuples of that width. Components sorted by source start
partition `0..simulator_observation_size-1` without gap/overlap; sorted by training
start independently partition `0..training_observation_size-1`. The global
`training_observation_order` is exactly the concatenated training-side element names.
`OTHER_SOURCE_DECLARED` is legal only with exact R1-tagged facts and never guesses a
semantic label.

Each `units` row has exactly `quantity_id, unit, scale_to_si, offset_to_si,
source_fact_ids, field_status`; when the unit schema is consistent, rows follow its
order and IDs are unique,
`field_status` maps the three value fields to `CONSISTENT | MISSING | CONFLICT`, and
every row retains at least its exact R1-tagged collection-fact provenance. A missing or
conflicting value is null rather than defaulted. A missing/conflicting collection has no
approved rows and remains visible in the reviewed candidate ledger. Each `coordinate_frames` row has exactly
`frame_id, parent_frame_id, handedness, translation_unit, rotation_representation,
transform_direction, source_fact_ids, field_status`, follows the same collection and
status/null rules, and is ordered by the frame schema. Parent is null with `CONSISTENT` only for the one declared root;
otherwise it names another row. The graph is connected, acyclic, has one root, and every
frame referenced by a schema member exists. Handedness is `RIGHT_HANDED | LEFT_HANDED`,
translation unit is a unit-schema ID whose resolved unit is `METER`, rotation is
`QUATERNION_WXYZ | QUATERNION_XYZW | ROTATION_MATRIX_ROW_MAJOR | AXIS_ANGLE | EULER_XYZ`,
and direction is `PARENT_FROM_CHILD | CHILD_FROM_PARENT`. A convention missing from
source remains null/`MISSING`; P9 never supplies a robotics default.

`signal_quantity_bindings` and `signal_frame_bindings` each contain exactly one row for
every ID in the deterministic signal domain and no other row. A quantity binding has
exactly `signal_id, quantity_id, source_fact_ids, field_status`; its quantity names a
consistent unit row. A frame binding has exactly `signal_id, disposition, frame_id,
source_fact_ids, field_status`; `frame_id` names a consistent frame row exactly for
`NAMED_FRAME`, and is null exactly for source-proven `NOT_FRAME_BEARING`. Both arrays
sort by unsigned UTF-8 `signal_id`, require nonempty fact provenance, and reject a
missing, duplicate, conflicting, or invented association. Consequently every action,
observation, normalization, state, limit, effort, and gain value has an explicit unit
and an explicit named-frame or not-frame-bearing disposition.

`export_inventory` is the closed object `schema_version=1, scope_roots,
ordered_export_paths, disposition, inventory_sha256`. `scope_roots` is exactly
`["experiments/08_unitree_r1"]`; `ordered_export_paths` must be empty; and
`disposition` is exactly `NO_EXPORTS_IN_SCOPE`. Its digest covers a descriptor-safe
inventory of every tracked and untracked regular file beneath that root and rejects
model/checkpoint/ONNX/TorchScript/safetensors or equivalent export extensions there;
the five ignored sparse-source checkouts live outside the scope root and are never
traversed. `export_schema_carriage_status` is exactly
`NO_EXPORTS_IN_SCOPE`, not `CONSISTENT` or `VERIFIED`. Any later exported model makes
this P9 disposition stale and must pass a separate schema-carriage gate against the
frozen observation/action identifiers before policy evaluation.

`collection_field_status` maps exactly `simulator_actuator_sequence,
sdk_slot_domain, simulator_observation_schema, training_observation_schema,
training_action_sequence, deployment_action_sequence, unit_schema,
coordinate_frame_schema` to `CONSISTENT | MISSING | CONFLICT`. A non-consistent
collection fact ID is null and its candidate fact IDs remain in the reviewed decision
ledger, allowing a valid nonpassing audit without fabricating a collection.
`stage0_field_status` maps exactly `signal_quantity_bindings, signal_frame_bindings,
simulation_rate, control_rate, control_decimation, timestamp_clock, timestamp_unit,
observation_schema_version, action_schema_version` to
`CONSISTENT | MISSING | CONFLICT`. A non-consistent field is null, retains every
available candidate fact ID, and cannot pass; for either binding-table field the
corresponding approved array is empty and all candidate associations remain only in the
reviewed decision ledger. Consistent `simulation_rate` and
`control_rate` are the reduced rational objects from Section 5 and their fact-ID tuples
are nonempty. `control_decimation` is a positive integer with
nonempty provenance and exactly relates the two rates. `timestamp_clock` must be
`MONOTONIC` for verification, and `timestamp_unit` must resolve through the unit schema
to `SECOND` or `NANOSECOND`; both have nonempty fact-ID tuples. Schema version origin is
`UPSTREAM_DECLARED | P9_SOURCE_DIGEST`. An upstream version cites its exact version fact;
a digest version cites every fact included in the canonical digest and is independently
recomputed by `freeze`, `check`, and pytest. The frozen observation and action version
identifiers are the values that every later exported model and adapter must carry; P9
does not export a model or create that adapter.

For `VERIFIED`, the eight top-level collection fact IDs must resolve to exact R1-tagged facts whose
canonical values declare the whole source collection, including its length and ordered
member identifiers. Counts, sizes, domains, and orders are copied from those facts, not
computed from accepted rows/components. Components exactly partition the two
source-declared observation domains. Rows exactly partition the source-declared
simulator, training-action, and deployment-action domains without gap or overlap, and
the row name at each index equals the corresponding declared sequence member.
`training_action_order` and `deployment_action_order` therefore reproduce, rather than
invent, their source-declared sequences. All order/permutation/component values have
nonempty SourceFact provenance. An omitted middle or trailing source member is a gap
even when every retained row is internally consecutive.

The audit result is `VERIFIED` only when every primary simulated actuator has exactly
one row, every required row field is sourced, all order arrays have exact coverage,
all observation components partition both domains, the SDK partition/mask is exact,
all source-declared quantities and named frames have exact nondefaulted contracts, both
signal-association tables exactly cover the deterministic signal domain,
rates and their decimation agree exactly, timestamp semantics are explicitly monotonic,
both schema versions reproduce, export disposition is exactly `NO_EXPORTS_IN_SCOPE`,
every Stage-0 and row field status is `CONSISTENT`, only
R1-tagged supporting evidence participates, and every pure manifest-validator
predicate invoked by `freeze` passes. The independent pytest command reruns those
predicates and adversarial fixtures as a final advancement gate; it does not mutate or
retroactively supply a manifest field.
`CONFLICT`, `MISSING_R1_SOURCE`, and `INCOMPLETE` are nonpassing audit outcomes; they
do not authorize a thin adapter or later R1 execution. `INVALID` is solely an artifact
state and is never a publishable scientific/audit outcome.

## 7. Pure mapping semantics and tests

The project-local test adapter is pure NumPy and cannot import a Unitree module:

```text
sim_command_to_sdk(a_sim) -> (sdk_command_values, sdk_commanded_mask)
sdk_command_to_sim(sdk_command_values, sdk_commanded_mask) -> a_sim
sim_state_to_sdk(q_sim) -> (sdk_state_values, sdk_mapped_mask)
sdk_state_to_sim(sdk_state_values, sdk_mapped_mask) -> q_sim
sim_action_to_training(a_sim) -> a_train
training_action_to_sim(a_train) -> a_sim
sim_action_to_deployment(a_sim) -> a_deploy
training_observation_from_sim(obs_sim) -> obs_train
```

For row `i`, the four SDK transforms are independent exact pairs:

```text
sdk_command[slot_i] = command_sign_i * sim_command[simulator_index_i]
                      + position_offset_i
sim_command[simulator_index_i] = command_sign_i
                      * (sdk_command[slot_i] - position_offset_i)

sdk_state[slot_i] = state_sign_i * sim_state[simulator_index_i]
                    + position_offset_i
sim_state[simulator_index_i] = state_sign_i
                    * (sdk_state[slot_i] - position_offset_i)
```

Because signs are exactly ±1, each pair round-trips independently even when command
and state signs differ. A command-forward result is never fed to the state inverse as
a round-trip assertion. Cross-channel correctness instead uses frozen source-derived
goldens: for every row, `(sim command zero, expected SDK command)`, `(SDK state at
offset, expected sim state zero)`, positive/negative one-hot command fixtures, and
lower/upper SDK-state fixtures. Each expected value cites fact IDs from both primary
R1 and SDK sources. A sign convention that cannot satisfy these independent goldens is
`CONFLICT`, not normalized away.

SDK arrays are domain-length float64 initialized to `0.0` only as an ignored storage
value; the separately returned boolean mask is authoritative and must equal the frozen
mask on inverse input. A false-mask slot is never read, compared as a command, or
called a hold value. `training_action_to_sim` writes
`training_action_scale * a_train[training_action_index] + training_action_offset` at
the simulator index; its inverse subtracts the offset and divides by the required
finite nonzero scale. `sim_action_to_training` is that inverse. Here `a_sim` is the
official decoder's simulator joint-position target, not an unscaled policy latent.
`sim_action_to_deployment` writes
`command_sign * a_sim[simulator_index] + position_offset` at each deployment index.
For observation component `c` and local target index `j`:

```text
obs_train[c.training_start + j] =
    c.scale[j] * obs_sim[c.source_start + c.source_to_training_permutation[j]]
    + c.offset[j]
```

No reshape, omitted component, inferred width, or broadcasting is permitted.

All integer/name/permutation/mask tests use exact equality. Floating tests use
binary64 and `rtol=0`, with
`atol = 8 * finfo(float64).eps * max(1, max(abs(expected)))` per vector. The random
generator is NumPy `PCG64` seeded by the first 128 big-endian bits of SHA-256 over
canonical JSON `[mapping_manifest_sha256, "r1-mapping-random-v1"]`. It draws exactly
1,000 simulator vectors independently with NumPy `uniform(lower+m, upper-m)`, whose
lower endpoint remains strictly inside the physical limit, where
`m=max(1e-9, 8*eps*max(1,abs(lower),abs(upper)))`; a row without a nonempty interval
after this margin makes the audit `INCOMPLETE`.

Required tests cover exact joint-name/actuator coverage; unique simulator/training/
deployment indices,
SDK slots, and order positions; explicit skipped slots; zero mapping; every one-hot
simulator joint and SDK slot; independent command and state forward/inverse round
trips; the frozen cross-channel goldens; 1,000 hash-seeded random vectors strictly inside limits;
left/right arm isolation; waist/head/leg isolation; training observation order;
training action order; deployment action order; limit/sign/offset boundaries; source
fact/file/hash integrity; complete quantity-unit coverage; coordinate-frame graph,
handedness, rotation-order, and transform-direction validation; exact simulator/control
rate and decimation equality; monotonic timestamp and timestamp-unit validation; exact
observation/action schema-version regeneration; issue-52 regression fixture; and negative duplicate,
missing, conflict, symlink, unsafe-format, non-R1, network, remote, and physical cases.
Pure fixture tests also cover complete P2/P3 gate/hash rejection, exact five-name P9
factory authority, unchanged eight-name P3 CLI eligibility, registry/lock-only spec
derivation, cumulative download accounting without network, deterministic sorted
inventory/rules/fact IDs, every parser grammar boundary and node/depth/alias/file/byte
ceiling, non-R1 zero authority, lifecycle-state cross-products, create-only resume,
transitive provenance tamper, extra/missing artifact rejection, and byte-identical
report/check rerender; canonical test-receipt command/count/test-ID validation and
tamper rejection; exact four-path evidence plus three-path maturity/state/report
publication commits; maturity-ledger extra/missing row, invalid/multiple label, local-
reproduction mismatch, and hash tampering; failure after each of the three publication
renames plus crash-journal recovery with exact preimage restoration.
Checkout tests use a recording runner and local fixture trees;
no test performs Git or HTTP network access.

Coverage fixtures independently delete a middle and the trailing member from each
source-declared actuator, SDK-slot, observation, training-action, deployment-action,
unit, and coordinate-frame
collection while leaving retained rows consecutive; every case must fail exact partition
validation. Parser fixtures include deeply nested and high-token Python below 4 MiB and
deep/high-node XML below 4 MiB, and assert abort occurs in the tokenize pre-pass or live
XML stream before `ast.parse` or full-tree retention. Gate tests mutate each closed
historical-gate input in turn—including both immutable phase records, both historical
P2/P3 report lifecycles, both P3 result reports, the historical P3 maturity ledger, and
the manifest-selected smoke fragment—and assert every subcommand
fails before checkout read/output creation. Resource tests accept exactly 2147483648 and
5368709120 bytes, reject each cap plus one, prevent over-reservation before process
launch, and prove failure releases only its immutable reservation.
Authority-seal tests separately alter the sealing commit, Git blob ID, and SHA-256 for
each of the operation manifest, extraction rules, and reviewed mapping; freeze, check,
and byte-for-byte reproduction must reject every mutation.
Historical-gate fixtures advance current pass, permitted later stage/lane/P9 fields,
and replace the root report after preserving the immutable P2/P3 phase records, their
complete stage values, both false safety values, and a platform lane of `in_progress |
complete`; every P9 command must still
validate. They then mutate each phase record, historical report commit/blob/hash, bound
evidence SHA, state-index commit SHA, or state-index manifest blob ID and require
rejection before checkout read/output creation. Separate histories add an extra changed
path to an index commit, give it a non-report parent, insert the record only in a later
commit, alter an earlier phase record while adding the later one, place a report outside
the sealed capture ancestry, introduce a merge in the derivation chain, and exceed the
4,096-commit traversal ceiling; every case is rejected. Positive fixtures prove the
unique adjacent P2 and P3 children, exact one-path diffs, exact canonical-record
introductions, and preservation of all prior manifest values. Stage-0
negative fixtures cover a missing unit/frame at every collection position, disconnected
or cyclic frames, convention mismatch, nonintegral decimation, wall/undeclared clocks,
timestamp-unit mismatch, and one-bit schema-version drift.
For every deterministic signal ID, tests independently delete and corrupt its quantity
association and frame/disposition association, and assert that unrelated complete unit
and frame collections cannot make the audit pass. Export fixtures prove an empty P9
export inventory yields only `NO_EXPORTS_IN_SCOPE`, while one model-like artifact,
untracked or tracked, invalidates the disposition rather than being silently ignored.
Gate fixtures independently mutate `stages.p2`, `stages.p3`, `lanes.platform`,
`safety.physical_deployment_allowed`, `safety.remote_enabled`, and the fixed runtime-
network literal in the sealed capture/current-state pair. They prove each gate field is
derived from its named source and cannot be accepted from caller JSON.

## 8. Artifacts, commands, and publication

`R1_SOURCE_MAP.md` renders every accepted and conflicting source fact grouped by pinned
repository/path/symbol, including the complete mapping/order and Stage-0 unit/frame/rate/
clock/schema contracts and every signal-to-quantity/frame association.
`R1_JOINT_MAPPING_AUDIT.md` renders the closed lifecycle states,
all mapping and Stage-0 predicates, exact gaps/conflicts, test disposition, and the Phase-1
decision, including `NO_EXPORTS_IN_SCOPE` rather than an export-schema verification.
Both state explicitly that static source inspection proves declarations and
pure transforms only, not runtime timing, simulator compatibility, or hardware safety.
They are pure renderings of the frozen manifest and fact ledger, never independent
decision surfaces.

Required tracked outputs are:

```text
experiments/08_unitree_r1/configs/p3-gate.json
experiments/08_unitree_r1/configs/operation-manifest.yaml
experiments/08_unitree_r1/configs/extraction-rules.yaml
experiments/08_unitree_r1/configs/reviewed-mapping.yaml
experiments/08_unitree_r1/configs/base.yaml
experiments/08_unitree_r1/audit.py
experiments/08_unitree_r1/fetch_sources.py
experiments/08_unitree_r1/run.py
experiments/08_unitree_r1/tests/conftest.py
experiments/08_unitree_r1/results/checkout-fragments/unitree_rl_mjlab.json
experiments/08_unitree_r1/results/checkout-fragments/unitree_mujoco.json
experiments/08_unitree_r1/results/checkout-fragments/unitree_sdk2.json
experiments/08_unitree_r1/results/checkout-fragments/unifolm_vla.json
experiments/08_unitree_r1/results/checkout-fragments/unifolm_wma.json
experiments/08_unitree_r1/results/checkout-fragments/manifest.json
experiments/08_unitree_r1/results/source-inventory.json
experiments/08_unitree_r1/results/discovery/source-facts.jsonl
experiments/08_unitree_r1/results/discovery/manifest.json
experiments/08_unitree_r1/results/issue-52-context.json
experiments/08_unitree_r1/results/test-summary.json
experiments/08_unitree_r1/docs/R1_SOURCE_MAP.md
experiments/08_unitree_r1/docs/R1_JOINT_MAPPING_AUDIT.md
experiments/08_unitree_r1/results/r1_joint_mapping_manifest.yaml
experiments/08_unitree_r1/tests/test_r1_joint_mapping.py
```

Final publication also creates or updates the tracked orchestrator-owned
`docs/MATURITY_LEDGER.md`, `docs/RUN_MANIFEST.yaml`, and `RUN_REPORT.md` in the
dedicated three-path maturity/state/report commit below; they are not experiment-owned
implementation files.

The checkout-fragment manifest lists exactly the five repository fragment paths above,
sizes, and hashes and excludes itself. No glob is used by a writer or validator.
Every downstream manifest binds all upstream hashes listed in Section 6. Small
discovery facts, evidence digests, and reports are tracked; sparse checkouts and raw
source remain ignored. `test-summary.json` is canonical JSON with exact keys
`schema_version, command, implementation_git_sha, mapping_manifest_sha256,
junit_sha256, collected, passed, failed, skipped, errors, ordered_test_ids_sha256`.
`record-tests` accepts only the exact command and test module below, zero failures/errors,
nonnegative integer counts satisfying `collected=passed+failed+skipped+errors`, and an
XML suite containing only project-relative P9 test IDs; it renders no timestamps,
durations, hostnames, or raw failure text. The raw JUnit file remains untracked under
`/private/tmp`. Exact command shapes are:

The three authority files use the same create-only sealing protocol. Each author command
requires a clean tree before creation; each validator reruns the complete Section 3 gate,
accepts no unknown fields, and checks every upstream hash. `git add` names exactly one
authority file, `git diff --cached --name-only` must equal that one path, and the commit
is therefore single-purpose. Downstream validation finds the sealing commit with
`git log -1 --format=%H -- <path>`, requires that commit's changed-path set to equal the
one authority path, obtains its blob with `git rev-parse <seal>:<path>`, hashes those blob
bytes with SHA-256, and compares all three identities recorded downstream. Review input
under `/private/tmp` is untrusted, never published, and may contain only the closed
selector or fact-ID/rationale decision fields; the author command derives every other
field and refuses values not already in inventory/discovery evidence.

```text
test -z "$(git status --porcelain)"
uv run python experiments/08_unitree_r1/audit.py gate \
  --registry references/repos.yaml --lock references/repos.lock.yaml \
  --run-manifest docs/RUN_MANIFEST.yaml --historical-report-path RUN_REPORT.md \
  --p3-operation-manifest \
  experiments/00_source_audit/configs/operation-manifest.yaml \
  --compatibility experiments/00_source_audit/results/compatibility.csv \
  --licenses references/licenses.md --source-map docs/SOURCE_MAP.md \
  --p3-maturity-ledger docs/MATURITY_LEDGER.md \
  --p3-results experiments/00_source_audit/RESULTS.md \
  --p3-interface-findings experiments/00_source_audit/INTERFACE_FINDINGS.md \
  --p3-fragment-root experiments/00_source_audit/results/fragments \
  --output experiments/08_unitree_r1/configs/p3-gate.json --headless
git add -- experiments/08_unitree_r1/configs/p3-gate.json
test "$(git diff --cached --name-only)" = \
  experiments/08_unitree_r1/configs/p3-gate.json
git commit -m "exp08: bind P2 and P3 gate evidence"

test -z "$(git status --porcelain)"
uv run python experiments/08_unitree_r1/audit.py author-operation-manifest \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --registry references/repos.yaml --lock references/repos.lock.yaml \
  --output experiments/08_unitree_r1/configs/operation-manifest.yaml --headless
uv run python experiments/08_unitree_r1/audit.py validate-authority \
  --kind operation-manifest \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --path experiments/08_unitree_r1/configs/operation-manifest.yaml --headless
git add -- experiments/08_unitree_r1/configs/operation-manifest.yaml
test "$(git diff --cached --name-only)" = \
  experiments/08_unitree_r1/configs/operation-manifest.yaml
git commit -m "exp08: seal R1 source operation manifest"
uv run python experiments/08_unitree_r1/audit.py validate-authority-seal \
  --kind operation-manifest \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --path experiments/08_unitree_r1/configs/operation-manifest.yaml --headless

uv run python experiments/08_unitree_r1/fetch_sources.py --operation-manifest \
  experiments/08_unitree_r1/configs/operation-manifest.yaml \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --fragment-dir experiments/08_unitree_r1/results/checkout-fragments \
  --output-root external/checkouts --max-source-bytes 2147483648 \
  --max-total-bytes 5368709120 --headless
git add -- experiments/08_unitree_r1/results/checkout-fragments/unitree_rl_mjlab.json \
  experiments/08_unitree_r1/results/checkout-fragments/unitree_mujoco.json \
  experiments/08_unitree_r1/results/checkout-fragments/unitree_sdk2.json \
  experiments/08_unitree_r1/results/checkout-fragments/unifolm_vla.json \
  experiments/08_unitree_r1/results/checkout-fragments/unifolm_wma.json \
  experiments/08_unitree_r1/results/checkout-fragments/manifest.json
git commit -m "exp08: record bounded R1 source checkouts"

uv run python experiments/08_unitree_r1/audit.py inventory \
  --operation-manifest experiments/08_unitree_r1/configs/operation-manifest.yaml \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --checkout-fragment-manifest \
  experiments/08_unitree_r1/results/checkout-fragments/manifest.json \
  --checkout-root external/checkouts \
  --output experiments/08_unitree_r1/results/source-inventory.json --headless
git add -- experiments/08_unitree_r1/results/source-inventory.json
test "$(git diff --cached --name-only)" = \
  experiments/08_unitree_r1/results/source-inventory.json
git commit -m "exp08: freeze neutral R1 source inventory"

test -z "$(git status --porcelain)"
uv run python experiments/08_unitree_r1/audit.py author-extraction-rules \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --source-inventory experiments/08_unitree_r1/results/source-inventory.json \
  --review-input /private/tmp/exp08-extraction-rule-decisions.yaml \
  --output experiments/08_unitree_r1/configs/extraction-rules.yaml --headless
uv run python experiments/08_unitree_r1/audit.py validate-authority \
  --kind extraction-rules \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --path experiments/08_unitree_r1/configs/extraction-rules.yaml --headless
git add -- experiments/08_unitree_r1/configs/extraction-rules.yaml
test "$(git diff --cached --name-only)" = \
  experiments/08_unitree_r1/configs/extraction-rules.yaml
git commit -m "exp08: seal R1 extraction rules"
uv run python experiments/08_unitree_r1/audit.py validate-authority-seal \
  --kind extraction-rules \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --path experiments/08_unitree_r1/configs/extraction-rules.yaml --headless

uv run python experiments/08_unitree_r1/audit.py discover \
  --operation-manifest experiments/08_unitree_r1/configs/operation-manifest.yaml \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --source-inventory experiments/08_unitree_r1/results/source-inventory.json \
  --extraction-rules experiments/08_unitree_r1/configs/extraction-rules.yaml \
  --checkout-root external/checkouts \
  --facts-output experiments/08_unitree_r1/results/discovery/source-facts.jsonl \
  --manifest-output experiments/08_unitree_r1/results/discovery/manifest.json \
  --headless
git add -- experiments/08_unitree_r1/results/discovery/source-facts.jsonl \
  experiments/08_unitree_r1/results/discovery/manifest.json
git commit -m "exp08: record static R1 source facts"

uv run python experiments/08_unitree_r1/audit.py issue-context \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --program "Reflect Lite Research Program.md" \
  --source-facts experiments/08_unitree_r1/results/discovery/source-facts.jsonl \
  --output experiments/08_unitree_r1/results/issue-52-context.json --headless
git add -- experiments/08_unitree_r1/results/issue-52-context.json
test "$(git diff --cached --name-only)" = \
  experiments/08_unitree_r1/results/issue-52-context.json
git commit -m "exp08: record pinned issue 52 context"

test -z "$(git status --porcelain)"
uv run python experiments/08_unitree_r1/audit.py author-reviewed-mapping \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --discovery-manifest experiments/08_unitree_r1/results/discovery/manifest.json \
  --source-facts experiments/08_unitree_r1/results/discovery/source-facts.jsonl \
  --review-input /private/tmp/exp08-reviewed-mapping-decisions.yaml \
  --output experiments/08_unitree_r1/configs/reviewed-mapping.yaml --headless
uv run python experiments/08_unitree_r1/audit.py validate-authority \
  --kind reviewed-mapping \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --path experiments/08_unitree_r1/configs/reviewed-mapping.yaml --headless
git add -- experiments/08_unitree_r1/configs/reviewed-mapping.yaml
test "$(git diff --cached --name-only)" = \
  experiments/08_unitree_r1/configs/reviewed-mapping.yaml
git commit -m "exp08: seal reviewed R1 mapping decisions"
uv run python experiments/08_unitree_r1/audit.py validate-authority-seal \
  --kind reviewed-mapping \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --path experiments/08_unitree_r1/configs/reviewed-mapping.yaml --headless

uv run python experiments/08_unitree_r1/audit.py freeze \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --discovery-manifest experiments/08_unitree_r1/results/discovery/manifest.json \
  --source-facts experiments/08_unitree_r1/results/discovery/source-facts.jsonl \
  --issue-context experiments/08_unitree_r1/results/issue-52-context.json \
  --reviewed-decisions experiments/08_unitree_r1/configs/reviewed-mapping.yaml \
  --output experiments/08_unitree_r1/results/r1_joint_mapping_manifest.yaml --headless

PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_CACHE_DIR=.cache/uv uv run --offline pytest \
  -c /dev/null --rootdir=. --confcutdir=experiments/08_unitree_r1/tests \
  -p no:cacheprovider experiments/08_unitree_r1/tests/test_r1_joint_mapping.py -q \
  --junitxml=/private/tmp/exp08-junit.xml
uv run python experiments/08_unitree_r1/audit.py record-tests \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --mapping-manifest experiments/08_unitree_r1/results/r1_joint_mapping_manifest.yaml \
  --junit-input /private/tmp/exp08-junit.xml \
  --output experiments/08_unitree_r1/results/test-summary.json --headless

uv run python experiments/08_unitree_r1/audit.py report \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --mapping-manifest experiments/08_unitree_r1/results/r1_joint_mapping_manifest.yaml \
  --discovery-manifest experiments/08_unitree_r1/results/discovery/manifest.json \
  --issue-context experiments/08_unitree_r1/results/issue-52-context.json \
  --test-summary experiments/08_unitree_r1/results/test-summary.json \
  --source-map-output experiments/08_unitree_r1/docs/R1_SOURCE_MAP.md \
  --audit-output experiments/08_unitree_r1/docs/R1_JOINT_MAPPING_AUDIT.md --headless

git add -- experiments/08_unitree_r1/results/r1_joint_mapping_manifest.yaml \
  experiments/08_unitree_r1/results/test-summary.json \
  experiments/08_unitree_r1/docs/R1_SOURCE_MAP.md \
  experiments/08_unitree_r1/docs/R1_JOINT_MAPPING_AUDIT.md
test "$(git diff --cached --name-only)" = \
"experiments/08_unitree_r1/docs/R1_JOINT_MAPPING_AUDIT.md
experiments/08_unitree_r1/docs/R1_SOURCE_MAP.md
experiments/08_unitree_r1/results/r1_joint_mapping_manifest.yaml
experiments/08_unitree_r1/results/test-summary.json"

uv run python experiments/08_unitree_r1/audit.py check \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --operation-manifest experiments/08_unitree_r1/configs/operation-manifest.yaml \
  --checkout-fragment-manifest \
  experiments/08_unitree_r1/results/checkout-fragments/manifest.json \
  --source-inventory experiments/08_unitree_r1/results/source-inventory.json \
  --extraction-rules experiments/08_unitree_r1/configs/extraction-rules.yaml \
  --discovery-manifest experiments/08_unitree_r1/results/discovery/manifest.json \
  --source-facts experiments/08_unitree_r1/results/discovery/source-facts.jsonl \
  --issue-context experiments/08_unitree_r1/results/issue-52-context.json \
  --reviewed-decisions experiments/08_unitree_r1/configs/reviewed-mapping.yaml \
  --mapping-manifest experiments/08_unitree_r1/results/r1_joint_mapping_manifest.yaml \
  --test-summary experiments/08_unitree_r1/results/test-summary.json \
  --source-map experiments/08_unitree_r1/docs/R1_SOURCE_MAP.md \
  --audit-report experiments/08_unitree_r1/docs/R1_JOINT_MAPPING_AUDIT.md \
  --publication-state staged --headless

PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_CACHE_DIR=.cache/uv uv run --offline pytest \
  -c /dev/null --rootdir=. --confcutdir=experiments/08_unitree_r1/tests \
  -p no:cacheprovider experiments/08_unitree_r1/tests/test_r1_joint_mapping.py -q

git commit -m "exp08: publish R1 static audit evidence"

test -z "$(git status --porcelain)"
uv run python experiments/08_unitree_r1/audit.py publish-state \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --mapping-manifest experiments/08_unitree_r1/results/r1_joint_mapping_manifest.yaml \
  --audit-report experiments/08_unitree_r1/docs/R1_JOINT_MAPPING_AUDIT.md \
  --test-summary experiments/08_unitree_r1/results/test-summary.json \
  --p9-evidence-commit "$(git rev-parse HEAD)" \
  --maturity-ledger docs/MATURITY_LEDGER.md \
  --run-manifest docs/RUN_MANIFEST.yaml --run-report RUN_REPORT.md --headless
git add -- docs/MATURITY_LEDGER.md docs/RUN_MANIFEST.yaml RUN_REPORT.md
test "$(git diff --cached --name-only)" = \
"RUN_REPORT.md
docs/MATURITY_LEDGER.md
docs/RUN_MANIFEST.yaml"
git commit -m "docs: record P9 source audit result"

uv run python experiments/08_unitree_r1/audit.py check \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --operation-manifest experiments/08_unitree_r1/configs/operation-manifest.yaml \
  --checkout-fragment-manifest experiments/08_unitree_r1/results/checkout-fragments/manifest.json \
  --source-inventory experiments/08_unitree_r1/results/source-inventory.json \
  --extraction-rules experiments/08_unitree_r1/configs/extraction-rules.yaml \
  --discovery-manifest experiments/08_unitree_r1/results/discovery/manifest.json \
  --source-facts experiments/08_unitree_r1/results/discovery/source-facts.jsonl \
  --issue-context experiments/08_unitree_r1/results/issue-52-context.json \
  --reviewed-decisions experiments/08_unitree_r1/configs/reviewed-mapping.yaml \
  --mapping-manifest experiments/08_unitree_r1/results/r1_joint_mapping_manifest.yaml \
  --test-summary experiments/08_unitree_r1/results/test-summary.json \
  --source-map experiments/08_unitree_r1/docs/R1_SOURCE_MAP.md \
  --audit-report experiments/08_unitree_r1/docs/R1_JOINT_MAPPING_AUDIT.md \
  --maturity-ledger docs/MATURITY_LEDGER.md \
  --run-manifest docs/RUN_MANIFEST.yaml --run-report RUN_REPORT.md \
  --p9-evidence-commit "$(git rev-parse HEAD^)" \
  --state-report-commit "$(git rev-parse HEAD)" \
  --publication-state published --headless
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_CACHE_DIR=.cache/uv uv run --offline pytest \
  -c /dev/null --rootdir=. --confcutdir=experiments/08_unitree_r1/tests \
  -p no:cacheprovider experiments/08_unitree_r1/tests/test_r1_joint_mapping.py -q

UV_CACHE_DIR=.cache/uv uv run --offline python experiments/08_unitree_r1/run.py \
  --config experiments/08_unitree_r1/configs/base.yaml --seed 0 \
  --output-dir experiments/08_unitree_r1/results --max-episodes 0 --headless

make exp08-audit
```

The lifecycle through both publication commits is driven by the external orchestrator,
not by the experiment umbrella. `check --publication-state staged` requires the exact
four final files to be the only staged paths and validates them before the evidence
commit. `publish-state` is the sole controlled replacement writer: starting from a clean
evidence commit, it prepares and validates one bounded three-file transaction and then
atomically replaces each of `docs/MATURITY_LEDGER.md`, `docs/RUN_MANIFEST.yaml`, and
`RUN_REPORT.md`. It retains descriptor-verified preimages until every rename and parent
fsync succeeds; failure restores every already-renamed path, while crash recovery blocks
publication and restores the complete preimage triplet from the ignored bounded
mode-`0700`, 4-MiB-max `.cache/p9-publication-transaction` journal before retry. The
journal contains only exact path/hash/preimage tuples for those three paths, is opened
no-follow, and is removed only after inode/hash verification. No partial worktree state
is a published result. The maturity ledger has the exact columns
`project_or_component, evidence_label, evidence_source, supported_embodiment_or_task,
license, compute_requirements, local_reproduction_status, known_failure_modes,
role_in_program, hardware_validation_status`. P3 must already have published one row
for every locked public source plus its Experiment-00 result. P9 preserves every
non-Unitree/P3-result row byte-semantically, updates only the five pinned Unitree rows
with P9's stronger static evidence, and adds exactly one P9 audit-result row. Each row
has exactly one Section-34 `evidence_label`; source rows use
`PRODUCTION_SHAPED_REFERENCE | UNVERIFIED` only as their evidence permits. The P9 audit-result row uses `PHYSICAL_R1_NOT_VALIDATED`,
records `local_reproduction_status=LOCALLY_REPRODUCED_M2` only when its artifacts are
valid and tests pass, and records `hardware_validation_status=NOT_VALIDATED`. The P9 phase
record binds the evidence commit, result/manifests/reports,
`prerequisite_state`, `artifact_state`, `audit_result`, and `advancement_state`.
`phase_records.p9` is closed with exact keys `phase_id=p9, lifecycle_state=complete,
implementation_evidence_git_sha, evidence_publication_git_sha,
state_report_parent_git_sha, p3_gate_sha256, operation_manifest_sha256,
mapping_manifest_sha256, test_summary_sha256, source_map_sha256, audit_report_sha256,
maturity_ledger_sha256, prerequisite_state, artifact_state, audit_result,
advancement_state, maturity_label=PHYSICAL_R1_NOT_VALIDATED,
local_reproduction_status=LOCALLY_REPRODUCED_M2,
hardware_validation_status=NOT_VALIDATED,
physical_deployment_allowed=false, remote_execution_allowed=false,
runtime_network_allowed=false`; the parent equals the evidence publication commit, and
the postcommit validator derives and checks the containing three-path commit rather than
attempting an impossible self-hash. No scientific result is inferred from the lifecycle
state.
`RUN_REPORT.md` renders the canonical environment, commands, tests, results,
public-source use, interface findings, blockers, next action, maturity/hardware-
validation disposition, and safety sections. The
three files are committed together and no source/evidence path may be staged. A
`READY+VALID+VERIFIED+READY` result records P9 complete and opens the separately gated
Phase-1 lane; a valid `CONFLICT | MISSING_R1_SOURCE | INCOMPLETE` result also records P9
complete but advancement `STOPPED` and publishes its exact gap. Invalid evidence creates
neither state update nor report conclusion. The postcommit check requires the exact
adjacent evidence and maturity/state/report commits, their changed-path sets, and byte-identical
rerenders.

`run.py` is the strictly offline, read-only Experiment 08 Phase-0 final-validation
umbrella. It accepts exactly the standard `--config`, `--seed`, `--output-dir`,
`--dry-run`, `--max-episodes`, and `--headless` flags; requires the literal canonical
config, `--seed 0`, canonical output directory `experiments/08_unitree_r1/results`, and
`--max-episodes 0`; and rejects unknown or alternative values. It validates the sealed
historical P2/P3 gate, current-state non-regression, published evidence/state commit
chain, manifest, reports, safety, and resource ledger by calling pure audit-library
functions in-process. This includes rederiving both state-index commits from the sealed
capture ancestry and rechecking their manifest blobs, adjacency, exact one-path diffs,
canonical record introductions, and prior-value preservation. Historical Git identities use only the fixed credential-free local
`git rev-parse`, `git cat-file`, `git diff-tree`, and `git status` read commands with no
remote argument; no other subprocess is permitted. It never calls `fetch_sources.py`,
any author/discover/freeze/report/publication command, pytest, or a Git network/write
operation, and installs an experiment-local `OfflineGuard` before reading artifacts.
The guard rejects socket construction, DNS helpers, and every subprocess except the
four exact local Git read command families above; it strips ambient Git configuration
and remote/credential variables and forces `GIT_OPTIONAL_LOCKS=0`. It never creates a file, checkout, socket, review
decision, or commit.
`--dry-run` performs the same gate and local-Git identity validation, prints the exact
offline read-only validation plan, and stops before artifact parsing. The literal root
target is:

```make
.PHONY: exp08-audit
exp08-audit:
	UV_CACHE_DIR=.cache/uv uv run --offline python experiments/08_unitree_r1/run.py --config experiments/08_unitree_r1/configs/base.yaml --seed 0 --output-dir experiments/08_unitree_r1/results --max-episodes 0 --headless
	PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_CACHE_DIR=.cache/uv uv run --offline pytest -c /dev/null --rootdir=. --confcutdir=experiments/08_unitree_r1/tests -p no:cacheprovider experiments/08_unitree_r1/tests/test_r1_joint_mapping.py -q
```

Both target commands are offline and evidence-read-only. The P9 `conftest.py` installs
the same socket/DNS/subprocess-denial policy before importing the test module; plugin
autoload, parent conftest discovery, project pytest configuration, cache, and bytecode
writing are disabled. A mandatory negative fixture attempts a socket, DNS lookup, and
unlisted subprocess and proves each is refused, while a positive fixture permits only
the fixed local Git reads. Only the preexisting ignored uv cache is read. A missing or
unpublished artifact fails; the target never falls back to lifecycle execution or
source fetching.

Every writer anchors an approved parent descriptor, rejects symlink components, creates
one private sibling temporary directory, writes exact-schema files, fsyncs, writes the
self-excluding manifest last, renames to an absent destination, then fsyncs the parent.
The sole three-file replacement exception uses the bounded preimage journal and
rollback/recovery protocol above; each individual replacement remains descriptor-
relative and atomic, but the design does not mislabel three cross-directory renames as
one filesystem-atomic operation.
Same-process cleanup removes only a continuously held inode. Restart recovery moves one
verified orphan descriptor-relatively to a create-only quarantine; it never deletes,
publishes, or repairs an unverifiable orphan. Resume validates and skips only an exact
complete artifact.

Every evidence operation is create-only and carries a clean implementation Git SHA. The
only replacement exception is the exact three-file orchestrator maturity/state/report transaction
described above. `inventory`,
`discover`, `freeze`, and `report` refuse an existing target unless all bytes and
transitive hashes validate exactly, in which case they skip without rewriting.
`check` is read-only. In `staged` mode it requires exactly the final four paths staged
and no other dirty path; in `published` mode it requires a clean tree plus the adjacent
exact-path evidence and maturity/state/report commits. Both modes reject an extra/missing tracked
evidence file, hash mismatch, wrong source commit, stale implementation SHA, or report
not byte-identical to a pure rerender. The entire tracked P9 evidence set above is capped at 64 MiB; writers include
their temporary sibling in the preflight budget and stop before overflow. Each command
has a 60-minute wall ceiling. Sparse source is separately bounded by the exact
2-GiB/source and 5-GiB/pass limits in Section 4 and never enters tracked evidence.

## 9. Decision and anti-scaffolding rule

P9 advances only with prerequisite `READY`, artifact `VALID`, audit result `VERIFIED`,
advancement `READY`, byte-identical pure reports, and all static tests. A valid
nonpassing audit publishes the exact source gap and stops; invalid evidence publishes
no audit conclusion. P9 does not patch upstream, infer undocumented slots,
build a compatibility layer, or start remote baseline work. No generic robotics schema,
runtime registry, SDK wrapper, simulator adapter, service, UI, or deployment code is
created. A future thin adapter must consume this manifest unchanged and belongs to a
separate remotely authorized phase. The inventory/parser/rule engine, checkout wrapper,
reports, masks, and pure audit transforms remain experiment-local and are not promoted
into `reflect` merely because they are reusable in theory.

The implementation plan may begin after independent design review, but execution may
begin only after complete hash-matched P2/P3 evidence and the unchanged P3 checkout
tests pass. Exact R1 joint names/counts/slots/component widths are intentionally
evidence outputs, not invented design constants.
