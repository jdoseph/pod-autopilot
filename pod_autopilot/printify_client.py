"""Printify client — upload art, create product, publish to Etsy; catalog helpers.

Flow: upload_image → create_product → publish_product. Once published, Printify's
Etsy integration handles the order→print→pack→ship loop (no fulfillment code here).

Production-safe (HANDOFF.md Prompt 3):
  - retry with exponential backoff on 429 + 5xx, respecting Retry-After.
  - idempotent publish: a slug → product_id ledger (JSON) so a re-run never
    creates or publishes a duplicate; already-published slugs are skipped.
  - after publishing, mockup image URLs are downloaded into the design folder.
  - API errors surface the response body, not just the status code.
  - a dry-run path (mock=True) that logs what it WOULD do and never hits network.

MOCK / dry-run: a no-op client that LOGS what it would do and returns fake ids —
never touches the network, never spends money, never publishes.

Independently runnable:
    python -m pod_autopilot.printify_client --catalog          # list blueprints
    python -m pod_autopilot.printify_client --blueprint <id>   # providers+variants
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)

API_ROOT = "https://api.printify.com/v3"
_TIMEOUT = 30           # seconds; every external call gets one (CLAUDE.md convention)
_MAX_RETRIES = 5
_BACKOFF_BASE = 1.5     # seconds; exponential
_MAX_BACKOFF = 60.0     # cap any single sleep (incl. Retry-After)


class PrintifyError(RuntimeError):
    """Raised on a non-successful Printify API response. Carries status + body."""

    def __init__(self, message: str, *, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class PublishResult:
    product_id: str
    published: bool
    mockup_urls: list[str]
    dry_run: bool = False
    skipped: bool = False            # True when the ledger short-circuited a re-run
    saved_mockups: list[str] = field(default_factory=list)  # local file paths


class PublishLedger:
    """Tiny JSON-backed slug → product record store, for idempotent publishing.

    Record shape: {slug: {"product_id": str, "published": bool}}. Kept separate
    from the run ledger in Prompt 5 (this one is Printify-specific).
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("publish ledger unreadable, starting fresh: %s", self.path)
                self._data = {}

    def get(self, slug: str) -> dict | None:
        return self._data.get(slug)

    def record(self, slug: str, product_id: str, published: bool) -> None:
        self._data[slug] = {"product_id": product_id, "published": published}
        self._flush()

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")


class PrintifyClient:
    """Thin wrapper over the Printify REST API.

    Pass cfg.mock=True (or construct with mock=True) for the offline no-op client.
    """

    def __init__(
        self,
        cfg: config.Config | None = None,
        *,
        mock: bool | None = None,
        ledger_path: str | Path | None = None,
    ):
        self.cfg = cfg or config.load()
        # mock and dry-run are the same offline no-op behavior.
        self.mock = self.cfg.mock if mock is None else mock
        self._session = None  # lazily created requests.Session
        ledger_path = ledger_path or (self.cfg.output_dir / "publish_ledger.json")
        self.ledger = PublishLedger(ledger_path)

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
        """Request with retry/backoff on 429 + 5xx, respecting Retry-After.

        Non-retryable 4xx fail immediately. Errors surface the response body.
        """
        import requests  # lazy import (for the exception type)

        url = path if path.startswith("http") else f"{API_ROOT}{path}"
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                resp = self.session.request(method, url, timeout=_TIMEOUT, **kwargs)
            except requests.RequestException as exc:  # network error — retry
                last_exc = exc
                logger.warning("%s %s network error (attempt %d): %s", method, url, attempt + 1, exc)
                self._sleep_backoff(attempt)
                continue

            if resp.status_code < 400:
                return resp.json() if resp.content else {}

            body = resp.text[:2000]
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = PrintifyError(
                    f"{method} {url} -> {resp.status_code}: {body}",
                    status=resp.status_code, body=body,
                )
                logger.warning("%s %s -> %d (attempt %d), backing off",
                               method, url, resp.status_code, attempt + 1)
                self._sleep_backoff(attempt, retry_after=resp.headers.get("Retry-After"))
                continue

            # Other 4xx won't fix itself — fail fast with the body.
            raise PrintifyError(
                f"{method} {url} -> {resp.status_code}: {body}",
                status=resp.status_code, body=body,
            )

        # Exhausted retries.
        if isinstance(last_exc, PrintifyError):
            raise last_exc
        raise PrintifyError(f"{method} {url} failed after {_MAX_RETRIES} attempts: {last_exc}")

    @staticmethod
    def _sleep_backoff(attempt: int, retry_after: str | None = None) -> None:
        if retry_after:
            try:
                time.sleep(min(float(retry_after), _MAX_BACKOFF))
                return
            except (TypeError, ValueError):
                pass
        time.sleep(min(_BACKOFF_BASE ** attempt, _MAX_BACKOFF))

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
        mockups = self.fetch_mockup_urls(product_id)
        return PublishResult(product_id=product_id, published=True, mockup_urls=mockups)

    def fetch_mockup_urls(self, product_id: str) -> list[str]:
        """Return the product's generated mockup image URLs."""
        if self.mock:
            return [f"mock://mockup/{product_id}.png"]
        product = self._request(
            "GET", f"/shops/{self.cfg.printify_shop_id}/products/{product_id}.json"
        )
        return [img.get("src", "") for img in product.get("images", []) if img.get("src")]

    def save_mockups(self, urls: list[str], dest_dir: str | Path) -> list[str]:
        """Download mockup images into dest_dir; return local file paths.

        Skips gracefully in mock mode (nothing real to download). Individual
        download failures are logged and skipped, not fatal.
        """
        dest_dir = Path(dest_dir)
        if self.mock:
            logger.info("[MOCK] save_mockups(%d urls) -> %s (skipped)", len(urls), dest_dir)
            return []

        import requests  # lazy import

        dest_dir.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        for i, url in enumerate(urls):
            if not url:
                continue
            try:
                resp = self.session.get(url, timeout=_TIMEOUT)
                if resp.status_code != 200:
                    logger.warning("mockup %s -> %d, skipping", url, resp.status_code)
                    continue
                out = dest_dir / f"mockup_{i}.png"
                out.write_bytes(resp.content)
                saved.append(str(out))
            except requests.RequestException as exc:
                logger.warning("mockup download failed (%s): %s", url, exc)
        return saved

    def create_and_publish(
        self,
        *,
        slug: str,
        title: str,
        description: str,
        image_id: str,
        variant_ids: list[int],
        price_cents: int,
        publish: bool = True,
        mockup_dir: str | Path | None = None,
    ) -> PublishResult:
        """Idempotent create+publish keyed by `slug`.

        Consults the publish ledger first: if `slug` was already published, returns
        a skipped result without creating a duplicate. If it was created but not yet
        published, reuses the existing product_id instead of creating another.
        """
        existing = self.ledger.get(slug)
        if existing and existing.get("published"):
            logger.info("SKIP publish for %s — already published as product %s",
                        slug, existing["product_id"])
            return PublishResult(
                product_id=existing["product_id"], published=True,
                mockup_urls=[], dry_run=self.mock, skipped=True,
            )

        # Reuse a previously-created-but-unpublished product; else create one.
        if existing and existing.get("product_id"):
            product_id = existing["product_id"]
            logger.info("reusing existing product %s for %s (not yet published)",
                        product_id, slug)
        else:
            product_id = self.create_product(
                title=title, description=description, image_id=image_id,
                variant_ids=variant_ids, price_cents=price_cents,
            )
            self.ledger.record(slug, product_id, published=False)

        if not publish:
            return PublishResult(product_id=product_id, published=False,
                                 mockup_urls=[], dry_run=self.mock)

        result = self.publish_product(product_id)
        self.ledger.record(slug, product_id, published=result.published)

        if mockup_dir is not None and result.mockup_urls:
            result.saved_mockups = self.save_mockups(result.mockup_urls, mockup_dir)
        return result


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
    ap.add_argument("--dry-run", action="store_true",
                    help="offline no-op client (same as MOCK=1) — never hits the network")
    args = ap.parse_args()

    cfg = config.load()
    if args.dry_run:
        import dataclasses
        cfg = dataclasses.replace(cfg, mock=True)
    try:
        if args.catalog:
            _print_catalog(cfg)
        elif args.blueprint is not None:
            _print_blueprint(cfg, args.blueprint)
        else:
            ap.print_help()
    except PrintifyError as exc:
        # Catalog/blueprint are read-only discovery calls; print a clean error
        # (e.g. missing/invalid token) instead of a traceback.
        raise SystemExit(f"Printify API error: {exc}")
