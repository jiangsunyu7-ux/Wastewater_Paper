#!/usr/bin/env python3
"""Independent Stage3G disk, calendar, algebra and isolation audit.

No Stage3G scientific implementation is imported. This rechecks saved real
outputs against canonical data and explicit normal equations; it does not
select models or inspect final/protected performance.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VERSION = "stage3g_transfer_reliability_v1"
ATOL = 1e-10


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def assert_near(actual, expected, context, atol=ATOL):
    if not np.allclose(actual, expected, atol=atol, rtol=ATOL, equal_nan=True):
        raise AssertionError(context)


def legal_persistence(series, origins, left):
    result = np.full(len(origins), np.nan)
    for lag in range(8):
        dates = origins - pd.Timedelta(days=lag)
        values = series.reindex(dates).to_numpy(float)
        values[dates < pd.Timestamp(left)] = np.nan
        use = ~np.isfinite(result) & np.isfinite(values)
        result[use] = values[use]
    return result


def independent_arrays(series, origins, horizon, left, scale):
    origins = pd.DatetimeIndex(origins)
    columns = []
    masks = []
    for lag in (0, 1, 6):
        dates = origins-pd.Timedelta(days=lag)
        values = series.reindex(dates).to_numpy(float)
        values[dates < pd.Timestamp(left)] = np.nan
        good = np.isfinite(values)
        columns.append(np.where(good, values/scale, 1.).astype(np.float32).astype(float))
        masks.append(good.astype(float))
    x = np.column_stack(columns+masks)
    p = legal_persistence(series, origins, left)
    truth = series.reindex(origins+pd.Timedelta(days=horizon)).to_numpy(float)
    # P can fall back seven days, while the actual tensor contains lag0--6.
    # Require at least one legal input in that seven-day tensor separately.
    any_input = legal_any_input(series, origins, left)
    eligible = np.isfinite(truth) & np.isfinite(p) & any_input
    return x, truth/scale, p, eligible


def legal_any_input(series, origins, left):
    available = np.zeros(len(origins), dtype=bool)
    for lag in range(7):
        dates = origins-pd.Timedelta(days=lag)
        values = series.reindex(dates).to_numpy(float)
        available |= np.isfinite(values) & (dates >= pd.Timestamp(left))
    return available


def load_canonical(cfg):
    data = pd.read_csv(ROOT/cfg["canonical_csv"], dtype={"site_id": str})
    if data.date.max() > "2023-12-31":
        raise AssertionError("Final-period rows in development canonical")
    if data.duplicated(["site_id", "date"]).any():
        raise AssertionError("Duplicate canonical calendar key")
    ids = list(dict.fromkeys(cfg["development_ids"]+[s for p in cfg["pools"] for s in p["site_ids"]]))
    series = {}
    calendar = pd.date_range("2016-01-01", "2023-12-31")
    for site in ids:
        rows = data[data.site_id.eq(site)]
        values = rows.assign(date=pd.to_datetime(rows.date)).set_index("date").observed_input_m3
        series[site] = values.reindex(calendar)
    return series


def moments(series, horizon):
    left, right = pd.Timestamp("2016-01-01"), pd.Timestamp("2021-12-31")
    positive = series.loc[left:right].dropna()
    positive = positive[positive > 0]
    scale = float(positive.median()) if len(positive) else 1.
    origins = pd.date_range(left, right-pd.Timedelta(days=horizon))
    x, y, p, good = independent_arrays(series, origins, horizon, left, scale)
    augmented = np.column_stack([x[good], np.ones(good.sum())])
    residual = y[good]-p[good]/scale
    return augmented.T@augmented/good.sum(), augmented.T@residual/good.sum()


def check_source_roles(cfg):
    counts = {"source_global_folds": 0, "strict_outer_roles": 0, "strict_inner_folds": 0}
    for pool in cfg["pools"]:
        folder = ROOT/cfg["source_output"]/pool["pool_id"]
        state = json.loads((folder/"status.json").read_text())
        if state["status"] != "COMPLETED":
            raise AssertionError("Source disk state incomplete")
        for filename, expected in state["outputs_sha256"].items():
            if sha(folder/filename) != expected:
                raise AssertionError("Source member SHA mismatch")
        for row in json.loads((folder/"source_cv_folds.json").read_text()):
            if set(row["excluded_site_ids"]) & set(row["base_fit_site_ids"]):
                raise AssertionError("Global selection held group leaked")
            if row["held_site_id"] not in row["excluded_site_ids"]:
                raise AssertionError("Missing held selection site")
            if row["held_group"] not in row["excluded_groups"]:
                raise AssertionError("Missing held selection associated group")
            if set(row["descriptor_fit_site_ids"]) != set(row["base_fit_site_ids"]):
                raise AssertionError("Descriptor training-side set differs")
            if row["base_fit_end"] > "2020-12-31":
                raise AssertionError("Selection source label boundary")
            counts["source_global_folds"] += 1
        roles = json.loads((folder/"strict_reliability_roles.json").read_text())
        if len(roles) != 5:
            raise AssertionError("Strict risk outer fold count")
        for outer in roles:
            base = set(outer["base_fit_site_ids"])
            role_sets = [set(ids) for ids in outer["role_site_ids"].values()]
            all_roles = [base]+role_sets
            for i, left in enumerate(all_roles):
                if any(left & right for right in all_roles[i+1:]):
                    raise AssertionError("Indirect source-role leakage")
            group_roles = [set(outer["base_fit_groups"])]+[set(groups) for groups in outer["role_groups"].values()]
            for i, left in enumerate(group_roles):
                if any(left & right for right in group_roles[i+1:]):
                    raise AssertionError("Associated group crossed source roles")
            if set.union(*all_roles) != set(pool["site_ids"]):
                raise AssertionError("Incomplete strict source role partition")
            if set(outer["upstream_selection_site_ids"]) != base or set(outer["descriptor_standardization_site_ids"]) != base:
                raise AssertionError("Outer held data entered upstream selection/standardization")
            for inner in outer["inner_selection_registry"]:
                if not set(inner["base_fit_site_ids"]).issubset(base):
                    raise AssertionError("Inner base data escaped outer base role")
                if not set(inner["excluded_site_ids"]).issubset(base):
                    raise AssertionError("Inner selection data escaped outer base role")
                if set(inner["base_fit_site_ids"]) & set(inner["excluded_site_ids"]):
                    raise AssertionError("Inner held group leakage")
                if inner["last_train_target"] > inner["fit_end"] or inner["base_fit_end"] > "2020-12-31":
                    raise AssertionError("Source inner chronology")
                counts["strict_inner_folds"] += 1
            counts["strict_outer_roles"] += 1
    return counts


def check_jobs(cfg, scope, series):
    run = ROOT/(cfg.get("smoke_output", f"runs/{VERSION}/smoke") if scope == "smoke" else cfg["output"])
    tasks = json.loads((run/"EXPECTED_TASKS.json").read_text())["tasks"]
    summary = {"expected_tasks": len(tasks), "disk_completed_tasks": 0, "prediction_rows_checked": 0,
               "source_weight_sets_checked": 0, "shuffled_multisets_checked": 0,
               "point_formula_sets_checked": 0, "normal_equation_models_checked": 0}
    score_rows = []
    gram_cache = {}
    for number, task in enumerate(tasks):
        folder = run/"jobs"/task
        state = json.loads((folder/"status.json").read_text())
        if state["status"] != "COMPLETED" or not state.get("write_verified"):
            raise AssertionError(f"Incomplete disk task: {task}")
        for filename, expected in state["outputs_sha256"].items():
            if sha(folder/filename) != expected:
                raise AssertionError(f"Output member SHA: {task}/{filename}")
        frame = pd.read_csv(folder/"predictions.csv", dtype={"site_id": str})
        if len(frame) != state["expected_prediction_rows"] or frame.duplicated(["pool_id", "model", "seed", "origin"]).any():
            raise AssertionError(f"Task calendar/cardinality: {task}")
        if (pd.to_datetime(frame.target_date)-pd.to_datetime(frame.origin)).dt.days.ne(frame.horizon).any():
            raise AssertionError("h=3 target alignment")
        if (pd.to_datetime(frame.latest_input_date)>pd.to_datetime(frame.origin)).any() or (pd.to_datetime(frame.last_train_target)>pd.to_datetime(frame.fit_end)).any():
            raise AssertionError("Forecast input or fit-label boundary")
        first = frame.iloc[0]; s = series[str(first.site_id)]
        left, end = pd.Timestamp(first.budget_start), pd.Timestamp(first.fit_end)
        if (end-left).days+1 != int(first.budget):
            raise AssertionError("Initial calendar budget definition")
        positive = s.loc[left:end].dropna(); positive = positive[positive > 0]
        scale = float(positive.median()) if len(positive) else 1.
        assert_near(frame.scale_m3, scale, "Initial scale")
        origins = pd.date_range(first.episode, periods=60)
        x, normalized_truth, baseline, _ = independent_arrays(s, origins, int(first.horizon), left, scale)
        fit_origins = pd.date_range(left, end-pd.Timedelta(days=int(first.horizon)))
        _, _, _, fit_good = independent_arrays(s, fit_origins, int(first.horizon), left, scale)
        if not frame.training_labels.eq(int(fit_good.sum())).all():
            raise AssertionError("Actual training-label count")
        parameters = np.load(folder/"model_parameters.npz")
        for (pool, model, seed), rows in frame.groupby(["pool_id", "model", "seed"], sort=False):
            rows = rows.sort_values("origin")
            if rows.origin.tolist() != origins.strftime("%Y-%m-%d").tolist():
                raise AssertionError("Model omitted planned origins")
            assert_near(rows.truth_m3, normalized_truth*scale, "Truth canonical alignment")
            assert_near(rows.persistence_m3, baseline, "Persistence legal current-or-seven-lag")
            assert_near(rows.prediction_nonnegative_m3, np.maximum(0., rows.prediction_m3), "Uniform clipping")
            if model == "persistence":
                assert_near(rows.prediction_m3, baseline, "Actual Persistence centre")
            elif model == "weekly_persistence":
                week_dates = origins+pd.Timedelta(days=int(first.horizon)-7)
                week = s.reindex(week_dates).to_numpy(float); week[week_dates < left] = np.nan
                assert_near(rows.prediction_m3, week, "Weekly target-minus-seven alignment")
            elif float(rows.shrinkage.iloc[0]) == 0:
                if not np.array_equal(rows.prediction_m3.to_numpy(), baseline, equal_nan=True):
                    raise AssertionError("lambda0 must exactly return Persistence")
            elif "shuffled" not in model:
                key = pool+"__"+model
                z = x@parameters[key+"__coef"]+float(parameters[key+"__intercept"])
                predicted = z*scale if "local_direct" in model else baseline+float(rows.shrinkage.iloc[0])*(z+float(rows.bias_m3.iloc[0])/scale)*scale
                predicted[~legal_any_input(s, origins, left)] = np.nan
                assert_near(rows.prediction_m3/scale, predicted/scale, "Saved model reconstruction")
                summary["point_formula_sets_checked"] += 1
            eligible = np.isfinite(rows.truth_m3) & np.isfinite(rows.prediction_m3)
            losses = rows.loc[eligible].prediction_m3-rows.loc[eligible].truth_m3
            score_rows.append(dict(site_id=str(first.site_id), episode=first.episode, budget=int(first.budget), horizon=int(first.horizon), pool_id=pool, model=model, seed=int(seed), n=int(eligible.sum()), mae=float(losses.abs().mean()) if eligible.any() else None, rmse=float(np.sqrt(np.mean(losses**2))) if eligible.any() else None))
        weights = pd.read_csv(folder/"source_weights.csv", dtype={"source_site_id": str})
        weights["seed"] = weights.get("seed", pd.Series(0, index=weights.index)).fillna(0).astype(int)
        for (pool, model, seed), rows in weights.groupby(["pool_id", "model", "seed"], sort=False):
            w = rows.weight.to_numpy(float)
            assert_near(w.sum(), 1., "Source weights sum one", atol=1e-12)
            assert_near(rows.effective_source_count, 1/np.sum(w*w), "Effective source count")
            assert_near(rows.maximum_source_weight, np.max(w), "Maximum source weight")
            if rows.eta.eq(0).all():
                assert_near(w, np.full(len(w), 1/len(w)), "eta0 uniform sources", atol=0.)
            if "shuffled" in model:
                matched = weights[(weights.pool_id == pool)&(weights.model == "similarity_residual_ridge_bias_selected")]
                if not np.array_equal(np.sort(w), np.sort(matched.weight.to_numpy(float))):
                    raise AssertionError("Shuffled source-weight values changed")
                summary["shuffled_multisets_checked"] += 1
            # Independent row moments for the two first-window B30 smoke sites,
            # both horizons, main uniform/weighted families only.
            if str(first.site_id) in cfg["smoke_ids"] and first.episode == cfg["evaluation_origins"][0] and int(first.budget) == 30 and pool == cfg["primary_pool_id"] and "shuffled" not in model:
                combined_gram = np.zeros((7, 7)); combined_rhs = np.zeros(7)
                for row in rows.itertuples():
                    key = (row.source_site_id, int(first.horizon))
                    if key not in gram_cache: gram_cache[key] = moments(series[row.source_site_id], int(first.horizon))
                    gram, rhs = gram_cache[key]; combined_gram += row.weight*gram; combined_rhs += row.weight*rhs
                alpha = float(frame[(frame.pool_id == pool)&(frame.model == model)].alpha.iloc[0])
                solved = np.linalg.solve(combined_gram+np.diag([alpha]*6+[0.]), combined_rhs)
                assert_near(parameters[pool+"__"+model+"__coef"], solved[:6], "Independent weighted Ridge coefficients")
                assert_near(float(parameters[pool+"__"+model+"__intercept"]), solved[6], "Unpenalized intercept")
                summary["normal_equation_models_checked"] += 1
            summary["source_weight_sets_checked"] += 1
        summary["disk_completed_tasks"] += 1
        summary["prediction_rows_checked"] += len(frame)
        if (number+1)%25 == 0:
            print(f"audit {number+1}/{len(tasks)} real task files", flush=True)
    return summary, pd.DataFrame(score_rows)


def check_statistics(cfg, own_metrics):
    """Derive four main comparison estimates and block draws from saved rows."""
    report = ROOT/cfg["report_output"]
    old = pd.read_csv(report/"metrics_by_station_window.csv", dtype={"site_id": str})
    old = old[old.constraint.eq("raw")]
    own = own_metrics[~own_metrics.model.str.contains("shuffled")]
    joined = own.merge(old, on=["site_id", "episode", "budget", "horizon", "pool_id", "model"], validate="one_to_one")
    if len(joined) != len(own):
        raise AssertionError("Reported own-date metrics missing registered conditions")
    if not np.array_equal(joined.n.to_numpy(), joined.n_dates.to_numpy()):
        raise AssertionError("Reported metric date denominator")
    assert_near(joined.mae, joined.mae_m3, "Independent available-date MAE", atol=1e-8)
    assert_near(joined.rmse, joined.rmse_m3, "Independent available-date RMSE", atol=1e-8)
    forecast = pd.read_csv(ROOT/cfg["output"]/"predictions_all.csv.gz", dtype={"site_id": str})
    forecast = forecast[forecast.pool_id.eq(cfg["primary_pool_id"]) & forecast.budget.eq(30)]
    ci = pd.read_csv(report/"paired_block_intervals.csv")
    ci = ci[ci.co_primary.eq(True)]
    if len(ci) != 12:
        raise AssertionError("Four primary comparisons times three blocks expected")
    candidates = ["similarity_residual_ridge_bias_selected", "persistence", "uniform_residual_ridge_bias_selected"]
    sites, windows = cfg["development_ids"], cfg["evaluation_origins"]
    checked = []
    for horizon in cfg["horizons"]:
        errors = np.full((len(sites), 60*len(windows), 3), np.nan)
        for model_index, model in enumerate(candidates):
            q = forecast[forecast.horizon.eq(horizon)&forecast.model.eq(model)]
            site_index = q.site_id.map({s:i for i,s in enumerate(sites)}).to_numpy()
            window_index = q.episode.map({s:i for i,s in enumerate(windows)}).to_numpy()
            day = (pd.to_datetime(q.origin)-pd.to_datetime(q.episode)).dt.days.to_numpy()
            errors[site_index, window_index*60+day, model_index] = np.abs(q.prediction_m3-q.truth_m3)
        paired = []
        for ref in (1, 2):
            valid = np.isfinite(errors[:, :, 0]) & np.isfinite(errors[:, :, ref])
            paired.extend([np.where(valid, errors[:, :, 0], np.nan), np.where(valid, errors[:, :, ref], np.nan)])
        paired = np.stack(paired, axis=2)
        with np.errstate(divide="ignore", invalid="ignore"):
            point = np.nanmean(paired, axis=1)
            point_skill = np.nanmean(np.where(point[:, [1, 3]]>0, 1-point[:, [0, 2]]/point[:, [1, 3]], np.nan), axis=0)
        for block in cfg["bootstrap"]["blocks"]:
            seed = int(cfg["bootstrap"]["seed"])+int(horizon)*100+int(block)
            rng = np.random.default_rng(seed)
            samples = np.full((int(cfg["bootstrap"]["replicates"]), 2), np.nan)
            for replicate in range(len(samples)):
                dates = []
                for window in range(len(windows)):
                    starts = rng.integers(0, 60-int(block)+1, size=int(np.ceil(60/int(block))))
                    within = (starts[:, None]+np.arange(int(block))).ravel()[:60]
                    dates.extend((window*60+within).tolist())
                sampled_sites = rng.integers(0, len(sites), size=len(sites))
                with np.errstate(divide="ignore", invalid="ignore"):
                    means = np.nanmean(paired[sampled_sites][:, dates, :], axis=1)
                    skills = np.where(means[:, [1, 3]]>0, 1-means[:, [0, 2]]/means[:, [1, 3]], np.nan)
                    samples[replicate] = np.nanmean(skills, axis=0)
            for ref_index, reference in enumerate(candidates[1:]):
                row = ci[(ci.horizon.eq(horizon))&(ci.block_days.eq(block))&(ci.reference.eq(reference))]
                if len(row) != 1: raise AssertionError("Main comparison identity")
                row = row.iloc[0]
                finite = samples[:, ref_index][np.isfinite(samples[:, ref_index])]
                bounds = np.quantile(finite, [.05/4/2, 1-.05/4/2])
                assert_near(point_skill[ref_index], row.mean_station_skill, "Independent primary mean skill")
                assert_near(bounds, [row.lower_ci, row.upper_ci], "Independent paired calendar bootstrap", atol=1e-10)
                if row.replicates != len(samples) or row.finite_replicates != len(finite) or row.bootstrap_seed != seed:
                    raise AssertionError("Bootstrap protocol count/seed mismatch")
                assert_near(row.confidence_level, .9875, "Four-primary multiplicity interval")
                checked.append(dict(horizon=int(horizon), reference=reference, block_days=int(block), replicates=len(samples), seed=seed,
                                    mean_station_skill=float(point_skill[ref_index]), lower_ci=float(bounds[0]), upper_ci=float(bounds[1]),
                                    maximum_interval_difference=float(np.max(np.abs(bounds-[row.lower_ci, row.upper_ci])))))
            print(f"independent primary bootstrap h{horizon}/L{block}: {len(samples)}", flush=True)
    return {"available_date_metric_rows_compared": len(joined), "independent_primary_bootstrap_comparisons": checked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=f"configs/{VERSION}/full.json")
    parser.add_argument("--scope", choices=["smoke", "full"], default="full")
    parser.add_argument("--statistics", action="store_true", help="Also require and independently recheck saved full evaluation metrics and 12 primary intervals")
    args = parser.parse_args(); started = time.perf_counter()
    cfg = json.loads((ROOT/args.config).read_text()); series = load_canonical(cfg)
    role_counts = check_source_roles(cfg)
    counts, scores = check_jobs(cfg, args.scope, series)
    statistics = check_statistics(cfg, scores) if args.statistics else {"statistics_checked": False}
    output = ROOT/f"reports/{VERSION}/audit"; output.mkdir(parents=True, exist_ok=True)
    scores.to_csv(output/f"independent_metrics_by_site_window_{args.scope}.csv", index=False)
    result = dict(status="PASSED", checked_utc=datetime.now(timezone.utc).isoformat(), scope=args.scope,
                  scientific_implementation_imported=False, tolerance=dict(normalized_atol=ATOL, rtol=ATOL, exact_lambda0=True),
                  config_sha256=sha(ROOT/args.config), checker_sha256=sha(__file__), seconds=time.perf_counter()-started,
                  **role_counts, **counts, **statistics)
    (output/f"INDEPENDENT_RESULTS_CHECK_{args.scope.upper()}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
