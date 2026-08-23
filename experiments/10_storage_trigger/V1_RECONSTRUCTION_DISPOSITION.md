# Experiment 10 V1 reconstruction disposition

Status: **SUPERSEDED — internally consistent but insufficient for independent reconstruction**

The V1 source and evidence at commits `f6d4448` and `6a94954` remain byte-identical. Independent review reproduced all 12,000 retained identities, all 120,950 step-to-summary metrics, all 50 paired-bootstrap rows, and the 10-file derived reconstruction. The retained raw and derived manifest hashes are respectively `45d5facb9bc3376f5d3b69a9296fdf3e2f404f1acedfb136a1ab524f57b49cb7` and `0ec41b0c3bb95270671e888b8176d4498a2b5d5d68bfe55a296a05ea7dc64fc7`.

V1 is nevertheless insufficient as scientific reconstruction evidence because its scorer trusts executor-authored step validity, failure, and completion-progress fields; its reconstruction does not enforce the exact config/seed/Cartesian/source closure; and its manifest validator ignores nested unlisted members. Those defects do not prove the committed V1 rows were dishonest, but they prevent approval of V1 as independently authenticated evidence.

V1 may be cited only as a deterministic implementation trace that motivated V2. It must not be pooled with V2, used as a confirmatory sample, or described as independently reconstructed evidence.
