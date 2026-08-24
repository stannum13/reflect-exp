# pi0.5 Semantic-Interface Feasibility V2

Disposition: **NOT_RUN**. Model inference: **NOT_RUN**.

Pinned source receipts independently derive a 15 x 32 internal model action array followed by the DROID public output transform `[..., :8]`. The public policy response is therefore 15 x 8 `actions` plus `policy_timing`; `server_timing` is added only by the websocket server. `state` is not in the public DROID response.

The transport/interface fixture is synthetic and working. It proves serialization shape only. No model forward pass was run, no checkpoint bytes were downloaded, and no physical execution occurred. No semantic decoder, text output, or semantic plan output exists in the inspected public response closure; no semantic plan was produced.

V1 is retained byte-for-byte but rejected and superseded because it conflated the internal 15 x 32 model shape with the transformed public interface, retained unsafe receipt material, and did not close replay against coherent rehashing.
