"""Bounded CPU empirical-interval development with frozen source-only selection."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import resource
import subprocess
import time
import traceback

import numpy as np
import pandas as pd

from .common import sha256, utc_now, write_json
from .shared_data import load_series
from .stage3d_intervals import (calibrate_history, construct_intervals, local_distribution,
    mixture_quantiles, persistence_with_dates, prepare_source_bank)

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'stage3d_interval_v1'
REQUIRED = {'intervals.csv','calibration.csv','diagnostics.json'}


def hash_value(value):
    import hashlib
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def load_config(path):
    cfg = json.loads((ROOT/path).read_text())
    expected = dict(version=VERSION, analysis_unit='station_exploratory', physical_mapping_verified=False,
      verified_real_time=False, qa_mode='published_good_only_retrospective',
      development_ids=['13013','13015','13016','13017','13022','13024','13025','13028','13029','13031'],
      evaluation_origins=['2022-01-01','2022-07-01','2023-01-01','2023-07-01','2023-10-01'],
      budgets=[30,90,180], horizons=[1,3], evaluation_days=60, gammas=[0,.25,.5,.75,1],
      methods=['LOCAL','SHARED','MIXTURE'], nominal_coverages=[.8,.9], min_calibration_scores=14,
      source_training_start='2016-01-01', source_training_end='2021-12-31',
      source_selection_train_end='2020-12-31',source_pseudo_origins=['2021-01-01','2021-07-01'],
      source_pseudo_validation_days=14, all_windows_already_used_development=True)
    for name, value in expected.items():
        if cfg.get(name) != value:
            raise ValueError('Unplanned Stage3D change: '+name)
    freeze = json.loads((ROOT/cfg['frozen_manifest']).read_text())
    for name, expected_sha in freeze['files_sha256'].items():
        if not (ROOT/name).is_file() or sha256(ROOT/name) != expected_sha:
            raise ValueError('Frozen file changed/missing: '+name)
    if freeze['files_sha256'].get(path) != sha256(ROOT/path):
        raise ValueError('Configuration absent from freeze')
    pooldef = json.loads((ROOT/cfg['source_pool_definition']).read_text())
    original = [p for p in pooldef['pools'] if p['k']==30]
    if cfg['pools'] != original or len(original)!=3:
        raise ValueError('Changed C2 K30 compositions')
    sources = {s for p in original for s in p['site_ids']}
    if sources & (set(pooldef['protected_ids']) | set(cfg['development_ids'])):
        raise ValueError('Protected/source/target overlap')
    # Conservatively honour the existing associated-measurement closure.
    for site in sources:
        linked = set(pooldef['source_related_ids'].get(site,[site])) | {site}
        if linked & (set(pooldef['protected_ids']) | set(cfg['development_ids'])):
            raise ValueError('Known associated source crosses target/protection partition')
    signature = hash_value(dict(files=freeze['files_sha256'],numpy=np.__version__,pandas=pd.__version__))
    return cfg, signature, pooldef


def expected_tasks(cfg, mode):
    sites = cfg['smoke_ids'] if mode=='smoke' else cfg['development_ids']
    dates = cfg['evaluation_origins'][:1] if mode=='smoke' else cfg['evaluation_origins']
    return [(str(s),d,b,h) for d in dates for s in sites for b in cfg['budgets'] for h in cfg['horizons']]


def task_key(task):
    s,d,b,h=task
    return f'{s}_{d}_B{b}_H{h}'


def job_fingerprint(signature, task, cfg):
    return hash_value(dict(signature=signature,task=task,pools=[p['pool_id'] for p in cfg['pools']]))


def validate_job(folder, fingerprint, rows):
    folder=Path(folder)
    if not (folder/'status.json').is_file():return False
    status=json.loads((folder/'status.json').read_text())
    if status.get('fingerprint')!=fingerprint:raise ValueError('Job cache fingerprint mismatch: '+str(folder))
    if status.get('status')!='COMPLETED':return False
    hashes=status.get('outputs_sha256',{})
    if not REQUIRED.issubset(hashes) or status.get('prediction_rows')!=rows:
        raise ValueError('Incomplete COMPLETED declaration')
    for name, expected in hashes.items():
        if not (folder/name).is_file() or sha256(folder/name)!=expected:
            raise ValueError('Completed-job output changed/missing: '+name)
    return True


def freeze_gamma(cfg, signature, banks):
    """Persist all legal source choices BEFORE producing target interval rows."""
    hashes={}
    choices={}
    for pool in cfg['pools']:
        folder=ROOT/cfg['source_output']/pool['pool_id']
        state=json.loads((folder/'status.json').read_text())
        if state.get('status')!='COMPLETED':raise ValueError('Source selection incomplete')
        hashes[str((folder/'status.json').relative_to(ROOT))]=sha256(folder/'status.json')
        for name, expected in state['outputs_sha256'].items():
            path=folder/name
            if sha256(path)!=expected:raise ValueError('Source selection output changed')
            hashes[str(path.relative_to(ROOT))]=expected
        choices[pool['pool_id']]={k:float(v) for k,v in banks[pool['pool_id']]['selected_gamma'].items()}
    result=dict(status='FROZEN_SOURCE_ONLY_GAMMA_BEFORE_TARGET_INTERVALS',signature=signature,
        configuration_sha256=sha256(ROOT/f'configs/{VERSION}/full.json'),
        files_sha256=hashes, selected_gamma=choices,
        source_selection_train_end=cfg['source_selection_train_end'],held_year=2021,
        target_deployment_scores_used=False,created_utc=utc_now())
    p=ROOT/cfg['gamma_freeze']
    if p.exists():
        old=json.loads(p.read_text())
        if old['signature']!=signature or old['files_sha256']!=hashes or old['selected_gamma']!=choices:
            raise ValueError('Frozen gamma/cached source checksum mismatch')
    else:
        if list((ROOT/f'runs/{VERSION}').glob('*/jobs/*/intervals.csv')):
            raise ValueError('Cannot retroactively claim gamma frozen before target predictions')
        write_json(p,result)
    return sha256(p)


def run_task(task, cfg, signature, banks, series, common, reference, quality, output):
    site,date,budget,h=task
    folder=output/'jobs'/task_key(task);folder.mkdir(parents=True,exist_ok=True)
    fp=job_fingerprint(signature,task,cfg)
    expected_rows=cfg['evaluation_days']*len(cfg['pools'])*len(cfg['methods'])*len(cfg['nominal_coverages'])
    started=time.perf_counter()
    if validate_job(folder,fp,expected_rows):
        return dict(task=task_key(task),status='CACHED',seconds=time.perf_counter()-started)
    prior=json.loads((folder/'status.json').read_text()) if (folder/'status.json').exists() else {}
    state=dict(status='RUNNING',fingerprint=fp,attempt=prior.get('attempt',0)+1,started_utc=utc_now())
    write_json(folder/'status.json',state)
    try:
        start=pd.Timestamp(date);left=start-pd.Timedelta(days=budget);end=start-pd.Timedelta(days=1)
        cal=calibrate_history(series[site],left,end,h,cfg['min_calibration_scores'])
        cal.frame.to_csv(folder/'calibration.csv',index=False)
        origins=pd.date_range(start,periods=cfg['evaluation_days'])
        # Persistence does not depend on scale; 1 here is solely an unused
        # tensor divisor if the explicit scale eligibility has failed.
        p,input_dates=persistence_with_dates(series[site],origins,h,left,cal.scale if cal.scale else 1.)
        targets=origins+pd.Timedelta(days=h)
        truth=series[site].reindex(targets).to_numpy(float)
        ref=reference[reference.site_id.eq(site)&reference.episode.eq(date)&
                      reference.budget.eq(budget)&reference.horizon.eq(h)].set_index('origin').reindex(origins.strftime('%Y-%m-%d'))
        if len(ref)!=len(origins) or ref.target_date.isna().any():raise ValueError('Missing original C2 Persistence reference')
        if not np.allclose(p,ref.prediction_m3.to_numpy(float),atol=cfg['tolerances']['m3_atol'],
                           rtol=cfg['tolerances']['m3_rtol'],equal_nan=True):
            raise ValueError('Persistence differs from original C2 definition')
        date_keys=[(site,date,h,str(o.date()),str(t.date())) for o,t in zip(origins,targets)]
        c2mask=np.asarray([bool(common.loc[key,'common_evaluation']) for key in date_keys])
        threshold_left=start-pd.Timedelta(days=cfg['high_volume_history_days'])
        threshold_history=series[site].loc[threshold_left:end].dropna()
        threshold=float(threshold_history.quantile(cfg['high_volume_quantile'])) if len(threshold_history)>=14 else np.nan
        local=local_distribution(cal.scores) if cal.valid else None
        rows=[];quantiles={}
        for pool in cfg['pools']:
            bank=banks[pool['pool_id']]
            selected_gamma=float(bank['selected_gamma'][f'B{budget}_H{h}'])
            for method,gamma in [('LOCAL',0.),('SHARED',1.),('MIXTURE',selected_gamma)]:
                q=mixture_quantiles(local,bank['final'][h],gamma,cfg['nominal_coverages']) if cal.valid else {c:np.nan for c in cfg['nominal_coverages']}
                quantiles[pool['pool_id']+'::'+method]={str(c):(float(v) if np.isfinite(v) else None) for c,v in q.items()}
                for coverage in cfg['nominal_coverages']:
                    lower,upper,clipped=construct_intervals(p,cal.scale,q[coverage]) if cal.valid else (np.full(len(p),np.nan),)*3
                    for j,(origin,target) in enumerate(zip(origins,targets)):
                        qkey=(site,str(target.date()))
                        qa=quality.loc[qkey] if qkey in quality.index else None
                        finite=bool(np.isfinite(truth[j]) and np.isfinite(p[j]))
                        eligible=bool(c2mask[j] and cal.valid and finite)
                        exclusion=('calibration_'+str(cal.reason) if not cal.valid else
                            'excluded_by_frozen_C2_common_dates' if not c2mask[j] else
                            'missing_target_or_persistence' if not finite else '')
                        rows.append(dict(run_id=VERSION,site_id=site,episode=date,budget=budget,horizon=h,
                            origin=str(origin.date()),target_date=str(target.date()),pool_id=pool['pool_id'],
                            order_label=pool['order_label'],method=method,nominal_coverage=coverage,
                            truth_m3=float(truth[j]),persistence_m3=float(p[j]),lower_m3=float(lower[j]),
                            upper_m3=float(upper[j]),lower_nonnegative_m3=float(clipped[j]),gamma=gamma,
                            selected_mixture_gamma=selected_gamma,scale_m3=cal.scale,
                            normalized_quantile=q[coverage],calibration_samples=len(cal.scores),
                            calibration_status='VALID' if cal.valid else cal.reason,
                            calibration_start=str(left.date()),calibration_end=str(end.date()),
                            calibration_latest_target=cal.diagnostic['latest_calibration_target'],
                            calibration_latest_input_date=cal.diagnostic['latest_calibration_input'],
                            latest_input_date=str(pd.Timestamp(input_dates[j]).date()) if not pd.isna(input_dates[j]) else None,
                            high_threshold_m3=threshold,threshold_start=str(threshold_left.date()),
                            threshold_end=str(end.date()),threshold_observations=len(threshold_history),
                            quality_flag=qa.quality_flag if qa is not None else 'No_record',
                            target_quality_valid=int(qa.target_quality_valid) if qa is not None else 0,
                            conflict=int(qa.conflict) if qa is not None else 0,
                            evaluation_mask_c2=bool(c2mask[j]),evaluation_mask=eligible,exclusion_reason=exclusion,
                            physical_mapping_verified=False,verified_real_time=False,
                            qa_mode=cfg['qa_mode'],window_class='reused_development'))
        frame=pd.DataFrame(rows)
        assert len(frame)==expected_rows
        assert (pd.to_datetime(frame.target_date)-pd.to_datetime(frame.origin)).dt.days.eq(h).all()
        if not (frame.upper_m3.isna() | frame.lower_m3.le(frame.upper_m3)).all():raise ValueError('Invalid interval order')
        frame.to_csv(folder/'intervals.csv',index=False)
        differences=np.abs(p-ref.prediction_m3.to_numpy(float))
        max_difference=float(np.max(differences[np.isfinite(differences)])) if np.isfinite(differences).any() else None
        diag=dict(cal.diagnostic)
        diag.update(site_id=site,episode=date,budget=budget,horizon=h,
            source_final_end='2021-12-31',source_selection_end='2020-12-31',
            selected_gamma_by_pool={k:float(v['selected_gamma'][f'B{budget}_H{h}']) for k,v in banks.items()},
            quantiles=quantiles,c2_reference_max_absolute_difference_m3=max_difference,
            c2_common_dates=int(c2mask.sum()),valid_evaluation_origins=int(frame.groupby('origin').evaluation_mask.all().sum()),
            parameters_frozen_60origins=True,deployment_error_updates=False,device='cpu')
        write_json(folder/'diagnostics.json',diag)
        state.update(status='COMPLETED',finished_utc=utc_now(),seconds=time.perf_counter()-started,
            prediction_rows=len(frame),calibration_valid=cal.valid,calibration_failure_reason=cal.reason,
            outputs_sha256={n:sha256(folder/n) for n in sorted(REQUIRED)})
        write_json(folder/'status.json',state)
        return dict(task=task_key(task),status='COMPLETED',seconds=state['seconds'],calibration_valid=cal.valid)
    except Exception as exc:
        (folder/f"failure_attempt_{state['attempt']}.txt").write_text(traceback.format_exc())
        state.update(status='FAILED',error=str(exc),finished_utc=utc_now(),seconds=time.perf_counter()-started)
        write_json(folder/'status.json',state)
        return dict(task=task_key(task),status='FAILED',error=str(exc))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',default=f'configs/{VERSION}/full.json')
    ap.add_argument('--mode',choices=['sources','smoke','full','resume'],default='full')
    ap.add_argument('--workers',type=int,default=1)
    ap.add_argument('--max-jobs',type=int)
    a=ap.parse_args()
    if a.workers!=1:raise ValueError('This lightweight deterministic runner uses one CPU worker; pass --workers 1')
    started=time.perf_counter();cfg,signature,pooldef=load_config(a.config)
    data_start=time.perf_counter()
    source_ids=sorted({s for p in cfg['pools'] for s in p['site_ids']})
    series=load_series(ROOT/cfg['canonical_csv'],source_ids+cfg['development_ids'])
    common=pd.read_csv(ROOT/cfg['c2_common_dates'],dtype={'site_id':str}).set_index(['site_id','episode','horizon','origin','target_date'])
    reference=pd.read_csv(ROOT/cfg['c2_persistence_reference'],dtype={'site_id':str})
    quality=pd.read_csv(ROOT/cfg['development_quality'],dtype={'site_id':str}).set_index(['site_id','date'])
    data_seconds=time.perf_counter()-data_start
    banks={};source_start=time.perf_counter()
    for pool in cfg['pools']:
        bank=prepare_source_bank(cfg,series,pool['site_ids'],ROOT/cfg['source_output']/pool['pool_id'],
             related_ids=pooldef['source_related_ids'],signature=signature,pool_id=pool['pool_id'],
             progress=lambda message:print(message,flush=True))
        # Core permits a tuple receipt; avoid inferring an incomplete cache.
        if isinstance(bank,tuple):bank=bank[0]
        banks[pool['pool_id']]=bank
        print('SOURCE_READY '+pool['pool_id'],flush=True)
    source_seconds=time.perf_counter()-source_start
    gamma_sha=freeze_gamma(cfg,signature,banks)
    if a.mode=='sources':
        print(json.dumps(dict(status='SOURCE_SELECTION_COMPLETED',gamma_freeze_sha256=gamma_sha,
                             seconds=time.perf_counter()-started)),flush=True);return
    mode='full' if a.mode=='resume' else a.mode
    if mode=='full':
        gate=ROOT/f'reports/{VERSION}/SMOKE_CHECK.json'
        if not gate.exists() or json.loads(gate.read_text()).get('status')!='PASSED' or json.loads(gate.read_text()).get('signature')!=signature:
            raise ValueError('Full experiment requires the original two-site smoke check')
    output=ROOT/f'runs/{VERSION}/{mode}';output.mkdir(parents=True,exist_ok=True)
    mp=output/'manifest.json'
    if mp.exists() and json.loads(mp.read_text()).get('signature')!=signature:raise ValueError('Output configuration signature mismatch')
    tasks=expected_tasks(cfg,mode);selected=tasks[:a.max_jobs] if a.max_jobs is not None else tasks
    rows_per=cfg['evaluation_days']*len(cfg['pools'])*len(cfg['methods'])*len(cfg['nominal_coverages'])
    manifest=dict(status='RUNNING',signature=signature,mode=mode,config_path=a.config,
        config_sha256=sha256(ROOT/a.config),gamma_freeze_sha256=gamma_sha,expected_conditions=len(tasks),
        expected_prediction_rows=len(tasks)*rows_per,started_utc=utc_now(),device='cpu',workers=1,
        physical_mapping_verified=False,all_windows_used_development=True,
        code_version={'git_head':subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True).stdout.strip()})
    write_json(mp,manifest)
    results=[];target_start=time.perf_counter()
    for task in selected:
        result=run_task(task,cfg,signature,banks,series,common,reference,quality,output)
        results.append(result)
        print(f'{mode} {len(results)}/{len(selected)} '+json.dumps(result),flush=True)
        write_json(output/'progress.json',dict(completed_this_call=len(results),expected=len(tasks),last=result,utc=utc_now()))
    target_seconds=time.perf_counter()-target_start;statuses=[]
    for task in tasks:
        folder=output/'jobs'/task_key(task)
        verified=validate_job(folder,job_fingerprint(signature,task,cfg),rows_per)
        state=json.loads((folder/'status.json').read_text()) if (folder/'status.json').exists() else {'status':'NOT_EXECUTED'}
        statuses.append(dict(task=task_key(task),status=state['status'],validated=verified,
                            calibration_valid=state.get('calibration_valid'),folder=str(folder.relative_to(ROOT))))
    completed=sum(s['validated'] for s in statuses)
    manifest.update(status='COMPLETED' if completed==len(tasks) else 'PARTIAL',completed_conditions=completed,
      failed_conditions=sum(s['status']=='FAILED' for s in statuses),not_completed_conditions=len(tasks)-completed,
      invalid_calibration_conditions=sum(s['validated'] and s['calibration_valid'] is False for s in statuses),
      counts_this_call={s:sum(r['status']==s for r in results) for s in ['COMPLETED','CACHED','FAILED']},
      phase_seconds=dict(data_load=data_seconds,source_calibration_or_cache=source_seconds,target_calibration_or_cache=target_seconds),
      finished_utc=utc_now(),peak_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    write_json(output/'completion.json',statuses);write_json(output/'completion_this_call.json',results)
    if completed==len(tasks):
        aggregate=pd.concat([pd.read_csv(output/'jobs'/s['task']/'intervals.csv',dtype={'site_id':str}) for s in statuses],ignore_index=True)
        assert len(aggregate)==manifest['expected_prediction_rows']
        aggregate.to_csv(output/'predictions_all.csv.gz',index=False,compression={'method':'gzip','mtime':0})
        manifest['predictions_sha256']=sha256(output/'predictions_all.csv.gz')
    manifest['seconds_this_call']=time.perf_counter()-started
    write_json(mp,manifest);print(json.dumps(manifest,indent=2),flush=True)
    if manifest['status']!='COMPLETED':raise SystemExit(3)


if __name__=='__main__':main()
