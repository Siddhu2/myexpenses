#!/usr/bin/env python3
"""
Helpers for loading gold articles and fetching live gold rates.
"""

import csv
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
GOLD_CSV_PATH = BASE_DIR / "data" / "gold_articles.csv"
GOLD_RATES_PATH = BASE_DIR / "data" / "gold_rates.json"

GOLD_FIELDS = ["item_id", "name", "karat", "grams", "notes", "created_at"]
KARAT_PURITY = {"24K": 1.0, "22K": 22 / 24, "18K": 18 / 24}
TROY_OUNCE_GRAMS = 31.1034768


def _fetch_json(url, timeout=10):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "expense-dashboard/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return json.loads(resp.read().decode(charset))


def load_gold_articles():
    if not GOLD_CSV_PATH.exists():
        return []
    with open(GOLD_CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_gold_article(record):
    GOLD_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not GOLD_CSV_PATH.exists() or GOLD_CSV_PATH.stat().st_size == 0
    with open(GOLD_CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=GOLD_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({k: record.get(k, "") for k in GOLD_FIELDS})


def delete_gold_article(item_id):
    if not GOLD_CSV_PATH.exists():
        return False
    with open(GOLD_CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    new_rows = [r for r in rows if r.get("item_id") != item_id]
    if len(new_rows) == len(rows):
        return False
    with open(GOLD_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=GOLD_FIELDS)
        writer.writeheader()
        writer.writerows(new_rows)
    return True


def load_gold_rates():
    if not GOLD_RATES_PATH.exists():
        return {}
    with open(GOLD_RATES_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_gold_rates(payload):
    GOLD_RATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(GOLD_RATES_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def fetch_live_gold_rates():
    """
    Fetch India gold rates per gram.

    Primary source:
    - GoldPricesIndia India rate page

    Fallback:
    - Global spot gold (USD/oz) + USDINR FX conversion
    """
    try:
        req = urllib.request.Request(
            "https://www.goldpricesindia.com/",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode(resp.headers.get_content_charset() or "utf-8", errors="replace")

        text = re.sub(r"<[^>]+>", " ", html)
        text = text.replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text)

        m24 = re.search(r"Gold Price Today in India is ([\d,]+) Indian Rupee \(INR\)/gram 24K", text, re.IGNORECASE)
        m22 = re.search(r"1 g 22K\s*([\d,]+)", text, re.IGNORECASE)
        mdate = re.search(r"Last update:\s*([^.]+\.)", text, re.IGNORECASE)

        if m24 and m22:
            rate_24k = float(m24.group(1).replace(",", ""))
            rate_22k = float(m22.group(1).replace(",", ""))
            payload = {
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source_timestamp": mdate.group(1) if mdate else "",
                "provider": "goldpricesindia.com",
                "rates": {
                    "24K": rate_24k,
                    "22K": rate_22k,
                    "18K": round(rate_24k * KARAT_PURITY["18K"], 2),
                },
            }
            save_gold_rates(payload)
            return payload
    except Exception:
        pass

    gold = _fetch_json("https://api.gold-api.com/price/XAU")
    usd_per_ounce = float(gold["price"])
    fx = _fetch_json("https://open.er-api.com/v6/latest/USD")
    inr_per_usd = float(fx["rates"]["INR"])
    rate_24k = round((usd_per_ounce / TROY_OUNCE_GRAMS) * inr_per_usd, 2)
    source_timestamp = gold.get("updatedAt") or gold.get("updated_at") or fx.get("time_last_update_utc") or ""

    payload = {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_timestamp": source_timestamp,
        "provider": "gold-api.com + open.er-api.com (fallback)",
        "rates": {
            "24K": round(rate_24k, 2),
            "22K": round(rate_24k * KARAT_PURITY["22K"], 2),
            "18K": round(rate_24k * KARAT_PURITY["18K"], 2),
        },
    }
    save_gold_rates(payload)
    return payload
