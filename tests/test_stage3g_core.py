"""Synthetic-fixture tests: software checks do not verify real facilities."""
import unittest

import numpy as np
import pandas as pd

from wastewater.stage3g_core import (
    Descriptor, build_samples, build_source_stats, calendar_history, calibration_fold,
    compact, fit_descriptor_transform, fit_weighted, history_descriptor,
    large_error_threshold, reconstruct, residual_target, ridge_fit,
    risk_features, similarity_weights, source_descriptors,
    source_stats_from_samples, subset, train_samples, usable,
)


def fixture(start="2016-01-01", end="2023-12-31", multiplier=1.):
    dates = pd.date_range(start, end)
    t = np.arange(len(dates), dtype=float)
    return pd.Series(multiplier * (120 + 17*np.sin(t/7) + 5*np.cos(t/3)), index=dates)


class Stage3GCoreTests(unittest.TestCase):
    def test_compact_feature_order_and_missing_placeholder(self):
        values = fixture("2022-01-01", "2022-01-20")
        values.loc["2022-01-10"] = np.nan
        data = build_samples(values, ["2022-01-10"], 3, "2022-01-01", 100.)
        x = compact(data.X)[0]
        self.assertEqual(x[0], 1.)
        self.assertEqual(x[3], 0.)
        self.assertAlmostEqual(x[1], values.loc["2022-01-09"]/100, places=6)
        self.assertAlmostEqual(x[2], values.loc["2022-01-04"]/100, places=6)
        self.assertEqual(list(x[4:]), [1., 1.])

    def test_h3_is_third_day_and_weekly_is_target_minus_seven(self):
        values = fixture("2022-01-01", "2022-01-30")
        data = build_samples(values, ["2022-01-15"], 3, "2022-01-01", 100.)
        self.assertEqual(data.targets[0], pd.Timestamp("2022-01-18"))
        self.assertEqual(data.y[0], values.loc["2022-01-18"]/100)
        self.assertEqual(data.weekly[0], values.loc["2022-01-11"])
        self.assertEqual(data.persistence[0], values.loc["2022-01-15"])

    def test_budget_left_blocks_unaccounted_warmup(self):
        values = fixture("2021-12-01", "2022-02-01")
        values.loc["2022-01-01"] = np.nan
        data = build_samples(values, ["2022-01-01"], 1, "2022-01-01", 100.)
        self.assertTrue(np.isnan(data.persistence[0]))
        self.assertTrue(np.isnan(data.weekly[0]))
        self.assertTrue((data.X[0, :, 1] == 0).all())
        self.assertTrue((data.X[0, :, 0] == 1).all())

    def test_training_labels_are_purged_at_cutoff(self):
        values = fixture("2022-01-01", "2022-03-01")
        data = train_samples(values, "2022-01-01", "2022-01-30", 3, 100.)
        self.assertEqual(len(data.y), 27)
        self.assertEqual(data.origins.max(), pd.Timestamp("2022-01-27"))
        self.assertEqual(data.targets.max(), pd.Timestamp("2022-01-30"))

    def test_internal_validation_normalization_and_descriptor_fit_prefix_only(self):
        values = fixture()
        cfg = dict(local_validation_fraction=.2, min_train_labels=14,
                   validation_min_fit_labels=30, validation_min_labels=10,
                   source_pseudo_validation_days=14)
        train0, val0, diag0 = calibration_fold(values, "2022-07-01", 90, 3, cfg)
        left, fit_end = diag0["budget_start"], diag0["fit_end"]
        desc0 = history_descriptor(values, left, fit_end)
        altered = values.copy()
        altered.loc[pd.Timestamp(fit_end)+pd.Timedelta(days=1):] = 999999.
        train1, val1, diag1 = calibration_fold(altered, "2022-07-01", 90, 3, cfg)
        desc1 = history_descriptor(altered, left, fit_end)
        self.assertEqual(diag0["scale_m3"], diag1["scale_m3"])
        self.assertEqual(desc0.diagnostics["calendar_days"], 72)
        np.testing.assert_array_equal(train0.X, train1.X)
        np.testing.assert_array_equal(train0.y, train1.y)
        np.testing.assert_array_equal(desc0.values, desc1.values)
        self.assertLess(train0.targets.max(), val0.origins.min())
        self.assertLessEqual(val1.targets.max(), pd.Timestamp("2022-06-30"))

    def test_calendar_adjacency_does_not_bridge_missing_dates(self):
        values = fixture("2022-01-01", "2022-01-30")
        values = values.drop(pd.Timestamp("2022-01-15"))
        result = history_descriptor(values, "2022-01-01", "2022-01-30")
        self.assertEqual(result.diagnostics["calendar_days"], 30)
        self.assertEqual(result.diagnostics["valid_observations"], 29)
        self.assertEqual(result.diagnostics["valid_adjacent_pairs"], 27)
        self.assertAlmostEqual(result.values[3], 1/30)

    def test_constant_autocorrelation_is_na_and_uniform_fallback(self):
        dates = pd.date_range("2022-01-01", periods=30)
        descriptor = history_descriptor(pd.Series(10., index=dates), dates[0], dates[-1])
        self.assertTrue(np.isnan(descriptor.values[2]))
        self.assertFalse(descriptor.valid)
        sources = np.array([[.1, .2, .3, 0], [.2, .3, .5, .1]])
        weights, diag = similarity_weights(descriptor, sources, .9)
        np.testing.assert_array_equal(weights, [.5, .5])
        self.assertTrue(diag["uniform_fallback"])
        self.assertEqual(diag["fallback_reason"], "target_descriptor_undefined")

    def test_source_descriptor_has_same_length_and_no_post_2020_use(self):
        values = fixture()
        raw, rows = source_descriptors({"s": values}, ["s"], 30, "2021-12-31")
        self.assertEqual(raw.shape, (1, 4))
        annual = [row for row in rows if isinstance(row["annual_year"], int)]
        self.assertEqual(len(annual), 5)
        self.assertTrue(all(row["calendar_days"] == 30 for row in annual))
        self.assertTrue(all(pd.Timestamp(row["history_end"]) <= pd.Timestamp("2020-12-31") for row in annual))
        later_changed = values.copy()
        later_changed.loc["2021-01-01":] = 999999.
        altered = source_descriptors({"s": later_changed}, ["s"], 30, "2021-12-31")[0]
        np.testing.assert_array_equal(raw, altered)

    def test_source_imputation_and_standardization_are_train_only(self):
        raw = np.array([[1., 3., .1, .2], [3., 3., np.nan, .4]])
        transform = fit_descriptor_transform(raw)
        self.assertEqual(transform.missing_cells, 1)
        self.assertEqual(transform.medians[2], .1)
        self.assertFalse(transform.active[1])
        self.assertFalse(transform.active[2])
        before = transform.means.copy()
        target = np.array([1e6, -1e6, .9, .9])
        similarity_weights(target, raw, .5, transform)
        np.testing.assert_array_equal(before, transform.means)

    def test_constant_source_keeps_finite_components_before_source_imputation(self):
        dates = pd.date_range("2016-01-01", "2021-12-31")
        values = pd.Series(10., index=dates)
        raw, rows = source_descriptors({"constant": values}, ["constant"], 30)
        np.testing.assert_array_equal(raw[0, [0, 1, 3]], [0., 0., 0.])
        self.assertTrue(np.isnan(raw[0, 2]))
        self.assertEqual(rows[-1]["finite_windows_by_component"], [5, 5, 0, 5])

    def test_decimal_constant_descriptor_component_is_ignored_without_epsilon(self):
        raw = np.tile([.1, .1, .1, .1], (30, 1))
        transform = fit_descriptor_transform(raw)
        self.assertFalse(transform.active.any())
        np.testing.assert_array_equal(transform.standard_deviations, np.zeros(4))
        weights, diag = similarity_weights([.2, .3, .4, .5], raw, .9, transform)
        np.testing.assert_array_equal(weights, np.full(30, 1/30))
        self.assertEqual(diag["fallback_reason"], "no_variable_source_descriptor_components")

    def test_eta_zero_exact_uniform_and_weight_bounds(self):
        raw = np.array([[.1, .2, .1, .02], [.5, .3, .4, .05], [1., .8, .6, .1]])
        target = raw[0]
        weights0, diag0 = similarity_weights(target, raw, 0)
        np.testing.assert_array_equal(weights0, np.full(3, 1/3))
        weights9, diag9 = similarity_weights(target, raw, .9)
        self.assertAlmostEqual(weights9.sum(), 1.)
        self.assertTrue((weights9 >= .1/3).all())
        self.assertTrue(weights9[0] > weights9[1])
        self.assertLessEqual(diag9["effective_source_count"], 3.)
        self.assertAlmostEqual(diag0["effective_source_count"], 3.)

    def test_weighted_statistics_match_row_weighted_ridge(self):
        first, second = fixture(multiplier=1.), fixture(multiplier=20.)
        first.loc["2017-06-01":"2017-06-10"] = np.nan
        cfg = dict(source_training_start="2016-01-01", min_train_labels=14)
        stats = build_source_stats({"a": first, "b": second}, cfg, ["a", "b"], 3, "2020-12-31")
        samples = [train_samples(series, "2016-01-01", "2020-12-31", 3,
                                 np.median(series.loc["2016-01-01":"2020-12-31"].dropna()))
                   for series in [first, second]]
        samples = [subset(sample, usable(sample)) for sample in samples]
        x = np.concatenate([compact(sample.X) for sample in samples])
        weights = np.concatenate([np.full(len(sample.y), w/len(sample.y))
                                  for sample, w in zip(samples, [.2, .8])])
        for target in ("direct", "residual"):
            y = np.concatenate([sample.y if target == "direct" else residual_target(sample)
                                for sample in samples])
            for alpha in (.0001, .1, 10.):
                actual = fit_weighted(stats, {"a": .2, "b": .8}, alpha, target)
                expected = ridge_fit(x, y, alpha, weights)
                np.testing.assert_allclose(actual.predict(x), expected.predict(x), atol=1e-10, rtol=1e-10)
                self.assertAlmostEqual(actual.intercept_, expected.intercept_, places=10)

    def test_eta_zero_matches_uniform_fitting(self):
        values = fixture("2022-01-01", "2022-03-01")
        samples = train_samples(values, "2022-01-01", "2022-02-28", 1, 120.)
        stats = {"a": source_stats_from_samples(samples), "b": source_stats_from_samples(samples)}
        raw = np.array([[.1, .2, .1, .02], [.5, .3, .4, .05]])
        weights, _ = similarity_weights(raw[0], raw, 0)
        weighted = fit_weighted(stats, weights, .01)
        uniform = fit_weighted(stats, np.full(2, .5), .01)
        np.testing.assert_array_equal(weighted.coef_, uniform.coef_)
        self.assertEqual(weighted.intercept_, uniform.intercept_)

    def test_lambda_zero_returns_same_persistence_including_nan(self):
        p = np.array([0., np.nan, 20.])
        result = reconstruct(p, [1e300, np.nan, -9999.], 1e300, 0., 120.)
        np.testing.assert_array_equal(result, p)

    def test_risk_features_and_source_fit_do_not_use_future(self):
        values = fixture()
        cfg = dict(source_training_start="2016-01-01", min_train_labels=14)
        original = build_source_stats({"a": values}, cfg, ["a"], 3, "2020-12-31")
        later = values.copy()
        later.loc["2021-01-01":] = 1e10
        altered = build_source_stats({"a": later}, cfg, ["a"], 3, "2020-12-31")
        np.testing.assert_array_equal(original["a"].gram, altered["a"].gram)
        np.testing.assert_array_equal(original["a"].residual_rhs, altered["a"].residual_rhs)
        risk0 = risk_features(values, "2022-01-10", "2021-12-01", 120., .5)
        later = values.copy()
        later.loc["2022-01-11":] = 1e10
        risk1 = risk_features(later, "2022-01-10", "2021-12-01", 120., .5)
        np.testing.assert_array_equal(risk0, risk1)

    def test_recent_risk_change_with_only_one_adjacent_pair_is_na(self):
        values = pd.Series(np.nan, index=pd.date_range("2022-01-01", periods=7))
        values.iloc[-2:] = [100., 120.]
        risk = risk_features(values, "2022-01-07", "2022-01-01", 100., .4)
        self.assertTrue(np.isnan(risk[2]))
        self.assertAlmostEqual(risk[1], 5/7)

    def test_zero_error_quantile_retained_and_short_history_is_unavailable(self):
        values = pd.Series(0., index=pd.date_range("2022-01-01", periods=30))
        training = train_samples(values, "2022-01-01", "2022-01-30", 3, 1.)
        threshold, diag = large_error_threshold(training)
        self.assertEqual(threshold, 0.)
        self.assertTrue(diag["threshold_zero"])
        short = subset(training, np.arange(len(training.y)) < 13)
        threshold, diag = large_error_threshold(short)
        self.assertIsNone(threshold)
        self.assertFalse(diag["threshold_valid"])

    def test_no_positive_scale_fallback_and_missing_values_are_not_volumes(self):
        values = pd.Series(0., index=pd.date_range("2022-01-01", periods=30))
        values.iloc[10:14] = np.nan
        desc = history_descriptor(values, values.index[0], values.index[-1])
        self.assertEqual(desc.diagnostics["scale_m3"], 1.)
        self.assertTrue(desc.diagnostics["scale_fallback_no_positive_observations"])
        self.assertEqual(desc.values[0], 0.)
        self.assertEqual(desc.values[1], 0.)
        self.assertAlmostEqual(desc.values[3], 4/30)


if __name__ == "__main__":
    unittest.main()
