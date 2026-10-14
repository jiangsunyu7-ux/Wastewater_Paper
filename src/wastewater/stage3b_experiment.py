"""CPU-only Stage 3B, frozen pre-deployment selection, deterministic resumable jobs.

Run: PYTHONPATH=src python -m wastewater.stage3b_experiment --config ... --smoke
Then remove --smoke to run the complete frozen target cohort. The source cache
uses 2016--2020 validation proxies and 2016--2021 final models. No final-period
performance is read or computed by this module.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import multiprocessing
from pathlib import Path
import sys
import time
import traceback

import numpy as np
import pandas as pd
import sklearn

from .common import runtime_manifest, sha256, utc_now, write_json
from .shared_data import load_series, scale_from_history, train_samples
from .stage3a_data import compact
from .stage3b_models import (FAMILIES, MODELS, LinearModel, calibration_fold, candidate_scores,
    choose_parameters, estimate_bias, initial_data, reconstruct, residual_target,
    ridge_fit, subset, usable)

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_IDS = ["13013", "13015", "13016", "13017", "13022", "13024", "13025", "13028", "13029", "13031"]
ORIGINAL_SOURCES = ["13006", "13008", "13012"]
ORIGINAL_ORIGINS = ["2022-01-01", "2022-07-01", "2023-01-01", "2023-07-01"]


def hash_value(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def array_hash(array):
    array = np.ascontiguousarray(array)
    return hashlib.sha256(str(array.dtype).encode() + str(array.shape).encode() + array.tobytes()).hexdigest()


def validate(cfg, root=ROOT, require_freeze=True):
    if cfg["stage"] != "development" or cfg["analysis_unit"] != "station_exploratory":
        raise ValueError("Stage 3B remains station-level development")
    if cfg["qa_mode"] != "published_good_only_retrospective" or cfg["verified_real_time"]:
        raise ValueError("Unverified QA must be explicitly retrospective")
    for key, expected in (("source_ids", ORIGINAL_SOURCES), ("development_ids", ORIGINAL_IDS),
                          ("origins", ORIGINAL_ORIGINS), ("budgets", [30, 90, 180]),
                          ("horizons", [1, 3]), ("ridge_alphas", [.0001, .001, .01, .1, 1., 10.]),
                          ("lambdas", [0., .25, .5, 1.])):
        if cfg[key] != expected:
            raise ValueError(f"Unplanned change: {key}")
    if cfg["source_training_start"] != "2016-01-01" or cfg["source_training_end"] != "2021-12-31":
        raise ValueError("Final source model temporal boundary changed")
    if cfg["source_selection_train_end"] != "2020-12-31":
        raise ValueError("Validation proxy must stop before 2021")
    if cfg["evaluation_days"] != 60 or cfg["sequence_length"] != 7 or cfg.get("extra_delay_days", 0) != 0:
        raise ValueError("Changed forecast information design")
    if cfg.get("additional_origin", "2023-10-01") != "2023-10-01":
        raise ValueError("Additional window cannot be replaced")
    if cfg.get("models", list(MODELS)) != list(MODELS):
        raise ValueError("Changed model set")
    canonical = root / cfg["canonical_csv"]
    canonical_manifest = json.loads((canonical.parent / "manifest.json").read_text())
    if canonical_manifest["status"] != "completed" or canonical_manifest["outputs_sha256"][canonical.name] != sha256(canonical):
        raise ValueError("Canonical data differs from completed QA audit")
    mapping = pd.read_csv(root / cfg["mapping_csv"], dtype={"site_id": str})
    if mapping.groupby("partition_group").partition.nunique().gt(1).any():
        raise ValueError("Linked facility crosses source/target partitions")
    for role, ids in (("source", ORIGINAL_SOURCES), ("development", ORIGINAL_IDS)):
        if not set(ids).issubset(set(mapping.loc[mapping.partition.eq(role), "site_id"])):
            raise ValueError("Mapping partition mismatch")
    coverage = pd.read_csv(root / "data/provenance/reconciliation_20261009/coverage_2016_2021.csv", dtype={"site_id": str})
    selected = coverage[coverage.site_id.isin(ORIGINAL_SOURCES)]
    if len(selected) != 18 or not selected.coverage.ge(.95).all():
        raise ValueError("Predetermined source coverage standard fails")
    for date in ORIGINAL_ORIGINS + ([cfg["additional_origin"]] if cfg.get("additional_window_authorized", False) else []):
        if pd.Timestamp(date) + pd.Timedelta(days=62) > pd.Timestamp("2023-12-31"):
            raise ValueError("Final-period performance is forbidden")
    if require_freeze:
        freeze = json.loads((root / cfg.get("frozen_manifest", "configs/stage3b_20261011_v1/FREEZE.json")).read_text())
        expected = {"protocol_sha256": sha256(root / cfg["protocol"]), "canonical_sha256": sha256(canonical)}
        for key, value in expected.items():
            if freeze.get(key) != value:
                raise ValueError(f"Frozen specification differs: {key}")
        physical_config = root / cfg.get("config_file", str(Path(cfg.get("frozen_manifest", "configs/stage3b_20261011_v1/FREEZE.json")).parent / "full.json"))
        physical_hash = sha256(physical_config) if physical_config.exists() else None
        if freeze.get("config_sha256") not in (hash_value(cfg), cfg.get("_config_file_sha256"), physical_hash):
            raise ValueError("Frozen config differs")
        if not (freeze.get("frozen_before_stage3b_performance", False) or
                freeze.get("status") == "frozen_before_any_stage3b_deployment_scores"):
            raise ValueError("Pre-performance freeze declaration missing")
        if cfg.get("additional_window_authorized", False):
            history_hash = freeze.get("additional_history_audit_sha256", freeze.get("history_eligibility_sha256"))
            history_file = root / cfg.get("history_eligibility_file", f"reports/{cfg['version']}/audit/historical_window_eligibility.json")
            if not history_hash or not history_file.is_file() or sha256(history_file) != history_hash:
                raise ValueError("Additional time validation requires the verified frozen historical-use audit")


def load_cfg(config_path):
    path = ROOT / config_path
    cfg = json.loads(path.read_text())
    # File checksum is verified separately without adding self-referential config fields.
    freeze_path = ROOT / cfg.get("frozen_manifest", "configs/stage3b_20261011_v1/FREEZE.json")
    if freeze_path.exists():
        freeze = json.loads(freeze_path.read_text())
        if freeze.get("config_sha256") not in (sha256(path), hash_value(cfg)):
            raise ValueError("Frozen config file checksum changed")
    return cfg


def execution_signature(cfg, config_path):
    files = ["common.py", "shared_data.py", "stage3a_data.py", "stage3b_models.py", "stage3b_experiment.py"]
    information = dict(code_sha256={name: sha256(ROOT / "src/wastewater" / name) for name in files},
        canonical_sha256=sha256(ROOT / cfg["canonical_csv"]), mapping_sha256=sha256(ROOT / cfg["mapping_csv"]),
        config_sha256=sha256(ROOT / config_path), protocol_sha256=sha256(ROOT / cfg["protocol"]),
        accepted_stage3a_selection_sha256=sha256(ROOT / cfg.get("stage3a_selection", "runs/stage3a_20261010_v3/source/selection.json")),
        sklearn=sklearn.__version__, numpy=np.__version__, pandas=pd.__version__)
    return hash_value(information), information


def run_cached(folder, fingerprint, operation):
    """Completed caches are immutable and every member is checksum-verified."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    status_path = folder / "status.json"
    previous = None
    if status_path.exists():
        previous = json.loads(status_path.read_text())
        if previous["fingerprint"] != fingerprint:
            raise ValueError("Changed configuration/data/code; use a new version directory")
        if previous["status"] == "completed":
            for member, expected in previous["outputs_sha256"].items():
                if not (folder / member).is_file() or sha256(folder / member) != expected:
                    raise ValueError(f"Cached output modified or missing: {member}")
            return "cached"
    attempt = 1 if previous is None else previous.get("attempt", 1) + 1
    status = dict(status="running", fingerprint=fingerprint, attempt=attempt, started_utc=utc_now())
    write_json(status_path, status)
    started = time.perf_counter()
    try:
        operation(folder)
        files = [p for p in sorted(folder.rglob("*")) if p.is_file() and p != status_path and not p.name.startswith("failure_attempt_")]
        status.update(status="completed", finished_utc=utc_now(), seconds=time.perf_counter() - started,
            outputs_sha256={str(p.relative_to(folder)): sha256(p) for p in files})
        write_json(status_path, status)
        return "completed"
    except Exception as error:
        (folder / f"failure_attempt_{attempt}.txt").write_text(traceback.format_exc())
        status.update(status="failed", error=str(error), finished_utc=utc_now(), seconds=time.perf_counter() - started)
        write_json(status_path, status)
        return "failed"


def source_pool(series, cfg, horizon, end, ids):
    X, y, r, weights, diagnostics = [], [], [], [], []
    for site in ids:
        scale = scale_from_history(series[site], cfg["source_training_start"], end)
        data = train_samples(series[site], cfg["source_training_start"], end, horizon, scale)
        data = subset(data, usable(data))
        if len(data.y) < cfg["min_train_labels"]:
            raise ValueError("Insufficient source labels")
        X.append(compact(data.X)); y.append(data.y); r.append(residual_target(data))
        weights.append(np.full(len(data.y), 1 / (len(ids) * len(data.y))))
        diagnostics.append(dict(site_id=site, training_labels=len(data.y), scale_m3=scale,
            normalization_fit_start=cfg["source_training_start"], normalization_fit_end=end,
            first_train_origin=str(data.origins.min().date()), last_train_origin=str(data.origins.max().date()),
            first_train_target=str(data.targets.min().date()), last_train_target=str(data.targets.max().date()),
            weight_sum=1 / len(ids), individual_sample_weight=1 / (len(ids) * len(data.y))))
    return np.concatenate(X), np.concatenate(y), np.concatenate(r), np.concatenate(weights), diagnostics


def save_models(path, direct, residual, alphas):
    np.savez(path, alphas=np.asarray(alphas, dtype=float),
        direct_coefs=np.stack([direct[float(a)].coef_ for a in alphas]),
        direct_intercepts=np.asarray([direct[float(a)].intercept_ for a in alphas]),
        residual_coefs=np.stack([residual[float(a)].coef_ for a in alphas]),
        residual_intercepts=np.asarray([residual[float(a)].intercept_ for a in alphas]))


def read_models(path):
    with np.load(path, allow_pickle=False) as values:
        return ({float(a): LinearModel(c.copy(), float(b)) for a, c, b in zip(values["alphas"], values["direct_coefs"], values["direct_intercepts"])},
                {float(a): LinearModel(c.copy(), float(b)) for a, c, b in zip(values["alphas"], values["residual_coefs"], values["residual_intercepts"])})


def prepare_sources(cfg, signature):
    folder = ROOT / cfg["source_output"]
    def operation(out):
        series = load_series(ROOT / cfg["canonical_csv"], cfg["source_ids"])
        diagnostics = []
        groups = [("final", cfg["source_training_end"], cfg["source_ids"]),
                  ("proxy", cfg["source_selection_train_end"], cfg["source_ids"])]
        groups.extend((f"loso_{held}", "2020-12-31", [s for s in cfg["source_ids"] if s != held]) for held in cfg["source_ids"])
        for name, end, ids in groups:
            for horizon in cfg["horizons"]:
                X, y, residuals, weights, diag = source_pool(series, cfg, horizon, end, ids)
                direct, residual = {}, {}
                for alpha in cfg["ridge_alphas"]:
                    direct[float(alpha)] = ridge_fit(X, y, alpha, weights)
                    residual[float(alpha)] = ridge_fit(X, residuals, alpha, weights)
                save_models(out / f"{name}_H{horizon}.npz", direct, residual, cfg["ridge_alphas"])
                diagnostics.append(dict(group=name, horizon=horizon, source_ids=ids, fit_end=end, sites=diag,
                    total_training_labels=len(y), nominal_parameters=7, features=6,
                    weight_sum=float(weights.sum()), objective="sum(w*(y-Xb-intercept)^2)+alpha*sum(b^2)",
                    intercept_penalized=False, training_X_sha256=array_hash(X), label_sha256=array_hash(y),
                    residual_label_sha256=array_hash(residuals), weights_sha256=array_hash(weights)))
        all_scores, direct_scores, folds, fallback = [], [], [], {}
        for budget in cfg["budgets"]:
            for horizon in cfg["horizons"]:
                relevant, direct_relevant = [], []
                for held in cfg["source_ids"]:
                    _, source_residual = read_models(out / f"loso_{held}_H{horizon}.npz")
                    for date in cfg["source_pseudo_origins"]:
                        train, val, diag = calibration_fold(series[held], date, budget, horizon, cfg, pseudo=True)
                        if not diag["valid"]:
                            raise ValueError(f"Invalid predeclared source fallback fold {held}/{date}/B{budget}/H{horizon}")
                        if held in [s for s in cfg["source_ids"] if s != held] or pd.Timestamp("2020-12-31") >= val.origins.min():
                            raise AssertionError("LOSO facility/time isolation failed")
                        fold_id = f"{held}_{date}_B{budget}_H{horizon}"
                        folds.append(dict(diag, fold_id=fold_id, held_out_source=held,
                            shared_fit_sites=[s for s in cfg["source_ids"] if s != held], shared_fit_end="2020-12-31"))
                        scores = candidate_scores(train, val, source_residual, cfg)
                        for score in scores:
                            score.update(fold_id=fold_id, held_out_source=held, budget=budget, horizon=horizon,
                                         normalization_fit_end=diag["normalization_fit_end"])
                        relevant.extend(scores); all_scores.extend(scores)
                        for alpha in cfg["ridge_alphas"]:
                            model = ridge_fit(compact(train.X), train.y, alpha)
                            score = dict(fold_id=fold_id, budget=budget, horizon=horizon, held_out_source=held,
                                alpha=float(alpha), validation_mae=float(np.mean(np.abs(model.predict(compact(val.X)) - val.y))))
                            direct_relevant.append(score); direct_scores.append(score)
                direct_frame = pd.DataFrame(direct_relevant).groupby("alpha", as_index=False).validation_mae.mean()
                chosen = direct_frame.sort_values(["validation_mae", "alpha"], kind="stable").iloc[0]
                fallback[f"B{budget}_H{horizon}"] = dict(parameters=choose_parameters(relevant),
                    direct_alpha=float(chosen.alpha), direct_validation_mae=float(chosen.validation_mae),
                    source_assisted=True, folds=6, fitting_source_end="2020-12-31", validation_end="2021-07-17" if horizon == 3 else "2021-07-15")
        # Direct compact alpha is the accepted Stage 3A choice, not selected anew here.
        selection_file = ROOT / cfg.get("stage3a_selection", "runs/stage3a_20261010_v3/source/selection.json")
        archive = json.loads(selection_file.read_text())
        direct_shared = {str(h): float(archive["settings"][str(h)]["shared_lags_alpha"]) for h in cfg["horizons"]}
        if direct_shared != {"1": .0001, "3": .01}:
            raise ValueError("Accepted Stage 3A direct comparator parameters differ")
        for horizon in cfg["horizons"]:
            key = f"B30_H{horizon}"
            if fallback[key]["direct_alpha"] != archive["fallback_settings"][key]["ridge_alphas"]["lags"]:
                raise AssertionError("Recomputed direct source-assisted alpha differs from Stage 3A")
        write_json(out / "selection.json", dict(signature=signature, fallback_settings=fallback,
            direct_shared_alphas=direct_shared, accepted_stage3a_selection_sha256=sha256(selection_file),
            hyperparameter_information="LOSO source auxiliary validation for insufficient target budgets; prefix target validation otherwise",
            tuning_loss="normalized MAE", training_loss="weighted MSE", source_model_diagnostics=diagnostics))
        write_json(out / "pseudo_validation_folds.json", folds)
        pd.DataFrame(all_scores).to_csv(out / "residual_fallback_grid.csv", index=False)
        pd.DataFrame(direct_scores).to_csv(out / "direct_fallback_grid.csv", index=False)
        write_json(out / "source_diagnostics.json", diagnostics)
    state = run_cached(folder, signature, operation)
    if state == "failed":
        raise RuntimeError(f"Source cache failed: {folder / 'status.json'}")
    return state


def select_for_target(series, cfg, date, budget, horizon, source_folder):
    train, val, fold = calibration_fold(series, date, budget, horizon, cfg)
    source_selection = json.loads((source_folder / "selection.json").read_text())
    if fold["valid"]:
        _, shared_residual = read_models(source_folder / f"proxy_H{horizon}.npz")
        if pd.Timestamp("2020-12-31") >= val.origins.min():
            raise AssertionError("Source CV proxy includes future validation information")
        grid = candidate_scores(train, val, shared_residual, cfg)
        parameters = choose_parameters(grid)
        direct_scores = []
        for alpha in cfg["ridge_alphas"]:
            model = ridge_fit(compact(train.X), train.y, alpha)
            direct_scores.append(dict(alpha=float(alpha), validation_mae=float(np.mean(np.abs(model.predict(compact(val.X)) - val.y)))))
        chosen = min(direct_scores, key=lambda r: (r["validation_mae"], r["alpha"]))
        direct_alpha, direct_loss = chosen["alpha"], chosen["validation_mae"]
        fold.update(shared_proxy_fit_end="2020-12-31", source_assisted=False,
                    choice_source="budget_internal_chronological_validation")
    else:
        key = f"B{budget}_H{horizon}"
        fallback = source_selection["fallback_settings"][key]
        parameters = fallback["parameters"]
        direct_alpha, direct_loss = fallback["direct_alpha"], fallback["direct_validation_mae"]
        grid, direct_scores = [], []
        fold.update(source_assisted=True, choice_source="LOSO_source_simulated_same_budget_validation",
            fallback_key=key, fallback_reason="insufficient internal fitting/validation labels",
            fallback_validation_labels="see source/pseudo_validation_folds.json: six folds",
            fallback_source_fit_end="2020-12-31", fallback_validation_end=fallback["validation_end"])
    return dict(fold=fold, parameters=parameters, direct_alpha=float(direct_alpha),
        direct_validation_mae=float(direct_loss), direct_validation=direct_scores,
        direct_shared_alpha=source_selection["direct_shared_alphas"][str(horizon)],
        residual_validation=grid, selection_uses_deployment_labels=False)


def prediction_frame(test, diag, outputs, choices):
    rows = []
    available = test.X[:, :, 1].sum(axis=1) > 0
    for model in MODELS:
        values = outputs[model]
        for index, (origin, target) in enumerate(zip(test.origins, test.targets)):
            prediction = float(values[index])
            # Lambda zero is the baseline EXACTLY, even if a baseline observed lag -7
            # falls outside the six feature columns. Common-date evaluation is separate.
            selected_lambda = choices.get(model, {}).get("shrinkage")
            if model not in ("persistence", "weekly_persistence") and selected_lambda != 0 and not available[index]:
                prediction = np.nan
            rows.append(dict(site_id=diag["site_id"], episode=diag["episode"], budget=diag["budget"],
                horizon=diag["horizon"], origin=str(origin.date()), target_date=str(target.date()), model=model, seed=0,
                truth_m3=float(test.y[index] * test.scale), prediction_m3=prediction,
                prediction_nonnegative_m3=max(0., prediction) if np.isfinite(prediction) else np.nan,
                budget_start=diag["budget_start"], fit_end=diag["fit_end"], last_train_target=diag["last_train_target"],
                latest_input_date=str(origin.date()), scale_m3=test.scale, training_labels=diag["training_labels"],
                high_threshold_m3=diag["high_threshold_m3"], threshold_observations=diag["threshold_observations"],
                threshold_start=diag["threshold_start"], threshold_end=diag["threshold_end"],
                alpha=choices.get(model, {}).get("alpha"), shrinkage=selected_lambda,
                bias_m3=choices.get(model, {}).get("bias_m3", 0.),
                analysis_unit="station_exploratory", qa_mode="published_good_only_retrospective",
                window_class="additional_time_validation" if diag["episode"] == "2023-10-01" else "reused_development"))
    return pd.DataFrame(rows)


def target_worker(config_path, signature, site, date, budget, horizon, smoke=False):
    cfg = load_cfg(config_path)
    output = ROOT / (cfg.get("smoke_output", f"runs/{cfg['version']}/smoke") if smoke else cfg["output"])
    task = f"{site}_{date}_B{budget}_H{horizon}"
    folder = output / "jobs" / task
    fingerprint = hash_value(dict(signature=signature, task=task, operation="deterministic_11_policy_point_prediction"))
    source_folder = ROOT / cfg["source_output"]
    def operation(job):
        series = load_series(ROOT / cfg["canonical_csv"], [site])[site]
        train, deployment, diag = initial_data(series, date, budget, horizon, cfg)
        diag["site_id"] = site
        diag.update(training_X_sha256=array_hash(train.X), training_y_sha256=array_hash(train.y),
                    training_residual_sha256=array_hash(residual_target(train)), evaluation_X_sha256=array_hash(deployment.X))
        selection = select_for_target(series, cfg, date, budget, horizon, source_folder)
        # Serialize selections before computing any forecast-period error or reading truth for evaluation.
        write_json(job / "selection.json", selection)
        pd.DataFrame(selection["residual_validation"]).to_csv(job / "validation_grid.csv", index=False)
        pd.DataFrame(selection["direct_validation"]).to_csv(job / "direct_validation_grid.csv", index=False)
        source_direct, source_residual = read_models(source_folder / f"final_H{horizon}.npz")
        local_direct = ridge_fit(compact(train.X), train.y, selection["direct_alpha"])
        shared_direct = source_direct[float(selection["direct_shared_alpha"])]
        direct_bias = float(np.mean(train.y - shared_direct.predict(compact(train.X))))
        outputs = dict(persistence=deployment.persistence.copy(), weekly_persistence=deployment.weekly.copy(),
            local_ridge_lags_tuned=local_direct.predict(compact(deployment.X)) * deployment.scale,
            shared_ridge_lags=shared_direct.predict(compact(deployment.X)) * deployment.scale,
            shared_ridge_lags_bias=(shared_direct.predict(compact(deployment.X)) + direct_bias) * deployment.scale)
        parameters = dict(local_ridge_lags_tuned=dict(alpha=selection["direct_alpha"], bias_m3=0.),
            shared_ridge_lags=dict(alpha=selection["direct_shared_alpha"], bias_m3=0.),
            shared_ridge_lags_bias=dict(alpha=selection["direct_shared_alpha"], bias_m3=direct_bias * deployment.scale))
        saved_arrays = dict(local_direct_coef=local_direct.coef_, local_direct_intercept=local_direct.intercept_,
            shared_direct_coef=shared_direct.coef_, shared_direct_intercept=shared_direct.intercept_, direct_bias_normalized=direct_bias)
        local_models = {}
        for name, decision in selection["parameters"].items():
            alpha, shrinkage = decision["alpha"], decision["shrinkage"]
            if name.startswith("local_"):
                if alpha not in local_models:
                    local_models[alpha] = ridge_fit(compact(train.X), residual_target(train), alpha)
                model, bias = local_models[alpha], 0.
            else:
                model = source_residual[float(alpha)]
                bias = estimate_bias(model, train) if name.startswith("shared_residual_ridge_bias_") else 0.
            outputs[name] = reconstruct(deployment.persistence, model.predict(compact(deployment.X)), bias, shrinkage, deployment.scale)
            parameters[name] = dict(decision, bias_normalized=bias, bias_m3=bias * deployment.scale,
                source_assisted=selection["fold"]["source_assisted"],
                actual_training_labels=len(train.y) if name.startswith("local_") else "see source_diagnostics.json",
                local_bias_calibration_labels=len(train.y) if name.startswith("shared_residual_ridge_bias_") else 0)
            saved_arrays[name + "_coef"] = model.coef_
            saved_arrays[name + "_intercept"] = model.intercept_
            saved_arrays[name + "_bias"] = bias
        write_json(job / "parameters.json", parameters)
        np.savez(job / "ridge_parameters.npz", **saved_arrays)
        frame = prediction_frame(deployment, diag, outputs, parameters)
        frame.to_csv(job / "predictions.csv", index=False)
        write_json(job / "diagnostics.json", dict(diag, validation=selection["fold"], parameters=parameters,
            local_weights_sum=1., local_individual_weight=1 / len(train.y),
            source_final_fit_end="2021-12-31", shared_validation_proxy_fit_end="2020-12-31",
            point_prediction_only=True, source_pool_fixed=True, device="cpu", nominal_parameters=7))
    state = run_cached(folder, fingerprint, operation)
    return dict(task=task, site_id=site, episode=date, budget=budget, horizon=horizon, status=state,
                folder=str(folder.relative_to(ROOT)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/stage3b_20261011_v1/full.json")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--max-jobs", type=int)
    args = parser.parse_args()
    cfg = load_cfg(args.config)
    # Accept both canonical-JSON and physical-file hashes in freeze, but verify exact physical bytes first.
    freeze_path = ROOT / cfg.get("frozen_manifest", "configs/stage3b_20261011_v1/FREEZE.json")
    freeze = json.loads(freeze_path.read_text())
    if freeze.get("config_sha256") != sha256(ROOT / args.config):
        raise ValueError("Actual frozen config file checksum does not match")
    checked_cfg = dict(cfg, _config_file_sha256=sha256(ROOT / args.config))
    validate(checked_cfg)
    signature, provenance = execution_signature(cfg, args.config)
    output = ROOT / (cfg.get("smoke_output", f"runs/{cfg['version']}/smoke") if args.smoke else cfg["output"])
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text())["signature"] != signature:
        raise ValueError("Changed frozen experiment; use a new version")
    started = time.perf_counter()
    source_state = prepare_sources(cfg, signature)
    if args.source_only:
        print(json.dumps(dict(source_status=source_state, signature=signature)), flush=True)
        return
    if args.smoke:
        all_tasks = [(args.config, signature, site, cfg["origins"][0], b, h, True)
                     for site in ["13013", "13015"] for b in cfg["budgets"] for h in cfg["horizons"]]
    else:
        origins = cfg["origins"] + ([cfg["additional_origin"]] if cfg.get("additional_window_authorized", False) else [])
        all_tasks = [(args.config, signature, site, date, b, h, False) for date in origins
                     for site in cfg["development_ids"] for b in cfg["budgets"] for h in cfg["horizons"]]
    tasks = all_tasks[:args.max_jobs] if args.max_jobs else all_tasks
    prior_started = json.loads(manifest_path.read_text()).get("first_started_utc") if manifest_path.exists() else None
    manifest = dict(status="running", signature=signature, provenance=provenance, config=cfg,
        first_started_utc=prior_started or utc_now(), last_started_utc=utc_now(), runtime=runtime_manifest(ROOT),
        execution_command=" ".join(sys.argv), expected_conditions=len(all_tasks), device="cpu",
        deterministic_new_models=True, physical_facility_independence_verified=False, online_QA_availability_verified=False)
    write_json(manifest_path, manifest)
    results = []
    phases = [tasks] if args.smoke else [[task for task in tasks if task[3] != "2023-10-01"],
                                        [task for task in tasks if task[3] == "2023-10-01"]]
    for phase in phases:
        if not phase:
            continue
        if phase[0][3] == "2023-10-01" and any(result["status"] == "failed" for result in results):
            # Preserve failed original tasks; additional time validation awaits their correction.
            print("Additional phase not executed because an original-window task failed", flush=True)
            break
        if args.workers == 1:
            for task in phase:
                results.append(target_worker(*task))
                print(f"condition {len(results)}/{len(tasks)} {results[-1]['task']} {results[-1]['status']}", flush=True)
        else:
            with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as executor:
                futures = {executor.submit(target_worker, *task): task for task in phase}
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as error:
                        task = futures[future]
                        results.append(dict(task=f"{task[2]}_{task[3]}_B{task[4]}_H{task[5]}", status="failed", error=str(error)))
                    print(f"condition {len(results)}/{len(tasks)} {results[-1]['task']} {results[-1]['status']}", flush=True)
    write_json(output / "completion_this_call.json", results)
    statuses = []
    for task in all_tasks:
        key = f"{task[2]}_{task[3]}_B{task[4]}_H{task[5]}"
        path = output / "jobs" / key / "status.json"
        if path.exists():
            status = json.loads(path.read_text())
            statuses.append(dict(task=key, **status))
        else:
            statuses.append(dict(task=key, status="not_executed"))
    completed = sum(s["status"] == "completed" for s in statuses)
    failed = sum(s["status"] == "failed" for s in statuses)
    manifest.update(status="completed" if completed == len(all_tasks) else "partial", completed_conditions=completed,
        failed_conditions=failed, not_executed_conditions=len(all_tasks)-completed-failed,
        counts_this_call={key: sum(r["status"] == key for r in results) for key in ["completed", "cached", "failed"]},
        source_state_this_call=source_state, finished_utc=utc_now(), seconds_this_call=time.perf_counter()-started,
        source_cache_status_sha256=sha256(ROOT / cfg["source_output"] / "status.json"))
    write_json(output / "completion.json", statuses)
    write_json(manifest_path, manifest)
    if not args.smoke:
        prediction_paths = [output / "jobs" / s["task"] / "predictions.csv" for s in statuses if s["status"] == "completed"]
        if prediction_paths:
            predictions = pd.concat([pd.read_csv(p, dtype={"site_id": str}) for p in prediction_paths], ignore_index=True)
            report = ROOT / cfg.get("report_output", f"reports/{cfg['version']}/results")
            report.mkdir(parents=True, exist_ok=True)
            predictions.to_csv(report / "predictions_all.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    print(json.dumps({k: manifest[k] for k in ["status", "completed_conditions", "expected_conditions", "failed_conditions", "counts_this_call", "seconds_this_call"]}, indent=2), flush=True)
    if failed or any(r["status"] == "failed" for r in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
