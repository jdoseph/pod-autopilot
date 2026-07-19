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
    """Policies require Settings access (not available via API).
    Skip — users configure in Shopify admin."""
    print(f"  - refund policy: set in Settings → Policies")


def setup_shipping() -> None:
    """Shipping requires write_shipping scope (not granted to this app).
    Skip — users configure in Shopify admin."""
    print(f"  - shipping: configure in Shopify admin (scope not granted)")


def setup_theme() -> None:
    """Themes require write_themes scope (not granted to this app).
    Skip — users install in Shopify admin."""
    print(f"  - theme: install Dawn in Shopify admin (scope not granted)")


if __name__ == "__main__":
    print("[shopify setup]\n")
    try:
        # Verify auth works
        shop = api("GET", "/shop.json").get("shop", {})
        print(f"✓ Authenticated to {shop.get('name', 'your store')}\n")
        print("Manual setup steps (5 min):")
        setup_collections()
        setup_policies()
        setup_shipping()
        setup_theme()
        print("\nThen your store is ready. First product publish will be via")
        print("GitHub Actions (run: gh workflow run pod-autopilot --approve).")
    except Exception as e:
        print(f"✗ Auth failed: {e}\nCheck SHOPIFY_STORE/CLIENT_ID/SECRET.")
        exit(1)
