#!/usr/bin/env python3
"""Read-only independent Stage3G risk reconstruction; no scientific imports/fits.

Rebuilds training-side feature transforms, saved logistic probabilities,
source-only operating thresholds, hash ties, and source/target flags. This is
an output audit, not new performance, facility-independence or online evidence.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ['initial_source_target_difference', 'recent_input_missing_fraction',
            'recent_volume_change_normalized']
METHODS = ['logistic', 'random', 'missing_rate', 'prediction_persistence_difference']
ATOL = RTOL = 1e-12
M3_ATOL = 1e-8


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def near(a, b, context):
    if not np.allclose(a, b, atol=ATOL, rtol=RTOL, equal_nan=True):
        raise AssertionError(context)


def event_values(frame):
    replacements = {'True': 1, 'False': 0, 'true': 1, 'false': 0}
    values = frame.large_error_event.map(lambda value: replacements.get(value, value))
    return pd.to_numeric(values, errors='coerce').to_numpy(float)


def equal_weights(frame):
    counts = frame.groupby(['site_id', 'episode']).size()
    windows = counts.groupby(level=0).size()
    weights = np.array([1/(len(windows)*windows[s]*counts[s, e])
        for s, e in frame[['site_id', 'episode']].itertuples(index=False, name=None)])
    return weights/weights.sum()


def hash_uniform(key, salt='risk-random'):
    value = hashlib.sha256(f'Wessex-G|20261014|{salt}|{key}'.encode()).digest()
    return int.from_bytes(value[:8], 'big')/float(2**64)


def reconstruct_scores(model, frame):
    x = frame[FEATURES].to_numpy(float)
    x = np.where(np.isfinite(x), x, model['medians'])
    x = (x-np.asarray(model['means']))/np.asarray(model['standard_deviations'])
    if model['status'] == 'NO_TRAINING_LABELS':
        logistic = np.full(len(frame), np.nan)
    elif model['constant_probability'] is not None:
        logistic = np.full(len(frame), model['constant_probability'])
    else:
        z = x@np.asarray(model['coefficients'])+model['intercept']
        logistic = np.empty(len(z)); positive = z >= 0
        logistic[positive] = 1/(1+np.exp(-z[positive]))
        e = np.exp(z[~positive]); logistic[~positive] = e/(1+e)
    keys = frame['row_key'] if 'row_key' in frame else frame['risk_row_key']
    difference = np.abs(frame.prediction_m3-frame.persistence_m3)/frame.scale_m3
    difference = np.where(np.isfinite(frame.scale_m3)&(frame.scale_m3 > 0), difference, np.nan)
    return dict(logistic=logistic, random=np.array([hash_uniform(k) for k in keys]),
        missing_rate=frame.recent_input_missing_fraction.to_numpy(float),
        prediction_persistence_difference=difference)


def verify_training_transform(model, frame):
    event = event_values(frame); valid = np.isfinite(event)&np.isin(event, [0, 1])
    train = frame.loc[valid]
    diagnostic = model['diagnostics']
    if sorted(train.site_id.unique()) != diagnostic['training_sites']:
        raise AssertionError('Risk transform/model training-site registry differs')
    if len(train) != diagnostic['eligible_train_rows'] or int(event[valid].sum()) != diagnostic['event_count']:
        raise AssertionError('Risk training label/event count differs')
    if not len(train):
        if model['status'] != 'NO_TRAINING_LABELS':
            raise AssertionError('No-label status differs')
        return
    x = train[FEATURES].to_numpy(float)
    medians = np.array([np.median(x[np.isfinite(x[:, j]), j])
        if np.isfinite(x[:, j]).any() else 0. for j in range(3)])
    near(medians, model['medians'], 'Training-only imputation medians differ')
    x = np.where(np.isfinite(x), x, medians)
    weights = equal_weights(train)
    means = np.average(x, axis=0, weights=weights)
    std = np.sqrt(np.average((x-means)**2, axis=0, weights=weights))
    constant = np.ptp(x, axis=0) == 0
    means[constant] = x[0, constant]; std[constant] = 1.
    std[std == 0] = 1.
    near(means, model['means'], 'Training-only feature means differ')
    near(std, model['standard_deviations'], 'Training-only feature deviations differ')


def threshold(values, frame, fraction):
    weights = equal_weights(frame); values = np.asarray(values, float)
    good = np.isfinite(values)&np.isfinite(weights)&(weights > 0)
    if not good.any():
        return dict(status='NO_CALIBRATION_SCORES', score_threshold=None, tie_fraction=None,
            expected_mark_fraction=fraction, calibration_scores=0)
    v, w = values[good], weights[good]; w = w/w.sum()
    order = np.argsort(v, kind='stable'); cumulative = np.cumsum(w[order])/w.sum()
    q = v[order[min(np.searchsorted(cumulative, 1-fraction, side='left'), len(v)-1)]]
    above, equal = w[v > q].sum(), w[v == q].sum()
    tie = min(1., max(0., (fraction-above)/equal))
    return dict(status='CALIBRATED', score_threshold=float(q), tie_fraction=float(tie),
        expected_mark_fraction=fraction, calibration_scores=int(good.sum()))


def verify_threshold(actual, expected, context):
    if actual['status'] != expected['status'] or int(actual['calibration_scores']) != expected['calibration_scores']:
        raise AssertionError(context+' status/count differs')
    for key in ['score_threshold', 'tie_fraction', 'expected_mark_fraction']:
        if expected[key] is None:
            if pd.notna(actual[key]): raise AssertionError(context+' undefined value differs')
        else:
            near(actual[key], expected[key], context+' '+key)


def verify_flags(frame, t, method, percentage):
    values = frame.risk_score.to_numpy(float); expected = np.full(len(frame), np.nan)
    if t['status'] == 'CALIBRATED':
        valid = np.isfinite(values)&np.isfinite(frame.prediction_m3)
        expected[valid] = (values[valid] > t['score_threshold']).astype(float)
        tied = valid&(values == t['score_threshold'])
        salt = f"risk-tie-{method}-{t['expected_mark_fraction']}"
        expected[tied] = [hash_uniform(k, salt) < t['tie_fraction'] for k in frame.loc[tied, 'risk_row_key']]
    if not np.array_equal(expected, frame[f'review_{percentage}pct'].to_numpy(float), equal_nan=True):
        raise AssertionError('Saved operating flags differ: '+method+f'/{percentage}')


def verify_row_truth_and_dates(frame):
    if (pd.to_datetime(frame.target_date)-pd.to_datetime(frame.origin)).dt.days.ne(frame.horizon).any():
        raise AssertionError('Risk target dates are not origin+h')
    if pd.to_datetime(frame.risk_recent_input_end).gt(pd.to_datetime(frame.origin)).any():
        raise AssertionError('Future recent risk input')
    if pd.to_datetime(frame.risk_static_information_cutoff_date).ge(pd.to_datetime(frame.episode)).any():
        raise AssertionError('Static risk calibration crosses deployment boundary')
    error = np.abs(frame.prediction_m3-frame.truth_m3)
    if not np.allclose(error, frame.absolute_error_m3, atol=M3_ATOL, rtol=RTOL, equal_nan=True):
        raise AssertionError('Risk absolute error differs from unchanged point prediction')
    e = event_values(frame); valid = np.isfinite(error)&np.isfinite(frame.large_error_threshold_m3)
    near(e[valid], (error[valid] > frame.loc[valid, 'large_error_threshold_m3']).astype(float), 'Large-error event formula differs')
    if frame.point_prediction_modified.any():
        raise AssertionError('Risk module changed point predictions')


def check_receipt(folder, evidence):
    receipt = json.loads((folder/'RUN_STATUS.json').read_text())
    if receipt['status'] != 'COMPLETED':
        raise AssertionError('Risk disk evidence is not COMPLETED')
    evidence[str((folder/'RUN_STATUS.json').relative_to(ROOT))] = sha(folder/'RUN_STATUS.json')
    for name, expected in receipt['members'].items():
        path = folder/name
        if sha(path) != expected: raise AssertionError('Risk member SHA differs: '+name)
        evidence[str(path.relative_to(ROOT))] = expected
    return receipt


def audit(cfg, scope):
    evidence = {}; source = ROOT/cfg['source_output']; risk = source/'reliability'
    receipt = check_receipt(risk, evidence)
    scored = pd.read_csv(risk/'source_risk_crossfit_scores.csv.gz', dtype={'site_id':str,'group_id':str}, float_precision='round_trip')
    thresholds = pd.read_csv(risk/'source_operating_thresholds.csv.gz', dtype={'outer_fold':str}, float_precision='round_trip')
    diagnostics = json.loads((risk/'risk_model_diagnostics.json').read_text())
    models = {(d['pool_id'], d['budget'], d['horizon'], str(d['outer_fold'])): d for d in diagnostics}
    bundle = json.loads((risk/'final_risk_bundle.json').read_text())
    if len(scored) != receipt['row_counts']['source_risk_crossfit_scores.csv.gz']:
        raise AssertionError('Source risk cardinality differs')
    counts = dict(source_scored_rows=len(scored), source_models_checked=0,
        source_thresholds_checked=0, target_scored_rows=0, target_conditions_checked=0)
    verify_row_truth_and_dates(scored)
    for pool in cfg['pools']:
        path = source/pool['pool_id']/'strict_reliability_base_predictions.csv.gz'
        base = pd.read_csv(path, dtype={'site_id':str,'group_id':str}, float_precision='round_trip')
        evidence[str(path.relative_to(ROOT))] = sha(path)
        for (budget, horizon, fold), condition in base.groupby(['budget','horizon','outer_fold']):
            model = models[pool['pool_id'], int(budget), int(horizon), str(fold)]
            train = condition[condition.role.eq('risk_train')]
            calibration = condition[condition.role.eq('threshold_calibration')]
            evaluation = condition[condition.role.eq('outer_evaluation')]
            role_sets = [set(frame.group_id) for frame in [train, calibration, evaluation]]
            if any(role_sets[i]&role_sets[j] for i in range(3) for j in range(i)):
                raise AssertionError('Source downstream reliability roles overlap')
            verify_training_transform(model, train); counts['source_models_checked'] += 1
            score_predictions = reconstruct_scores(model, evaluation)
            calibration_scores = reconstruct_scores(model, calibration)
            rows = scored[scored.pool_id.eq(pool['pool_id'])&scored.budget.eq(budget)&scored.horizon.eq(horizon)&scored.outer_fold.eq(fold)]
            for method in METHODS:
                table = rows[rows.risk_method.eq(method)].set_index('row_key').reindex(evaluation.row_key).reset_index()
                near(table.risk_score, score_predictions[method], 'Source group-OOF risk probability differs')
                for percentage in [10,20]:
                    actual = thresholds[thresholds.pool_id.eq(pool['pool_id'])&thresholds.budget.eq(budget)&thresholds.horizon.eq(horizon)&thresholds.outer_fold.eq(str(fold))&thresholds.risk_method.eq(method)&thresholds.operating_fraction.eq(f'{percentage}pct')]
                    if len(actual) != 1: raise AssertionError('Missing outer operating threshold')
                    actual = actual.iloc[0].to_dict()
                    verify_threshold(actual, threshold(calibration_scores[method], calibration, percentage/100), 'Disjoint source threshold')
                    verify_flags(table, actual, method, percentage); counts['source_thresholds_checked'] += 1
        for (budget, horizon), condition in base[base.role.eq('outer_evaluation')].groupby(['budget','horizon']):
            key = f"{pool['pool_id']}|B{int(budget)}|h{int(horizon)}"; entry = bundle[key]
            verify_training_transform(entry['model'], condition); counts['source_models_checked'] += 1
            rows = scored[scored.pool_id.eq(pool['pool_id'])&scored.budget.eq(budget)&scored.horizon.eq(horizon)]
            for method in METHODS:
                table = rows[rows.risk_method.eq(method)]
                for percentage in [10,20]:
                    actual = entry['thresholds'][method][f'{percentage}pct']
                    verify_threshold(actual, threshold(table.risk_score, table, percentage/100), 'Final threshold from source risk-OOF')
                    if actual['source'] != 'source_outer_crossfit_OOS': raise AssertionError('Final threshold used fitted risk scores')
                    counts['source_thresholds_checked'] += 1
    if scope != 'source':
        run = ROOT/cfg['output']
        if scope == 'smoke': run = run.parent/'smoke'
        target_folder = run/'reliability'; target_receipt = check_receipt(target_folder, evidence)
        target = pd.read_csv(target_folder/'target_risk_predictions.csv.gz', dtype={'site_id':str}, float_precision='round_trip')
        if len(target) != target_receipt['row_counts']['target_risk_predictions.csv.gz']:
            raise AssertionError('Target risk cardinality differs')
        verify_row_truth_and_dates(target); counts['target_scored_rows'] = len(target)
        for (pool, budget, horizon), rows in target.groupby(['pool_id','budget','horizon']):
            entry = bundle[f'{pool}|B{int(budget)}|h{int(horizon)}']
            for method in METHODS:
                table = rows[rows.risk_method.eq(method)]
                near(table.risk_score, reconstruct_scores(entry['model'], table)[method], 'Frozen source-model target risk score differs')
                for percentage in [10,20]:
                    verify_flags(table, entry['thresholds'][method][f'{percentage}pct'], method, percentage)
            counts['target_conditions_checked'] += 1
    return dict(status='PASSED', scope=scope, finished_utc=datetime.now(timezone.utc).isoformat(),
        counts=counts, files_sha256=evidence,
        tolerance=dict(dimensionless_absolute=ATOL,relative=RTOL,original_volume_absolute_m3=M3_ATOL),
        score_reconstruction='numpy only; saved coefficients, training transforms and sigmoid, no sklearn or Stage3G imports',
        flags='Exact saved flags using source-calibrated thresholds and truth-independent SHA tie handling',
        limitations=['No new model fit or predictive performance proof',
            'Source upstream base/group isolation is additionally checked by check_stage3g_results.py',
            'No independent physical-facility certification or real-time QA validation'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='configs/stage3g_transfer_reliability_v1/full.json')
    parser.add_argument('--scope',choices=['source','smoke','full'],default='full')
    args = parser.parse_args(); cfg = json.loads((ROOT/args.config).read_text())
    result = audit(cfg, args.scope); result['audit_script_sha256'] = sha(Path(__file__))
    folder = ROOT/'reports'/cfg['version']/'audit'; folder.mkdir(parents=True,exist_ok=True)
    target = folder/f'INDEPENDENT_RISK_CHECK_{args.scope.upper()}.json'
    content = (json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    fd, name = tempfile.mkstemp(prefix='.risk-audit-', dir=folder)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.replace(name,target)
    finally:
        if os.path.exists(name): os.unlink(name)
    print(json.dumps(dict(status=result['status'],scope=args.scope,counts=result['counts'],report=str(target)),ensure_ascii=False))


if __name__ == '__main__': main()
