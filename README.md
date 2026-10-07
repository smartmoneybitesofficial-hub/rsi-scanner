# rsi-scanner
It is Daily RSI Scanner for SP500 List + SOME ETFs appx 525 symbols.

## View RSI signal follow-ups in Google Sheets

The scanner uses each oversold or overbought row in `signals.csv` as a
tracking event. For each ticker and signal date, `signal_followup.csv`
contains the signal RSI, the close on the signal date (`Days After` 0), and
the next 10 trading days' closes and returns. Repeated copies of the same
ticker, date, and signal are treated as one event. Prices are available only
for signal dates within Yahoo Finance's downloaded history (`PERIOD` in the
scanner configuration).

To view the data in Google Sheets:

1. Create a blank Google Sheet and select cell A1.
2. Enter this formula in A1:

   ```gs
   =IMPORTDATA("https://raw.githubusercontent.com/smartmoneybitesofficial-hub/rsi-scanner/main/signal_followup.csv")
   ```

3. Select the imported data and use **Insert → Chart**. Use `Days After` for
   the horizontal axis and `Close` for the price series. Filter by `Ticker`,
   `Signal Date`, and `Condition` to focus on one event. `Signal RSI` and
   `Return %` are included for analysis.

The repository must be public for this import formula to read the CSV without
additional authentication. Sheets refreshes imported data periodically rather
than immediately after each scan.

## Support and resistance reversal scanner

The `support-resistence-scanner` directory contains a separate daily scanner
for the S&P 500 and Nasdaq-100. It clusters confirmed swing lows and highs
using an ATR-based tolerance, requires at least three distinct touches, and
reports setups when the latest candle tests a zone and forms a matching
hammer, shooting star, engulfing, morning/evening star, or doji pattern.
The current reversal candle counts as the latest touch. Results are filtered to
stocks with market capitalization strictly above $2 billion and latest
pattern-day volume at least 1.5 times the preceding 20-session average
(excluding the pattern day). Market caps are loaded in bulk from Nasdaq's
exchange screener, with Yahoo Finance as a fallback for unmatched listings.

Install its dependencies and run both index universes with:

```sh
python -m pip install -r support-resistence-scanner/requirements.txt
python support-resistence-scanner/support_resistance_scanner.py
```

Use `--indexes sp500` or `--indexes nasdaq100` to scan one index. The defaults
are a 5-bar swing window, ATR(14), a 0.6 ATR clustering tolerance, an 8-bar
minimum gap between touches, and 3 minimum touches. Adjust these with
`--order`, `--atr-period`, `--tolerance-atr`, `--min-gap`, and `--min-touches`.
The CSV is written to `support-resistence-scanner/support_resistance_signals.csv`
by default and includes a clickable **Open chart** hyperlink for each ticker,
plus market cap in billions and the pattern-day volume ratio. Tune the quality
filters with `--min-market-cap` (billions; default 2),
`--volume-lookback`, and `--min-volume-ratio`.

The scheduled **Support and Resistance Scanner** GitHub Actions workflow runs
on weekdays and uploads its CSV as a downloadable artifact retained for 30
days. It can also be started manually from the Actions tab.