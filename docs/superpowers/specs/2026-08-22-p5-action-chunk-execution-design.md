# P5 Temporal Action-Chunk Execution Design

Date: 2026-08-22

Status: approved autonomous default. P5 requires complete P3 provenance and a completed, eligible P4 confirmation.

## Outcome and hard P4 eligibility

Experiment 02 compares seven ways to alter only unissued future samples on P4's simulated arm. It measures bounded latency/reactivity/smoothness trade-offs, not VLA intelligence, hardware asynchronous safety, or real-time-control equivalence.

P5 may execute only if P4's published promotion decision contains exact P2 or P4. Only those stack IDs have multi-knot trajectories. Frozen input records the promoted IDs and representations; the first promoted eligible ID is PRIMARY and a second is DESCRIPTIVE. If neither exists, P5 is prerequisite-blocked, produces no scientific label, and must not turn a one-knot stack into a trajectory.

P5 freezes its proposal rate before pilot at `P=0.100 s`, never outcome-selected. P4 has `D=0.002 s`, so `Q=P/D=50` ticks, `H=ceil(0.8/P)+1=9`, `E=ceil(2.5P/D)=125`, and `N_knot=(H-1)Q+1=401`. The usable proposal horizon is `N=min(401,125)=125`, indexed `0..124`, with 124 future ticks. Eligibility records the selected stack/representation, these exact values, raw expiry, one `K` in `{1,2,4}`, and proves `K+2<=124`. Missing adapter/rate/horizon proof blocks P5 rather than relocating perturbations.

## Boundary, data flow, and virtual timing

The selected approach is the P4 task plus a project-local virtual-time broker. A pure-Python point-mass fixture is tests-only; LeRobot/OpenPI runtime adaptation is deferred. P5 adds no VLA, checkpoint, server, ROS, CUDA, remote transport, physical connection, copied upstream source, or shared Reflect schema change.

P4 arm/target -> `Observation+SkillSpec` -> raw proposal schedule -> broker -> executable `ActionChunk` -> unchanged P4 executor/controller -> MuJoCo -> `ControlReference`/events/metrics -> atomic evidence bundle.

`VirtualClock` is the only behavior-time source. At tick `t`, the deterministic order is: apply exogenous target moves; request phase (create at most one observation/request if capacity was free at the start of this phase); delivery phase ordered by `(delivery_tick, request_sequence)`; broker transition; execute P4; record telemetry; advance. A delivery at `t` therefore cannot free capacity for another request until `t+1`. Host time is measurement only. First issue copies the absolute-tick reference to a C-contiguous read-only array in append-only `issued[tick]` and `ControlReference`; later deliveries cannot mutate it, and tests hash all prior values after every delivery.

## Common setup and exogenous core schedule

Every A--G rollout begins with the same deterministic setup. At tick 0 the selected P4 stack evaluates the initial observation once, outside the measured protocol, and its valid raw becomes the accepted warm-up `ActionChunk`. Its issued reference must differ bytewise from the tick-0 reference on at least one tick in `1..52`, and every issued value must be finite and dimensionally valid. A setup is invalid only for a nonfinite value, dimension mismatch, reference outside the hard joint/workspace envelope before the common safety clamp, joint-limit escape, or unbounded controller divergence. Ordinary activation of P4's `1.5 rad/s` reference slew limiter and bounded torque saturation are retained safety metrics and do not invalidate warm-up. A bytewise-constant/hold setup invalidates the cell. The setup response is preserved in lifecycle evidence and safety metrics but excluded from proposal-age and protocol estimands.

The measured origin is `S=50`. Every protocol creates measured request `r0` at `s0=S`. The one-move and two-move scenarios use the single common exogenous schedules `m1=S+1=51` and `(m1,m2)=(51,52)`, respectively. Because the minimum frozen latency is 25 ticks, `r0` is outstanding at every move for every protocol and eligible core cell. Its observation has the old target; the first request after `r0` is the first that can observe both moves. No A-specific or candidate-specific target schedule exists. Recovery windows end at `m1+1000=1051` or `m2+1000=1052`, below the 3125-tick episode end. Thus every candidate/A pair has exactly equal stack, seed, latency, `m1`, and `m2`, and one A rollout is reused rather than rerun across candidate contrasts.

Core cells are latency `ell in {25,75,150,350}` times one/two moves. A normal response has `d_j=s_j+ell`. Requests are admitted only when the number of outstanding requests at the start of the request phase is strictly less than the protocol cap `I`; acceptance at the delivery phase does not retroactively admit a request that tick.

## Protocol recurrences and transforms

| ID | Protocol | Measured request recurrence | Accepted-arrival transition |
|---|---|---|---|
| A | OPEN_LOOP | `s0=S` only | accept raw executable; no later request |
| B | RECEDING_PREFIX | `s_(j+1)=d_j+K` after issuing K samples; `I=1` | discard suffix, accept raw; hold while absent |
| C | TEMPORAL_ENSEMBLE | desired epoch `e_j=S+jQ`; actual `s_j=min{t>=e_j: outstanding_start(t)<I}` | derive unissued absolute samples from valid raws |
| D | LATEST_VALID | same periodic recurrence as C | replace all unissued samples with newest raw |
| E | ASYNC_SAFE_PREFIX | `s_(j+1)=d_j+E-K`; `I=1` | continue prefix pending prefetch, then replace future |
| F | OVERLAP_BLEND | same periodic recurrence as C | derive blended overlap then newest raw suffix |
| G | RTC_APPROXIMATION | same periodic recurrence as C | derive committed-prefix-conditioned future then raw suffix |

The periodic minimum is evaluated tick by tick, so a capped desired epoch is deferred, not dropped: if its oldest delivery is at `t`, it may fire no earlier than `t+1`. There is at most one admitted request per tick, and the invariant is exactly `outstanding<=I` after admission. Each admitted request captures a fresh observation; none is reused.

Every delivered raw `i` is first converted, without execution, to a canonical absolute-tick proposal function `R_i(u)` in its promoted P4 representation domain. Its half-open coverage is `U_i=[d_i,min(d_i+N,3125))`. P2 joint knots and P4 Cartesian knots use the frozen P4 linear interpolation at exact 2 ms ticks; no executor state, target update, or future observation enters this resampling. The raw retains its request observation as source. The active non-hold executable before an arrival defines `O(u)` over its remaining half-open coverage only when it has the same representation and row width as the arriving raw; already issued ticks are never included. A broker safe hold, mismatched representation, or mismatched row width never defines overlap future for F/G, even though a hold remains executable until the raw is accepted.

For C at broker transition tick `b`, contributors are `V_b={i:b in U_i}`. Order them by `(d_i,request_sequence,proposal_id)`. Set `z=min_i end(U_i)` for `i in V_b`; if `V_b` is empty, enter hold. For every integer `u in [b,z)`, `w_i(u)=exp(-lambda*((u-d_i)*D))` and `C(u)=sum_i(w_i(u)*R_i(u))/sum_i(w_i(u))`. Exact `lambda=0` gives an arithmetic mean. At `z`, the old derived chunk is half-open expired: clear it without `CHUNK_REPLACED`, remove expired parents, and immediately derive a new C chunk from the remaining parents before execution. This expiry-driven transition emits local `DERIVATION_RECOMPUTED` then canonical `CHUNK_ACCEPTED`, but no invented policy response. If no parent remains, enter hold. A newly delivered raw performs the same derivation after its real `POLICY_RESPONDED` event and replaces a compatible old chunk only when that old chunk is still half-open valid.

For F on arriving raw `r` at tick `b`, let `z=end(U_r)` and let `o=O` only when the compatible prior non-hold executable covers `b`. The overlap length is `h=min(M,z-b,end(O)-b)` when `o` exists and zero otherwise. For `j=0..h-1`, `beta=(j+1)/(M+1)` and `F(b+j)=(1-beta)O(b+j)+beta R_r(b+j)`; for `u in [b+h,z)`, `F(u)=R_r(u)`. For G use the same exact compatible old-future definition as its approximation's committed future: `c(u)=O(u)`, `h=min(L,z-b,end(O)-b)`, `gamma=(L-j)/L`, and `G(b+j)=gamma O(b+j)+(1-gamma)R_r(b+j)` for `j=0..h-1`; later rows are `R_r`. If no compatible non-hold old executable covers `b`, F and G use the raw without blending/conditioning. This makes G a transparent committed-future projection, not learned flow conditioning.

Every C/F/G derived chunk owns a new ID. Its parent proposal SHA-256 values are sorted in metadata. F/G source observation is the arriving raw's observation. C source observation is the newest contributor by the frozen order above, including after expiry recomputation. `generated_time_ns=valid_from_ns=b*2,000,000`, `expires_at_ns=z*2,000,000`, and `actions.shape=(z-b,A)`. Parent coverages, owner observation, `b`, `z`, scalar/vector revision, and output SHA-256 are immutable sidecar fields. P4 limits, slew limiting, and PD control follow transforms. G remains `RTC_APPROXIMATION`; `RTC_COMPATIBLE` is forbidden without P3-provenanced compatible flow policy and real compatible execution.

## Fault schedules

Fault probes use `ell=150`, one move exactly one tick after the targeted request, all four pilot seeds, and only the first four confirmation seeds. Each probe starts from a fresh rollout. For A the target is `r0` at 50. For B it is the first post-`r0` request at `p=200+K`; for E it is the first post-`r0` request at `p=200+125-K`; and for C/D/F/G it is a frozen post-initial-acceptance request at `p=201`. Its normal delivery is `p+150`. Apart from the second request in old-after-newer, no other request is admitted in a fault probe. Drop creates no queued response or wrapper: active future exhausts, then hold. Pause retains a pending response, changes only its delivery from `p+150` to `p+300`, then enqueues and processes it through the ordinary valid/expired/out-of-order lifecycle; it is never modeled as a drop. Alternative-response and discontinuity probes change only that request's payload/transition and keep its request, move, and delivery ticks fixed.

The old-after-newer probe is executable only for periodic C/D/F/G with `I>=2`. Freeze `s0=50,d0=200`, then `s1=d0+1=201`, `s2=s1+Q=251`, `d2=s2+150=401`, and delayed `d1=d2+1=402`. Thus `r0` has already been accepted, `r1` alone is outstanding when `r2` is admitted, `r2` arrives first, and `r1` is rejected out of order. It requires and never exceeds capacity two. It is N/A for `v0 (I=1)`, A, B, and E; N/A cells are absent, not imputed.

| protocol | drop | old-after-newer | pause | alternative | discontinuity |
|---|---|---|---|---|---|
| A | `r0` dropped; hold; safety-only | N/A | `r0` pending 150 extra ticks, then normal lifecycle | N/A | accept/account `r0` |
| B | first post-`r0` request dropped; hold | N/A | pending 150 extra ticks, then normal lifecycle | replace suffix | accept/account |
| C | `r1` dropped; ensemble then hold | exact `201/251/401/402` schedule when `I>=2` | pending 150 extra ticks, then normal lifecycle | ensemble/account `r1` | ensemble/account |
| D | `r1` dropped; future then hold | exact `201/251/401/402` schedule when `I>=2` | pending 150 extra ticks, then normal lifecycle | replace `r1` | replace/account |
| E | first post-`r0` prefetch dropped; hold | N/A | pending 150 extra ticks, then normal lifecycle | accept prefetch | replace/account |
| F | `r1` dropped; future then hold | exact `201/251/401/402` schedule when `I>=2` | pending 150 extra ticks, then normal lifecycle | blend/account `r1` | blend/account |
| G | `r1` dropped; future then hold | exact `201/251/401/402` schedule when `I>=2` | pending 150 extra ticks, then normal lifecycle | condition/account `r1` | condition/account |

Cells per seed are A=11, B=12, E=12, and each C/D/F/G=12 for v0 or 13 for v1/v2. The eight no-fault core cells are paired primary evidence; fault probes are safety/descriptive only. A stationary no-fault control is descriptive for the first four confirmation seeds.

## Terminal cutoff and lifecycle

No protocol may create a request after tick `C=2500`. A natural trigger or deferred periodic epoch that first becomes admissible after C is canceled before observation/request creation. The cutoff is frozen from the worst path: `2500 + max normal ell 350 + pause extension 150 + E 125 = 3125`. Consequently every normal or paused response is delivered and every accepted executable expires by episode end. At terminal tick 3125 the delivery queue and broker queue must be empty; no active chunk remains. A deliberately dropped request has no delivery queue entry and is closed by a `dropped` disposition in the sidecar. Any other unresolved request, response, or queue entry invalidates the rollout.

Every raw proposal records proposal ID, rollout ID, request observation ID/time, request sequence, delivery tick, representation, `dt_s`, action shape/values/SHA256, disposition, lifecycle/derived chunk IDs, and parent hashes in `results/<phase>/bundles/<identity>/proposals.jsonl`.

Direct A/B/D/E raws are executable. C/F/G raws remain sidecar records. A derived chunk starts at first unissued tick `b` and ends `z=min(raw/executable coverage endpoint,3125)`, requiring `z>b`. It has `actions.shape=(z-b,A)`, `A=3` for P2 and `A=2` for P4; one absolute row per tick; `dt_s=.002`; validity `[b*2 ms,z*2 ms)`; and decoder row `current_tick-b` with no reinterpolation. Metadata has sorted parent hashes, rule/scalars, b/z, and owner (C newest contributor at b; F/G arriving raw). P4 knots are sampled to this domain before transform.

Every delivered rejected raw creates an immutable wrapper `ActionChunk` with raw shape/payload/source/validity and `metadata.origin=raw_rejected`; its `generated_time_ns` is the actual delivery time even when its retained raw validity has already expired. `POLICY_RESPONDED` references the wrapper, followed by `CHUNK_REJECTED_EXPIRED` or `CHUNK_REJECTED_OUT_OF_ORDER`. A dropped request has no wrapper; a paused request gets no wrapper while pending and one only when actually delivered. For C/F/G, the valid `POLICY_RESPONDED` references the delivery-derived executable chunk while the raw stays sidecar-only. A valid direct/derived response emits `POLICY_RESPONDED`, `CHUNK_REPLACED` only for a half-open-valid old chunk, then `CHUNK_ACCEPTED`. Expired old state clears before new acceptance; no nonexistent expiry event is invented.

At tick `b<3125` with no valid future, the P5-local representation dispatcher latches measured `q_ref=q(b)` and installs a broker-generated `JOINT_POSITION ActionChunk`. Its rows are `(3125-b,3)`, every row exactly `q_ref`, `dt_s=.002`, validity `[b*2 ms,6.25 s)`, `metadata.origin=broker_safe_hold`, and `metadata.hold_adapter=p5_joint_pd_latch_v1`. Its required `source_observation_id/time` are the most recent stored canonical observation at or before `b`; metadata separately records `hold_latched_tick=b` and the SHA-256 of measured q, so it never falsely presents that observation as a policy response. The dispatcher handles that origin before stack dispatch and calls P4's unchanged common joint-reference slew/PD/torque path directly; it never passes a 3-column hold through P4's P4/Cartesian decoder and never edits P4 source. It commands desired `dq=0`, invokes no differential IK or null-space posture, and produces ordinary immutable `ControlReference(controller_mode="p5_joint_pd_hold")` and `ACTION_EXECUTED` rows.

Hold installation emits canonical `CHUNK_REPLACED` only if a prior executable is still half-open valid, then `CHUNK_ACCEPTED`; exhaustion at an expiry first clears the expired executable and directly accepts hold. A hold is not periodically renewed. A later valid response may replace it, and a later distinct exhaustion may create one new hold with a new ID and newly latched q. At terminal tick 3125 the half-open hold is cleared before terminal assertions without an invented expiry event, so no active chunk remains. Replay resolves every hold reference/action to that hold ID and reproduces the same terminal inactive state. Regression tests assert exact q-reference latching, desired dq zero, no DIK call, bounded PD settling/error under the frozen P4 tolerance, no post-settling reference drift, second-hold behavior after a later replacement, and terminal clearing; they do not incorrectly require physical q/dq to be constant at hold entry.

Global invariants are: no invalid execution or old-observation supersession; finite shapes; bounded queue/inflight; immutable issued samples; safe hold rather than stale future; monotonic events; one fresh observation per request; addressable direct/derived/rejected/hold lifecycle; and no network, remote, or physical path.

## Pilot, freeze, confirmation, and multiplicity

Exactly three candidate vectors exist across all candidate execution: `v0=(K=1,I=1,lambda=0,M=1,L=1)`, `v1=(2,2,1,2,2)`, and `v2=(4,4,4,4,4)`. A is an untuned anchor and runs once per scenario. Timeout is absent: drop waits for active exhaustion then installs hold; pause has its finite delivery state machine above. A correction can replace a vector only before any pilot output exists; after pilot begins, any vector or schedule change ends the study and requires a reviewed new design. No protocol consumes more than these three vectors.

Before pilot, commit the code SHA, three vectors, tuning manifest, encrypted-or-hash-committed disjoint validation manifest, selection/tie rules, and resource ceiling. Four tuning seeds run all three vectors for B--G; four untouched validation seeds are revealed only after selecting the vector and run that vector. Select the highest equal-weight eight-core recovery success among vectors with zero invariant failures; ties resolve v0, v1, v2. The candidate is a pilot survivor only if the selected vector also has zero invariant failures on all validation cells. No source/config edit is allowed after the first pilot output; any correction starts a new reviewed study identity. Any A invariant or safety failure stops the entire eligible-stack study, not merely one protocol. It yields no scientific result before confirmation and INCONCLUSIVE if confirmation had begun. Candidate failures stop that candidate. Zero survivors after a valid A pilot freezes an operational `NOT_SUPPORTED` decision with no confirmation or efficacy claim.

After the invariant pilot, freeze the survivor set and family size `m` once. If `m>0`, run A confirmation once and the m survivors; do not shrink the family after seeing confirmation. Six is the maximum family. Family-wise `alpha=0.05`. Each candidate/A paired percentile-bootstrap interval uses deterministic 10,000 resamples and Bonferroni marginal confidence `1-alpha/m`, equivalently lower and upper probabilities `alpha/(2m)` and `1-alpha/(2m)`. A stopped/invalid confirmation makes the eligible-stack study `INCONCLUSIVE`; a failed candidate remains in the frozen family as a non-passing contrast.

The sole count source is:

| protocol class | cells/seed by config | pilot tuning | pilot validation max | pilot max | confirmation core | confirmation probes, first 4 seeds | controls, first 4 seeds | confirmation max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A anchor | 11 | 4x11 | 4x11 | 88 | 32x8=256 | 4x3=12 | 4 | 272 |
| B or E | 12 per vector | 4x(12+12+12)=144 | 4x12=48 | 192 each | 256 | 4x4=16 | 4 | 276 each |
| C/D/F/G | v0=12; v1/v2=13 | 4x(12+13+13)=152 | 4x13=52 | 204 each | 256 | at most 4x5=20 | 4 | 280 each |

Thus pilot maximum per eligible stack is `88 + 2*192 + 4*204 = 1288` rollouts, and every protocol is <=204 pilot rollouts. Confirmation maximum per stack is `272 + 2*276 + 4*280 = 1944`; two eligible stacks give 3888 confirmation rollouts. The PRIMARY claim uses only the PRIMARY stack. DESCRIPTIVE results and all probes never affect the label.

Freeze hashes P2--P4 evidence, eligibility proof, unchanged code SHA, selected vectors, survivor family/m, cell table, the exact fixed margins/gates below, metrics/bootstrap, and only the confirmation RNG algorithm/candidate procedure/count 32 before deriving the immutable unseen confirmation manifest. Confirmation seed values must not be read, materialized, or logged before that freeze.

## Resources, evidence, and resume

All maxima derive from the count table and a 6.25-second episode:

| scope | rollout max | simulated seconds | episode-bundle bytes at <=1 MiB each | report allowance |
|---|---:|---:|---:|---:|
| pilot, one stack | 1288 | 8050 | 1288 MiB | 128 MiB |
| confirmation, one stack | 1944 | 12150 | 1944 MiB | 128 MiB |
| complete phase, two stacks | `2*(1288+1944)=6464` | 40400 | 6464 MiB | 512 MiB |

The two-stack generated-artifact maximum is 6976 MiB, below 10 GiB. Every complete outer episode bundle—including canonical rollout, every sidecar, and bundle manifest—is checked at <=1,048,576 bytes before publication; nothing is budgeted off-ledger. Preflight reserves the full selected stage plus existing temporary/quarantine bytes and the 512 MiB aggregate allowance and fails closed if the ceiling would be exceeded. A pilot shard `(phase,stack,protocol,vector-or-anchor,seed)` has at most 13 episodes/81.25 simulated seconds; a confirmation shard `(phase,stack,protocol,seed)` has at most 14 episodes/87.5 seconds. Serial execution therefore remains below the 60-minute wall-time ceiling per shard.

The sole runner is `python -m experiments.02_action_chunks.run`. All paths below are repository-root relative and are rejected if absolute, escaping, symlinked, or not the declared manifest path. Live commands call `SafetyConfig` and the P3/P4 evidence gate before importing MuJoCo or creating output. The runner exposes exactly `pilot`, `freeze`, `confirmation`, and `analyze`. Pilot additionally requires exactly one `--pilot-stage tuning|select|validation`; tuning and validation are physics shards, while select is a physics-free one-shot reduction. A manifest driver enumerates every declared shard and substitutes its literal stack/protocol/vector/seed shard fields into these same shapes; there is no alternate batch API. Exact command shapes and stage order are:

```text
UV_CACHE_DIR=.cache/uv uv run python -m experiments.02_action_chunks.run --phase pilot --pilot-stage tuning \
  --config experiments/02_action_chunks/configs/pilot-r1.yaml \
  --seed-manifest experiments/02_action_chunks/protocol/pilot-r1/tuning-seeds.json \
  --stack-id P2 --protocol B --vector v0 --shard-index 0 --shard-count 4 \
  --output-dir experiments/02_action_chunks/results --headless --max-episodes 12

UV_CACHE_DIR=.cache/uv uv run python -m experiments.02_action_chunks.run --phase pilot --pilot-stage select \
  --config experiments/02_action_chunks/configs/pilot-r1.yaml \
  --seed-manifest experiments/02_action_chunks/protocol/pilot-r1/tuning-seeds.json \
  --validation-commitment experiments/02_action_chunks/protocol/pilot-r1/validation-seeds.json \
  --validation-secret experiments/02_action_chunks/private/validation-seeds.secret.json \
  --output-dir experiments/02_action_chunks/results \
  --selection-output experiments/02_action_chunks/protocol/pilot-r1/pilot-selection.json \
  --validation-seed-output experiments/02_action_chunks/protocol/pilot-r1/validation-seeds.revealed.json \
  --headless

UV_CACHE_DIR=.cache/uv uv run python -m experiments.02_action_chunks.run --phase pilot --pilot-stage validation \
  --config experiments/02_action_chunks/configs/pilot-r1.yaml \
  --seed-manifest experiments/02_action_chunks/protocol/pilot-r1/validation-seeds.revealed.json \
  --selection-manifest experiments/02_action_chunks/protocol/pilot-r1/pilot-selection.json \
  --stack-id P2 --protocol B --shard-index 0 --shard-count 4 \
  --output-dir experiments/02_action_chunks/results --headless --max-episodes 12

UV_CACHE_DIR=.cache/uv uv run python -m experiments.02_action_chunks.run --phase freeze \
  --config experiments/02_action_chunks/configs/pilot-r1.yaml \
  --seed-manifest experiments/02_action_chunks/protocol/pilot-r1/validation-seeds.revealed.json \
  --selection-manifest experiments/02_action_chunks/protocol/pilot-r1/pilot-selection.json \
  --output-dir experiments/02_action_chunks/results \
  --frozen-output experiments/02_action_chunks/configs/frozen.yaml \
  --confirmation-seed-output experiments/02_action_chunks/protocol/confirmation/seed-manifest.json \
  --headless

UV_CACHE_DIR=.cache/uv uv run python -m experiments.02_action_chunks.run --phase confirmation \
  --config experiments/02_action_chunks/configs/frozen.yaml \
  --seed-manifest experiments/02_action_chunks/protocol/confirmation/seed-manifest.json \
  --stack-id P2 --protocol B --shard-index 0 --shard-count 32 \
  --output-dir experiments/02_action_chunks/results --headless --max-episodes 13

UV_CACHE_DIR=.cache/uv uv run python -m experiments.02_action_chunks.run --phase analyze \
  --config experiments/02_action_chunks/configs/frozen.yaml \
  --seed-manifest experiments/02_action_chunks/protocol/confirmation/seed-manifest.json \
  --output-dir experiments/02_action_chunks/results --headless
```

Candidate pilot tuning requires `--vector`; A anchor shards forbid it and use `vector_id=null`. Pilot validation and confirmation forbid `--vector` and resolve the create-only selected vector for B--G, while A remains the untuned anchor. Pilot select requires `--selection-output`, `--validation-commitment`, `--validation-secret`, and `--validation-seed-output`; forbids stack/protocol/vector/shard flags; validates every tuning shard before choosing; atomically publishes the exact selection schema below; then reads the ignored root-relative secret, verifies its canonical-byte SHA-256 commitment, and create-only materializes the validation seed file. Both output targets must initially be absent, and the seed output is not created until the selection file is fsynced and revalidated. The secret has the revealed seed-manifest schema, is never copied into results, and a missing/mismatched/non-ignored secret fails closed. Pilot validation requires `--selection-manifest`. Freeze/analyze forbid stack/protocol/shard flags and run no physics. Freeze validates all tuning/selection/validation bundles, writes the frozen protocol create-only, fsyncs and reopens it to verify its hash, then and only then derives the new confirmation RNG root and create-only seed manifest; failure between those operations leaves no confirmation seeds and resume validates the existing frozen protocol before generation. `--shard-index` is zero-based and strictly less than `--shard-count`; the manifest records and requires the exact count. The pure sorted manifest iterator is the sole source of stack/protocol/vector/seed/cell identities and exact shard episode count. `--max-episodes` is smoke-only unless it equals that complete count. A v1/v2 periodic pilot shard therefore uses 13 rather than the B example's 12; confirmation uses 11/12/13/14 according to the manifest, with 14 only for a first-four periodic seed containing five probes plus control.

Each episode publishes one outer bundle with exact inventory:

```text
bundle/
  rollout/                 # unchanged canonical RolloutWriter directory
  exp02/proposals.jsonl
  exp02/derived-chunks.jsonl
  exp02/issued-references.parquet
  exp02/broker-lifecycle.jsonl
  exp02/episode-metrics.json
  bundle-manifest.json
```

`proposals.jsonl` has exact keys `proposal_id,rollout_id,request_observation_id,request_time_ns,request_sequence,normal_delivery_tick,actual_delivery_tick,delivery_mode,representation,dt_s,shape,actions_sha256,coverage_start_tick,coverage_end_tick,disposition,wrapper_chunk_id,derived_chunk_ids,parent_sha256s`; `delivery_mode` is `normal|paused`, while final disposition is exactly `accepted|expired|out_of_order|dropped`. `derived-chunks.jsonl` has `chunk_id,rule,owner_observation_id,owner_proposal_id,parent_sha256s,b,z,representation,dt_s,shape,actions_sha256,scalar_revision,transition_reason`, where transition is `delivery|parent_expiry|safe_hold`; safe hold uses `rule=SAFE_HOLD` and null owner/proposal with an empty parent list. `issued-references.parquet` has typed columns `tick:int64,time_ns:int64,source_chunk_id:string,source_observation_id:int64,q_ref:fixed_size_list<float64>[3],dq_ref:fixed_size_list<float64>[3],representation:string,reference_sha256:string,is_hold:bool`; rows are unique and strictly tick-ordered. `broker-lifecycle.jsonl` has `tick,sequence,event,request_id,proposal_id,chunk_id,old_chunk_id,queue_depth,outstanding_count,reason`; local events include `DERIVATION_RECOMPUTED`, `REQUEST_DROPPED`, and `TERMINAL_CLEARED` and cross-link the canonical events rather than extending `ExecutionEventType`. `episode-metrics.json` contains exact primary indicators plus numerator/denominator/sample-count fields for age, hold, jerk, discontinuity, safety, queue, and warm-up validity.

Every JSONL line is canonical JSON with fixed exact keys, finite values, LF ending, and no unknown field. The bundle validator requires unique IDs, sorted parent hashes, action/reference byte hashes, raw-to-derived-to-issued coverage, canonical event ordering, source observation ownership, wrapper/rejection links, hold dispatch, terminal inactive replay, and byte-equal immutable issued rows after every later delivery. The manifest has exact keys `schema_version,identity,protocol_hash,source_hashes,files,total_bytes`; `files` lists every other regular file with relative path, media type, bytes, and SHA-256, excludes itself and temporary files, and has no self-digest.

Each phase additionally publishes create-only `protocol-manifest.json`, `seed-manifest.json`, `shard-manifest.jsonl`, `aggregate.csv`, `bootstrap.json`, `decision.json`, and `artifact-manifest.json`; pilot alone also publishes `pilot-selection.json`. `protocol-manifest.json` has exact keys `schema_version,phase,study_id,implementation_git_sha,working_tree_clean,p2_hash,p3_hash,p4_decision_hash,p4_config_hash,adapter_hash,config_hash,vector_hashes,schedule_hash,metric_hash,gate_hash,seed_manifest_hash,resource_ceiling_bytes`. `seed-manifest.json` has exact keys `schema_version,phase,rng_algorithm,rng_root_commitment,rng_root,partition,scenario_count,scenario_records`; `scenario_records`, when revealed, is an ordered array whose row keys are exactly `seed,scenario_id,move_count,latency_ticks,fault,target_request_sequence,move_ticks`. Pilot validation keeps `rng_root` and `scenario_records` null in the commitment file and never overwrites it: reveal is a distinct create-only `validation-seeds.revealed.json` with the same schema and matching commitment. Confirmation forbids its seed file before freeze. `pilot-selection.json` has exact keys `schema_version,study_id,tuning_protocol_hash,tuning_seed_hash,stack_selections,validation_commitment_hash`; each ordered stack-selection row has exactly `stack_id,protocol_id,selected_vector_id,objective,valid_cell_count,tie_rank`, including A with null vector/tie rank. Each `shard-manifest.jsonl` row has exact keys `shard_id,phase,pilot_stage,stack_id,protocol_id,vector_id,seed,cell_ids,episode_count,protocol_hash,seed_hash,output_identity`; non-pilot `pilot_stage` is null, and sorted shard rows are unique and complete. `artifact-manifest.json` uses exact keys `schema_version,phase,protocol_hash,files,total_bytes`, excludes itself/no self-digest, and lists every phase file with exact entry keys `path,media_type,bytes,sha256`.

The exact aggregate header is `phase,stack_id,protocol_id,vector_id,seed,cell_id,recovery_numerator,recovery_denominator,recovery_score,age_n,age_p95_s,hold_ticks,total_core_ticks,jerk_n,jerk_p95,discontinuity_n,discontinuity_p95,unsafe_count,joint_limit_count,queue_overrun_count,terminal_empty,warmup_valid,bundle_sha256,validity`. Bootstrap records exact keys `alpha,m,resamples,seed_derivation,paired_seed_ids,lower_probability,upper_probability,lower_index,upper_index,estimate,lower,upper,width,precision`. Decision records exact keys `prerequisite_state,artifact_state,scientific_result,primary_stack,descriptive_stack,frozen_family,contrasts,gates,selected_protocol,reasons`. All schemas reject unknown/missing fields, duplicate identities, noncanonical order, and nonfinite numeric values. Analyze consumes only validated bundles and cannot load MuJoCo or modify a score.

Publication creates a private same-parent temporary bundle while holding its directory descriptor, writes canonical rollout and sidecars, fsyncs files, writes and fsyncs the manifest last, fsyncs the temporary directory, atomically renames to an absent final identity, then fsyncs the parent. Same-process failure cleanup may remove only the temporary tree whose descriptor/inode has been held continuously since creation.

After restart, no process can claim held-inode continuity. Recovery opens the parent and exact `.<identity>.partial-<nonce>` entries descriptor-relatively with no-follow, rejects symlinks/non-directories/foreign owner or identity/malformed or ambiguous entries, and atomically renames each single verified orphan to an absent descriptor-relative `quarantine/<identity>.<nonce>`. Restart recovery never deletes or publishes an orphan. Quarantine remains evidence-bearing, counts against the byte ceiling, and requires explicit later review. Any unsafe or ambiguous recovery state fails closed. Resume skips only an exact complete final bundle; partial/conflicting output fails. `--max-episodes` is smoke-only unless it equals the exact shard count.

## Decision and implementation boundary

For each displacement, recovery success is `1` only when the unchanged P4 success condition—EEF error at most `0.025 m` continuously for `0.10 s`—first completes within the displacement's `2.0 s` window; otherwise it is `0`, including a valid censored non-recovery. A one-move episode score is its one indicator and a two-move episode score is the arithmetic mean of its two indicators. For one `(protocol,stack,seed)`, the primary value is the equal-weight arithmetic mean of the eight complete no-fault core episode scores. The paired seed contrast is `candidate-A`, so positive is beneficial. The minimum worthwhile effect is fixed before pilot at `delta=0.05` (five percentage points); it is not pilot-selected.

For each frozen candidate contrast, sort the complete paired seed IDs ascending. `frozen_manifest_sha256` is exactly the lowercase SHA-256 of the canonical bytes of `experiments/02_action_chunks/configs/frozen.yaml` recorded by the confirmation protocol manifest. PCG64 uses the first 128 big-endian bits of SHA-256 over canonical JSON `[frozen_manifest_sha256,"exp02-bootstrap-v1",stack_id,protocol_id]`. Each of 10,000 resamples draws the complete paired-seed count with replacement and stores the mean paired contrast. Sort values ascending; for probability `p`, use index `max(0,ceil(p*10000)-1)` with no interpolation or tie deduplication. Lower/upper probabilities are the Bonferroni values above. Efficacy requires the adjusted lower endpoint strictly greater than `0.05`; equality fails efficacy. A conclusive exclusion of the worthwhile effect requires the adjusted upper endpoint strictly less than `0.05`; equality or an interval spanning `0.05` is imprecise.

One missing or corrupt core episode invalidates that `(candidate,seed)` and its paired A seed only for that contrast; it is reported and excluded before resampling. At least 31 of 32 paired seeds and adjusted interval width at most `0.20` are required for a precise contrast. A second missing paired seed for one contrast, systematic protocol-specific loss, any missing/corrupt A core/control, any missing stationary control, or any invalid shard makes the PRIMARY study `INCONCLUSIVE`. Censored non-recovery is observed zero, never missing. No value is imputed. A frozen-family candidate with complete valid evidence but an observed absolute-gate failure remains in `m`, fails that gate, and cannot be silently removed or used to reduce multiplicity; a lifecycle/evidence invariant failure is instead invalid evidence and therefore `INCONCLUSIVE`.

Absolute confirmation gates are exact. Every candidate requires: zero nonfinite or unclamped unsafe output; zero hard joint-limit violation; zero queue overrun; terminal empty queues; p95 action age at most `1.00 s`; pooled hold-tick fraction over the eight core cells no greater than the paired A fraction plus `0.05`; and p95 joint jerk and p95 command discontinuity each at most `1.5` times the valid P5 pilot-validation A value for the identical promoted P4 stack. Episode percentiles use the P4 nearest-rank rule; jerk/discontinuity first compute episode p95, then nearest-rank p95 across the 256 complete core episodes with equal episode weight. Action age pools stored 100 Hz valid executed-reference samples; hold ticks have no proposal age and are excluded from that domain. Equality to an absolute maximum passes. A fault-probe lifecycle/evidence invariant failure invalidates evidence and is `INCONCLUSIVE`; observed unsafe/overrun outcomes in otherwise valid fault probes are reported and block promotion but remain descriptive and do not alter the scientific label. Stationary controls must satisfy the unchanged P4 negative-control rule.

Fixed `B,C,D,E,F,G` order breaks an exact efficacy/gate tie and selects one protocol. `SUPPORTED` means at least one frozen-family candidate clears efficacy and every gate. `NOT_SUPPORTED` means zero pilot survivors after valid A with no efficacy claim, or every completed valid frozen-family candidate has adjusted upper endpoint strictly below `0.05` or fails a predeclared non-efficacy gate while all A/control, missingness, and precision requirements remain valid. `INCONCLUSIVE` applies after eligible execution begins when no candidate supports and at least one contrast equals/spans `0.05`, lacks precision, has disallowed missingness, or A/control/evidence/shard validity fails. Descriptive-stack results and all probes never affect the PRIMARY scientific label.

`experiments/02_action_chunks` owns docs/configs/run/broker/protocol/schedule/adapter/evaluate/tests/bundles/reports. It imports no study-only ACT/LeRobot/OpenPI code. Parallel work has disjoint broker/protocol, scheduler/adapter/evaluator, and config/CLI/artifact ownership; integration is broker then adapter then replay; live shards are serial. Tests cover formulas/counts; the exact recurrence and tick order; request/move chronology; inflight equality; lifecycle and pause/drop distinction; immutable issued ticks; eligibility; terminal cutoff and empty queues; hold latch/zero-dq/no-DIK/settling; atomic crash/resume/quarantine; paired equality; headless replay; source/P4 hashes; safety; secret/artifact scan; and diff check.

## Executable schedule self-review

The schedule implementation must expose a pure iterator used by both runner and tests. Golden hand examples are executable assertions, not prose-only examples:

- Core, all A--G, `ell=25`: setup accepts at 0; `r0` requests at 50; moves occur at 51 and 52 while r0 is outstanding; normal r0 delivers at 75.
- Periodic, `I=1,ell=75`: desired epochs are 50,100,150; actual `s0=50,d0=125`; the epoch 100 is capped through request phase 125 and admits at `s1=126,d1=201`; the epoch 150 admits at `s2=202`, not 201, because delivery follows request processing.
- Periodic, `I=2,ell=150`: actual `s0=50,s1=100`; the desired epoch 150 is capped, `d0=200`, and the next request admits at 201; outstanding count is never above two.
- Old-after-newer: `s0/d0=50/200`, `s1=201`, `s2=251`, `d2=401`, `d1=402`; r2 accepts and r1 is lifecycle-addressably rejected.
- Worst terminal pause: request at 2500, normal ell-350 delivery 2850, paused delivery 3000, executable expiry 3125; no request is created at 2501 and terminal queues are empty.

This review-fix revision additionally freezes the executable statistical decision rule, raw-to-derived C/F/G ownership and recomputation, warm-up invalidity boundary, representation-dispatch safe hold, and the root-relative staged CLI plus strict evidence schemas. It preserves the common exogenous schedule, exact capacity-aware recurrence, feasible out-of-order delivery, terminal closure, whole-study anchor semantics, fixed survivor multiplicity, evidence-bearing restart recovery, and maxima derived from one count table. G remains an approximation.
