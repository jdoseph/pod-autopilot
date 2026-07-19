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
BLUEPRINTS = {"t-shirt": {"blueprint_id": 6, "print_provider_id": 99},   # Unisex Gildan 5000
              "mug": {"blueprint_id": 68, "print_provider_id": 28}}


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


def create_product(shop: int, image_id: str, product_type: str,
                   title: str, description: str, price_cents: int, tags: list[str]) -> dict:
    bp = BLUEPRINTS.get(product_type, BLUEPRINTS["t-shirt"])
    variants_r = requests.get(
        f"{BASE}/catalog/blueprints/{bp['blueprint_id']}/print_providers/{bp['print_provider_id']}/variants.json",
        headers=_headers(), timeout=30)
    variants_r.raise_for_status()
    all_variants = variants_r.json()["variants"]
    payload = {
        "title": title, "description": description, "tags": tags[:13],
        "blueprint_id": bp["blueprint_id"], "print_provider_id": bp["print_provider_id"],
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
    r.raise_for_status()
    return r.json()


def publish(shop: int, product_id: str) -> None:
    """Push the product live to the connected Shopify/Etsy store."""
    r = requests.post(f"{BASE}/shops/{shop}/products/{product_id}/publish.json",
                      headers=_headers(), timeout=60,
                      json={k: True for k in
                            ("title", "description", "images", "variants", "tags")})
    r.raise_for_status()
