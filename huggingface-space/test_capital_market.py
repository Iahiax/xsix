import unittest
from datetime import datetime, timedelta, timezone

from capital_market import CapitalMarketClient, CapitalMarketError


def prices_payload():
    values = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for index in range(60):
        bid = 1.1 + index * 0.0001
        values.append(
            {
                "snapshotTimeUTC": (start + timedelta(hours=index)).isoformat().replace("+00:00", "Z"),
                "openPrice": {"bid": bid, "ask": bid + 0.0002},
                "highPrice": {"bid": bid + 0.002, "ask": bid + 0.0022},
                "lowPrice": {"bid": bid - 0.001, "ask": bid - 0.0008},
                "closePrice": {"bid": bid + 0.001, "ask": bid + 0.0012},
                "lastTradedVolume": 12,
            }
        )
    return {"prices": values}


class CapitalMarketTests(unittest.TestCase):
    def test_candles_are_parsed_from_provider_bid_ask_and_sorted(self):
        client = CapitalMarketClient(env={"CAPITAL_API_MODE": "demo"})
        client._request = lambda *args, **kwargs: (prices_payload(), {})
        candles = client.fetch_candles("FX.TEST", "HOUR", 100)
        self.assertEqual(candles[0]["timestamp"], "2025-01-01T00:00:00Z")
        self.assertAlmostEqual(candles[0]["spread"], 0.0002)

    def test_client_refuses_live_credentials_and_unenabled_demo_orders(self):
        live_client = CapitalMarketClient(
            env={
                "CAPITAL_API_MODE": "live",
                "CAPITAL_API_KEY": "not-used",
                "CAPITAL_IDENTIFIER": "not-used",
                "CAPITAL_PASSWORD": "not-used",
            }
        )
        with self.assertRaises(CapitalMarketError):
            live_client._credentials()

        demo_client = CapitalMarketClient(
            env={
                "CAPITAL_API_MODE": "demo",
                "CAPITAL_API_KEY": "not-used",
                "CAPITAL_IDENTIFIER": "not-used",
                "CAPITAL_PASSWORD": "not-used",
                "CAPITAL_DEMO_EXECUTION_ENABLED": "false",
            }
        )
        with self.assertRaises(CapitalMarketError):
            demo_client.submit_demo_order(
                epic="FX.TEST",
                direction="BUY",
                size=0.01,
                stop_level=1.1,
                profit_level=1.2,
            )

    def test_market_quote_requires_actual_bid_and_offer(self):
        client = CapitalMarketClient(env={"CAPITAL_API_MODE": "demo"})
        client._request = lambda *args, **kwargs: (
            {
                "market": {
                    "snapshot": {
                        "bid": 1.25,
                        "offer": 1.251,
                        "updateTime": "now",
                        "marketStatus": "TRADEABLE",
                    }
                }
            },
            {},
        )
        quote = client.market_quote("FX.TEST")
        self.assertEqual(quote["bid"], 1.25)
        self.assertEqual(quote["ask"], 1.251)
        self.assertAlmostEqual(quote["spread"], 0.001)

        client._request = lambda *args, **kwargs: (
            {"market": {"snapshot": {"bid": 1.25, "offer": 1.251, "marketStatus": "CLOSED"}}},
            {},
        )
        with self.assertRaises(CapitalMarketError):
            client.market_quote("FX.TEST")


if __name__ == "__main__":
    unittest.main()
