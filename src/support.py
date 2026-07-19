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
import re
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from .claude_client import ask_json

FLAGGED = Path("runs/flagged_emails.jsonl")
# Hard per-run ceiling on emails sent to Claude. A huge unseen backlog (spam
# wave, misconfigured inbox, "mark all unread") must never turn into a mass
# LLM spend again — July 19 2026: 11k personal emails, $13.61 in one run.
MAX_PER_RUN = int(os.environ.get("SUPPORT_MAX_EMAILS", "25"))
BULK_FROM = re.compile(r"no-?reply|do-?not-?reply|notifications?@|mailer@|newsletter",
                       re.IGNORECASE)
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


def _is_bulk(msg) -> bool:
    """Newsletter/notification/no-reply mail — never a customer inquiry."""
    if msg.get("List-Unsubscribe") or msg.get("List-Id"):
        return True
    if (msg.get("Precedence") or "").lower() in ("bulk", "list", "junk"):
        return True
    if (msg.get("Auto-Submitted") or "no").lower() != "no":
        return True
    return bool(BULK_FROM.search(msg.get("From") or ""))


def run() -> None:
    if not os.environ.get("SUPPORT_IMAP_HOST"):
        return
    m = _conn()
    m.select("INBOX")
    _, ids = m.search(None, "UNSEEN")
    handled = skipped = 0
    for eid in ids[0].split():
        # Peek headers first (doesn't set \Seen): bulk mail is marked read and
        # skipped without an LLM call or a reply.
        _, data = m.fetch(eid, "(BODY.PEEK[HEADER])")
        if _is_bulk(email.message_from_bytes(data[0][1])):
            m.store(eid, "+FLAGS", "\\Seen")
            skipped += 1
            continue
        if handled >= MAX_PER_RUN:
            print(f"[support] cap {MAX_PER_RUN} reached; leaving the rest "
                  f"unseen for the next run")
            break
        _, data = m.fetch(eid, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        handled += 1
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
    print(f"[support] {handled} emails handled, {skipped} bulk skipped")
    m.logout()


if __name__ == "__main__":
    run()
