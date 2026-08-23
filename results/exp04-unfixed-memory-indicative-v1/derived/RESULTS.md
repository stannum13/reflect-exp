# Experiment 04 Fixed-vs-Unfixed Memory Indicative Result

Status: `SUPPORTS_ONLINE_SEPARATE_MEMORY`

## Situation and objective

A matched synthetic robot-memory task changed valve pose, availability, room restrictions, and attempt history. The objective was to test whether an M5-style memory should remain fixed or update its semantic/geometric and episodic stores online.

## Method

The run completed 64 seeds x 4 variants. Each variant received byte-identical observations and emitted 12 primary decisions per seed without scorer truth. Effects are paired by seed; intervals are 20,000-draw PCG64 cluster bootstraps.

## Outcome

FIXED_M5 correctness was 0.3281; LIVE_SEPARATE was 0.8815. The paired difference was +0.5534 (95% +0.5039 to +0.6003). Adverse composite changed by -0.2257 (95% -0.2543 to -0.1953).

Separate live semantic memory exceeded episodic-only memory by +0.3867 on mutation decisions; adding live episodic history to live semantic memory changed history-query correctness by +0.5078. Gates passed: 6/6.

## Inference and limits

The preregistered disposition is `SUPPORTS_ONLINE_SEPARATE_MEMORY`. This is indicative causal evidence for the frozen synthetic generator and controller only. It does not establish perception quality, real-robot performance, a production database, or broad generalization. Raw streams, decisions, truth, scores, paired rows, examples, graphs, hashes, and replay code are preserved.
