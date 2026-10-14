# Stage3G presentation and independent risk audit

Frozen scientific files were not edited. The unfrozen plotting helper was corrected before plotting: the actual saved `parameter_choices.csv` column is `maximum_source_weight`; an earlier helper requested `max_source_weight`. This is a presentation/schema fix and changes no predictions, selection or evaluation.

`check_stage3g_risk_independent.py` was added after the scientific freeze as a read-only auditor, not upstream scientific code. It imports neither sklearn nor the Stage3G scientific implementation. It independently reconstructs the imputation/scaling from the named risk-training rows, saved logistic probabilities, source calibration support quantiles, source equal-SiteID/window weights, final thresholds from outer risk-OOF scores, and truth-independent SHA tie flags. It does not fit a model or select a parameter. Numeric score/transform comparisons use absolute and relative tolerance 1e-12; original-unit error subtraction uses the existing scientific tolerance 1e-8 m³ absolute / 1e-12 relative; saved review flags must agree exactly. This tolerance audit is not bitwise identity. Source and smoke reports are separate; the full report is written only if all full target rows are actually checked.

The source group-isolation/base fitting hierarchy is also checked by `check_stage3g_results.py`. Neither audit establishes physical-facility independence, real-time data arrival, predictive benefit or new algorithmic novelty.

Actual read-only audit commands:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv-stage2/bin/python scripts/check_stage3g_risk_independent.py --scope smoke
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv-stage2/bin/python scripts/check_stage3g_risk_independent.py --scope full
```

The first full independent-audit attempt incorrectly applied the dimensionless 1e-12 absolute tolerance to m³ subtraction. Eight long-table rows (two distinct forecasts repeated across four risk methods) exceeded that dimensionless rule; the maximum original-unit discrepancy was 8.731149137020111e-11 m³, and every row passed the already defined scientific 1e-8 m³ absolute / 1e-12 relative tolerance. The auditor was corrected to apply the documented units; scientific code, predictions, events and flags were not altered. The failed attempt is retained in `validation/stage3g_independent_risk_full_initial_tolerance_failure.log`. This is a numeric-tolerance audit, not bitwise result identity.
