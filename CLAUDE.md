# CLAUDE.md — Project Context for AI Assistant

This file gives full context to Claude (or any AI assistant) about this project so future conversations can pick up without re-explaining everything.

---

## Recent Updates

### 2026-05-23 — Expense Filtering + HDFC Debit Card Purchase Support
- **Credit card bill exclusion in dashboard**: expense-page totals, charts, averages, and the main expense table now exclude rows categorized as `Credit card bill`. The rows stay in `expenses.csv` for reference, but they no longer inflate spending totals because underlying card spends are already tracked separately.
- **New HDFC debit card purchase parser**: added support for direct debit-card purchase alerts like `Rs.150.00 is debited from your HDFC Bank Debit Card ending 6167 at ENRICH FUELS on 07 May, 2026`.
- **Repair mode**: `expense_tracker.py --repair --days N` can now re-read matching emails and update already-saved CSV rows by `Message-ID` when parser logic improves or email formats drift.

### 2026-04-11 — Duplicate Fix & IMAP Reconnect
- **Deduplication fix**: `email_id` now stores the email's `Message-ID` header instead of the IMAP sequence number. IMAP sequence numbers are unstable (shift when inbox changes), causing the same email to be saved twice across multiple refreshes. `Message-ID` is globally unique and never changes.
- **IMAP reconnect**: Extracted `_connect()` helper; `fetch_and_parse()` now retries up to 3 times on `imaplib.abort` / `OSError` (connection drop). Fixes crash when fetching large date ranges (e.g. `--days 100`) where Gmail drops the connection mid-session.
- Note: existing CSV rows still have IMAP sequence numbers as `email_id` — they are already saved and won't be re-imported; only new rows use `Message-ID`.

### 2026-04-05 — Folder Restructure
- Organised into `config/`, `data/`, `web/`, `logs/`, `legacy/` subdirectories
- Updated all path references in `expense_tracker.py`, `stocks_fetcher.py`, `server.py`, `debug_email.py`
- `config.json` `csv_path` updated to `data/expenses.csv`; resolved absolutely in `load_config()` so cron and CLI work from any directory
- Cron log path updated to `logs/tracker.log`

### 2026-04-05 — Unified Dashboard
- **Merged both dashboards** into a single site at `http://localhost:8080`
- Created `combined_dashboard.html` with tab navigation: **💰 Expenses** | **📈 Portfolio**
- Updated `server.py` to handle all routes — added `/api/stocks` and `/api/stocks/refresh`; `stocks_server.py` (port 8081) is now legacy
- Portfolio tab lazy-loads on first click to avoid Chart.js canvas sizing issues
- All JS namespaced: `exp*` for expenses, `stk*` for stocks; shared `showToast()`, `INR()` helpers
- Merged `CLAUDE-STOCKS.md` into this file; deleted the separate stocks context file

---

## What This Project Does

Two integrated tools served from a single dashboard at `http://localhost:8080`:

1. **Expense Tracker** — connects to Gmail via IMAP, reads bank transaction alert emails, parses amount/merchant/date/account, stores in `expenses.csv`
2. **Stock Portfolio** — fetches Groww DEMAT holdings via the Groww Trade API, stores in `stocks.csv`

Both are accessible via tab navigation in `combined_dashboard.html`.

---

## File Structure

```
expense/
├── config/
│   ├── config.json              # Non-secret app settings
│   ├── .env                     # Gmail IMAP + Groww secrets (never commit)
│   ├── .env.example             # Safe template for local secrets
│   └── merchant_categories.json # Keyword-to-category map
├── data/
│   ├── expenses.csv             # All parsed transactions (auto-created)
│   └── stocks.csv               # Holdings snapshot (auto-created)
├── web/
│   └── combined_dashboard.html  # Unified frontend (Expenses + Portfolio tabs)
├── logs/
│   └── tracker.log              # Cron output log (auto-created)
├── legacy/
│   ├── dashboard.html           # Old expense-only dashboard
│   ├── stocks_dashboard.html    # Old stocks-only dashboard
│   └── stocks_server.py         # Old stocks server (port 8081)
├── expense_tracker.py           # IMAP fetch + email parsers + CSV writer + CLI report
├── stocks_fetcher.py            # Groww API + Yahoo Finance fetcher
├── server.py                    # Combined HTTP server (port 8080)
├── debug_email.py               # Dev tool: prints raw email body for debugging
├── README.md
└── CLAUDE.md                    # This file
```

---

## Running

```bash
# Start the combined dashboard (expenses + stocks)
python3 server.py
# Opens http://localhost:8080 automatically

# Fetch holdings manually (python3.9 required for growwapi)
python3.9 stocks_fetcher.py
```

---

## Email Sources (Expense Tracker)

| Bank | Email Sender | Source Tag in CSV |
|------|-------------|-------------------|
| HDFC Bank InstaAlerts | alerts@hdfcbank.bank.in | `HDFC-CC`, `HDFC-UPI`, `HDFC-ATM`, or `HDFC-DC` |
| HDFC Bank InstaAlerts (alt) | alerts@hdfcbank.net | `HDFC-CC`, `HDFC-UPI`, `HDFC-ATM`, or `HDFC-DC` |
| SBI Card Transaction Alert | onlinesbicard@sbicard.com | `SBI-CC` |

> HDFC sends alerts from **two senders**. Both are listed in `from_patterns` in `SOURCES`. The fetch loop iterates all patterns and merges results before processing.

---

## Exact Email Body Formats (Critical for Regex)

All emails are **HTML-only** (no `text/plain` part). The parser strips HTML tags using `re.sub(r'<[^>]+>', ' ', html)` before applying regex.

### HDFC Credit Card — Direct Swipe
```
Dear Customer, Rs.351.00 is debited from your HDFC Bank Credit Card ending 7641
towards FRESH2DAY PRIVATE LIMI on 28 Mar, 2026 at 18:48:05.
```
- Amount: `Rs\.([\d,]+\.?\d*)\s+is\s+debited`
- Account: `Credit Card ending\s+(\d{4})`
- Merchant: between `towards` and `on DD Mon, YYYY`
- Date format: `28 Mar, 2026` → `%d %b %Y`

### HDFC UPI — Savings Account
```
Dear Customer, Rs.200.00 has been debited from account 2351
to VPA 4505040101794046@axl SRI VENKATESHWARA HOT CHIPS on 29-03-26.
```
- Amount: `Rs\.([\d,]+\.?\d*)\s+has been debited`
- Account: `from account\s+(\d+)`
- Merchant: after `to [VPA] <address>`, before ` on DD-MM-YY`
- Date format: `29-03-26` → `%d-%m-%y`

### HDFC Credit Card — Via UPI
```
Dear Customer, Rs.130.00 has been debited from your HDFC Bank RuPay Credit Card XX7641
to vyapar.174180793351@hdfcbank TEA TALKIES on 29-03-26.
```
- Same parser as HDFC UPI (`parse_hdfc_upi`)
- Account: `Credit Card\s+XX(\d{4})`
- Merchant: after `to <vpa_address>`, before ` on DD-MM-YY`
- Source tag set to `HDFC-CC` when credit card detected

### HDFC Debit Card — ATM Withdrawal
```
Dear Card Holder, Thank you for using your HDFC Bank Debit Card ending 6167
for ATM withdrawal for Rs 6000.00 in CHENNAI at SHOLINGANALLUR on 27-03-2026 13:15:43.
```
- Trigger: body contains `ATM withdrawal`
- Amount: `for\s+Rs\s+([\d,]+\.?\d*)` (note: space between `Rs` and amount, not `Rs.`)
- Account: `Debit Card ending\s+(\d{4})`
- Merchant: `ATM <location>` — location extracted from `at <LOCATION> on DD-MM-YYYY`
- Date format: `27-03-2026` → `%d-%m-%Y`
- Source tag: `HDFC-ATM`

### HDFC Debit Card — Direct Purchase
```
Dear Customer, Greetings from HDFC Bank! Rs.150.00 is debited from your
HDFC Bank Debit Card ending 6167 at ENRICH FUELS on 07 May, 2026 at 18:07:31.
```
- Amount: `Rs\.\s*([\d,]+\.?\d*)\s+(?:is|has been)\s+debited`
- Account: `Debit Card ending\s+(\d{4})`
- Merchant: between `at` and `on DD Mon, YYYY`
- Date format: `07 May, 2026` → `%d %b %Y`
- Source tag: `HDFC-DC`

### SBI Credit Card
```
Dear Cardholder, This is to inform you that, Rs.1,247.00 spent on your SBI Credit Card
ending 0311 at AVENUEEMERCELIMITED on 29/03/26.
```
- Amount: `Rs\.([\d,]+\.?\d*)\s+spent`
- Account: `Credit Card ending\s+(\d{4})`
- Merchant: between `at` and `on DD/MM/YY`
- Date format: `29/03/26` → `%d/%m/%y`

---

## Key Design Decisions

- **CSV over database** — user explicitly chose CSV instead of SQLite for simplicity and portability.
- **No external libraries (expense side)** — uses Python standard library only (`imaplib`, `csv`, `json`, `re`, `http.server`).
- **Duplicate prevention** — uses IMAP `email_id` as a unique key; re-running never double-counts.
- **Server-side IMAP filter** — searches by `FROM "<sender>"` on the server to avoid downloading the full inbox.
- **HTML stripping** — emails have no `text/plain` part; body is extracted by stripping all HTML tags with regex.
- **SBI card repayment skipped** — HDFC-UPI payments to "SBI CARDS" / "SBICARD" are filtered out in `parse_hdfc_upi` (returns `None`) to avoid double-counting.
- **Expense dashboard excludes credit card bill repayments** — rows categorized as `Credit card bill` remain stored, but they are not counted in expense-page analytics or the main expense table.
- **Single server** — `server.py` on port 8080 serves both expense and stocks APIs. `stocks_server.py` (port 8081) is legacy.

---

## config.json Structure

```json
{
  "lookback_days": 1,
  "csv_path": "data/expenses.csv"
}
```

## .env Structure

```
GMAIL_EMAIL=user@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
GROWW_API_TOKEN=your_token_here
```

Parsed manually with regex in `stocks_fetcher.py` — no `python-dotenv` needed.

---

## CSV Columns

### expenses.csv
```
date, amount, type, source, merchant, account, email_id, raw_snippet
```
- `source` values: `HDFC-CC`, `HDFC-UPI`, `HDFC-ATM`, `HDFC-DC`, `SBI-CC`
- `type` values: `debit`, `credit`
- `amount` is stored as a float string (e.g., `351.0`)
- `email_id` is the IMAP sequence number (used as unique key)

### stocks.csv
```
symbol, isin, quantity, average_price, invested_value, t1_quantity, demat_free_quantity, last_updated
```
- `invested_value` = `quantity × average_price` (computed at fetch time)
- `last_updated` = timestamp of the fetch run
- Sorted by `invested_value` descending
- Full overwrite on each refresh (snapshot, not ledger)

---

## expense_tracker.py — Function Map

| Function | Purpose |
|----------|---------|
| `load_config()` | Reads config.json |
| `load_seen_ids(csv_path)` | Returns set of already-saved email_ids |
| `append_expense(csv_path, record)` | Appends one row to CSV, creates header if new |
| `load_rows(csv_path)` | Reads all existing expense rows from CSV |
| `write_rows(csv_path, rows)` | Rewrites the CSV with updated rows |
| `get_body(msg)` | Extracts plain text; strips HTML tags as fallback |
| `parse_hdfc_cc(body, email_id)` | Parses HDFC direct swipe CC emails |
| `parse_hdfc_upi(body, email_id)` | Parses HDFC UPI (savings + CC-via-UPI) emails |
| `parse_hdfc_debit_card_purchase(body, email_id)` | Parses direct HDFC debit-card purchase emails |
| `_parse_hdfc_auto(body, email_id)` | Tries CC parser first, falls back to UPI parser |
| `parse_sbi(body, email_id)` | Parses SBI Credit Card emails |
| `fetch_and_parse(config, days, repair_existing=False)` | Main IMAP loop — fetches, parses, saves, and can repair existing rows |
| `print_report(config, month)` | Prints terminal report from CSV |

## stocks_fetcher.py — Function Map

| Function | Purpose |
|----------|---------|
| `load_token()` | Reads `GROWW_API_TOKEN` from `.env` |
| `fetch_holdings(token)` | Calls Groww API, returns list of holding dicts |
| `save_csv(holdings)` | Writes/overwrites `stocks.csv`, prints terminal summary |

---

## server.py — API Routes

| Route | Description |
|-------|-------------|
| `GET /` | Serves `combined_dashboard.html` |
| `GET /api/expenses` | Reads `expenses.csv`, injects `category` from `merchant_categories.json`, returns JSON |
| `GET /api/refresh` | Calculates days since last transaction, runs `expense_tracker.py --days N`, returns `{ ok, days, label, new, output }` |
| `GET /api/stocks` | Reads `stocks.csv`, casts numeric fields to float, returns JSON |
| `GET /api/stocks/refresh` | Runs `python3.9 stocks_fetcher.py`, returns `{ ok, holdings, output }` |

---

## combined_dashboard.html

- Tab bar: **💰 Expenses** | **📈 Portfolio**
- Expenses tab loads on page open; Portfolio tab lazy-loads on first click
- All JS namespaced: `exp*` prefix for expenses, `stk*` prefix for stocks
- Shared: `showToast()`, `INR()`, `NUM()` helpers; one `#toast` div

### Expenses Tab
- Month selector filters all charts + table simultaneously
- Charts: Daily spending (stacked bar), Source breakdown (donut), Top 10 merchants (horizontal bar), Monthly trend (line), Spending by Category (pie)
- Table: Searchable by merchant, filterable by source and category, paginated 20/page
- Rows categorized as `Credit card bill` are excluded from expense totals, charts, averages, and the main expense table to avoid double-counting tracked card spending
- Source colors: HDFC-CC = `#3b82f6`, HDFC-UPI = `#10b981`, HDFC-ATM = `#a855f7`, HDFC-DC = `#ec4899`, SBI-CC = `#f59e0b`

### Portfolio Tab
- Hero banner: Total Current Value, Total Invested, Overall P&L, Overall Return %
- Cards: Holdings count, Best/Worst performer, Avg position size
- Charts: Portfolio Allocation donut (top 14 + Others), Top 10 by Current Value (bar)
- Table: Searchable by symbol/ISIN; columns: Symbol, Qty, Avg Price, Invested, CMP, Current Value, P&L, Return %, ISIN

---

## Groww API Details

| Field | Value |
|-------|-------|
| Endpoint | `GET https://api.groww.in/v1/holdings/user` |
| SDK | `growwapi==1.5.0` (requires Python 3.9+) |
| Auth | Bearer token passed to `GrowwAPI(token)` |

**Important:** The API does NOT return live `current_price` or P&L. Only `average_price` (purchase price) is available.

---

## Python Version Note

- `growwapi` requires **Python 3.9+**
- System Python is 3.8.10 (Ubuntu 20.04)
- Python 3.9.5 installed via apt; pip bootstrapped via `get-pip.py`
- **Always use `python3.9` to run `stocks_fetcher.py`**
- `server.py` uses system `python3` and calls `python3.9` via subprocess for the fetcher

---

## Cron Job

```
0 9 * * * cd /home/siddharth/Documents/expense && python3 expense_tracker.py >> logs/tracker.log 2>&1
```

Runs daily at 9 AM, fetches previous day's emails (`lookback_days: 1`).

---

## merchant_categories.json

- Keyword-to-category map; matching is **case-insensitive substring**
- Keys starting with `_` are ignored (used for comments)
- Edit freely — no server restart needed, just hard-refresh (`Ctrl+Shift+R`)

---

## Known Issues / Gotchas

- **IMAP email_id** — now uses `Message-ID` header (stable). Existing CSV rows have old IMAP sequence numbers but won't be re-imported.
- **HDFC uses two sender addresses** — `alerts@hdfcbank.bank.in` and `alerts@hdfcbank.net`. If transactions go missing, check if HDFC added a third sender.
- **No live P&L** — Groww holdings API only returns `average_price`. Live P&L would require a separate market data endpoint per symbol.
- **Chart.js loaded from CDN** — dashboard requires internet access on first load.

---

## How to Debug Parser Issues

```bash
python3 debug_email.py
```

Prints the stripped plain-text body of the last 2 emails from each sender. Use output to update regexes in `parse_hdfc_cc`, `parse_hdfc_upi`, or `parse_sbi`.
