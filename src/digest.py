"""Weekly digest — the one-way information channel. Emails you a summary
(revenue, spend, net, published, killed, flagged support emails) so the
system reports out without ever needing input back.
Run weekly after analytics:  python -m src.digest
"""
import json
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

from . import budget

FLAGGED = Path("runs/flagged_emails.jsonl")


def run() -> None:
    to = os.environ.get("OWNER_EMAIL")
    if not to:
        return
    spend, revenue = budget.month_spend(), budget.month_revenue()
    flagged = [json.loads(l) for l in FLAGGED.open()] if FLAGGED.exists() else []
    ok, status = budget.publishing_allowed()
    body = (f"POD Autopilot — weekly report\n\n"
            f"Month to date:  revenue ${revenue:.2f} | spend ${spend:.2f} "
            f"| net ${revenue - spend:.2f}\n"
            f"Governor: {status}\n\n"
            f"Flagged support emails needing a human ({len(flagged)}):\n" +
            ("\n".join(f"  - {f['ts'][:10]} {f['from']}: {f['subject']} "
                       f"[{f['category']}]" for f in flagged[-20:]) or "  none") +
            "\n\nNo action required unless flagged emails exist or the "
            "governor is paused.\n")
    msg = MIMEText(body)
    msg["Subject"] = f"POD Autopilot weekly: net ${revenue - spend:.2f} MTD"
    msg["From"], msg["To"] = os.environ["SUPPORT_EMAIL"], to
    with smtplib.SMTP_SSL(os.environ["SUPPORT_SMTP_HOST"]) as s:
        s.login(os.environ["SUPPORT_EMAIL"], os.environ["SUPPORT_EMAIL_PASSWORD"])
        s.send_message(msg)
    if FLAGGED.exists():
        FLAGGED.rename(FLAGGED.with_suffix(".archived.jsonl"))


if __name__ == "__main__":
    run()
