import unittest

import numpy as np
import pandas as pd

from fuel_hedge.insights import (
    calibration_history, forecast_window, hedge_windows, market_prices, pct_rank,
    regular_weekly, return_correlations, weekly_proxy_returns, window_config, window_path_ids,
)
from fuel_hedge.simulation import box_muller, calibrate, price_paths


class InsightsTests(unittest.TestCase):
    def weekly(self, n=170):
        return pd.DataFrame({"week_ending": pd.date_range("2020-01-03", periods=n, freq="W-FRI"),
                             "jet_fuel_gal": 2*np.exp(np.sin(np.arange(n)/11)*.2)})

    def test_purchase_average_excludes_s0(self):
        weekly = self.weekly(53)
        weekly["jet_fuel_gal"] = [100.] + [2.]*52
        result = hedge_windows(weekly)
        self.assertEqual(len(result), 5)
        self.assertTrue(result.realized_avg.eq(2).all())
        self.assertAlmostEqual(result.iloc[0].budget_overrun_b, 1.5*(2-100))

    def test_missing_week_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing week"):
            regular_weekly(self.weekly().drop(index=65))

    def test_calibration_uses_only_past(self):
        weekly = self.weekly()
        history = calibration_history(weekly)
        t = history.iloc[10]
        changed = weekly.copy()
        changed.loc[changed.week_ending > t.week_ending, "jet_fuel_gal"] *= 4
        other = calibration_history(changed)
        self.assertEqual(t.mu, other.iloc[10].mu)
        expected = calibrate(weekly[weekly.week_ending <= t.week_ending])
        self.assertAlmostEqual(t.mu, expected["mu"], places=14)
        self.assertAlmostEqual(history.iloc[-1].sigma, calibrate(weekly)["sigma"], places=14)

    def test_seed_repartition_and_explicit_triple(self):
        config = window_config(2, .1, .3, 17, 10, 1234)
        all_paths = price_paths(window_path_ids(np.arange(10), 17), config)
        np.testing.assert_array_equal(all_paths[[7, 2]], price_paths(window_path_ids([7, 2], 17), config))
        shocks = box_muller(np.random.default_rng(np.random.SeedSequence([1234, 17, 7])), 52)
        expected = 2*np.exp(np.cumsum((.1-.5*.3**2)/52+.3/np.sqrt(52)*shocks))
        np.testing.assert_allclose(all_paths[7, 1:], expected, atol=1e-14)
        zero = window_config(2, .1, .3, 0, 10, 1234)
        shocks = box_muller(np.random.default_rng(np.random.SeedSequence([1234, 0, 7])), 52)
        expected = 2*np.exp(np.cumsum((.1-.5*.3**2)/52+.3/np.sqrt(52)*shocks))
        np.testing.assert_allclose(price_paths(window_path_ids([7], 0), zero)[0, 1:], expected, atol=1e-14)

    def test_percent_rank_ties(self):
        np.testing.assert_allclose(pct_rank([1, 2, 2, 4, np.nan]), [0, 1/3, 1/3, 1, np.nan], equal_nan=True)
        np.testing.assert_allclose(pct_rank([1., 2., 2.+1e-14, 4.]), [0, 1/3, 1/3, 1])

    def test_forecast_deterministic_and_purchase_rule(self):
        row = dict(week_ending=pd.Timestamp("2020-01-03"), s0=2., mu=.04, sigma=0., realized_avg=2.1)
        result = forecast_window(row, 9, 20)
        expected = np.mean(2*np.exp(.04*np.arange(1, 53)/52))
        self.assertAlmostEqual(result.iloc[0].p50, expected)
        self.assertEqual(result.iloc[1].p50, 2.)

    def market(self):
        dates = pd.bdate_range("2020-01-01", periods=100)
        jet = 2*np.exp(np.sin(np.arange(100)/7)/10)
        return market_prices(pd.DataFrame(dict(price_date=dates, jet_fuel_gal=jet,
            wti_spot_bbl=jet*30, brent_spot_bbl=jet*35, heating_oil_gal=jet*.9,
            crack_spread=jet-jet*30/42, rolling_corr_90d=1., long_return_gap=False)))

    def test_calendar_correlation_and_gap_suppression(self):
        market = self.market()
        result = return_correlations(market)
        self.assertTrue(result.iloc[:20].ret_corr_jet_wti_90d.isna().all())
        self.assertAlmostEqual(result.iloc[-1].ret_corr_jet_wti_90d, 1.)
        market.loc[60, "long_return_gap"] = True
        self.assertTrue(return_correlations(market).iloc[60:].ret_corr_jet_wti_90d.isna().all())

    def test_return_range_includes_both_calendar_endpoints(self):
        market = self.market()
        market.loc[24, "wti_gal"] *= 1.3
        result = return_correlations(market)
        prices = market.set_index("price_date")[["jet_fuel_gal", "wti_gal"]]
        returns = np.log(prices).diff()
        dt = market.price_date.iloc[-1]
        pair = returns.loc[(returns.index >= dt-pd.Timedelta(days=90)) & (returns.index <= dt)]
        self.assertAlmostEqual(result.iloc[-1].ret_corr_jet_wti_90d, pair.corr().iloc[0, 1])

    def test_weekly_return_does_not_bridge_empty_week(self):
        market = self.market()
        dates = market.price_date
        market = market[~dates.between("2020-02-03", "2020-02-07")]
        returns = weekly_proxy_returns(market)
        self.assertTrue(returns.loc["2020-02-07":"2020-02-14"].isna().all().all())


if __name__ == "__main__":
    unittest.main()
