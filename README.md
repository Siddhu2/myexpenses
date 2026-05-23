# Finance Dashboard

A personal finance tracker for an Indian user (INR) that automatically captures bank transaction emails and Groww stock holdings, visualized through a single local web dashboard.

---

## What It Does

| Feature | Description |
|---------|-------------|
| **Expense Tracking** | Reads HDFC & SBI bank alert emails via Gmail IMAP, parses transactions, stores in CSV |
| **Stock Portfolio** | Fetches Groww DEMAT holdings + live prices via Yahoo Finance, stores in CSV |
| **Unified Dashboard** | Single web UI at `http://localhost:8080` with tab navigation for both |

---

## Folder Structure

```
expense/
├── config/
│   ├── config.json              # Non-secret app settings
│   ├── .env                     # Gmail IMAP + Groww secrets (ignored)
│   ├── .env.example             # Safe template for local secrets
│   └── merchant_categories.json # Merchant-to-category keyword map
│
├── data/
│   ├── expenses.csv             # All parsed transactions (auto-created)
│   └── stocks.csv               # Latest holdings snapshot (auto-created)
│
├── web/
│   └── combined_dashboard.html  # Unified frontend (Expenses + Portfolio tabs)
│
├── logs/
│   └── tracker.log              # Cron run output (auto-created)
│
├── legacy/                      # Standalone files from before the merge
│   ├── dashboard.html           # Old expense-only dashboard
│   ├── stocks_dashboard.html    # Old stocks-only dashboard
│   └── stocks_server.py         # Old stocks server (port 8081)
│
├── expense_tracker.py           # IMAP email fetcher + parser + CLI report
├── stocks_fetcher.py            # Groww API + Yahoo Finance fetcher
├── server.py                    # Combined HTTP server (port 8080)
├── debug_email.py               # Dev tool: prints raw email body for regex debugging
├── README.md
└── CLAUDE.md                    # AI assistant context file
```

---

## Setup

### 1. Expense Tracker — Gmail IMAP

**Enable Gmail IMAP:**
Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP → Save.

**Create a Gmail App Password:**
1. [myaccount.google.com](https://myaccount.google.com) → Security → 2-Step Verification (must be ON)
2. Scroll to the bottom → App passwords
3. Create one named `expense-tracker`, copy the 16-character code

**Configure `config/.env`:**
```env
GMAIL_EMAIL=your_gmail@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
```

**Configure `config/config.json`:**
```json
{
  "lookback_days": 1,
  "csv_path": "data/expenses.csv"
}
```

### 2. Stock Portfolio — Groww API

**Get your Groww API token** from the Groww Trade API portal.

Add the Groww token to the same `config/.env` file:
```
GROWW_API_TOKEN=your_token_here
```

**Python version note:** `growwapi` requires Python 3.9+. If your system Python is older:
```bash
sudo apt-get install python3.9
curl -sS https://bootstrap.pypa.io/get-pip.py | python3.9
python3.9 -m pip install growwapi yfinance
```

### 3. Requirements

Expense tracker: **Python standard library only** (`imaplib`, `csv`, `json`, `http.server`) — no pip install needed.

Stocks fetcher: requires `growwapi` and `yfinance`:
```bash
python3.9 -m pip install growwapi yfinance
```

---

## Usage

### Start the Dashboard

```bash
python3 server.py
```

Opens `http://localhost:8080` automatically. Press `Ctrl+C` to stop.

### Fetch Expenses (CLI)

```bash
# Fetch yesterday's emails (default — used by cron)
python3 expense_tracker.py

# Backfill last N days
python3 expense_tracker.py --days 30

# Print today's report from CSV (no email fetch)
python3 expense_tracker.py --report

# Print a monthly summary
python3 expense_tracker.py --month 2026-03
```

### Fetch Stock Holdings (CLI)

```bash
python3.9 stocks_fetcher.py
```

---

## Dashboard

Navigate between tabs using the bar at the top of the page.

### 💰 Expenses Tab

| Section | Description |
|---------|-------------|
| **Summary cards** | Total spent, transaction count, daily average, top merchant |
| **Daily Spending** | Stacked bar chart by source (HDFC-CC / HDFC-UPI / HDFC-ATM / HDFC-DC / SBI-CC) |
| **By Source** | Donut chart showing spend split across accounts |
| **Top 10 Merchants** | Horizontal bar sorted by total spend |
| **Monthly Trend** | Line chart across all months |
| **Spending by Category** | Pie chart for the selected month |
| **Transaction Table** | Searchable, filterable by source and category, paginated 20/page |

Use the **month selector** to filter all charts and the table simultaneously.

**Refresh button** — fetches new transactions directly from Gmail without leaving the browser. Automatically calculates the gap from the last recorded transaction date to today (inclusive) and fetches exactly that range.

### 📈 Portfolio Tab

| Section | Description |
|---------|-------------|
| **Hero banner** | Total Current Value, Total Invested, Overall P&L, Overall Return % |
| **Summary cards** | Holdings count, Best/Worst performer, Avg position size |
| **Portfolio Allocation** | Donut chart (top 14 holdings + Others bucket) |
| **Top 10 by Current Value** | Horizontal bar chart |
| **Holdings Table** | Searchable by symbol/ISIN; shows Qty, Avg Price, Invested, CMP, Current Value, P&L, Return % |

**Refresh button** — fetches latest holdings from Groww and live prices from Yahoo Finance.

---

## Automate with Cron

Run the expense tracker automatically every morning at 9 AM:

```bash
crontab -e
```

Add:
```
0 9 * * * cd /home/siddharth/Documents/expense && python3 expense_tracker.py >> logs/tracker.log 2>&1
```

---

## Supported Email Formats

| Bank | Type | Sender |
|------|------|--------|
| HDFC | Credit Card (direct swipe) | alerts@hdfcbank.bank.in |
| HDFC | UPI (savings / CC via UPI) | alerts@hdfcbank.bank.in |
| HDFC | ATM withdrawal | alerts@hdfcbank.bank.in |
| HDFC | All types (alternate sender) | alerts@hdfcbank.net |
| SBI  | Credit Card | onlinesbicard@sbicard.com |

---

## CSV Formats

### data/expenses.csv

| Column | Description |
|--------|-------------|
| `date` | Transaction date (YYYY-MM-DD) |
| `amount` | Amount in INR |
| `type` | `debit` or `credit` |
| `source` | `HDFC-CC`, `HDFC-UPI`, `HDFC-ATM`, `HDFC-DC`, or `SBI-CC` |
| `merchant` | Merchant / payee name |
| `account` | Last 4 digits of card or account number |
| `email_id` | IMAP email ID (used to prevent duplicates) |
| `raw_snippet` | First 300 characters of the email body |

### data/stocks.csv

| Column | Description |
|--------|-------------|
| `symbol` | NSE trading symbol |
| `isin` | ISIN code |
| `quantity` | Shares held |
| `average_price` | Purchase price (from Groww) |
| `invested_value` | `quantity × average_price` |
| `current_price` | Live price from Yahoo Finance |
| `current_value` | `quantity × current_price` |
| `pnl` | `current_value − invested_value` |
| `pnl_pct` | Return percentage |
| `t1_quantity` | T+1 settlement quantity |
| `demat_free_quantity` | Free (unpledged) quantity |
| `last_updated` | Timestamp of the fetch run |

---

## Merchant Categories

Edit `config/merchant_categories.json` to categorize merchants. Matching is **case-insensitive substring** — one keyword covers all variants.

```json
{
  "FRESH2DAY":      "Vegetables & Fruits",
  "ZOMATO":         "Food Delivery",
  "N SANJIV KUMAR": "House Rent"
}
```

No server restart needed — categories are applied on every request. Hard-refresh the browser (`Ctrl+Shift+R`) to see changes.

---

## Debugging Parser Issues

If transactions stop parsing after a bank changes their email template:

```bash
python3 debug_email.py
```

Prints the raw stripped text of the last 2 emails from each sender. Use the output to update regexes in `expense_tracker.py`.

---

## Security Notes

- `config/.env` contains Gmail IMAP credentials and the Groww API token — **do not commit it**.
- `data/` contains personal financial records and is ignored by `.gitignore`.
- All data is stored locally; nothing is sent to any external service.
