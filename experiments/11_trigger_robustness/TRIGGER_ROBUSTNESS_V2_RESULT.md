# Experiment 11 V2 Trigger Robustness Dose Response

Status: `VALIDATED_SYNTHETIC_ENGINEERING_EVIDENCE`. Scope: `SYNTHETIC_TYPED_ORACLE_TRIGGER_ENGINEERING_NOT_VLA`. This experiment used no physical or remote execution and is not VLA evidence.

## Frozen execution

- Source commit: `e1cd3b3fff900ee8bf7dfa4b61bb46a04a6b286e`.
- Source closure SHA-256: `722bdcc07223b9d07690b14274930f907df14acaacea15f3cb657f55e5d5ca42`.
- Configuration SHA-256: `e41281cc369609d2affb3fc60c046ef820cb3c8bcb6cf1571a01f98bc49f9bef`.
- Seed-manifest SHA-256: `7a9c58b3767c2d289f613f57d4b93508cf1d710bcbd78b379df5dcb914293736`.
- Matrix SHA-256: `d4551145b002ea8471078d51d6f15543d4f172dab6cce95a1c8ec67d564ace8d`.
- Exact matrix: 46,080 episodes using 12 paired seeds `20266301..20266312`; 46,080 starts, 552,960 ticks, and 46,080 terminals were independently replay-scored.

The replay scorer is a separate implementation that does not import or call the generator kernel. Cross-implementation fixture controls agree, and a generator-only action-validity mutant is rejected by replay.

## Paired inference

All 28 preregistered effect IDs were estimated for completion, progress, and cost, yielding 84 paired contrast rows. All 84 gates passed with effective seed-cluster n=12 and exactly 10,000 bootstrap draws; no gate failed.

- Strongest storage completion contrast: `STORAGE_LIVE_EPISODIC_MINUS_LIVE_BELIEF__FAILURE_THRESHOLD__COMPACT_TYPED`, estimate `+0.546875`, 95% interval `[+0.54305556, +0.55069444]`.
- Strongest positive policy completion contrast: `POLICY_EVENT_DRIVEN_MINUS_PERIODIC_ONLY__LIVE_BELIEF__VERBOSE_TYPED`, estimate `+0.33819444`, 95% interval `[+0.32534722, +0.35069444]`.
- Prompt completion contrasts were exactly `0.0`; the largest prompt cost contrast was `PROMPT_VERBOSE_TYPED_MINUS_COMPACT_TYPED__LIVE_BELIEF__PERIODIC_ONLY`, estimate `+5.509375`, 95% interval `[+5.37916667, +5.63958333]`.
- The best aggregated storage/policy/quality/prompt completion was `1.0`; the worst was `0.25`.

The derived evidence additionally contains 336 preregistered disturbance-family heterogeneity rows and 16 storage/policy/prompt slope-and-cliff rows. Working and nonworking episode samples retain complete raw-ledger ancestry.

## Graph and reconstruction integrity

The graph table keeps `LIVE_BELIEF` and `LIVE_EPISODIC` as separate series. `plot-metadata.json` declares storage pooling `NONE` and the sole transformation `ARITHMETIC_MEAN_OVER_DECLARED_NUISANCE_AXES`; both SVG panels and PNG points are generated from the authenticated graph table.

- Root manifest SHA-256: `fe3d5e74ec42ce741e6b9fac9c66be8679f12ad7c0e9280b8d4e9cf9005ccb0a`.
- Raw manifest SHA-256: `8d1b143366e7a9f0d32663fc4b10fc79810ecbc0377eac3dfb03a0d4895264cb`.
- Derived manifest SHA-256: `f279b613eb9d9241ddef7c6a4d62f33ac2e2b42e8fc144420c5caa25b31903ac`.
- Graph-table SHA-256: `1bd7c7c03a8820a6c8aac82861d2fa0cd5dae42f0ffb474172328bbe98ed786c`.
- SVG SHA-256: `11da7420a49f07a16d53a97ead6cfe4e61747ded89a17fac211734eb27544009`.
- PNG SHA-256: `8ccddf659ad1697f24b562cb6c53e77cfd994bf9f467d2cd94f08e80f0ba5214`.

A fresh reconstruction at `/private/tmp/exp11-v2-reconstruct.a4CTKe/rebuilt` authenticated the external root-manifest receipt, exact source Git blobs, config, seeds, matrix, recursive raw/root/derived inventories (including manifest files), rejected symlinks by contract, independently replayed raw ledgers, recomputed every derived table/statistic/graph from raw, and produced the same root-manifest SHA-256 byte-for-byte.

## V1 preservation and disposition

Experiment 11 V1 remains byte-for-byte unchanged and has disposition `INVALID_REJECTED`, claim authority `NONE`. Its retained raw-manifest SHA-256 is `0b5f7565c950765fcc7a226e43963847ce0811728a1296d27949913aaa0194cb`; its retained derived-manifest SHA-256 is `faa187325ce1e432adbb7d9307c55ad954a006c3c41471c69afde26c23dca3b4`. The exact closed registry is `configs/retired-attempts-v2.json`.
