# P3 Run Report

## Executive result

The bounded Experiment 00 source-compatibility gate passed locally. No comparative implementation-time claim was made.

## Environment

- Implementation/evidence-base Git SHA: `2a38fcda1b6abdfcfb6d3baf763dd7c1599457c4`
- Workspace: repository root
- Branch: `integration/autonomous-run`
- Platform contract: `darwin-arm64`
- Runtime contract: `mujoco-3.12.0;python-3.11.13`
- MuJoCo package: `3.12.0`

## Commands

Exact report command: `python scripts/write_p3_report.py --evidence-base-sha 2a38fcda1b6abdfcfb6d3baf763dd7c1599457c4`. The reporter executed only fixed local Git identity/blob reads; it ran no source operation, network request, or installation.

## Tests

P3 evidence validation: PASS. The report deterministically reconstructed the complete bounded artifact inventory at the evidence SHA.

## Results

- `docs/ASSUMPTIONS.md`: Git blob `6d06c49d062af4edef6b952d01216083ce1c6b0e`, SHA-256 `ffd3bfc466d12644227d59b983f2542cebf23db16af12e3b9b5b0f4ea0e4ad20`
- `docs/MATURITY_LEDGER.md`: Git blob `e8e128d78cbbac705230b91a63eaf39983259192`, SHA-256 `9646a40cd76ff8f41bf6eeff274604e5881fcadf97959881f798dbfed83ba7c6`
- `docs/RUN_MANIFEST.yaml`: Git blob `30f68e9ce1c4b322cad625ddce83a7f92e1058fe`, SHA-256 `3dfce8e084681128eae09fb135bf4df9498d357cdeb4ebf42cdb96f38bfe0575`
- `docs/SOURCE_MAP.md`: Git blob `10e71ca8f12e45facb1eff1533673e04dc1032dd`, SHA-256 `835fe0a1215e1d8b572d7d17abe5289da7f1e4bd954ac0f4f3869a27d850341f`
- `experiments/00_source_audit/INTERFACE_FINDINGS.md`: Git blob `e778bc3ac774f2f3a547d21444868e3eeaa761e2`, SHA-256 `f62b70c8545140c0a0622f376a607e62d39cbea9f2483a159cf16c1da42d37c1`
- `experiments/00_source_audit/MANIFEST_AMENDMENT.yaml`: Git blob `100c4268bfd55a89d4b75de1fd46707b315a7ee3`, SHA-256 `58a18736dbdee83081228a8ce3cc44c537c3c5bbbb56e2b9fe75c692ec95a67e`
- `experiments/00_source_audit/MANIFEST_AMENDMENT_R2.yaml`: Git blob `72c841dc9da3236fd93298fcc9fae1095895daa7`, SHA-256 `7d998f508d069e66b8742210700e3d09ac006626f3e9bf42650c79c46bd74c06`
- `experiments/00_source_audit/MANIFEST_AMENDMENT_R3.yaml`: Git blob `4927679d6ffcb6d345c7a61afdd927dc5c4f189a`, SHA-256 `0e33fd2d4b94a08788bd0c0990343e69db0950355bd0de0fef2bd15293a7b06c`
- `experiments/00_source_audit/RESULTS.md`: Git blob `943522ace97642be115e19e7cb1028953508e2c1`, SHA-256 `843a621453835d5d7826ec44f47172c10a688329c4e1374433196f1b72cf02a6`
- `experiments/00_source_audit/configs/lerobot-contained-symlinks-v1.json`: Git blob `04f230d94c5d6b5cedac8159833420c443b5d5a7`, SHA-256 `4ce69394bc36198ec39372b250804f341453a96b1778377fc2a2c8a23292b02f`
- `experiments/00_source_audit/configs/operation-manifest.yaml`: Git blob `36e74b023dad8ef66ac81b146bbfdbb1247c1586`, SHA-256 `00bbb8f33d5000302d76994a57933d3f29ed590f18df559b739e616b9d94ec26`
- `experiments/00_source_audit/results/attempts/lerobot-checkout-v1-fail.json`: Git blob `4c1f7f1f3839474815a7c7a9ac58fa56724cef9c`, SHA-256 `edcbb60b2a4d640fdae4affb3451977e2eabb6ef7fb83d9b65a7ac6cd25693fe`
- `experiments/00_source_audit/results/attempts/lerobot-checkout-v2-pass.json`: Git blob `5d024c6a37896b15df1bbde697c8476ebf3b6e1a`, SHA-256 `62cfdfac96ccf89c6de3e3ad8075293636fa4c223149939135e0d01a94805f32`
- `experiments/00_source_audit/results/compatibility.csv`: Git blob `93acc232627b5d0a8df6de57804d2e3a99d411d9`, SHA-256 `4c9a08281326350281681eb04167e4055a99b32e057e19a00062544ca785d519`
- `experiments/00_source_audit/results/fragments/act-checkout.json`: Git blob `2d7ca9f5464af535a7bb60ee5e898eabe3c5fc38`, SHA-256 `7072212cb9d2f4d4f1f9f19baaba8a81a203e395ae1baa43863fdef22d207388`
- `experiments/00_source_audit/results/fragments/behaviortree_cpp-checkout.json`: Git blob `0d680dfe2ee41400b6c4653af1caa69253c23de0`, SHA-256 `43d2c36164361e725f1371afab50a7841aa9e77287a7c68b946f6690a4f6cf32`
- `experiments/00_source_audit/results/fragments/lerobot-checkout.json`: Git blob `af9a194d98905a7b1818543146924c2433cab783`, SHA-256 `4bb7e2bf8697809e213c1635f030be9ab91c460ea87fe2901fb202315420bb44`
- `experiments/00_source_audit/results/fragments/mjctrl-ast.json`: Git blob `c083acb09f9e5032297166a38d73305ecad24fde`, SHA-256 `d06c6514a2081d9f90c40f25546c0db0cba12acadc730b08019016d382691399`
- `experiments/00_source_audit/results/fragments/mjctrl-checkout.json`: Git blob `3bf1281e00ddc935aa84c0336ce168cd507336d5`, SHA-256 `f341b99fd976ad4d76acdf46b358c3bb2ef63aad51ba3fe4a471f65913e6d616`
- `experiments/00_source_audit/results/fragments/mujoco-package-smoke.json`: Git blob `1e6da64d4e328947b4d1daead6aff86c117b7771`, SHA-256 `107c8fe3c0a031f4d842a4a537b97e3dee4c100d0adfa34435956c6a91489480`
- `experiments/00_source_audit/results/fragments/mujoco_menagerie-checkout.json`: Git blob `82ab1c924ce12072ee6f929898120f4f6b2b3390`, SHA-256 `7a10e840a7b371659191dd01c6e0d7df041fc0a4195cc1e70a2300b43dd77b35`
- `experiments/00_source_audit/results/fragments/mujoco_mpc-checkout.json`: Git blob `5b28756db88911ce03c7cb11eb0fb8efee17c605`, SHA-256 `f28b22990990b2efc6823f5daa9fcc5cfefd5cab8e23da88f6284cd46780bf82`
- `experiments/00_source_audit/results/fragments/navigation2-checkout.json`: Git blob `98f6ffc2999e0b30ced7eb9541962573053720f9`, SHA-256 `03b4acacfdbbe2fb6d6c69b806f5dfaf615e6d048bbaf4d3c4a12598c844786c`
- `experiments/00_source_audit/results/fragments/openpi-checkout.json`: Git blob `ec3c3c92203ea873d0c2105d5c9606e08355df68`, SHA-256 `f002cb171abdf0fae5e8953ff8156aae322d6324dd0e4522b590f44e5dd3817b`
- `references/licenses.md`: Git blob `cc8bfa87724c88e89d1320a7a893054d8ee29eb6`, SHA-256 `316dcb79b4b47cf660a6184d3a3d0401ccb8d9750b6fc8d2ed953b42d8f94e10`
- `references/p2-live-attempts.yaml`: Git blob `a7eb4b3f20bbff773fc99ad12255b36b74ecb975`, SHA-256 `61e93bb8b70b8ab9d2560b7fe7a8d1ee208429e89a149dbd5cbc6f4240dc19f8`
- `references/repos.lock.yaml`: Git blob `c390234e5ccc507be1fb5284daa86c5cb87f8bce`, SHA-256 `9a21b203bca93429384bafe78fe8a561922c215d82f6bd7dec629b88c6780538`
- `references/repos.yaml`: Git blob `8f006b7fc8d65d00bbe4fc1f9078d84108931e5a`, SHA-256 `eb72b501a177ee9dcf93a77444536e07dd532d9ac92950c61a063b8a8d1a4a3d`

Selected runtime artifact: `experiments/00_source_audit/results/fragments/mujoco-package-smoke.json`. Operational gate: PASS. Comparative implementation-time claim: INCONCLUSIVE.

## Public-source use

The registry and lock bind 45 public sources. Only the locked MuJoCo 3.12.0 package runtime is promoted as locally reproduced; sparse source inspections remain study evidence with recorded license provenance.

## Interface findings

Promote only the manifest-bound package/runtime seam and deterministic compatibility outputs. Static source inspection does not establish runtime compatibility.

## Blockers

NONE for opening bounded local experiment lanes. Physical deployment, remote execution, and comparative adoption-speed claims remain outside this gate.

## Highest-value next action

Run the first preregistered Experiment 01 local policy-control pilot against the frozen P3 interfaces.

## Safety

- No physical motor messages were sent.
- No non-loopback deployment connection or public inference server was used.
- No secrets or checkout/model artifacts are tracked.
- No unreviewed large model was downloaded.
- Physical deployment and remote execution remain disabled.
