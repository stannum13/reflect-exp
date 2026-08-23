# Experiment 11: Trigger Robustness Dose Response

## Disposition

`COMPLETE` for synthetic trigger-transport engineering. This experiment used `DETERMINISTIC_TYPED_ORACLE_V1`; it did not run or approximate a VLA and provides no frontline-model evidence.

The valid namespace contains 46,080 paired episodes, 552,960 exact ticks, and 46,080 terminal rows over twelve seed clusters. Every raw episode independently replayed, the committed raw/derived manifests validated, and a fresh reconstruction matched byte-for-byte at tree hash `c57e3f906c2ff54666db266e110eb91f7dda0d16df02635fa2886d72adcf3caf`.

## Directional results

Across all ten observation-quality profiles, live+episodic storage was the dominant design:

| Storage | Trigger | Mean completion | Mean cost proxy | Hostile completion (seed-cluster 95% CI) |
|---|---:|---:|---:|---:|
| Live+episodic | Failure threshold | 1.000 | 14.87 | 1.000 [1.000, 1.000] |
| Live+episodic | Hybrid | 0.975 | 35.05 | 0.750 [0.750, 0.750] |
| Live+episodic | Periodic | 0.950 | 31.26 | 0.500 [0.500, 0.500] |
| Live+episodic | Event driven | 0.845 | 18.71 | 0.660 [0.601, 0.719] |
| Live belief | Event driven | 0.845 | 18.75 | 0.660 [0.601, 0.722] |
| Live belief | Hybrid | 0.819 | 40.81 | 0.399 [0.358, 0.438] |
| Live belief | Periodic | 0.492 | 36.92 | 0.389 [0.361, 0.417] |
| Live belief | Failure threshold | 0.456 | 41.14 | 0.250 [0.250, 0.250] |

Mean completion averaged across policies and quality profiles was 0.942 for live+episodic versus 0.653 for live belief, a +28.9 percentage-point association. The trade-off is retained episodic state plus its read/write and byte costs. Under the hostile profile, event-driven transport retained only 0.545 recall and 0.273 precision, with completion 0.660; failure-threshold+episodic remained at 1.000 because it recovered from authenticated action failure rather than depending on event delivery.

Clean-to-hostile normalized slopes per profile interval were -0.0667 for live-belief hybrid, -0.0556 for live+episodic periodic, -0.0378 for both event-driven stores, -0.0278 for live+episodic hybrid, -0.0123 for live-belief periodic, and 0 for both failure-threshold variants. The largest registered profile transitions were:

- live-belief hybrid: -0.413 after `Q08_GUARDED`;
- live+episodic periodic: -0.500 after `Q08_GUARDED`;
- live+episodic hybrid: -0.250 after `Q08_GUARDED`;
- event driven: -0.188 after `Q00_CLEAN` for either store;
- live-belief failure threshold: -0.750 after `Q05_DELAY3`;
- live+episodic failure threshold: no drop.

These profile transitions are engineering cliff indicators, not derivatives of one scalar corruption axis: the frozen profiles deliberately combine recall, delay, burst, ordering, cooldown, and hysteresis, and some delayed/duplicate profiles improved alignment. The authoritative per-profile and one-cell tables should be used for causal interpretation.

The hardest physical families were pose shift (0.724 completion), availability loss (0.728), and restriction change (0.739); control failure was 1.000 because failure feedback made the required retry observable. Completion increased from 0.773 at horizon 4 to 0.825 at horizon 12. Compact and verbose typed envelopes had identical completion (0.7977); verbose envelopes increased transport/storage cost but did not change semantic content.

## Examples and boundaries

Working: clean event-driven/live-belief, pose shift, horizon 12 completed with progress 16, one wake, zero retries, and cost 8. Nonworking: clean periodic/live-belief, pose shift, horizon 4 ended at progress 1 with two wasted wakes, seven retries, and cost 27.

The first unpublished attempt was invalidated because its transport draw included policy/storage/prompt identity. Seeds 20266101..20266112 were retired before publication; its tree hash and typed reason are frozen in `configs/retired-seed-namespaces.json`. Published outcomes use 20266201..20266212 with a test proving shared transport realization across paired policy, storage, and prompt cells.

Authoritative tables are `results/v1/derived/bootstrap.csv`, `graph-table.csv`, `heterogeneity.csv`, and `slopes-cliffs.csv`. Their SHA-256 values are respectively `e0d3f4b6bc14555284b64af87411be5d2e83e20ff00e583aa390837314eead0b`, `906519828de213a445e7a5122d7c700fbf12567bf76842e6e7ad48ecc2941afc`, `289046895f3c52cd800189a91a8f8df0c77b3de131a47cff309c86b4808e6b11`, and `e8d389bbde5f103d498bc74799b64d0d5fc52c47c6443c4e1961f2c39832e7a9`.
