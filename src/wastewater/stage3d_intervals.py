"""Stage3D empirical intervals with legal historical calibration.

These are weighted empirical prediction intervals, without a conformal or
conditional-coverage guarantee. Persistence is the existing Stage3C2
implementation, including its bounded seven-day retrospective-QA lookback.
No target deployment loss is available to any source-selection function.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
import traceback

import numpy as np
import pandas as pd

from .common import sha256, utc_now, write_json
from .shared_data import build_samples, scale_from_history


GAMMAS = (0., .25, .5, .75, 1.)
COVERAGES = (.8, .9)
QUANTILE_CDF_TOLERANCE = 8*np.finfo(np.float64).eps


@dataclass
class Calibration:
    frame: pd.DataFrame
    scale: float | None
    left: pd.Timestamp
    right: pd.Timestamp
    horizon: int
    valid: bool
    reason: str | None
    diagnostic: dict

    @property
    def scores(self):
        return self.frame.loc[self.frame.valid_score, "score"].to_numpy(float)


@dataclass
class EmpiricalDistribution:
    values: np.ndarray
    weights: np.ndarray
    site_ids: tuple = ()
    sample_counts: tuple = ()


def _json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _prefix_hash(series, left, right):
    prefix = series.loc[left:right]
    h = hashlib.sha256()
    h.update(prefix.index.to_numpy(dtype="datetime64[ns]").tobytes())
    values = prefix.to_numpy(dtype="float64").copy()
    # Canonical NaNs for a deterministic legal-prefix cache key.
    values[np.isnan(values)] = np.nan
    h.update(values.tobytes())
    return h.hexdigest()


def weighted_empirical_quantile(values, weights, probability):
    """inf{x:F(x)>=probability}; no interpolation, zero errors are retained.

    Only positive weights contribute. The last cumulative probability is
    exactly one to avoid a rounding-induced out-of-bounds quantile. The
    implementation sorts with stable mergesort. Cumulative probabilities
    use long double, decimal nominal coverage and a frozen 8*float64-eps
    boundary tolerance, solely for probability rounding. The returned
    quantile is always an observed error, never an interpolated value.
    """
    values, weights = np.asarray(values, float), np.asarray(weights, float)
    if values.ndim != 1 or weights.shape != values.shape or not len(values):
        raise ValueError("Quantile needs non-empty one-dimensional matching arrays")
    if not 0 < float(probability) <= 1:
        raise ValueError("Probability must be in (0,1]")
    if not np.isfinite(values).all() or not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError("Quantile values/weights must be finite and weights nonnegative")
    keep = weights > 0
    if not keep.any():
        raise ValueError("Positive total empirical weight is required")
    values, weights = values[keep], weights[keep]
    order = np.argsort(values, kind="mergesort")
    values, weights = values[order], weights[order]
    if float(probability) == 1.:
        return float(values[-1])
    cumulative = np.cumsum(weights, dtype=np.longdouble)
    cumulative /= cumulative[-1]
    cumulative[-1] = 1.
    threshold = np.longdouble(str(float(probability))) - np.longdouble(QUANTILE_CDF_TOLERANCE)
    return float(values[np.searchsorted(cumulative, threshold, side="left")])


def local_distribution(scores):
    values = np.asarray(scores, float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Local errors must be non-empty, finite and nonnegative")
    return EmpiricalDistribution(values.copy(), np.full(len(values), 1. / len(values)))


def source_distribution(errors, source_ids=None, excluded_ids=()):
    """Give every retained source SiteID exactly equal total probability mass."""
    frame = errors.copy()
    frame["site_id"] = frame.site_id.astype(str)
    ids = list(map(str, source_ids)) if source_ids is not None else sorted(frame.site_id.unique())
    ids = [s for s in ids if s not in set(map(str, excluded_ids))]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Shared distribution requires unique nonempty source SiteIDs")
    values, weights, counts = [], [], []
    for site in ids:
        selected = frame.loc[frame.site_id.eq(site), "score"].to_numpy(float)
        if not len(selected) or not np.isfinite(selected).all() or (selected < 0).any():
            raise ValueError(f"Missing/invalid source error library for {site}")
        values.append(selected)
        weights.append(np.full(len(selected), 1. / (len(ids) * len(selected))))
        counts.append(len(selected))
    return EmpiricalDistribution(np.concatenate(values), np.concatenate(weights), tuple(ids), tuple(counts))


def mixture_quantiles(local, source, gamma, coverages=COVERAGES):
    """One gamma shared by both nominal coverages, with exact endpoint paths."""
    gamma = float(gamma)
    if gamma not in GAMMAS:
        raise ValueError("Gamma is outside the frozen five-value grid")
    if gamma == 0.:
        values, weights = local.values, local.weights
    elif gamma == 1.:
        values, weights = source.values, source.weights
    else:
        values = np.concatenate([local.values, source.values])
        weights = np.concatenate([(1.-gamma)*local.weights, gamma*source.weights])
    result = {float(c): weighted_empirical_quantile(values, weights, c) for c in coverages}
    ordered = sorted(result)
    if any(result[a] > result[b] for a, b in zip(ordered[:-1], ordered[1:])):
        raise AssertionError("Empirical nominal intervals are not nested")
    return result


def construct_intervals(persistence, scale, quantile):
    p = np.asarray(persistence, float)
    if not np.isfinite(scale) or scale <= 0 or not np.isfinite(quantile) or quantile < 0:
        raise ValueError("Intervals require a finite positive scale/nonnegative quantile")
    half_width = float(scale) * float(quantile)
    lower, upper = p - half_width, p + half_width
    return lower, upper, np.maximum(0., lower)


def interval_score(truth, lower, upper, alpha, return_components=False):
    """Return raw-unit interval score; NaNs stay NaN rather than being removed."""
    y, l, u = np.broadcast_arrays(np.asarray(truth, float), np.asarray(lower, float), np.asarray(upper, float))
    if not 0 < float(alpha) < 1 or np.any(l > u):
        raise ValueError("Invalid alpha or reversed interval")
    width = u-l
    lower_penalty = (2./float(alpha))*np.maximum(l-y, 0.)
    upper_penalty = (2./float(alpha))*np.maximum(y-u, 0.)
    score = width + lower_penalty + upper_penalty
    if return_components:
        return score, width, lower_penalty, upper_penalty
    return score


def persistence_with_dates(series, origins, horizon, left, scale):
    """Call the legacy Persistence implementation and audit its input dates."""
    origins = pd.DatetimeIndex(origins)
    samples = build_samples(series, origins, int(horizon), left, float(scale))
    input_dates = np.full(len(origins), np.datetime64("NaT"), dtype="datetime64[ns]")
    for lag in range(8):
        dates = origins - pd.Timedelta(days=lag)
        values = series.reindex(dates).to_numpy(float)
        use = np.isnat(input_dates) & np.isfinite(values) & (dates >= pd.Timestamp(left))
        input_dates[use] = dates.to_numpy()[use]
    if np.any(input_dates[~np.isnat(input_dates)] > origins.to_numpy()[~np.isnat(input_dates)]):
        raise AssertionError("Persistence input is after the prediction origin")
    return samples.persistence, pd.DatetimeIndex(input_dates)


def calibrate_history(series, left, right, horizon, min_scores=14):
    """Only origins, Persistence inputs and target labels inside [left,right].

    An all-zero/missing history has no strictly positive median scale and is
    explicitly invalid. The old scale function's numeric fallback of one is
    never promoted to a valid scale in this interval experiment.
    """
    left, right = pd.Timestamp(left), pd.Timestamp(right)
    horizon, min_scores = int(horizon), int(min_scores)
    if horizon not in (1, 3) or left > right or min_scores < 1:
        raise ValueError("Unsupported horizon/history/minimum calibration count")
    prefix = series.loc[left:right]
    values = prefix.to_numpy(float)
    if np.isinf(values).any() or (values[np.isfinite(values)] < 0).any():
        raise ValueError("Input series must already obey finite nonnegative QA rules")
    positives = values[np.isfinite(values) & (values > 0)]
    scale = scale_from_history(series, left, right) if len(positives) else None
    if scale is not None and (not np.isfinite(scale) or scale <= 0):
        scale = None
    origins = pd.date_range(left, right-pd.Timedelta(days=horizon), freq="D")
    targets = origins + pd.Timedelta(days=horizon)
    persistence, input_dates = persistence_with_dates(series, origins, horizon, left, scale or 1.)
    truth = series.reindex(targets).to_numpy(float)
    valid = np.isfinite(truth) & np.isfinite(persistence) & (scale is not None)
    score = np.full(len(origins), np.nan)
    if scale is not None:
        score[valid] = np.abs(truth[valid]-persistence[valid]) / scale
    reason = np.full(len(origins), "", dtype=object)
    reason[~np.isfinite(persistence)] = "MISSING_LEGAL_PERSISTENCE"
    reason[~np.isfinite(truth)] = "MISSING_TARGET"
    reason[~np.isfinite(truth) & ~np.isfinite(persistence)] = "MISSING_TARGET_AND_PERSISTENCE"
    if scale is None:
        reason[:] = "NO_VALID_SCALE"
    frame = pd.DataFrame(dict(origin=origins, target_date=targets, truth=truth,
        persistence=persistence, latest_input_date=input_dates, score=score,
        valid_score=valid, exclusion_reason=reason))
    selected = frame.loc[frame.valid_score]
    sufficient = len(selected) >= min_scores and scale is not None
    failure = None if sufficient else ("NO_VALID_SCALE" if scale is None else "INSUFFICIENT_CALIBRATION_ERRORS")
    if len(selected) and ((selected.target_date > right).any() or
            (selected.origin < left).any() or (selected.latest_input_date < left).any()):
        raise AssertionError("Calibration violated its allowed calendar history")
    def date_minmax(column, direction):
        if selected.empty:
            return None
        value = getattr(selected[column], direction)()
        return None if pd.isna(value) else str(value.date())
    diagnostic = dict(history_start=str(left.date()), history_end=str(right.date()),
        calendar_history_days=(right-left).days+1, horizon=horizon,
        valid_history_observations=int(np.isfinite(values).sum()),
        positive_history_observations=len(positives), scale_m3=scale,
        scale_fit_start=str(left.date()), scale_fit_end=str(right.date()),
        possible_calibration_origins=len(origins), calibration_samples=len(selected),
        zero_errors=int((selected.score == 0).sum()),
        first_calibration_origin=date_minmax("origin", "min"),
        last_calibration_origin=date_minmax("origin", "max"),
        first_calibration_target=date_minmax("target_date", "min"),
        latest_calibration_target=date_minmax("target_date", "max"),
        first_calibration_input=date_minmax("latest_input_date", "min"),
        latest_calibration_input=date_minmax("latest_input_date", "max"),
        missing_target_rows=int((~np.isfinite(truth)).sum()),
        missing_persistence_rows=int((~np.isfinite(persistence)).sum()),
        minimum_calibration_errors=min_scores, valid=sufficient, reason=failure)
    return Calibration(frame, scale, left, right, horizon, sufficient, failure, diagnostic)


def choose_gamma(rows, gammas=GAMMAS, tie_tolerance=1e-12):
    """Average pseudo-windows within SiteID, then equal-weight SiteIDs.

    Every gamma must have the same valid folds. Missing software results are
    errors, not candidate-specific intersections. Fixed tolerance handles
    numeric ties; the smallest gamma within tolerance of minimum wins.
    """
    frame = pd.DataFrame(rows)
    if frame.empty or frame.duplicated(["site_id", "pseudo_origin", "gamma"]).any():
        raise ValueError("Empty or duplicate source-validation rows")
    candidate_sets = {float(g): set(map(tuple, frame.loc[frame.gamma.eq(g), ["site_id", "pseudo_origin"]].to_numpy()))
                      for g in gammas}
    if any(not v for v in candidate_sets.values()) or len({frozenset(v) for v in candidate_sets.values()}) != 1:
        raise ValueError("Gamma candidate validation folds are not identical")
    if not np.isfinite(frame.normalized_interval_score.to_numpy(float)).all():
        raise ValueError("Nonfinite source-validation objective")
    by_site = frame.groupby(["gamma", "site_id"], sort=True).normalized_interval_score.mean()
    objectives = by_site.groupby(level="gamma").mean()
    minimum = float(objectives.min())
    selected = min(float(g) for g in gammas if float(objectives.loc[g]) <= minimum+float(tie_tolerance))
    return selected, {str(float(g)): float(objectives.loc[g]) for g in gammas}


def _validate_rules(cfg):
    expected = dict(source_training_start="2016-01-01", source_training_end="2021-12-31",
        source_selection_train_end="2020-12-31", source_pseudo_origins=["2021-01-01", "2021-07-01"],
        source_pseudo_validation_days=14, budgets=[30, 90, 180], horizons=[1, 3],
        gammas=list(GAMMAS), min_calibration_scores=14)
    for key, value in expected.items():
        if cfg.get(key) != value:
            raise ValueError(f"Frozen Stage3D source rule differs: {key}")
    if float(cfg.get("gamma_tie_tolerance", 1e-12)) != 1e-12:
        raise ValueError("Gamma numeric tie tolerance must be frozen at 1e-12")
    if float(cfg.get("quantile_cdf_tolerance", QUANTILE_CDF_TOLERANCE)) != QUANTILE_CDF_TOLERANCE:
        raise ValueError("Empirical CDF numeric boundary tolerance changed")


_SOURCE_CALIBRATION_CACHE = {}


def linked_sites(site, related_ids=None):
    """Stage3C2's identical conservative undirected relation closure.

    The small pure relation operation is copied here to keep Stage3D from
    importing any Ridge, GRU or scikit-learn code. Unknown relations do not
    establish physical-facility independence.
    """
    result = {str(site)}
    adjacency = {}
    for key, members in (related_ids or {}).items():
        if isinstance(members, str):
            raise TypeError("related_ids must map SiteIDs to lists, not facility-name strings")
        group = {str(key), *(str(member) for member in members)}
        for member in group:
            adjacency.setdefault(member, set()).update(group)
    pending = list(result)
    while pending:
        member = pending.pop()
        for other in adjacency.get(member, ()):
            if other not in result:
                result.add(other)
                pending.append(other)
    return result


def _source_errors(series, cfg, source_ids, end):
    rows, diagnostics = [], []
    for site in source_ids:
        for horizon in cfg["horizons"]:
            key = (str(site), cfg["source_training_start"], end, horizon,
                   _prefix_hash(series[site], cfg["source_training_start"], end))
            if key not in _SOURCE_CALIBRATION_CACHE:
                _SOURCE_CALIBRATION_CACHE[key] = calibrate_history(series[site],
                    cfg["source_training_start"], end, horizon, cfg["min_calibration_scores"])
            calibration = _SOURCE_CALIBRATION_CACHE[key]
            if not calibration.valid:
                raise ValueError(f"Source calibration invalid: {site}/{end}/H{horizon}: {calibration.reason}")
            frame = calibration.frame.loc[calibration.frame.valid_score].copy()
            frame["site_id"] = str(site)
            frame["horizon"] = horizon
            frame["scale_m3"] = calibration.scale
            frame["full_pool_per_error_weight"] = 1./(len(source_ids)*len(calibration.scores))
            rows.append(frame)
            diagnostics.append(dict(site_id=str(site), source_end=end,
                full_pool_total_site_weight=1./len(source_ids),
                full_pool_per_error_weight=1./(len(source_ids)*len(calibration.scores)),
                **calibration.diagnostic))
    return pd.concat(rows, ignore_index=True), diagnostics


def validate_completed_source_cache(folder, fingerprint, cfg, expected_sites):
    """COMPLETED requires all expected folds, decisions and checked artifacts."""
    folder = Path(folder)
    status_file = folder / "status.json"
    if not status_file.is_file():
        return False
    status = json.loads(status_file.read_text())
    if status.get("fingerprint") != fingerprint:
        raise ValueError("Source interval cache fingerprint mismatch")
    if status.get("status") != "COMPLETED":
        return False
    required = {"source_errors_proxy.csv.gz", "source_errors_final.csv.gz", "source_diagnostics.csv",
        "source_validation.csv", "source_validation_diagnostics.csv", "selected_gamma.json"}
    hashes = status.get("outputs_sha256", {})
    expected_folds = len(expected_sites)*len(cfg["source_pseudo_origins"])*len(cfg["budgets"])*len(cfg["horizons"])
    if status.get("completed_folds") != expected_folds or status.get("expected_folds") != expected_folds:
        raise ValueError("Source interval cache fold counts are incomplete")
    if status.get("completed_choices") != len(cfg["budgets"])*len(cfg["horizons"]):
        raise ValueError("Source interval cache choices are incomplete")
    if not required.issubset(hashes):
        raise ValueError("Source interval cache is missing required output hashes")
    for member, digest in hashes.items():
        path = folder / member
        if not path.is_file() or sha256(path) != digest:
            raise ValueError(f"Source interval cache artifact changed/missing: {member}")
    return True


def load_source_bank(folder, cfg, source_ids, fingerprint=None):
    folder = Path(folder)
    status = json.loads((folder / "status.json").read_text())
    fingerprint = fingerprint or status["fingerprint"]
    if not validate_completed_source_cache(folder, fingerprint, cfg, source_ids):
        raise ValueError("Cannot load partial source interval calibration")
    errors = pd.read_csv(folder / "source_errors_final.csv.gz", dtype={"site_id": str})
    selection = json.loads((folder / "selected_gamma.json").read_text())
    final = {h: source_distribution(errors.loc[errors.horizon.eq(h)], source_ids) for h in cfg["horizons"]}
    gamma = {f"B{b}_H{h}": float(selection["choices"][f"B{b}_H{h}"]["gamma"])
             for b in cfg["budgets"] for h in cfg["horizons"]}
    return dict(final=final, selected_gamma=gamma, source_ids=list(source_ids),
        pool_id=selection["pool_id"], selection=selection, folder=str(folder), status=status,
        selection_sha256=sha256(folder / "selected_gamma.json"))


def prepare_source_bank(cfg, series, source_ids, source_output, related_ids=None,
                        signature=None, pool_id="order20261012_K30", progress=None):
    """Cache source-only LOSO-group gamma selection before target prediction.

    Source library scales use each source's own 2016--cutoff positive median.
    Held-source local scales use only its B-day initial history. Source
    validation 90% scores are divided by those held local scales, and averaged
    equally by held SiteID and its two pseudo-deployment windows.
    """
    _validate_rules(cfg)
    ids = list(map(str, source_ids))
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError("A source pool must contain unique nonempty SiteIDs")
    folder = Path(source_output)
    folder.mkdir(parents=True, exist_ok=True)
    provenance = dict(pool_id=pool_id, source_ids=ids, related_ids=related_ids or {}, run_signature=signature,
        legal_source_prefix_sha256={s: _prefix_hash(series[s], "2016-01-01", "2021-12-31") for s in ids},
        rules={key: cfg.get(key) for key in ("source_training_start", "source_training_end",
            "source_selection_train_end", "source_pseudo_origins", "source_pseudo_validation_days",
            "budgets", "horizons", "gammas", "min_calibration_scores", "gamma_tie_tolerance",
            "quantile_cdf_tolerance")},
        code_sha256={p.name: sha256(p) for p in [Path(__file__), Path(__file__).with_name("shared_data.py")]},
        numpy=np.__version__, pandas=pd.__version__)
    fingerprint = _json_hash(provenance)
    if validate_completed_source_cache(folder, fingerprint, cfg, ids):
        bank = load_source_bank(folder, cfg, ids, fingerprint)
        bank["cache_reused"] = True
        return bank
    expected = len(ids)*len(cfg["source_pseudo_origins"])*len(cfg["budgets"])*len(cfg["horizons"])
    status = dict(status="RUNNING", fingerprint=fingerprint, provenance=provenance,
        expected_folds=expected, completed_folds=0, completed_choices=0,
        failed=0, started_utc=utc_now(), outputs_sha256={})
    write_json(folder / "status.json", status)
    started = time.perf_counter()
    try:
        proxy, proxy_diagnostics = _source_errors(series, cfg, ids, cfg["source_selection_train_end"])
        final, final_diagnostics = _source_errors(series, cfg, ids, cfg["source_training_end"])
        proxy.to_csv(folder / "source_errors_proxy.csv.gz", index=False, compression={"method":"gzip", "mtime":0})
        final.to_csv(folder / "source_errors_final.csv.gz", index=False, compression={"method":"gzip", "mtime":0})
        pd.DataFrame(proxy_diagnostics+final_diagnostics).to_csv(folder / "source_diagnostics.csv", index=False)
        validation_rows, fold_diagnostics = [], []
        last_progress = started
        for held in ids:
            excluded = linked_sites(held, related_ids)
            if not (set(ids)-excluded):
                raise ValueError("A held relation group leaves no legal source error library")
            held_distributions = {h: source_distribution(proxy.loc[proxy.horizon.eq(h)], ids, excluded)
                                  for h in cfg["horizons"]}
            for pseudo_origin in cfg["source_pseudo_origins"]:
                first_origin = pd.Timestamp(pseudo_origin)
                for budget in cfg["budgets"]:
                    left, right = first_origin-pd.Timedelta(days=budget), first_origin-pd.Timedelta(days=1)
                    for horizon in cfg["horizons"]:
                        local = calibrate_history(series[held], left, right, horizon, cfg["min_calibration_scores"])
                        diagnostic = dict(site_id=held, pseudo_origin=pseudo_origin, budget=budget,
                            pool_id=pool_id, excluded_related_ids="|".join(sorted(excluded)),
                            retained_source_count=len(held_distributions[horizon].site_ids),
                            source_error_cutoff=cfg["source_selection_train_end"], **local.diagnostic)
                        if not local.valid:
                            # These are deterministic data limitations, not software failures.
                            diagnostic.update(validation_valid=False, validation_failure=local.reason,
                                              validation_samples=0)
                            fold_diagnostics.append(diagnostic)
                            status["completed_folds"] += 1
                            continue
                        origins = pd.date_range(first_origin, periods=cfg["source_pseudo_validation_days"], freq="D")
                        p, inputs = persistence_with_dates(series[held], origins, horizon, left, local.scale)
                        targets = origins+pd.Timedelta(days=horizon)
                        truth = series[held].reindex(targets).to_numpy(float)
                        keep = np.isfinite(p) & np.isfinite(truth)
                        if not keep.any():
                            diagnostic.update(validation_valid=False, validation_failure="NO_VALID_PSEUDO_TARGETS",
                                              validation_samples=0)
                            fold_diagnostics.append(diagnostic)
                            status["completed_folds"] += 1
                            continue
                        diagnostic.update(validation_valid=True, validation_failure=None,
                            validation_samples=int(keep.sum()),
                            first_validation_origin=str(origins[keep].min().date()),
                            last_validation_origin=str(origins[keep].max().date()),
                            latest_validation_target=str(targets[keep].max().date()),
                            latest_validation_input=str(inputs[keep].max().date()))
                        fold_diagnostics.append(diagnostic)
                        empirical_local = local_distribution(local.scores)
                        for gamma in cfg["gammas"]:
                            q = mixture_quantiles(empirical_local, held_distributions[horizon], gamma)[.9]
                            lower, upper, _ = construct_intervals(p[keep], local.scale, q)
                            normalized_score = interval_score(truth[keep], lower, upper, .1)/local.scale
                            validation_rows.append(dict(pool_id=pool_id, site_id=held, pseudo_origin=pseudo_origin,
                                budget=budget, horizon=horizon, gamma=float(gamma), quantile_90=q,
                                normalized_interval_score=float(normalized_score.mean()),
                                coverage=float(((truth[keep]>=lower)&(truth[keep]<=upper)).mean()),
                                normalized_width=float(np.mean(upper-lower)/local.scale),
                                validation_samples=int(keep.sum()), calibration_samples=len(local.scores),
                                scale_m3=local.scale, source_error_cutoff=cfg["source_selection_train_end"],
                                excluded_related_ids="|".join(sorted(excluded))))
                        status["completed_folds"] += 1
                        if time.perf_counter()-last_progress >= 30:
                            write_json(folder / "status.json", status)
                            if progress:
                                progress(f"source_interval_validation {pool_id} {status['completed_folds']}/{expected}")
                            last_progress = time.perf_counter()
        validation = pd.DataFrame(validation_rows)
        validation.to_csv(folder / "source_validation.csv", index=False)
        pd.DataFrame(fold_diagnostics).to_csv(folder / "source_validation_diagnostics.csv", index=False)
        choices = {}
        for budget in cfg["budgets"]:
            for horizon in cfg["horizons"]:
                selected_rows = validation.loc[validation.budget.eq(budget)&validation.horizon.eq(horizon)]
                gamma, objectives = choose_gamma(selected_rows, cfg["gammas"], cfg.get("gamma_tie_tolerance",1e-12))
                choices[f"B{budget}_H{horizon}"] = dict(gamma=gamma, normalized_objectives=objectives,
                    valid_held_sites=int(selected_rows.site_id.nunique()),
                    valid_held_windows=int(len(selected_rows)/len(cfg["gammas"])),
                    intended_held_sites=len(ids), intended_held_windows=len(ids)*len(cfg["source_pseudo_origins"]))
        selection = dict(pool_id=pool_id, source_ids=ids, fingerprint=fingerprint,
            choices=choices, selected_without_target_deployment_losses=True,
            empirical_quantile="inf{x:weighted_CDF(x)>=c}; no interpolation",
            loss="90% interval score / held-source allowed initial-history scale",
            averaging="equal pseudo-windows within held SiteID, then equal held SiteIDs",
            tie_tolerance=cfg.get("gamma_tie_tolerance",1e-12), tie_rule="smaller gamma",
            quantile_cdf_tolerance=QUANTILE_CDF_TOLERANCE,
            selected_utc=utc_now())
        write_json(folder / "selected_gamma.json", selection)
        members=["source_errors_proxy.csv.gz", "source_errors_final.csv.gz", "source_diagnostics.csv",
                 "source_validation.csv", "source_validation_diagnostics.csv", "selected_gamma.json"]
        status.update(status="COMPLETED", completed_choices=len(choices), finished_utc=utc_now(),
            elapsed_seconds=time.perf_counter()-started,
            outputs_sha256={m:sha256(folder/m) for m in members})
        if status["completed_folds"] != expected:
            raise AssertionError("Not all source-validation folds were processed")
        write_json(folder / "status.json", status)
        bank = load_source_bank(folder, cfg, ids, fingerprint)
        bank["cache_reused"] = False
        return bank
    except Exception:
        status.update(status="FAILED", failed=1, finished_utc=utc_now(),
                      failure_traceback=traceback.format_exc(), elapsed_seconds=time.perf_counter()-started)
        write_json(folder / "status.json", status)
        raise
