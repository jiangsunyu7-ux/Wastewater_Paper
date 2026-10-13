# Stage 3A implementation and reproducibility notes

The protocol remains immutable after launch; this implementation note discloses preflight corrections rather than rewriting registration history. Initial source-only preflight versions `runs/stage3a_20261010` and `_v2` remain on disk. No target deployment scores or final-period scores were used in these corrections.

1. Fold metadata initially contained a NumPy boolean. It was converted to a built-in boolean for JSON serialization; the new test serializes real fold metadata. This changes no scientific rule.
2. The current old and new GRU trainers match each other bitwise on an actual multi-batch source-data check and on deterministic resume fixtures. Archived Stage 2 source weights nevertheless differ slightly across executions (observed normalized prediction maximum 1.705e−5). The root cause is unresolved. Endpoint checks therefore record both parameter and normalized-prediction differences and require atol=1e−4, rtol=1e−5; they do not falsely claim archive bitwise equivalence. Final frozen-head diagnostics load the **actual archived Stage 2 source40 weights**, so this backbone is preserved exactly. Within-current-run resume still requires exact equivalence.
3. Accepted scientific code/config version is `stage3a_20261010_v3`. Each condition persists selections before deployment prediction scoring. The 12-condition one-seed smoke experiment selects hyperparameters using all three original seeds where applicable; smoke outputs are excluded from the 240-condition primary report. All original inputs match Stage 2 hashes.

CPU commands (from project ROOT):

```bash
bash scripts/refresh_stage2_environment.sh
export PYTHONPATH="$PWD/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
.venv-stage2/bin/python -m unittest discover -s tests -v
.venv-stage2/bin/python -m wastewater.stage3a_experiment --smoke --workers 4
.venv-stage2/bin/python -m wastewater.stage3a_experiment --workers 4
.venv-stage2/bin/python scripts/summarize_stage3a.py
.venv-stage2/bin/python scripts/plot_stage3a.py
```

Repeated scientific commands verify completed top-level job file hashes and reuse completed caches; incomplete trajectories resume from atomic last checkpoints. Changed code/config/data/initial weights are rejected by fingerprints and require a new version. Failures remain as status/attempt logs. CPU workers use separate processes to isolate Torch RNG; using threads for independently seeded training would be unsafe. Models train on CPU; no paid resources or GPU are needed for this scale.

For a clean extracted ROOT, import the three original Stage 2 archives as described in the Stage 3A delivery instructions. The Stage 2 Code archive is retained intact but **its older document payload is not overlaid on the new Stage 3A code package**. Stage 2 Runs and Reports retain their original project-relative locations and are necessary for archive endpoint verification and original-comparator reporting. No million-row original CSV is required to replay derived-data experiments. Rebuilding original QA requires user-provided original packages and a new output directory.

Completing these commands does not authorize Stage 3B. Residual modeling, source expansion, prediction intervals, final testing, manuscript rewriting and software deployment remain unexecuted proposals.
