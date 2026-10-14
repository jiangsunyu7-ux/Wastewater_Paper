"""Matched, calendar-preserving Stage3G evaluation. Never trains or selects models.

All dates are reused development dates. Equal-SiteID skill and original-volume
error are distinct estimands. Undefined denominators stay NA. Seeds in the
weight-shuffle control average losses, never predictions or facility counts.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .common import sha256, utc_now, write_json
from .stage3c2_evaluation import bootstrap_station_means

MODELS = ('persistence', 'weekly_persistence', 'local_direct_ridge_selected',
          'local_residual_ridge_selected', 'uniform_residual_ridge_selected',
          'uniform_residual_ridge_bias_selected', 'similarity_residual_ridge_selected',
          'similarity_residual_ridge_bias_selected')
PRIMARY = 'similarity_residual_ridge_bias_selected'
UNIFORM = 'uniform_residual_ridge_bias_selected'
LOCAL = 'local_residual_ridge_selected'
SHUFFLE = 'shuffled_similarity_residual_ridge_bias_selected'
MAIN_POOL = 'order20261012_K30'
KEYS = ['site_id', 'episode', 'horizon', 'origin', 'target_date']
ROW_KEYS = KEYS + ['budget', 'pool_id', 'model']
TASK_KEYS = ['site_id', 'episode', 'budget', 'horizon', 'pool_id', 'model']
TIE_TOLERANCE = 1e-12


def mean(values, axis=None):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        return np.nanmean(values, axis=axis)


def ratio_skill(candidate, reference):
    """No arbitrary epsilon: zero/nonfinite reference is genuinely undefined."""
    a, b = np.broadcast_arrays(np.asarray(candidate, float), np.asarray(reference, float))
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(np.isfinite(a) & np.isfinite(b) & (b > 0), 1-a/b, np.nan)


def pools(cfg):
    raw = cfg.get('pools', cfg.get('source_pools', []))
    if isinstance(raw, dict):
        raw = [dict(v, pool_id=k) for k, v in raw.items()]
    ids = [str(p.get('pool_id', p.get('id'))) for p in raw]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Explicit distinct frozen source pools required')
    return ids


def episodes(cfg):
    out = list(cfg.get('evaluation_origins', cfg.get('origins', [])))
    if not out or len(out) != len(set(out)):
        raise ValueError('Explicit unique deployment starts required')
    for t in out:
        if pd.Timestamp(t)+pd.Timedelta(days=int(cfg['evaluation_days'])-1+max(cfg['horizons'])) > pd.Timestamp('2023-12-31'):
            raise ValueError('Final 2024--2025 performance is forbidden')
    return out


def expected_rows(cfg):
    table = pd.MultiIndex.from_product([list(map(str, cfg['development_ids'])), episodes(cfg),
        cfg['budgets'], cfg['horizons'], pools(cfg), MODELS], names=TASK_KEYS).to_frame(index=False)
    n = len(table); length = int(cfg['evaluation_days'])
    table = table.loc[table.index.repeat(length)].reset_index(drop=True)
    table['origin'] = (pd.to_datetime(table.episode)+pd.to_timedelta(np.tile(np.arange(length), n), unit='D')).dt.strftime('%Y-%m-%d')
    table['target_date'] = (pd.to_datetime(table.origin)+pd.to_timedelta(table.horizon, unit='D')).dt.strftime('%Y-%m-%d')
    return table


def prepare_predictions(frame, cfg):
    p = frame.copy()
    required = ROW_KEYS+['truth_m3', 'prediction_m3', 'scale_m3', 'high_threshold_m3']
    if not set(required) <= set(p):
        raise ValueError('Missing forecast columns: '+','.join(sorted(set(required)-set(p))))
    p['site_id'] = p.site_id.astype(str); p['pool_id'] = p.pool_id.astype(str)
    for c in ['episode', 'origin', 'target_date']:
        p[c] = pd.to_datetime(p[c]).dt.strftime('%Y-%m-%d')
    main = p[p.model.isin(MODELS)].copy()
    if main.duplicated(ROW_KEYS).any():
        raise ValueError('Duplicate registered point forecast')
    expected = expected_rows(cfg)
    main['prediction_row_present'] = True
    checked = expected.merge(main, on=ROW_KEYS, how='outer', indicator=True, validate='one_to_one')
    if checked._merge.eq('right_only').any():
        raise ValueError('Unregistered task/date in predictions')
    checked['prediction_row_present'] = checked.prediction_row_present.fillna(False).astype(bool)
    checked = checked.drop(columns='_merge')
    if not (pd.to_datetime(checked.target_date)-pd.to_datetime(checked.origin)).dt.days.eq(checked.horizon).all():
        raise ValueError('h=3 must align to origin+3 single-day volume')
    if 'latest_input_date' in checked and (pd.to_datetime(checked.latest_input_date)>pd.to_datetime(checked.origin)).any():
        raise ValueError('Future deployment input')
    cutoff = pd.to_datetime(checked.episode)-pd.Timedelta(days=1)
    left = pd.to_datetime(checked.episode)-pd.to_timedelta(checked.budget, unit='D')
    if 'fit_end' in checked and (pd.to_datetime(checked.fit_end)>cutoff).any():
        raise ValueError('Training/adaptation after initial calibration cutoff')
    if 'budget_start' in checked and (pd.to_datetime(checked.budget_start)!=left).any():
        raise ValueError('Initial history left boundary does not match budget')
    for c in ['truth_m3', 'high_threshold_m3']:
        q = checked.groupby(KEYS)[c].agg(['min', 'max'])
        if ((q['max']-q['min']).abs()>1e-8+1e-12*q['min'].abs()).any():
            raise ValueError('Conflicting shared calendar '+c)
    checked['finite_truth'] = np.isfinite(checked.truth_m3)
    checked['finite_prediction'] = np.isfinite(checked.prediction_m3)
    checked['forecast_eligible'] = checked.prediction_row_present & checked.finite_truth & checked.finite_prediction
    checked['common_evaluation'] = checked.groupby(KEYS).forecast_eligible.transform('all')
    # Evaluation availability remains visible over all 60 planned origins.
    checked['prediction_failure_reason'] = np.select([
        ~checked.prediction_row_present, ~checked.finite_truth,
        checked.finite_truth & ~checked.finite_prediction],
        ['missing_output_row', 'missing_true_target', 'nonfinite_prediction'], default='')
    clipped = np.maximum(0., checked.prediction_m3.to_numpy(float))
    if 'prediction_nonnegative_m3' in checked and not np.array_equal(clipped, checked.prediction_nonnegative_m3.to_numpy(float), equal_nan=True):
        raise ValueError('Selective/inconsistent nonnegative constraint')
    checked['prediction_nonnegative_m3'] = clipped
    if 'shrinkage' in checked:
        base = checked[checked.model.eq('persistence')][KEYS+['budget', 'pool_id', 'prediction_m3']]
        zero = checked[checked.shrinkage.eq(0)&~checked.model.eq('persistence')]
        q = zero.merge(base, on=KEYS+['budget', 'pool_id'], suffixes=('', '_p'), validate='many_to_one')
        if not np.array_equal(q.prediction_m3.to_numpy(float), q.prediction_m3_p.to_numpy(float), equal_nan=True):
            raise ValueError('lambda=0 must exactly equal matched Persistence')
    # Duplicate baselines provide matched pool comparisons, not extra plants.
    for c in ['prediction_m3', 'scale_m3']:
        q = checked[checked.model.isin(MODELS[:4])].groupby(KEYS+['budget', 'model'])[c]
        if q.nunique(dropna=False).gt(1).any():
            raise ValueError('Shared/local baseline differs across source pool: '+c)
    return checked


def daily_losses(p):
    frames=[]
    common=p[p.forecast_eligible]
    columns=KEYS+['budget', 'pool_id', 'model', 'truth_m3', 'high_threshold_m3']
    for constraint, col in [('raw','prediction_m3'), ('all_models_nonnegative','prediction_nonnegative_m3')]:
        q=common[columns].copy(); err=common[col]-common.truth_m3
        q['absolute_error']=err.abs(); q['squared_error']=err**2; q['signed_error']=err
        q['constraint']=constraint
        q['high_volume']=q.truth_m3.ge(q.high_threshold_m3)&q.high_threshold_m3.notna()
        frames.append(q)
    return pd.concat(frames,ignore_index=True)


def paired_date_index(p,cfg):
    """All planned dates for every pair, including unavailable rows and reasons."""
    rows=[]
    for comparison in comparisons(cfg):
        c=comparison
        a=p[p.pool_id.eq(c['pool_id'])&p.model.eq(c['model'])&p.budget.eq(c['budget'])&p.horizon.eq(c['horizon'])]
        b=p[p.pool_id.eq(c['pool_id'])&p.model.eq(c['reference'])&p.budget.eq(c['reference_budget'])&p.horizon.eq(c['horizon'])]
        cols=KEYS+['forecast_eligible','prediction_failure_reason','prediction_row_present','finite_prediction','finite_truth']
        pair=a[cols].merge(b[cols],on=KEYS,how='outer',validate='one_to_one',suffixes=('_candidate','_reference'))
        pair['paired_evaluation']=pair.forecast_eligible_candidate&pair.forecast_eligible_reference
        for k in ['comparison_id','pool_id','model','reference','budget','reference_budget','kind','prespecified_primary']:pair[k]=c[k]
        rows.append(pair)
    return pd.concat(rows,ignore_index=True)


def station_metrics(daily,cfg,per_episode=False):
    keys=['constraint','site_id','pool_id','model','budget','horizon']
    if per_episode: keys.insert(1,'episode')
    g=daily.groupby(keys).agg(n_dates=('absolute_error','size'),mae_m3=('absolute_error','mean'),mse=('squared_error','mean')).reset_index()
    expected=pd.MultiIndex.from_product([['raw','all_models_nonnegative'],map(str,cfg['development_ids']),pools(cfg),MODELS,cfg['budgets'],cfg['horizons']],names=['constraint','site_id','pool_id','model','budget','horizon']).to_frame(index=False)
    if per_episode: expected=expected.merge(pd.DataFrame({'episode':episodes(cfg)}),how='cross')
    out=expected.merge(g,on=keys,how='left',validate='one_to_one')
    out['n_dates']=out.n_dates.fillna(0).astype(int);out['rmse_m3']=np.sqrt(out.pop('mse'))
    # A weak/failed third policy must not change a valid candidate-Persistence pair.
    reference_keys=KEYS+['constraint','budget','pool_id']
    ref=daily[daily.model.eq('persistence')][reference_keys+['absolute_error']].rename(columns={'absolute_error':'persistence_absolute_error'})
    paired=daily.merge(ref,on=reference_keys,how='inner',validate='many_to_one')
    pair_metric=paired.groupby(keys).agg(paired_dates_vs_persistence=('absolute_error','size'),
        paired_mae_m3_vs_persistence=('absolute_error','mean'),persistence_mae_m3=('persistence_absolute_error','mean')).reset_index()
    out=out.merge(pair_metric,on=keys,how='left',validate='one_to_one')
    out['paired_dates_vs_persistence']=out.paired_dates_vs_persistence.fillna(0).astype(int)
    out['skill_vs_persistence']=ratio_skill(out.paired_mae_m3_vs_persistence,out.persistence_mae_m3)
    out['zero_reference_mae']=out.persistence_mae_m3.eq(0)
    return out


def aggregate_metrics(metric,per_episode=False):
    keys=['constraint','pool_id','model','budget','horizon']
    if per_episode: keys.insert(1,'episode')
    rows=[]
    for values,g in metric.groupby(keys):
        s=g.skill_vs_persistence.dropna();n=len(s)
        wins=int((s>TIE_TOLERANCE).sum());ties=int((s.abs()<=TIE_TOLERANCE).sum());losses=int((s<-TIE_TOLERANCE).sum())
        rows.append(dict(zip(keys,values),stations=len(g),stations_with_dates=int(g.n_dates.gt(0).sum()),defined_skill_stations=n,
            equal_station_mae_m3=g.mae_m3.mean(),equal_station_rmse_m3=g.rmse_m3.mean(),mean_skill=s.mean(),median_skill=s.median(),
            winning_stations=wins,tied_stations=ties,worse_stations=losses,win_fraction=wins/n if n else np.nan,
            tie_fraction=ties/n if n else np.nan,loss_fraction=losses/n if n else np.nan,
            zero_reference_stations=int(g.zero_reference_mae.sum()),min_dates=int(g.n_dates.min()),max_dates=int(g.n_dates.max())))
    return pd.DataFrame(rows)


def comparisons(cfg):
    out=[];main=cfg.get('primary_pool_id',MAIN_POOL)
    def add(pool,model,b,reference,rb,h,kind):
        primary=pool==main and model==PRIMARY and b==rb==30 and reference in ('persistence',UNIFORM)
        out.append(dict(comparison_id=f'{pool}_{model}_B{b}_vs_{reference}_B{rb}_H{h}',pool_id=pool,model=model,budget=b,
            reference=reference,reference_budget=rb,horizon=h,kind=kind,prespecified_primary=primary))
    for pool,h,b in itertools.product(pools(cfg),cfg['horizons'],cfg['budgets']):
        for model in MODELS[1:]:add(pool,model,b,'persistence',b,h,'vs_persistence')
        for model,uniform in [('similarity_residual_ridge_selected','uniform_residual_ridge_selected'),(PRIMARY,UNIFORM)]:
            add(pool,model,b,uniform,b,h,'weighting_vs_matched_uniform')
            add(pool,model,b,LOCAL,b,h,'same_budget_transfer')
        add(pool,PRIMARY,b,'local_direct_ridge_selected',b,h,'same_budget_direct_local')
        add(pool,PRIMARY,b,'similarity_residual_ridge_selected',b,h,'bias_diagnostic')
    for pool,h in itertools.product(pools(cfg),cfg['horizons']):
        for b,rb in [(30,90),(30,180),(90,180)]:add(pool,PRIMARY,b,LOCAL,rb,h,'history_budget_comparison')
    if sum(x['prespecified_primary'] for x in out)!=4:raise ValueError('Exactly four frozen primary contrasts required')
    return out


def dense_errors(daily,cfg,horizon,constraint,subset):
    sites=list(map(str,cfg['development_ids']));eps=episodes(cfg);length=int(cfg['evaluation_days'])
    labels=[(b,p,m) for b in cfg['budgets'] for p in pools(cfg) for m in MODELS];lookup={x:i for i,x in enumerate(labels)}
    q=daily[daily.horizon.eq(horizon)&daily.constraint.eq(constraint)]
    if subset=='historical_high_volume':q=q[q.high_volume]
    a=np.full((len(sites),len(eps)*length,len(labels)),np.nan)
    if len(q):
        si=q.site_id.map({s:i for i,s in enumerate(sites)}).to_numpy()
        day=(pd.to_datetime(q.origin)-pd.to_datetime(q.episode)).dt.days.to_numpy()
        di=q.episode.map({e:i for i,e in enumerate(eps)}).to_numpy()*length+day
        pi=np.fromiter((lookup[x] for x in zip(q.budget,q.pool_id,q.model)),int,count=len(q))
        a[si,di,pi]=q.absolute_error.to_numpy()
    return a,labels


def paired_intervals(daily,cfg,constraint='raw',subset='all_dates',progress=print):
    rows=[];site_rows=[];comparisons_all=comparisons(cfg)
    for h in cfg['horizons']:
        a,labels=dense_errors(daily,cfg,h,constraint,subset);lookup={x:i for i,x in enumerate(labels)}
        pairs=[x for x in comparisons_all if x['horizon']==h]
        matched_columns=[]
        for pi,p in enumerate(pairs):
            ai=lookup[p['budget'],p['pool_id'],p['model']];bi=lookup[p['reference_budget'],p['pool_id'],p['reference']]
            valid=np.isfinite(a[:,:,ai])&np.isfinite(a[:,:,bi])
            ma=np.where(valid,a[:,:,ai],np.nan);mb=np.where(valid,a[:,:,bi],np.nan)
            matched_columns.extend([ma,mb]);ap=mean(ma,axis=1);bp=mean(mb,axis=1);counts=valid.sum(axis=1)
            sk=ratio_skill(ap,bp)
            for i,site in enumerate(map(str,cfg['development_ids'])):
                denom=bp[i];denomvalid=np.isfinite(denom) and denom>0
                site_rows.append(dict(p,constraint=constraint,subset=subset,site_id=site,n_dates=int(counts[i]),reference_n_dates=int(counts[i]),
                    mae_m3=ap[i],reference_mae_m3=denom,skill=sk[i],mae_ratio=1-sk[i] if denomvalid else np.nan,
                    absolute_mae_difference_m3=ap[i]-denom,zero_reference_mae=bool(denom==0),
                    negative_transfer=bool(sk[i]<-TIE_TOLERANCE),win=bool(sk[i]>TIE_TOLERANCE),tie=bool(abs(sk[i])<=TIE_TOLERANCE)))
        matched=np.stack(matched_columns,axis=2);point=mean(matched,axis=1);counts=np.isfinite(matched).sum(axis=1)
        for block in cfg['bootstrap']['blocks']:
            started=time.monotonic();rep=int(cfg['bootstrap']['replicates']);seed=int(cfg['bootstrap']['seed'])+int(h)*100+int(block)
            draws=bootstrap_station_means(matched,len(episodes(cfg)),int(cfg['evaluation_days']),int(block),rep,seed)
            for pi,p in enumerate(pairs):
                ai=2*pi;bi=2*pi+1
                primary=p['prespecified_primary'] and constraint=='raw' and subset=='all_dates'
                alpha=.05/4 if primary else .05;sk=ratio_skill(point[:,ai],point[:,bi])
                ss=mean(ratio_skill(draws[:,:,ai],draws[:,:,bi]),axis=1);finite=ss[np.isfinite(ss)]
                bounds=np.quantile(finite,[alpha/2,1-alpha/2]) if len(finite) else [np.nan,np.nan]
                diff=mean(draws[:,:,ai]-draws[:,:,bi],axis=1);fd=diff[np.isfinite(diff)]
                db=np.quantile(fd,[alpha/2,1-alpha/2]) if len(fd) else [np.nan,np.nan]
                ratio=mean(1-ratio_skill(draws[:,:,ai],draws[:,:,bi]),axis=1);fr=ratio[np.isfinite(ratio)]
                rb=np.quantile(fr,[alpha/2,1-alpha/2]) if len(fr) else [np.nan,np.nan]
                rows.append(dict(p,constraint=constraint,subset=subset,block_days=int(block),replicates=rep,finite_replicates=len(finite),bootstrap_seed=seed,
                    mean_station_skill=mean(sk),median_station_skill=float(np.nanmedian(sk)) if np.isfinite(sk).any() else np.nan,
                    lower_ci=bounds[0],upper_ci=bounds[1],confidence_level=1-alpha,co_primary=primary,
                    equal_station_absolute_mae_difference_m3=mean(point[:,ai]-point[:,bi]),difference_lower_ci_m3=db[0],difference_upper_ci_m3=db[1],
                    mean_station_mae_ratio=mean(1-sk),ratio_lower_ci=rb[0],ratio_upper_ci=rb[1],
                    winning_stations=int((sk>TIE_TOLERANCE).sum()),negative_transfer_stations=int((sk<-TIE_TOLERANCE).sum()),
                    defined_skill_stations=int(np.isfinite(sk).sum()),zero_reference_stations=int((point[:,bi]==0).sum()),
                    minimum_paired_dates=int(counts[:,ai].min()),multiplicity_family='four B30 primary contrasts' if primary else 'exploratory pointwise'))
            progress(f'Statistics {constraint}/{subset}: h={h}, block={block}, {rep} synchronous resamples; {time.monotonic()-started:.2f}s',flush=True)
    return pd.DataFrame(rows),pd.DataFrame(site_rows)


def safe_auc(event,score):
    e=np.asarray(event,float);s=np.asarray(score,float);mask=np.isfinite(e)&np.isfinite(s)
    if mask.sum()==0 or len(np.unique(e[mask]))<2:return np.nan
    return float(roc_auc_score(e[mask],s[mask]))


def flag_metrics(event,flag,error):
    e=np.asarray(event,float);f=np.asarray(flag,float);err=np.asarray(error,float)
    mask=np.isfinite(e)&np.isfinite(f)&np.isfinite(err);e=e[mask].astype(bool);f=f[mask].astype(bool);err=err[mask]
    n=len(e);events=int(e.sum());flagged=int(f.sum());trueflags=int((e&f).sum());retained=int((~f).sum())
    return dict(n_dates=n,event_count=events,event_fraction=events/n if n else np.nan,flagged_dates=flagged,
        actual_flag_fraction=flagged/n if n else np.nan,true_flag_events=trueflags,
        flag_precision=trueflags/flagged if flagged else np.nan,
        missed_event_fraction=int((e&~f).sum())/events if events else np.nan,
        event_recall=trueflags/events if events else np.nan,retained_dates=retained,
        retained_mae_m3=float(err[~f].mean()) if retained else np.nan,all_dates_mae_m3=float(err.mean()) if n else np.nan,
        no_flags=flagged==0,all_flagged=flagged==n and n>0,single_event_class=events in (0,n) if n else True,
        precision_denominator=flagged,recall_denominator=events)


def tie_key(value):
    return hashlib.sha256(('Stage3G-risk-offline-tie-v1|'+str(value)).encode()).hexdigest()


def retention_curve(group,fractions=np.linspace(.1,1,10)):
    """Offline ranking curve, not target-selected deployment thresholds."""
    q=group[np.isfinite(group.risk_score)&np.isfinite(group.absolute_error_m3)].copy()
    q['_tie']=q.risk_row_key.map(tie_key)
    q=q.sort_values(['risk_score','_tie'],kind='mergesort')
    rows=[];n=len(q)
    for f in fractions:
        keep=int(np.ceil(float(f)*n)) if n else 0;k=q.iloc[:keep]
        rows.append(dict(retention_fraction=float(f),n_dates=n,retained_dates=keep,actual_retention_fraction=keep/n if n else np.nan,
            retained_mae_m3=k.absolute_error_m3.mean(),all_dates_mae_m3=q.absolute_error_m3.mean(),
            retained_event_fraction=k.large_error_event.mean(),posthoc_ranking_only=True,target_selected_threshold=False))
    return rows


def reliability_metrics(frame,cfg):
    p=frame.copy();p['site_id']=p.site_id.astype(str)
    for c in ['episode','origin','target_date']:p[c]=pd.to_datetime(p[c]).dt.strftime('%Y-%m-%d')
    required=['risk_score','risk_method','large_error_event','large_error_threshold_m3','absolute_error_m3','risk_row_key','review_10pct','review_20pct']+KEYS+['budget','pool_id']
    if not set(required)<=set(p):raise ValueError('Missing reliability fields: '+','.join(sorted(set(required)-set(p))))
    methods=['logistic','random','missing_rate','prediction_persistence_difference']
    if set(p.risk_method)!=set(methods):raise ValueError('Missing/unregistered risk baseline')
    planned=expected_rows(cfg)
    planned=planned[planned.model.eq(PRIMARY)][KEYS+['budget','pool_id']].merge(pd.DataFrame({'risk_method':methods}),how='cross')
    marker=planned.merge(p[KEYS+['budget','pool_id','risk_method']],on=KEYS+['budget','pool_id','risk_method'],how='outer',indicator=True,validate='one_to_one')
    if not marker._merge.eq('both').all():raise ValueError('Risk task/date set differs from full predeclared calendar')
    if 'risk_recent_input_end' in p and (pd.to_datetime(p.risk_recent_input_end)>pd.to_datetime(p.origin)).any():
        raise ValueError('Risk recent features read future input')
    if 'risk_static_information_cutoff_date' in p and (pd.to_datetime(p.risk_static_information_cutoff_date)>=pd.to_datetime(p.episode)).any():
        raise ValueError('Risk static/threshold information exceeds initial budget')
    keys=['pool_id','budget','horizon','risk_method','site_id','episode'];bywindow=[];curves=[]
    if p.duplicated(KEYS+['budget','pool_id','risk_method']).any():raise ValueError('Duplicate risk evaluation date')
    for values,g in p.groupby(keys):
        d=dict(zip(keys,values));event=g.large_error_event.to_numpy(float);scores=g.risk_score.to_numpy(float)
        for rate in [10,20]:
            valid=np.isfinite(event)&np.isfinite(scores)
            flags=g[f'review_{rate}pct'].astype(float).to_numpy();flags[~valid]=np.nan
            row=dict(d,flag_budget_pct=rate,**flag_metrics(event,flags,g.absolute_error_m3),within_site_window_auc=safe_auc(event,scores),
                mean_risk_score=g.risk_score.mean(),
                risk_score_unique=int(g.risk_score.nunique(dropna=True)),risk_scores_missing=int(g.risk_score.isna().sum()),
                event_undefined_dates=int(g.large_error_event.isna().sum()),planned_dates=int(cfg['evaluation_days']))
            bywindow.append(row)
        for row in retention_curve(g):curves.append(dict(d,**row))
    bw=pd.DataFrame(bywindow);curves=pd.DataFrame(curves)
    bysite=[];sitekeys=['pool_id','budget','horizon','risk_method','site_id']
    for values,g in p.groupby(sitekeys):
        d=dict(zip(sitekeys,values))
        for rate in [10,20]:
            sub=bw[(bw.flag_budget_pct==rate)]
            for k,v in d.items():sub=sub[sub[k]==v]
            flags=g[f'review_{rate}pct'].astype(float).to_numpy()
            flags[~np.isfinite(g.risk_score.to_numpy(float))]=np.nan
            bysite.append(dict(d,flag_budget_pct=rate,pooled_within_site_auc=safe_auc(g.large_error_event,g.risk_score),
                macro_within_window_auc=sub.within_site_window_auc.mean(),defined_within_window_auc=int(sub.within_site_window_auc.count()),
                **flag_metrics(g.large_error_event,flags,g.absolute_error_m3)))
    bs=pd.DataFrame(bysite);summ=[];groupkeys=['pool_id','budget','horizon','risk_method','flag_budget_pct']
    for values,g in bw.groupby(groupkeys):
        d=dict(zip(groupkeys,values));siteg=bs
        for k,v in d.items():siteg=siteg[siteg[k]==v]
        # Every SiteID receives equal weight; each of its windows receives equal weight.
        macro_cols=['within_site_window_auc','actual_flag_fraction','flag_precision','missed_event_fraction','retained_mae_m3','all_dates_mae_m3','event_fraction']
        per_site=g.groupby('site_id')[macro_cols].mean()
        row=dict(d,stations=len(per_site),conditions=len(g),total_event_count=int(g.event_count.sum()),total_evaluable_dates=int(g.n_dates.sum()),
            defined_within_condition_auc=int(g.within_site_window_auc.count()),undefined_single_class_conditions=int(g.single_event_class.sum()),
            no_flag_conditions=int(g.no_flags.sum()),all_flag_conditions=int(g.all_flagged.sum()))
        row.update({'macro_'+c:per_site[c].mean() for c in macro_cols});row['macro_pooled_within_site_auc']=siteg.pooled_within_site_auc.mean()
        # Between-condition score/event-rate association describes a different task.
        raw=p
        for k,v in {k:v for k,v in d.items() if k!='flag_budget_pct'}.items():raw=raw[raw[k]==v]
        conditions=raw.groupby(['site_id','episode']).agg(mean_risk=('risk_score','mean'),event_rate=('large_error_event','mean'))
        row['between_condition_risk_event_spearman']=conditions.mean_risk.corr(conditions.event_rate,method='spearman') if conditions.mean_risk.nunique()>1 and conditions.event_rate.nunique()>1 else np.nan
        row['pooled_all_dates_auc']=safe_auc(raw.large_error_event,raw.risk_score)
        summ.append(row)
    curvekeys=['pool_id','budget','horizon','risk_method','retention_fraction']
    cs=curves.groupby(curvekeys+['site_id'])[['retained_mae_m3','all_dates_mae_m3','retained_event_fraction','actual_retention_fraction']].mean().reset_index()
    cs=cs.groupby(curvekeys).agg(retained_mae_m3=('retained_mae_m3','mean'),all_dates_mae_m3=('all_dates_mae_m3','mean'),
        retained_event_fraction=('retained_event_fraction','mean'),actual_retention_fraction=('actual_retention_fraction','mean'),stations=('site_id','size')).reset_index()
    cs['posthoc_ranking_only']=True;cs['target_selected_threshold']=False
    return bw,bs,pd.DataFrame(summ),curves,cs


def save(frame,out,name):
    from .stage3g_source import atomic_csv
    return atomic_csv(out/name,frame)


def summarize(frame,cfg,out,integrity,shuffle=None,risk=None,progress=print):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);started=time.monotonic()
    from .stage3e_runtime import atomic_json
    atomic_json(out/'evaluation_validation.json',dict(status='RUNNING',
        work='Saved-row evaluation only; no model fits',started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
    p=prepare_predictions(frame,cfg);save(p,out,'predictions_all.csv.gz')
    avail=p.groupby(TASK_KEYS).agg(planned_origins=('origin','size'),saved_prediction_rows=('prediction_row_present','sum'),
        valid_truths=('finite_truth','sum'),finite_predictions=('finite_prediction','sum'),common_dates=('common_evaluation','sum'),
        negative_predictions=('prediction_m3',lambda x:int(x.lt(0).sum()))).reset_index()
    avail['prediction_coverage']=avail.finite_predictions/avail.planned_origins;save(avail,out,'availability.csv')
    save(p[p.prediction_failure_reason.ne('')][ROW_KEYS+['prediction_failure_reason']],out,'missing_or_failed_predictions.csv.gz')
    idx=p.groupby(KEYS).agg(common_evaluation=('common_evaluation','first'),truth_m3=('truth_m3','first'),high_threshold_m3=('high_threshold_m3','first'),
        expected_condition_rows=('model','size'),saved_rows=('prediction_row_present','sum'),finite_predictions=('finite_prediction','sum')).reset_index()
    save(idx,out,'paired_evaluation_index.csv.gz')
    save(paired_date_index(p,cfg),out,'paired_date_index.csv.gz')
    daily=daily_losses(p);save(daily,out,'daily_losses.csv.gz')
    metric=station_metrics(daily,cfg);save(metric,out,'metrics_by_station.csv');save(aggregate_metrics(metric),out,'summary.csv')
    wm=station_metrics(daily,cfg,True);save(wm,out,'metrics_by_station_window.csv');save(aggregate_metrics(wm,True),out,'summary_by_window.csv')
    strict=daily.merge(idx[KEYS+['common_evaluation']],on=KEYS,validate='many_to_one')
    strict=station_metrics(strict[strict.common_evaluation],cfg)
    save(strict,out,'strict_all_model_common_date_metrics_by_station.csv');save(aggregate_metrics(strict),out,'strict_all_model_common_date_summary.csv')
    high=daily[daily.high_volume];hm=station_metrics(high,cfg);save(hm,out,'high_volume_metrics_by_station.csv');save(aggregate_metrics(hm),out,'high_volume_summary.csv')
    allci=[];allpairs=[];highci=[];highpairs=[]
    for constraint in ['raw','all_models_nonnegative']:
        ci,pair=paired_intervals(daily,cfg,constraint,progress=progress);allci.append(ci);allpairs.append(pair)
        ci,pair=paired_intervals(daily,cfg,constraint,'historical_high_volume',progress=progress);highci.append(ci);highpairs.append(pair)
    ci=pd.concat(allci,ignore_index=True);pair=pd.concat(allpairs,ignore_index=True)
    save(ci,out,'paired_block_intervals.csv');save(pair,out,'paired_comparisons_by_station.csv')
    save(pd.concat(highci,ignore_index=True),out,'high_volume_block_intervals.csv');save(pd.concat(highpairs,ignore_index=True),out,'high_volume_paired_by_station.csv')
    save(pair[pair.kind.eq('history_budget_comparison')],out,'cross_budget_by_station.csv');save(ci[ci.kind.eq('history_budget_comparison')],out,'cross_budget_intervals.csv')
    transfer=pair[pair.kind.eq('same_budget_transfer')].groupby(['constraint','pool_id','model','budget','horizon','reference']).agg(
        stations=('site_id','size'),defined_skill_stations=('skill','count'),mean_skill_vs_local=('skill','mean'),median_skill_vs_local=('skill','median'),
        negative_transfer_stations=('negative_transfer','sum'),winning_stations=('win','sum')).reset_index()
    transfer['negative_transfer_fraction']=transfer.negative_transfer_stations/transfer.defined_skill_stations.where(transfer.defined_skill_stations.gt(0));save(transfer,out,'negative_transfer_summary.csv')
    save(pair[pair.zero_reference_mae],out,'zero_reference_comparisons.csv')
    params=TASK_KEYS+[x for x in ['alpha','shrinkage','eta','bias_m3','scale_m3','training_labels','validation_labels','source_assisted_tuning',
        'effective_source_count','maximum_source_weight','initial_source_target_difference','uniform_fallback','fit_end','budget_start'] if x in p]
    choices=p[params].drop_duplicates()
    if choices.duplicated(TASK_KEYS).any():raise ValueError('Frozen parameters changed during deployment')
    save(choices,out,'parameter_choices.csv')
    if 'eta' in choices:
        w=choices[choices.model.isin([PRIMARY,'similarity_residual_ridge_selected'])].copy()
        w['bias_normalized']=w.bias_m3/w.scale_m3
        agg=dict(tasks=('episode','size'),eta_zero=('eta',lambda x:int(x.eq(0).sum())),
            mean_absolute_bias_m3=('bias_m3',lambda x:float(x.abs().mean())),mean_absolute_bias_normalized=('bias_normalized',lambda x:float(x.abs().mean())))
        if 'uniform_fallback' in w:agg['uniform_descriptor_fallbacks']=('uniform_fallback','sum')
        if 'effective_source_count' in w:agg['mean_effective_source_count']=('effective_source_count','mean')
        if 'maximum_source_weight' in w:agg['mean_maximum_source_weight']=('maximum_source_weight','mean')
        weighting=w.groupby(['pool_id','model','budget','horizon']).agg(**agg).reset_index()
        weighting['eta_zero_fraction']=weighting.eta_zero/weighting.tasks
        if 'uniform_descriptor_fallbacks' in weighting:weighting['descriptor_fallback_fraction']=weighting.uniform_descriptor_fallbacks/weighting.tasks
        save(weighting,out,'weighting_diagnostics_summary.csv')
    if 'shrinkage' in choices:
        fb=choices.groupby(['pool_id','model','budget','horizon']).agg(tasks=('episode','size'),lambda_zero=('shrinkage',lambda x:int(x.eq(0).sum()))).reset_index()
        fb['lambda_zero_fraction']=fb.lambda_zero/fb.tasks;save(fb,out,'lambda_fallback.csv')
    if risk is not None:
        reference=p[p.model.eq(PRIMARY)][KEYS+['budget','pool_id','prediction_m3','truth_m3','scale_m3']]
        scored=risk.merge(reference,on=KEYS+['budget','pool_id'],how='left',validate='many_to_one',suffixes=('','_point'))
        for c in ['prediction_m3','truth_m3','scale_m3']:
            if not np.allclose(scored[c],scored[c+'_point'],atol=1e-8,rtol=1e-12,equal_nan=True):raise ValueError('Risk evaluation point data differ: '+c)
        actual=(scored.prediction_m3-scored.truth_m3).abs()
        if not np.allclose(scored.absolute_error_m3,actual,atol=1e-8,rtol=1e-12,equal_nan=True):raise ValueError('Risk outcome absolute error differs')
        valid=scored.large_error_event.notna()
        declared=(actual>scored.large_error_threshold_m3).astype(float)
        if not np.array_equal(scored.loc[valid,'large_error_event'].to_numpy(float),declared[valid].to_numpy(float)):
            raise ValueError('Large-error event differs from frozen initial-error threshold definition')
        tables=reliability_metrics(risk,cfg)
        for table,name in zip(tables,['reliability_by_site_window.csv','reliability_by_station.csv','reliability_summary.csv','risk_retention_curves.csv','risk_retention_summary.csv']):save(table,out,name)
        rk=['site_id','episode','budget','horizon','pool_id','risk_method']
        available=risk.groupby(rk).agg(planned_origins=('origin','size'),finite_risk_scores=('risk_score','count'),
            defined_events=('large_error_event','count'),flag10_available=('review_10pct','count'),flag20_available=('review_20pct','count'),
            zero_initial_error_threshold=('large_error_threshold_m3',lambda x:int(x.eq(0).sum())),
            point_forecast_available=('prediction_m3',lambda x:int(np.isfinite(x).sum())),valid_truths=('truth_m3',lambda x:int(np.isfinite(x).sum()))).reset_index()
        available['risk_score_coverage']=available.finite_risk_scores/available.planned_origins;save(available,out,'reliability_availability.csv')
    if shuffle is not None and len(shuffle):evaluate_shuffle(shuffle,p,cfg,out)
    complete=bool(integrity.get('all_expected_tasks_verified',False)) and not (~p.prediction_row_present).any()
    status=dict(status='COMPLETED' if complete else 'PARTIAL',experiment_integrity=integrity,planned_prediction_rows=len(p),
        saved_prediction_rows=int(p.prediction_row_present.sum()),common_calendar_groups=int(idx.common_evaluation.sum()),planned_calendar_groups=len(idx),
        new_model_training_in_evaluation=False,physical_mapping_verified=False,verified_real_time=False,final_2024_2025_performance_used=False,
        date_matching='Pair-specific candidate/reference finite truth and prediction dates; all planned dates/availability retained. Strict all-model common calendar is a separate sensitivity/trace',
        seed_aggregation='Shuffle seed results and arithmetic mean daily losses only, never averaged predictions or extra independent stations',
        multiplicity='Four B30 primary comparisons: Bonferroni 98.75%; other comparisons exploratory 95%',
        statistical_unit='Exploratory SiteID; synchronous noncircular blocks inside each 60-day deployment then whole-SiteID bootstrap',
        no_engineering_noninferiority_margin=True,statistics_seconds=time.monotonic()-started,finished_utc=utc_now(),
        files_sha256={f.name:sha256(f) for f in sorted(out.iterdir()) if f.is_file() and f.name!='evaluation_validation.json'})
    atomic_json(out/'evaluation_validation.json',status)
    for member,expected in status['files_sha256'].items():
        if sha256(out/member)!=expected:raise IOError('Evaluation writeback SHA mismatch: '+member)
    return status


def evaluate_shuffle(shuffle,main,cfg,out):
    """Mechanism ablation: fixed settings, three loss replicates, no ensemble."""
    q=shuffle.copy();q['site_id']=q.site_id.astype(str)
    for c in ['episode','origin','target_date']:q[c]=pd.to_datetime(q[c]).dt.strftime('%Y-%m-%d')
    seeds=list(cfg.get('shuffle',{}).get('seeds',[20261014,20261015,20261016]));mainpool=cfg.get('primary_pool_id',MAIN_POOL)
    if set(q.seed.astype(int))!=set(seeds):raise ValueError('Missing/unregistered shuffle seeds')
    planned=len(cfg['development_ids'])*len(episodes(cfg))*len(cfg['horizons'])*int(cfg['evaluation_days'])*len(seeds)
    if len(q)!=planned or not q.pool_id.eq(mainpool).all() or not q.budget.eq(30).all():raise ValueError('Incomplete fixed shuffle ablation')
    if q.duplicated(KEYS+['seed']).any():raise ValueError('Duplicate shuffle forecast')
    base=main[main.pool_id.eq(mainpool)&main.budget.eq(30)&main.model.eq(PRIMARY)][KEYS+['forecast_eligible','prediction_m3','truth_m3']]
    q=q.merge(base,on=KEYS,validate='many_to_one',suffixes=('','_weighted'))
    if not np.allclose(q.truth_m3,q.truth_m3_weighted,atol=1e-8,rtol=1e-12,equal_nan=True):raise ValueError('Shuffle truth differs')
    q['paired_evaluation']=q.forecast_eligible&np.isfinite(q.prediction_m3)
    save(q,out,'shuffle_paired_date_index.csv.gz')
    daily=[]
    for constraint in ['raw','all_models_nonnegative']:
        valid=q[q.paired_evaluation].copy()
        pred=valid.prediction_m3 if constraint=='raw' else np.maximum(0.,valid.prediction_m3)
        candidate=valid.prediction_m3_weighted if constraint=='raw' else np.maximum(0.,valid.prediction_m3_weighted)
        valid['absolute_error']=(pred-valid.truth_m3).abs();valid['squared_error']=(pred-valid.truth_m3)**2
        valid['weighted_absolute_error']=(candidate-valid.truth_m3).abs();valid['constraint']=constraint;daily.append(valid)
    q=pd.concat(daily,ignore_index=True);save(q,out,'shuffle_daily_losses.csv.gz')
    keys=['constraint','site_id','horizon','seed']
    metric=q.groupby(keys).agg(n_dates=('origin','size'),mae_m3=('absolute_error','mean'),mse=('squared_error','mean'),weighted_mae_m3=('weighted_absolute_error','mean')).reset_index()
    metric['rmse_m3']=np.sqrt(metric.pop('mse'));metric['weighted_skill_vs_shuffle']=ratio_skill(metric.weighted_mae_m3,metric.mae_m3)
    save(metric,out,'shuffle_metrics_by_station_seed.csv')
    lossmean=q.groupby(KEYS+['constraint']).agg(shuffle_mean_absolute_error=('absolute_error','mean'),shuffle_mean_squared_error=('squared_error','mean'),
        weighted_absolute_error=('weighted_absolute_error','first'),seed_count=('seed','nunique')).reset_index()
    # A mean of three seed losses is defined only when all three are available.
    # Individual seeds still retain their separate availability/metrics above.
    lossmean['all_seeds_available']=lossmean.seed_count.eq(len(seeds))
    lossmean.loc[~lossmean.all_seeds_available,['shuffle_mean_absolute_error','shuffle_mean_squared_error','weighted_absolute_error']]=np.nan
    save(lossmean,out,'shuffle_seed_mean_daily_losses.csv.gz')
    metricmean=lossmean[lossmean.all_seeds_available].groupby(['constraint','site_id','horizon']).agg(n_dates=('origin','size'),mae_m3=('shuffle_mean_absolute_error','mean'),
        mse=('shuffle_mean_squared_error','mean'),weighted_mae_m3=('weighted_absolute_error','mean')).reset_index()
    metricmean['rmse_m3']=np.sqrt(metricmean.pop('mse'));metricmean['weighted_skill_vs_shuffle']=ratio_skill(metricmean.weighted_mae_m3,metricmean.mae_m3)
    metricmean['aggregation']='arithmetic mean daily losses across three fixed seeds, no prediction ensemble'
    save(metricmean,out,'shuffle_seed_mean_metrics_by_station.csv')
    cis=[];sites=list(map(str,cfg['development_ids']));eps=episodes(cfg);length=int(cfg['evaluation_days'])
    for constraint,h in itertools.product(['raw','all_models_nonnegative'],cfg['horizons']):
        matched=np.full((len(sites),len(eps)*length,2*(len(seeds)+1)),np.nan)
        for i,seed in enumerate(seeds+['seed_loss_mean']):
            if seed=='seed_loss_mean':
                z=lossmean[lossmean.constraint.eq(constraint)&lossmean.horizon.eq(h)&lossmean.all_seeds_available]
                values=z.shuffle_mean_absolute_error
            else:
                z=q[q.constraint.eq(constraint)&q.horizon.eq(h)&q.seed.eq(seed)];values=z.absolute_error
            si=z.site_id.map({s:k for k,s in enumerate(sites)}).to_numpy()
            di=z.episode.map({e:k for k,e in enumerate(eps)}).to_numpy()*length+(pd.to_datetime(z.origin)-pd.to_datetime(z.episode)).dt.days.to_numpy()
            matched[si,di,2*i]=z.weighted_absolute_error.to_numpy();matched[si,di,2*i+1]=values.to_numpy()
        point=mean(matched,axis=1)
        for block in cfg['bootstrap']['blocks']:
            n=int(cfg['bootstrap']['replicates']);bsseed=int(cfg['bootstrap']['seed'])+int(h)*100+int(block)
            draws=bootstrap_station_means(matched,len(eps),length,int(block),n,bsseed)
            for i,seed in enumerate(seeds+['seed_loss_mean']):
                skills=ratio_skill(point[:,2*i],point[:,2*i+1]);samples=mean(ratio_skill(draws[:,:,2*i],draws[:,:,2*i+1]),axis=1)
                finite=samples[np.isfinite(samples)];bounds=np.quantile(finite,[.025,.975]) if len(finite) else [np.nan,np.nan]
                cis.append(dict(constraint=constraint,horizon=h,shuffle_seed=seed,block_days=int(block),replicates=n,bootstrap_seed=bsseed,
                    mean_station_skill=mean(skills),lower_ci=bounds[0],upper_ci=bounds[1],confidence_level=.95,exploratory=True,
                    prediction_ensemble=False,permutation_significance_test=False,defined_skill_stations=int(np.isfinite(skills).sum())))
    save(pd.DataFrame(cis),out,'shuffle_mechanism_block_intervals.csv')
