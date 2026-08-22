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

Every A--G rollout begins with the same deterministic setup. At tick 0 the selected P4 stack evaluates the initial observation once, outside the measured protocol, and its valid raw becomes the accepted warm-up `ActionChunk`. Its issued reference must change on at least one tick in `0..52`; a hold, clamp, or zero-motion setup invalidates the cell. The setup response is preserved in lifecycle evidence and safety metrics but excluded from proposal-age and protocol estimands.

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

For C at tick `t`, `V(t)` is the valid delivered raws covering `t`, `w_i=exp(-lambda*(now_ns-d_i)/1e9)`, and `a_C(t)=sum(w_i*a_i(t))/sum(w_i)`. For F, `j=0..M-1`, `beta=(j+1)/(M+1)` and `a_F=(1-beta)o+beta*r`; later samples are `r`. For G, `j=0..L-1`, `gamma=(L-j)/L` and `a_G=gamma*c+(1-gamma)r`; later samples are `r`. P4 limits, slew limiting, and PD control follow transforms. G remains `RTC_APPROXIMATION`; `RTC_COMPATIBLE` is forbidden without P3-provenanced compatible flow policy and real compatible execution.

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

Every delivered rejected raw creates an immutable wrapper `ActionChunk` with raw shape/payload/source/validity and `metadata.origin=raw_rejected`. `POLICY_RESPONDED` references the wrapper, followed by `CHUNK_REJECTED_EXPIRED` or `CHUNK_REJECTED_OUT_OF_ORDER`. A dropped request has no wrapper; a paused request gets no wrapper while pending and one only when actually delivered. A valid direct/derived response emits `POLICY_RESPONDED`, `CHUNK_REPLACED` only for a half-open-valid old chunk, then `CHUNK_ACCEPTED`. Expired old state clears before new acceptance; no nonexistent expiry event is invented.

At tick b with no valid future, the broker latches measured `q_ref=q(b)` and installs a broker-generated `JOINT_POSITION ActionChunk` through the existing joint-PD hold seam, including for primary P4. Its rows are `(3125-b,3)`, every row exactly `q_ref`, `dt_s=.002`, validity `[b*2 ms,6.25 s)`, `metadata.origin=broker_safe_hold`, and `metadata.hold_adapter=joint_pd_latch`. It commands desired `dq=0`, invokes no differential IK or null-space posture, is accepted/executed/replayed normally, is never renewed, expires at episode end, and only a valid response replaces it while valid. Regression tests assert exact q-reference latching, desired dq zero, no DIK call, bounded PD settling/error under the frozen P4 tolerance, and no post-settling reference drift; they do not incorrectly require physical q/dq to be constant at hold entry.

Global invariants are: no invalid execution or old-observation supersession; finite shapes; bounded queue/inflight; immutable issued samples; safe hold rather than stale future; monotonic events; one fresh observation per request; addressable direct/derived/rejected/hold lifecycle; and no network, remote, or physical path.

## Pilot, freeze, confirmation, and multiplicity

Exactly three candidate vectors exist across all candidate execution: `v0=(K=1,I=1,lambda=0,M=1,L=1)`, `v1=(2,2,1,2,2)`, and `v2=(4,4,4,4,4)`. A is an untuned anchor and runs once per scenario. Timeout is absent: drop waits for active exhaustion then installs hold; pause has its finite delivery state machine above. A correction can replace a vector only before any pilot output exists; after pilot begins, any vector or schedule change ends the study and requires a reviewed new design. No protocol consumes more than these three vectors.

Before pilot, commit the code SHA, three vectors, tuning manifest, encrypted-or-hash-committed disjoint validation manifest, selection/tie rules, and resource ceiling. Four tuning seeds run all three vectors for B--G; four untouched validation seeds are revealed only after selecting the vector and run that vector. Select the highest equal-weight eight-core recovery success among vectors with zero invariant failures; ties resolve v0, v1, v2. The candidate is a pilot survivor only if the selected vector also has zero invariant failures on all validation cells. No source/config edit is allowed after the first pilot output; any correction starts a new reviewed study identity. Any A invariant or safety failure stops the entire eligible-stack study, not merely one protocol. It yields no scientific result before confirmation and INCONCLUSIVE if confirmation had begun. Candidate failures stop that candidate. Zero survivors after a valid A pilot freezes an operational `NOT_SUPPORTED` decision with no confirmation or efficacy claim.

After the invariant pilot, freeze the survivor set and family size `m` once. If `m>0`, run A confirmation once and the m survivors; do not shrink the family after seeing confirmation. Six is the maximum family. Each candidate/A paired percentile-bootstrap interval uses deterministic 10,000 resamples and family-wise Bonferroni confidence `1-alpha/m` (equivalently two-sided tail allocation `alpha/(2m)`). A stopped/invalid confirmation makes the eligible-stack study INCONCLUSIVE; a failed candidate remains in the frozen family as a non-passing contrast.

The sole count source is:

| protocol class | cells/seed by config | pilot tuning | pilot validation max | pilot max | confirmation core | confirmation probes, first 4 seeds | controls, first 4 seeds | confirmation max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A anchor | 11 | 4x11 | 4x11 | 88 | 32x8=256 | 4x3=12 | 4 | 272 |
| B or E | 12 per vector | 4x(12+12+12)=144 | 4x12=48 | 192 each | 256 | 4x4=16 | 4 | 276 each |
| C/D/F/G | v0=12; v1/v2=13 | 4x(12+13+13)=152 | 4x13=52 | 204 each | 256 | at most 4x5=20 | 4 | 280 each |

Thus pilot maximum per eligible stack is `88 + 2*192 + 4*204 = 1288` rollouts, and every protocol is <=204 pilot rollouts. Confirmation maximum per stack is `272 + 2*276 + 4*280 = 1944`; two eligible stacks give 3888 confirmation rollouts. The PRIMARY claim uses only the PRIMARY stack. DESCRIPTIVE results and all probes never affect the label.

Freeze hashes P2--P4 evidence, eligibility proof, unchanged code SHA, selected vectors, survivor family/m, cell table, margins/metrics/bootstrap, and only the confirmation RNG algorithm/candidate procedure/count 32 before deriving the immutable unseen confirmation manifest. Confirmation seed values must not be read, materialized, or logged before that freeze.

## Resources, evidence, and resume

All maxima derive from the count table and a 6.25-second episode:

| scope | rollout max | simulated seconds | rollout bytes at <=1 MiB each | report allowance |
|---|---:|---:|---:|---:|
| pilot, one stack | 1288 | 8050 | 1288 MiB | 128 MiB |
| confirmation, one stack | 1944 | 12150 | 1944 MiB | 128 MiB |
| complete phase, two stacks | `2*(1288+1944)=6464` | 40400 | 6464 MiB | 512 MiB |

The two-stack generated-artifact maximum is 6976 MiB, below 10 GiB. Every serialized rollout is checked at <=1,048,576 bytes before publication. Preflight reserves the full selected stage plus existing quarantine bytes and fails closed if the ceiling would be exceeded. A pilot shard `(phase,stack,protocol,vector-or-anchor,seed)` has at most 13 episodes/81.25 simulated seconds; a confirmation shard `(phase,stack,protocol,seed)` has at most 14 episodes/87.5 seconds. Serial execution therefore remains below the 60-minute wall-time ceiling per shard.

The evidence CLI requires phase, frozen config, seed manifest, stack ID, protocol, shard index/count, output directory, and headless mode. Identity hashes phase, frozen/P2--P4/seed hashes, stack/protocol/vector/seed/cell/schema. Publication creates a private same-parent temporary bundle while holding its directory descriptor, writes rollout and sidecar, fsyncs files, writes and fsyncs the manifest last, fsyncs the temporary directory, atomically renames to an absent final identity, then fsyncs the parent. Same-process failure cleanup may remove only the temporary tree whose descriptor/inode has been held continuously since creation.

After restart, no process can claim held-inode continuity. Recovery opens the parent and exact `.<identity>.partial-<nonce>` entries descriptor-relatively with no-follow, rejects symlinks/non-directories/foreign owner or identity/malformed or ambiguous entries, and atomically renames each single verified orphan to an absent descriptor-relative `quarantine/<identity>.<nonce>`. Restart recovery never deletes or publishes an orphan. Quarantine remains evidence-bearing, counts against the byte ceiling, and requires explicit later review. Any unsafe or ambiguous recovery state fails closed. Resume skips only an exact complete final bundle; partial/conflicting output fails. `--max-episodes` is smoke-only unless it equals the exact shard count.

## Decision and implementation boundary

The primary estimand is paired seed-level candidate-minus-A recovery success, equal-weighted over the eight common core cells. Frozen gates set delta, p95 age/jerk/discontinuity, hold/overrun limits; equality at maxima passes, while nonfinite, unclamped unsafe, or invariant failure fails. Efficacy requires the adjusted lower endpoint strictly greater than delta. Fixed B,C,D,E,F,G order selects one protocol.

`SUPPORTED` means at least one frozen-family candidate clears efficacy and every gate. `NOT_SUPPORTED` means zero pilot survivors after a valid A, or every completed valid frozen-family candidate has upper endpoint <=delta or a frozen non-efficacy failure with valid precision/controls. `INCONCLUSIVE` is available only after eligible execution begins, for straddling/equality at delta, invalid A/control, corrupt/missing evidence, systematic loss, or invalid shard. Descriptive results never affect the label.

`experiments/02_action_chunks` owns docs/configs/run/broker/protocol/schedule/adapter/evaluate/tests/bundles/reports. It imports no study-only ACT/LeRobot/OpenPI code. Parallel work has disjoint broker/protocol, scheduler/adapter/evaluator, and config/CLI/artifact ownership; integration is broker then adapter then replay; live shards are serial. Tests cover formulas/counts; the exact recurrence and tick order; request/move chronology; inflight equality; lifecycle and pause/drop distinction; immutable issued ticks; eligibility; terminal cutoff and empty queues; hold latch/zero-dq/no-DIK/settling; atomic crash/resume/quarantine; paired equality; headless replay; source/P4 hashes; safety; secret/artifact scan; and diff check.

## Executable schedule self-review

The schedule implementation must expose a pure iterator used by both runner and tests. Golden hand examples are executable assertions, not prose-only examples:

- Core, all A--G, `ell=25`: setup accepts at 0; `r0` requests at 50; moves occur at 51 and 52 while r0 is outstanding; normal r0 delivers at 75.
- Periodic, `I=1,ell=75`: desired epochs are 50,100,150; actual `s0=50,d0=125`; the epoch 100 is capped through request phase 125 and admits at `s1=126,d1=201`; the epoch 150 admits at `s2=202`, not 201, because delivery follows request processing.
- Periodic, `I=2,ell=150`: actual `s0=50,s1=100`; the desired epoch 150 is capped, `d0=200`, and the next request admits at 201; outstanding count is never above two.
- Old-after-newer: `s0/d0=50/200`, `s1=201`, `s2=251`, `d2=401`, `d1=402`; r2 accepts and r1 is lifecycle-addressably rejected.
- Worst terminal pause: request at 2500, normal ell-350 delivery 2850, paused delivery 3000, executable expiry 3125; no request is created at 2501 and terminal queues are empty.

This revision freezes one common exogenous schedule, an exact capacity-aware recurrence, feasible out-of-order delivery, terminal closure, whole-study anchor semantics, fixed survivor multiplicity, evidence-bearing restart recovery, and maxima derived from one count table. G remains an approximation.
