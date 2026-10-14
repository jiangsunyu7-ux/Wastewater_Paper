"""Frozen, compact residual Ridge primitives; no deployment labels in fitting.

Volumes and residuals are divided by an allowed-history positive median.
Weights sum to one, so sklearn Ridge minimizes weighted mean squared error
plus alpha times squared coefficients; the intercept is not penalized.
"""
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from .shared_data import Samples, build_samples, scale_from_history, train_samples
from .stage3a_data import compact


FAMILIES = ("local_residual_ridge", "shared_residual_ridge", "shared_residual_ridge_bias")
MODELS = ("persistence", "weekly_persistence", "local_ridge_lags_tuned",
          "shared_ridge_lags", "shared_ridge_lags_bias") + tuple(
    f"{family}_{policy}" for family in FAMILIES for policy in ("unshrunk", "selected"))


@dataclass
class LinearModel:
    coef_: np.ndarray
    intercept_: float

    def predict(self, X):
        return np.asarray(X, dtype=float).reshape(len(X), -1) @ self.coef_ + self.intercept_


def ridge_fit(X, y, alpha, weights=None):
    X = np.asarray(X, dtype=float).reshape(len(y), -1)
    y = np.asarray(y, dtype=float)
    if not len(y) or not np.isfinite(X).all() or not np.isfinite(y).all():
        raise ValueError("Ridge needs finite inputs and labels")
    weights = np.full(len(y), 1 / len(y)) if weights is None else np.asarray(weights, dtype=float)
    if len(weights) != len(y) or not np.all(weights > 0) or not np.isclose(weights.sum(), 1.):
        raise ValueError("Weights must be positive and sum to one")
    fit = Ridge(alpha=float(alpha), fit_intercept=True).fit(X, y, sample_weight=weights)
    return LinearModel(fit.coef_.copy(), float(fit.intercept_))


def subset(data, keep):
    return Samples(data.X[keep], data.y[keep], data.origins[keep], data.targets[keep],
                   data.persistence[keep], data.weekly[keep], data.scale)


def usable(data):
    """One training mask for all new residual and matched direct methods."""
    return np.isfinite(data.y) & np.isfinite(data.persistence) & (data.X[:, :, 1].sum(axis=1) > 0)


def residual_target(data):
    if not np.isfinite(data.persistence).all():
        raise ValueError("A residual label needs its legal Persistence forecast")
    return data.y - data.persistence / data.scale


def reconstruct(persistence, residual_prediction, bias, shrinkage, scale):
    """Zero shrinkage returns the actual baseline, including its missing values."""
    if shrinkage == 0:
        return np.asarray(persistence, dtype=float).copy()
    return np.asarray(persistence, dtype=float) + float(shrinkage) * (
        np.asarray(residual_prediction, dtype=float) + float(bias)) * float(scale)


def estimate_bias(model, training):
    return float(np.mean(residual_target(training) - model.predict(compact(training.X))))


def initial_data(series, date, budget, horizon, cfg):
    start = pd.Timestamp(date)
    left = start - pd.Timedelta(days=budget)
    end = start - pd.Timedelta(days=1)
    scale = scale_from_history(series, left, end)
    before = train_samples(series, left, end, horizon, scale)
    train = subset(before, usable(before))
    if len(train.y) < cfg["min_train_labels"]:
        raise ValueError("Insufficient legal calibration labels")
    deployment = build_samples(series, pd.date_range(start, periods=cfg["evaluation_days"]),
                               horizon, left, scale)
    history = series.loc[left:end]
    threshold_left = start - pd.Timedelta(days=cfg.get("high_volume_history_days", 30))
    qhistory = series.loc[threshold_left:end].dropna()
    diag = dict(site_id=None, episode=date, budget=budget, horizon=horizon,
        budget_start=str(left.date()), fit_end=str(end.date()), initial_calendar_days=budget,
        scale_m3=scale, normalization_fit_start=str(left.date()), normalization_fit_end=str(end.date()),
        scale_observed_count=int(history.notna().sum()), valid_initial_inputs=int(history.notna().sum()),
        valid_initial_targets=int(history.notna().sum()), training_labels=len(train.y),
        direct_legacy_training_labels=len(before.y), residual_required_persistence_exclusions=len(before.y)-len(train.y),
        first_train_origin=str(train.origins.min().date()), last_train_origin=str(train.origins.max().date()),
        first_train_target=str(train.targets.min().date()), last_train_target=str(train.targets.max().date()),
        high_threshold_m3=float(qhistory.quantile(cfg["high_volume_quantile"])) if len(qhistory) >= 14 else None,
        threshold_history_days=cfg.get("high_volume_history_days", 30), threshold_observations=len(qhistory),
        threshold_start=str(threshold_left.date()), threshold_end=str(end.date()),
        model_and_scale_frozen=True, deployment_label_updates=False,
        information_assumption="origin-day volume known at end of day; published QA used retrospectively")
    if train.targets.max() > end:
        raise AssertionError("Training label crosses initial calibration cutoff")
    return train, deployment, diag


def calibration_fold(series, date, budget, horizon, cfg, pseudo=False):
    start = pd.Timestamp(date)
    left = start - pd.Timedelta(days=budget)
    end = start - pd.Timedelta(days=1)
    if pseudo:
        fit_end = end
        origins = pd.date_range(start, periods=cfg["source_pseudo_validation_days"])
        val_start = start
    else:
        tail = math.ceil(cfg["local_validation_fraction"] * budget)
        val_start = end - pd.Timedelta(days=tail - 1)
        fit_end = val_start - pd.Timedelta(days=1)
        origins = pd.date_range(val_start, end - pd.Timedelta(days=horizon))
    scale = scale_from_history(series, left, fit_end)
    train = train_samples(series, left, fit_end, horizon, scale)
    train = subset(train, usable(train))
    validation = build_samples(series, origins, horizon, left, scale)
    validation = subset(validation, usable(validation))
    min_fit = cfg["min_train_labels"] if pseudo else cfg["validation_min_fit_labels"]
    min_val = 1 if pseudo else cfg["validation_min_labels"]
    diag = dict(kind="source_simulated_same_budget_LOSO" if pseudo else "budget_internal_purged_time_validation",
        source_assisted=pseudo, budget=budget, horizon=horizon, date=date,
        budget_start=str(left.date()), budget_end=str(end.date()), fit_start=str(left.date()),
        fit_end=str(fit_end.date()), validation_start=str(val_start.date()),
        first_fit_origin=str(train.origins.min().date()) if len(train.y) else None,
        last_fit_origin=str(train.origins.max().date()) if len(train.y) else None,
        first_fit_target=str(train.targets.min().date()) if len(train.y) else None,
        last_fit_target=str(train.targets.max().date()) if len(train.y) else None,
        first_validation_origin=str(validation.origins.min().date()) if len(validation.y) else None,
        last_validation_origin=str(validation.origins.max().date()) if len(validation.y) else None,
        first_validation_target=str(validation.targets.min().date()) if len(validation.y) else None,
        last_validation_target=str(validation.targets.max().date()) if len(validation.y) else None,
        fitting_labels=len(train.y), validation_labels=len(validation.y),
        valid_fit_inputs=int(series.loc[left:fit_end].notna().sum()), scale_m3=scale,
        normalization_fit_start=str(left.date()), normalization_fit_end=str(fit_end.date()),
        valid=bool(len(train.y) >= min_fit and len(validation.y) >= min_val),
        label_purge_horizon=horizon, bias_fit_start=str(left.date()), bias_fit_end=str(fit_end.date()))
    if len(train.y) and train.targets.max() >= val_start:
        raise AssertionError("A fitting label crosses validation start")
    ceiling = pd.Timestamp("2021-12-31") if pseudo else end
    if len(validation.y) and validation.targets.max() > ceiling:
        raise AssertionError("Validation target crosses allowed boundary")
    return train, validation, diag


def candidate_scores(train, validation, shared_models, cfg):
    """Fit b on training labels, then evaluate the frozen b on validation labels."""
    rows = []
    val_residual = residual_target(validation)
    for alpha in cfg["ridge_alphas"]:
        local = ridge_fit(compact(train.X), residual_target(train), alpha)
        shared = shared_models[float(alpha)]
        bias = estimate_bias(shared, train)
        for family, model, b in ((FAMILIES[0], local, 0.), (FAMILIES[1], shared, 0.),
                                 (FAMILIES[2], shared, bias)):
            predicted = model.predict(compact(validation.X)) + b
            for lam in cfg["lambdas"]:
                # Algebraically equal to normalized volume MAE against its own legal baseline.
                error = float(lam) * predicted - val_residual
                rows.append(dict(family=family, alpha=float(alpha), shrinkage=float(lam),
                    validation_mae=float(np.mean(np.abs(error))),
                    validation_mse=float(np.mean(error ** 2)), bias_normalized=b,
                    fitting_labels=len(train.y), validation_labels=len(validation.y)))
    return rows


def choose_parameters(rows):
    """Exact numerical ties: smaller lambda, then smaller alpha; no deployment error."""
    frame = pd.DataFrame(rows)
    decisions = {}
    for family in FAMILIES:
        grouped = frame[frame.family.eq(family)].groupby(["alpha", "shrinkage"], as_index=False).validation_mae.mean()
        for policy in ("unshrunk", "selected"):
            choices = grouped[grouped.shrinkage.eq(1.)] if policy == "unshrunk" else grouped
            row = choices.sort_values(["validation_mae", "shrinkage", "alpha"], kind="stable").iloc[0]
            decisions[f"{family}_{policy}"] = dict(alpha=float(row.alpha), shrinkage=float(row.shrinkage),
                validation_mae=float(row.validation_mae), selection_rule="equal fold mean normalized MAE; ties lambda then alpha")
    return decisions
