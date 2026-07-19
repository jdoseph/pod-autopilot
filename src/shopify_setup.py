"""One-time store setup: collections, policies, shipping, and theme.
Run: python -m src.shopify_setup
Requires: SHOPIFY_STORE, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET in env.
"""
import json
import os

import requests

from . import shopify_auth

STORE = os.environ["SHOPIFY_STORE"]
COLLECTIONS = ["t-shirts", "mugs", "totes", "posters"]
POLICY_HTML = """<p>We stand behind every product. If you're not satisfied,
contact us within 30 days of receipt for a full refund or exchange.</p>"""


def api(method: str, path: str, data: dict | None = None) -> dict:
    """Call Shopify Admin API."""
    auth = shopify_auth.headers()
    if not auth:
        raise RuntimeError("Shopify auth failed — check SHOPIFY_STORE/CLIENT_ID/SECRET")
    url = f"https://{STORE}/admin/api/2025-07{path}"
    if method == "GET":
        r = requests.get(url, headers=auth, timeout=30)
    elif method == "POST":
        r = requests.post(url, headers=auth, json=data, timeout=30)
    elif method == "PUT":
        r = requests.put(url, headers=auth, json=data, timeout=30)
    else:
        raise ValueError(method)
    if not r.ok:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:200]}")
    return r.json()


def setup_collections() -> None:
    """Create collections for product categories."""
    existing = {c["title"]: c["id"] for c in api("GET", "/collections.json").get("collections", [])}
    for name in COLLECTIONS:
        title = name.replace("-", " ").title()
        if title not in existing:
            api("POST", "/collections.json", {
                "collection": {"title": title, "handle": name}})
            print(f"  ✓ collection: {title}")
        else:
            print(f"  - collection: {title} (exists)")


def setup_policies() -> None:
    """Set refund policy."""
    current = api("GET", "/shop.json").get("shop", {}).get("policy_text")
    if not current or "30 days" not in current:
        api("PUT", "/shop.json", {
            "shop": {"policy_text": POLICY_HTML}})
        print(f"  ✓ refund policy")
    else:
        print(f"  - refund policy (exists)")


def setup_shipping() -> None:
    """Set flat-rate shipping."""
    zones = api("GET", "/shipping_zones.json").get("shipping_zones", [])
    if zones:
        print(f"  - shipping zones ({len(zones)} exist)")
        return
    api("POST", "/shipping_zones.json", {
        "shipping_zone": {
            "name": "Worldwide",
            "countries": [{"code": "*"}],
            "shipping_rates": [{
                "name": "Standard",
                "price": "0.00",
                "weight_based": False
            }]
        }
    })
    print(f"  ✓ shipping: flat-rate worldwide")


def setup_theme() -> None:
    """Ensure Dawn theme is active."""
    themes = api("GET", "/themes.json").get("themes", [])
    dawn = [t for t in themes if "dawn" in t.get("name", "").lower()]
    if not dawn:
        print(f"  - theme: install Dawn manually via Shopify admin")
        return
    active = [t for t in themes if t.get("role") == "main"]
    if active and "dawn" in active[0].get("name", "").lower():
        print(f"  - theme: Dawn (active)")
        return
    api("PUT", f"/themes/{dawn[0]['id']}.json", {
        "theme": {"role": "main"}})
    print(f"  ✓ theme: Dawn")


if __name__ == "__main__":
    print("[shopify setup]")
    try:
        setup_collections()
        setup_policies()
        setup_shipping()
        setup_theme()
        print("\n✓ Store setup complete. Ready to publish products.")
    except Exception as e:
        print(f"\n✗ Setup failed: {e}")
        exit(1)
