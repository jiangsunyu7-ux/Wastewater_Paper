"""Fixed pre-forecast risk scoring for Stage3G; never changes point forecasts.

All transforms fit on the named source training role.  Source operating
thresholds are calibrated on a separate source role; final thresholds use
outer-fold honest risk scores, not the final model's training scores.  Missing
metrics remain missing.  Hash tie breaking never uses truth or an error label.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from .shared_data import build_samples


FEATURES = ("initial_source_target_difference", "recent_input_missing_fraction",
            "recent_volume_change_normalized")
RISK_METHODS = ("logistic", "random", "missing_rate",
                "prediction_persistence_difference")
OPERATING_FRACTIONS = (.1, .2)
HASH_SEED = 20261014
MIN_ERROR_COUNT = 14


def hash_uniform(key, salt="risk-random", seed=HASH_SEED):
    """Truth-independent uniform in [0,1); stable across CPUs and resumes."""
    digest = sha256(f"Wessex-G|{seed}|{salt}|{key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64)


def weighted_left_quantile(values, probability, weights=None):
    """inf{x:F(x)>=probability}, with exact observed support and no interpolation."""
    values = np.asarray(values, dtype=float)
    weights = np.ones(len(values), float) if weights is None else np.asarray(weights, float)
    if len(values) != len(weights) or not 0 <= probability <= 1:
        raise ValueError("Invalid quantile inputs")
    good = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not np.any(good):
        raise ValueError("No finite positively weighted quantile observations")
    values, weights = values[good], weights[good]
    order = np.argsort(values, kind="stable")
    values, weights = values[order], weights[order]
    # Accumulate before normalization: ten equal observations have F(x_9)=.9,
    # rather than an accumulated .1 rounding error changing the support index.
    cumulative = np.cumsum(weights) / weights.sum()
    index = min(int(np.searchsorted(cumulative, probability, side="left")), len(values)-1)
    return float(values[index])


def equal_site_window_weights(frame, total=1.0):
    """Equal SiteID, then equal pseudo-window, then equal eligible date."""
    if frame.empty:
        return np.empty(0, float)
    if not {"site_id", "episode"}.issubset(frame.columns):
        raise ValueError("Equal source weights need site_id and episode")
    sites = frame.site_id.astype(str)
    episodes = frame.episode.astype(str)
    pairs = pd.DataFrame({"site": sites.to_numpy(), "episode": episodes.to_numpy()})
    windows_per_site = pairs.drop_duplicates().groupby("site").episode.nunique()
    count_per_pair = pairs.groupby(["site", "episode"]).size()
    n_sites = int(sites.nunique())
    weights = np.asarray([1/(n_sites * windows_per_site[s] * count_per_pair[(s, e)])
                          for s, e in pairs.itertuples(index=False, name=None)], float)
    return weights * (float(total) / weights.sum())


def recent_risk_features(series, origin, budget_left, scale):
    """Last seven calendar inputs through origin; no pre-budget warm start."""
    origin, budget_left = pd.Timestamp(origin), pd.Timestamp(budget_left)
    if not np.isfinite(scale) or scale <= 0 or origin < budget_left:
        raise ValueError("Invalid risk input boundary or scale")
    left = max(budget_left, origin-pd.Timedelta(days=6))
    dates = pd.date_range(left, origin, freq="D")
    values = series.reindex(dates).to_numpy(float)
    finite = np.isfinite(values)
    pair = finite[1:] & finite[:-1]
    change = float(np.median(np.abs(np.diff(values)[pair])) / scale) if pair.sum() >= 2 else np.nan
    return dict(recent_input_missing_fraction=float(1-finite.mean()),
                recent_volume_change_normalized=change,
                recent_input_start=str(left.date()), recent_input_end=str(origin.date()),
                recent_input_calendar_days=len(dates), recent_valid_inputs=int(finite.sum()),
                recent_valid_adjacent_pairs=int(pair.sum()))


def initial_error_threshold(series, left, right, horizon, scale=1.0):
    """Persistence-error Q90 within initial history; both labels and inputs legal."""
    left, right = pd.Timestamp(left), pd.Timestamp(right)
    if horizon not in (1, 3) or right < left or not np.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid initial calibration history")
    origins = pd.date_range(left, right-pd.Timedelta(days=horizon), freq="D")
    data = build_samples(series, origins, horizon, left, scale)
    errors = np.abs(data.y*scale-data.persistence)
    good = np.isfinite(errors)
    q = weighted_left_quantile(errors[good], .9) if good.sum() >= MIN_ERROR_COUNT else np.nan
    return dict(large_error_threshold_m3=q, initial_error_samples=int(good.sum()),
                initial_error_threshold_defined=bool(np.isfinite(q)),
                initial_error_threshold_zero=bool(np.isfinite(q) and q == 0),
                threshold_quantile_definition="left empirical support quantile; event strictly greater",
                threshold_first_origin=str(data.origins[good].min().date()) if good.any() else None,
                threshold_last_origin=str(data.origins[good].max().date()) if good.any() else None,
                threshold_last_label=str(data.targets[good].max().date()) if good.any() else None,
                threshold_history_start=str(left.date()), threshold_history_end=str(right.date()))


def large_error_events(truth, prediction, threshold):
    truth, prediction, threshold = np.broadcast_arrays(np.asarray(truth, float),
        np.asarray(prediction, float), np.asarray(threshold, float))
    valid = np.isfinite(truth) & np.isfinite(prediction) & np.isfinite(threshold) & (threshold >= 0)
    event = np.full(truth.shape, np.nan)
    event[valid] = (np.abs(truth[valid]-prediction[valid]) > threshold[valid]).astype(float)
    return event


@dataclass
class RiskModel:
    medians: list
    means: list
    standard_deviations: list
    coefficients: list
    intercept: float
    constant_probability: float | None
    status: str
    diagnostics: dict

    def predict(self, frame):
        if self.status == "NO_TRAINING_LABELS":
            return np.full(len(frame), np.nan)
        x = frame.loc[:, list(FEATURES)].to_numpy(float)
        x = np.where(np.isfinite(x), x, np.asarray(self.medians))
        x = (x-np.asarray(self.means))/np.asarray(self.standard_deviations)
        if self.constant_probability is not None:
            return np.full(len(frame), self.constant_probability, float)
        z = x @ np.asarray(self.coefficients) + self.intercept
        # Numerically stable sigmoid without an epsilon or changed event threshold.
        result = np.empty(len(z), float)
        positive = z >= 0
        result[positive] = 1/(1+np.exp(-z[positive]))
        ez = np.exp(z[~positive]); result[~positive] = ez/(1+ez)
        return result


def fit_risk_model(frame):
    """Fixed C=1 logistic regression; all imputation/scaling from risk-train side."""
    required = set(FEATURES) | {"large_error_event", "site_id", "episode"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Missing risk training columns: {sorted(required-set(frame.columns))}")
    event = pd.to_numeric(frame.large_error_event.replace({"True": 1, "False": 0,
        "true": 1, "false": 0}), errors="coerce").to_numpy(float)
    valid = np.isfinite(event) & np.isin(event, [0, 1])
    train = frame.loc[valid].copy()
    x = train.loc[:, list(FEATURES)].to_numpy(float)
    medians = np.asarray([np.median(x[np.isfinite(x[:, j]), j]) if np.isfinite(x[:, j]).any()
                          else 0.0 for j in range(len(FEATURES))], float)
    missing_features = [FEATURES[j] for j in range(len(FEATURES)) if not np.isfinite(x[:, j]).any()]
    x = np.where(np.isfinite(x), x, medians)
    diagnostics = dict(train_rows=len(frame), eligible_train_rows=len(train), excluded_labels=int((~valid).sum()),
        event_count=int(event[valid].sum()), non_event_count=int(len(train)-event[valid].sum()),
        features=list(FEATURES), all_missing_features_imputed_to_zero=missing_features,
        training_sites=sorted(train.site_id.astype(str).unique().tolist()),
        training_windows=sorted(train.episode.astype(str).unique().tolist()),
        C=1.0, solver="lbfgs", max_iter=1000, class_weight=None,
        weight_rule="equal SiteID then pseudo-window then date; weights rescaled to eligible row count",
        standardization_and_medians_fit_role="risk_train_only")
    if train.empty:
        return RiskModel(medians.tolist(), [0.]*3, [1.]*3, [0.]*3, 0., None,
                         "NO_TRAINING_LABELS", diagnostics)
    weights = equal_site_window_weights(train, total=len(train))
    means = np.average(x, axis=0, weights=weights)
    deviations = np.sqrt(np.average((x-means)**2, axis=0, weights=weights))
    constant = np.ptp(x, axis=0) == 0
    means[constant] = x[0, constant]
    deviations[constant] = 1.
    deviations[deviations == 0] = 1.
    transformed = (x-means)/deviations
    classes = np.unique(event[valid])
    if len(classes) == 1:
        probability = float(classes[0])
        diagnostics["single_class"] = int(classes[0]); diagnostics["optimizer_iterations"] = 0
        return RiskModel(medians.tolist(), means.tolist(), deviations.tolist(), [0.]*3, 0.,
                         probability, "SINGLE_CLASS_CONSTANT", diagnostics)
    model = LogisticRegression(C=1., solver="lbfgs", max_iter=1000, class_weight=None,
                               fit_intercept=True).fit(transformed, event[valid].astype(int), sample_weight=weights)
    diagnostics["optimizer_iterations"] = int(model.n_iter_.max())
    diagnostics["optimizer_at_iteration_limit"] = bool(model.n_iter_.max() >= 1000)
    return RiskModel(medians.tolist(), means.tolist(), deviations.tolist(), model.coef_[0].tolist(),
                     float(model.intercept_[0]), None, "FITTED", diagnostics)


def score_methods(model, frame):
    keys = frame["row_key"].astype(str) if "row_key" in frame else frame["risk_row_key"].astype(str)
    logistic = model.predict(frame)
    if "prediction_m3" in frame and "persistence_m3" in frame:
        scale = frame.scale_m3.to_numpy(float)
        disagreement = np.abs(frame.prediction_m3.to_numpy(float)-frame.persistence_m3.to_numpy(float))/scale
        disagreement[~np.isfinite(scale) | (scale <= 0)] = np.nan
    else:
        disagreement = frame.disagreement_rule_score.to_numpy(float)
    return dict(logistic=logistic,
        random=np.asarray([hash_uniform(k) for k in keys]),
        missing_rate=frame.recent_input_missing_fraction.to_numpy(float),
        prediction_persistence_difference=disagreement)


def operating_threshold(scores, weights, fraction, source="source_threshold_calibration"):
    """Expected source marking mass; exact score ties use a truth-free hash coin."""
    scores, weights = np.asarray(scores, float), np.asarray(weights, float)
    good = np.isfinite(scores) & np.isfinite(weights) & (weights > 0)
    if not 0 < fraction < 1 or len(scores) != len(weights):
        raise ValueError("Invalid operating threshold calibration")
    if not good.any():
        return dict(score_threshold=None, tie_fraction=None, expected_mark_fraction=fraction,
                    status="NO_CALIBRATION_SCORES", calibration_scores=0, source=source)
    scores, weights = scores[good], weights[good]; weights = weights/weights.sum()
    q = weighted_left_quantile(scores, 1-fraction, weights)
    above = float(weights[scores > q].sum()); equal = float(weights[scores == q].sum())
    tie = min(1., max(0., (fraction-above)/equal))
    return dict(score_threshold=q, tie_fraction=tie, expected_mark_fraction=fraction,
                status="CALIBRATED", calibration_scores=len(scores),
                above_threshold_weight=above, at_threshold_weight=equal,
                expected_calibration_mark_fraction=above+tie*equal, source=source,
                ties_resolved="fixed SHA256 score-independent hash; no error or truth used")


def apply_operating_threshold(scores, keys, threshold, method):
    scores = np.asarray(scores, float); keys = np.asarray(keys, str)
    result = np.full(len(scores), np.nan)
    if len(keys) != len(scores):
        raise ValueError("Score/key length differs")
    if threshold["status"] != "CALIBRATED":
        return result
    valid = np.isfinite(scores); q = threshold["score_threshold"]
    result[valid] = (scores[valid] > q).astype(float)
    tied = valid & (scores == q)
    salt = f"risk-tie-{method}-{threshold['expected_mark_fraction']}"
    result[tied] = np.asarray([hash_uniform(k, salt=salt) < threshold["tie_fraction"]
                              for k in keys[tied]], float)
    return result


def _long_scores(frame, model, thresholds, score_source):
    rows = []
    keys = frame["row_key"].astype(str).to_numpy() if "row_key" in frame else frame["risk_row_key"].astype(str).to_numpy()
    for method, scores in score_methods(model, frame).items():
        out = frame.copy(); out["risk_method"] = method; out["risk_score"] = scores
        out["large_error_event"] = pd.to_numeric(out.large_error_event.replace({
            "True": 1, "False": 0, "true": 1, "false": 0}), errors="coerce").astype(float)
        out["risk_row_key"] = keys; out["risk_score_source"] = score_source
        out["risk_model_status"] = model.status; out["point_prediction_modified"] = False
        if "origin" in out and "episode" in out and "budget" in out:
            origins = pd.to_datetime(out.origin)
            starts = pd.to_datetime(out.episode)
            history_left = starts-pd.to_timedelta(out.budget.astype(int), unit="D")
            recent_left = (origins-pd.Timedelta(days=6)).where(origins-pd.Timedelta(days=6) >= history_left, history_left)
            out["risk_recent_input_start"] = recent_left.dt.strftime("%Y-%m-%d")
            out["risk_recent_input_end"] = origins.dt.strftime("%Y-%m-%d")
            out["risk_static_information_cutoff_date"] = (starts-pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
        available = np.isfinite(out.prediction_m3.to_numpy(float))
        out["point_prediction_available"] = available
        for fraction in OPERATING_FRACTIONS:
            tag = f"{int(fraction*100)}pct"; t = thresholds[method][tag]
            flagged = apply_operating_threshold(scores, keys, t, method)
            flagged[~available] = np.nan
            out[f"review_{tag}"] = flagged
            out[f"operating_threshold_{tag}"] = t["score_threshold"]
            out[f"tie_fraction_{tag}"] = t["tie_fraction"]
            out[f"threshold_status_{tag}"] = t["status"]
            out[f"threshold_source_{tag}"] = t["source"]
        rows.append(out)
    return pd.concat(rows, ignore_index=True)


def _thresholds(model, frame, source):
    weights = equal_site_window_weights(frame)
    scores = score_methods(model, frame)
    return {method: {f"{int(f*100)}pct": operating_threshold(s, weights, f, source)
                     for f in OPERATING_FRACTIONS} for method, s in scores.items()}


def _condition_key(pool, budget, horizon):
    return f"{pool}|B{int(budget)}|h{int(horizon)}"


def fit_source_crossfit(source_rows):
    """Five predeclared source roles; final risk model and honest score thresholds."""
    required = {"pool_id", "budget", "horizon", "outer_fold", "role", "site_id",
                "group_id", "episode", "row_key"} | set(FEATURES) | {"large_error_event"}
    if not required.issubset(source_rows.columns):
        raise ValueError(f"Missing source crossfit fields: {sorted(required-set(source_rows.columns))}")
    scores_all, threshold_rows, model_rows, bundle = [], [], [], {}
    for (pool, budget, horizon), condition in source_rows.groupby(["pool_id", "budget", "horizon"], sort=True):
        outer_scores = []
        folds = sorted(condition.outer_fold.unique())
        if folds != [0, 1, 2, 3, 4]:
            raise ValueError(f"Expected frozen five outer folds, found {folds}")
        for fold in folds:
            current = condition[condition.outer_fold.eq(fold)]
            train = current[current.role.eq("risk_train")].copy()
            calibration = current[current.role.eq("threshold_calibration")].copy()
            evaluation = current[current.role.eq("outer_evaluation")].copy()
            groups = {name: set(frame.group_id.astype(str)) for name, frame in
                      (("risk_train", train), ("threshold_calibration", calibration), ("outer_evaluation", evaluation))}
            if any(groups[a] & groups[b] for a, b in (("risk_train", "threshold_calibration"),
                        ("risk_train", "outer_evaluation"), ("threshold_calibration", "outer_evaluation"))):
                raise ValueError("Source role groups overlap; refusing indirect leakage")
            if any(not group for group in groups.values()):
                raise ValueError("Missing a source risk role; do not silently score a partial fold")
            model = fit_risk_model(train)
            thresholds = _thresholds(model, calibration, "source_disjoint_threshold_calibration")
            scored = _long_scores(evaluation, model, thresholds, "source_outer_group_crossfit")
            outer_scores.append(scored); scores_all.append(scored)
            model_rows.append(dict(pool_id=pool, budget=int(budget), horizon=int(horizon),
                outer_fold=int(fold), role="outer_crossfit_risk_model", **asdict(model),
                group_roles={key: sorted(value) for key, value in groups.items()}))
            for method in RISK_METHODS:
                for tag, threshold in thresholds[method].items():
                    threshold_rows.append(dict(pool_id=pool, budget=int(budget), horizon=int(horizon),
                        outer_fold=int(fold), risk_method=method, operating_fraction=tag, **threshold))
        all_scores = pd.concat(outer_scores, ignore_index=True)
        base_eval = condition[condition.role.eq("outer_evaluation")].copy()
        if base_eval.row_key.duplicated().any():
            raise ValueError("Repeated outer evaluation row; group crossfit is not unique")
        final_model = fit_risk_model(base_eval)
        final_thresholds = {}
        for method in RISK_METHODS:
            honest = all_scores[all_scores.risk_method.eq(method)]
            weights = equal_site_window_weights(honest)
            final_thresholds[method] = {}
            for fraction in OPERATING_FRACTIONS:
                tag = f"{int(fraction*100)}pct"
                threshold = operating_threshold(honest.risk_score, weights, fraction,
                                               "source_outer_crossfit_OOS")
                final_thresholds[method][tag] = threshold
                threshold_rows.append(dict(pool_id=pool, budget=int(budget), horizon=int(horizon),
                    outer_fold="final", risk_method=method, operating_fraction=tag, **threshold))
        key = _condition_key(pool, budget, horizon)
        bundle[key] = dict(model=asdict(final_model), thresholds=final_thresholds,
            final_training_groups=sorted(base_eval.group_id.astype(str).unique().tolist()),
            operational_threshold_scores="source_outer_group_crossfit; no final-model fitted scores",
            limitation="source role risk training 6 to final 30 groups; base fitting 12 to target 30 groups")
        model_rows.append(dict(pool_id=pool, budget=int(budget), horizon=int(horizon),
            outer_fold="final", role="final_source_base_OOF_training", **asdict(final_model)))
    return bundle, pd.concat(scores_all, ignore_index=True), pd.DataFrame(threshold_rows), model_rows


def score_target_risk(bundle, target_rows):
    """Apply frozen source-only models and thresholds; target truth cannot affect scores."""
    results = []
    for (pool, budget, horizon), rows in target_rows.groupby(["pool_id", "budget", "horizon"], sort=True):
        key = _condition_key(pool, budget, horizon)
        if key not in bundle:
            raise ValueError(f"Missing frozen risk condition {key}; refusing silent omission")
        entry = bundle[key]; model = RiskModel(**entry["model"])
        results.append(_long_scores(rows, model, entry["thresholds"], "frozen_source_model_target_deployment"))
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def write_bundle(bundle, path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def read_bundle(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
