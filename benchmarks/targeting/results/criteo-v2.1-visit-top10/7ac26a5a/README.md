# Full Criteo v2.1 locked targeting evidence — `7ac26a5a`

This directory persists the compact evidence bundle produced by GitHub Actions run `33263792683` from GrowthEvo commit `7ac26a5aebde2c70e1b43264b89f08dddcff0245`. That evidence commit is an ancestor of main merge commit `0e8cfd3cdeed4687b67dc3f8d817bfefa7bc6ee2`.

The experiment was pre-registered by `benchmarks/targeting/criteo-v2.1-visit-top10.v1.json`. Five fixed LightGBM 4.7.0 CATE configurations were trained only on the training split and compared only on randomized validation evidence. The validation winner was frozen before a second source pass exposed final holdout, and only that winner was scored on holdout.

## Dataset and protocol

| Field | Value |
| --- | --- |
| Dataset | Criteo Uplift v2.1 |
| Source rows | 13,979,592 |
| Outcome | `visit` |
| Treatment | randomized `treatment` |
| Forbidden post-assignment feature | `exposure` |
| Split | 50% train / 25% validation / 25% holdout |
| Split strategy | SplitMix64 source-row assignment, seed `20260830` |
| Training rows | 6,990,168 |
| Validation rows | 3,494,354 |
| Holdout rows | 3,495,070 |
| Frozen propensity | training treatment share = `0.8501983071` |
| Targeting policy | treat top 10% by CATE score |
| Candidates | S / T / X / R / DR LightGBM |
| LightGBM | 4.7.0, deterministic CPU, no validation HPO/early stopping |

`exposure` is post-assignment and was not loaded as either treatment or feature. The propensity used for randomized Horvitz–Thompson evaluation was estimated from the independent training split and frozen before validation; reported inference is conditional on that frozen propensity.

## Locked validation selection

Validation ranking by randomized population incremental visit value versus treat-none:

| Rank | Candidate | Population increment | Selected-group increment |
| ---: | --- | ---: | ---: |
| 1 | **S-Learner** | `0.0096579179` | `0.0965792899` |
| 2 | X-Learner | `0.0093758434` | `0.0937585410` |
| 3 | DR-Learner | `0.0093340850` | `0.0933409566` |
| 4 | R-Learner | `0.0092452964` | `0.0924530700` |
| 5 | T-Learner | `0.0089461680` | `0.0894617825` |

S-Learner won this **specific frozen validation cohort**. This is not a universal claim that S-Learner dominates DR/R/X learners. GrowthEvo selects the predeclared candidate supported by locked validation evidence instead of forcing the newest estimator to win.

## Final holdout

Only `s-lgbm` was scored on final holdout.

| Metric | Locked result |
| --- | ---: |
| Holdout rows | 3,495,070 |
| Selected fraction | 10% |
| Treat-none value | `0.0381058865` |
| Locked policy value | `0.0474849889` |
| Population incremental visit value | **`0.0093791024`** |
| Population standard error | `0.0002146266` |
| Population 95% CI | **`[0.0089584420, 0.0097997628]`** |
| Selected-group incremental visit value | **`0.0937910242`** |
| Selected-group standard error | `0.0021462659` |
| Selected-group 95% CI | **`[0.0895844204, 0.0979976281]`** |
| Treat-all value | `0.0483788909` |

Interpretation: `0.0093791024` is an **absolute population visit-probability increment**, i.e. about **+0.93791 percentage points** versus treat-none. `0.0937910242` is the corresponding absolute incremental visit effect among the selected top 10%, i.e. about **+9.37910 percentage points**. The locked policy value is about **24.61% higher relative to treat-none**, but that relative ratio is not the historical repository metric called `Uplift@10%`.

The historical `+6.8%` Criteo record is pre-locked, uses a different protocol/metric definition, and is not numerically comparable to this result.

## Provenance

- Evidence commit: `7ac26a5aebde2c70e1b43264b89f08dddcff0245`
- Main merge commit preserving it: `0e8cfd3cdeed4687b67dc3f8d817bfefa7bc6ee2`
- GitHub Actions run: `33263792683`
- Actions artifact ID: `9718130078`
- Actions artifact digest: `sha256:bbdc93a306e532ba6f880dadf409808b65c3dea872a7b41032f4b2e09819ada0`
- Experiment-plan fingerprint: `28a0ee4516199f2235bc9d52653cc8ab7ec28f5d`
- Candidate-config fingerprint: `e10eb2fc6552b28109b67cfe075b55fd1d0e8f62`
- Export-manifest fingerprint: `f765bf351f6b4e2e11fcc464ebd115fddf77520c`
- Locked protocol fingerprint: `95a3209a87ad8aa3b7b6d9f3933fade51cb3c9fe`
- Validation fingerprint: `dedf85dec29c0f6731a81bcb52d1e3e6db379de4`
- Holdout fingerprint: `3b187bd143e729b7d2ee60c8f28c5f438ec61709`
- Pinned Criteo source commit: `82811785048bb633de2d55c02bab4e57066e6423`
- Pinned Criteo source SHA256: `2716e1bf0fd157a93b5bf86924d9088419dfbac2022c6cd90030220634f616dc`

`environment.txt` is the exact `pip freeze` captured by the successful full-data workflow. `evidence-metadata.json` records both the uploaded artifact digest and SHA256 for every source-artifact file.

Raw Criteo data, train arrays, validation score arrays and holdout score arrays are not stored in git.
