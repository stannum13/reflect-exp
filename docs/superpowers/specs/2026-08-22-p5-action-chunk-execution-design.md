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

A requests s0=0 only. B requests s(j+1)=d(j)+K after issuing K samples and discarding suffix, with one outstanding request. C/D/F/G request s_j=j*50 while fewer than I are outstanding; a capped ordinal fires at oldest delivery. E requests s(j+1)=d(j)+125-K, with exactly K unissued samples and one prefetch. The request observation is captured at s_j; its canonical target move is at m_j=s_j+1 while that inference is outstanding. Thus the response to s_j deliberately contains the old target, and the next request is the first proposal that can observe m_j. No observation is reused.

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

Core cells are latency ell={25,75,150,350} ticks times one/two moves. Let d0=ell. B: s1=d0+K,s2=d1+K. E: s1=d0+125-K,s2=d1+125-K. C/D/F/G: s1=50,s2=100 unless I=1, when s2 is the oldest-delivery tick plus 50. A has s0=0, m1=1 and m2=51. Every B--G one-move target is m1=s1+1; two moves are m1=s1+1 and m2=s2+1. Their final recovery windows are [m1,m1+1000] and [m2,m2+1000]. The response at s1 is old-target by construction; the later outstanding request s2 observes m1. Latest endpoints are periodic 1101, B 1709, and E 1943, each <3125.

The primary claim is stratified by protocol: within each protocol, candidate and A run identical scenario seed, latency, and that protocol's frozen exogenous m1/m2 schedule. It does not pool recovery values across protocols with unequal target ticks. The protocol comparison is the six separately adjusted candidate-minus-A contrasts, each paired within its own stratum.

Fault probes use ell=150 and one motion at m1=s1+1. Drop has no delivery; active future runs then hold. Pause is finite: it delays r1 by exactly 150 ticks beyond normal delivery, then enqueues it and processes it through ordinary valid/expired/out-of-order lifecycle; it is not a drop. For periodic old-after-newer: s2=s1+50, d2=s2+150, d1=d2+1; r2 arrives first and r1 is out-of-order. This probe requires I>=2. Under v0 (I=1) it is N/A for C/D/F/G; under v1/v2 it is executable. B/E permit one outstanding and A only one request, hence their replacement cells are N/A.

| protocol | drop | old-after-newer | pause | alternative | discontinuity |
|---|---|---|---|---|---|
| A | r0 dropped; hold; safety-only | N/A | delay r0 150 ticks, then normal lifecycle | N/A | accept/account r0 |
| B | r1 after K dropped; hold | N/A | delay r1 150 ticks, then normal lifecycle | replace suffix | accept/account r1 |
| C | r1 dropped; ensemble then hold | only I>=2: s1,s2,d2=s2+150,d1=d2+1; reject r1 | delay r1 150 ticks, then normal lifecycle | ensemble r1/r2 | ensemble/account |
| D | r1 dropped; future then hold | only I>=2: s1,s2,d2=s2+150,d1=d2+1; reject r1 | delay r1 150 ticks, then normal lifecycle | replace r1 | replace/account |
| E | r1 dropped with K remaining; hold | N/A | delay r1 150 ticks, then normal lifecycle | prefetch r1 | replace/account |
| F | r1 dropped; future then hold | only I>=2: s1,s2,d2=s2+150,d1=d2+1; reject r1 | delay r1 150 ticks, then normal lifecycle | blend r1/r2 | blend/account |
| G | r1 dropped; future then hold | only I>=2: s1,s2,d2=s2+150,d1=d2+1; reject r1 | delay r1 150 ticks, then normal lifecycle | condition r1/r2 | condition/account |

Cells/seed are A=11, B=12, E=12, and C/D/F/G=12 for v0 or 13 for v1/v2. N/A is excluded, never imputed. The maximum is 87 cells/seed; v0 has 83. Eight no-fault core cells are paired primary evidence; probes are safety/descriptive only. Stationary no-fault control is descriptive for first four confirmation seeds. Tests assert request_before_move (the observation at s1 has the old target and s2 has m1) and, for every candidate/A pair, equal seed, ell, m1, and m2.

## Lifecycle and invariants

Every raw proposal records proposal_id, rollout_id, request observation ID/time, request sequence, delivery tick, representation, dt_s, actions shape/values/SHA256, disposition, lifecycle/derived chunk IDs, and parent hashes in results/<phase>/bundles/<identity>/proposals.jsonl.

Direct A/B/D/E raws are executable. C/F/G raws remain sidecar records. Derived chunk starts at first unissued b and ends z=min(raw/executable coverage endpoint,3125), requiring z>b. It has actions.shape=(z-b,A), A=3 for P2 and A=2 for P4; one absolute row/tick; dt_s=.002; validity [b*2ms,z*2ms); and decoder row current_tick-b with no reinterpolation. Metadata has sorted parent hashes, rule/scalars, b/z, and owner (C newest contributor at b; F/G arriving raw). P4 knots are sampled to this domain before transform.

Every delivered rejected raw creates immutable wrapper ActionChunk with raw shape/payload/source/validity and metadata.origin=raw_rejected. POLICY_RESPONDED references wrapper then CHUNK_REJECTED_EXPIRED or CHUNK_REJECTED_OUT_OF_ORDER. Dropped/paused requests have no wrapper. Valid direct/derived response emits POLICY_RESPONDED, CHUNK_REPLACED only for half-open-valid old chunk, then CHUNK_ACCEPTED. Expired old clears then new accepts; no invented expiry event.

At b with no valid future, broker hold captures q. It is a broker-generated JOINT_POSITION ActionChunk routed through the existing joint-PD hold seam, including for primary P4; rows are (3125-b,3), each exact q(b), dt_s=.002, validity [b*2ms,6.25s), metadata.origin=broker_safe_hold, metadata.hold_adapter=joint_pd_latch. It is accepted/executed/replayed normally, never renewed, expires at episode end, and only valid response replaces it while valid. Regression tests require q,dq and issued q reference remain constant through hold, proving P4 differential-IK null-space posture cannot move it.

Invariants: no invalid execution or old-observation supersession; finite shapes; bounded queue/inflight; immutable issued samples; safe hold rather than stale future; monotonic events; one request/observation; addressable direct/derived/rejected/hold lifecycle; no network/remote/physical path.

## Pilot, freeze, confirmation, resources, and resume

Exactly three vectors exist across all execution: v0=(K=1,I=1,lambda=0,M=1,L=1), v1=(2,2,1,2,2), v2=(4,4,4,4,4). Timeout is removed: drop waits for active exhaustion then installs hold; pause has its finite 150-tick delivery and then normal valid/expired/out-of-order handling. A correction can replace a revision only before pilot output exists; after pilot begins any change ends the study and requires reviewed design. No protocol consumes candidates over two revisions.

Four tuning seeds run all vectors; four untouched validation seeds run selected vector. Select highest equal-weight eight-core recovery success among zero-invariant candidates; ties v0/v1/v2; none feasible STOPs protocol. A stopped A anchor stops its protocol pilot immediately and produces no scientific result. Pre-freeze killed candidates are excluded from primary contrasts and multiplicity; the decision family contains only completed, eligible B--G protocols versus a completed valid A. For v1/v2 13 cells gives 208; v0 C/D/F/G has 12 cells and gives 192. Exact all-protocol upper maximum is 1376: A=176, B=192, E=192, C/D/F/G=4*204. Every protocol is <=256 pilot episodes.

Freeze hashes P2-P4 evidence, eligibility proof, selected vector, cell table, margins/metrics/bootstrap, and only confirmation RNG algorithm/candidate procedure/count 32; then makes immutable 32-scenario manifest. Confirmation/protocol maximum is 256 core + <=20 probes +4 controls=280; seven protocols=1944. PRIMARY plus DESCRIPTIVE maximum=3888 rollouts, 24,300 seconds, 3888 MiB because every serialized rollout is checked <=1MiB before publication, plus 256MiB reports=4144MiB (<10GiB). Shard (phase,stack,vector-or-protocol,seed) max is pilot 13 episodes/81.25s and confirmation 14/87.5s; serial runs cap wall time at 60 minutes.

Evidence CLI requires phase/frozen-config/seed-manifest/stack-id/protocol/shard-index/shard-count/output-dir/headless. Identity hashes phase, frozen/P2-P4/seed hashes, stack/protocol/vector/seed/cell/schema. Before publication it measures serialized rollout bytes and refuses >1,048,576. Publication writes rollout, sidecar, and bundle manifest to private same-parent temporary bundle, fsyncs files/directories, writes manifest last, then atomically renames to absent final identity. Recovery opens only a stale .<identity>.partial-<nonce> via parent descriptor/no-follow, verifies owner identity and inode held since creation, and removes only that owned directory; symlinked, changed-inode, malformed, foreign, or ambiguous temporary paths fail. Resume skips only exact complete bundle; partial/conflicting output fails. --max-episodes is smoke-only unless exact shard count.

## Decision and implementation boundary

Primary estimand is paired seed-level candidate-minus-A recovery success, equal-weighted eight core cells. Six B-G PRIMARY contrasts use deterministic 10,000-resample paired percentile bootstrap with Bonferroni-adjusted intervals. Frozen gates set delta, p95 age/jerk/discontinuity, hold/overrun limits; equality at maxima passes; nonfinite/unclamped unsafe/invariant failure fails. Efficacy requires lower endpoint strictly >delta. Fixed B,C,D,E,F,G order selects one protocol.

SUPPORTED means one candidate clears efficacy/gates. NOT_SUPPORTED means all completed valid candidates upper endpoint <=delta or frozen non-efficacy failure with valid precision/controls. INCONCLUSIVE occurs only after eligible execution begins, for straddling/equal delta, invalid control, corrupt/missing evidence, systematic loss, or invalid shard. Descriptive results never affect label.

experiments/02_action_chunks owns docs/configs/run/broker/protocol/schedule/adapter/evaluate/tests/bundles/reports. It imports no study-only ACT/LeRobot/OpenPI code. Parallel work has disjoint broker/protocol, scheduler/adapter/evaluator, and config/CLI/artifact ownership; integration is broker then adapter then replay; live shards are serial. Tests cover formulas/cells/lifecycle, immutable ticks, eligibility, atomic crash/resume, equality, headless replay, source/P4 hashes, safety, secret/artifact scan, and diff check.

## Self-review

This revision freezes non-outcome-selected 10Hz timing, specifies 2ms derived/hold chunks and B-G schedules, fixes old-after-newer, bounds pilots to three vectors/<=256 protocol, corrects two-stack resources, makes evidence atomic, and distinguishes blocked prerequisites from scientific inconclusiveness. G remains an approximation.
