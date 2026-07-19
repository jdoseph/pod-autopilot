"""Stage 10 — Support agent. Polls the store inbox over IMAP, auto-answers
routine questions (tracking, sizing, product info) with an automated-assistant
disclosure, and quarantines anything sensitive (refunds, disputes, legal,
anger) into a flag file that surfaces in the weekly digest — never answered
automatically, never lost.
Run hourly or piggyback on the daily cron:  python -m src.support
"""
import email
import imaplib
import json
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from .claude_client import ask_json

FLAGGED = Path("runs/flagged_emails.jsonl")
DISCLOSURE = ("\n\n—\nThis reply was drafted by our automated shop assistant. "
              "A human reviews flagged messages weekly.")

SYSTEM = """You are a shop support assistant for a print-on-demand store.
You may ONLY fully answer: order tracking questions (tell them tracking is
emailed by our production partner on shipment, typically 2-5 business days
after order), sizing/product questions (answer from the listing), and general
shop questions. You MUST escalate (answer=null) anything involving: refunds,
returns, chargebacks, damaged items, legal threats, anger/frustration,
account issues, or anything you are unsure about. Never promise delivery
dates, refunds, or replacements."""


def _conn():
    m = imaplib.IMAP4_SSL(os.environ["SUPPORT_IMAP_HOST"])
    m.login(os.environ["SUPPORT_EMAIL"], os.environ["SUPPORT_EMAIL_PASSWORD"])
    return m


def _send(to_addr: str, subject: str, body: str) -> None:
    msg = MIMEText(body + DISCLOSURE)
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ["SUPPORT_EMAIL"], to_addr
    with smtplib.SMTP_SSL(os.environ["SUPPORT_SMTP_HOST"]) as s:
        s.login(os.environ["SUPPORT_EMAIL"], os.environ["SUPPORT_EMAIL_PASSWORD"])
        s.send_message(msg)


def run() -> None:
    if not os.environ.get("SUPPORT_IMAP_HOST"):
        return
    m = _conn()
    m.select("INBOX")
    _, ids = m.search(None, "UNSEEN")
    for eid in ids[0].split():
        _, data = m.fetch(eid, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode(errors="ignore")[:3000]
                break
        verdict = ask_json(
            SYSTEM,
            f"""Customer email — Subject: {msg.get('Subject', '')}\n{body}\n
Return JSON: {{"category": str, "answer": str or null}}""",
            tier="cheap")
        if verdict.get("answer"):
            _send(msg.get("From"), "Re: " + (msg.get("Subject") or "your message"),
                  verdict["answer"])
        else:
            FLAGGED.parent.mkdir(parents=True, exist_ok=True)
            with FLAGGED.open("a") as f:
                f.write(json.dumps({"ts": datetime.utcnow().isoformat(),
                                    "from": msg.get("From"),
                                    "subject": msg.get("Subject"),
                                    "category": verdict.get("category")}) + "\n")
    m.logout()


if __name__ == "__main__":
    run()
