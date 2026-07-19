"""Stage 4 — Printify: upload art, create product, publish to the linked store.
Fulfillment itself is native Printify: with auto-fulfill ON in your Printify
account settings, incoming store orders are produced and shipped to the
customer with zero code and zero touch."""
import base64
import math
import os

import requests

BASE = "https://api.printify.com/v1"


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['PRINTIFY_API_KEY']}"}

# Popular defaults — list real IDs with GET /catalog/blueprints.json
# Providers are preferences, not guarantees: availability shifts, so the
# actual provider is resolved from the live catalog at create time.
BLUEPRINTS = {"t-shirt": {"blueprint_id": 145, "preferred_provider": None},   # Unisex Softstyle T-Shirt
              "mug": {"blueprint_id": 68, "preferred_provider": None},         # Mug 11oz
              "tote": {"blueprint_id": 507, "preferred_provider": None},       # Canvas Tote Bag
              "poster": {"blueprint_id": 97, "preferred_provider": None}}
MAX_VARIANTS = 100  # Printify rejects products with more enabled variants

# Pricing: guarantee MIN_MARGIN of retail over production cost + estimated
# shipping (the store offers free shipping, so the price must absorb it).
SHIPPING_EST = {"t-shirt": 475, "mug": 550, "tote": 450, "poster": 550}  # cents, US economy
MIN_MARGIN = 0.40
PRICE_FLOOR = 1295


def price_from_cost(cost_cents: int, product_type: str) -> int:
    """Per-variant retail (cents): landed cost / (1 - margin), x.95 ending."""
    landed = cost_cents + SHIPPING_EST.get(product_type, 500)
    price = math.ceil(landed / (1 - MIN_MARGIN) / 100) * 100 - 5
    return max(price, PRICE_FLOOR)


def shop_id() -> int:
    r = requests.get(f"{BASE}/shops.json", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()[0]["id"]


def upload_image(png_path: str) -> str:
    with open(png_path, "rb") as f:
        contents = base64.b64encode(f.read()).decode()
    r = requests.post(f"{BASE}/uploads/images.json", headers=_headers(), timeout=120,
                      json={"file_name": os.path.basename(png_path), "contents": contents})
    r.raise_for_status()
    return r.json()["id"]


def _get_json(url: str) -> dict:
    r = requests.get(url, headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def resolve_provider(blueprint_id: int, preferred: int | None = None) -> int:
    """Pick a print provider that actually serves this blueprint right now."""
    providers = _get_json(f"{BASE}/catalog/blueprints/{blueprint_id}/print_providers.json")
    ids = [p["id"] for p in providers]
    if not ids:
        raise RuntimeError(f"no print providers offer blueprint {blueprint_id}")
    # If no preference, pick the first available (Printify orders them by quality)
    if not preferred:
        return ids[0]
    # If preference was set, use it if available, else fall back to first
    return preferred if preferred in ids else ids[0]


def create_product(shop: int, image_id: str, product_type: str,
                   title: str, description: str, price_cents: int, tags: list[str]) -> dict:
    product_type = product_type.lower().strip()  # research sometimes capitalizes
    bp = BLUEPRINTS.get(product_type, BLUEPRINTS["t-shirt"])
    provider = resolve_provider(bp["blueprint_id"], bp.get("preferred_provider"))
    all_variants = _get_json(
        f"{BASE}/catalog/blueprints/{bp['blueprint_id']}/print_providers/{provider}/variants.json"
    )["variants"][:MAX_VARIANTS]
    payload = {
        "title": title, "description": description, "tags": tags[:13],
        "blueprint_id": bp["blueprint_id"], "print_provider_id": provider,
        "variants": [{"id": v["id"], "price": price_cents, "is_enabled": True}
                     for v in all_variants],
        "print_areas": [{
            "variant_ids": [v["id"] for v in all_variants],
            "placeholders": [{"position": "front", "images": [
                {"id": image_id, "x": 0.5, "y": 0.5, "scale": 0.9, "angle": 0}]}],
        }],
    }
    r = requests.post(f"{BASE}/shops/{shop}/products.json", headers=_headers(),
                      json=payload, timeout=60)
    if not r.ok:  # surface Printify's reason, not just the status code
        raise RuntimeError(f"product create {r.status_code}: {r.text[:300]}")
    product = r.json()

    # Reprice per variant from the REAL production costs Printify returns —
    # sizes differ by dollars, and a flat price can go underwater on 2XL+.
    costed = [v for v in product.get("variants", []) if v.get("cost")]
    if costed:
        upd = requests.put(
            f"{BASE}/shops/{shop}/products/{product['id']}.json",
            headers=_headers(), timeout=60,
            json={"variants": [
                {"id": v["id"], "price": price_from_cost(v["cost"], product_type),
                 "is_enabled": v.get("is_enabled", True)} for v in costed]})
        if not upd.ok:  # a mispriced product must not reach the store
            raise RuntimeError(f"reprice {upd.status_code}: {upd.text[:200]}")
        product = upd.json()
    return product


def publish(shop: int, product_id: str) -> None:
    """Push the product live to the connected Shopify/Etsy store."""
    r = requests.post(f"{BASE}/shops/{shop}/products/{product_id}/publish.json",
                      headers=_headers(), timeout=60,
                      json={k: True for k in
                            ("title", "description", "images", "variants", "tags")})
    r.raise_for_status()
