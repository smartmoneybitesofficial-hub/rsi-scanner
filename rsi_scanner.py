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
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

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

    for symbol in SYMBOLS:
        try:
            df = yf.download(symbol, interval=INTERVAL, period=PERIOD, progress=False)
            if df.empty or len(df) < 2:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df["RSI"] = compute_rsi_wilder(df["Close"], RSI_PERIOD)
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
                    INTERVAL,
                    current_rsi,
                    rsi_dir,
                    f"{price_change:.2f}%",
                    candle_trend,
                    signal
                ])
        except:
            continue

    if results:
        df_result = pd.DataFrame(results, columns=[
            "Time", "Ticker", "TF", "RSI", "RSI Dir", "Price %", "Candle", "Signal"
        ])
        print(tabulate(df_result, headers="keys", tablefmt="fancy_grid", showindex=False))

        # Save to CSV (dashboard)
        df_result.to_csv(CSV_FILE, index=False)
        print(f"✅ Signals saved to {CSV_FILE}")

        # Optional email
        send_email(df_result)
    else:
        print("No extreme RSI signals right now.")

if __name__ == "__main__":
    run_rsi_scanner()
