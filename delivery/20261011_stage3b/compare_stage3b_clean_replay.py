"""Compare independently extracted/recalculated deliverables without model fitting."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path('/workspace/Wastewater_Paper')
EXTRACTED = Path('/tmp/wastewater_stage3b_external_review')
RECALCULATED = EXTRACTED / 'outputs/recomputed_stage3b'
ARCHIVED = EXTRACTED / 'reports/stage3b_20261011_v1/results'
KEYS = ['site_id', 'episode', 'horizon', 'origin', 'target_date']
TASK = ['site_id', 'episode', 'budget', 'horizon', 'model']
KEYSETS = {
    'predictions_all.csv.gz': KEYS + ['budget', 'model'],
    'daily_losses.csv.gz': ['evaluation_set', 'constraint'] + KEYS + ['budget', 'model'],
    'paired_evaluation_index.csv.gz': ['evaluation_set'] + KEYS,
    'availability.csv': ['evaluation_set'] + TASK,
    'missing_or_failed_predictions.csv.gz': ['evaluation_set'] + TASK + ['origin', 'target_date'],
    'metrics_by_station.csv': ['evaluation_set', 'constraint', 'site_id', 'budget', 'horizon', 'model'],
    'high_volume_metrics_by_station.csv': ['evaluation_set', 'constraint', 'site_id', 'budget', 'horizon', 'model'],
    'summary.csv': ['evaluation_set', 'constraint', 'budget', 'horizon', 'model'],
    'high_volume_summary.csv': ['evaluation_set', 'constraint', 'budget', 'horizon', 'model'],
    'paired_comparisons_by_station.csv': ['evaluation_set', 'constraint', 'subset', 'id', 'site_id'],
    'high_volume_paired_by_station.csv': ['evaluation_set', 'constraint', 'subset', 'id', 'site_id'],
    'zero_reference_comparisons.csv': ['evaluation_set', 'constraint', 'subset', 'id', 'site_id'],
    'paired_block_intervals.csv': ['evaluation_set', 'constraint', 'subset', 'id', 'block_days'],
    'high_volume_block_intervals.csv': ['evaluation_set', 'constraint', 'subset', 'id', 'block_days'],
    'negative_transfer_summary.csv': ['evaluation_set', 'constraint', 'model', 'budget', 'horizon', 'reference'],
}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    checks = {}
    files = sorted(f for f in RECALCULATED.iterdir() if f.name.endswith(('.csv', '.csv.gz')))
    if {f.name for f in files} != set(KEYSETS):
        raise AssertionError('Unexpected or missing recalculated CSV tables')
    for current in files:
        saved = ARCHIVED/current.name
        a = pd.read_csv(current, dtype={'site_id': str}, low_memory=False)
        b = pd.read_csv(saved, dtype={'site_id': str}, low_memory=False)
        if list(a.columns) != list(b.columns) or len(a) != len(b):
            raise AssertionError(f'{current.name}: schema or row count mismatch')
        keys = KEYSETS[current.name]
        if a.duplicated(keys).any() or b.duplicated(keys).any():
            raise AssertionError(f'{current.name}: duplicated comparison keys')
        a = a.set_index(keys).sort_index()
        b = b.set_index(keys).sort_index()
        if not a.index.equals(b.index):
            raise AssertionError(f'{current.name}: comparison keys differ')
        columns = {}
        for column in a.columns:
            left, right = a[column], b[column]
            if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
                if not np.array_equal(left.isna(), right.isna()):
                    raise AssertionError(f'{current.name}/{column}: missingness differs')
                av, bv = left.to_numpy(float), right.to_numpy(float)
                skill_column = ('skill' in column or column.startswith(('lower_', 'upper_')))
                atol = 1e-12 if skill_column else 1e-8
                np.testing.assert_allclose(av, bv, atol=atol, rtol=1e-12, equal_nan=True,
                                           err_msg=f'{current.name}/{column}')
                finite = np.isfinite(av) & np.isfinite(bv)
                columns[column] = {'numeric': True, 'atol': atol, 'rtol': 1e-12,
                                   'max_absolute_difference': float(np.max(np.abs(av[finite]-bv[finite]))) if finite.any() else None}
            else:
                if not left.equals(right):
                    raise AssertionError(f'{current.name}/{column}: nonnumeric values differ')
                columns[column] = {'numeric': False, 'identical': True}
        checks[current.name] = {'rows': len(a), 'columns': len(a.columns)+len(keys),
                                'key_fields': keys, 'key_sets_identical': True,
                                'recomputed_sha256': sha(current), 'saved_sha256': sha(saved),
                                'checks': columns}
        print(f'{current.name}: {len(a)} rows compared and passed', flush=True)
    stage3a = json.loads((EXTRACTED/'outputs/recomputed_stage3a/RECALCULATION_STATUS.json').read_text())
    stage3a_rows = {
        'daily_losses': len(pd.read_csv(EXTRACTED/'outputs/recomputed_stage3a/daily_losses_recomputed.csv.gz', usecols=['site_id'])),
        'station_metrics': len(pd.read_csv(EXTRACTED/'outputs/recomputed_stage3a/metrics_by_station_recomputed.csv', usecols=['site_id']))}
    station_keys = ['constraint', 'site_id', 'budget', 'horizon', 'model']
    a3 = pd.read_csv(EXTRACTED/'outputs/recomputed_stage3a/metrics_by_station_recomputed.csv', dtype={'site_id': str}).set_index(station_keys).sort_index()
    b3 = pd.read_csv(EXTRACTED/'reports/stage3a_20261010/results/metrics_by_station.csv', dtype={'site_id': str}).set_index(station_keys).sort_index()
    if not a3.index.equals(b3.index):
        raise AssertionError('Stage3A metric keys differ')
    np.testing.assert_allclose(a3.skill_vs_persistence, b3.skill_vs_persistence,
                               atol=1e-12, rtol=1e-12, equal_nan=True)
    strict_stage3a_skill = {'metric_rows': len(a3), 'atol': 1e-12, 'rtol': 1e-12,
                           'max_absolute_difference': float(np.nanmax(np.abs(a3.skill_vs_persistence-b3.skill_vs_persistence)))}
    natural_missing = pd.read_csv(RECALCULATED/'missing_or_failed_predictions.csv.gz')
    missing_reasons = {str(k): int(v) for k, v in natural_missing.prediction_failure_reason.value_counts(dropna=False).items()}
    independently_checked = json.loads((EXTRACTED/'outputs/STAGE3B_ARITHMETIC_CHECK.json').read_text())
    imported = json.loads((PROJECT/'validation/stage3b_clean_import.log').read_text())
    result = {'status': 'passed', 'completed_utc': datetime.now(timezone.utc).isoformat(),
              'extracted_root': str(EXTRACTED), 'import': imported,
              'stage3a_independent_arithmetic': stage3a, 'stage3a_recomputed_rows': stage3a_rows,
              'stage3a_independent_strict_skill_check': strict_stage3a_skill,
              'stage3b_independent_arithmetic': independently_checked,
              'stage3b_missing_or_unavailable_forecast_reasons': missing_reasons,
              'stage3b_saved_vs_recomputed_tables': checks,
              'all_recomputed_tables_compared': True,
              'numeric_replay_claim': 'Specified tolerance agreement, not bitwise identity.',
              'python_executable': str(PROJECT/'.venv-stage2/bin/python'),
              'pythonpath': str(EXTRACTED/'src'),
              'data_and_source_are_from_extracted_packages': True,
              'original_scientific_outputs_modified': False,
              'scope_excludes': ['Full Stage3A GRU training replay', 'Live Colab/Drive verification',
                                'Fresh Stage3B fitting (root performs separate Code-only smoke)',
                                'Any 2024-2025 prediction-performance computation'],
              'commands_completed_exit_code_0': [
                  'scripts/import_stage3b_delivery.py --destination /tmp/wastewater_stage3b_external_review --sha256sums deliverables/stage3b_20261011_v1/SHA256SUMS deliverables/stage3b_20261011_v1/*.zip',
                  'scripts/recalculate_stage3a_delivery.py --output outputs/recomputed_stage3a',
                  'scripts/summarize_stage3b.py --config configs/stage3b_20261011_v1/full.json --predictions reports/stage3b_20261011_v1/results/predictions_all.csv.gz --output outputs/recomputed_stage3b',
                  'scripts/check_stage3b_results.py --arithmetic-only --output outputs/STAGE3B_ARITHMETIC_CHECK.json']}
    (PROJECT/'validation/STAGE3B_CLEAN_METRIC_REPLAY.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'status': result['status'], 'stage3a_rows': stage3a_rows,
                      'stage3b_tables_compared': len(checks),
                      'receipt': str(PROJECT/'validation/STAGE3B_CLEAN_METRIC_REPLAY.json')}, indent=2))


if __name__ == '__main__':
    main()
