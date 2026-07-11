"""Printify client — upload art, create product, publish to Etsy; catalog helpers.

Flow: upload_image → create_product → publish_product. Once published, Printify's
Etsy integration handles the order→print→pack→ship loop (no fulfillment code here).

STATUS: done, UNHARDENED (per CLAUDE.md). HANDOFF.md Prompt 3 adds retry/backoff on
429/5xx (respecting Retry-After), idempotent publish (slug → product_id map, no
dupes), mockup-URL saving, and full response-body error surfacing.

MOCK mode: a no-op client that LOGS what it would do and returns fake ids — never
touches the network, never spends money, never publishes.

Independently runnable:
    python -m pod_autopilot.printify_client --catalog          # list blueprints
    python -m pod_autopilot.printify_client --blueprint <id>   # providers+variants
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)

API_ROOT = "https://api.printify.com/v3"
_TIMEOUT = 30  # seconds; every external call gets one (CLAUDE.md convention)


class PrintifyError(RuntimeError):
    """Raised on a non-successful Printify API response."""


@dataclass
class PublishResult:
    product_id: str
    published: bool
    mockup_urls: list[str]
    dry_run: bool = False


class PrintifyClient:
    """Thin wrapper over the Printify REST API.

    Pass cfg.mock=True (or construct with mock=True) for the offline no-op client.
    """

    def __init__(self, cfg: config.Config | None = None, *, mock: bool | None = None):
        self.cfg = cfg or config.load()
        self.mock = self.cfg.mock if mock is None else mock
        self._session = None  # lazily created requests.Session

    # -- HTTP plumbing -----------------------------------------------------

    @property
    def session(self):
        if self._session is None:
            import requests  # lazy import

            s = requests.Session()
            s.headers.update(
                {
                    "Authorization": f"Bearer {self.cfg.printify_api_token}",
                    "User-Agent": "pod-autopilot/0.1",
                    "Content-Type": "application/json",
                }
            )
            self._session = s
        return self._session

    def _request(self, method: str, path: str, **kwargs):
        """Single request. NOTE: no retry/backoff yet — Prompt 3 adds it."""
        url = path if path.startswith("http") else f"{API_ROOT}{path}"
        resp = self.session.request(method, url, timeout=_TIMEOUT, **kwargs)
        if resp.status_code >= 400:
            # Surface the body, not just the status (Prompt 3 formalizes this).
            body = resp.text[:2000]
            raise PrintifyError(f"{method} {url} -> {resp.status_code}: {body}")
        if resp.content:
            return resp.json()
        return {}

    # -- Catalog helpers ---------------------------------------------------

    def list_blueprints(self) -> list[dict]:
        data = self._request("GET", "/catalog/blueprints.json")
        return data if isinstance(data, list) else data.get("data", [])

    def blueprint_providers(self, blueprint_id: int) -> list[dict]:
        data = self._request("GET", f"/catalog/blueprints/{blueprint_id}/print_providers.json")
        return data if isinstance(data, list) else data.get("data", [])

    def blueprint_variants(self, blueprint_id: int, provider_id: int) -> list[dict]:
        data = self._request(
            "GET",
            f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json",
        )
        return data.get("variants", data if isinstance(data, list) else [])

    # -- Core flow ---------------------------------------------------------

    def upload_image(self, png_path: str | Path) -> str:
        """Upload a PNG, return its Printify image id."""
        png_path = Path(png_path)
        if self.mock:
            logger.info("[MOCK] upload_image(%s) -> fake-image-id", png_path.name)
            return f"mock-image-{png_path.stem}"

        encoded = base64.b64encode(png_path.read_bytes()).decode("ascii")
        data = self._request(
            "POST",
            "/uploads/images.json",
            json={"file_name": png_path.name, "contents": encoded},
        )
        return str(data["id"])

    def create_product(self, *, title: str, description: str, image_id: str, variant_ids: list[int], price_cents: int) -> str:
        """Create a product on the shop, return product_id."""
        if self.mock:
            logger.info("[MOCK] create_product(title=%r, variants=%d) -> fake-product-id",
                        title, len(variant_ids))
            return f"mock-product-{abs(hash(title)) % 10_000_000}"

        blueprint_id = self.cfg.printify_blueprint_id
        provider_id = self.cfg.printify_print_provider_id
        payload = {
            "title": title,
            "description": description,
            "blueprint_id": blueprint_id,
            "print_provider_id": provider_id,
            "variants": [
                {"id": vid, "price": price_cents, "is_enabled": True} for vid in variant_ids
            ],
            "print_areas": [
                {
                    "variant_ids": variant_ids,
                    "placeholders": [
                        {"position": "front", "images": [
                            {"id": image_id, "x": 0.5, "y": 0.5, "scale": 1.0, "angle": 0}
                        ]}
                    ],
                }
            ],
        }
        data = self._request("POST", f"/shops/{self.cfg.printify_shop_id}/products.json", json=payload)
        return str(data["id"])

    def publish_product(self, product_id: str) -> PublishResult:
        """Publish a product to the connected Etsy shop.

        NOTE: not idempotent yet — Prompt 3 adds the slug→product_id ledger so
        re-runs don't create/publish duplicates.
        """
        if self.mock:
            logger.info("[MOCK] publish_product(%s) -> would publish to Etsy", product_id)
            return PublishResult(product_id=product_id, published=False,
                                 mockup_urls=[f"mock://mockup/{product_id}.png"], dry_run=True)

        self._request(
            "POST",
            f"/shops/{self.cfg.printify_shop_id}/products/{product_id}/publish.json",
            json={"title": True, "description": True, "images": True, "variants": True,
                  "tags": True, "key_features": True, "shipping_template": True},
        )
        # Fetch mockups (Prompt 3 saves these into the design folder).
        product = self._request("GET", f"/shops/{self.cfg.printify_shop_id}/products/{product_id}.json")
        mockups = [img.get("src", "") for img in product.get("images", []) if img.get("src")]
        return PublishResult(product_id=product_id, published=True, mockup_urls=mockups)


def _print_catalog(cfg: config.Config) -> None:
    client = PrintifyClient(cfg)
    for bp in client.list_blueprints():
        print(f"{bp.get('id'):>6}  {bp.get('title', '')}")


def _print_blueprint(cfg: config.Config, blueprint_id: int) -> None:
    client = PrintifyClient(cfg)
    print(f"# Providers for blueprint {blueprint_id}")
    for prov in client.blueprint_providers(blueprint_id):
        pid = prov.get("id")
        print(f"provider {pid}: {prov.get('title', '')}")
        for v in client.blueprint_variants(blueprint_id, pid)[:10]:
            print(f"    variant {v.get('id')}: {v.get('title', '')}")


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Printify catalog explorer.")
    ap.add_argument("--catalog", action="store_true", help="list blueprint ids")
    ap.add_argument("--blueprint", type=int, help="list providers + variants for a blueprint id")
    args = ap.parse_args()

    cfg = config.load()
    if args.catalog:
        _print_catalog(cfg)
    elif args.blueprint is not None:
        _print_blueprint(cfg, args.blueprint)
    else:
        ap.print_help()
