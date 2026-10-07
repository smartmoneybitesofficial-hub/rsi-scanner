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
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"])


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
        frame.index = pd.date_range("2025-01-01", periods=len(frame))
        hits = scan_symbol(
            "TEST",
            frame,
            ["S&P 500"],
            order=1,
            atr_period=2,
            tolerance_atr=0.6,
            min_gap=2,
            min_touches=3,
        )
        self.assertTrue(any(hit["Side"] == "Support" for hit in hits))
        support_hit = next(hit for hit in hits if hit["Side"] == "Support")
        self.assertGreaterEqual(support_hit["Touches"], 3)
        self.assertEqual(support_hit["Last Touch"], frame.index[-1].strftime("%Y-%m-%d"))


if __name__ == "__main__":
    unittest.main()
