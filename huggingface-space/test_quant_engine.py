import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_engine import (
    QuantDataError,
    analyze_market,
    risk_position_size,
    technical_indicators,
    train_direction_mlp,
    train_q_learning,
    validate_candles,
)
from quant_store import QuantStore


def make_candles(count=320, *, include_spread=True):
    candles = []
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    previous = 100.0
    for index in range(count):
        close = 100 + index * 0.035 + 2.2 * math.sin(index / 8) + 0.7 * math.sin(index / 2.7)
        open_price = previous
        high = max(open_price, close) + 0.3
        low = min(open_price, close) - 0.3
        candles.append(
            {
                "timestamp": (start + timedelta(hours=index)).isoformat(),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100 + index,
                "spread": 0.02 if include_spread else None,
            }
        )
        previous = close
    return candles


class QuantEngineTests(unittest.TestCase):
    def test_rejects_invalid_or_unsorted_provider_candles(self):
        candles = make_candles(60)
        candles[10]["close"] = float("nan")
        with self.assertRaises(QuantDataError):
            validate_candles(candles)

        candles = make_candles(60)
        candles[10]["timestamp"], candles[11]["timestamp"] = candles[11]["timestamp"], candles[10]["timestamp"]
        with self.assertRaises(QuantDataError):
            validate_candles(candles)

    def test_indicators_are_finite_and_warm_up_without_fake_values(self):
        rows = technical_indicators(make_candles(120))
        self.assertIsNone(rows[10]["rsi"])
        self.assertIsNotNone(rows[-1]["rsi"])
        self.assertGreaterEqual(rows[-1]["rsi"], 0)
        self.assertLessEqual(rows[-1]["rsi"], 100)
        self.assertIsNotNone(rows[-1]["atr"])
        self.assertIn(rows[-1]["trend"], (-1, 1))
        self.assertIsNotNone(rows[-1]["volatility20"])

    def test_risk_size_obeys_risk_and_exposure_caps(self):
        plan = risk_position_size(
            equity=10_000,
            entry_price=100,
            stop_price=95,
            risk_fraction=0.005,
            max_notional_fraction=0.25,
        )
        self.assertAlmostEqual(plan["risk_budget"], 50)
        self.assertLessEqual(plan["notional"], 2_500)
        self.assertAlmostEqual(plan["units"], 10)

    def test_mlp_and_q_learning_use_separate_chronological_test_windows(self):
        candles = make_candles()
        model = train_direction_mlp(candles)
        self.assertEqual(model["model_type"], "two_hidden_layer_mlp")
        self.assertGreaterEqual(model["validation"]["observations"], 20)
        self.assertGreaterEqual(model["out_of_sample"]["observations"], 20)
        q_report = train_q_learning(candles)
        self.assertGreater(q_report["test_observations"], 20)
        self.assertTrue(q_report["candidate_only"])

    def test_backtest_requires_real_spreads_and_an_evaluated_candidate(self):
        candles = make_candles()
        model = train_direction_mlp(candles)
        report = analyze_market(candles, starting_equity=10_000)
        self.assertEqual(report["data"]["source"], "provider_required")
        self.assertEqual(report["backtest"]["execution"], "simulated_only")
        self.assertGreaterEqual(report["backtest"]["max_drawdown"], 0)

        no_spread = make_candles(include_spread=False)
        with self.assertRaises(QuantDataError):
            analyze_market(no_spread, starting_equity=10_000)

    def test_sqlite_store_keeps_only_provider_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = QuantStore(str(Path(temporary) / "research.sqlite3"))
            candles = make_candles(60)
            self.assertEqual(store.save_candles("FX.TEST", "HOUR", candles, source="Capital.com"), 60)
            loaded = store.load_candles("FX.TEST", "HOUR", 100)
            self.assertEqual(len(loaded), 60)
            self.assertEqual(loaded[0]["timestamp"], candles[0]["timestamp"])
            with self.assertRaises(ValueError):
                store.save_candles("FX.TEST", "HOUR", candles, source="synthetic")
            store.save_run("run-1", "FX.TEST", "HOUR", 60, {"status": "research"}, source="Capital.com")
            self.assertEqual(store.list_runs()[0]["report"]["status"], "research")


if __name__ == "__main__":
    unittest.main()
