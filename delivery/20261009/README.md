# Verified development delivery — 9 October 2026

This delivery branch contains existing, verified artifacts copied without rerunning experiments or rebuilding the manuscript. It does not change the repository main branch. The manuscript is a **six-page development draft**, not a completed shared-learning/final-test journal paper.

| File | Size (MiB) | Contents |
|---|---:|---|
| Wastewater_Results_20261009_redelivery.zip | 15.16 | Code, fixed configurations, saved predictions/metrics/logs, provenance, actual figures and editable draw.io sources |
| Wastewater_Audit_20261009_redelivery.zip | 22.43 | Complete original derived row audit, candidate table, flags, rules, summary and manifest |
| Wastewater_Draft_20261009_redelivery.pdf | 0.266 | Locally compiled six-page English development draft |
| Wastewater_Overleaf_20261009_redelivery.zip | 0.037 | Verified paper sources, bibliography and figures; no full raw dataset |

Each ZIP is under 24 MiB. ZIP CRC, all internal SHA256 entries and the complete artifact SHA256 were checked against the original delivery. The PDF was parsed and confirmed to have six pages. Checksums are in SHA256SUMS.txt.

Download files individually using GitHub's **Download raw file** button on each file page. Do not use a repository-wide ZIP as a substitute for the individual deliverables; it combines all four files. Private repository access requires signing into an authorized GitHub account.

The main results are ten exploratory SiteIDs, twelve completed development runs and 129,600 model prediction rows. Site identifiers are not verified independent physical facilities. Local ridge had negative mean MAE skill versus persistence in every tested budget/horizon/delay condition; all 687 negative predictions are retained. Shared models, prediction intervals and final 2024–2025 forecast evaluation have not been run. Historical observation arrival/revision timing is unverified; results are retrospective scenarios, not a validated online deployment.

For Overleaf, upload only Wastewater_Overleaf_20261009_redelivery.zip and choose main.tex / pdfLaTeX. The exact original source archive was extracted and compiled locally; this transfer does not claim an Overleaf account sync or journal submission.
