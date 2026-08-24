# Experiment 11 V1 Reconstruction Disposition

Disposition: `INVALID_REJECTED`. Claim authority: `NONE`.

V1 is retained byte-for-byte as the actual retired attempt. Its raw manifest SHA-256 is `0b5f7565c950765fcc7a226e43963847ce0811728a1296d27949913aaa0194cb`; its derived manifest SHA-256 is `faa187325ce1e432adbb7d9307c55ad954a006c3c41471c69afde26c23dca3b4`. The closed machine-readable ledger is `configs/retired-attempts-v2.json`.

V1 cannot support claims because the replay scorer called the generator, the freeze omitted transitive package identity, inventories were shallow and did not authenticate manifests, no preregistered paired contrasts were reported, storage series were pooled in graphs, and derived validation did not independently recompute outputs.
