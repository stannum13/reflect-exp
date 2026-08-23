# Invalid execution provenance

Status: `INVALID_EVIDENCE`

This first execution is preserved as a nonworking operational sample. The
runner was frozen at Git commit
`9369114fc5dffa32b00866526d2bf82b71ab7bd8`, but the launch argument recorded
the nonexistent SHA `9369114b4023dba107cd94bad3be90788dd58179`.

No outcome or implementation changed after discovery. The canonical replacement
is `results/exp04-unfixed-memory-indicative-v2`, rerun from the same frozen source
with the correct immutable Git identity. Do not cite this v1 result as evidence.
