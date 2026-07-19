"""Stage 4 — Printify: upload art, create product, publish to the linked store.
Fulfillment itself is native Printify: with auto-fulfill ON in your Printify
account settings, incoming store orders are produced and shipped to the
customer with zero code and zero touch."""
import base64
import os

import requests

BASE = "https://api.printify.com/v1"


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['PRINTIFY_API_KEY']}"}

# Popular defaults — list real IDs with GET /catalog/blueprints.json
# Providers are preferences, not guarantees: availability shifts, so the
# actual provider is resolved from the live catalog at create time.
BLUEPRINTS = {"t-shirt": {"blueprint_id": 6, "preferred_provider": 99},   # Unisex Gildan 5000
              "mug": {"blueprint_id": 68, "preferred_provider": 28},
              "tote": {"blueprint_id": 75, "preferred_provider": 75},      # Canvas tote
              "poster": {"blueprint_id": 207, "preferred_provider": 11}}
MAX_VARIANTS = 100  # Printify rejects products with more enabled variants


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
    return preferred if preferred in ids else ids[0]


def create_product(shop: int, image_id: str, product_type: str,
                   title: str, description: str, price_cents: int, tags: list[str]) -> dict:
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
    return r.json()


def publish(shop: int, product_id: str) -> None:
    """Push the product live to the connected Shopify/Etsy store."""
    r = requests.post(f"{BASE}/shops/{shop}/products/{product_id}/publish.json",
                      headers=_headers(), timeout=60,
                      json={k: True for k in
                            ("title", "description", "images", "variants", "tags")})
    r.raise_for_status()
