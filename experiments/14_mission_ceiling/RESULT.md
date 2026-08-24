# Exp14 deterministic mission-logic ceiling/stress screen

Disposition: `INDICATIVE_DETERMINISTIC_LOGIC_SCREEN`. This is an experiment-first
mission-space preflight only. It is not pi0.5, not a final mission-stability claim,
not a semantic-memory or hierarchy-mechanism causal result, and not real-world
evidence.

## Frozen execution

Source/config/preregistration were frozen at
`23a300fc643da1bc1c65a3bab352448e20b3f8a1` before the 9,216 held-out episodes ran.
The exact matrix is 12 seeds x 6 missions x 4 horizons x 8 one-axis variants x 4
fixed agents. Analysis code was corrected afterward at
`d65bb16277158cd08df086a0a994a7abf5a9e0db` to resample complete seed clusters;
raw outcomes were not rerun or tuned.

All 9,216 matrix identities are unique and complete. Independent scoring derives
completion, safety, and progress from terminal building state and transition
effects, not an agent outcome label.

## Results

| Variant | Open loop | Live memory | Lower recovery | Full hierarchy |
|---|---:|---:|---:|---:|
| Baseline | 240/288 | 240/288 | 240/288 | 240/288 |
| Route | 80/288 | 90/288 | 90/288 | 90/288 |
| Topology | 180/288 | 180/288 | 180/288 | 180/288 |
| Constraint | 240/288 unsafe | 240/288 unsafe | 240/288 unsafe | 0/288 safe |
| Disturbance | 0/288 | 0/288 | 0/288 | 0/288 |
| Intervention | 0/288 | 0/288 | 0/288 | 240/288 |
| Paraphrase | 0/288 | 240/288 | 240/288 | 240/288 |
| Novelty | 0/288 | 0/288 | 0/288 | 180/288 |

Across all 2,304 episodes per agent, completion was open-loop 740 (32.1%), live
memory 990 (43.0%), lower recovery 990 (43.0%), and full hierarchy 1,170 (50.8%).
Safety was 2,016/2,304 (87.5%) for the first three agents and 2,304/2,304 for full.
Mean progress was 0.492, 0.608, 0.608, and 0.666 respectively.

The seed-cluster paired completion differences were full-minus-open +0.1866 (95%
bootstrap interval [0.1823, 0.1931]), full-minus-live +0.0781 [0.0781, 0.0781], and
full-minus-lower +0.0781 [0.0781, 0.0781], each with effective n=12 seeds and
10,000 draws. Zero-width intervals describe identical within-seed aggregate values
in this deterministic matrix, not population certainty.

Lower recovery matched live memory exactly on completion while adding 1.84 mean
retries and higher cost. Full averaged 0.125 semantic replans and 1.60 retries.
Route performance remained low and disturbance caused complete collapse for every
agent. The constraint axis exposed a direct safety/completion tradeoff: full avoided
unsafe rooms but exhausted its horizon in every case, while the other agents often
completed through unsafe rooms.

## Interpretation boundary

This implementation is a symbolic deterministic mission-logic stress screen. The
planner receives the full `Scenario` and ground-truth building state; the
paraphrase condition is directly recognized in policy code; live-memory and
lower-recovery choose the same fresh plan and differ mainly in retry accounting;
seeds mainly shift topology. There is no VLA, learned policy, perceptual uncertainty,
physics, or physical controller. Therefore these numbers do not establish causal
benefit from semantic memory, episodic memory, or a hierarchical architecture, and
they do not establish mission-space stability. The defensible result is narrower:
the frozen mission-logic policies have clear deterministic ceilings, especially for
route/disturbance handling, while the full policy alone handles the coded goal
intervention and novelty rules.

An independent reviewer must decide whether any claim stronger than this bounded
stress-screen description is supportable.

## Evidence

Canonical corrected evidence is `results/qualification-v3`; raw-only reconstruction
is `results/reconstruction-v3`. Each recursive manifest has 9,224 entries (9,221
files, 3 directories) and SHA-256
`89e4edb50d7945d5aba33f4630d7227f839a28507a43ac2946281fafbd033e5a`.
All reconstructed derived bytes and the full manifest match qualification exactly.
The corrected one-seed preliminary shard reports effective n=1 and no inferential
interval, as required.
