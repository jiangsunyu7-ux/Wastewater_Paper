"""Synthetic fixtures only; these tests do not verify real facility identities."""
import unittest
import numpy as np
import pandas as pd

from wastewater.stage3g_reliability import (FEATURES, RiskModel, fit_risk_model,
    weighted_left_quantile, equal_site_window_weights, recent_risk_features,
    initial_error_threshold, large_error_events, operating_threshold,
    apply_operating_threshold, fit_source_crossfit, score_target_risk)


def training_fixture():
    return pd.DataFrame(dict(site_id=['a']*4+['b']*4, episode=['one']*8,
        initial_source_target_difference=[0,1,0,2,0,2,1,2],
        recent_input_missing_fraction=[0,0,.1,.2,0,.1,.2,.1],
        recent_volume_change_normalized=[0,1,0,2,0,2,1,2],
        large_error_event=[0,0,1,1,0,1,0,1]))


def crossfit_fixture():
    rows=[]
    for outer in range(5):
        for role,fold in [('outer_evaluation',outer),('risk_train',(outer+1)%5),
                          ('threshold_calibration',(outer+2)%5)]:
            for group in range(fold*2,(fold+1)*2):
                for origin in range(4):
                    rows.append(dict(pool_id='fixture',budget=30,horizon=1,
                        outer_fold=outer,role=role,site_id=f's{group}',group_id=f'g{group}',
                        episode='2021-01-01',origin=f'2021-01-{origin+1:02d}',row_key=f'{outer}|{group}|{origin}',
                        initial_source_target_difference=group/10,
                        recent_input_missing_fraction=origin/10,
                        recent_volume_change_normalized=(origin%2)/10,
                        large_error_event=origin%2,prediction_m3=10+origin,
                        persistence_m3=10,scale_m3=10,truth_m3=10+2*origin))
    return pd.DataFrame(rows)


def test_left_quantile_observed_support_zero_and_no_interpolation():
    assert weighted_left_quantile(np.arange(10),.9)==8
    assert weighted_left_quantile([0,0,9],.5)==0
    assert weighted_left_quantile([0,3],.5,[1,1])==0
    with unittest.TestCase().assertRaises(ValueError):weighted_left_quantile([], .9)


def test_site_window_weights_do_not_reward_long_series():
    frame=pd.DataFrame(dict(site_id=['a']*5+['b'],episode=['x']*4+['y','x']))
    weights=equal_site_window_weights(frame)
    np.testing.assert_allclose(weights[:4].sum(),.25)
    np.testing.assert_allclose(weights[4],.25)
    np.testing.assert_allclose(weights[5],.5)


def test_recent_features_true_zero_calendar_missing_and_future_invariance():
    dates=pd.date_range('2020-01-01',periods=20)
    series=pd.Series(np.arange(20,dtype=float),index=dates);series.iloc[2]=np.nan
    r=recent_risk_features(series,dates[5],dates[0],2)
    assert r['recent_input_calendar_days']==6 and r['recent_valid_inputs']==5
    np.testing.assert_allclose(r['recent_input_missing_fraction'],1/6)
    assert r['recent_volume_change_normalized']==.5
    changed=series.copy();changed.iloc[6:]=1e9;changed.iloc[:2]=0
    first=recent_risk_features(series,dates[5],dates[2],2)
    second=recent_risk_features(changed,dates[5],dates[2],2)
    assert first==second


def test_initial_calibration_h3_boundary_and_constant_zero_threshold():
    dates=pd.date_range('2020-01-01',periods=35)
    s=pd.Series(0.,index=dates)
    d=initial_error_threshold(s,dates[0],dates[29],3)
    assert d['initial_error_samples']==27
    assert d['threshold_last_label']=='2020-01-30'
    assert d['large_error_threshold_m3']==0 and d['initial_error_threshold_zero']
    np.testing.assert_array_equal(large_error_events([0,1],[0,0],0),[0,1])
    s.iloc[30:]=100000
    assert initial_error_threshold(s,dates[0],dates[29],3)==d
    insufficient=initial_error_threshold(s,dates[20],dates[29],3)
    assert not insufficient['initial_error_threshold_defined']
    assert np.isnan(insufficient['large_error_threshold_m3'])


def test_imputer_and_standardizer_use_training_only():
    train=training_fixture();model=fit_risk_model(train)
    before=model.predict(train)
    evaluated=train.copy();evaluated.loc[:,FEATURES[0]]=1e9
    model.predict(evaluated)
    np.testing.assert_array_equal(model.predict(train),before)
    changed=train.copy();changed[FEATURES[2]]=np.nan
    allmissing=fit_risk_model(changed)
    assert allmissing.diagnostics['all_missing_features_imputed_to_zero']==[FEATURES[2]]
    assert np.isfinite(allmissing.predict(changed)).all()


def test_single_class_and_no_label_are_explicit():
    f=training_fixture();f.large_error_event=1
    model=fit_risk_model(f)
    assert model.status=='SINGLE_CLASS_CONSTANT'
    np.testing.assert_array_equal(model.predict(f),np.ones(len(f)))
    f.large_error_event=np.nan;model=fit_risk_model(f)
    assert model.status=='NO_TRAINING_LABELS'
    assert np.isnan(model.predict(f)).all()


def test_threshold_ties_use_expected_mass_and_truth_independent_hash():
    threshold=operating_threshold(np.zeros(10),np.ones(10),.2)
    assert threshold['score_threshold']==0
    np.testing.assert_allclose(threshold['tie_fraction'],.2)
    np.testing.assert_allclose(threshold['expected_calibration_mark_fraction'],.2)
    keys=[f'k{i}' for i in range(20)]
    one=apply_operating_threshold(np.zeros(20),keys,threshold,'missing_rate')
    two=apply_operating_threshold(np.zeros(20),keys,threshold,'missing_rate')
    np.testing.assert_array_equal(one,two)
    missing=operating_threshold([np.nan],[1],.1)
    assert np.isnan(apply_operating_threshold([1],['one'],missing,'logistic')).all()


def test_source_crossfit_disjoint_roles_and_final_oos_threshold_source():
    f=crossfit_fixture()
    bundle,scores,thresholds,models=fit_source_crossfit(f)
    assert len(scores)==5*2*4*4
    assert scores.risk_score_source.eq('source_outer_group_crossfit').all()
    assert thresholds[thresholds.outer_fold.eq('final')].source.eq('source_outer_crossfit_OOS').all()
    assert len(bundle['fixture|B30|h1']['final_training_groups'])==10
    broken=f.copy();mask=(broken.outer_fold==0)&(broken.role=='threshold_calibration')
    broken.loc[mask,'group_id']='g2'
    with unittest.TestCase().assertRaises(ValueError):fit_source_crossfit(broken)


def test_target_truth_never_changes_scores_or_flags():
    source=crossfit_fixture();bundle,*_=fit_source_crossfit(source)
    target=source[(source.outer_fold==0)&(source.role=='outer_evaluation')].copy()
    original=score_target_risk(bundle,target)
    changed=target.copy();changed.truth_m3=1e9;changed.large_error_event=1
    later=score_target_risk(bundle,changed)
    for column in ['risk_score','review_10pct','review_20pct']:
        np.testing.assert_array_equal(original[column],later[column])
    np.testing.assert_array_equal(original.prediction_m3,
        pd.concat([target.prediction_m3]*4,ignore_index=True))


def load_tests(loader, tests, pattern):
    suite=unittest.TestSuite()
    for name,value in globals().items():
        if name.startswith('test_') and callable(value):suite.addTest(unittest.FunctionTestCase(value))
    return suite


if __name__=='__main__':unittest.main()
