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
# image_y / panel_frac: blueprint 507's "front" area is a tall WRAP running
# under the bag — art must sit in the top half or it prints past the fold
# and looks cut off on the physical front face.
BLUEPRINTS = {"t-shirt": {"blueprint_id": 145, "preferred_provider": None},   # Unisex Softstyle T-Shirt
              "mug": {"blueprint_id": 68, "preferred_provider": None},         # Mug 11oz
              "tote": {"blueprint_id": 507, "preferred_provider": None,        # Canvas Tote Bag
                       "image_y": 0.25, "panel_frac": 0.5},
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


def shops() -> list[dict]:
    r = requests.get(f"{BASE}/shops.json", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def shop_ids_by_channel() -> dict[str, int]:
    """Connected sales channels -> shop id, e.g. {"shopify": 1, "etsy": 2}.
    Printify doesn't document the exact sales_channel strings, so match by
    substring; unknown channels pass through under their raw name."""
    out = {}
    for s in shops():
        ch = (s.get("sales_channel") or "").lower()
        key = ("etsy" if "etsy" in ch else
               "shopify" if "shopify" in ch else ch)
        if key and key != "disconnected":
            out.setdefault(key, s["id"])
    return out


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


def contain_scale(image_aspect: float, area_w: int | None, area_h: int | None,
                  max_scale: float = 0.9) -> float:
    """Largest fraction of the print-area WIDTH the image can occupy while
    the whole image still fits inside the area (Printify crops overflow —
    this is why portrait art was getting cut off on square tote areas).
    image_aspect = width/height of the artwork; 5% breathing room."""
    if not (area_w and area_h):
        return max_scale
    fit = image_aspect * area_h / area_w * 0.95
    return round(min(max_scale, fit), 4)


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
                   title: str, description: str, price_cents: int,
                   tags: list[str], image_aspect: float = 0.75) -> dict:
    product_type = product_type.lower().strip()  # research sometimes capitalizes
    bp = BLUEPRINTS.get(product_type, BLUEPRINTS["t-shirt"])
    provider = resolve_provider(bp["blueprint_id"], bp.get("preferred_provider"))
    all_variants = _get_json(
        f"{BASE}/catalog/blueprints/{bp['blueprint_id']}/print_providers/{provider}/variants.json"
    )["variants"][:MAX_VARIANTS]
    panel = bp.get("panel_frac", 1.0)
    image_y = bp.get("image_y", 0.5)
    fits = [contain_scale(image_aspect, p.get("width"),
                          int((p.get("height") or 0) * panel) or None)
            for v in all_variants
            for p in v.get("placeholders", []) if p.get("position") == "front"]
    scale = min(fits) if fits else 0.9
    payload = {
        "title": title, "description": description, "tags": tags[:13],
        "blueprint_id": bp["blueprint_id"], "print_provider_id": provider,
        "variants": [{"id": v["id"], "price": price_cents, "is_enabled": True}
                     for v in all_variants],
        "print_areas": [{
            "variant_ids": [v["id"] for v in all_variants],
            "placeholders": [{"position": "front", "images": [
                {"id": image_id, "x": 0.5, "y": image_y, "scale": scale,
                 "angle": 0}]}],
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
