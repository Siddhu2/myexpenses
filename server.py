#!/usr/bin/env python3
"""
Local dashboard server for expense tracker.
Usage: python3 server.py
Then open http://localhost:8080
"""

import http.server
import json
import csv
import subprocess
import sys
import webbrowser
import urllib.parse
from datetime import datetime, date
from pathlib import Path

from gold_rates import (
    append_gold_article,
    delete_gold_article,
    fetch_live_gold_rates,
    load_gold_articles,
    load_gold_rates,
)

CSV_PATH        = Path(__file__).parent / "data"   / "expenses.csv"
HTML_PATH       = Path(__file__).parent / "web"    / "combined_dashboard.html"
TRACKER_PATH    = Path(__file__).parent / "expense_tracker.py"
CATEGORIES_PATH = Path(__file__).parent / "config" / "merchant_categories.json"
STOCKS_CSV_PATH = Path(__file__).parent / "data"   / "stocks.csv"
STOCKS_FETCHER  = Path(__file__).parent / "stocks_fetcher.py"
PYTHON39        = "python3.9"
PORT            = 8080

def ensure_runtime_dirs():
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    STOCKS_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

def load_categories():
    if not CATEGORIES_PATH.exists():
        return {}
    with open(CATEGORIES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}

def resolve_category(merchant, categories):
    if not merchant:
        return "Uncategorized"
    m = merchant.lower()
    for keyword, category in categories.items():
        if keyword.lower() in m:
            return category
    return "Uncategorized"

class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/income/add':
            self._handle_income_add()
        elif self.path == '/api/gold/add':
            self._handle_gold_add()
        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        if self.path.startswith('/api/income/'):
            email_id = urllib.parse.unquote(self.path[len('/api/income/'):])
            self._handle_income_delete(email_id)
        elif self.path.startswith('/api/gold/'):
            item_id = urllib.parse.unquote(self.path[len('/api/gold/'):])
            self._handle_gold_delete(item_id)
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/dashboard"):
            self._serve_file(HTML_PATH, "text/html; charset=utf-8")
        elif self.path == "/api/expenses":
            self._json(self._load_csv())
        elif self.path == "/api/refresh":
            self._handle_refresh()
        elif self.path == "/api/stocks":
            self._json(self._load_stocks_csv())
        elif self.path == "/api/stocks/refresh":
            self._handle_stocks_refresh()
        elif self.path == "/api/gold":
            self._json(self._load_gold_payload())
        elif self.path == "/api/gold/refresh":
            self._handle_gold_refresh()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_refresh(self):
        # Calculate days from last transaction date → today
        days = self._days_since_last_transaction()
        label = f"last {days} day{'s' if days != 1 else ''}"

        try:
            result = subprocess.run(
                [sys.executable, str(TRACKER_PATH), "--days", str(days)],
                capture_output=True, text=True, timeout=120,
                cwd=str(TRACKER_PATH.parent)
            )
            output = result.stdout + result.stderr

            # Count new rows saved (parse from stdout)
            new_count = 0
            for line in output.splitlines():
                if line.strip().startswith("+"):
                    new_count += 1

            self._json({
                "ok":        True,
                "days":      days,
                "label":     label,
                "new":       new_count,
                "output":    output.strip(),
            })
        except subprocess.TimeoutExpired:
            self._json({"ok": False, "error": "Timed out after 120s — Gmail may be slow."})
        except Exception as e:
            self._json({"ok": False, "error": str(e)})

    def _days_since_last_transaction(self):
        """Return number of days between the most recent transaction date and today (min 1)."""
        if not CSV_PATH.exists():
            return 1
        latest = None
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("type") == "credit" and row.get("source") == "MANUAL":
                    continue  # skip manual income entries
                d = row.get("date", "")
                if d and (latest is None or d > latest):
                    latest = d
        if not latest:
            return 1
        try:
            last_date = datetime.strptime(latest, "%Y-%m-%d").date()
            delta = (date.today() - last_date).days
            return max(delta + 1, 1)
        except ValueError:
            return 1

    def _load_csv(self):
        data = []
        if CSV_PATH.exists():
            categories = load_categories()
            with open(CSV_PATH, newline="", encoding="utf-8") as f:
                data = list(csv.DictReader(f))
            for row in data:
                row["amount"] = float(row.get("amount", 0))
                row["category"] = resolve_category(row.get("merchant", ""), categories)
        return data

    def _serve_file(self, path, content_type):
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _load_stocks_csv(self):
        if not STOCKS_CSV_PATH.exists():
            return []
        with open(STOCKS_CSV_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            r["quantity"]            = float(r.get("quantity", 0))
            r["average_price"]       = float(r.get("average_price", 0))
            r["invested_value"]      = float(r.get("invested_value", 0))
            r["t1_quantity"]         = float(r.get("t1_quantity", 0))
            r["demat_free_quantity"] = float(r.get("demat_free_quantity", 0))
            for col in ["current_price", "current_value", "pnl", "pnl_pct"]:
                r[col] = float(r[col]) if r.get(col) not in ("", None) else ""
        return rows

    def _load_gold_payload(self):
        items = []
        rates_payload = load_gold_rates() or {}
        rates = rates_payload.get("rates", {})
        for row in load_gold_articles():
            grams = float(row.get("grams", 0) or 0)
            karat = (row.get("karat") or "").upper()
            live_rate = rates.get(karat)
            current_value = round(grams * live_rate, 2) if live_rate else ""
            items.append({
                "item_id": row.get("item_id", ""),
                "name": row.get("name", ""),
                "karat": karat,
                "grams": grams,
                "notes": row.get("notes", ""),
                "created_at": row.get("created_at", ""),
                "live_rate": float(live_rate) if live_rate not in ("", None) else "",
                "current_value": current_value,
            })

        items.sort(key=lambda r: (r["karat"], -r["grams"], r["name"]))

        summary = {
            "item_count": len(items),
            "total_grams": round(sum(r["grams"] for r in items), 2),
            "total_value": round(sum(r["current_value"] for r in items if r["current_value"] != ""), 2),
            "by_karat": {},
        }
        for karat in ("18K", "22K", "24K"):
            subset = [r for r in items if r["karat"] == karat]
            summary["by_karat"][karat] = {
                "items": len(subset),
                "grams": round(sum(r["grams"] for r in subset), 2),
                "value": round(sum(r["current_value"] for r in subset if r["current_value"] != ""), 2),
            }

        return {"items": items, "rates": rates_payload, "summary": summary}

    def _handle_stocks_refresh(self):
        import re
        try:
            result = subprocess.run(
                [PYTHON39, str(STOCKS_FETCHER)],
                capture_output=True, text=True, timeout=30,
                cwd=str(STOCKS_FETCHER.parent)
            )
            output = result.stdout + result.stderr
            ok = result.returncode == 0
            holdings_count = 0
            m = re.search(r"(\d+) holdings", output)
            if m:
                holdings_count = int(m.group(1))
            self._json({"ok": ok, "holdings": holdings_count, "output": output.strip()})
        except subprocess.TimeoutExpired:
            self._json({"ok": False, "error": "Timed out — Groww API may be slow."})
        except Exception as e:
            self._json({"ok": False, "error": str(e)})

    def _handle_gold_refresh(self):
        try:
            payload = fetch_live_gold_rates()
            enriched = self._load_gold_payload()
            self._json({"ok": True, "rates": payload, "summary": enriched["summary"]})
        except Exception as e:
            self._json({"ok": False, "error": str(e)})

    def _handle_gold_add(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            name = body.get('name', '').strip()
            karat = body.get('karat', '').strip().upper()
            grams = float(body.get('grams', 0))
            notes = body.get('notes', '').strip()
            if not name:
                self._json({'ok': False, 'error': 'article name is required'})
                return
            if karat not in {'18K', '22K', '24K'}:
                self._json({'ok': False, 'error': 'karat must be 18K, 22K, or 24K'})
                return
            if grams <= 0:
                self._json({'ok': False, 'error': 'grams must be greater than 0'})
                return
            item_id = f"gold-{int(datetime.now().timestamp() * 1000)}"
            append_gold_article({
                'item_id': item_id,
                'name': name,
                'karat': karat,
                'grams': grams,
                'notes': notes,
                'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            self._json({'ok': True, 'item_id': item_id})
        except Exception as e:
            self._json({'ok': False, 'error': str(e)})

    def _handle_gold_delete(self, item_id):
        try:
            if not item_id.startswith('gold-'):
                self._json({'ok': False, 'error': 'Invalid gold item id'})
                return
            if not delete_gold_article(item_id):
                self._json({'ok': False, 'error': 'Gold article not found'})
                return
            self._json({'ok': True})
        except Exception as e:
            self._json({'ok': False, 'error': str(e)})

    def _handle_income_add(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            date_val = body.get('date', '').strip()
            amount   = float(body.get('amount', 0))
            category = body.get('category', 'Other').strip()
            note     = body.get('note', '').strip()
            if not date_val or amount <= 0:
                self._json({'ok': False, 'error': 'date and amount are required'})
                return
            email_id = f"manual-{int(datetime.now().timestamp() * 1000)}"
            record = {
                'date':        date_val,
                'amount':      amount,
                'type':        'credit',
                'source':      'MANUAL',
                'merchant':    note or category,
                'account':     category,
                'email_id':    email_id,
                'raw_snippet': f"Manual income: {category} — {note}",
            }
            fieldnames = ['date', 'amount', 'type', 'source', 'merchant', 'account', 'email_id', 'raw_snippet']
            CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
            write_header = not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0
            with open(CSV_PATH, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()
                writer.writerow({k: record.get(k, '') for k in fieldnames})
            self._json({'ok': True, 'email_id': email_id})
        except Exception as e:
            self._json({'ok': False, 'error': str(e)})

    def _handle_income_delete(self, email_id):
        try:
            if not email_id.startswith('manual-'):
                self._json({'ok': False, 'error': 'Only manual entries can be deleted'})
                return
            if not CSV_PATH.exists():
                self._json({'ok': False, 'error': 'No data file found'})
                return
            fieldnames = ['date', 'amount', 'type', 'source', 'merchant', 'account', 'email_id', 'raw_snippet']
            with open(CSV_PATH, newline='', encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
            new_rows = [r for r in rows if r.get('email_id') != email_id]
            if len(new_rows) == len(rows):
                self._json({'ok': False, 'error': 'Record not found'})
                return
            with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(new_rows)
            self._json({'ok': True})
        except Exception as e:
            self._json({'ok': False, 'error': str(e)})

    def log_message(self, fmt, *args):
        pass  # suppress request logs

if __name__ == "__main__":
    ensure_runtime_dirs()
    server = http.server.HTTPServer(("localhost", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"[✓] Finance dashboard running → {url}")
    print(f"    Press Ctrl+C to stop\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[✓] Server stopped.")
