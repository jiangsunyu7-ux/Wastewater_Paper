"""Synthetic fixtures only: no assertions about real physical independence."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import pandas as pd
from wastewater import stage3g_source as source
from wastewater import stage3g_experiment as experiment
from wastewater.stage3e_runtime import atomic_bytes,atomic_json,FingerprintMismatch


class SourceRunnerTests(unittest.TestCase):
    def test_connected_group_fold_never_splits_and_order_invariant(self):
        ids=[str(x) for x in range(7)];groups={s:'g'+str(int(s)//2) for s in ids}
        first=source.group_folds(ids,groups,3)
        self.assertEqual(first,source.group_folds(ids[::-1],groups,3))
        self.assertEqual(first['0'],first['1']);self.assertEqual(first['2'],first['3'])

    def test_selection_ties_use_frozen_eta_lambda_alpha_order(self):
        rows=[]
        for family in source.FAMILIES:
            for eta,lam,alpha,score in [(.9,0.,.01,.1),(0.,.5,.1,.1+5e-13),(0.,0.,1.,.1+8e-13),(0.,0.,.01,.1+9e-13)]:
                rows.append(dict(model=family,eta=eta,shrinkage=lam,alpha=alpha,validation_mae=score,
                                 held_site_id='synthetic',episode='2021-01-01'))
        selected=source.choose(rows)
        for family in source.FAMILIES:
            self.assertEqual(selected[family]['eta'],0.)
            self.assertEqual(selected[family]['shrinkage'],0.)
            self.assertEqual(selected[family]['alpha'],.01)

    def test_completed_cache_needs_present_unchanged_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);atomic_bytes(folder/'required.txt',b'synthetic fixture')
            atomic_json(folder/'status.json',dict(status='COMPLETED',fingerprint='expected',write_verified=True,
                outputs_sha256={'required.txt':source.sha256(folder/'required.txt')}))
            self.assertTrue(source.validate_cache(folder,'expected',{'required.txt'}))
            atomic_bytes(folder/'required.txt',b'corrupted fixture')
            self.assertFalse(source.validate_cache(folder,'expected',{'required.txt'}))
            with self.assertRaises(FingerprintMismatch):source.validate_cache(folder,'other',{'required.txt'})

    def test_running_partial_status_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);atomic_json(folder/'status.json',dict(status='RUNNING',fingerprint='expected',write_verified=True))
            self.assertFalse(source.validate_cache(folder,'expected',set()))

    def test_budget_internal_descriptor_only_uses_train_prefix(self):
        dates=pd.date_range('2016-01-01','2023-12-31')
        data=pd.Series(100+10*np.sin(np.arange(len(dates))/7),index=dates)
        series={'synthetic_target':data,'s1':data*1.2,'s2':data*.8}
        cfg=dict(ridge_alphas=[.0001,.001,.01,.1,1.,10.],lambdas=[0,.25,.5,1.],
            etas=[0,.5,.9],local_validation_fraction=.2,validation_min_fit_labels=30,
            validation_min_labels=10,min_train_labels=14,source_training_start='2016-01-01')
        fallback={m:dict(alpha=.1,shrinkage=1.,eta=.5 if m in(source.WEIGHTED,source.WEIGHTED_BIAS) else 0.) for m in source.FAMILIES}
        pool=dict(pool_id='synthetic_pool',site_ids=['s1','s2'])
        selected=dict(parameters={'B90_H3':fallback})
        first,fold,_=experiment.target_selection(data,'2022-01-01',90,3,cfg,pool,selected,fallback,series)
        changed=data.copy();changed.loc[pd.Timestamp(fold['fit_end'])+pd.Timedelta(days=1):]*=3
        # Changing validation labels may change chosen alpha/lambda, but must not affect prefix descriptor.
        _,fold2,_=experiment.target_selection(changed,'2022-01-01',90,3,cfg,pool,selected,fallback,series)
        self.assertEqual(fold['descriptor_target'],fold2['descriptor_target'])
        self.assertEqual(fold['source_descriptor_matching_calendar_days'],72)
        self.assertLess(pd.Timestamp(fold['last_fit_target']),pd.Timestamp(fold['validation_start']))

    def test_synthetic_full_job_resume_and_future_independence(self):
        dates=pd.date_range('2016-01-01','2023-12-31');t=np.arange(len(dates))
        series={site:pd.Series(100+index*20+10*np.sin(t/(5+index))+.003*t,index=dates)
                for index,site in enumerate(['13013','s1','s2'])}
        cfg=dict(ridge_alphas=[.0001,.001,.01,.1,1.,10.],lambdas=[0,.25,.5,1.],etas=[0,.5,.9],
            local_validation_fraction=.2,validation_min_fit_labels=30,validation_min_labels=10,
            min_train_labels=14,source_training_start='2016-01-01',evaluation_days=60,
            high_volume_history_days=30,high_volume_quantile=.9,primary_pool_id='order20261012_K30',
            shuffle={'seeds':[20261014,20261015,20261016]},max_attempts=2)
        cfg['pools']=[dict(pool_id=f'order{label}_K30',site_ids=['s1','s2']) for label in(20261012,20261013,20261014)]
        fallback={model:dict(alpha=.1,shrinkage=1. if model==source.LOCAL_DIRECT else 0.,
                   eta=0.,source_assisted=True) for model in source.FAMILIES}
        selections={pool['pool_id']:dict(parameters={'B30_H3':fallback}) for pool in cfg['pools']}
        task=('13013','2022-01-01',30,3)
        with tempfile.TemporaryDirectory() as first,tempfile.TemporaryDirectory() as second:
            result=experiment.run_target(task,cfg,series,selections,'synthetic-fingerprint',first)
            self.assertEqual(result['status'],'COMPLETED',result)
            cached=experiment.run_target(task,cfg,series,selections,'synthetic-fingerprint',first)
            self.assertEqual(cached['status'],'CACHED_VERIFIED')
            changed={key:value.copy() for key,value in series.items()}
            for value in changed.values():value.loc['2022-03-05':]*=7
            repeated=experiment.run_target(task,cfg,changed,selections,'synthetic-fingerprint',second)
            self.assertEqual(repeated['status'],'COMPLETED',repeated)
            a=pd.read_csv(Path(first)/'jobs'/experiment.task_key(task)/'predictions.csv')
            b=pd.read_csv(Path(second)/'jobs'/experiment.task_key(task)/'predictions.csv')
            pd.testing.assert_frame_equal(a,b)
            reference=a[a.model.eq('persistence')].set_index(['pool_id','origin']).prediction_m3
            for model in(source.LOCAL_RESIDUAL,source.UNIFORM,source.UNIFORM_BIAS,source.WEIGHTED,source.WEIGHTED_BIAS):
                actual=a[a.model.eq(model)].set_index(['pool_id','origin']).prediction_m3
                pd.testing.assert_series_equal(actual,reference)


if __name__=='__main__':unittest.main()
