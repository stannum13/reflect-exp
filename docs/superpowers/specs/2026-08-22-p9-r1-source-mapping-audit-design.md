# P9 Unitree R1 Static Source and Joint-Mapping Audit Design

**Date:** 2026-08-22

**Status:** Approved autonomous design; implementation is gated on complete,
hash-matched P2 and P3 evidence

**Scope:** P9 / Experiment 08 Phase 0 only; no simulator execution or deployment

## 1. Decision and non-deployment boundary

P9 answers one bounded question: can every R1 actuator and observation/action position
declared by the pinned official sources be mapped to the expected SDK motor-slot domain
with explicit sign, offset, limits, gains, provenance, and isolation tests?

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
`references/repos.lock.yaml`, `docs/RUN_MANIFEST.yaml`, `RUN_REPORT.md`, P2's clean
evidence-base Git SHA and report-only commit/hash, P3's clean implementation/evidence
Git SHA and report-only commit/hash, P3's
`experiments/00_source_audit/configs/operation-manifest.yaml`,
`experiments/00_source_audit/results/compatibility.csv`, `references/licenses.md`,
`docs/SOURCE_MAP.md`, `experiments/00_source_audit/RESULTS.md`,
`experiments/00_source_audit/INTERFACE_FINDINGS.md`, and the exact MuJoCo-smoke
fragment path/hash named by P3's operation manifest. Missing, dirty, incomplete, or
hash-mismatched evidence blocks P9 before checkout or output creation.

`P3GateEvidence` is the closed JSON object `schema_version, p2_state, p3_state,
registry_sha256, p2_lock_sha256, run_manifest_sha256, run_report_sha256,
p2_evidence_base_git_sha, p2_report_commit_git_sha, p2_report_sha256,
p3_implementation_evidence_git_sha, p3_report_commit_git_sha, p3_report_sha256,
p3_operation_manifest_sha256, p3_compatibility_sha256, licenses_sha256,
source_map_sha256, p3_results_sha256, p3_interface_findings_sha256,
p3_mujoco_smoke_relative_path, p3_mujoco_smoke_sha256, p3_local_lane_open,
physical_deployment_allowed, remote_execution_allowed, runtime_network_allowed`.
States must be `complete`, the lane boolean true, and all three authority booleans
false. File hashes are lowercase 64-hex and Git SHAs lowercase 40-hex. The P9 factory
rehashes every named file rather than trusting this summary. The smoke path must be the
single MuJoCo-smoke fragment identity selected from the hash-matched P3 operation
manifest, be relative beneath P3's fragment root, and hash to the recorded value. Every
P9 subcommand, including authoring, validation, fetch, inventory, discovery, issue,
freeze, report, check, and the umbrella command, reruns this complete gate before it
reads a checkout or creates output.
The gate resolves P2's historical report-only commit from the completed P2 phase record
in `docs/RUN_MANIFEST.yaml`, reads `RUN_REPORT.md` at that commit as a Git blob, and
checks its bound preceding evidence-base SHA; it separately treats the current P3
`RUN_REPORT.md` report-only commit and its bound implementation/evidence SHA. Thus the
two report hashes cannot accidentally alias merely because the pathname was reused.

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
`UPPER_LIMIT`, `EFFORT_LIMIT`, `KP`, `KD`, and `SKIPPED_SLOT`.
The five sequence/schema collection facts have canonical value exactly
`{"size": nonnegative_integer, "ordered_ids": [NFKC_ASCII_string, ...]}` with array
length equal to `size` and unique IDs. `SDK_SLOT_DOMAIN` has canonical value exactly
`{"size": nonnegative_integer, "ordered_slots": [nonnegative_integer, ...]}`, with
unique strictly increasing slots and array length equal to `size`. These whole-collection
facts must come from source-declared collection definitions; discovery may not synthesize
them by grouping element facts.

The discovery report groups facts by canonical source symbol and emits
`CONSISTENT | MISSING | CONFLICT | NON_R1 | UNSUPPORTED_EXPRESSION`. It never chooses
between conflicting facts. A reviewed freeze may approve a row only when the primary
R1 source and SDK evidence are each exact and every applicable R1-tagged supporting
order fact is consistent.
Every resolution records all candidate fact IDs, the selected fact IDs, a bounded
rationale enum, and the reviewer commit SHA. Free-text rationale cannot create a value.
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

The six top-level collection fact IDs must resolve to exact R1-tagged facts whose
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
only R1-tagged supporting evidence participates, and every pure manifest-validator
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
fact/file/hash integrity; issue-52 regression fixture; and negative duplicate,
missing, conflict, symlink, unsafe-format, non-R1, network, remote, and physical cases.
Pure fixture tests also cover complete P2/P3 gate/hash rejection, exact five-name P9
factory authority, unchanged eight-name P3 CLI eligibility, registry/lock-only spec
derivation, cumulative download accounting without network, deterministic sorted
inventory/rules/fact IDs, every parser grammar boundary and node/depth/alias/file/byte
ceiling, non-R1 zero authority, lifecycle-state cross-products, create-only resume,
transitive provenance tamper, extra/missing artifact rejection, and byte-identical
report/check rerender. Checkout tests use a recording runner and local fixture trees;
no test performs Git or HTTP network access.

Coverage fixtures independently delete a middle and the trailing member from each
source-declared actuator, SDK-slot, observation, training-action, and deployment-action
collection while leaving retained rows consecutive; every case must fail exact partition
validation. Parser fixtures include deeply nested and high-token Python below 4 MiB and
deep/high-node XML below 4 MiB, and assert abort occurs in the tokenize pre-pass or live
XML stream before `ast.parse` or full-tree retention. Gate tests mutate each closed gate
input in turn—including both run-state documents, both P2/P3 report lifecycles, both P3
result reports, and the manifest-selected smoke fragment—and assert every subcommand
fails before checkout read/output creation. Resource tests accept exactly 2147483648 and
5368709120 bytes, reject each cap plus one, prevent over-reservation before process
launch, and prove failure releases only its immutable reservation.
Authority-seal tests separately alter the sealing commit, Git blob ID, and SHA-256 for
each of the operation manifest, extraction rules, and reviewed mapping; freeze, check,
and byte-for-byte reproduction must reject every mutation.

## 8. Artifacts, commands, and publication

Required tracked outputs are:

```text
experiments/08_unitree_r1/configs/p3-gate.json
experiments/08_unitree_r1/configs/operation-manifest.yaml
experiments/08_unitree_r1/configs/extraction-rules.yaml
experiments/08_unitree_r1/configs/reviewed-mapping.yaml
experiments/08_unitree_r1/configs/base.yaml
experiments/08_unitree_r1/run.py
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
experiments/08_unitree_r1/docs/R1_SOURCE_MAP.md
experiments/08_unitree_r1/docs/R1_JOINT_MAPPING_AUDIT.md
experiments/08_unitree_r1/results/r1_joint_mapping_manifest.yaml
experiments/08_unitree_r1/tests/test_r1_joint_mapping.py
```

The checkout-fragment manifest lists exactly the five repository fragment paths above,
sizes, and hashes and excludes itself. No glob is used by a writer or validator.
Every downstream manifest binds all upstream hashes listed in Section 6. Small
discovery facts, evidence digests, and reports are tracked; sparse checkouts and raw
source remain ignored. Exact command shapes are:

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
  --run-manifest docs/RUN_MANIFEST.yaml --run-report RUN_REPORT.md \
  --p3-operation-manifest \
  experiments/00_source_audit/configs/operation-manifest.yaml \
  --compatibility experiments/00_source_audit/results/compatibility.csv \
  --licenses references/licenses.md --source-map docs/SOURCE_MAP.md \
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

uv run python experiments/08_unitree_r1/audit.py report \
  --p3-gate experiments/08_unitree_r1/configs/p3-gate.json \
  --mapping-manifest experiments/08_unitree_r1/results/r1_joint_mapping_manifest.yaml \
  --discovery-manifest experiments/08_unitree_r1/results/discovery/manifest.json \
  --issue-context experiments/08_unitree_r1/results/issue-52-context.json \
  --source-map-output experiments/08_unitree_r1/docs/R1_SOURCE_MAP.md \
  --audit-output experiments/08_unitree_r1/docs/R1_JOINT_MAPPING_AUDIT.md --headless

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
  --source-map experiments/08_unitree_r1/docs/R1_SOURCE_MAP.md \
  --audit-report experiments/08_unitree_r1/docs/R1_JOINT_MAPPING_AUDIT.md --headless

UV_CACHE_DIR=.cache/uv uv run pytest \
  experiments/08_unitree_r1/tests/test_r1_joint_mapping.py -q

uv run python experiments/08_unitree_r1/run.py \
  --config experiments/08_unitree_r1/configs/base.yaml --seed 0 \
  --output-dir experiments/08_unitree_r1/results --max-episodes 0 --headless

make exp08-audit
```

`run.py` is the thin Experiment 08 Phase 0 umbrella. It accepts exactly the standard
`--config`, `--seed`, `--output-dir`, `--dry-run`, `--max-episodes`, and `--headless`
flags, requires `--max-episodes 0`, rejects unknown flags, and delegates only to the
commands above. `--dry-run` reruns the complete gate, prints the exact offline command
plan in order, and creates no file, checkout, subprocess, or socket. The literal root
target is:

```make
.PHONY: exp08-audit
exp08-audit:
	UV_CACHE_DIR=.cache/uv uv run python experiments/08_unitree_r1/run.py --config experiments/08_unitree_r1/configs/base.yaml --seed 0 --output-dir experiments/08_unitree_r1/results --max-episodes 0 --headless
	UV_CACHE_DIR=.cache/uv uv run pytest experiments/08_unitree_r1/tests/test_r1_joint_mapping.py -q
```

Every writer anchors an approved parent descriptor, rejects symlink components, creates
one private sibling temporary directory, writes exact-schema files, fsyncs, writes the
self-excluding manifest last, renames to an absent destination, then fsyncs the parent.
Same-process cleanup removes only a continuously held inode. Restart recovery moves one
verified orphan descriptor-relatively to a create-only quarantine; it never deletes,
publishes, or repairs an unverifiable orphan. Resume validates and skips only an exact
complete artifact.

Every operation is create-only and carries a clean implementation Git SHA. `inventory`,
`discover`, `freeze`, and `report` refuse an existing target unless all bytes and
transitive hashes validate exactly, in which case they skip without rewriting.
`check` is read-only and rejects an extra/missing tracked evidence file, hash mismatch,
wrong source commit, stale implementation SHA, or report not byte-identical to a pure
rerender. The entire tracked P9 evidence set above is capped at 64 MiB; writers include
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
