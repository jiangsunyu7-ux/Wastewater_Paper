# Stage3G CPU reproduction

Version: `stage3g_transfer_reliability_v1`. New bounded SiteID development experiment after repeated use of the same 2022–2023 windows. Physical-facility independence and daily observation/QA arrival remain unverified. Do not use final2024–2025 or protected-facility performance. No new GRU, rainfall, interval, App or manuscript work is included.

This guide lists the actual experiment entry points. Final command outcomes, timings and independent checks are recorded in the supplied validation logs and stage receipts; a command written here alone is not evidence of execution. Colab notebook code has local offline checks; logged-in Colab/Drive execution is unverified.

## Extract all required payloads

Extract Code_and_Reproduce and **every** Predictions_and_Diagnostics part into one new empty directory, preserving repository-relative paths. Quick_Review contains interpretation, not alone the full scientific evidence. Extract Delivery_Index separately to inspect ARTIFACT_INDEX.json and PACKAGE_CHECKS.json. Every ZIP has PACKAGE_MEMBER_SHA256.json; its own digest is omitted deliberately because the external index hashes the complete ZIP. Duplicate PACKAGE_README/manifest names across parts are package-control metadata only; scientific paths stay unique within each ZIP.

The Code package includes the frozen cleaned C2 calendar input (2016–2023 only), original fixed K30 pool and connected-group ledger, and transitive imported helpers. It does not include whole old scientific ZIPs or their predictions. The original raw Wessex CSV is not necessary to re-run **this unchanged-cleaning Stage3G experiment** from the audited canonical input; reproducing raw-to-cleaned preparation is a separate C2 dependency, described in INPUT_DEPENDENCIES.json. Do not claim an independent raw-cleaning audit merely because the canonical-file SHA passes.

## Prepare a pinned environment

Run from the extracted project root. Python3.12 was used. Installation is needed only for a new environment; the original experiment reused its existing `.venv-stage2`.

```bash
python3.12 -m venv .venv-stage3g
.venv-stage3g/bin/python -m pip install -r requirements-stage3g.txt
export PYTHONPATH=src
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
TASK_PY=.venv-stage3g/bin/python
```

Use the scientific-package versions in requirements-stage3g.txt exactly. The runner refuses mismatched frozen config/data/code/package fingerprints. The Git base commit alone does not represent untracked science; CODE_VERSION.json registers actual content hashes and the true checkout commit separately.

## Inspect and verify existing evidence without new fits

```bash
$TASK_PY scripts/check_stage3g_results.py --scope smoke --config configs/stage3g_transfer_reliability_v1/full.json
$TASK_PY scripts/check_stage3g_results.py --scope full --statistics --config configs/stage3g_transfer_reliability_v1/full.json
$TASK_PY scripts/summarize_stage3g.py --config configs/stage3g_transfer_reliability_v1/full.json
```

The independent checker imports no Stage3G scientific implementation and checks saved rows against canonical data, explicit Ridge normal equations, legal dates, source roles, frozen weights and separately recomputed primary intervals. Declared tolerance is normalized absolute/relative1e−10; lambda0 is exact Persistence. These are numerical-tolerance checks, not a claim of universally bit-identical CPU output.

The evaluator checks every expected task's on-disk status, fingerprint and members. A PARTIAL result is not complete even if failed=0. It reads saved predictions and risk outputs; it never fits a predictor. Review the actual generated evaluation_validation.json and audit/INDEPENDENT_RESULTS_CHECK_FULL.json. For byte-level supplied-file integrity use the package manifests and external SHA256SUMS.txt before running commands that rewrite metadata.

## Boundary and software tests

```bash
$TASK_PY -m unittest discover -s tests -p 'test_stage3g*.py' -v
```

Synthetic fixtures test calendar/label boundaries, weighting, fallback, strict role exclusion, risk thresholds, atomic/cache checks and resume. Passing fixtures do not verify real facility independence, live data arrival or scientific benefit.

## Source preparation and strict source risk cross-fit

```bash
$TASK_PY -m wastewater.stage3g_experiment --mode prepare-source --config configs/stage3g_transfer_reliability_v1/full.json
$TASK_PY scripts/run_stage3g_reliability.py source --config configs/stage3g_transfer_reliability_v1/full.json
```

With the supplied validated source caches, these commands verify and reuse them. Cache verification/replay is not a newly trained source experiment. Global source candidate grids and nested risk upstream selections are retained, including negative choices and all3 pools. Genuine cold source preparation requires running in a **second copy** whose `runs/stage3g_transfer_reliability_v1/source` directory is absent; retain the delivered original untouched. Base fit labels stop2020 in source selection/OOF; final point fit labels stop2021. Source2021 retrospective group-out reconstruction is assembled after that year and is not a claim of January2021 online availability.

## Small full-pipeline smoke and independent check

```bash
$TASK_PY -m wastewater.stage3g_experiment --mode smoke --config configs/stage3g_transfer_reliability_v1/full.json
$TASK_PY scripts/run_stage3g_reliability.py target --mode smoke --config configs/stage3g_transfer_reliability_v1/full.json
$TASK_PY scripts/check_stage3g_results.py --scope smoke --config configs/stage3g_transfer_reliability_v1/full.json
```

Smoke is the fixed two SiteIDs13013/13015, first window2022-01-01, all3 budgets/h1,h3:12 jobs and18000 rows including the three-seed mainpool/B30 shuffle. Supplied smoke jobs reuse checked caches. To cold-recompute only these12 jobs in an isolated new copy, omit that copy's `runs/stage3g_transfer_reliability_v1/smoke` directory while retaining the delivered source caches. Source choices remain frozen. Do not delete or overwrite delivered originals.

## Full and resume

```bash
$TASK_PY -m wastewater.stage3g_experiment --mode full --config configs/stage3g_transfer_reliability_v1/full.json
$TASK_PY -m wastewater.stage3g_experiment --mode resume --config configs/stage3g_transfer_reliability_v1/full.json
$TASK_PY scripts/run_stage3g_reliability.py target --mode full --config configs/stage3g_transfer_reliability_v1/full.json
$TASK_PY scripts/summarize_stage3g.py --config configs/stage3g_transfer_reliability_v1/full.json
$TASK_PY scripts/check_stage3g_results.py --scope full --statistics --config configs/stage3g_transfer_reliability_v1/full.json
```

The full frozen design is300 conditions,432000 rows for8 models×3 fixed pools and18000 shuffled-mechanism rows; full risk scoring retains216000 method/date rows. These counts describe the planned matrix; completion requires original disk receipts and full output validation. Each task persists a status,7 scientific members, hashes and failure records. FAILED/RUNNING/missing/corrupt/fingerprint mismatch cannot be counted completed. At most2 target attempts; do not hand-edit state to bypass this guard. Point parameters, scales, weights and initial bias remain frozen for60 deployment origins. Risk flags do not modify predictions.

For a genuine full cold point rerun, use another directory with no full target cache, preserving config and source caches. Deterministic output values should match within the registered tolerance, while timestamps/state execution counters may change. Pure Ridge is not repeated for random seeds. Shuffle seeds20261014/15/16 are fixed mechanism controls, not three independent facilities or prediction ensemble.

## Figures and package recheck

```bash
$TASK_PY scripts/plot_stage3g.py --help
$TASK_PY scripts/package_stage3g.py verify delivery/20261014_stage3g_v2/*.zip --extract-root /tmp/stage3g-recheck-NEW
```

The extraction path must be unused. Plotting reads actual saved result tables; exact plot command is in validation/stage3g_figures.log. PNG/PDF/SVG and source CSVs accompany each actual figure. Editable drawio is the executed workflow, not an image-generated statistical figure.

## Interpretation boundary

Main four point comparisons are weighted+bias/B30/mainpool/h1,h3 versus Persistence and matched uniform+bias, with98.75% intervals; other scores/ablation/risk/history/high-volume analyses are secondary or exploratory. All windows are reused development history. Source similarity eta0 is matched uniform sharing; shrinkage lambda0 is Persistence, not evidence of transfer. Risk training/threshold scores are group-isolated downstream cross-fit; source12→target30 and risk6→final30 size shifts remain limitations. No predeclared engineering noninferiority margin exists, so nonsignificance cannot establish history saving. A score/curve alone cannot establish engineering value, independent physical plants or live deployability.

## Known metadata limitations

The original task diagnostics.json field `site_id` is null because the inherited initial_data call did not receive a station-name argument. The task path and prediction/risk/selection rows contain the correct SiteID; the independent checker verifies those. This display-metadata omission does not change training, selected parameters or forecasts. Original frozen diagnostics are left byte-identical. TRAINING_DIAGNOSTIC_INDEX.csv supplies a separate SiteID index from the checked task name and unique actual prediction SiteID, retaining each original diagnostics SHA. It is not a silently rewritten original.

The non-frozen scripts/measure_stage3g.py captures wall time and observed process RSS for actual commands; see its original logs. It does not change scientific selection or cache fingerprints. A source cache replay is identified as CACHED_VERIFIED, not new training. Packaging-helper synthetic checks are separate from PACKAGE_CHECKS.json's actual delivered-archive checks.

## Actual isolated-directory validation

CLEAN_DIRECTORY_REPRODUCTION.json and CLEAN_DIRECTORY_SCIENTIFIC_SHA_COMPARISON.csv record the executed new-directory check. The directory began with the reproduction code/canonical inputs and exact original verified source/risk caches, with **no target smoke jobs**. All12 target conditions ran cold and produced18000 rows. All84 original scientific task members (12×7) matched SHA256 exactly; the maximum raw/normalized prediction difference was0 in this same CPU environment. Target risk produced8640 rows with the original scientific risk-table SHA. A repeated smoke entry verified12 caches with0 target recalculations; a repeated target-risk entry was CACHED_VERIFIED. This is a cold **target** reproduction with frozen source caches, not new source hyperparameter CV or a universal bitwise portability guarantee.

The correctly isolated directory passed43 synthetic software tests and the independent smoke checker. An initial unit-test invocation accidentally used the original cwd; its attempt0 log was preserved, and the tests were then actually run in the new directory. Per-task cold times totalled63.925 seconds during simultaneous root bootstrap work; the full cold-run wall time was not separately instrumented. Logs retain these limits rather than replacing them with estimated timings.


## Delivery packaging revision

The first actual pack attempt passed CRC/memberSHA/extraction but split the diagnostic members by their count, producing twelve unequally sized diagnostic ZIPs. Those original attempt archives and checks remain untouched in delivery/20261014_stage3g. Final delivery uses delivery/20261014_stage3g_v2 and deterministic byte-balanced packing, using actual first-attempt compression sizes. No scientific file, prediction or candidate score was changed or regenerated to reduce the number of packages. Both attempts are packaging work, not separate science runs. Final PACKAGE_CHECKS.json checks the actual final archives; the small synthetic PACKAGING_HELPER_CHECK remains separate.
