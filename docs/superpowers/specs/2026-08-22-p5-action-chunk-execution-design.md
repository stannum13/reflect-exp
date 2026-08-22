# P5 Temporal Action-Chunk Execution Design

Date: 2026-08-22

Status: approved autonomous default. P5 requires complete P3 provenance and completed P4 confirmation.

## Outcome and hard P4 eligibility

Experiment 02 compares seven ways to alter only unissued future samples on P4's simulated arm. It measures bounded latency/reactivity/smoothness trade-offs, not VLA intelligence, hardware async safety, or real RTC equivalence.

P5 may execute only if P4's published promotion decision contains exact P2 or P4; only those P4 stacks have multi-knot trajectories. Frozen input records promoted IDs/representations, making the first promoted eligible ID PRIMARY and a second eligible ID DESCRIPTIVE. If neither exists, P5 is prerequisite-blocked, produces no scientific label, and does not turn a one-knot stack into a trajectory.

P5 freezes its proposal rate before pilot at P=0.100s, never outcome-selected. P4 has D=0.002s, therefore Q=P/D=50 ticks, H=ceil(.8/P)+1=9, E=ceil(2.5P/D)=125, and N_knot=(H-1)Q+1=401. Usable horizon is N=min(401,125)=125, indexed 0..124, and U=124 future ticks. Eligibility records the selected stack/representation, these exact values, raw expiry, one K in {1,2,4}, and proves K+2<=124.

For A, delivery at n0 has target moves at n0+K+1 (one) or n0+K+1,n0+K+2 (two). The final 2.0s recovery endpoint is at most 350+6+1000=1356 < 3125 episode ticks. Missing adapter/rate/horizon proof blocks P5 rather than relocating perturbations.

## Boundary, data flow, and timing

The selected approach is P4 task plus project-local virtual-time broker. A pure Python point-mass fixture is tests-only; LeRobot/OpenPI runtime adaptation is deferred. P5 adds no VLA, checkpoint, server, ROS, CUDA, remote transport, physical connection, copied upstream source, or shared reflect schema change.

P4 arm/target -> Observation+SkillSpec -> raw proposal schedule -> broker -> executable ActionChunk -> unchanged P4 executor/controller -> MuJoCo -> ControlReferences/events/metrics -> atomic evidence bundle.

VirtualClock is the only behavior-time source. Each 2ms tick applies target moves; creates at most one fresh request observation; schedules/drops/pauses raw proposals; delivers by (delivery_tick,request_sequence); transitions broker; executes P4; records telemetry; advances. Host time is measurement only. First issue copies absolute-tick reference to a C-contiguous read-only array in append-only issued[tick] and ControlReference; later deliveries cannot mutate it and tests hash prior values after every delivery.

## Protocols, schedules, and transforms

A requests s0=0 only. B requests s(j+1)=d(j)+K after issuing K samples and discarding suffix, with one outstanding request. C/D/F/G request s_j=j*50 while fewer than I are outstanding; a capped ordinal fires at oldest delivery. E requests s(j+1)=d(j)+125-K, with exactly K unissued samples and one prefetch. Target motion precedes request capture; no observation is reused.

| ID | Name | accepted-arrival transition |
|---|---|---|
| A | OPEN_LOOP | accept raw executable; no later request |
| B | RECEDING_PREFIX | discard suffix, accept raw; hold while absent |
| C | TEMPORAL_ENSEMBLE | derive unissued absolute samples from valid raws |
| D | LATEST_VALID | replace all unissued samples with newest raw |
| E | ASYNC_SAFE_PREFIX | continue prefix pending prefetch, then replace future |
| F | OVERLAP_BLEND | derive blended overlap then newest raw suffix |
| G | RTC_APPROXIMATION | derive committed-prefix-conditioned future then raw suffix |

For C at t, V(t) is valid delivered raws covering t, w_i=exp(-lambda*(now_ns-d_i)/1e9), and a_C(t)=sum(w_i*a_i(t))/sum(w_i). For F j=0..M-1, beta=(j+1)/(M+1), a_F=(1-beta)o+beta*r; later samples are r. For G j=0..L-1, gamma=(L-j)/L, a_G=gamma*c+(1-gamma)r; later samples are r. P4 limits/slew/PD follow transforms. G is always RTC_APPROXIMATION; RTC_COMPATIBLE is forbidden without P3-provenanced compatible flow policy and real compatible execution.

Core cells are latency ell={25,75,150,350} ticks times one/two moves. Let d0=ell. B: s1=d0+K,s2=d1+K. E: s1=d0+125-K,s2=d1+125-K. C/D/F/G: s1=50,s2=100. A uses its n0-relative schedule. One move is at s1 with window [s1,s1+1000]; two moves are s1/s2 with final window [s2,s2+1000]. Latest endpoints: periodic 1100, B 1708, E 1942, each <3125.

Fault probes use ell=150 and one motion at s1. Drop/pause has no delivery; active future runs then hold. For periodic old-after-newer: s2=s1+50, d2=s2+150, d1=d2+1; r2 arrives first and r1 is out-of-order. B/E permit one outstanding and A only one request, hence their replacement cells are N/A.

| protocol | drop | old-after-newer | pause | alternative | discontinuity |
|---|---|---|---|---|---|
| A | r0 dropped; hold; safety-only | N/A | r0 paused; hold | N/A | accept/account r0 |
| B | r1 after K dropped; hold | N/A | r1 paused; hold | replace suffix | accept/account r1 |
| C | r1 dropped; ensemble then hold | s1,s2,d2=s2+150,d1=d2+1; reject r1 | pause r1 | ensemble r1/r2 | ensemble/account |
| D | r1 dropped; future then hold | s1,s2,d2=s2+150,d1=d2+1; reject r1 | pause r1 | replace r1 | replace/account |
| E | r1 dropped with K remaining; hold | N/A | pause r1 | prefetch r1 | replace/account |
| F | r1 dropped; future then hold | s1,s2,d2=s2+150,d1=d2+1; reject r1 | pause r1 | blend r1/r2 | blend/account |
| G | r1 dropped; future then hold | s1,s2,d2=s2+150,d1=d2+1; reject r1 | pause r1 | condition r1/r2 | condition/account |

Cells per seed are A=11, B=12, C=13, D=13, E=12, F=13, G=13 (87). N/A is excluded, never imputed. Eight no-fault core cells are paired primary evidence; probes are safety/descriptive only. Stationary no-fault control is descriptive for first four confirmation seeds.

## Lifecycle and invariants

Every raw proposal records proposal_id, rollout_id, request observation ID/time, request sequence, delivery tick, representation, dt_s, actions shape/values/SHA256, disposition, lifecycle/derived chunk IDs, and parent hashes in results/<phase>/bundles/<identity>/proposals.jsonl.

Direct A/B/D/E raws are executable. C/F/G raws remain sidecar records. Derived chunk starts at first unissued b and ends z=min(raw/executable coverage endpoint,3125), requiring z>b. It has actions.shape=(z-b,A), A=3 for P2 and A=2 for P4; one absolute row/tick; dt_s=.002; validity [b*2ms,z*2ms); and decoder row current_tick-b with no reinterpolation. Metadata has sorted parent hashes, rule/scalars, b/z, and owner (C newest contributor at b; F/G arriving raw). P4 knots are sampled to this domain before transform.

Every delivered rejected raw creates immutable wrapper ActionChunk with raw shape/payload/source/validity and metadata.origin=raw_rejected. POLICY_RESPONDED references wrapper then CHUNK_REJECTED_EXPIRED or CHUNK_REJECTED_OUT_OF_ORDER. Dropped/paused requests have no wrapper. Valid direct/derived response emits POLICY_RESPONDED, CHUNK_REPLACED only for half-open-valid old chunk, then CHUNK_ACCEPTED. Expired old clears then new accepts; no invented expiry event.

At b with no valid future, broker hold captures q. It uses primary representation/domain/decoder, rows (3125-b,A), dt_s=.002, validity [b*2ms,6.25s), metadata.origin=broker_safe_hold; P2 rows equal q(b), P4 rows FK(q(b)). It is accepted/executed normally, never renewed, expires at episode end, and only valid response replaces it while valid.

Invariants: no invalid execution or old-observation supersession; finite shapes; bounded queue/inflight; immutable issued samples; safe hold rather than stale future; monotonic events; one request/observation; addressable direct/derived/rejected/hold lifecycle; no network/remote/physical path.

## Pilot, freeze, confirmation, resources, and resume

Exactly three vectors exist across all execution: v0=(K=1,I=1,lambda=0,M=1,L=1), v1=(2,2,1,2,2), v2=(4,4,4,4,4). Timeout is removed: drop/pause waits for active exhaustion then installs hold; delivered responses are valid/expired/out-of-order only. A correction can replace a revision only before pilot output exists; after pilot begins any change ends the study and requires reviewed design. No protocol consumes candidates over two revisions.

Four tuning seeds run all vectors; four untouched validation seeds run selected vector. Select highest equal-weight eight-core recovery success among zero-invariant candidates; ties v0/v1/v2; none feasible STOPs protocol. For 13 cells: 3*4*13+4*13=208. All protocols: 4*(3+1)*87=1392. Every protocol is <=256 pilot episodes.

Freeze hashes P2-P4 evidence, eligibility proof, selected vector, cell table, margins/metrics/bootstrap, and only confirmation RNG algorithm/candidate procedure/count 32; then makes immutable 32-scenario manifest. Confirmation/protocol is 256 core + <=20 probes +4 controls=280; seven protocols=1944. PRIMARY plus DESCRIPTIVE maximum=3888 rollouts, 24,300 seconds, 3888 MiB payload+256 MiB reports=4144 MiB (<10GiB). Shard (phase,stack,vector-or-protocol,seed) max is pilot 13 episodes/81.25s and confirmation 14/87.5s; serial runs cap wall time at 60 minutes.

Evidence CLI requires phase/frozen-config/seed-manifest/stack-id/protocol/shard-index/shard-count/output-dir/headless. Identity hashes phase, frozen/P2-P4/seed hashes, stack/protocol/vector/seed/cell/schema. Publication writes rollout, sidecar, and bundle manifest to private same-parent temporary bundle, fsyncs files/directories, writes manifest last, then atomically renames to absent final identity. Resume skips only exact complete bundle; partial/conflicting output fails. --max-episodes is smoke-only unless exact shard count.

## Decision and implementation boundary

Primary estimand is paired seed-level candidate-minus-A recovery success, equal-weighted eight core cells. Six B-G PRIMARY contrasts use deterministic 10,000-resample paired percentile bootstrap with Bonferroni-adjusted intervals. Frozen gates set delta, p95 age/jerk/discontinuity, hold/overrun limits; equality at maxima passes; nonfinite/unclamped unsafe/invariant failure fails. Efficacy requires lower endpoint strictly >delta. Fixed B,C,D,E,F,G order selects one protocol.

SUPPORTED means one candidate clears efficacy/gates. NOT_SUPPORTED means all completed valid candidates upper endpoint <=delta or frozen non-efficacy failure with valid precision/controls. INCONCLUSIVE occurs only after eligible execution begins, for straddling/equal delta, invalid control, corrupt/missing evidence, systematic loss, or invalid shard. Descriptive results never affect label.

experiments/02_action_chunks owns docs/configs/run/broker/protocol/schedule/adapter/evaluate/tests/bundles/reports. It imports no study-only ACT/LeRobot/OpenPI code. Parallel work has disjoint broker/protocol, scheduler/adapter/evaluator, and config/CLI/artifact ownership; integration is broker then adapter then replay; live shards are serial. Tests cover formulas/cells/lifecycle, immutable ticks, eligibility, atomic crash/resume, equality, headless replay, source/P4 hashes, safety, secret/artifact scan, and diff check.

## Self-review

This revision freezes non-outcome-selected 10Hz timing, specifies 2ms derived/hold chunks and B-G schedules, fixes old-after-newer, bounds pilots to three vectors/<=256 protocol, corrects two-stack resources, makes evidence atomic, and distinguishes blocked prerequisites from scientific inconclusiveness. G remains an approximation.
