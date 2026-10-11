from dataclasses import replace
import unittest

import numpy as np
import pandas as pd

from fuel_hedge.simulation import (
    SimulationConfig, box_muller, calibrate, cost_distribution, price_paths, risk_summary,
)


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.config=SimulationConfig(s0=3,mu=.03,sigma=.3,n_paths=5000)

    def test_seed_and_partition_invariance(self):
        whole=price_paths(np.arange(100),self.config)
        split=np.vstack([price_paths(np.arange(37),self.config),price_paths(np.arange(37,100),self.config)])
        np.testing.assert_array_equal(whole,split)
        np.testing.assert_array_equal(whole[17],price_paths(np.array([17]),self.config)[0])
        self.assertFalse(np.array_equal(whole,price_paths(np.arange(100),replace(self.config,seed=7))))

    def test_box_muller_moments_and_gbm_terminal_mean(self):
        z=box_muller(np.random.default_rng(10),100_000)
        self.assertLess(abs(z.mean()),.015)
        self.assertLess(abs(z.std()-1),.015)
        paths=price_paths(np.arange(5000),self.config)
        expected=self.config.s0*np.exp(self.config.mu)
        standard_error=expected*np.sqrt(np.exp(self.config.sigma**2)-1)/np.sqrt(len(paths))
        self.assertLess(abs(paths[:,-1].mean()-expected),4*standard_error)

    def test_deterministic_drift_purchase_average_and_horizon_volume(self):
        config=replace(self.config,sigma=0,mu=.1,horizon_years=2)
        paths=price_paths(np.arange(3),config)
        expected=3*np.exp(.1*np.arange(105)/52)
        np.testing.assert_allclose(paths[0],expected)
        costs=cost_distribution(paths,config)
        self.assertAlmostEqual(costs[0].iloc[0],expected[1:].mean()*3)
        self.assertAlmostEqual(costs[.8].iloc[0],(.8*config.forward_price+.2*expected[1:].mean())*3)

    def test_affine_hedge_risk_reduction_and_tail(self):
        costs=cost_distribution(price_paths(np.arange(2000),self.config),self.config)
        risk=risk_summary(costs)
        for ratio in self.config.hedge_ratios:
            row=risk[risk.hedge_ratio==ratio].iloc[0]
            self.assertAlmostEqual(row.var_reduction_pct,ratio*100,places=9)
            self.assertGreaterEqual(row.cvar_95_b,row.p95_cost_b)
        fixed=replace(self.config,hedge_ratios=(0.0,1.0))
        metrics=risk_summary(cost_distribution(price_paths(np.arange(20),fixed),fixed))
        self.assertAlmostEqual(metrics.iloc[1].var_95_b,0,places=12)

    def test_zero_variance_and_quantile_definition(self):
        costs=pd.DataFrame({0.0:[1.,2.,3.,4.,5.],.8:[2.,2.2,2.4,2.6,2.8]})
        risk=risk_summary(costs)
        self.assertAlmostEqual(risk.iloc[0].p95_cost_b,4.8)
        self.assertAlmostEqual(risk.iloc[0].var_95_b,1.8)
        self.assertAlmostEqual(risk.iloc[0].cvar_95_b,5)
        fixed=risk_summary(pd.DataFrame({0.0:[3.]*10,.8:[3.]*10}))
        self.assertTrue(fixed.var_reduction_pct.isna().all())

    def test_ewm_latest_sample_and_arithmetic_drift(self):
        dates=pd.date_range('2024-01-05',periods=60,freq='W-FRI')
        frame=pd.DataFrame({'week_ending':dates,'jet_fuel_gal':3*np.exp(np.arange(60)*.001)})
        result=calibrate(frame.sample(frac=1,random_state=4))
        self.assertAlmostEqual(result['mu'],.052,places=10)
        self.assertLess(result['sigma'],1e-12)
        frame.loc[59,'jet_fuel_gal']*=1.2
        result=calibrate(frame)
        self.assertGreater(result['weekly_log_mean'],np.diff(np.log(frame.jet_fuel_gal)).mean())
        self.assertAlmostEqual(result['mu'],52*result['weekly_log_mean']+.5*result['sigma']**2)
        with self.assertRaises(ValueError):
            calibrate(frame.drop(index=40))

    def test_invalid_inputs(self):
        for changes in [{'s0':0},{'sigma':-1},{'n_paths':0},{'horizon_years':.01},
                        {'hedge_ratios':(.2,.4)},{'mu':float('nan')},{'seed':-1}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                replace(self.config,**changes)


if __name__=='__main__':
    unittest.main()
