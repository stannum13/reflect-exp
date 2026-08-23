# pi0.5 Semantic-Interface Feasibility Result

Disposition: **NOT_RUN_NO_CHECKPOINT_BACKEND**

Pinned OpenPI `15a9616a00943ada6c20a0f158e3adb39df2ccac` exposes a flow-matching action sampler. Its public policy and websocket path return action chunks, state, and timing; they expose no semantic token/text plan field or semantic decoder. The DROID configuration returns a 15 x 32 action chunk.

The official BasePolicy source executed locally with a deterministic transport fixture, proving the callable API boundary only. It was not checkpoint inference. The full frozen runtime dry-run failed because `jax-cuda12-plugin==0.5.3` has no macOS arm64 wheel. No checkpoint was downloaded. Metadata identifies 20 objects totaling 12429488598 bytes. No authenticated remote backend was configured.

Inference boundary: source inspection, official base-policy invocation, dependency resolution, and checkpoint metadata only. No model forward pass, semantic plan, motion plan, controller action, or scientific outcome was produced.

Next executable route: run this exact pinned source and checkpoint on a supported NVIDIA Linux host, or configure an authenticated OpenPI websocket server that supplies immutable checkpoint identity and a forward-pass receipt. Even then, Exp09 needs a separately specified semantic decoder/interface because the official endpoint itself returns actions only.
