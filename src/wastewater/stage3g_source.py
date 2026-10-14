"""Stage3G source-only selection and independently isolated reliability roles.

No development target labels are inspected. Selection scores are selection
scores, never unbiased evidence of prediction or risk-detection performance.
"""
from __future__ import annotations
from copy import deepcopy
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
import traceback
import numpy as np
import pandas as pd
from .common import sha256, utc_now
from .stage3e_runtime import atomic_bytes, atomic_json, append_event, FingerprintMismatch
from . import stage3g_core as core

LOCAL_DIRECT='local_direct_ridge_selected'
LOCAL_RESIDUAL='local_residual_ridge_selected'
UNIFORM='uniform_residual_ridge_selected'
UNIFORM_BIAS='uniform_residual_ridge_bias_selected'
WEIGHTED='similarity_residual_ridge_selected'
WEIGHTED_BIAS='similarity_residual_ridge_bias_selected'
FAMILIES=(LOCAL_DIRECT,LOCAL_RESIDUAL,UNIFORM,UNIFORM_BIAS,WEIGHTED,WEIGHTED_BIAS)
_STATS={};_DESCRIPTORS={};_PSEUDOS={};_FIT_COUNTS={'source_weighted':0,'local':0}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def atomic_csv(path,frame):
    content=frame.to_csv(index=False).encode()
    if str(path).endswith('.gz'): content=gzip.compress(content,mtime=0)
    return atomic_bytes(path,content)


def group_folds(ids,groups,n=5,prefix='Wessex-G-source-fold-v1|'):
    unique=sorted({groups[str(s)] for s in ids},key=lambda g:(hashlib.sha256((prefix+g).encode()).hexdigest(),g))
    if len(unique)<n: raise ValueError('Not enough connected groups for fixed source folds')
    gf={g:i%n for i,g in enumerate(unique)}
    return {str(s):gf[groups[str(s)]] for s in ids}


def stats_for(series,cfg,ids,horizon,end):
    result={}
    for site in ids:
        key=(str(site),int(horizon),str(end))
        if key not in _STATS:
            _STATS[key]=core.build_source_stats(series,cfg,[str(site)],horizon,end)[str(site)]
        result[str(site)]=_STATS[key]
    return result


def descriptors_for(series,ids,budget):
    raw=[];rows=[]
    for site in ids:
        key=(str(site),int(budget))
        if key not in _DESCRIPTORS:
            _DESCRIPTORS[key]=core.source_descriptors(series,[str(site)],int(budget),end='2020-12-31')
        values,diagnostics=_DESCRIPTORS[key]
        raw.append(values[0]);rows.extend(diagnostics)
    return np.asarray(raw),rows


def pseudo_for(series,site,date,budget,horizon,cfg):
    key=(str(site),date,int(budget),int(horizon))
    if key not in _PSEUDOS:
        pseudo_cfg=dict(cfg,evaluation_days=cfg['source_pseudo_validation_days'])
        train,test,diag=core.initial_data(series[str(site)],date,budget,horizon,pseudo_cfg)
        desc=core.history_descriptor(series[str(site)],diag['budget_start'],diag['fit_end'])
        _PSEUDOS[key]=(train,test,diag,desc)
    return _PSEUDOS[key]


def weights_for(series,source_ids,budget,target_descriptor,eta):
    raw,_=descriptors_for(series,source_ids,budget)
    transform=core.fit_descriptor_transform(raw)
    weights,diagnostic=core.similarity_weights(target_descriptor,raw,float(eta),transform)
    return dict(zip(source_ids,map(float,weights))),diagnostic


def choose(rows,families=FAMILIES):
    frame=pd.DataFrame(rows)
    if frame.empty:raise ValueError('No legal source selection rows')
    decisions={}
    for family in families:
        sub=frame[frame.model.eq(family)]
        # Equal pseudo-site and pseudo-window. Each retained row is one such task.
        means=sub.groupby(['eta','alpha','shrinkage'],as_index=False).validation_mae.mean()
        if means.empty:raise ValueError('Missing source candidate family: '+family)
        minimum=float(means.validation_mae.min())
        eligible=means[means.validation_mae <= minimum + 1e-12]
        best=eligible.sort_values(['eta','shrinkage','alpha'],kind='stable').iloc[0]
        decisions[family]=dict(alpha=float(best.alpha),shrinkage=float(best.shrinkage),eta=float(best.eta),
            validation_mae=float(best.validation_mae),source_assisted=True,
            selection_rule='equal pseudo-SiteID/window normalized MAE; ties within 1e-12 normalized MAE: eta,lambda,alpha',
            evaluated_pseudo_tasks=int(sub.groupby(['held_site_id','episode']).ngroups))
    return decisions


def source_cv(series,cfg,ids,groups,n_folds=5,context='global',progress=None):
    folds=group_folds(ids,groups,n_folds,'Wessex-G-source-fold-v1|')
    rows=[];registry=[];selection={}
    for budget in cfg['budgets']:
      for horizon in cfg['horizons']:
        relevant=[]
        for held in ids:
          excluded=[s for s in ids if folds[s]==folds[held]]
          fit_ids=[s for s in ids if s not in excluded]
          source_stats=stats_for(series,cfg,fit_ids,horizon,'2020-12-31')
          for date in cfg['source_pseudo_origins']:
            train,test,diag,descriptor=pseudo_for(series,held,date,budget,horizon,cfg)
            keep=core.usable(test)
            if not keep.any():raise ValueError('No legal pseudo-deployment labels')
            val=core.subset(test,keep);x=core.compact(val.X);r=core.residual_target(val)
            foldid=f'{context}_{held}_{date}_B{budget}_H{horizon}'
            registry.append(dict(context=context,fold_id=foldid,fold=int(folds[held]),held_site_id=held,
               held_group=groups[held],excluded_groups=sorted({groups[s] for s in excluded}),
               excluded_site_ids=excluded,base_fit_site_ids=fit_ids,base_fit_end='2020-12-31',
               descriptor_fit_site_ids=fit_ids,descriptor_source_end='2020-12-31',**diag))
            base=dict(context=context,fold_id=foldid,held_site_id=held,held_group=groups[held],
                 episode=date,budget=budget,horizon=horizon,fitting_labels=len(train.y),validation_labels=len(val.y),
                 scale_m3=val.scale,base_fit_end='2020-12-31',descriptor_end=diag['fit_end'])
            for alpha in cfg['ridge_alphas']:
              local_direct=core.ridge_fit(core.compact(train.X),train.y,alpha);_FIT_COUNTS['local']+=1
              local_res=core.ridge_fit(core.compact(train.X),core.residual_target(train),alpha);_FIT_COUNTS['local']+=1
              direct_e=local_direct.predict(x)-val.y
              relevant.append(dict(base,model=LOCAL_DIRECT,alpha=float(alpha),shrinkage=1.,eta=0.,
                    validation_mae=float(np.mean(np.abs(direct_e))),bias_normalized=0.))
              lp=local_res.predict(x)
              for lam in cfg['lambdas']:
                relevant.append(dict(base,model=LOCAL_RESIDUAL,alpha=float(alpha),shrinkage=float(lam),eta=0.,
                    validation_mae=float(np.mean(np.abs(float(lam)*lp-r))),bias_normalized=0.))
              for eta in cfg['etas']:
                w,wdiag=weights_for(series,fit_ids,budget,descriptor,eta)
                model=core.fit_weighted(source_stats,w,alpha,target='residual');_FIT_COUNTS['source_weighted']+=1
                bias=core.estimate_bias(model,train);pred=model.predict(x)
                names=[(WEIGHTED,0.),(WEIGHTED_BIAS,bias)]
                if eta==0:names.extend([(UNIFORM,0.),(UNIFORM_BIAS,bias)])
                for family,b in names:
                  for lam in cfg['lambdas']:
                    relevant.append(dict(base,model=family,alpha=float(alpha),shrinkage=float(lam),eta=float(eta),
                        validation_mae=float(np.mean(np.abs(float(lam)*(pred+b)-r))),bias_normalized=float(b),
                        effective_sources=float(wdiag['effective_source_count']),max_source_weight=float(max(w.values())),
                        descriptor_uniform_fallback=bool(wdiag['uniform_fallback'])))
        selection[f'B{budget}_H{horizon}']=choose(relevant);rows.extend(relevant)
        if progress:progress(f'{context} source CV B{budget} H{horizon} candidates={len(relevant)}')
    return selection,pd.DataFrame(rows),registry


def predict_source_role(series,cfg,fit_ids,target_site,date,budget,horizon,parameter,groups,outer_fold,role,pool_id):
    train,test,diag,desc=pseudo_for(series,target_site,date,budget,horizon,cfg)
    weights,wd=weights_for(series,fit_ids,budget,desc,parameter['eta'])
    model=core.fit_weighted(stats_for(series,cfg,fit_ids,horizon,'2020-12-31'),weights,parameter['alpha'],target='residual')
    _FIT_COUNTS['source_weighted']+=1
    bias=core.estimate_bias(model,train)
    values=core.reconstruct(test.persistence,model.predict(core.compact(test.X)),bias,parameter['shrinkage'],test.scale)
    threshold,threshold_diag=core.large_error_threshold(train,minimum_errors=cfg.get('risk_min_initial_errors',14))
    initial_difference=float(wd.get('initial_source_difference') if wd.get('initial_source_difference') is not None else np.nan)
    rows=[]
    for i,(origin,target) in enumerate(zip(test.origins,test.targets)):
      features=core.risk_features(series[target_site],origin,diag['budget_start'],test.scale,initial_difference,recent_days=7)
      y=float(test.y[i]*test.scale);p=float(values[i]);baseline=float(test.persistence[i])
      available=bool(np.isfinite(test.X[i,:,1]).all() and test.X[i,:,1].sum()>0)
      if parameter['shrinkage']!=0 and not available:p=np.nan
      event=bool(abs(y-p)>threshold) if threshold is not None and np.isfinite(y) and np.isfinite(p) else None
      rows.append(dict(pool_id=pool_id,outer_fold=outer_fold,role=role,site_id=target_site,group_id=groups[target_site],
        episode=date,budget=budget,horizon=horizon,origin=str(origin.date()),target_date=str(target.date()),
        truth_m3=y,prediction_m3=p,persistence_m3=baseline,scale_m3=test.scale,
        initial_source_target_difference=float(features[0]),recent_input_missing_fraction=float(features[1]),
        recent_volume_change_normalized=float(features[2]),large_error_threshold_m3=threshold,
        large_error_event=event,absolute_error_m3=abs(y-p) if np.isfinite(y) and np.isfinite(p) else np.nan,
        disagreement_rule_score=abs(p-baseline)/test.scale,
        row_key=f'{pool_id}|{outer_fold}|{role}|{target_site}|{date}|B{budget}|H{horizon}|{origin.date()}',
        alpha=parameter['alpha'],shrinkage=parameter['shrinkage'],eta=parameter['eta'],bias_normalized=bias,
        latest_input_date=str(origin.date()),latest_training_label=diag['last_train_target'],
        base_fit_end='2020-12-31',source_assisted_upstream_parameters=True,
        threshold_error_samples=threshold_diag.get('calibration_error_count')))
    return rows


def strict_reliability_base_rows(series,cfg,ids,groups,pool_id,progress=None):
    folds=group_folds(ids,groups,5);rows=[];registries=[];nested_grids=[]
    for outer in range(5):
      rolefolds={'outer_evaluation':outer,'risk_train':(outer+1)%5,'threshold_calibration':(outer+2)%5}
      fit_ids=[s for s in ids if folds[s] not in rolefolds.values()]
      selected,grid,innerregistry=source_cv(series,cfg,fit_ids,groups,3,
           context=f'{pool_id}_risk_outer{outer}_inner',progress=progress)
      grid['outer_fold']=outer;grid['pool_id']=pool_id;nested_grids.append(grid)
      roles={role:[s for s in ids if folds[s]==value] for role,value in rolefolds.items()}
      registries.append(dict(pool_id=pool_id,outer_fold=outer,base_fit_site_ids=fit_ids,
        base_fit_groups=sorted({groups[s] for s in fit_ids}),upstream_selection_site_ids=fit_ids,
        descriptor_standardization_site_ids=fit_ids,role_site_ids=roles,
        role_groups={role:sorted({groups[s] for s in sites}) for role,sites in roles.items()},
        inner_selection_registry=innerregistry,parameters=selected,
        exclusion_verified=all(not(set(fit_ids)&set(sites)) for sites in roles.values())))
      for role,sites in roles.items():
        for held in sites:
          for date in cfg['source_pseudo_origins']:
            for budget in cfg['budgets']:
              for horizon in cfg['horizons']:
                rows.extend(predict_source_role(series,cfg,fit_ids,held,date,budget,horizon,
                  selected[f'B{budget}_H{horizon}'][WEIGHTED_BIAS],groups,outer,role,pool_id))
      if progress:progress(f'{pool_id} strict risk base outer{outer+1}/5 rows={len(rows)}')
    return pd.DataFrame(rows),registries,pd.concat(nested_grids,ignore_index=True)


def validate_cache(folder,fingerprint,required):
    folder=Path(folder);path=folder/'status.json'
    if not path.exists():return False
    state=json.loads(path.read_text())
    if state.get('fingerprint')!=fingerprint:raise FingerprintMismatch(str(folder))
    if state.get('status')!='COMPLETED':return False
    hashes=state.get('outputs_sha256',{})
    if not set(required).issubset(hashes):return False
    if any(not(folder/member).is_file() or sha256(folder/member)!=expected for member,expected in hashes.items()):return False
    if not state.get('write_verified'):return False
    if 'source_cv_candidates.csv.gz' in required:
        checks=[('source_cv_candidates.csv.gz','source_cv_rows',{'model','held_site_id','episode','budget','horizon','eta','alpha','shrinkage','validation_mae'}),
                ('strict_reliability_base_predictions.csv.gz','reliability_base_rows',{'role','outer_fold','site_id','budget','horizon','origin','target_date'}),
                ('nested_source_cv_candidates.csv.gz','nested_cv_rows',{'model','outer_fold','held_site_id','budget','horizon'})]
        for filename,count_key,columns in checks:
            frame=pd.read_csv(folder/filename)
            if len(frame)!=state.get(count_key) or not columns.issubset(frame.columns):return False
        if state.get('source_cv_rows')!=79920 or state.get('reliability_base_rows')!=15120 or state.get('nested_cv_rows')!=159840:return False
        role_frame=pd.read_csv(folder/'strict_reliability_base_predictions.csv.gz')
        if set(role_frame.role)!={'risk_train','threshold_calibration','outer_evaluation'} or role_frame.outer_fold.nunique()!=5:return False
    return True


def prepare_source_pool(series,cfg,pool,groups,folder,signature,progress=print):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);ids=list(pool['site_ids'])
    required={'selection.json','source_cv_candidates.csv.gz','source_cv_folds.json',
      'strict_reliability_base_predictions.csv.gz','strict_reliability_roles.json','nested_source_cv_candidates.csv.gz','source_descriptor_windows.json','source_training_diagnostics.json'}
    fingerprint=digest(dict(signature=signature,pool=pool,groups={s:groups[s] for s in ids}))
    if validate_cache(folder,fingerprint,required):
      return json.loads((folder/'selection.json').read_text()),'CACHED_VERIFIED'
    previous=json.loads((folder/'status.json').read_text()) if(folder/'status.json').exists() else {}
    attempt=int(previous.get('attempt',0))+1
    if attempt>cfg.get('max_attempts',2):raise RuntimeError('Source attempt limit reached: '+str(folder))
    state=dict(status='RUNNING',fingerprint=fingerprint,attempt=attempt,started_utc=utc_now())
    atomic_json(folder/'status.json',state);started=time.perf_counter()
    def pulse(message):
      state.update(last_progress_utc=utc_now(),last_step=message,elapsed_seconds=time.perf_counter()-started)
      atomic_json(folder/'status.json',state)
      if progress:progress(message,flush=True)
    try:
      selections,grid,folds=source_cv(series,cfg,ids,groups,5,context=pool['pool_id'],progress=pulse)
      descriptor_rows=[]
      for length in (30,72,90,144,180):descriptor_rows.extend(descriptors_for(series,ids,length)[1])
      atomic_json(folder/'source_descriptor_windows.json',descriptor_rows)
      statistic_rows=[]
      for horizon in cfg['horizons']:
        for end in ('2020-12-31','2021-12-31'):
          statistic_rows.extend(dict(s.diagnostics,horizon=horizon,source_end=end) for s in stats_for(series,cfg,ids,horizon,end).values())
      atomic_json(folder/'source_training_diagnostics.json',statistic_rows)
      atomic_json(folder/'selection.json',dict(pool_id=pool['pool_id'],source_ids=ids,parameters=selections,
        base_proxy_fit_end='2020-12-31',source_descriptor_end='2020-12-31',final_fit_end='2021-12-31',
        selection_scores_not_unbiased_evidence=True,descriptor_schema='IQR/scale,median adjacent change/scale,ACF1,missing fraction'))
      atomic_csv(folder/'source_cv_candidates.csv.gz',grid);atomic_json(folder/'source_cv_folds.json',folds)
      riskrows,roles,nested= strict_reliability_base_rows(series,cfg,ids,groups,pool['pool_id'],progress=pulse)
      atomic_csv(folder/'strict_reliability_base_predictions.csv.gz',riskrows)
      atomic_json(folder/'strict_reliability_roles.json',roles)
      atomic_csv(folder/'nested_source_cv_candidates.csv.gz',nested)
      outputs={name:sha256(folder/name) for name in sorted(required)}
      state.update(status='COMPLETED',finished_utc=utc_now(),seconds=time.perf_counter()-started,
        source_cv_rows=len(grid),reliability_base_rows=len(riskrows),nested_cv_rows=len(nested),
        outputs_sha256=outputs,write_verified=True,fit_counts=dict(_FIT_COUNTS))
      atomic_json(folder/'status.json',state)
      if not validate_cache(folder,fingerprint,required):raise IOError('Source writeback verification failed')
      return json.loads((folder/'selection.json').read_text()),'COMPLETED'
    except Exception as error:
      atomic_bytes(folder/f'failure_attempt_{attempt}.txt',traceback.format_exc().encode())
      state.update(status='FAILED',error=str(error),finished_utc=utc_now())
      atomic_json(folder/'status.json',state);append_event(folder/'failure_events.jsonl',dict(attempt=attempt,error=str(error)))
      raise
