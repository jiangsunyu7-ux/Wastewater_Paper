"""Matched calendar, equal-SiteID evaluation for frozen source-scale experiments.

This module never fits a model. All five 2022--2023 episodes are USED
development history. Inference is exploratory: synchronized noncircular
calendar blocks within each episode, followed by whole-SiteID resampling.
The six prespecified B30 comparisons use Bonferroni-adjusted intervals.
"""
from __future__ import annotations

import itertools
import json
import time
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .common import sha256, utc_now, write_json

KEYS = ['site_id', 'episode', 'horizon', 'origin', 'target_date']
ROW_KEYS = KEYS + ['budget', 'pool_id', 'model']
TASK_KEYS = ['site_id', 'episode', 'budget', 'horizon', 'pool_id', 'model']
PRIMARY_MODEL = 'shared_residual_ridge_bias_selected'
LOCAL = 'local_residual_ridge_selected'
BASE_MODELS = ['persistence', 'weekly_persistence', 'local_residual_ridge_unshrunk', LOCAL]
SHARED_MODELS = ['shared_residual_ridge_unshrunk', 'shared_residual_ridge_selected',
                 'shared_residual_ridge_bias_unshrunk', PRIMARY_MODEL]
TIE_TOLERANCE = 1e-12


def _mean(array, axis=None):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        return np.nanmean(array, axis=axis)


def evaluation_policies(cfg):
    """Return the explicit frozen policy registry; never infer missing jobs away."""
    if cfg.get('evaluation_policies'):
        policies = [dict(p) for p in cfg['evaluation_policies']]
    else:
        pools = cfg.get('pools', cfg.get('source_pools', []))
        if isinstance(pools, dict):
            pools = [dict(value, pool_id=key) for key, value in pools.items()]
        policies = [dict(pool_id='baseline', model=m, k=0, order_label='baseline') for m in BASE_MODELS]
        for pool in pools:
            pool_id = pool.get('pool_id', pool.get('id'))
            if not pool_id:
                raise ValueError('Source pool requires pool_id')
            k = pool.get('k', pool.get('K', len(pool.get('source_ids', []))))
            policies.extend(dict(pool_id=pool_id, model=m, k=int(k),
                                 order_label=str(pool.get('order_label', 'common' if int(k) == 3 else 'unknown')))
                            for m in SHARED_MODELS)
    if not policies:
        raise ValueError('An explicit evaluation_policies or source-pool registry is required')
    for policy in policies:
        policy['pool_id'] = str(policy['pool_id'])
        policy['model'] = str(policy['model'])
        policy['k'] = int(policy.get('k', 0))
        policy['order_label'] = str(policy.get('order_label', 'baseline'))
        policy['policy_id'] = policy['pool_id'] + '::' + policy['model']
    if len({p['policy_id'] for p in policies}) != len(policies):
        raise ValueError('Duplicate policy registration')
    return policies


def origins(cfg):
    values = list(cfg.get('evaluation_origins', cfg['origins']))
    if len(values) != len(set(values)):
        raise ValueError('Duplicate episode')
    for origin in values:
        if pd.Timestamp(origin) + pd.Timedelta(days=int(cfg['evaluation_days']) - 1 + max(cfg['horizons'])) > pd.Timestamp('2023-12-31'):
            raise ValueError('2024--2025 performance is forbidden')
    return values


def prepare_predictions(frame, cfg):
    p = frame.rename(columns={'prediction_raw': 'prediction_m3', 'prediction_nonnegative': 'prediction_nonnegative_m3',
                              'truth': 'truth_m3', 'target': 'target_date', 'threshold': 'high_threshold_m3'}).copy()
    required = ROW_KEYS + ['truth_m3', 'prediction_m3', 'high_threshold_m3']
    if any(column not in p for column in required):
        raise ValueError('Missing columns: ' + ', '.join(c for c in required if c not in p))
    policies = evaluation_policies(cfg)
    registry = pd.DataFrame(policies)
    p['site_id'] = p.site_id.astype(str)
    p['pool_id'] = p.pool_id.astype(str)
    for name in ['budget', 'horizon']:
        p[name] = p[name].astype(int)
    for name in ['episode', 'origin', 'target_date']:
        p[name] = pd.to_datetime(p[name]).dt.strftime('%Y-%m-%d')
    p['seed'] = p['seed'] if 'seed' in p else 0
    if not p.seed.eq(0).all():
        raise ValueError('C2 Ridge is deterministic; no seed repetition or prediction ensemble')
    if p.duplicated(ROW_KEYS).any():
        raise ValueError('Duplicate deterministic forecast')
    p['policy_id'] = p.pool_id + '::' + p.model
    if not set(p.policy_id) <= set(registry.policy_id):
        raise ValueError('Unregistered pool/model')
    if not set(p.site_id) <= set(map(str, cfg['development_ids'])):
        raise ValueError('Unregistered target SiteID')
    if not set(p.episode) <= set(origins(cfg)) or not set(p.budget) <= set(cfg['budgets']) or not set(p.horizon) <= set(cfg['horizons']):
        raise ValueError('Unregistered condition')
    if not (pd.to_datetime(p.target_date) - pd.to_datetime(p.origin)).dt.days.eq(p.horizon).all():
        raise ValueError('Target must be origin+h single-day volume')
    if not (pd.to_datetime(p.origin) - pd.to_datetime(p.episode)).dt.days.between(0, cfg['evaluation_days'] - 1).all():
        raise ValueError('Origin outside frozen episode')
    if 'latest_input_date' in p and (pd.to_datetime(p.latest_input_date) > pd.to_datetime(p.origin)).any():
        raise ValueError('Input later than forecast origin')
    if {'last_train_target', 'fit_end'} <= set(p) and (pd.to_datetime(p.last_train_target) > pd.to_datetime(p.fit_end)).any():
        raise ValueError('Training target exceeds cutoff')
    # The registry, rather than observed output, defines expected tasks.
    for column in ['k', 'order_label']:
        if column in p:
            declared = p.policy_id.map(registry.set_index('policy_id')[column])
            if not (p[column].astype(str) == declared.astype(str)).all():
                raise ValueError('Pool metadata differs from frozen registry: ' + column)
            p = p.drop(columns=column)
    for column in ['truth_m3', 'high_threshold_m3']:
        bounds = p.groupby(KEYS)[column].agg(['min', 'max'])
        if ((bounds['max'] - bounds['min']) > 1e-8 + 1e-12 * bounds['min'].abs()).any():
            raise ValueError('Inconsistent matched ' + column)
    clipped = np.maximum(0., p.prediction_m3.to_numpy(float))
    if 'prediction_nonnegative_m3' in p:
        if not np.allclose(p.prediction_nonnegative_m3.to_numpy(float), clipped, rtol=0, atol=0, equal_nan=True):
            raise ValueError('Nonnegative constraint is not exact/uniform')
    else:
        p['prediction_nonnegative_m3'] = clipped
    p['prediction_row_present'] = p.prediction_row_present.eq(True) if 'prediction_row_present' in p else True
    condition = pd.MultiIndex.from_product([list(map(str, cfg['development_ids'])), origins(cfg), cfg['budgets'], cfg['horizons'],
                                             registry.policy_id], names=['site_id', 'episode', 'budget', 'horizon', 'policy_id']).to_frame(index=False)
    length = int(cfg['evaluation_days'])
    expected = condition.loc[condition.index.repeat(length)].reset_index(drop=True)
    offsets = np.tile(np.arange(length), len(condition))
    expected['origin'] = (pd.to_datetime(expected.episode) + pd.to_timedelta(offsets, unit='D')).dt.strftime('%Y-%m-%d')
    expected['target_date'] = (pd.to_datetime(expected.origin) + pd.to_timedelta(expected.horizon, unit='D')).dt.strftime('%Y-%m-%d')
    expected = expected.merge(registry, on='policy_id', validate='many_to_one')
    p = expected.merge(p.drop(columns='policy_id'), on=ROW_KEYS, how='left', validate='one_to_one')
    p['prediction_row_present'] = p.prediction_row_present.eq(True)
    p['seed'] = p.seed.fillna(0).astype(int)
    for column in ['truth_m3', 'high_threshold_m3']:
        p[column] = p[column].fillna(p.groupby(KEYS)[column].transform('first'))
    p['finite_truth'] = np.isfinite(p.truth_m3)
    p['finite_prediction'] = np.isfinite(p.prediction_m3)
    p['evaluation_set'] = 'all_five_used_development'
    valid = (p.finite_truth & p.finite_prediction & p.prediction_row_present).groupby([p[key] for key in KEYS]).all()
    p['common_evaluation'] = p.set_index(KEYS).index.map(valid).astype(bool)
    p['prediction_failure_reason'] = np.select([~p.prediction_row_present, ~p.finite_truth, ~p.finite_prediction],
                                              ['missing_prediction_row_or_failed_task', 'missing_true_target', 'nonfinite_prediction'], default='')
    # Exact lambda=0 identity is mandatory wherever a persistence value exists.
    if 'shrinkage' in p:
        baseline = p[p.pool_id.eq('baseline') & p.model.eq('persistence')][KEYS + ['budget', 'prediction_m3']]
        zero = p[p.shrinkage.eq(0) & p.model.ne('persistence')]
        matched = zero.merge(baseline, on=KEYS + ['budget'], suffixes=('', '_p'), validate='many_to_one')
        if not np.array_equal(matched.prediction_m3.to_numpy(), matched.prediction_m3_p.to_numpy(), equal_nan=True):
            raise ValueError('lambda=0 must exactly return Persistence')
    return p


def station_metrics(daily, cfg, per_episode=False):
    keys = ['evaluation_set', 'constraint', 'site_id', 'pool_id', 'model', 'budget', 'horizon']
    if per_episode:
        keys.insert(1, 'episode')
    metric = daily.groupby(keys).agg(n_dates=('absolute_error', 'size'), mae_m3=('absolute_error', 'mean'),
                                    mse=('squared_error', 'mean')).reset_index()
    registry = pd.DataFrame(evaluation_policies(cfg))
    base = pd.MultiIndex.from_product([['all_five_used_development'], ['raw', 'all_models_nonnegative'],
                                      map(str, cfg['development_ids']), cfg['budgets'], cfg['horizons']],
                                     names=['evaluation_set', 'constraint', 'site_id', 'budget', 'horizon']).to_frame(index=False)
    expected = base.merge(registry, how='cross')
    if per_episode:
        expected = expected.merge(pd.DataFrame({'episode': origins(cfg)}), how='cross')
    metric = expected.merge(metric, on=keys, how='left', validate='one_to_one')
    metric['n_dates'] = metric.n_dates.fillna(0).astype(int)
    metric['rmse_m3'] = np.sqrt(metric.pop('mse'))
    reference_keys = [key for key in keys if key not in ['pool_id', 'model']]
    reference = metric[metric.pool_id.eq('baseline') & metric.model.eq('persistence')][reference_keys + ['mae_m3']]
    metric = metric.merge(reference.rename(columns={'mae_m3': 'persistence_mae_m3'}), on=reference_keys, validate='many_to_one')
    metric['zero_reference_mae'] = metric.persistence_mae_m3.eq(0)
    metric['skill_vs_persistence'] = 1 - metric.mae_m3 / metric.persistence_mae_m3.where(metric.persistence_mae_m3.gt(0))
    return metric


def aggregate_station_metrics(metric, per_episode=False):
    keys = ['evaluation_set', 'constraint', 'pool_id', 'model', 'k', 'order_label', 'budget', 'horizon']
    if per_episode:
        keys.insert(1, 'episode')
    rows = []
    for values, g in metric.groupby(keys, sort=True):
        skill = g.skill_vs_persistence.dropna()
        wins = int(skill.gt(TIE_TOLERANCE).sum()); losses = int(skill.lt(-TIE_TOLERANCE).sum())
        ties = int(skill.abs().le(TIE_TOLERANCE).sum()); n = len(skill)
        rows.append(dict(zip(keys, values), stations=len(g), stations_with_dates=int(g.n_dates.gt(0).sum()),
                         defined_skill_stations=n, equal_station_mae_m3=float(g.mae_m3.mean()),
                         equal_station_rmse_m3=float(g.rmse_m3.mean()), mean_skill=float(skill.mean()),
                         median_skill=float(skill.median()), winning_stations=wins, tied_stations=ties,
                         worse_stations=losses, win_fraction=wins / n if n else np.nan,
                         tie_fraction=ties / n if n else np.nan, loss_fraction=losses / n if n else np.nan,
                         zero_reference_stations=int(g.zero_reference_mae.sum()),
                         min_dates=int(g.n_dates.min()), max_dates=int(g.n_dates.max())))
    return pd.DataFrame(rows)


def comparisons(cfg):
    policies = evaluation_policies(cfg); registered = {(p['pool_id'], p['model']) for p in policies}
    primary_pool = cfg.get('primary_pool_id', 'order20261012_K30')
    common_pool = cfg.get('reference_pool_id', 'K3')
    pairs = []
    def add(pool, model, budget, ref_pool, ref_model, ref_budget, horizon, kind):
        if (pool, model) not in registered or (ref_pool, ref_model) not in registered:
            return
        primary = pool == primary_pool and model == PRIMARY_MODEL and budget == 30 and ref_budget == 30 and (
            (ref_pool, ref_model) in [('baseline', 'persistence'), (common_pool, PRIMARY_MODEL), ('baseline', LOCAL)])
        pairs.append(dict(id=f'{pool}_{model}_B{budget}_vs_{ref_pool}_{ref_model}_B{ref_budget}_H{horizon}',
                          pool_id=pool, model=model, budget=budget, reference_pool_id=ref_pool, reference=ref_model,
                          reference_budget=ref_budget, horizon=horizon, kind=kind, prespecified_primary=primary))
    for horizon in cfg['horizons']:
        for budget in cfg['budgets']:
            for p in policies:
                pool, model = p['pool_id'], p['model']
                if model != 'persistence':
                    add(pool, model, budget, 'baseline', 'persistence', budget, horizon, 'vs_persistence')
                if model.startswith('shared_'):
                    local = LOCAL if model.endswith('_selected') else 'local_residual_ridge_unshrunk'
                    add(pool, model, budget, 'baseline', local, budget, horizon, 'same_budget_transfer')
                    if pool != common_pool:
                        add(pool, model, budget, common_pool, model, budget, horizon, 'source_scale_vs_K3')
                if model.endswith('_selected'):
                    add(pool, model, budget, pool, model.replace('_selected', '_unshrunk'), budget, horizon, 'selection_and_shrinkage')
                if model.startswith('shared_residual_ridge_bias'):
                    add(pool, model, budget, pool, model.replace('_bias', ''), budget, horizon, 'bias_diagnostic')
        for p in policies:
            if p['model'].startswith('shared_'):
                for budget, ref_budget in [(30, 90), (30, 180), (90, 180)]:
                    local = LOCAL if p['model'].endswith('_selected') else 'local_residual_ridge_unshrunk'
                    add(p['pool_id'], p['model'], budget, 'baseline', local, ref_budget, horizon, 'history_budget_comparison')
    if len({p['id'] for p in pairs}) != len(pairs):
        raise ValueError('Duplicate comparison')
    return pairs


def calendar_draw_indices(n_sites, n_episodes, length, block, replicates, seed):
    """Retain old time-then-SiteID RNG order; never concatenate block gaps."""
    if not 1 <= block <= length:
        raise ValueError('Block outside episode length')
    rng = np.random.default_rng(seed)
    for _ in range(replicates):
        dates = []
        for episode in range(n_episodes):
            starts = rng.integers(0, length - block + 1, size=int(np.ceil(length / block)))
            draws = (starts[:, None] + np.arange(block)).ravel()[:length]
            dates.extend((episode * length + draws).tolist())
        yield rng.integers(0, n_sites, size=n_sites), np.asarray(dates, dtype=np.int32)


@lru_cache(maxsize=24)
def _draw_tables(n_sites, n_episodes, length, block, replicates, seed):
    draws = list(calendar_draw_indices(n_sites, n_episodes, length, block, replicates, seed))
    dates = np.stack([d[1] for d in draws]); sites = np.stack([d[0] for d in draws])
    dates.flags.writeable = False; sites.flags.writeable = False
    return sites, dates


def bootstrap_station_means(errors, n_episodes, length, block, replicates, seed, batch_size=128):
    """Rolling sums replace repeated date gathering; identical arithmetic estimand.

    All policy/date masks are common. Bootstrap time indices still include
    missing calendar positions, whose error/count contribution is zero.
    Blocks are drawn separately inside each of the fixed episodes.
    """
    n_sites, n_dates, n_policies = errors.shape
    if n_dates != n_episodes * length:
        raise ValueError('Dense array lost calendar positions')
    site_indices, time_indices = _draw_tables(n_sites, n_episodes, length, block, replicates, seed)
    finite = np.isfinite(errors)
    result = np.empty((replicates, n_sites, n_policies), dtype=float)
    prefix = np.concatenate([np.zeros((n_sites, 1, n_policies)), np.cumsum(np.where(finite, errors, 0.), axis=1)], axis=1)
    counts = np.concatenate([np.zeros((n_sites, 1, n_policies), dtype=np.int32), np.cumsum(finite, axis=1)], axis=1)
    chunk_starts = np.arange(0, length, block)
    for begin in range(0, replicates, batch_size):
        end = min(replicates, begin + batch_size)
        numer = np.zeros((end - begin, n_sites, n_policies)); denom = np.zeros_like(numer)
        for episode in range(n_episodes):
            for chunk_start in chunk_starts:
                start = time_indices[begin:end, episode * length + chunk_start]
                stop = start + min(block, length - chunk_start)
                numer += (prefix[:, stop, :] - prefix[:, start, :]).transpose(1, 0, 2)
                denom += (counts[:, stop, :] - counts[:, start, :]).transpose(1, 0, 2)
        with np.errstate(divide='ignore', invalid='ignore'):
            means = np.where(denom > 0, numer / denom, np.nan)
        result[begin:end] = means[np.arange(end - begin)[:, None], site_indices[begin:end], :]
    return result


def _dense_errors(daily, cfg, horizon, constraint, subset):
    sites = list(map(str, cfg['development_ids'])); episodes = origins(cfg); length = cfg['evaluation_days']
    labels = [(b, p['pool_id'], p['model']) for b in cfg['budgets'] for p in evaluation_policies(cfg)]
    label_lookup = {label: i for i, label in enumerate(labels)}
    q = daily[daily.horizon.eq(horizon) & daily.constraint.eq(constraint)]
    if subset == 'historical_high_volume':
        q = q[q.truth_m3.ge(q.high_threshold_m3) & q.high_threshold_m3.notna()]
    errors = np.full((len(sites), len(episodes) * length, len(labels)), np.nan)
    if len(q):
        day = (pd.to_datetime(q.origin) - pd.to_datetime(q.episode)).dt.days.to_numpy()
        site_idx = q.site_id.map({s: i for i, s in enumerate(sites)}).to_numpy()
        date_idx = q.episode.map({e: i for i, e in enumerate(episodes)}).to_numpy() * length + day
        policy_idx = np.fromiter((label_lookup[row] for row in zip(q.budget, q.pool_id, q.model)), dtype=int, count=len(q))
        errors[site_idx, date_idx, policy_idx] = q.absolute_error.to_numpy()
    return errors, labels


def paired_block_intervals(daily, cfg, constraint='raw', subset='all_dates', progress=print):
    sites = list(map(str, cfg['development_ids'])); episodes = origins(cfg)
    rows = []; site_rows = []; all_comparisons = comparisons(cfg)
    for horizon in cfg['horizons']:
        errors, labels = _dense_errors(daily, cfg, horizon, constraint, subset)
        label_lookup = {label: i for i, label in enumerate(labels)}
        mean = _mean(errors, axis=1); counts = np.isfinite(errors).sum(axis=1)
        active = [p for p in all_comparisons if p['horizon'] == horizon]
        for comparison in active:
            aidx = label_lookup[(comparison['budget'], comparison['pool_id'], comparison['model'])]
            bidx = label_lookup[(comparison['reference_budget'], comparison['reference_pool_id'], comparison['reference'])]
            a, b = mean[:, aidx], mean[:, bidx]
            with np.errstate(divide='ignore', invalid='ignore'):
                skills = np.where(b > 0, 1 - a / b, np.nan)
            for i, site in enumerate(sites):
                site_rows.append(dict(comparison, evaluation_set='all_five_used_development', constraint=constraint, subset=subset,
                                      site_id=site, mae_m3=float(a[i]), reference_mae_m3=float(b[i]), skill=float(skills[i]),
                                      n_dates=int(counts[i, aidx]), reference_n_dates=int(counts[i, bidx]),
                                      zero_reference_mae=bool(b[i] == 0), negative_transfer=bool(skills[i] < -TIE_TOLERANCE),
                                      win=bool(skills[i] > TIE_TOLERANCE), tie=bool(abs(skills[i]) <= TIE_TOLERANCE)))
        for block in cfg['bootstrap']['blocks']:
            started = time.monotonic()
            seed = int(cfg['bootstrap']['seed']) + int(horizon) * 100 + int(block)
            replicates = int(cfg['bootstrap']['replicates'])
            draw_means = bootstrap_station_means(errors, len(episodes), cfg['evaluation_days'], block, replicates, seed)
            for comparison in active:
                aidx = label_lookup[(comparison['budget'], comparison['pool_id'], comparison['model'])]
                bidx = label_lookup[(comparison['reference_budget'], comparison['reference_pool_id'], comparison['reference'])]
                a, b = draw_means[:, :, aidx], draw_means[:, :, bidx]
                a0, b0 = mean[:, aidx], mean[:, bidx]
                with np.errstate(divide='ignore', invalid='ignore'):
                    samples = _mean(np.where(b > 0, 1 - a / b, np.nan), axis=1)
                    station_skill = np.where(b0 > 0, 1 - a0 / b0, np.nan)
                usable = samples[np.isfinite(samples)]
                primary = comparison['prespecified_primary'] and constraint == 'raw' and subset == 'all_dates'
                alpha = .05 / 6 if primary else .05
                quantiles = [.025, .975, alpha / 2, 1 - alpha / 2]
                bounds = np.quantile(usable, quantiles) if len(usable) else np.full(4, np.nan)
                rows.append(dict(comparison, evaluation_set='all_five_used_development', constraint=constraint, subset=subset,
                                 block_days=int(block), replicates=replicates, finite_replicates=len(usable), bootstrap_seed=seed,
                                 mean_station_skill=float(_mean(station_skill)), lower_95=float(bounds[0]), upper_95=float(bounds[1]),
                                 lower_ci=float(bounds[2]), upper_ci=float(bounds[3]),
                                 lower_bonferroni_6=float(bounds[2]) if primary else np.nan,
                                 upper_bonferroni_6=float(bounds[3]) if primary else np.nan,
                                 confidence_level=1-alpha, co_primary=primary,
                                 multiplicity_family='six prespecified B30 comparisons' if primary else 'exploratory pointwise',
                                 winning_stations=int(np.sum(station_skill > TIE_TOLERANCE)),
                                 tied_stations=int(np.sum(np.abs(station_skill) <= TIE_TOLERANCE)),
                                 negative_transfer_stations=int(np.sum(station_skill < -TIE_TOLERANCE)),
                                 defined_skill_stations=int(np.isfinite(station_skill).sum()),
                                 zero_reference_stations=int(np.sum(b0 == 0)), minimum_paired_dates=int(counts[:, aidx].min())))
            progress(f'Statistics: {constraint}, {subset}, h={horizon}, block={block}, {replicates} synchronized replicates; {time.monotonic()-started:.2f}s', flush=True)
    return pd.DataFrame(rows), pd.DataFrame(site_rows)


def _save_csv(frame, output, name):
    frame.to_csv(output / name, index=False, compression={'method': 'gzip', 'mtime': 0} if name.endswith('.gz') else None)


def summarize_predictions(frame, cfg, output, experiment_integrity=None, progress=print):
    """Recompute every output from saved predictions; report partial honestly."""
    output = Path(output); output.mkdir(parents=True, exist_ok=True); started = time.monotonic()
    p = prepare_predictions(frame, cfg)
    _save_csv(p, output, 'predictions_all.csv.gz')
    availability = p.groupby(TASK_KEYS).agg(planned_origins=('origin', 'size'), saved_prediction_rows=('prediction_row_present', 'sum'),
                                           valid_truths=('finite_truth', 'sum'), finite_predictions=('finite_prediction', 'sum'),
                                           common_dates=('common_evaluation', 'sum'), negative_predictions=('prediction_m3', lambda s: int(s.lt(0).sum()))).reset_index()
    availability['prediction_coverage'] = availability.finite_predictions / availability.planned_origins
    availability['matched_evaluation_coverage'] = availability.common_dates / availability.planned_origins
    _save_csv(availability, output, 'availability.csv')
    missing = p[p.prediction_failure_reason.ne('')][TASK_KEYS + ['origin', 'target_date', 'prediction_failure_reason']]
    _save_csv(missing, output, 'missing_or_failed_predictions.csv.gz')
    paired = p.groupby(KEYS).agg(expected_condition_rows=('model', 'size'), common_evaluation=('common_evaluation', 'first'),
                                saved_rows=('prediction_row_present', 'sum'), finite_predictions=('finite_prediction', 'sum'),
                                truth_m3=('truth_m3', 'first'), high_threshold_m3=('high_threshold_m3', 'first')).reset_index()
    paired['high_volume'] = paired.truth_m3.ge(paired.high_threshold_m3) & paired.high_threshold_m3.notna()
    _save_csv(paired, output, 'paired_evaluation_index.csv.gz')
    common = p[p.common_evaluation].copy(); frames = []
    for constraint, column in [('raw', 'prediction_m3'), ('all_models_nonnegative', 'prediction_nonnegative_m3')]:
        daily = common[KEYS + ['budget', 'pool_id', 'model', 'k', 'order_label', 'truth_m3', 'high_threshold_m3']].copy()
        error = common[column] - common.truth_m3
        daily['absolute_error'] = error.abs(); daily['squared_error'] = error ** 2
        daily['constraint'] = constraint; daily['evaluation_set'] = 'all_five_used_development'; daily['seed_count'] = 1
        frames.append(daily)
    daily = pd.concat(frames, ignore_index=True); _save_csv(daily, output, 'daily_losses.csv.gz')
    metric = station_metrics(daily, cfg); _save_csv(metric, output, 'metrics_by_station.csv')
    _save_csv(aggregate_station_metrics(metric), output, 'summary.csv')
    episode_metric = station_metrics(daily, cfg, True); _save_csv(episode_metric, output, 'metrics_by_station_window.csv')
    _save_csv(aggregate_station_metrics(episode_metric, True), output, 'summary_by_window.csv')
    high = daily[daily.truth_m3.ge(daily.high_threshold_m3) & daily.high_threshold_m3.notna()]
    high_metric = station_metrics(high, cfg); _save_csv(high_metric, output, 'high_volume_metrics_by_station.csv')
    _save_csv(aggregate_station_metrics(high_metric), output, 'high_volume_summary.csv')
    cis = []; pairs = []; high_cis = []; high_pairs = []
    for constraint in ['raw', 'all_models_nonnegative']:
        ci, pair = paired_block_intervals(daily, cfg, constraint, progress=progress); cis.append(ci); pairs.append(pair)
        ci, pair = paired_block_intervals(daily, cfg, constraint, 'historical_high_volume', progress=progress)
        high_cis.append(ci); high_pairs.append(pair)
    ci = pd.concat(cis, ignore_index=True); pair = pd.concat(pairs, ignore_index=True)
    _save_csv(ci, output, 'paired_block_intervals.csv'); _save_csv(pair, output, 'paired_comparisons_by_station.csv')
    _save_csv(pd.concat(high_cis, ignore_index=True), output, 'high_volume_block_intervals.csv')
    _save_csv(pd.concat(high_pairs, ignore_index=True), output, 'high_volume_paired_by_station.csv')
    _save_csv(pair[pair.kind.eq('history_budget_comparison')], output, 'cross_budget_by_station.csv')
    _save_csv(ci[ci.kind.eq('history_budget_comparison')], output, 'cross_budget_intervals.csv')
    transfer = pair[pair.kind.eq('same_budget_transfer')].groupby(['constraint', 'pool_id', 'model', 'budget', 'horizon', 'reference']).agg(
        stations=('site_id', 'size'), defined_skill_stations=('skill', 'count'), mean_skill_vs_local=('skill', 'mean'),
        median_skill_vs_local=('skill', 'median'), negative_transfer_stations=('negative_transfer', 'sum'),
        winning_stations=('win', 'sum'), tied_stations=('tie', 'sum')).reset_index()
    transfer['negative_transfer_fraction'] = transfer.negative_transfer_stations / transfer.defined_skill_stations.where(transfer.defined_skill_stations.gt(0))
    _save_csv(transfer, output, 'negative_transfer_summary.csv')
    _save_csv(pair[pair.zero_reference_mae], output, 'zero_reference_comparisons.csv')
    # Selection is frozen per initial-history task; never count repeated daily
    # rows as independent parameter choices.
    if 'shrinkage' in p:
        choice_columns = TASK_KEYS + [c for c in ['alpha', 'shrinkage', 'bias_m3', 'training_labels', 'scale_m3', 'fit_end'] if c in p]
        choice = p[choice_columns].drop_duplicates()
        if choice.duplicated(TASK_KEYS).any():
            raise ValueError('Frozen deployment parameters changed within task')
        _save_csv(choice, output, 'parameter_choices.csv')
        selected = choice[choice.model.str.endswith('_selected')]
        fallback = selected.groupby(['pool_id', 'model', 'budget', 'horizon']).agg(
            tasks=('episode', 'size'), selected_lambda_zero=('shrinkage', lambda s: int(s.eq(0).sum())),
            missing_lambda=('shrinkage', lambda s: int(s.isna().sum()))).reset_index()
        fallback['fallback_fraction'] = fallback.selected_lambda_zero / fallback.tasks
        _save_csv(fallback, output, 'lambda_fallback.csv')
        _save_csv(selected.groupby(['pool_id', 'model', 'budget', 'horizon', 'shrinkage'], dropna=False).size().reset_index(name='tasks'), output, 'lambda_distribution.csv')
    missing_rows = int((~p.prediction_row_present).sum())
    unexplained_predictions = int((p.prediction_row_present & p.finite_truth & ~p.finite_prediction).sum())
    # A legal input/label mask can produce a saved NaN forecast (for example
    # weekly persistence on a missing reference day). This is an explicit
    # coverage exclusion, not an unexecuted task. Completion requires all
    # saved rows and independently validated task artifacts, not all targets
    # or lag inputs being observable.
    complete_outputs = missing_rows == 0
    integrity = experiment_integrity or {'status': 'NOT_PROVIDED', 'all_expected_tasks_verified': False}
    experiment_complete = complete_outputs and bool(integrity.get('all_expected_tasks_verified', False))
    write_json(output / 'evaluation_validation.json', dict(
        status='COMPLETED' if experiment_complete else 'PARTIAL', evaluation_outputs_complete=complete_outputs,
        experiment_integrity=integrity, started_from_saved_predictions_only=True, planned_prediction_rows=len(p),
        missing_prediction_rows=missing_rows, nonfinite_predictions_with_valid_truth=unexplained_predictions,
        missing_forecast_interpretation='Saved nonfinite forecasts remain explicit coverage exclusions; execution completion comes from every expected verified task',
        missing_true_targets=int((~p.finite_truth).sum()), common_calendar_groups=int(paired.common_evaluation.sum()),
        planned_calendar_groups=len(paired), seed_aggregation='Deterministic forecasts: no repeated Ridge seeds or prediction ensemble',
        station_aggregation='Five used episodes pooled within SiteID; ratio of per-SiteID MAEs, then equal SiteID mean',
        date_matching='Global common dates across registered source compositions, models, and budgets; complete calendar preserved',
        high_volume='One Q90 from original initial 30-day history per SiteID/episode, consistent across budgets',
        intervals='Noncircular calendar moving blocks within each 60-origin episode, synchronous across sites/methods; whole-SiteID resampling',
        multiplicity='Six B30 primary comparisons: individual confidence 1-0.05/6; all other contrasts exploratory pointwise 95%',
        truth_and_threshold_tolerance={'absolute_m3': 1e-8, 'relative': 1e-12}, tie_skill_tolerance=TIE_TOLERANCE,
        physical_mapping_verified=False, verified_real_time=False, final_2024_2025_performance_used=False,
        statistics_seconds=time.monotonic()-started, finished_utc=utc_now(),
        files_sha256={f.name: sha256(f) for f in sorted(output.iterdir()) if f.is_file() and f.name != 'evaluation_validation.json'}))
    return p, daily, metric, ci
