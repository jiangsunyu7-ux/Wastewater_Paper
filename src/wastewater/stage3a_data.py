"""Purged chronological validation, preserving calendar positions and budgets."""
import math
import numpy as np
import pandas as pd
from .shared_data import build_samples,train_samples,scale_from_history


def compact(X):
    return np.concatenate([X[:,[6,5,0],0],X[:,[6,5,0],1]],axis=1)


def eligible(data):
    keep=np.isfinite(data.y)&(data.X[:,:,1].sum(axis=1)>0)
    return dict(X=data.X[keep],y=data.y[keep],weights=np.ones(keep.sum())/keep.sum()),keep


def internal_fold(series,date,budget,horizon,cfg):
    end=pd.Timestamp(date)-pd.Timedelta(days=1);left=pd.Timestamp(date)-pd.Timedelta(days=budget)
    tail=math.ceil(cfg['local_validation_fraction']*budget);split=end-pd.Timedelta(days=tail-1)
    fit_end=split-pd.Timedelta(days=1);scale=scale_from_history(series,left,fit_end)
    train=train_samples(series,left,fit_end,horizon,scale)
    val=build_samples(series,pd.date_range(split,end-pd.Timedelta(days=horizon)),horizon,left,scale)
    validation,keep=eligible(val)
    diag=dict(kind='budget_internal_purged_time_validation',budget=budget,horizon=horizon,
        budget_start=str(left.date()),budget_end=str(end.date()),validation_start=str(split.date()),
        fit_end=str(fit_end.date()),last_fit_target=str(train.targets.max().date()) if len(train.y) else None,
        first_validation_origin=str(val.origins[keep].min().date()) if keep.any() else None,
        last_validation_target=str(val.targets[keep].max().date()) if keep.any() else None,
        fitting_labels=len(train.y),validation_labels=int(keep.sum()),scale_m3=scale,
        source_assisted=False,valid=bool(len(train.y)>=cfg['validation_min_fit_labels'] and keep.sum()>=cfg['validation_min_labels']))
    if len(train.y) and train.targets.max()>=split:raise AssertionError('Fit label crosses validation split')
    if keep.any() and val.targets[keep].max()>end:raise AssertionError('Validation label exceeds budget')
    return train,validation,diag


def pseudo_fold(series,date,budget,horizon,cfg):
    start=pd.Timestamp(date);left=start-pd.Timedelta(days=budget);end=start-pd.Timedelta(days=1)
    scale=scale_from_history(series,left,end);train=train_samples(series,left,end,horizon,scale)
    val=build_samples(series,pd.date_range(start,periods=cfg['source_pseudo_validation_days']),horizon,left,scale)
    validation,keep=eligible(val)
    if train.targets.max()>end or val.targets.max()>pd.Timestamp('2021-12-31'):raise AssertionError('Pseudo validation boundary')
    return train,validation,dict(kind='source_simulated_same_budget',date=date,budget=budget,horizon=horizon,
        budget_start=str(left.date()),fit_end=str(end.date()),last_fit_target=str(train.targets.max().date()),
        first_validation_origin=date,last_validation_target=str(val.targets[keep].max().date()),
        fitting_labels=len(train.y),validation_labels=int(keep.sum()),scale_m3=scale,source_assisted=True)
