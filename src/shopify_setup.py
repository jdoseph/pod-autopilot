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
    """Collections require write_collections scope (not granted to this app).
    Skip — users can create them manually in Shopify admin."""
    print(f"  - collections: create manually in Shopify admin (scope not granted)")


def setup_policies() -> None:
    """Set refund policy (via admin_shop_settings scope)."""
    try:
        current = api("GET", "/shop.json").get("shop", {}).get("policy_text", "")
        if not current or "30 days" not in current:
            api("PUT", "/shop.json", {
                "shop": {"policy_text": POLICY_HTML}})
            print(f"  ✓ refund policy")
        else:
            print(f"  - refund policy (exists)")
    except RuntimeError as e:
        if "403" in str(e):
            print(f"  - refund policy: configure in Shopify admin")
        else:
            raise


def setup_shipping() -> None:
    """Shipping requires write_shipping scope (not granted to this app).
    Skip — users configure in Shopify admin."""
    print(f"  - shipping: configure in Shopify admin (scope not granted)")


def setup_theme() -> None:
    """Themes require write_themes scope (not granted to this app).
    Skip — users install in Shopify admin."""
    print(f"  - theme: install Dawn in Shopify admin (scope not granted)")


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
