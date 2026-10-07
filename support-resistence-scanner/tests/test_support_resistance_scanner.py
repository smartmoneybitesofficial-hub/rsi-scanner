import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support_resistance_scanner import (  # noqa: E402
    detect_reversal_patterns,
    find_pivots,
    scan_symbol,
)


def frame_from_rows(rows):
    frame = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"])
    frame["Volume"] = 100.0
    return frame


class ScannerTests(unittest.TestCase):
    def test_pivots_are_confirmed_only_after_right_hand_bars(self):
        lows = [10, 9, 8, 9, 10, 9, 7, 9, 10]
        frame = pd.DataFrame(
            {
                "Open": [value + 1 for value in lows],
                "High": [value + 2 for value in lows],
                "Low": lows,
                "Close": [value + 1 for value in lows],
            },
            index=pd.date_range("2025-01-01", periods=len(lows)),
        )
        pivots = find_pivots(frame, "support", order=1, atr_period=2)
        self.assertEqual([pivot.position for pivot in pivots], [2, 6])

    def test_engulfing_pattern_is_bullish(self):
        frame = frame_from_rows(
            [
                (12, 13, 10, 11),
                (11, 12, 9, 10),
                (10, 10.5, 8, 9),
                (8.5, 11, 8, 10.5),
            ]
        )
        self.assertIn("Bullish Engulfing", detect_reversal_patterns(frame)["bullish"])

    def test_scan_requires_touch_and_matching_pattern(self):
        lows = [100] * 40
        lows[7] = 98
        lows[21] = 98
        rows = [(low + 1, low + 2, low, low + 1) for low in lows]
        rows.extend([(100.5, 101, 99, 99.5), (99, 102, 97.5, 101.5)])
        frame = frame_from_rows(rows)
        frame.loc[frame.index[-1], "Volume"] = 200
        frame.index = pd.date_range("2025-01-01", periods=len(frame))
        hits = scan_symbol(
            "TEST",
            frame,
            ["S&P 500"],
            market_cap=15_000_000_000,
            order=1,
            atr_period=2,
            tolerance_atr=0.6,
            min_gap=2,
            min_touches=3,
        )
        self.assertTrue(any(hit["Side"] == "Support" for hit in hits))
        support_hit = next(hit for hit in hits if hit["Side"] == "Support")
        self.assertEqual(
            support_hit["Chart"],
            '=HYPERLINK("https://finance.yahoo.com/quote/TEST/chart/","Open chart")',
        )
        self.assertGreaterEqual(support_hit["Touches"], 3)
        self.assertEqual(support_hit["Last Touch"], frame.index[-1].strftime("%Y-%m-%d"))
        self.assertEqual(support_hit["Market Cap ($B)"], 15.0)
        self.assertEqual(support_hit["Volume Ratio"], 2.0)

    def test_market_cap_and_volume_filters_exclude_weak_candidates(self):
        lows = [100] * 40
        lows[7] = 98
        lows[21] = 98
        rows = [(low + 1, low + 2, low, low + 1) for low in lows]
        rows.extend([(100.5, 101, 99, 99.5), (99, 102, 97.5, 101.5)])
        frame = frame_from_rows(rows)
        frame.loc[frame.index[-1], "Volume"] = 149
        frame.index = pd.date_range("2025-01-01", periods=len(frame))

        options = {
            "order": 1,
            "atr_period": 2,
            "tolerance_atr": 0.6,
            "min_gap": 2,
            "min_touches": 3,
        }
        self.assertEqual(
            scan_symbol("TEST", frame, ["S&P 500"], market_cap=2_000_000_000, **options),
            [],
        )
        self.assertEqual(
            scan_symbol("TEST", frame, ["S&P 500"], market_cap=2_100_000_000, **options),
            [],
        )

    def test_market_cap_above_two_billion_passes_market_cap_filter(self):
        lows = [100] * 40
        lows[7] = 98
        lows[21] = 98
        rows = [(low + 1, low + 2, low, low + 1) for low in lows]
        rows.extend([(100.5, 101, 99, 99.5), (99, 102, 97.5, 101.5)])
        frame = frame_from_rows(rows)
        frame.loc[frame.index[-1], "Volume"] = 200
        frame.index = pd.date_range("2025-01-01", periods=len(frame))
        hits = scan_symbol(
            "TEST",
            frame,
            ["S&P 500"],
            market_cap=2_100_000_000,
            order=1,
            atr_period=2,
            tolerance_atr=0.6,
            min_gap=2,
            min_touches=3,
        )
        self.assertTrue(any(hit["Side"] == "Support" for hit in hits))


if __name__ == "__main__":
    unittest.main()
