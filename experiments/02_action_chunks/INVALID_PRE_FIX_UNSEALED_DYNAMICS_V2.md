# INVALID_PRE_FIX: Unsealed Dynamics V2

Every trial under `results/unsealed-dynamics-v2` has effective disposition `INVALID_PRE_FIX`. Its embedded `WORKING`/`NONWORKING` labels are superseded and must not be used for protocol ranking, promotion, causal inference, or pilot evidence.

Reason identifiers:

- `PREFX_BROKER_BYPASS`: the runner maintained its own active executable instead of using the total `TemporalBroker` lifecycle.
- `PREFX_UNSEALED_PROPOSAL`: normalized proposals were publicly forgeable and dispatch did not enforce complete raw/inverse binding.
- `PREFX_DERIVATION_INCOMPLETE`: C/F/G parent ordering, coverage, positive overlap, full suffix, and output identities were not evidence-complete.
- `PREFX_EVENT_LINK_INCOMPLETE`: event/recipe reconstruction did not validate the complete proposal-to-parent-to-issued chain.

Preserved identities:

- implementation: `73c6fb68277290d58ae958738072f1d0d6ffc950`
- raw manifest SHA-256: `ef23206fa6f99feb2b2d6d8b24eddc919696a0f8bf4610e1898f4810b80ce44d`
- trials SHA-256: `9a773632682cb50ff3c03321df6b7928a47e94377aa89e71d33c6b3976cb026c`
- events SHA-256: `bec56e2613f626483fab153ed1843403257a554d71a36bcb08f51631e34d2818`
- preserved tree SHA-256: `611c031c9a666153647d9d54c0482504fea4a2bdba724f58a813cb453ede7ca6`

The raw directory is retained byte-for-byte and will not be overwritten. Any post-fix run must use a new result identity and implementation commit.
