#!/usr/bin/env python3
"""
Stock Portfolio Dashboard Server
Usage: python3 stocks_server.py
Then open http://localhost:8081
"""

import http.server
import json
import csv
import subprocess
import sys
import webbrowser
from pathlib import Path

CSV_PATH    = Path(__file__).parent / "stocks.csv"
HTML_PATH   = Path(__file__).parent / "stocks_dashboard.html"
FETCHER     = Path(__file__).parent / "stocks_fetcher.py"
PYTHON39    = "python3.9"
PORT        = 8081


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/dashboard"):
            self._serve_file(HTML_PATH, "text/html; charset=utf-8")
        elif self.path == "/api/stocks":
            self._json(self._load_csv())
        elif self.path == "/api/refresh":
            self._handle_refresh()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_refresh(self):
        try:
            result = subprocess.run(
                [PYTHON39, str(FETCHER)],
                capture_output=True, text=True, timeout=30,
                cwd=str(FETCHER.parent)
            )
            output = result.stdout + result.stderr
            ok = result.returncode == 0
            holdings_count = 0
            for line in output.splitlines():
                if "holdings found" in line:
                    import re
                    m = re.search(r"(\d+) holdings", line)
                    if m:
                        holdings_count = int(m.group(1))
            self._json({"ok": ok, "holdings": holdings_count, "output": output.strip()})
        except subprocess.TimeoutExpired:
            self._json({"ok": False, "error": "Timed out — Groww API may be slow."})
        except Exception as e:
            self._json({"ok": False, "error": str(e)})

    def _load_csv(self):
        if not CSV_PATH.exists():
            return []
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
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

    def _serve_file(self, path, content_type):
        if not path.exists():
            self.send_response(404)
            self.end_headers()
            return
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

    def log_message(self, fmt, *args):
        pass  # suppress request logs


if __name__ == "__main__":
    server = http.server.HTTPServer(("localhost", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"[✓] Stock dashboard running → {url}")
    print(f"    Press Ctrl+C to stop\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[✓] Server stopped.")
