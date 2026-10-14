"""Frozen Stage3G source-weighted residual Ridge development runner, CPU only."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
from importlib import metadata
import json
from pathlib import Path
import resource
import time
import traceback
import numpy as np
import pandas as pd
from .common import sha256,utc_now
from .shared_data import load_series
from .stage3e_runtime import atomic_bytes,atomic_json,append_event,FingerprintMismatch
from . import stage3g_core as core
from .stage3g_source import (LOCAL_DIRECT,LOCAL_RESIDUAL,UNIFORM,UNIFORM_BIAS,WEIGHTED,WEIGHTED_BIAS,
    FAMILIES,digest,atomic_csv,stats_for,descriptors_for,weights_for,choose,prepare_source_pool,validate_cache)

ROOT=Path(__file__).resolve().parents[2]
VERSION='stage3g_transfer_reliability_v1'
MODELS=('persistence','weekly_persistence',*FAMILIES)
REQUIRED={'predictions.csv','risk_inputs.csv','source_weights.csv','selection.json','validation_grid.csv',
          'diagnostics.json','model_parameters.npz'}


def load_config(path):
    path=ROOT/path if not Path(path).is_absolute() else Path(path)
    cfg=json.loads(path.read_text())
    if cfg['version']!=VERSION or cfg['physical_mapping_verified'] or cfg['verified_real_time']:
        raise ValueError('Unverified SiteID retrospective experiment only')
    expected={'development_ids':['13013','13015','13016','13017','13022','13024','13025','13028','13029','13031'],
      'evaluation_origins':['2022-01-01','2022-07-01','2023-01-01','2023-07-01','2023-10-01'],
      'evaluation_days':60,'budgets':[30,90,180],'horizons':[1,3],
      'ridge_alphas':[.0001,.001,.01,.1,1.,10.],'lambdas':[0,.25,.5,1],'etas':[0,.5,.9],
      'source_training_start':'2016-01-01','source_training_end':'2021-12-31',
      'source_selection_train_end':'2020-12-31','source_pseudo_origins':['2021-01-01','2021-07-01'],
      'source_pseudo_validation_days':14,'qa_mode':'published_good_only_retrospective'}
    for key,value in expected.items():
        if cfg.get(key)!=value:raise ValueError('Frozen experiment setting differs: '+key)
    freeze_path=ROOT/cfg['frozen_manifest'];freeze=json.loads(freeze_path.read_text())
    for filename,expected_sha in freeze['files_sha256'].items():
        if not(ROOT/filename).is_file() or sha256(ROOT/filename)!=expected_sha:
            raise ValueError('Frozen file mismatch: '+filename)
    actual_packages={name:metadata.version(name) for name in ('numpy','pandas','scikit-learn','scipy')}
    if cfg.get('runtime_packages')!=actual_packages:
        raise ValueError('Runtime scientific package versions differ from frozen configuration: '+repr(actual_packages))
    signature=digest(dict(files_sha256=freeze['files_sha256'],runtime_packages=actual_packages))
    return cfg,signature


def group_mapping(cfg):
    if cfg.get('source_groups'):return {str(k):str(v) for k,v in cfg['source_groups'].items()}
    rows=pd.read_csv(ROOT/cfg.get('partition_group_ledger','data/provenance/stage3c2_source_scale_v1/partition_group_ledger.csv'),dtype=str)
    groups={}
    for row in rows.itertuples():
        for site in str(row.all_pre2022_related_siteids).split('|'):
            if site and site!='nan':groups[site]=row.provisional_group_id
    return groups


def task_key(task):
    s,t,b,h=task;return f'{s}_{t}_B{b}_H{h}'


def expected_tasks(cfg,mode):
    sites=cfg['smoke_ids'] if mode=='smoke' else cfg['development_ids']
    origins=cfg['evaluation_origins'][:1] if mode=='smoke' else cfg['evaluation_origins']
    return [(s,t,b,h) for t in origins for s in sites for b in cfg['budgets'] for h in cfg['horizons']]


def target_selection(series,date,budget,horizon,cfg,pool,selections,local_fallback,all_series):
    train,val,fold=core.calibration_fold(series,date,budget,horizon,cfg)
    fallback=selections['parameters'][f'B{budget}_H{horizon}']
    if not fold['valid']:
        parameters=deepcopy(fallback)
        for model in (LOCAL_DIRECT,LOCAL_RESIDUAL):parameters[model]=deepcopy(local_fallback[model])
        fold.update(choice_source='main_K30_source_assisted_for_local; matching_pool_source_assisted_for_shared',
                    source_assisted=True,upstream_fit_end='2020-12-31',selection_uses_deployment_labels=False)
        return parameters,fold,[]
    ids=list(pool['site_ids']);x=core.compact(val.X);r=core.residual_target(val)
    descriptor=core.history_descriptor(series,fold['budget_start'],fold['fit_end'])
    prefix_days=(pd.Timestamp(fold['fit_end'])-pd.Timestamp(fold['budget_start'])).days+1
    stats=stats_for(all_series,cfg,ids,horizon,'2020-12-31')
    candidates=[]
    base=dict(held_site_id='target_initial_fold',episode=date,context='budget_internal_chronological',
             budget=budget,horizon=horizon,fitting_labels=len(train.y),validation_labels=len(val.y))
    for alpha in cfg['ridge_alphas']:
        direct=core.ridge_fit(core.compact(train.X),train.y,alpha)
        candidates.append(dict(base,model=LOCAL_DIRECT,alpha=float(alpha),eta=0.,shrinkage=1.,
            validation_mae=float(np.mean(np.abs(direct.predict(x)-val.y))),bias_normalized=0.))
        local=core.ridge_fit(core.compact(train.X),core.residual_target(train),alpha)
        for lam in cfg['lambdas']:
            candidates.append(dict(base,model=LOCAL_RESIDUAL,alpha=float(alpha),eta=0.,shrinkage=float(lam),
                validation_mae=float(np.mean(np.abs(lam*local.predict(x)-r))),bias_normalized=0.))
    parameters=choose(candidates,families=(LOCAL_DIRECT,LOCAL_RESIDUAL))
    for parameter in parameters.values():parameter['source_assisted']=False
    for model_name in(UNIFORM,UNIFORM_BIAS,WEIGHTED,WEIGHTED_BIAS):
        parameters[model_name]=deepcopy(fallback[model_name])
        parameters[model_name]['source_assisted']=True
    fold.update(choice_source='local: budget_internal_chronological; shared: fixed source-only selection for all budgets',
                source_assisted=False,shared_source_assisted=True,
                source_descriptor_matching_calendar_days=prefix_days,descriptor_target=descriptor.diagnostics,
                upstream_fit_end='2020-12-31',selection_uses_deployment_labels=False)
    return parameters,fold,candidates


def validate_target(folder,fingerprint,expected_rows):
    if not validate_cache(folder,fingerprint,REQUIRED):return False
    state=json.loads((Path(folder)/'status.json').read_text())
    if state.get('prediction_rows')!=expected_rows:return False
    frame=pd.read_csv(Path(folder)/'predictions.csv',dtype={'site_id':str})
    if len(frame)!=expected_rows or frame.duplicated(['pool_id','model','seed','origin']).any():return False
    if not(pd.to_datetime(frame.target_date)-pd.to_datetime(frame.origin)).dt.days.eq(frame.horizon).all():return False
    if (pd.to_datetime(frame.latest_input_date)>pd.to_datetime(frame.origin)).any():return False
    if (pd.to_datetime(frame.last_train_target)>pd.to_datetime(frame.fit_end)).any():return False
    return True


def run_target(task,cfg,series,selections,signature,output):
    site,date,budget,horizon=task;folder=Path(output)/'jobs'/task_key(task);folder.mkdir(parents=True,exist_ok=True)
    shuffled=budget==30 and cfg['primary_pool_id'] in [p['pool_id'] for p in cfg['pools']]
    expected_rows=60*len(cfg['pools'])*len(MODELS)+(60*len(cfg['shuffle']['seeds']) if shuffled else 0)
    fingerprint=digest(dict(signature=signature,task=task))
    if validate_target(folder,fingerprint,expected_rows):return dict(task=task_key(task),status='CACHED_VERIFIED')
    previous=json.loads((folder/'status.json').read_text()) if(folder/'status.json').exists() else {}
    attempt=int(previous.get('attempt',0))+1
    if attempt>cfg.get('max_attempts',2):raise RuntimeError('Target attempt limit reached: '+str(folder))
    state=dict(status='RUNNING',fingerprint=fingerprint,attempt=attempt,started_utc=utc_now(),expected_prediction_rows=expected_rows)
    atomic_json(folder/'status.json',state);started=time.perf_counter()
    try:
      train,test,diag=core.initial_data(series[site],date,budget,horizon,cfg)
      descriptor=core.history_descriptor(series[site],diag['budget_start'],diag['fit_end'])
      mainfallback=selections[cfg['primary_pool_id']]['parameters'][f'B{budget}_H{horizon}']
      allpredictions=[];riskrows=[];weightrows=[];grids=[];selected={};parameters={}
      threshold,td=core.large_error_threshold(train,minimum_errors=cfg.get('risk_min_initial_errors',14))
      local_models={}
      for pool in cfg['pools']:
        pid=pool['pool_id'];ids=list(pool['site_ids'])
        decisions,fold,grid=target_selection(series[site],date,budget,horizon,cfg,pool,selections[pid],mainfallback,series)
        selected[pid]=dict(parameters=decisions,fold=fold);grids.extend(dict(row,pool_id=pid) for row in grid)
        outputs=[('persistence',test.persistence.copy(),{},None),('weekly_persistence',test.weekly.copy(),{},None)]
        for model_name in (LOCAL_DIRECT,LOCAL_RESIDUAL):
          decision=decisions[model_name]
          key=(model_name,decision['alpha'])
          if key not in local_models:
            labels=train.y if model_name==LOCAL_DIRECT else core.residual_target(train)
            local_models[key]=core.ridge_fit(core.compact(train.X),labels,decision['alpha'])
          model=local_models[key]
          if model_name==LOCAL_DIRECT:values=model.predict(core.compact(test.X))*test.scale
          else:values=core.reconstruct(test.persistence,model.predict(core.compact(test.X)),0,decision['shrinkage'],test.scale)
          outputs.append((model_name,values,dict(decision,bias_m3=0.,bias_normalized=0.),None))
          parameters[pid+'__'+model_name+'__coef']=model.coef_;parameters[pid+'__'+model_name+'__intercept']=model.intercept_
        for model_name in(UNIFORM,UNIFORM_BIAS,WEIGHTED,WEIGHTED_BIAS):
          decision=decisions[model_name];weights,wd=weights_for(series,ids,budget,descriptor,decision['eta'])
          model=core.fit_weighted(stats_for(series,cfg,ids,horizon,'2021-12-31'),weights,decision['alpha'],target='residual')
          bias=core.estimate_bias(model,train) if model_name in(UNIFORM_BIAS,WEIGHTED_BIAS) else 0.
          choice=dict(decision,bias_m3=bias*test.scale,bias_normalized=bias)
          values=core.reconstruct(test.persistence,model.predict(core.compact(test.X)),bias,decision['shrinkage'],test.scale)
          outputs.append((model_name,values,choice,wd))
          for i,source in enumerate(ids):
            weightrows.append(dict(site_id=site,episode=date,budget=budget,horizon=horizon,pool_id=pid,model=model_name,
              source_site_id=source,weight=weights[source],squared_distance=wd['squared_distances'][i],
              effective_source_count=wd['effective_source_count'],maximum_source_weight=wd['maximum_source_weight'],
              uniform_fallback=wd['uniform_fallback'],fallback_reason=wd['fallback_reason'],eta=decision['eta'],
              source_descriptor_end='2020-12-31',target_descriptor_end=diag['fit_end']))
          parameters[pid+'__'+model_name+'__coef']=model.coef_;parameters[pid+'__'+model_name+'__intercept']=model.intercept_
          parameters[pid+'__'+model_name+'__bias']=bias
          if shuffled and pid==cfg['primary_pool_id'] and model_name==WEIGHTED_BIAS:
            for seed in cfg['shuffle']['seeds']:
              # Frozen seed + site/window/horizon yields a deterministic true permutation.
              salt=int(hashlib.sha256(f'{seed}|{site}|{date}|B{budget}|H{horizon}'.encode()).hexdigest()[:16],16)
              rng=np.random.default_rng(salt);shuffled_values=rng.permutation(list(weights.values()))
              shuffled_weights=dict(zip(ids,map(float,shuffled_values)))
              shuffled_model=core.fit_weighted(stats_for(series,cfg,ids,horizon,'2021-12-31'),shuffled_weights,decision['alpha'],target='residual')
              shuffled_bias=core.estimate_bias(shuffled_model,train)
              shuffled_prediction=core.reconstruct(test.persistence,shuffled_model.predict(core.compact(test.X)),shuffled_bias,decision['shrinkage'],test.scale)
              outputs.append(('shuffled_similarity_residual_ridge_bias_selected',shuffled_prediction,
                             dict(choice,seed=int(seed),bias_m3=shuffled_bias*test.scale,bias_normalized=shuffled_bias),wd))
              for source,weight in shuffled_weights.items():
                weightrows.append(dict(site_id=site,episode=date,budget=budget,horizon=horizon,pool_id=pid,
                  model='shuffled_similarity_residual_ridge_bias_selected',seed=seed,source_site_id=source,weight=weight,
                  effective_source_count=wd['effective_source_count'],maximum_source_weight=wd['maximum_source_weight'],
                  uniform_fallback=wd['uniform_fallback'],eta=decision['eta']))
        for model_name,values,choice,wd in outputs:
          for i,(origin,target) in enumerate(zip(test.origins,test.targets)):
            prediction=float(values[i]);has_input=bool(test.X[i,:,1].sum()>0)
            if model_name not in('persistence','weekly_persistence') and choice.get('shrinkage')!=0 and not has_input:prediction=np.nan
            truth=float(test.y[i]*test.scale);seed=int(choice.get('seed',0))
            row=dict(site_id=site,episode=date,budget=budget,horizon=horizon,origin=str(origin.date()),target_date=str(target.date()),
              model=model_name,pool_id=pid,policy_id=pid+'::'+model_name+('::seed'+str(seed) if seed else ''),seed=seed,
              truth_m3=truth,prediction_m3=prediction,prediction_nonnegative_m3=max(0.,prediction) if np.isfinite(prediction) else np.nan,
              persistence_m3=float(test.persistence[i]),scale_m3=test.scale,budget_start=diag['budget_start'],fit_end=diag['fit_end'],
              last_train_target=diag['last_train_target'],latest_input_date=str(origin.date()),
              training_labels=len(train.y),validation_labels=fold['validation_labels'],
              high_threshold_m3=diag['high_threshold_m3'],threshold_observations=diag['threshold_observations'],
              threshold_start=diag['threshold_start'],threshold_end=diag['threshold_end'],
              alpha=choice.get('alpha'),shrinkage=choice.get('shrinkage'),eta=choice.get('eta'),bias_m3=choice.get('bias_m3',0.),
              source_assisted_tuning=choice.get('source_assisted',fold['source_assisted']),uniform_fallback=wd['uniform_fallback'] if wd else False,
              effective_source_count=wd['effective_source_count'] if wd else None,
              maximum_source_weight=wd['maximum_source_weight'] if wd else None,
              analysis_unit='station_exploratory',physical_mapping_verified=False,verified_real_time=False,
              qa_mode='published_good_only_retrospective',window_class='reused_development')
            allpredictions.append(row)
            if model_name==WEIGHTED_BIAS:
              features=core.risk_features(series[site],origin,diag['budget_start'],test.scale,wd['initial_source_difference'],recent_days=7)
              event=bool(abs(truth-prediction)>threshold) if threshold is not None and np.isfinite(truth) and np.isfinite(prediction) else None
              riskrows.append(dict(row,initial_source_target_difference=features[0],recent_input_missing_fraction=features[1],
                recent_volume_change_normalized=features[2],large_error_threshold_m3=threshold,
                large_error_event=event,absolute_error_m3=abs(truth-prediction),disagreement_rule_score=abs(prediction-test.persistence[i])/test.scale,
                row_key=f'{pid}|{site}|{date}|B{budget}|H{horizon}|{origin.date()}',
                threshold_error_samples=td['calibration_error_count']))
      frame=pd.DataFrame(allpredictions)
      if len(frame)!=expected_rows:raise AssertionError(f'Rows {len(frame)} != {expected_rows}')
      atomic_csv(folder/'predictions.csv',frame);atomic_csv(folder/'risk_inputs.csv',pd.DataFrame(riskrows))
      atomic_csv(folder/'source_weights.csv',pd.DataFrame(weightrows));atomic_csv(folder/'validation_grid.csv',pd.DataFrame(grids))
      atomic_json(folder/'selection.json',selected)
      diag.update(source_final_fit_end='2021-12-31',source_descriptor_end='2020-12-31',threshold=td,
                  target_descriptor=descriptor.diagnostics,selection_uses_deployment_labels=False,
                  prediction_rows=len(frame),risk_input_rows=len(riskrows),physical_mapping_verified=False,
                  verified_real_time=False,device='cpu')
      atomic_json(folder/'diagnostics.json',diag)
      import io
      buf=io.BytesIO();np.savez_compressed(buf,**parameters);atomic_bytes(folder/'model_parameters.npz',buf.getvalue())
      hashes={name:sha256(folder/name) for name in sorted(REQUIRED)}
      state.update(status='COMPLETED',finished_utc=utc_now(),prediction_rows=len(frame),risk_input_rows=len(riskrows),
        outputs_sha256=hashes,write_verified=True,seconds=time.perf_counter()-started,
        peak_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
      atomic_json(folder/'status.json',state)
      if not validate_target(folder,fingerprint,expected_rows):raise IOError('On-disk target completion validation failed')
      return dict(task=task_key(task),status='COMPLETED',seconds=state['seconds'],prediction_rows=len(frame))
    except Exception as error:
      atomic_bytes(folder/f'failure_attempt_{attempt}.txt',traceback.format_exc().encode())
      state.update(status='FAILED',error=str(error),seconds=time.perf_counter()-started,finished_utc=utc_now())
      atomic_json(folder/'status.json',state);append_event(folder/'failure_events.jsonl',dict(attempt=attempt,error=str(error)))
      return dict(task=task_key(task),status='FAILED',error=str(error))


def verify_run(run,cfg,signature,mode='full'):
    run=Path(run);tasks=expected_tasks(cfg,mode);verified=[];invalid=[]
    for task in tasks:
        fp=digest(dict(signature=signature,task=task))
        expected_rows=60*len(cfg['pools'])*len(MODELS)+(60*len(cfg['shuffle']['seeds']) if task[2]==30 else 0)
        folder=run/'jobs'/task_key(task)
        if validate_target(folder,fp,expected_rows):verified.append(task_key(task))
        else:invalid.append(task_key(task))
    return dict(status='COMPLETED' if not invalid else 'PARTIAL',expected=len(tasks),
                disk_verified_completed=len(verified),verified_tasks=verified,not_completed=invalid,
                signature=signature,mode=mode)


def aggregate_run(run,cfg,signature,mode='full'):
    checked=verify_run(run,cfg,signature,mode)
    if checked['status']!='COMPLETED':raise ValueError('Cannot aggregate partial point experiment')
    run=Path(run)
    paths=[run/'jobs'/key/'predictions.csv' for key in checked['verified_tasks']]
    frame=pd.concat([pd.read_csv(path,dtype={'site_id':str}) for path in paths],ignore_index=True)
    atomic_csv(run/'predictions_all.csv.gz',frame)
    checked.update(prediction_rows=len(frame),predictions_all_sha256=sha256(run/'predictions_all.csv.gz'),
      input_sha256={str(path.relative_to(run)):sha256(path) for path in paths})
    atomic_json(run/'AGGREGATION_CHECK.json',checked)
    return checked


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default=f'configs/{VERSION}/full.json')
    parser.add_argument('--mode',choices=['prepare-source','smoke','full','resume'],default='full')
    parser.add_argument('--max-jobs',type=int)
    args=parser.parse_args();cfg,signature=load_config(args.config);started=time.perf_counter()
    ids=list(dict.fromkeys(s for p in cfg['pools'] for s in p['site_ids']))
    series=load_series(ROOT/cfg['canonical_csv'],ids+cfg['development_ids']);groups=group_mapping(cfg)
    selections={};source_states=[]
    for pool in cfg['pools']:
      value,status=prepare_source_pool(series,cfg,pool,groups,ROOT/cfg['source_output']/pool['pool_id'],signature)
      selections[pool['pool_id']]=value;source_states.append(dict(pool_id=pool['pool_id'],status=status))
    if args.mode=='prepare-source':
      atomic_json(ROOT/cfg['source_output']/'SOURCE_RUN_STATUS.json',dict(status='COMPLETED',signature=signature,
        pools=source_states,completed=len(source_states),expected=3,seconds=time.perf_counter()-started,finished_utc=utc_now()))
      return 0
    mode='full' if args.mode=='resume' else args.mode
    output=ROOT/cfg['output'] if mode=='full' else ROOT/cfg.get('smoke_output',f'runs/{VERSION}/smoke')
    output.mkdir(parents=True,exist_ok=True);tasks=expected_tasks(cfg,mode)
    atomic_json(output/'EXPECTED_TASKS.json',dict(signature=signature,tasks=[task_key(t) for t in tasks],
      expected=len(tasks),defined_before_target_results=True))
    results=[]
    for count,task in enumerate(tasks,1):
      if args.max_jobs is not None and count>args.max_jobs:break
      result=run_target(task,cfg,series,selections,signature,output);results.append(result)
      print(f"target {mode} {count}/{len(tasks)} {result['task']} {result['status']}",flush=True)
    verified=[]
    for task in tasks:
      expected_rows=60*3*8+(180 if task[2]==30 else 0)
      fp=digest(dict(signature=signature,task=task))
      if validate_target(output/'jobs'/task_key(task),fp,expected_rows):verified.append(task_key(task))
    completed=len(verified);failed=sum(r['status']=='FAILED' for r in results)
    state=dict(status='COMPLETED' if completed==len(tasks) else 'PARTIAL',signature=signature,
      mode=mode,expected=len(tasks),disk_verified_completed=completed,
      function_successes=sum(r['status']=='COMPLETED' for r in results),verified_cached=sum(r['status']=='CACHED_VERIFIED' for r in results),
      failed_this_invocation=failed,not_completed=[task_key(t) for t in tasks if task_key(t) not in verified],
      source_states=source_states,results=results,seconds=time.perf_counter()-started,finished_utc=utc_now())
    atomic_json(output/'RUN_STATUS.json',state)
    if state['status']=='COMPLETED':aggregate_run(output,cfg,signature,mode)
    return 0 if state['status']=='COMPLETED' else 3


if __name__=='__main__':raise SystemExit(main())
