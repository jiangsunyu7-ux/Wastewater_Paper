"""V3 retrospective-QA data, strict calendars and identical model information."""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Samples:
    X: np.ndarray
    y: np.ndarray
    origins: pd.DatetimeIndex
    targets: pd.DatetimeIndex
    persistence: np.ndarray
    weekly: np.ndarray
    scale: float


def scale_from_history(series, left, right):
    values = series.loc[left:right].dropna().to_numpy(float)
    positives = values[values > 0]
    return float(np.median(positives)) if len(positives) else 1.0


def build_samples(series, origins, horizon, left, scale, length=7):
    """Missing values become fixed training-history median (=1), with a mask.

    The six channels are normalized volume, observation mask, input weekday
    sin/cos, and target weekday sin/cos. Ridge receives the flattened SAME
    tensor as GRU. Calendar padding never reads observations before left.
    """
    if horizon not in (1, 3) or scale <= 0 or length != 7:
        raise ValueError('Unsupported horizon/scale/sequence length')
    origins = pd.DatetimeIndex(origins)
    targets = origins + pd.Timedelta(days=horizon)
    dates = origins.values[:, None] - np.arange(length-1, -1, -1)[None, :] * np.timedelta64(1, 'D')
    indices = series.index.get_indexer(pd.DatetimeIndex(dates.reshape(-1))).reshape(dates.shape)
    observed = np.full(dates.shape, np.nan)
    valid = (indices >= 0) & (dates >= np.datetime64(pd.Timestamp(left)))
    observed[valid] = series.to_numpy(float)[indices[valid]]
    mask = np.isfinite(observed)
    volume = np.where(mask, observed / scale, 1.0)
    weekdays = pd.DatetimeIndex(dates.reshape(-1)).dayofweek.to_numpy().reshape(dates.shape)
    wd = targets.dayofweek.to_numpy()[:, None] * np.ones((1, length))
    X = np.stack([volume, mask.astype(float), np.sin(2*np.pi*weekdays/7),
                  np.cos(2*np.pi*weekdays/7), np.sin(2*np.pi*wd/7), np.cos(2*np.pi*wd/7)], axis=-1)
    truth = series.reindex(targets).to_numpy(float)
    persistence = np.full(len(origins), np.nan)
    # At most seven previous days beyond the current allowed observation.
    for lag in range(8):
        d = origins - pd.Timedelta(days=lag)
        values = series.reindex(d).to_numpy(float)
        values[d < pd.Timestamp(left)] = np.nan
        use = np.isnan(persistence) & np.isfinite(values)
        persistence[use] = values[use]
    d = targets - pd.Timedelta(days=7)
    weekly = series.reindex(d).to_numpy(float)
    weekly[(d < pd.Timestamp(left)) | (d > origins)] = np.nan
    return Samples(X.astype(np.float32), truth / scale, origins, targets, persistence, weekly, scale)


def train_samples(series, left, right, horizon, scale, length=7):
    origins = pd.date_range(left, pd.Timestamp(right)-pd.Timedelta(days=horizon), freq='D')
    data = build_samples(series, origins, horizon, left, scale, length)
    eligible = np.isfinite(data.y) & data.X[:, :, 1].sum(axis=1).astype(bool)
    return Samples(data.X[eligible], data.y[eligible], data.origins[eligible], data.targets[eligible],
                   data.persistence[eligible], data.weekly[eligible], scale)


def load_series(path, ids, maximum='2023-12-31'):
    data = pd.read_csv(path, dtype={'site_id': str})
    if data.date.max() > maximum:
        raise ValueError('Stage-2 canonical must not contain final-period data')
    if data.duplicated(['site_id', 'date']).any():
        raise ValueError('Unresolved duplicate canonical dates')
    result = {}
    for site in ids:
        rows = data[data.site_id.eq(str(site))].copy()
        if rows.empty:
            raise ValueError(f'Missing selected site {site}')
        if not np.allclose(rows.observed_input_m3, rows.candidate_value_m3, equal_nan=True):
            raise ValueError('V3 requires SAME published-QA mask for inputs, training labels and truth')
        values = rows.observed_input_m3.dropna()
        if (values < 0).any() or not np.isfinite(values).all():
            raise ValueError('Unquarantined invalid volume')
        series = rows.assign(date=pd.to_datetime(rows.date)).set_index('date').observed_input_m3.sort_index()
        result[str(site)] = series.reindex(pd.date_range('2016-01-01', maximum, freq='D'))
    return result
