from pathlib import Path
import unittest

from scripts.build_powerbi import MEASURES, measures, parse_starter_measures


class PowerBIContractTests(unittest.TestCase):
    def test_adjacent_starter_measures_remain_separate(self):
        parsed = parse_starter_measures("// Comment\nMean = SELECTEDVALUE(T[mean])\nP95 =\nCALCULATE(\n    SELECTEDVALUE(T[p95]))\nTail = SELECTEDVALUE(T[tail])")
        self.assertEqual(set(parsed), {"Mean", "P95", "Tail"})
        self.assertEqual(parsed["Mean"], "SELECTEDVALUE(T[mean])")
        self.assertEqual(parsed["P95"], "CALCULATE(\n    SELECTEDVALUE(T[p95]))")

    def test_all_starter_metrics_preserve_their_definitions(self):
        starter = parse_starter_measures(Path("powerbi/measures.dax").read_text(encoding="utf-8"))
        self.assertEqual(set(starter), {"Fuel Cost USD", "Unhedged Cost USD", "Fuel Gallons", "Mean Cost B", "P95 Cost B", "Incremental VaR95 B", "CVaR95 B", "VaR Reduction"})
        measures()
        for name, expression in starter.items():
            self.assertEqual(MEASURES[name][0], expression, name)
        self.assertEqual(MEASURES["Mean Cost B"][0], "SELECTEDVALUE('Risk Metrics'[mean_cost_b])")


if __name__ == "__main__":
    unittest.main()
