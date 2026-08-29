# Full Open Bandit locked OPE evidence — `7d538cea`

This directory persists the compact evidence bundle produced by GitHub Actions run `33254728121` from GrowthEvo commit `7d538cea9698b5f0a48c585eed85e3ae526e5af6`. That commit is an ancestor of main merge commit `075124fc11cfa8181715f27338afe9fef54b4af9`.

The experiment was pre-registered by `benchmarks/ope/obd-full-all-random-to-bts.v1.json`. Nine estimator configurations were compared **only on the validation reference**. The winning configuration was then frozen and revealed once on final holdout.

## Dataset and protocol

| Field | Value |
| --- | --- |
| Behavior policy | random |
| Evaluation policy | BernoulliTS |
| Campaign | all |
| Random-policy rows | 1,374,327 |
| BTS reference rows | 12,357,200 |
| Validation fraction | 0.5 |
| Q model | 3-fold cross-fitted logistic |
| BernoulliTS simulations | 100,000 |
| Validation support gate | >= 0.95 |
| Validation ESS-ratio gate | >= 0.05 |
| Final support gate | >= 0.95 |
| Final ESS-ratio gate | >= 0.05 |

## Locked selection

Validation ranking by absolute error:

| Rank | Candidate | Validation absolute error |
| ---: | --- | ---: |
| 1 | IPS | 0.0000599942 |
| 2 | DR | 0.0000781114 |
| 3 | SNIPS | 0.0000808755 |
| 4 | cross-fitted beta*-IPS | 0.0000839676 |
| 5 | Meta-BLUE | 0.0000863754 |
| 6 | SWITCH-DR, threshold 10 | 0.0005727031 |
| 7 | SWITCH-DR, threshold 5 | 0.0009256920 |
| 8 | DR-OS, lambda 10 | 0.0009745007 |
| 9 | DR-OS, lambda 1 | 0.0011962679 |

IPS won this **specific frozen validation cohort**. This is not a claim that IPS is universally superior to the newer estimators in the candidate set; GrowthEvo deliberately prefers observed locked-validation performance over estimator novelty when choosing what is allowed to see final holdout.

## Final holdout

| Metric | Value |
| --- | ---: |
| Selected estimator | IPS |
| Estimate | 0.004529543456874923 |
| On-policy reference | 0.0049885087236590814 |
| Absolute error | 0.00045896526678415855 |
| Relative error | 9.2004503191% |
| Standard error | 0.0002042613746779296 |
| Support coverage | 1.0 |
| Effective sample ratio | 0.16123376175710658 |
| Maximum importance weight | 19.5984 |

Validation support coverage was `1.0` and validation effective-sample ratio was `0.16144245093091883`; both validation and holdout passed the predeclared evidence gates. Tuning fingerprint `3f4698265dc1e1f77003788e8b48e2347b826cf5` differs from test fingerprint `d93bdd9361bd9d5d7d6e8552f67b0134600474c1`.

## Provenance

- Experiment-plan fingerprint: `4466cd81502843a349e52fc00f1e834e1a28b98b`
- Export-manifest fingerprint: `9c377a8a69bd158c477c1f789f0e57b150abdbfa`
- Locked protocol fingerprint: `b9206804bde8752a88b2a03bbda4b648f648f891`
- Actions artifact digest: `sha256:b7dbd5afbb331de40b73b5657f7ccdd753ac4c894921dc08dc5d6373c082cc83`
- Pinned mirror revision: `57a688e`
- Random/all SHA256: `f24fdf91e38de41dcd15f2482279358766556be04155b35882e327b465d104b7`
- BTS/all SHA256: `05ba8416e6626be0dc16ee09a434d736eca1c4c274e10eabe3931521c4aeede2`
- Item-context SHA256: `88345bc52dea9965cf148f02c661d03ce566f278b2b870ec0c70c5d3da1c2d1c`

`environment.txt` is the exact `pip freeze` captured by the full-data workflow. It intentionally preserves the upstream packaging fact that both `sb-obp==0.5.10` and `obp==0.4.1` distributions were installed, while the imported OBP module reported version string `0.5.5` in the export manifest.

The checked-in evidence is compact. Raw OBD CSV files and generated validation/holdout JSONL are not stored in git.
