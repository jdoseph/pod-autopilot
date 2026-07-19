"""Budget governor. Logs every real cost, compares month-to-date spend against
month-to-date store revenue, and throttles publishing to keep the operation
net-positive each month (after a small grace budget for the cold-start period).

Rule the orchestrator enforces before publishing anything:
    allowed spend this month = revenue_mtd * SPEND_RATIO + GRACE_BUDGET
If projected spend (incl. the next listing fee) exceeds that, publishing pauses
until revenue catches up. Research/design/IP calls are pennies and continue.
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests

from . import shopify_auth

LEDGER = Path("runs/ledger.jsonl")
GRACE_BUDGET = float(os.environ.get("GRACE_BUDGET_USD", "30"))   # allowed monthly loss floor
SPEND_RATIO = float(os.environ.get("SPEND_RATIO", "0.25"))       # spend <= 25% of revenue
MONTHLY_LLM_BUDGET = float(os.environ.get("MONTHLY_LLM_BUDGET_USD", "25"))
ETSY_LISTING_FEE = 0.20
IMAGE_COST = {"schnell": 0.003, "pro": 0.04, "text": 0.03, "bgremove": 0.0005}

# $/MTok — verified July 2026; batch API halves these if you migrate to batches
PRICES = {
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00, "cached": 0.30},
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00, "cached": 0.10},
}


def _log(kind: str, usd: float, meta: dict | None = None) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps({"ts": datetime.utcnow().isoformat(),
                            "kind": kind, "usd": round(usd, 6),
                            **(meta or {})}) + "\n")


def record_llm(model: str, in_tok: int, out_tok: int, cached_tok: int = 0) -> None:
    p = PRICES.get(model, PRICES["claude-sonnet-4-6"])
    fresh_in = max(in_tok - cached_tok, 0)
    usd = (fresh_in * p["in"] + cached_tok * p["cached"] + out_tok * p["out"]) / 1e6
    _log("llm", usd, {"model": model, "in": in_tok, "out": out_tok, "cached": cached_tok})


def record_image(tier: str = "schnell") -> None:
    _log("image", IMAGE_COST.get(tier, 0.04), {"tier": tier})


def record_listing_fee() -> None:
    _log("listing_fee", ETSY_LISTING_FEE)


def _month_start() -> str:
    return datetime.utcnow().replace(day=1, hour=0, minute=0, second=0,
                                     microsecond=0).isoformat()


def month_spend() -> float:
    if not LEDGER.exists():
        return 0.0
    start = _month_start()
    return sum(json.loads(line)["usd"] for line in LEDGER.open()
               if json.loads(line)["ts"] >= start)


def llm_spend_mtd() -> float:
    if not LEDGER.exists():
        return 0.0
    start = _month_start()
    total = 0.0
    for line in LEDGER.open():
        e = json.loads(line)
        if e["kind"] == "llm" and e["ts"] >= start:
            total += e["usd"]
    return total


def check_llm_budget() -> None:
    """Circuit breaker checked before every Claude call. Unlike the publish
    governor (which only pauses listings), this hard-stops all LLM spend for
    the month — the backstop against any runaway loop, whatever its source."""
    spent = llm_spend_mtd()
    if spent >= MONTHLY_LLM_BUDGET:
        raise RuntimeError(
            f"LLM budget breaker tripped: ${spent:.2f} spent this month >= "
            f"${MONTHLY_LLM_BUDGET:.2f} cap (raise MONTHLY_LLM_BUDGET_USD to override)")


def month_revenue() -> float:
    """Month-to-date gross revenue from Shopify orders. A failed lookup counts
    as $0 revenue — the governor then errs toward pausing, never overspending."""
    shop = os.environ.get("SHOPIFY_STORE")
    if not shop:
        return 0.0
    try:
        auth = shopify_auth.headers()
        if not auth:
            return 0.0
        r = requests.get(f"https://{shop}/admin/api/2025-07/orders.json",
                         headers=auth, timeout=30,
                         params={"status": "any", "created_at_min": _month_start(),
                                 "financial_status": "paid", "limit": 250})
        r.raise_for_status()
        return sum(float(o["total_price"]) for o in r.json()["orders"])
    except Exception as e:
        print(f"[budget] revenue lookup failed ({e}); treating as $0")
        return 0.0


def publishing_allowed() -> tuple[bool, str]:
    spend, revenue = month_spend(), month_revenue()
    cap = revenue * SPEND_RATIO + GRACE_BUDGET
    if spend + ETSY_LISTING_FEE > cap:
        return False, (f"paused: MTD spend ${spend:.2f} vs cap ${cap:.2f} "
                       f"(revenue ${revenue:.2f}) — resumes when revenue catches up")
    return True, f"ok: MTD spend ${spend:.2f} / cap ${cap:.2f} (revenue ${revenue:.2f})"
