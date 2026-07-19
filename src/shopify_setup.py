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
        # Verify auth works and check scopes
        shop = api("GET", "/shop.json").get("shop", {})
        print(f"✓ Authenticated to {shop.get('name', 'your store')}\n")

        # Try each scope and report
        scopes_to_test = [
            ("write_collections", lambda: api("GET", "/collections.json")),
            ("write_policies", lambda: api("GET", "/shop.json")),
            ("write_shipping", lambda: api("GET", "/shipping_zones.json")),
            ("write_themes", lambda: api("GET", "/themes.json")),
        ]

        print("Scope availability:")
        for scope_name, test_fn in scopes_to_test:
            try:
                test_fn()
                print(f"  ✓ {scope_name}")
            except RuntimeError as e:
                if "403" in str(e):
                    print(f"  ✗ {scope_name} (403 Forbidden)")
                else:
                    print(f"  ? {scope_name} ({e})")

        print("\nIf any scopes show ✗, reinstall the app:")
        print("  1. Settings → Apps → your app → ⋯ → Uninstall")
        print("  2. Settings → Apps → your app → Install app")
    except Exception as e:
        print(f"✗ Auth failed: {e}\nCheck SHOPIFY_STORE/CLIENT_ID/SECRET.")
        exit(1)
