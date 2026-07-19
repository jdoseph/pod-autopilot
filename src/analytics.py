"""Stage 8 — Weekly kill/scale loop. Pulls Shopify sales, delists losers,
queues variants of winners for the next research run.
Run weekly:  python -m src.analytics
"""
import os
from datetime import datetime, timedelta

import requests

from . import shopify_auth
from .claude_client import ask_json

KILL_AFTER_DAYS = 30   # no sales in this window -> delist
SCALE_THRESHOLD = 3    # sales this week -> make variants


def _shop() -> str:
    return os.environ["SHOPIFY_STORE"]  # e.g. mystore.myshopify.com


def _headers() -> dict:
    return shopify_auth.headers()


def fetch_products() -> list[dict]:
    r = requests.get(f"https://{_shop()}/admin/api/2025-07/products.json",
                     headers=_headers(), params={"limit": 250}, timeout=30)
    r.raise_for_status()
    return r.json()["products"]


def fetch_recent_order_lines(days: int = 35) -> dict[int, int]:
    """product_id -> units sold in window."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    r = requests.get(f"https://{_shop()}/admin/api/2025-07/orders.json",
                     headers=_headers(), timeout=30,
                     params={"status": "any", "created_at_min": since, "limit": 250})
    r.raise_for_status()
    counts: dict[int, int] = {}
    for order in r.json()["orders"]:
        for line in order["line_items"]:
            if line.get("product_id"):
                counts[line["product_id"]] = counts.get(line["product_id"], 0) + line["quantity"]
    return counts


def weekly_loop() -> None:
    products = fetch_products()
    sales = fetch_recent_order_lines()
    winners, killed = [], 0
    for p in products:
        age_days = (datetime.utcnow()
                    - datetime.fromisoformat(p["created_at"][:19])).days
        units = sales.get(p["id"], 0)
        if units >= SCALE_THRESHOLD:
            winners.append(p["title"])
        elif age_days > KILL_AFTER_DAYS and units == 0:
            requests.put(f"https://{_shop()}/admin/api/2025-07/products/{p['id']}.json",
                         headers=_headers(), timeout=30,
                         json={"product": {"id": p["id"], "status": "draft"}})
            killed += 1
    print(f"Killed {killed} stale products. Winners: {winners}")

    if winners:
        ideas = ask_json(
            "You expand winning print-on-demand designs into variant concepts.",
            f"""These listings are selling: {winners}
Return JSON: {{"variant_concepts": [str x{3 * len(winners)}]}} — same niches,
new angles (different sub-audience, colorway concept, or complementary product).""",
            tier="cheap",
        )
        # next research run picks this file up as a priority signal
        with open("runs/priority_signals.txt", "a") as f:
            f.write("\n".join(ideas["variant_concepts"]) + "\n")


if __name__ == "__main__":
    weekly_loop()
