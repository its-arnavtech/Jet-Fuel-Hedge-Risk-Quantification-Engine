from datetime import date
import unittest

import pandas as pd

from fuel_hedge.operations import linear_hedge_mark, scenario_cost, synthetic_operations


class OperationsTests(unittest.TestCase):
    def test_deterministic_unique_labeled_and_complete_schedule(self):
        data = synthetic_operations(date(2026, 10, 6))
        again = synthetic_operations(date(2026, 10, 6))
        for name, frame in data.items():
            pd.testing.assert_frame_equal(frame, again[name])
            self.assertTrue(frame.is_synthetic.all())
        self.assertTrue(data['flights'].flight_id.is_unique)
        self.assertEqual(len(data['flights']), data['routes'].daily_frequencies.sum()*365)
        self.assertTrue(data['flights'].cancelled.any())
        self.assertTrue(set(data['flights'].route_id) <= set(data['routes'].route_id))

    def test_matching_underlying_units_and_linear_sign(self):
        spots = {'jet_fuel_gal': 3.0, 'wti_spot_bbl': 84.0, 'heating_oil_gal': 2.5}
        self.assertEqual(linear_hedge_mark('futures','WTI',100,1.5,spots),50)
        self.assertEqual(linear_hedge_mark('swap','JET_FUEL',100,3.5,spots),-50)
        self.assertIsNone(linear_hedge_mark('futures','HEATING_OIL',100,2,{}))
        with self.assertRaises(ValueError):
            linear_hedge_mark('call_option','JET_FUEL',100,2,spots)
        with self.assertRaises(ValueError):
            linear_hedge_mark('futures','WTI',0,2,spots)

    def test_scenario_cost_boundaries(self):
        self.assertEqual(scenario_cost(100,3,2,0),300)
        self.assertEqual(scenario_cost(100,3,2,1),200)
        self.assertAlmostEqual(scenario_cost(100,3,2,.6),240)
        with self.assertRaises(ValueError):
            scenario_cost(100,3,2,1.1)


if __name__ == '__main__':
    unittest.main()
