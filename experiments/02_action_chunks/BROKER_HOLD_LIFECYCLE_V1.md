# Broker Hold Lifecycle Qualification V1

This record is real execution of the Experiment 02 integer-tick broker at commit `79d23b5`. It is qualification-only: it proves broker lifecycle behavior, not MuJoCo dynamics or policy efficacy.

Across fresh seeds 200–207, all 48 trials matched the preregistered timing relation and ended `TERMINAL_EMPTY`:

| vector | boundary result | latency-150 result |
|---|---|---|
| v0 (`J_E=25`) | 0 hold ticks, 0 safe-hold transitions | 125 hold ticks, exactly 1 transition |
| v1 (`J_E=75`) | 0 hold ticks, 0 safe-hold transitions | 75 hold ticks, exactly 1 transition |
| v2 (`J_E=124`) | 0 hold ticks, 0 safe-hold transitions | 26 hold ticks, exactly 1 transition |

Every issued action was a copied, C-contiguous, read-only float64 row. Each long-latency gap latched the measured position once and used that value for the complete contiguous hold. Equality delivered the successor at half-open expiry without an intervening hold tick.

Evidence hashes:

- manifest: `ce9679b8b758bc3f4229901c5e41b54f48fc0b2b926a97bf2e8bbcfecb8b8fdf`
- trials: `40480664f6079fefb0cc15078aad8063c23881f7c1ede553cf18ecc004306ab9`
- events: `f3bb47b50d61073a695e49880b0cb7d1c45e31af2c734b3a591635a6996df37e`

The remaining Task 3 claim surface—C/F/G transforms, complete rejection ordering, and fault payloads—is not validated by this record.
