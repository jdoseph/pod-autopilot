"""Shopify Admin API auth. Two supported modes:
- SHOPIFY_ACCESS_TOKEN set (a permanent shpat_ Admin API token): used as-is.
- SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET set: exchanged per run via the
  OAuth client-credentials grant (own-store apps only). Those tokens expire
  after ~24h, which is fine — every scheduled run mints a fresh one.
"""
import os
import time

import requests

_cached = {"token": None, "exp": 0.0}


def access_token() -> str | None:
    static = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    if static:
        return static
    cid = os.environ.get("SHOPIFY_CLIENT_ID")
    secret = os.environ.get("SHOPIFY_CLIENT_SECRET")
    shop = os.environ.get("SHOPIFY_STORE")
    if not (cid and secret and shop):
        return None
    if _cached["token"] and time.time() < _cached["exp"]:
        return _cached["token"]
    r = requests.post(f"https://{shop}/admin/oauth/access_token", timeout=30,
                      data={"grant_type": "client_credentials",
                            "client_id": cid, "client_secret": secret})
    r.raise_for_status()
    j = r.json()
    _cached["token"] = j["access_token"]
    _cached["exp"] = time.time() + j.get("expires_in", 86400) - 300
    return _cached["token"]


def headers() -> dict:
    """Auth headers for Admin API calls; {} when no credentials configured."""
    tok = access_token()
    return {"X-Shopify-Access-Token": tok} if tok else {}
