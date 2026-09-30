import yfinance as yf
import pandas as pd
from tabulate import tabulate
from colorama import Fore, Style, init
import smtplib
from email.message import EmailMessage
import os
from datetime import datetime


# Initialize colorama
init(autoreset=True)

# ==========================
# CONFIG
# ==========================
INTERVAL = "1d"
PERIOD = "6mo"
RSI_PERIOD = 14

RSI_OVERSOLD = 20
RSI_EXTREME_OVERSOLD = 15
RSI_OVERBOUGHT = 85
RSI_EXTREME_OVERBOUGHT = 90

# Optional: Gmail for alerts (use app password)
SEND_EMAIL = True
EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

CSV_FILE = "signals.csv"
FOLLOWUP_CSV_FILE = "signal_followup.csv"
FOLLOWUP_COLUMNS = [
    "Signal Date", "Ticker", "Condition", "Signal RSI", "Entry Price",
    "Days After", "Date", "Close", "Return %"
]

# ==========================
# SYMBOL UNIVERSE
# ==========================
def get_sp500_symbols():
    try:
        url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
        df = pd.read_csv(url)
        symbols = df["Symbol"].tolist()
        symbols = [s.replace(".", "-") for s in symbols]
        return symbols
    except:
        return []

def get_major_etfs():
    return [
        "SPY", "QQQ", "IWM", "VTI", "DIA",
        "XLK", "XLF", "XLE", "XLV", "XLY",
        "XLI", "XLP", "XLB", "XLU", "XLRE",
        "ARKK", "SMH", "SOXX",
        "GLD", "SLV", "TLT", "IEF", "HYG"
    ]

def build_symbol_universe():
    symbols = sorted(list(set(get_sp500_symbols() + get_major_etfs())))
    print(f"Total symbols to scan: {len(symbols)}")
    return symbols

# ==========================
# RSI Calculation
# ==========================
def compute_rsi_wilder(series, period=14):
    delta = series.astype(float).diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    rsi = pd.Series(float("nan"), index=series.index, dtype=float)
    if len(series) <= period:
        return rsi

    average_gain = float(gains.iloc[1:period + 1].mean())
    average_loss = float(losses.iloc[1:period + 1].mean())
    for position in range(period, len(series)):
        if position > period:
            average_gain = (average_gain * (period - 1) + float(gains.iloc[position])) / period
            average_loss = (average_loss * (period - 1) + float(losses.iloc[position])) / period

        if average_loss == 0:
            rsi.iloc[position] = 50.0 if average_gain == 0 else 100.0
        elif average_gain == 0:
            rsi.iloc[position] = 0.0
        else:
            relative_strength = average_gain / average_loss
            rsi.iloc[position] = 100 - (100 / (1 + relative_strength))
    return rsi

def make_followup_row(symbol, condition, signal_date, signal_rsi, entry_price,
                      days_after, date, close):
    return {
        "Signal Date": signal_date,
        "Ticker": symbol,
        "Condition": condition,
        "Signal RSI": signal_rsi,
        "Entry Price": round(entry_price, 2),
        "Days After": days_after,
        "Date": date,
        "Close": round(close, 2),
        "Return %": round((close / entry_price - 1) * 100, 2),
    }

def load_signal_events():
    if not os.path.isfile(CSV_FILE) or os.path.getsize(CSV_FILE) == 0:
        return pd.DataFrame(columns=["Signal Date", "Ticker", "Condition", "Signal RSI"])

    signals = pd.read_csv(CSV_FILE)
    required_columns = {"Time", "Ticker", "RSI", "Signal"}
    missing_columns = required_columns.difference(signals.columns)
    if missing_columns:
        raise ValueError(
            f"{CSV_FILE} is missing required columns: {', '.join(sorted(missing_columns))}"
        )

    events = signals[["Time", "Ticker", "RSI", "Signal"]].copy()
    event_dates = pd.to_datetime(events["Time"], errors="coerce")
    event_rsi = pd.to_numeric(events["RSI"], errors="coerce")
    if event_dates.isna().any() or event_rsi.isna().any():
        raise ValueError(f"{CSV_FILE} contains invalid signal dates or RSI values")

    events["Signal Date"] = event_dates.dt.strftime("%Y-%m-%d")
    events["Ticker"] = events["Ticker"].astype(str).str.strip()
    events["Condition"] = events["Signal"].astype(str).str.strip()
    events["Signal RSI"] = event_rsi
    events = events[
        events["Condition"].str.contains("OVERSOLD|OVERBOUGHT", case=False, regex=True)
    ]
    return events[["Signal Date", "Ticker", "Condition", "Signal RSI"]].drop_duplicates(
        ["Signal Date", "Ticker", "Condition"], keep="last"
    )

def get_followup_rows_from_signals(symbol, df, signal_events):
    rows = []
    symbol_events = signal_events[signal_events["Ticker"] == symbol]
    if symbol_events.empty:
        return rows

    history = df[["Close"]].copy()
    history["Date"] = history.index.strftime("%Y-%m-%d")
    history = history.drop_duplicates("Date", keep="last").reset_index(drop=True)
    positions_by_date = {date: position for position, date in enumerate(history["Date"])}

    for event in symbol_events.to_dict("records"):
        signal_date = event["Signal Date"]
        signal_position = positions_by_date.get(signal_date)
        if signal_position is None:
            print(f"No downloaded close for {symbol} signal date {signal_date}")
            continue

        entry_price = float(history["Close"].iloc[signal_position])
        for days_after in range(min(10, len(history) - signal_position - 1) + 1):
            position = signal_position + days_after
            close = float(history["Close"].iloc[position])
            rows.append(make_followup_row(
                symbol,
                event["Condition"],
                signal_date,
                float(event["Signal RSI"]),
                entry_price,
                days_after,
                history["Date"].iloc[position],
                close,
            ))
    return rows

def save_followup_rows(new_rows):
    df_followup = pd.DataFrame(new_rows, columns=FOLLOWUP_COLUMNS)
    if not df_followup.empty:
        df_followup.sort_values(
            ["Signal Date", "Ticker", "Condition", "Days After"], inplace=True
        )
    df_followup.to_csv(FOLLOWUP_CSV_FILE, index=False)

# ==========================
# Optional: Send Email
# ==========================
# ==========================
# Professional Email Version
# ==========================

def send_email(df):
    if df.empty or not SEND_EMAIL:
        return

    # Copy df so we don't modify original
    df_email = df.copy()

    # Make ticker clickable (Yahoo Finance)
    df_email["Ticker"] = df_email["Ticker"].apply(
        lambda x: f'<a href="https://finance.yahoo.com/quote/{x}" target="_blank">{x}</a>'
    )

    # Color RSI values
    def style_rsi(val):
        if val <= RSI_OVERSOLD:
            return f'<span style="color: #00c853; font-weight: bold;">{val}</span>'
        elif val >= RSI_OVERBOUGHT:
            return f'<span style="color: #ff1744; font-weight: bold;">{val}</span>'
        return val

    df_email["RSI"] = df_email["RSI"].apply(style_rsi)

    # Highlight EXTREME signals
    def highlight_signal(val):
        if "EXTREME" in val:
            return f'<span style="color: #ff1744; font-weight: bold;">{val}</span>'
        return val

    df_email["Signal"] = df_email["Signal"].apply(highlight_signal)

    # Convert to HTML table
    html_table = df_email.to_html(index=False, escape=False)

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    html = f"""
    <html>
    <head>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background-color: #f4f6f8;
            padding: 20px;
        }}
        .container {{
            background-color: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.05);
        }}
        h2 {{
            margin-top: 0;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
        }}
        th {{
            background-color: #111827;
            color: white;
            padding: 10px;
            text-align: center;
        }}
        td {{
            border-bottom: 1px solid #ddd;
            padding: 8px;
            text-align: center;
        }}
        tr:hover {{
            background-color: #f1f1f1;
        }}
        .footer {{
            margin-top: 20px;
            font-size: 12px;
            color: #777;
        }}
    </style>
    </head>
    <body>
        <div class="container">
            <h2>📊 RSI Extreme Signals</h2>
            <p><strong>Scan Time:</strong> {timestamp}</p>
            {html_table}
            <div class="footer">
                Generated automatically by your RSI Scanner system.
            </div>
        </div>
    </body>
    </html>
    """

    msg = EmailMessage()
    msg["Subject"] = "📊 RSI Extreme Signals Alert"
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    msg.set_content("Your email client does not support HTML.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
        print("✅ Professional email sent successfully")
    except Exception as e:
        print("❌ Failed to send email:", e)


# ==========================
# RSI Scanner
# ==========================
def run_rsi_scanner():
    SYMBOLS = build_symbol_universe()
    results = []
    existing_events = load_signal_events()
    SYMBOLS = sorted(set(SYMBOLS + existing_events["Ticker"].tolist()))
    price_history = {}

    for symbol in SYMBOLS:
        try:
            df = yf.download(symbol, interval=INTERVAL, period=PERIOD, progress=False)
            if df.empty or len(df) < 2:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df["RSI"] = compute_rsi_wilder(df["Close"], RSI_PERIOD)
            price_history[symbol] = df
            current_rsi = round(float(df["RSI"].iloc[-1]), 2)
            previous_rsi = float(df["RSI"].iloc[-2])

            # RSI Direction
            if current_rsi > previous_rsi:
                rsi_dir = "Rising"
            elif current_rsi < previous_rsi:
                rsi_dir = "Falling"
            else:
                rsi_dir = "Flat"

            # Price change
            current_price = round(float(df["Close"].iloc[-1]), 2)
            price_change = round(((df["Close"].iloc[-1] - df["Close"].iloc[-2]) / df["Close"].iloc[-2]) * 100, 2)
            candle_trend = "🟢" if price_change>0 else "🔴" if price_change<0 else "➖"

            # Signal
            signal = None
            if current_rsi <= RSI_EXTREME_OVERSOLD:
                signal = "EXTREME OVERSOLD"
            elif current_rsi <= RSI_OVERSOLD:
                signal = "OVERSOLD"
            elif current_rsi >= RSI_EXTREME_OVERBOUGHT:
                signal = "EXTREME OVERBOUGHT"
            elif current_rsi >= RSI_OVERBOUGHT:
                signal = "OVERBOUGHT"

            if signal:
                results.append([
                    df.index[-1].strftime("%Y-%m-%d %H:%M"),
                    symbol,
                    current_price,
                    INTERVAL,
                    current_rsi,
                    rsi_dir,
                    f"{price_change:.2f}%",
                    candle_trend,
                    signal
                ])
        except Exception as error:
            print(f"Failed to process {symbol}: {error}")
            continue

    if results:
        df_result = pd.DataFrame(results, columns=[
            "Time", "Ticker", "Price", "TF", "RSI", "RSI Dir", "Price %", "Candle", "Signal"
        ])
        print(tabulate(df_result, headers="keys", tablefmt="fancy_grid", showindex=False))

        # Append this scan to the historical CSV (dashboard)
        csv_has_content = os.path.isfile(CSV_FILE) and os.path.getsize(CSV_FILE) > 0
        df_result.to_csv(CSV_FILE, mode="a", header=not csv_has_content, index=False)
        print(f"✅ Signals saved to {CSV_FILE}")

        # Optional email
        send_email(df_result)
    else:
        print("No extreme RSI signals right now.")

    signal_events = load_signal_events()
    followup_rows = []
    for symbol, history in price_history.items():
        followup_rows.extend(
            get_followup_rows_from_signals(symbol, history, signal_events)
        )
    save_followup_rows(followup_rows)
    print(f"✅ Signal follow-ups saved to {FOLLOWUP_CSV_FILE}")

if __name__ == "__main__":
    run_rsi_scanner()
