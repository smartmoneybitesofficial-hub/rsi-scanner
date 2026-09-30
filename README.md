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