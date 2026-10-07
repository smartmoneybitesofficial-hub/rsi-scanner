import sys
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support_resistance_scanner import (  # noqa: E402
    detect_reversal_patterns,
    build_html_report,
    find_pivots,
    run_scan,
    save_history,
    scan_symbol,
    send_email_report,
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
            support_hit["Chart URL"],
            "https://finance.yahoo.com/quote/TEST/chart/",
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

    def test_html_report_has_clickable_yahoo_chart_link(self):
        report = build_html_report(
            pd.DataFrame(
                [{
                    "Ticker": "TEST",
                    "Chart URL": "https://finance.yahoo.com/quote/TEST/chart/",
                }]
            )
        )
        self.assertIn(
            '<a href="https://finance.yahoo.com/quote/TEST/chart/">Open chart</a>',
            report,
        )

    def test_email_report_sends_html_using_configured_gmail_credentials(self):
        results = pd.DataFrame([{"Date": "2026-10-07", "Ticker": "TEST"}])
        html_report = "<html><body>Daily scan</body></html>"
        with (
            patch.dict(
                os.environ,
                {
                    "EMAIL_FROM": "scanner@example.com",
                    "EMAIL_TO": "recipient@example.com",
                    "EMAIL_PASSWORD": "test-app-password",
                },
            ),
            patch("support_resistance_scanner.smtplib.SMTP_SSL") as smtp,
        ):
            send_email_report(results, html_report, "2026-10-07")

        server = smtp.return_value.__enter__.return_value
        server.login.assert_called_once_with("scanner@example.com", "test-app-password")
        message = server.send_message.call_args.args[0]
        self.assertEqual(message["To"], "recipient@example.com")
        self.assertIn("Daily scan", message.get_payload()[1].get_content())

    def test_history_keeps_previous_dates_and_replaces_same_day_on_retry(self):
        columns = ["Date", "Ticker", "Chart URL", "Score"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.csv"
            save_history(
                pd.DataFrame(
                    [
                        ["2026-10-06", "OLD", "https://finance.yahoo.com/quote/OLD/chart/", 30],
                        ["2026-10-07", "STALE", "https://finance.yahoo.com/quote/STALE/chart/", 20],
                    ],
                    columns=columns,
                ),
                path,
                "2026-10-07",
            )
            current = pd.DataFrame(
                [["2026-10-07", "NEW", "https://finance.yahoo.com/quote/NEW/chart/", 40]],
                columns=columns,
            )
            save_history(current, path, "2026-10-07")
            history = pd.read_csv(path)

        self.assertEqual(history["Ticker"].tolist(), ["OLD", "NEW"])

    def test_run_scan_writes_history_and_html_report(self):
        lows = [100] * 40
        lows[7] = 98
        lows[21] = 98
        rows = [(low + 1, low + 2, low, low + 1) for low in lows]
        rows.extend([(100.5, 101, 99, 99.5), (99, 102, 97.5, 101.5)])
        frame = frame_from_rows(rows)
        frame.loc[frame.index[-1], "Volume"] = 200
        frame.index = pd.date_range("2026-10-01", periods=len(frame))

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "history.csv"
            html_output = Path(directory) / "report.html"
            with (
                patch("support_resistance_scanner.get_universe", return_value={"TEST": ["S&P 500"]}),
                patch("support_resistance_scanner.get_market_caps", return_value={"TEST": 15_000_000_000}),
                patch("support_resistance_scanner.download_history", return_value={"TEST": frame}),
            ):
                results = run_scan(
                    indexes=["sp500"],
                    order=1,
                    atr_period=2,
                    min_gap=2,
                    output=output,
                    html_output=html_output,
                )

            history = pd.read_csv(output)
            report = html_output.read_text(encoding="utf-8")

        self.assertFalse(results.empty)
        self.assertTrue(any("TEST" == ticker for ticker in history["Ticker"]))
        self.assertIn(
            '<a href="https://finance.yahoo.com/quote/TEST/chart/">Open chart</a>',
            report,
        )


if __name__ == "__main__":
    unittest.main()
