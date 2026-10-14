"""Stage3G fixed, calendar-safe primitives for similarity-weighted Ridge.

This is a new development implementation. It imports, rather than edits, the
reviewed Stage3B volume features, budget/persistence rules and Ridge algebra.
Weights operate on per-SiteID sufficient statistics: their sum is one and
the intercept is unpenalized. Physical facility independence is not asserted.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .shared_data import Samples, build_samples, scale_from_history, train_samples
from .stage3a_data import compact
from .stage3b_models import (
    LinearModel, calibration_fold, estimate_bias, initial_data, reconstruct,
    residual_target, ridge_fit, subset, usable,
)


DESCRIPTOR_COLUMNS = (
    "iqr_over_scale", "median_adjacent_change_over_scale",
    "lag_one_autocorrelation", "missing_fraction",
)
FEATURE_COLUMNS = (
    "normalized_volume_t", "normalized_volume_t_minus_1",
    "normalized_volume_t_minus_6", "mask_t", "mask_t_minus_1",
    "mask_t_minus_6",
)


@dataclass
class SourceStats:
    """Per-source average augmented-design moments, before source weighting."""

    gram: np.ndarray
    direct_rhs: np.ndarray
    residual_rhs: np.ndarray
    diagnostics: dict


@dataclass
class Descriptor:
    values: np.ndarray
    diagnostics: dict

    @property
    def valid(self):
        return bool(self.diagnostics.get("valid", False))


@dataclass
class DescriptorTransform:
    """All imputation and distance-standardization estimates are source-only."""

    medians: np.ndarray
    means: np.ndarray
    standard_deviations: np.ndarray
    active: np.ndarray
    fitted_source_rows: int
    missing_cells: int

    def transform(self, values):
        raw = np.asarray(values, dtype=float)
        if raw.shape[-1] != 4:
            raise ValueError("Exactly four frozen descriptor components required")
        imputed = np.where(np.isfinite(raw), raw, self.medians)
        out = np.zeros_like(imputed, dtype=float)
        out[..., self.active] = (
            imputed[..., self.active] - self.means[self.active]
        ) / self.standard_deviations[self.active]
        return out

    def as_dict(self):
        return dict(
            medians=self.medians.tolist(), means=self.means.tolist(),
            standard_deviations=self.standard_deviations.tolist(),
            active_components=self.active.tolist(),
            fitted_source_rows=self.fitted_source_rows,
            missing_source_cells=self.missing_cells,
            imputation="finite component median of this training-side source set",
            zero_standard_deviation="component contributes zero distance",
        )


def calendar_history(series, left, right):
    """Explicit calendar positions, with no left-side warm-up or row deletion."""
    left, right = pd.Timestamp(left), pd.Timestamp(right)
    if left > right:
        raise ValueError("History left boundary is after right boundary")
    if not series.index.is_unique:
        raise ValueError("Canonical series must have unique calendar dates")
    dates = pd.date_range(left, right, freq="D")
    return series.reindex(dates).astype(float)


def history_descriptor(series, left, right, minimum_observations=14,
                       minimum_adjacent_pairs=7):
    """Describe only observations in [left,right], ignoring placeholder values.

    IQR uses the reviewed pandas linear empirical quantile convention. Adjacent
    changes and lag-one correlation use pairs exactly one calendar day apart.
    Constant or inadequate sequences have NA correlation; target descriptors
    with any undefined component trigger the documented uniform fallback.
    """
    history = calendar_history(series, left, right)
    values = history.to_numpy(float)
    observed = np.isfinite(values)
    positives = values[observed & (values > 0)]
    scale = float(np.median(positives)) if len(positives) else 1.0
    pairs = observed[:-1] & observed[1:]
    n_observed, n_pairs = int(observed.sum()), int(pairs.sum())
    reasons = []
    iqr = change = autocorrelation = np.nan
    if n_observed >= minimum_observations:
        quantiles = np.quantile(values[observed], [.25, .75], method="linear")
        iqr = float((quantiles[1] - quantiles[0]) / scale)
    else:
        reasons.append("insufficient_valid_observations")
    if n_pairs >= minimum_adjacent_pairs:
        earlier, later = values[:-1][pairs], values[1:][pairs]
        change = float(np.median(np.abs(later - earlier)) / scale)
        if np.std(earlier) > 0 and np.std(later) > 0:
            autocorrelation = float(np.corrcoef(earlier, later)[0, 1])
        else:
            reasons.append("constant_adjacent_series_autocorrelation_undefined")
    else:
        reasons.append("insufficient_valid_adjacent_calendar_pairs")
    result = np.array([iqr, change, autocorrelation, 1. - observed.mean()])
    diagnostics = dict(
        history_start=str(history.index[0].date()),
        history_end=str(history.index[-1].date()),
        calendar_days=len(history), valid_observations=n_observed,
        valid_adjacent_pairs=n_pairs, scale_m3=scale,
        scale_fallback_no_positive_observations=not bool(len(positives)),
        minimum_observations=minimum_observations,
        minimum_adjacent_pairs=minimum_adjacent_pairs,
        components=dict(zip(DESCRIPTOR_COLUMNS,
                            [float(x) if np.isfinite(x) else None for x in result])),
        valid=bool(np.isfinite(result).all()), invalid_reasons=reasons,
    )
    return Descriptor(result, diagnostics)


def source_descriptors(series, ids, budget, end="2020-12-31",
                       minimum_windows=3):
    """Median of fixed same-length calendar histories ending each year 2016--20.

    Each descriptor component uses at least three finite annual windows, never
    a multi-year statistic compared with the target's short-history statistic.
    end may make fewer windows eligible but cannot enable years after 2020.
    Component medians are retained only if >=minimum_windows finite component
    values exist. Inadequate components yield NA; current-training-side source
    imputation handles those components and records the cells it imputes.
    """
    if int(budget) < 1 or int(minimum_windows) < 1:
        raise ValueError("Positive calendar budget/window minimum required")
    end = pd.Timestamp(end)
    rows, raw = [], []
    for site in map(str, ids):
        windows = []
        for year in range(2016, 2021):
            right = pd.Timestamp(year, 12, 31)
            if right > end:
                continue
            left = right - pd.Timedelta(days=int(budget) - 1)
            desc = history_descriptor(series[site], left, right)
            rows.append(dict(site_id=site, descriptor_budget=int(budget),
                             annual_year=year, **desc.diagnostics))
            windows.append(desc.values)
        values = np.asarray(windows, dtype=float).reshape(len(windows), 4)
        counts = np.isfinite(values).sum(axis=0)
        summary = np.array([
            np.median(values[np.isfinite(values[:, j]), j])
            if counts[j] >= minimum_windows else np.nan for j in range(4)
        ])
        raw.append(summary)
        rows.append(dict(site_id=site, descriptor_budget=int(budget),
                         annual_year="summary", annual_windows=len(windows),
                         finite_windows_by_component=counts.tolist(),
                         minimum_windows=int(minimum_windows),
                         valid=bool(np.isfinite(summary).all()),
                         components=dict(zip(DESCRIPTOR_COLUMNS,
                            [float(x) if np.isfinite(x) else None for x in raw[-1]]))))
    return np.asarray(raw, dtype=float).reshape(len(ids), 4), rows


def fit_descriptor_transform(source_raw):
    raw = np.asarray(source_raw, dtype=float)
    if raw.ndim != 2 or raw.shape[1] != 4 or len(raw) == 0:
        raise ValueError("Nonempty source K-by-four descriptors required")
    medians = np.array([
        np.median(raw[np.isfinite(raw[:, j]), j])
        if np.isfinite(raw[:, j]).any() else 0. for j in range(4)
    ])
    imputed = np.where(np.isfinite(raw), raw, medians)
    means = imputed.mean(axis=0)
    deviations = imputed.std(axis=0, ddof=0)
    # Identical float values can produce a tiny nonzero numpy std because the
    # computed mean rounds differently. Exact zero range identifies the stated
    # constant-component case without an arbitrary epsilon or scale threshold.
    active = np.ptp(imputed, axis=0) > 0
    deviations[~active] = 0.
    return DescriptorTransform(medians, means, deviations, active,
                               len(raw), int((~np.isfinite(raw)).sum()))


def similarity_weights(target, source_raw, eta, transform=None):
    """A single squared standardized Euclidean distance and bounded softmax.

    eta=0 is exactly uniform. No labels enter descriptors or standardization.
    Undefined target descriptors, no usable source descriptor, or no active
    distance component yield a recorded uniform fallback.
    """
    if float(eta) not in (0., .5, .9):
        raise ValueError("eta is outside the frozen three-value grid")
    raw = np.asarray(source_raw, dtype=float)
    if raw.ndim != 2 or raw.shape[1] != 4 or len(raw) == 0:
        raise ValueError("Nonempty source K-by-four descriptors required")
    target_values = np.asarray(target.values if isinstance(target, Descriptor)
                               else target, dtype=float)
    if target_values.shape != (4,):
        raise ValueError("Target requires four components")
    transform = transform or fit_descriptor_transform(raw)
    uniform = np.full(len(raw), 1. / len(raw))
    reason = None
    target_valid = bool(np.isfinite(target_values).all())
    if isinstance(target, Descriptor):
        target_valid = target_valid and target.valid
    if not target_valid:
        reason = "target_descriptor_undefined"
    elif not np.isfinite(raw).any():
        reason = "all_source_descriptors_undefined"
    elif not transform.active.any():
        reason = "no_variable_source_descriptor_components"
    if reason is not None:
        weights, d2 = uniform, np.full(len(raw), np.nan)
    else:
        standardized_sources = transform.transform(raw)
        standardized_target = transform.transform(target_values)
        d2 = np.sum((standardized_sources - standardized_target) ** 2, axis=1)
        logits = -d2
        exponential = np.exp(logits - np.max(logits))
        softmax = exponential / exponential.sum()
        weights = uniform if float(eta) == 0 else (
            (1. - float(eta)) * uniform + float(eta) * softmax)
    if not np.isfinite(weights).all() or not np.isclose(weights.sum(), 1.):
        raise AssertionError("Source weight normalization failed")
    difference = float(np.sqrt(np.mean(d2))) if np.isfinite(d2).all() else np.nan
    diagnostics = dict(
        eta=float(eta), source_count=len(raw), weights=weights.tolist(),
        squared_distances=[float(x) if np.isfinite(x) else None for x in d2],
        effective_source_count=float(1. / np.sum(weights ** 2)),
        maximum_source_weight=float(weights.max()),
        uniform_fallback=reason is not None, fallback_reason=reason,
        initial_source_difference=difference if np.isfinite(difference) else None,
        transform=transform.as_dict(),
    )
    return weights, diagnostics


def source_stats_from_samples(data, site_id=None, diagnostics=None):
    """Average moments reproduce weights w_j/n_j without pooled row dominance."""
    data = subset(data, usable(data))
    if not len(data.y):
        raise ValueError("Source has no usable legal residual labels")
    x = compact(data.X).astype(float)
    augmented = np.column_stack([x, np.ones(len(x))])
    n = len(x)
    diag = dict(site_id=site_id, training_labels=n, scale_m3=float(data.scale),
                first_train_origin=str(data.origins.min().date()),
                last_train_origin=str(data.origins.max().date()),
                first_train_target=str(data.targets.min().date()),
                last_train_target=str(data.targets.max().date()),
                nominal_parameters=7, features=6,
                feature_columns=list(FEATURE_COLUMNS),
                objective="sum_j w_j/n_j * sum_t squared_error_jt + alpha*sum_coef_squared",
                intercept_penalized=False)
    diag.update(diagnostics or {})
    return SourceStats(augmented.T @ augmented / n,
                       augmented.T @ np.asarray(data.y, float) / n,
                       augmented.T @ residual_target(data) / n, diag)


def build_source_stats(series, cfg, ids, horizon, end):
    """Legal source samples: input/normalization/labels never cross end."""
    left = pd.Timestamp(cfg.get("source_training_start", "2016-01-01"))
    end = pd.Timestamp(end)
    if end > pd.Timestamp("2021-12-31") or left < pd.Timestamp("2016-01-01"):
        raise ValueError("Stage3G source fitting limited to 2016--2021")
    minimum = int(cfg.get("min_train_labels", 14))
    result = {}
    for site in map(str, ids):
        history = calendar_history(series[site], left, end)
        positives = history[history > 0]
        scale = scale_from_history(series[site], left, end)
        data = train_samples(series[site], left, end, horizon, scale)
        data = subset(data, usable(data))
        if len(data.y) < minimum:
            raise ValueError(f"Insufficient source labels: {site}/{end.date()}/h{horizon}")
        if data.targets.max() > end or data.origins.min() < left:
            raise AssertionError("Illegal source input/target date")
        result[site] = source_stats_from_samples(data, site, dict(
            normalization_fit_start=str(left.date()),
            normalization_fit_end=str(end.date()),
            scale_fallback_no_positive_observations=not bool(len(positives)),
            valid_history_observations=int(history.notna().sum()),
            fit_end=str(end.date()),
        ))
    return result


def fit_weighted(stats, weights, alpha, target="residual"):
    """Solve seven-dimensional weighted normal equations with free intercept."""
    if target not in ("direct", "residual"):
        raise ValueError("Ridge target must be direct or residual")
    if not stats or not np.isfinite(float(alpha)) or float(alpha) <= 0:
        raise ValueError("Nonempty source stats and positive alpha required")
    ids = list(stats)
    w = np.asarray([weights[s] for s in ids] if isinstance(weights, dict)
                   else weights, dtype=float)
    if len(w) != len(ids) or not np.isfinite(w).all() or np.any(w <= 0):
        raise ValueError("Source weights must be positive, finite and aligned")
    if not np.isclose(w.sum(), 1., atol=1e-12, rtol=1e-12):
        raise ValueError("Source total weights must sum to one")
    gram = sum(weight * stats[site].gram for site, weight in zip(ids, w))
    rhs = sum(weight * getattr(stats[site], target + "_rhs")
              for site, weight in zip(ids, w))
    penalty = np.diag([float(alpha)] * 6 + [0.])
    coefficients = np.linalg.solve(gram + penalty, rhs)
    return LinearModel(coefficients[:6], float(coefficients[6]))


def large_error_threshold(training, minimum_errors=14):
    """Initial-history Q90 absolute Persistence error; no deployment truth.

    The inverse-empirical-CDF (inverted_cdf) quantile retains zero errors. An
    event uses error strictly greater than the threshold, including when zero.
    """
    errors = np.abs(training.y * training.scale - training.persistence)
    errors = errors[np.isfinite(errors)]
    enough = len(errors) >= int(minimum_errors)
    threshold = float(np.quantile(errors, .9, method="inverted_cdf")) if enough else None
    diagnostics = dict(
        calibration_error_count=len(errors), minimum_calibration_errors=int(minimum_errors),
        large_error_threshold_m3=threshold, threshold_valid=enough,
        threshold_zero=bool(threshold == 0) if enough else None,
        threshold_quantile=.9, quantile_definition="inf{x:F_empirical(x)>=0.9}",
        event_definition="absolute_error_strictly_greater_than_threshold",
        latest_calibration_target=str(training.targets.max().date()) if len(training.y) else None,
    )
    return threshold, diagnostics


def risk_features(series, origin, left, scale, initial_difference, recent_days=7):
    """Three pre-prediction inputs; no future target or evaluation error used."""
    origin, left = pd.Timestamp(origin), pd.Timestamp(left)
    if scale <= 0 or not np.isfinite(float(scale)) or int(recent_days) != 7:
        raise ValueError("Frozen positive scale and seven-calendar-day risk window required")
    if origin < left:
        raise ValueError("Risk origin is before the allowed history")
    recent_left = max(left, origin - pd.Timedelta(days=6))
    history = calendar_history(series, recent_left, origin).to_numpy(float)
    valid = np.isfinite(history)
    paired = valid[:-1] & valid[1:]
    change = float(np.median(np.abs(np.diff(history)[paired])) / scale) if paired.sum() >= 2 else np.nan
    difference = np.nan if initial_difference is None else float(initial_difference)
    return np.array([difference, float(1. - valid.mean()), change], dtype=float)
