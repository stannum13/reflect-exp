# Experiment 02 engineering qualification v1

Status: `PRELIMINARY_NON_SCIENTIFIC_QUALIFICATION_ONLY`. This run exercises broker
invariants and evidence reconstruction. It is not P5 pilot, confirmation, or evidence
that any protocol improves robot control.

## Outcome

The six declared A/D/F cases all executed and retained a disposition. Three expected
working cases terminated with an empty queue: A with a smooth low-latency proposal,
D with a low-latency target shift and future replacement, and F with an alternative
proposal blended over the exact two-row overlap. Three deliberately adverse cases
were retained as nonworking rather than dropped: A with a 150-tick dropped response,
D with a 150-tick discontinuous response, and F with a 150-tick dropped response.

| Case | Protocol | Condition | Latency ticks | Disposition | Terminal state |
|---|---|---|---:|---|---|
| `a-smooth-25` | A | `SMOOTH` | 25 | `WORKING` | `EMPTY` |
| `a-drop-150` | A | `DROPPED` | 150 | `NONWORKING` | `EMPTY` |
| `d-shift-25` | D | `TARGET_SHIFT` | 25 | `WORKING` | `EMPTY` |
| `d-discontinuous-150` | D | `DISCONTINUOUS` | 150 | `NONWORKING` | `EMPTY` |
| `f-alternative-25` | F | `ALTERNATIVE` | 25 | `WORKING` | `EMPTY` |
| `f-drop-150` | F | `DROPPED` | 150 | `NONWORKING` | `EMPTY` |

`analysis_included=false` for all six cases because this is qualification-only. No
scientific effect, promotion, runtime authority, or P4 eligibility is inferred.

## Raw evidence

Ignored local evidence is under
`experiments/02_action_chunks/results/engineering-qualification-v1/`. The raw event
ledger is 15,108 bytes and includes every request, delivery, acceptance/rejection,
issue, and hold transition. Raw trials and dispositions retain one row for every
scheduled case. The hashes are:

- `raw/manifest.json`: `450002d9ed82fd00388d25ed6c4c07027f8df9cf30ee71be54e713559d8c5b68`
- `raw/events.jsonl`: `1ff5081dba2d7fbed68a88ef429055db80b2275759d5cd2498a1d9dd9b9d3ba2`
- `raw/trials.jsonl`: `49961320fcf9b8ab3ddf70d5a0037e4f1362cb71d516e370b8a54559b01200f2`
- `raw/dispositions.jsonl`: `281e1088afd66b5be84565319db7799a70c4ae06c4332a1cb74505344e5db750`
- `derived/trial-table.csv`: `f95f1c823b034f3dbef240dcb532fdb1e80b398edd8260776757f6c60d2dac38`
- `derived/sample-index.json`: `3ccb3a741657e02c02bed3f46f60ba9dc12945fccbe81fc7cd36feacbd574225`
- `derived/recipe.json`: `1d96682e6f41f8eae58357813227aae986050962ec9b51b533813068cb778d28`

The sample index annotates observed working/nonworking representatives and explicit
`CLASS_NOT_OBSERVED` entries with eligible denominators; it never hand-picks across
the declared ordering.

## Reconstruction

The exact commands were:

```text
.venv/bin/python -m experiments.02_action_chunks.src.qualification --output-dir experiments/02_action_chunks/results/engineering-qualification-v1
.venv/bin/python -m experiments.02_action_chunks.src.qualification --reconstruct-from experiments/02_action_chunks/results/engineering-qualification-v1/raw --output-dir experiments/02_action_chunks/results/engineering-qualification-v1-reconstructed
diff -rq experiments/02_action_chunks/results/engineering-qualification-v1/derived experiments/02_action_chunks/results/engineering-qualification-v1-reconstructed
```

The final `diff -rq` produced no output: the trial table, annotated sample index, and
recipe were reconstructed byte-for-byte from raw inputs in a clean destination.

## Next empirical discriminator

This slice validates only the small A/D/F broker mechanics. The next scientific
vertical slice must use the exact A--G schedule, the P4 adapter and MuJoCo executor,
varied latency/move cells, and paired seeds. It must retain every failed or missing
case and must not reuse this qualification output as scientific evidence.
