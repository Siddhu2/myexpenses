#!/usr/bin/env python3
"""
Expense Tracker - Parses HDFC InstaAlert & SBI Card transaction emails via Gmail IMAP
Stores results in a CSV file.

Usage:
  python3 expense_tracker.py             # fetch today's emails, append to CSV, print report
  python3 expense_tracker.py --days 7    # fetch last 7 days
  python3 expense_tracker.py --report    # print today's report from CSV
  python3 expense_tracker.py --month 2026-03   # print monthly summary
"""

import imaplib
import email
import re
import csv
import argparse
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path

from config_loader import load_runtime_config

# ─── Config ──────────────────────────────────────────────────────────────────

def load_config():
    return load_runtime_config()

# ─── CSV Storage ──────────────────────────────────────────────────────────────

FIELDNAMES = ["date", "amount", "type", "source", "merchant", "account", "email_id", "raw_snippet"]

def load_seen_ids(csv_path):
    """Return a set of already-saved email_ids to prevent duplicates."""
    seen = set()
    p = Path(csv_path)
    if p.exists():
        with open(p, newline="") as f:
            for row in csv.DictReader(f):
                seen.add(row["email_id"])
    return seen

def append_expense(csv_path, record):
    """Append one record to the CSV; create with header if new."""
    p = Path(csv_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_header = not p.exists() or p.stat().st_size == 0
    with open(p, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow({k: record.get(k, "") for k in FIELDNAMES})


def load_rows(csv_path):
    p = Path(csv_path)
    if not p.exists():
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def write_rows(csv_path, rows):
    p = Path(csv_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})

# ─── Email Helpers ────────────────────────────────────────────────────────────

def decode_subject(msg):
    subject, encoding = decode_header(msg["Subject"])[0]
    if isinstance(subject, bytes):
        subject = subject.decode(encoding or "utf-8", errors="replace")
    return subject

def get_body(msg):
    """Extract plain text from email. Falls back to stripping HTML tags if no text/plain part."""
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            charset = part.get_content_charset() or "utf-8"
            if ct == "text/plain":
                plain += part.get_payload(decode=True).decode(charset, errors="replace")
            elif ct == "text/html" and not plain:
                html = part.get_payload(decode=True).decode(charset, errors="replace")
    else:
        charset = msg.get_content_charset() or "utf-8"
        raw = msg.get_payload(decode=True).decode(charset, errors="replace")
        if msg.get_content_type() == "text/html":
            html = raw
        else:
            plain = raw

    if plain:
        return plain
    # Drop style/script blocks so CSS does not pollute parser matches or raw snippets.
    html = re.sub(r"<style\b[^>]*>.*?</style>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    # Strip HTML tags and collapse whitespace
    text = re.sub(r'<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', text).strip()

def clean_amount(raw):
    return float(raw.replace(",", ""))


def _extract_match(body, patterns, flags=re.IGNORECASE):
    for pattern in patterns:
        m = re.search(pattern, body, flags)
        if m:
            return m
    return None

# ─── Parsers ──────────────────────────────────────────────────────────────────

def parse_hdfc_cc(body, email_id):
    """
    HDFC Credit Card direct swipe:
      Rs.351.00 is debited from your HDFC Bank Credit Card ending 7641
      towards FRESH2DAY PRIVATE LIMI on 28 Mar, 2026 at 18:48:05.
    """
    record = {"source": "HDFC-CC", "email_id": email_id, "raw_snippet": body[:300].replace("\n", " ")}

    m = re.search(r"Rs\.\s*([\d,]+\.?\d*)\s+(?:is|has been)\s+debited", body, re.IGNORECASE)
    if not m:
        return None
    if re.search(r"\bVPA\b", body, re.IGNORECASE):
        return None
    if re.search(r"Debit Card ending\s+\d{4}", body, re.IGNORECASE):
        return None
    record["amount"] = clean_amount(m.group(1))
    record["type"]   = "debit"

    card = re.search(r"Credit Card ending\s+(\d{4})", body, re.IGNORECASE)
    record["account"] = card.group(1) if card else ""

    merchant_m = _extract_match(body, [
        r"towards\s+(.+?)\s+on\s+\d{1,2}\s+\w{3},?\s+\d{4}",
        r"towards\s+(.+?)\s+on\s+\d{2}-\d{2}-\d{2,4}",
    ])
    if not merchant_m:
        return None
    record["merchant"] = merchant_m.group(1).strip()[:100]

    date_m = _extract_match(body, [
        r"\bon\s+(\d{1,2}\s+\w{3},?\s+\d{4})\b",
        r"\bon\s+(\d{2}-\d{2}-\d{2,4})\b",
    ])
    record["date"] = _parse_date(
        date_m.group(1).replace(",", "").strip(),
        ["%d %b %Y", "%d-%m-%y", "%d-%m-%Y"],
    ) if date_m else _today()

    return record


def parse_hdfc_upi(body, email_id):
    """
    HDFC UPI (savings or CC-via-UPI):
      Rs.200.00 has been debited from account 2351 to VPA 4505040101794046@axl SRI VENKATESHWARA HOT CHIPS on 29-03-26.
      Rs.130.00 has been debited from your HDFC Bank RuPay Credit Card XX7641 to vyapar.174180793351@hdfcbank TEA TALKIES on 29-03-26.
    """
    record = {"source": "HDFC-UPI", "email_id": email_id, "raw_snippet": body[:300].replace("\n", " ")}

    m = re.search(r"Rs\.\s*([\d,]+\.?\d*)\s+(?:has been|is)\s+debited", body, re.IGNORECASE)
    if not m:
        return None
    if not (
        re.search(r"\bVPA\b", body, re.IGNORECASE) or
        re.search(r"\bUPI\b", body, re.IGNORECASE)
    ):
        return None
    record["amount"] = clean_amount(m.group(1))
    record["type"]   = "debit"

    # Savings account number
    acc = _extract_match(body, [
        r"from account\s+(\d+)",
        r"from your account ending\s+(\d+)",
    ])
    if acc:
        record["account"] = acc.group(1)
        record["source"]  = "HDFC-UPI"
    else:
        # Credit card via UPI — extract last 4 digits
        card = _extract_match(body, [
            r"Credit Card\s+XX(\d{4})",
            r"Credit Card ending\s+(\d{4})",
        ])
        record["account"] = card.group(1) if card else ""
        record["source"]  = "HDFC-CC"

    merchant_m = _extract_match(body, [
        r"\btowards\s+VPA\s+\S+\s+\((.+?)\)\s+on\s+\d{2}-\d{2}-\d{2}",
        r"\bcredited to\s+VPA\s+\S+\s+\((.+?)\)\s+on\s+\d{1,2}\s+\w{3},?\s+\d{4}",
        r"\bto\s+(?:VPA\s+)?\S+\s+(.+?)\s+on\s+\d{2}-\d{2}-\d{2}",
    ])
    if merchant_m:
        record["merchant"] = merchant_m.group(1).strip()[:100]
    else:
        record["merchant"] = ""

    # Skip credit card bill repayments to avoid double-counting
    SKIP_MERCHANTS = ["sbi card", "sbicard", "sbi cards"]
    if any(s in record["merchant"].lower() for s in SKIP_MERCHANTS):
        return None

    date_m = _extract_match(body, [
        r"\bon\s+(\d{2}-\d{2}-\d{2,4})\b",
        r"\bon\s+(\d{1,2}\s+\w{3},?\s+\d{4})\b",
    ])
    record["date"] = _parse_date(
        date_m.group(1).replace(",", "").strip(),
        ["%d-%m-%y", "%d-%m-%Y", "%d %b %Y"],
    ) if date_m else _today()

    return record


def parse_hdfc_atm(body, email_id):
    """
    HDFC Debit Card ATM withdrawal:
      Thank you for using your HDFC Bank Debit Card ending 6167 for ATM withdrawal
      for Rs 6000.00 in CHENNAI at SHOLINGANALLUR on 27-03-2026 13:15:43.
    """
    record = {"source": "HDFC-ATM", "email_id": email_id, "raw_snippet": body[:300].replace("\n", " ")}

    m = re.search(r"ATM withdrawal", body, re.IGNORECASE)
    if not m:
        return None

    amt = re.search(r"for\s+Rs\s+([\d,]+\.?\d*)", body, re.IGNORECASE)
    if not amt:
        return None
    record["amount"] = clean_amount(amt.group(1))
    record["type"]   = "debit"

    card = re.search(r"Debit Card ending\s+(\d{4})", body, re.IGNORECASE)
    record["account"] = card.group(1) if card else ""

    # Location: "at SHOLINGANALLUR on DD-MM-YYYY"
    loc = re.search(r"\bat\s+(\S+)\s+on\s+\d{2}-\d{2}-\d{4}", body, re.IGNORECASE)
    record["merchant"] = ("ATM " + loc.group(1).strip())[:100] if loc else "ATM WITHDRAWAL"

    date_m = re.search(r"\bon\s+(\d{2}-\d{2}-\d{4})", body, re.IGNORECASE)
    record["date"] = _parse_date(date_m.group(1), ["%d-%m-%Y"]) if date_m else _today()

    return record


def parse_hdfc_debit_card_purchase(body, email_id):
    """
    HDFC Debit Card purchase:
      Dear Customer, Greetings from HDFC Bank! Rs.150.00 is debited from your
      HDFC Bank Debit Card ending 6167 at ENRICH FUELS on 07 May, 2026 at 18:07:31.
    """
    record = {"source": "HDFC-DC", "email_id": email_id, "raw_snippet": body[:300].replace("\n", " ")}

    if not re.search(r"Debit Card ending\s+\d{4}", body, re.IGNORECASE):
        return None
    if re.search(r"ATM withdrawal", body, re.IGNORECASE):
        return None

    amt = re.search(r"Rs\.\s*([\d,]+\.?\d*)\s+(?:is|has been)\s+debited", body, re.IGNORECASE)
    if not amt:
        return None
    record["amount"] = clean_amount(amt.group(1))
    record["type"] = "debit"

    card = re.search(r"Debit Card ending\s+(\d{4})", body, re.IGNORECASE)
    record["account"] = card.group(1) if card else ""

    merchant_m = _extract_match(body, [
        r"\bat\s+(.+?)\s+on\s+\d{1,2}\s+\w{3},?\s+\d{4}",
        r"\bat\s+(.+?)\s+on\s+\d{2}-\d{2}-\d{2,4}",
    ])
    record["merchant"] = merchant_m.group(1).strip()[:100] if merchant_m else ""

    date_m = _extract_match(body, [
        r"\bon\s+(\d{1,2}\s+\w{3},?\s+\d{4})\b",
        r"\bon\s+(\d{2}-\d{2}-\d{2,4})\b",
    ])
    record["date"] = _parse_date(
        date_m.group(1).replace(",", "").strip(),
        ["%d %b %Y", "%d-%m-%y", "%d-%m-%Y"],
    ) if date_m else _today()

    return record


def parse_sbi(body, email_id):
    """
    SBI Credit Card format:
      Rs.1,247.00 spent on your SBI Credit Card ending 0311
      at AVENUEEMERCELIMITED on 29/03/26.
    """
    record = {"source": "SBI-CC", "email_id": email_id, "raw_snippet": body[:300].replace("\n", " ")}

    # Amount
    m = re.search(r"Rs\.([\d,]+\.?\d*)\s+spent", body, re.IGNORECASE)
    if not m:
        return None
    record["amount"] = clean_amount(m.group(1))
    record["type"]   = "debit"

    # Card last 4
    card = re.search(r"Credit Card ending\s+(\d{4})", body, re.IGNORECASE)
    record["account"] = card.group(1) if card else ""

    # Merchant — between "at " and " on "
    merchant_m = re.search(r"\bat\s+(\S+)\s+on\s+\d", body, re.IGNORECASE)
    record["merchant"] = merchant_m.group(1).strip()[:100] if merchant_m else ""

    # Date — "29/03/26"
    date_m = re.search(r"\bon\s+(\d{2}/\d{2}/\d{2,4})\b", body, re.IGNORECASE)
    record["date"] = _parse_date(date_m.group(1), ["%d/%m/%y", "%d/%m/%Y"]) if date_m else _today()

    return record

# ─── Date helpers ─────────────────────────────────────────────────────────────

def _parse_date(raw, formats):
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return _today()

def _today():
    return datetime.today().strftime("%Y-%m-%d")

# ─── Source definitions ───────────────────────────────────────────────────────

def _parse_hdfc_auto(body, email_id):
    """Try CC parser first, then UPI, then ATM withdrawal."""
    return (
        parse_hdfc_cc(body, email_id)
        or parse_hdfc_upi(body, email_id)
        or parse_hdfc_atm(body, email_id)
        or parse_hdfc_debit_card_purchase(body, email_id)
    )

SOURCES = [
    {
        "name": "HDFC",
        "from_patterns":    ["alerts@hdfcbank.bank.in", "alerts@hdfcbank.net"],
        "subject_patterns": ["instaalert", "hdfc bank alert"],
        "parser": _parse_hdfc_auto,
    },
    {
        "name": "SBI",
        "from_patterns":    ["onlinesbicard@sbicard.com"],
        "subject_patterns": ["transaction alert", "sbi card"],
        "parser": parse_sbi,
    },
]

def matches_source(msg, source):
    sender  = (msg.get("From") or "").lower()
    subject = decode_subject(msg).lower()
    return (any(p in sender  for p in source["from_patterns"]) or
            any(p in subject for p in source["subject_patterns"]))

# ─── Fetch loop ───────────────────────────────────────────────────────────────

def _connect(config):
    """Open a fresh IMAP connection and return the mail object."""
    mail = imaplib.IMAP4_SSL(config["imap_server"], config["imap_port"])
    mail.login(config["email"], config["app_password"])
    mail.select("inbox")
    return mail


def _should_refresh_row(existing, record):
    return (
        not existing.get("merchant") or
        not existing.get("account") or
        existing.get("raw_snippet", "").startswith("HDFC BANK --> @media")
    )


def fetch_and_parse(config, lookback_days=None, repair_existing=False):
    days  = lookback_days or config.get("lookback_days", 1)
    since = (datetime.today() - timedelta(days=days)).strftime("%d-%b-%Y")
    csv_path = config["csv_path"]

    rows      = load_rows(csv_path)
    index_by_id = {row["email_id"]: i for i, row in enumerate(rows)}
    seen      = set(index_by_id)
    new_count = 0
    repaired_count = 0
    changed = False

    print(f"[*] Connecting to Gmail IMAP...")
    mail = _connect(config)

    for source in SOURCES:
        print(f"[*] Searching {source['name']} emails since {since}...")
        # Search each from_pattern separately and merge results
        all_ids = set()
        for sender_email in source["from_patterns"]:
            _, data = mail.search(None, f'(FROM "{sender_email}" SINCE "{since}")')
            all_ids.update(data[0].split())
        ids = sorted(all_ids, key=lambda x: int(x))
        print(f"    {len(ids)} emails found")

        matched = 0
        for eid in ids:
            for attempt in range(3):
                try:
                    _, msg_data = mail.fetch(eid, "(RFC822)")
                    break
                except (imaplib.IMAP4.abort, OSError):
                    if attempt == 2:
                        raise
                    print(f"    [!] Connection dropped, reconnecting...")
                    mail = _connect(config)

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            body       = get_body(msg)
            message_id = msg.get("Message-ID", eid.decode()).strip()
            record = source["parser"](body, message_id)

            if record and record["email_id"] not in seen:
                rows.append({k: record.get(k, "") for k in FIELDNAMES})
                index_by_id[record["email_id"]] = len(rows) - 1
                seen.add(record["email_id"])
                new_count += 1
                matched   += 1
                changed   = True
                print(f"    + [{record['date']}] {record['type'].upper():6s} "
                      f"Rs.{record['amount']:>10.2f}  {record['merchant'] or '—'}  ({source['name']})")
            elif record and repair_existing:
                existing = rows[index_by_id[record["email_id"]]]
                if _should_refresh_row(existing, record):
                    rows[index_by_id[record["email_id"]]] = {k: record.get(k, "") for k in FIELDNAMES}
                    repaired_count += 1
                    changed = True
                    print(f"    ~ Repaired {record['email_id']} -> {record['merchant'] or '—'}")

        print(f"    Saved {matched} new {source['name']} transactions")

    mail.logout()
    if changed:
        write_rows(csv_path, rows)
    print(f"\n[✓] Done. {new_count} new expenses, {repaired_count} repaired → {csv_path}")

# ─── Report ───────────────────────────────────────────────────────────────────

def print_report(config, month=None):
    csv_path = Path(config["csv_path"])
    if not csv_path.exists():
        print("No expenses file found yet.")
        return

    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    if month:
        rows  = [r for r in rows if r["date"].startswith(month)]
        label = month
    else:
        today = _today()
        rows  = [r for r in rows if r["date"] == today]
        label = f"Today ({today})"

    if not rows:
        print(f"No expenses found for {label}.")
        return

    rows.sort(key=lambda r: (r["date"], float(r["amount"])), reverse=True)

    total_debit  = sum(float(r["amount"]) for r in rows if r["type"] == "debit")
    total_credit = sum(float(r["amount"]) for r in rows if r["type"] == "credit")

    print(f"\n{'─'*70}")
    print(f"  Expense Report — {label}")
    print(f"{'─'*70}")
    print(f"  {'Date':<12} {'Src':<6} {'Type':<7} {'Amount':>10}  Merchant")
    print(f"{'─'*70}")
    for r in rows:
        print(f"  {r['date']:<12} {r['source']:<6} {r['type']:<7} "
              f"Rs.{float(r['amount']):>8.2f}  {r['merchant'] or '—'}")
    print(f"{'─'*70}")
    print(f"  {'Total Debits':.<34} Rs.{total_debit:>10.2f}")
    print(f"  {'Total Credits':.<34} Rs.{total_credit:>10.2f}")
    print(f"  {'Net Spend':.<34} Rs.{total_debit - total_credit:>10.2f}")
    print(f"{'─'*70}\n")

# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gmail Expense Tracker (CSV)")
    parser.add_argument("--days",   type=int, default=None, help="Fetch emails from last N days")
    parser.add_argument("--repair", action="store_true", help="Repair existing rows by re-reading matching emails")
    parser.add_argument("--report", action="store_true",    help="Print today's report from CSV")
    parser.add_argument("--month",  type=str, default=None, help="Monthly report, format: YYYY-MM")
    args = parser.parse_args()

    cfg = load_config()

    if args.report:
        print_report(cfg)
    elif args.month:
        print_report(cfg, month=args.month)
    else:
        fetch_and_parse(cfg, lookback_days=args.days, repair_existing=args.repair)
        print_report(cfg)
