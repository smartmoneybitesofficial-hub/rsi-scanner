"""Daily S&P 500 and Nasdaq-100 support/resistance reversal scanner."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Iterable
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf


SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_API_URL = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
OHLC_COLUMNS = ("Open", "High", "Low", "Close")
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "support_resistance_signals.csv"


@dataclass(frozen=True)
class Pivot:
    position: int
    price: float
    atr: float


@dataclass(frozen=True)
class Zone:
    side: str
    low: float
    high: float
    touches: int
    last_touch: pd.Timestamp
    score: float


def _column_name(column: object) -> str:
    return str(column).strip().lower().replace(" ", "").replace("_", "")


def _ticker_column(frame: pd.DataFrame) -> str:
    for column in frame.columns:
        if _column_name(column) in {"symbol", "ticker", "tickersymbol"}:
            return column
    raise ValueError(f"Could not find a ticker column in constituent table: {list(frame.columns)}")


def get_universe(indexes: Iterable[str]) -> dict[str, list[str]]:
    """Fetch current index members; symbols are normalized for Yahoo Finance."""
    members: dict[str, list[str]] = {}
    sources = {
        "sp500": ("S&P 500", SP500_URL, False),
        "nasdaq100": ("Nasdaq-100", NASDAQ100_API_URL, True),
    }
    for index in indexes:
        label, url, is_json = sources[index]
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; SupportResistanceScanner/1.0)",
                "Accept": "application/json" if is_json else "text/html",
            },
        )
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
        if is_json:
            rows = json.loads(body)["data"]["data"]["rows"]
            symbols = pd.Series([row["symbol"] for row in rows], dtype="string")
        else:
            tables = pd.read_html(StringIO(body))
            constituent_table = next(
                (table for table in tables if any(
                    _column_name(column) in {"symbol", "ticker", "tickersymbol"}
                    for column in table.columns
                )),
                None,
            )
            if constituent_table is None:
                raise ValueError(f"No ticker table found on {url}")
            column = _ticker_column(constituent_table)
            symbols = constituent_table[column]

        symbols = (
            symbols.dropna()
            .astype(str)
            .str.strip()
            .str.replace(".", "-", regex=False)
        )
        for symbol in symbols:
            if symbol:
                members.setdefault(symbol, [])
                if label not in members[symbol]:
                    members[symbol].append(label)

    if not members:
        raise RuntimeError("The selected index constituents could not be loaded.")
    return members


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Wilder-style ATR using a rolling mean of true range."""
    high = pd.to_numeric(df["High"], errors="coerce")
    low = pd.to_numeric(df["Low"], errors="coerce")
    close = pd.to_numeric(df["Close"], errors="coerce")
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period, min_periods=period).mean()


def find_pivots(
    df: pd.DataFrame,
    side: str,
    order: int = 5,
    atr_period: int = 14,
) -> list[Pivot]:
    """Return confirmed swing highs or lows; right-side bars confirm each pivot."""
    if side not in {"support", "resistance"}:
        raise ValueError("side must be 'support' or 'resistance'")
    if order < 1:
        raise ValueError("order must be at least 1")

    values = pd.to_numeric(df["Low" if side == "support" else "High"], errors="coerce")
    atr = compute_atr(df, atr_period)
    pivots: list[Pivot] = []
    for position in range(order, len(df) - order):
        value = float(values.iloc[position])
        left = values.iloc[position - order:position]
        right = values.iloc[position + 1:position + order + 1]
        current_atr = float(atr.iloc[position])
        if not math.isfinite(value) or not math.isfinite(current_atr) or current_atr <= 0:
            continue

        if side == "support":
            is_pivot = value < float(left.min()) and value <= float(right.min())
        else:
            is_pivot = value > float(left.max()) and value >= float(right.max())
        if is_pivot:
            pivots.append(Pivot(position, value, current_atr))
    return pivots


def _separated_pivots(pivots: list[Pivot], min_gap: int, side: str) -> list[Pivot]:
    """Avoid counting a tight run of neighboring pivots as separate tests."""
    selected: list[Pivot] = []
    for pivot in sorted(pivots, key=lambda item: item.position):
        if not selected or pivot.position - selected[-1].position >= min_gap:
            selected.append(pivot)
            continue
        previous = selected[-1]
        is_stronger = (
            pivot.price < previous.price if side == "support"
            else pivot.price > previous.price
        )
        if is_stronger:
            selected[-1] = pivot
    return selected


def _cluster_pivots(
    pivots: list[Pivot],
    side: str,
    tolerance_atr: float,
    min_gap: int,
    min_touches: int,
    dates: pd.Index,
    latest_position: int,
) -> list[Zone]:
    ordered = sorted(pivots, key=lambda item: item.price)
    clusters: list[list[Pivot]] = []
    for pivot in ordered:
        matching_cluster: list[Pivot] | None = None
        best_distance = math.inf
        for cluster in clusters:
            center = sum(item.price for item in cluster) / len(cluster)
            cluster_atr = sum(item.atr for item in cluster) / len(cluster)
            distance = abs(pivot.price - center)
            if distance <= tolerance_atr * (pivot.atr + cluster_atr) / 2 and distance < best_distance:
                matching_cluster = cluster
                best_distance = distance
        if matching_cluster is None:
            clusters.append([pivot])
        else:
            matching_cluster.append(pivot)

    zones: list[Zone] = []
    latest_date = pd.Timestamp(dates[latest_position])
    for cluster in clusters:
        distinct = _separated_pivots(cluster, min_gap, side)
        if len(distinct) < min_touches:
            continue
        median_atr = sorted(item.atr for item in distinct)[len(distinct) // 2]
        padding = tolerance_atr * median_atr / 2
        prices = [item.price for item in distinct]
        last_touch = pd.Timestamp(dates[max(item.position for item in distinct)])
        days_since_touch = max(0, (latest_date - last_touch).days)
        score = len(distinct) * 10 + max(0.0, 5.0 - days_since_touch / 60.0)
        zones.append(
            Zone(
                side=side,
                low=min(prices) - padding,
                high=max(prices) + padding,
                touches=len(distinct),
                last_touch=last_touch,
                score=score,
            )
        )
    return zones


def find_zones(
    df: pd.DataFrame,
    *,
    order: int = 5,
    atr_period: int = 14,
    tolerance_atr: float = 0.6,
    min_gap: int = 8,
    min_touches: int = 3,
) -> list[Zone]:
    """Build independent support and resistance zones from confirmed pivots."""
    if df.empty:
        return []
    if tolerance_atr <= 0 or min_gap < 1 or min_touches < 1:
        raise ValueError("tolerance_atr, min_gap, and min_touches must be positive")

    zones: list[Zone] = []
    for side in ("support", "resistance"):
        pivots = find_pivots(df, side, order=order, atr_period=atr_period)
        zones.extend(
            _cluster_pivots(
                pivots,
                side,
                tolerance_atr,
                min_gap,
                min_touches,
                df.index,
                len(df) - 1,
            )
        )
    return zones


def detect_reversal_patterns(df: pd.DataFrame) -> dict[str, list[str]]:
    """Detect common one- and three-candle reversals on the latest completed bar."""
    empty = {"bullish": [], "bearish": []}
    if len(df) < 3:
        return empty

    candles = df.loc[:, OHLC_COLUMNS].astype(float).reset_index(drop=True)
    current = candles.iloc[-1]
    previous = candles.iloc[-2]
    first = candles.iloc[-3]

    def stats(candle: pd.Series) -> tuple[float, float, float, float]:
        body = abs(float(candle["Close"] - candle["Open"]))
        candle_range = float(candle["High"] - candle["Low"])
        upper = float(candle["High"] - max(candle["Open"], candle["Close"]))
        lower = float(min(candle["Open"], candle["Close"]) - candle["Low"])
        return body, candle_range, upper, lower

    result = {"bullish": [], "bearish": []}
    body, candle_range, upper, lower = stats(current)
    if candle_range <= 0:
        return result

    if body / candle_range <= 0.1:
        result["bullish"].append("Doji")
        result["bearish"].append("Doji")
        if lower / candle_range >= 0.6 and upper / candle_range <= 0.15:
            result["bullish"].append("Dragonfly Doji")
        if upper / candle_range >= 0.6 and lower / candle_range <= 0.15:
            result["bearish"].append("Gravestone Doji")
    elif body > 0:
        if lower >= 2 * body and upper <= body * 0.5 and min(
            current["Open"], current["Close"]
        ) >= current["Low"] + candle_range * 0.55:
            result["bullish"].append("Hammer")
        if upper >= 2 * body and lower <= body * 0.5 and max(
            current["Open"], current["Close"]
        ) <= current["Low"] + candle_range * 0.45:
            result["bearish"].append("Shooting Star")

    if (
        previous["Close"] < previous["Open"]
        and current["Close"] > current["Open"]
        and current["Open"] <= previous["Close"]
        and current["Close"] >= previous["Open"]
    ):
        result["bullish"].append("Bullish Engulfing")
    if (
        previous["Close"] > previous["Open"]
        and current["Close"] < current["Open"]
        and current["Open"] >= previous["Close"]
        and current["Close"] <= previous["Open"]
    ):
        result["bearish"].append("Bearish Engulfing")

    first_body = abs(float(first["Close"] - first["Open"]))
    previous_body = abs(float(previous["Close"] - previous["Open"]))
    midpoint = (float(first["Open"]) + float(first["Close"])) / 2
    if (
        first["Close"] < first["Open"]
        and previous_body <= first_body * 0.5
        and current["Close"] > current["Open"]
        and current["Close"] >= midpoint
    ):
        result["bullish"].append("Morning Star")
    if (
        first["Close"] > first["Open"]
        and previous_body <= first_body * 0.5
        and current["Close"] < current["Open"]
        and current["Close"] <= midpoint
    ):
        result["bearish"].append("Evening Star")
    return result


def scan_symbol(
    symbol: str,
    df: pd.DataFrame,
    indexes: list[str],
    *,
    order: int = 5,
    atr_period: int = 14,
    tolerance_atr: float = 0.6,
    min_gap: int = 8,
    min_touches: int = 3,
) -> list[dict[str, object]]:
    """Return reversal signals only when the latest candle tests a matching zone."""
    required = set(OHLC_COLUMNS)
    if not required.issubset(df.columns):
        missing = ", ".join(sorted(required.difference(df.columns)))
        raise ValueError(f"{symbol} is missing OHLC columns: {missing}")
    data = df.dropna(subset=list(OHLC_COLUMNS)).sort_index()
    if len(data) < max(atr_period + order * 2 + 1, 30):
        return []

    patterns = detect_reversal_patterns(data)
    latest = data.iloc[-1]
    latest_atr = float(compute_atr(data, atr_period).iloc[-1])
    if not math.isfinite(latest_atr) or latest_atr <= 0:
        return []

    results: list[dict[str, object]] = []
    candidate_zones = find_zones(
        data,
        order=order,
        atr_period=atr_period,
        tolerance_atr=tolerance_atr,
        min_gap=min_gap,
        min_touches=max(1, min_touches - 1),
    )
    for zone in candidate_zones:
        if float(latest["Low"]) > zone.high or float(latest["High"]) < zone.low:
            continue
        matching_patterns = patterns["bullish" if zone.side == "support" else "bearish"]
        total_touches = zone.touches + 1
        if total_touches < min_touches or not matching_patterns:
            continue
        results.append(
            {
                "Date": pd.Timestamp(data.index[-1]).strftime("%Y-%m-%d"),
                "Ticker": symbol,
                "Index": ", ".join(indexes),
                "Side": zone.side.title(),
                "Zone Low": round(zone.low, 2),
                "Zone High": round(zone.high, 2),
                "Close": round(float(latest["Close"]), 2),
                "Touches": total_touches,
                "Last Touch": pd.Timestamp(data.index[-1]).strftime("%Y-%m-%d"),
                "Pattern": ", ".join(matching_patterns),
                "Score": round(total_touches * 10 + 5.0, 2),
            }
        )
    return results


def _extract_ticker_frame(download: pd.DataFrame, symbol: str) -> pd.DataFrame | None:
    if download.empty:
        return None
    frame = download
    if isinstance(download.columns, pd.MultiIndex):
        frame = None
        for level in range(download.columns.nlevels):
            values = download.columns.get_level_values(level).astype(str)
            match = next((value for value in values.unique() if value.upper() == symbol.upper()), None)
            if match is not None:
                frame = download.xs(match, axis=1, level=level, drop_level=True)
                break
        if frame is None and download.columns.nlevels == 2 and len(download.columns) == 5:
            frame = download.copy()
            frame.columns = download.columns.get_level_values(0)
    if frame is None:
        return None
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.rename(columns={column: str(column).title() for column in frame.columns})
    if not set(OHLC_COLUMNS).issubset(frame.columns):
        return None
    return frame


def download_history(
    symbols: Iterable[str],
    *,
    period: str = "2y",
    interval: str = "1d",
    batch_size: int = 25,
) -> dict[str, pd.DataFrame]:
    """Download OHLCV in modest batches to reduce API requests and rate limiting."""
    ticker_list = list(symbols)
    histories: dict[str, pd.DataFrame] = {}
    for start in range(0, len(ticker_list), batch_size):
        batch = ticker_list[start:start + batch_size]
        downloaded = yf.download(
            tickers=batch,
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=False,
            threads=True,
            progress=False,
        )
        for symbol in batch:
            frame = _extract_ticker_frame(downloaded, symbol)
            if frame is not None and not frame.empty:
                clean_frame = frame.dropna(subset=list(OHLC_COLUMNS))
                if not clean_frame.empty:
                    histories[symbol] = clean_frame
        missing = [symbol for symbol in batch if symbol not in histories]
        if missing:
            print(f"Warning: no usable price history for {', '.join(missing)}", file=sys.stderr)
    if ticker_list and not histories:
        raise RuntimeError("Yahoo Finance returned no usable price history for any ticker.")
    return histories


def run_scan(
    *,
    indexes: Iterable[str] = ("sp500", "nasdaq100"),
    period: str = "2y",
    order: int = 5,
    atr_period: int = 14,
    tolerance_atr: float = 0.6,
    min_gap: int = 8,
    min_touches: int = 3,
    output: Path = DEFAULT_OUTPUT,
) -> pd.DataFrame:
    members = get_universe(indexes)
    print(f"Downloading daily prices for {len(members)} unique index members.")
    histories = download_history(members, period=period)
    results: list[dict[str, object]] = []
    for symbol, history in histories.items():
        try:
            results.extend(
                scan_symbol(
                    symbol,
                    history,
                    members[symbol],
                    order=order,
                    atr_period=atr_period,
                    tolerance_atr=tolerance_atr,
                    min_gap=min_gap,
                    min_touches=min_touches,
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            print(f"Warning: skipping {symbol}: {error}", file=sys.stderr)

    columns = [
        "Date", "Ticker", "Index", "Side", "Zone Low", "Zone High", "Close",
        "Touches", "Last Touch", "Pattern", "Score",
    ]
    result = pd.DataFrame(results, columns=columns)
    if not result.empty:
        result.sort_values(
            ["Score", "Touches", "Ticker"],
            ascending=[False, False, True],
            inplace=True,
            ignore_index=True,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)
    if result.empty:
        print("No support/resistance reversal setups found.")
    else:
        print(result.to_string(index=False))
    print(f"Saved {len(result)} setup(s) to {output}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--indexes",
        nargs="+",
        choices=("sp500", "nasdaq100"),
        default=["sp500", "nasdaq100"],
        help="Index universes to scan (default: both)",
    )
    parser.add_argument("--period", default="2y", help="Yahoo Finance history period (default: 2y)")
    parser.add_argument("--order", type=int, default=5, help="Bars on each side to confirm a pivot")
    parser.add_argument("--atr-period", type=int, default=14)
    parser.add_argument("--tolerance-atr", type=float, default=0.6)
    parser.add_argument("--min-gap", type=int, default=8)
    parser.add_argument("--min-touches", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_scan(
        indexes=args.indexes,
        period=args.period,
        order=args.order,
        atr_period=args.atr_period,
        tolerance_atr=args.tolerance_atr,
        min_gap=args.min_gap,
        min_touches=args.min_touches,
        output=args.output,
    )


if __name__ == "__main__":
    main()
