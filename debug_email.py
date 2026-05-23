#!/usr/bin/env python3
"""Prints the raw body of the first 2 emails from each sender for debugging."""

import imaplib
import email
from email.header import decode_header

from config_loader import load_runtime_config

def load_config():
    return load_runtime_config()

def get_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                body += "[TEXT/PLAIN]\n" + part.get_payload(decode=True).decode(charset, errors="replace")
            elif ct == "text/html":
                charset = part.get_content_charset() or "utf-8"
                body += "\n[TEXT/HTML (truncated)]\n" + part.get_payload(decode=True).decode(charset, errors="replace")[:3000]
    else:
        charset = msg.get_content_charset() or "utf-8"
        body = msg.get_payload(decode=True).decode(charset, errors="replace")
    return body

cfg = load_config()
mail = imaplib.IMAP4_SSL(cfg["imap_server"], cfg["imap_port"])
mail.login(cfg["email"], cfg["app_password"])
mail.select("inbox")

for sender, label in [
    ("alerts@hdfcbank.bank.in", "HDFC"),
    ("onlinesbicard@sbicard.com", "SBI"),
]:
    print(f"\n{'='*70}")
    print(f"  {label} — sender: {sender}")
    print(f"{'='*70}")
    _, data = mail.search(None, f'FROM "{sender}"')
    ids = data[0].split()[-2:]  # last 2 emails only
    for eid in ids:
        _, msg_data = mail.fetch(eid, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        subj, enc = decode_header(msg["Subject"])[0]
        if isinstance(subj, bytes):
            subj = subj.decode(enc or "utf-8", errors="replace")
        print(f"\n--- Subject: {subj}")
        print(f"--- From:    {msg['From']}")
        print(f"--- Body:\n{get_body(msg)[:1000]}")
        print()

mail.logout()
