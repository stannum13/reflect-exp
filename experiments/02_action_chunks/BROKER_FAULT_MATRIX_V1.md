# Broker Fault Matrix Qualification V1

This qualification-only record executes the Task 3 broker and sealed fault transform at implementation commit `25a7d62`. It is not MuJoCo, policy-efficacy, or runtime-authority evidence.

Eight fresh seeds (300–307) produced 56 retained trials:

| case | disposition | count |
|---|---|---:|
| direct acceptance | `WORKING` | 8 |
| C ensemble derivation | `WORKING` | 8 |
| F overlap blend | `WORKING` | 8 |
| G RTC approximation | `WORKING` | 8 |
| expired response | `NONWORKING` | 8 |
| drop-to-hold | `NONWORKING` | 8 |
| injected P4 discontinuity | `NONWORKING` | 8 |

The expired response is retained as `CHUNK_REJECTED/EXPIRED`. Each drop-to-hold case records the complete hold tick list, exactly one safe-hold transition, and terminal-empty closure. Each discontinuity retains all 125 pre/post-relevant output rows in `payloads.jsonl`, fault revision `exp02-fault-payload-v1` through the implementation identity, and a hash distinct from its unchanged source.

Evidence hashes:

- manifest: `083cb8dc898f13aa05996d8bb8c22acaf897bdafb588d556d1ff882136383c2e`
- trials: `3111f71580bf3bdb1f0ff9195525df147c1ca85bc697d103b795c81a480e861e`
- events: `6c5a1e2384750e0974174070c75693a9b1e20a321799d733c431dc82b271741f`
- payloads: `2125dc402c24f1af9bcc2021522273e56427474b701bf2dbcac60543bcb63d8d`

This seals the requested Task 3 qualification evidence. Work must not advance to Task 4 based on this record alone.
