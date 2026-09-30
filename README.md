# rsi-scanner
It is Daily RSI Scanner for SP500 List + SOME ETFs appx 525 symbols.

## View oversold signal follow-ups in Google Sheets

The daily GitHub Actions scan updates `signal_followup.csv` with the closing
price for each oversold RSI entry and the next 10 trading days. An entry is
recorded when RSI crosses down to 20 or lower; another event for that ticker
is recorded only after RSI rises above 20 and crosses down again. `Days After`
0 is the trigger-day closing price, and days 1-10 are subsequent trading days.
Returns are measured from the trigger-day close.

To view the data in Google Sheets:

1. Create a blank Google Sheet and select cell A1.
2. Enter this formula in A1:

   ```gs
   =IMPORTDATA("https://raw.githubusercontent.com/smartmoneybitesofficial-hub/rsi-scanner/main/signal_followup.csv")
   ```

3. Select the imported data and use **Insert → Chart**. Use `Date` for the
   horizontal axis and `Close` for the price series. Filter by `Ticker` and
   `Signal Date` to focus on one event; `Signal RSI` is the RSI value on day 0.

The repository must be public for this import formula to read the CSV without
additional authentication. Sheets refreshes imported data periodically rather
than immediately after each scan.