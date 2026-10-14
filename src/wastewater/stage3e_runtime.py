"""Stage3E persistence guards around the unchanged, frozen Stage3D science.

Single-process adapter only. It recalculates at most the original 12 smoke
calibrations; it never fits a forecasting model or changes gamma/source banks.
A function return is not a completion certificate: on-disk rows, boundaries,
fingerprint, hashes and a durable completion receipt must independently pass.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import traceback
from unittest.mock import patch

import numpy as np
import pandas as pd

from .common import sha256, utc_now
from . import stage3d_experiment as science
from .stage3d_intervals import load_source_bank
from .shared_data import load_series

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'stage3e_evidence_review_v1'
MAX_ATTEMPTS = 2
REQUIRED = tuple(sorted(science.REQUIRED))


class FingerprintMismatch(ValueError):
    """Never repair a different experiment in-place."""


def _directory_fsync(directory):
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
    descriptor = os.open(str(directory), flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_bytes(path, content, fault=None):
    """Same-directory temp -> flush/fsync -> replace -> directory fsync -> read.

    A fault callback is only for controlled tests. The caller receives success
    only after exact SHA readback. Atomic replacement is a per-file guarantee,
    not a transaction over three scientific files; the completion receipt is
    the transaction commit. A post-replace failure remains uncommitted.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix='.'+path.name+'.', suffix='.tmp', dir=path.parent)
    temporary = Path(temporary_name)
    digest = hashlib.sha256(content).hexdigest()
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if fault:
            fault('before_replace', path)
        os.replace(temporary, path)
        _directory_fsync(path.parent)
        if fault:
            fault('after_replace', path)
        if sha256(path) != digest:
            raise IOError('Atomic write readback SHA mismatch: '+str(path))
        if fault:
            fault('after_verified', path)
        return digest
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_json(path, value, fault=None):
    content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()
    return atomic_bytes(path, content, fault)


def append_event(path, event):
    """Append-only fsynced recovery/failure journal; never erase past failures."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('ab') as handle:
        handle.write((json.dumps(dict(utc=utc_now(), **event), sort_keys=True, allow_nan=False)+'\n').encode())
        handle.flush()
        os.fsync(handle.fileno())
    _directory_fsync(path.parent)


@contextmanager
def atomic_science_writes(output, injected_status_fault=None):
    """Process-local, sequential adapter; original science file bytes unchanged.

    Restrict patched writes to this NEW output tree. CSV uses the identical
    pandas serialization into a text buffer, then atomic byte persistence.
    """
    output = Path(output).resolve()
    original_csv = pd.DataFrame.to_csv
    original_json = science.write_json

    def guarded_json(path, value):
        path = Path(path)
        if not path.resolve().is_relative_to(output):
            return original_json(path, value)
        if injected_status_fault and path.name == 'status.json' and value.get('status') == 'COMPLETED':
            injected_status_fault(path, value)
        return atomic_json(path, value)

    def guarded_csv(frame, destination=None, *args, **kwargs):
        if destination is None or not isinstance(destination, (str, os.PathLike)):
            return original_csv(frame, destination, *args, **kwargs)
        path = Path(destination)
        if not path.resolve().is_relative_to(output):
            return original_csv(frame, destination, *args, **kwargs)
        if kwargs.get('compression') or path.suffix != '.csv':
            raise ValueError('This adapter only guards the original uncompressed task CSVs')
        buffer = io.StringIO(newline='')
        original_csv(frame, buffer, *args, **kwargs)
        atomic_bytes(path, buffer.getvalue().encode(kwargs.get('encoding') or 'utf-8'))
        return None

    with patch.object(science, 'write_json', guarded_json), patch.object(pd.DataFrame, 'to_csv', guarded_csv):
        yield


def verify_outputs(folder, fingerprint, task, cfg, require_runtime=False, runtime_signature=None):
    """Independently validate actual bytes and rows, not return flags alone."""
    folder = Path(folder)
    state_path = folder/'status.json'
    if not state_path.is_file():
        return dict(valid=False, reason='MISSING_STATUS')
    try:
        state = json.loads(state_path.read_text())
    except (ValueError, UnicodeError) as exc:
        return dict(valid=False, reason='UNREADABLE_STATUS', error=str(exc))
    if state.get('fingerprint') != fingerprint:
        raise FingerprintMismatch('Job fingerprint mismatch: '+str(folder))
    if state.get('status') != 'COMPLETED':
        return dict(valid=False, reason='STATUS_'+str(state.get('status')))
    rows = cfg['evaluation_days']*len(cfg['pools'])*len(cfg['methods'])*len(cfg['nominal_coverages'])
    hashes = state.get('outputs_sha256', {})
    if set(hashes) != set(REQUIRED) or state.get('prediction_rows') != rows:
        return dict(valid=False, reason='INCOMPLETE_COMPLETION_RECEIPT')
    for member in REQUIRED:
        if not (folder/member).is_file():
            return dict(valid=False, reason='MISSING_OUTPUT', member=member)
        if sha256(folder/member) != hashes[member]:
            return dict(valid=False, reason='OUTPUT_SHA_MISMATCH', member=member)
    try:
        frame = pd.read_csv(folder/'intervals.csv', dtype={'site_id':str})
        cal = pd.read_csv(folder/'calibration.csv')
        diag = json.loads((folder/'diagnostics.json').read_text())
        site, date, budget, horizon = task
        start = pd.Timestamp(date); left = start-pd.Timedelta(days=budget); cutoff = start-pd.Timedelta(days=1)
        if len(frame) != rows or len(cal) != budget-horizon:
            raise ValueError('Actual CSV row count differs from planned calendar rows')
        for name, value in [('site_id',str(site)),('episode',date),('budget',budget),('horizon',horizon)]:
            if not frame[name].eq(value).all():
                raise ValueError('Actual CSV task field mismatch: '+name)
        origins = pd.to_datetime(frame.origin); targets = pd.to_datetime(frame.target_date)
        if origins.min() != start or origins.max() != start+pd.Timedelta(days=cfg['evaluation_days']-1):
            raise ValueError('Wrong deployment calendar endpoints')
        if not (targets-origins).dt.days.eq(horizon).all():
            raise ValueError('Wrong day-h target definition')
        keys = ['origin','pool_id','method','nominal_coverage']
        if frame.duplicated(keys).any() or origins.nunique() != cfg['evaluation_days']:
            raise ValueError('Missing/duplicate planned forecast rows')
        if set(frame.pool_id) != {p['pool_id'] for p in cfg['pools']} or set(frame.method) != set(cfg['methods']) or set(frame.nominal_coverage) != set(cfg['nominal_coverages']):
            raise ValueError('Wrong policy set')
        cal_origins=pd.to_datetime(cal.origin);cal_targets=pd.to_datetime(cal.target_date);inputs=pd.to_datetime(cal.latest_input_date)
        if cal_origins.min() < left or cal_targets.max() > cutoff or not (cal_targets-cal_origins).dt.days.eq(horizon).all():
            raise ValueError('Calibration label/history boundary violation')
        if ((inputs>cal_origins) | (inputs<left)).any():
            raise ValueError('Calibration input boundary violation')
        if diag['calendar_history_days'] != budget or diag['horizon'] != horizon or diag['calibration_samples'] != int(cal.valid_score.sum()):
            raise ValueError('Diagnostics/calendar/calibration count inconsistency')
        if state['calibration_valid'] != diag['valid']:
            raise ValueError('Calibration eligibility mismatch')
        if diag['valid'] and (not np.isfinite(diag['scale_m3']) or diag['scale_m3'] <= 0 or int(cal.valid_score.sum()) < cfg['min_calibration_scores']):
            raise ValueError('Invalid scale or insufficient scores wrongly eligible')
        if require_runtime:
            receipt_path = folder/'runtime_status.json'
            if not receipt_path.is_file():
                return dict(valid=False, reason='MISSING_RUNTIME_RECEIPT')
            receipt = json.loads(receipt_path.read_text())
            if receipt.get('runtime_signature') != runtime_signature:
                raise FingerprintMismatch('Stage3E runtime fingerprint mismatch')
            if receipt.get('status') != 'COMPLETED' or receipt.get('outputs_sha256') != hashes or receipt.get('scientific_status_sha256') != sha256(state_path):
                return dict(valid=False, reason='INVALID_RUNTIME_RECEIPT')
    except FingerprintMismatch:
        raise
    except Exception as exc:
        return dict(valid=False, reason='OUTPUT_CONTENT_INVALID', error=str(exc))
    return dict(valid=True, reason='VERIFIED_DISK_EVIDENCE', actual_rows=len(frame),
                calibration_rows=len(cal), calibration_valid=bool(diag['valid']),
                outputs_sha256=hashes, scientific_status_sha256=sha256(state_path))


def _snapshot_recovery(folder, output, task, attempt):
    destination = Path(output)/'recovery_evidence'/science.task_key(task)/f'attempt_{attempt:02d}_{time.time_ns()}'
    if folder.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(folder, destination)
    return str(destination)


def run_reliably(task, cfg, signature, runtime_signature, output, execute, max_attempts=MAX_ATTEMPTS):
    """A bounded recovery. Different fingerprints always abort, never overwrite."""
    if max_attempts < 1 or max_attempts > MAX_ATTEMPTS:
        raise ValueError('Recovery attempt bound must be in [1,2]')
    output = Path(output); folder=output/'jobs'/science.task_key(task)
    fp = science.job_fingerprint(signature, task, cfg)
    existing = verify_outputs(folder, fp, task, cfg, True, runtime_signature)
    if existing['valid']:
        return dict(task=science.task_key(task), status='CACHED_VERIFIED', function_returns=[],
                    function_return_success_count=0, disk_verified_completed=True, attempts=0, evidence=existing)
    returns=[]; failures=[]
    for attempt in range(1, max_attempts+1):
        before=verify_outputs(folder,fp,task,cfg)
        if folder.exists() and not before['valid']:
            archived=_snapshot_recovery(folder,output,task,attempt)
            append_event(output/'failure_events.jsonl',dict(task=science.task_key(task),event='RECOVERY_REQUIRED',attempt=attempt,evidence=before,archived=archived))
            # The new Stage3E tree is disposable and the prior bytes are saved.
            # A corrupt original Stage3D experiment is NEVER modified here.
            shutil.rmtree(folder)
        try:
            result = execute()
            returns.append(result)
            evidence=verify_outputs(folder,fp,task,cfg)
            if not evidence['valid']:
                raise IOError('Function returned '+str(result.get('status'))+' but disk verification failed: '+json.dumps(evidence))
            receipt=dict(status='COMPLETED',version=VERSION,runtime_signature=runtime_signature,
                scientific_fingerprint=fp,scientific_status_sha256=evidence['scientific_status_sha256'],
                outputs_sha256=evidence['outputs_sha256'],prediction_rows=evidence['actual_rows'],
                completed_utc=utc_now(),attempt_this_call=attempt,
                scientific_method_changed=False,function_return_status=result.get('status'))
            atomic_json(folder/'runtime_status.json',receipt)
            final=verify_outputs(folder,fp,task,cfg,True,runtime_signature)
            if not final['valid']:
                raise IOError('Runtime completion readback failed')
            return dict(task=science.task_key(task),status='COMPLETED_VERIFIED',function_returns=returns,
                function_return_success_count=sum(r.get('status') in ('COMPLETED','CACHED') for r in returns),
                disk_verified_completed=True,attempts=attempt,failures=failures,evidence=final)
        except FingerprintMismatch:
            raise
        except Exception as exc:
            failure=dict(task=science.task_key(task),event='ATTEMPT_FAILED',attempt=attempt,error=str(exc),traceback=traceback.format_exc())
            failures.append(failure)
            append_event(output/'failure_events.jsonl',failure)
    atomic_json(folder/'runtime_status.json',dict(status='FAILED',version=VERSION,
        runtime_signature=runtime_signature,completed=False,attempts=max_attempts,failures=failures))
    return dict(task=science.task_key(task),status='FAILED_VERIFICATION',function_returns=returns,
        function_return_success_count=sum(r.get('status') in ('COMPLETED','CACHED') for r in returns),
        disk_verified_completed=False,attempts=max_attempts,failures=failures)


def collect_manifest(tasks, cfg, signature, runtime_signature, output, results):
    """Disk-certified count is authoritative even if every function succeeded."""
    statuses=[]
    for task in tasks:
        evidence=verify_outputs(Path(output)/'jobs'/science.task_key(task),science.job_fingerprint(signature,task,cfg),task,cfg,True,runtime_signature)
        statuses.append(dict(task=science.task_key(task), **evidence))
    completed=sum(x['valid'] for x in statuses)
    return dict(version=VERSION,status='COMPLETED' if completed == len(tasks) else 'PARTIAL',
        expected_tasks=len(tasks),disk_verified_completed=completed,not_completed=len(tasks)-completed,
        function_return_success_count_this_call=sum(r['function_return_success_count'] for r in results),
        cached_verified_this_call=sum(r['status']=='CACHED_VERIFIED' for r in results),
        repaired_or_recalculated_this_call=sum(r['status']=='COMPLETED_VERIFIED' for r in results),
        failed_this_call=sum(not r['disk_verified_completed'] for r in results),
        completion_basis='on-disk fingerprints + required files + actual rows + hashes + durable receipt',
        tasks=statuses,max_attempts_per_call=MAX_ATTEMPTS,generated_utc=utc_now())


def load_science_inputs(config_path):
    cfg,signature,pooldef=science.load_config(config_path)
    ids=sorted({s for p in cfg['pools'] for s in p['site_ids']})
    series=load_series(ROOT/cfg['canonical_csv'],ids+cfg['development_ids'])
    banks={p['pool_id']:load_source_bank(ROOT/cfg['source_output']/p['pool_id'],cfg,p['site_ids']) for p in cfg['pools']}
    common=pd.read_csv(ROOT/cfg['c2_common_dates'],dtype={'site_id':str}).set_index(['site_id','episode','horizon','origin','target_date'])
    reference=pd.read_csv(ROOT/cfg['c2_persistence_reference'],dtype={'site_id':str})
    quality=pd.read_csv(ROOT/cfg['development_quality'],dtype={'site_id':str}).set_index(['site_id','date'])
    return cfg,signature,banks,series,common,reference,quality


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--science-config',default='configs/stage3d_interval_v1/full.json')
    ap.add_argument('--output',default=f'runs/{VERSION}/runtime/smoke')
    ap.add_argument('--mode',choices=['smoke','resume'],default='smoke')
    ap.add_argument('--max-jobs',type=int)
    a=ap.parse_args(); started=time.perf_counter()
    output=ROOT/a.output
    if not output.resolve().is_relative_to((ROOT/f'runs/{VERSION}').resolve()):
        raise ValueError('Stage3E runtime writes must remain in its NEW run tree')
    cfg,signature,banks,series,common,reference,quality=load_science_inputs(a.science_config)
    runtime_signature=science.hash_value(dict(version=VERSION,science_signature=signature,
        runtime_code_sha256=sha256(Path(__file__)),max_attempts=MAX_ATTEMPTS))
    tasks=science.expected_tasks(cfg,'smoke'); selected=tasks[:a.max_jobs] if a.max_jobs is not None else tasks
    results=[]
    for task in selected:
        def execute(task=task):
            with atomic_science_writes(output):
                return science.run_task(task,cfg,signature,banks,series,common,reference,quality,output)
        result=run_reliably(task,cfg,signature,runtime_signature,output,execute)
        results.append(result)
        progress=dict(step=len(results),selected=len(selected),expected=len(tasks),task=result['task'],status=result['status'],utc=utc_now())
        atomic_json(output/'progress.json',progress)
        print(json.dumps(progress),flush=True)
    manifest=collect_manifest(tasks,cfg,signature,runtime_signature,output,results)
    manifest.update(seconds_this_call=time.perf_counter()-started,science_config_sha256=sha256(ROOT/a.science_config),
        science_signature=signature,runtime_signature=runtime_signature,
        original_natural_anomaly='NOT_REPRODUCED; root cause unconfirmed',
        work_kind='12 historical calibration reconstructions; no new predictive model/source selection')
    atomic_json(output/'manifest.json',manifest);atomic_json(output/'completion_this_call.json',results)
    print(json.dumps({k:v for k,v in manifest.items() if k!='tasks'},indent=2),flush=True)
    if manifest['status'] != 'COMPLETED':
        raise SystemExit(3)


if __name__=='__main__':
    main()
