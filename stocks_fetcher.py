#!/usr/bin/env python3.9
"""
Groww Stock Portfolio Fetcher
Fetches holdings via Groww API + live prices via Yahoo Finance, saves to stocks.csv.

Usage:
  python3.9 stocks_fetcher.py
"""

import csv
from datetime import datetime
from pathlib import Path

from config_loader import load_env_file

CSV_PATH   = Path(__file__).parent / "data" / "stocks.csv"
FIELDNAMES = [
    "symbol", "isin", "quantity", "average_price", "invested_value",
    "current_price", "current_value", "pnl", "pnl_pct",
    "t1_quantity", "demat_free_quantity", "last_updated",
]


def load_token():
    token = load_env_file().get("GROWW_API_TOKEN")
    if token:
        return token
    raise ValueError("GROWW_API_TOKEN not found in config/.env")


def fetch_holdings(token):
    from growwapi import GrowwAPI
    groww = GrowwAPI(token)
    response = groww.get_holdings_for_user(timeout=10)
    if isinstance(response, dict):
        payload  = response.get("payload", response)
        holdings = payload.get("holdings", payload) if isinstance(payload, dict) else payload
        if isinstance(holdings, list):
            return holdings
    raise ValueError(f"Unexpected response format: {response}")


def fetch_current_prices(symbols):
    """
    Fetch latest prices for all symbols in one batch from Yahoo Finance (NSE).
    Returns dict: { symbol: price_float }. Price is None if not found.
    """
    import yfinance as yf

    ns_tickers = [s + ".NS" for s in symbols]
    print(f"[*] Fetching live prices from Yahoo Finance ({len(symbols)} stocks)...")

    data = yf.download(ns_tickers, period="1d", auto_adjust=True, progress=False)

    prices = {}
    if not data.empty:
        close = data["Close"].iloc[-1] if len(data) > 0 else data["Close"]
        for sym in symbols:
            ticker_key = sym + ".NS"
            val = close.get(ticker_key)
            if val is not None:
                import math
                prices[sym] = None if math.isnan(float(val)) else round(float(val), 2)
            else:
                prices[sym] = None

    # For any symbol that returned None, try BSE (.BO) as fallback
    missing = [s for s in symbols if not prices.get(s)]
    if missing:
        print(f"    Retrying {len(missing)} symbols on BSE (.BO)...")
        bo_tickers = [s + ".BO" for s in missing]
        data2 = yf.download(bo_tickers, period="1d", auto_adjust=True, progress=False)
        if not data2.empty:
            close2 = data2["Close"].iloc[-1]
            for sym in missing:
                val = close2.get(sym + ".BO")
                if val is not None:
                    import math
                    prices[sym] = None if math.isnan(float(val)) else round(float(val), 2)

    found   = sum(1 for v in prices.values() if v is not None)
    missing = len(symbols) - found
    print(f"    Prices fetched: {found}/{len(symbols)}" + (f"  ({missing} not found)" if missing else ""))
    return prices


def build_rows(holdings, prices):
    now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for h in holdings:
        sym = h.get("trading_symbol", "")
        qty = float(h.get("quantity", 0))
        avg = float(h.get("average_price", 0))
        cur = prices.get(sym)

        invested = round(qty * avg, 2)
        cur_val  = round(qty * cur, 2) if cur is not None else ""
        pnl      = round(cur_val - invested, 2) if cur is not None else ""
        pnl_pct  = round((pnl / invested) * 100, 2) if cur is not None and invested else ""

        rows.append({
            "symbol":              sym,
            "isin":                h.get("isin", ""),
            "quantity":            qty,
            "average_price":       avg,
            "invested_value":      invested,
            "current_price":       cur if cur is not None else "",
            "current_value":       cur_val,
            "pnl":                 pnl,
            "pnl_pct":             pnl_pct,
            "t1_quantity":         float(h.get("t1_quantity", 0)),
            "demat_free_quantity": float(h.get("demat_free_quantity", 0)),
            "last_updated":        now,
        })

    rows.sort(key=lambda r: r["invested_value"], reverse=True)
    return rows


def save_csv(rows):
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    print("[*] Loading Groww API token...")
    token = load_token()

    print("[*] Fetching holdings from Groww...")
    holdings = fetch_holdings(token)
    print(f"    {len(holdings)} holdings found")

    symbols = [h.get("trading_symbol", "") for h in holdings]
    prices  = fetch_current_prices(symbols)
    rows    = build_rows(holdings, prices)
    save_csv(rows)

    total_invested = sum(r["invested_value"] for r in rows)
    total_current  = sum(r["current_value"] for r in rows if r["current_value"] != "")
    total_pnl      = total_current - total_invested if total_current else 0

    print(f"\n{'─'*80}")
    print(f"  {'Symbol':<12} {'Qty':>6} {'Avg':>10} {'Invested':>12} {'CMP':>10} {'Cur.Val':>12} {'P&L':>10}")
    print(f"{'─'*80}")
    for r in rows:
        pnl_str = f"{r['pnl']:+.2f}" if r["pnl"] != "" else "  —"
        cmp_str = f"{r['current_price']:.2f}" if r["current_price"] != "" else "—"
        cv_str  = f"{r['current_value']:.2f}" if r["current_value"] != "" else "—"
        print(f"  {r['symbol']:<12} {r['quantity']:>6.0f} {r['average_price']:>10.2f} "
              f"{r['invested_value']:>12.2f} {cmp_str:>10} {cv_str:>12} {pnl_str:>10}")
    print(f"{'─'*80}")
    print(f"  {'Total Invested':.<44} Rs.{total_invested:>10.2f}")
    if total_current:
        print(f"  {'Total Current Value':.<44} Rs.{total_current:>10.2f}")
        print(f"  {'Total P&L':.<44} Rs.{total_pnl:>+10.2f}")
    print(f"{'─'*80}\n")
    print(f"[✓] Saved {len(rows)} holdings → {CSV_PATH}")
