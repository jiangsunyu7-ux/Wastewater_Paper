"""Synthetic boundary fixtures: none are evidence about actual facilities."""
import unittest

import numpy as np
import pandas as pd

from wastewater.stage3c2_evaluation import bootstrap_station_means, calendar_draw_indices
from wastewater.stage3g_evaluation import (
    MAIN_POOL, MODELS, PRIMARY, LOCAL, expected_rows, prepare_predictions,
    daily_losses, station_metrics, ratio_skill, flag_metrics, safe_auc,
    retention_curve, paired_date_index,
    reliability_metrics,
)


class Stage3GEvaluationTests(unittest.TestCase):
    def config(self):
        return dict(development_ids=['13013'],origins=['2023-07-01'],budgets=[30,90,180],
            horizons=[1,3],evaluation_days=4,pools=[dict(pool_id=MAIN_POOL)],
            bootstrap=dict(blocks=[1,2],replicates=20,seed=20261014))

    def fixture(self):
        cfg=self.config();p=expected_rows(cfg)
        p['truth_m3']=100.;p['prediction_m3']=110.;p['scale_m3']=100.;p['high_threshold_m3']=150.
        p['fit_end']='2023-06-30'
        p['budget_start']=(pd.to_datetime(p.episode)-pd.to_timedelta(p.budget,unit='D')).dt.strftime('%Y-%m-%d')
        p['latest_input_date']=p.origin
        return p,cfg

    def test_zero_reference_is_undefined(self):
        s=ratio_skill([0,1,2],[0,0,4])
        self.assertTrue(np.isnan(s[:2]).all());self.assertEqual(s[2],.5)
        f=flag_metrics([0,0],[0,0],[1,2])
        self.assertTrue(np.isnan(f['flag_precision']));self.assertTrue(np.isnan(f['missed_event_fraction']))
        self.assertEqual(f['precision_denominator'],0);self.assertEqual(f['all_dates_mae_m3'],1.5)

    def test_all_flagged_and_single_class(self):
        f=flag_metrics([1,1],[1,1],[4,8])
        self.assertTrue(f['all_flagged']);self.assertTrue(np.isnan(f['retained_mae_m3']))
        self.assertTrue(np.isnan(safe_auc([1,1],[.2,.9])))
        self.assertEqual(safe_auc([0,1],[.1,.9]),1.)

    def test_pair_dates_ignore_unrelated_missing_policy(self):
        p,cfg=self.fixture()
        bad=p.model.eq('weekly_persistence')&p.budget.eq(90)&p.horizon.eq(1)&p.origin.eq('2023-07-01')
        p.loc[bad,'prediction_m3']=np.nan
        checked=prepare_predictions(p,cfg)
        unavailable=checked.model.eq('weekly_persistence')&checked.budget.eq(90)&checked.horizon.eq(1)&checked.origin.eq('2023-07-01')
        self.assertFalse(checked.loc[unavailable,'common_evaluation'].iloc[0])
        metric=station_metrics(daily_losses(checked),cfg)
        candidate=metric[metric.model.eq(PRIMARY)&metric.budget.eq(30)&metric.horizon.eq(1)&metric.constraint.eq('raw')].iloc[0]
        self.assertEqual(candidate.paired_dates_vs_persistence,4)
        idx=paired_date_index(checked,cfg)
        q=idx[idx.model.eq(PRIMARY)&idx.reference.eq('persistence')&idx.budget.eq(30)&idx.horizon.eq(1)]
        self.assertEqual(int(q.paired_evaluation.sum()),4)
        weekly=metric[metric.model.eq('weekly_persistence')&metric.budget.eq(90)&metric.horizon.eq(1)&metric.constraint.eq('raw')].iloc[0]
        self.assertEqual(weekly.paired_dates_vs_persistence,3)

    def test_wrong_input_or_label_boundaries_rejected(self):
        p,cfg=self.fixture();p.loc[0,'latest_input_date']='2024-01-01'
        with self.assertRaisesRegex(ValueError,'Future'):prepare_predictions(p,cfg)
        p,cfg=self.fixture();p.loc[0,'fit_end']='2023-07-01'
        with self.assertRaisesRegex(ValueError,'cutoff'):prepare_predictions(p,cfg)
        p,cfg=self.fixture();p.loc[0,'target_date']='2023-07-08'
        with self.assertRaisesRegex(ValueError,'Unregistered'):prepare_predictions(p,cfg)

    def test_lambda_zero_identity(self):
        p,cfg=self.fixture();p['shrinkage']=1.
        q=p.model.isin([LOCAL,PRIMARY]);p.loc[q,'shrinkage']=0.
        prepare_predictions(p,cfg)
        p.loc[q,'prediction_m3']=109.
        with self.assertRaisesRegex(ValueError,'lambda=0'):prepare_predictions(p,cfg)

    def test_nonnegative_rule_applies_identically(self):
        p,cfg=self.fixture();p['prediction_m3']=-1.;p['prediction_nonnegative_m3']=0.
        prepare_predictions(p,cfg);p.loc[0,'prediction_nonnegative_m3']=1.
        with self.assertRaisesRegex(ValueError,'nonnegative'):prepare_predictions(p,cfg)

    def test_offline_tie_order_never_uses_truth(self):
        p=pd.DataFrame(dict(risk_score=[.5,.5,.5,.5],risk_row_key=['a','b','c','d'],absolute_error_m3=[1,2,10,20],large_error_event=[0,0,1,1]))
        c=retention_curve(p,[.5,1.]);rev=retention_curve(p.iloc[::-1],[.5,1.])
        self.assertEqual(c,rev);self.assertTrue(c[0]['posthoc_ranking_only']);self.assertFalse(c[0]['target_selected_threshold'])

    def test_block_means_retain_missing_calendar_positions(self):
        # Two paired losses share their masks. A third method's unavailable
        # date is irrelevant to this pair, and no deleted calendar is created.
        a=np.array([[[1,2],[np.nan,np.nan],[3,6],[4,8],[5,10],[6,12]],
                    [[2,1],[4,2],[6,3],[np.nan,np.nan],[10,5],[12,6]]],float)
        rep=30;seed=42
        means=bootstrap_station_means(a,1,6,2,rep,seed)
        direct=[]
        for si,ti in calendar_draw_indices(2,1,6,2,rep,seed):
            with np.errstate(invalid='ignore'):
                direct.append(np.nanmean(a[:,ti,:],axis=1)[si,:])
        np.testing.assert_allclose(means,np.array(direct),atol=1e-12,rtol=1e-12,equal_nan=True)

    def test_risk_macro_separates_within_window_and_single_class(self):
        p,cfg=self.fixture();p=p[p.model.eq(PRIMARY)].copy();parts=[]
        for method in ['logistic','random','missing_rate','prediction_persistence_difference']:
            q=p.copy();q['risk_method']=method;q['risk_score']=.5
            q['large_error_event']=0.;q['large_error_threshold_m3']=10.;q['absolute_error_m3']=10.
            q['risk_row_key']=q.index.astype(str);q['review_10pct']=0.;q['review_20pct']=1.;parts.append(q)
        bw,bs,summary,curve,cs=reliability_metrics(pd.concat(parts,ignore_index=True),cfg)
        self.assertTrue(bw.within_site_window_auc.isna().all())
        self.assertTrue(summary.macro_within_site_window_auc.isna().all())
        self.assertTrue(summary.pooled_all_dates_auc.isna().all())
        self.assertTrue(bw[bw.flag_budget_pct.eq(10)].flag_precision.isna().all())
        self.assertTrue(bw[bw.flag_budget_pct.eq(20)].retained_mae_m3.isna().all())
        self.assertTrue(curve.posthoc_ranking_only.all());self.assertFalse(curve.target_selected_threshold.any())


if __name__=='__main__':unittest.main()
