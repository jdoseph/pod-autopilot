"""Daily pipeline with cost optimization and net-gain enforcement.
Run:  python -m src.orchestrator          (daily)
      python -m src.orchestrator --approve (publish staged, review mode)

Cost design:
- Budget governor gates every publish: monthly spend must stay under
  revenue * SPEND_RATIO + GRACE_BUDGET, so the operation is structurally
  net-positive once past the grace floor.
- Cheap-first ordering: concept scoring (1 Sonnet call) -> IP gate (Sonnet,
  fractions of a cent) BEFORE any image is rendered; listings for all
  survivors are written in ONE Haiku call; images use Flux Schnell.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from . import budget, design, ip_check, listing, marketing, printify_client, research

RUN_DIR = Path("runs") / datetime.now().strftime("%Y-%m-%d")
APPROVAL_MODE = os.environ.get("APPROVAL_MODE", "auto")
MAX_PUBLISHES_PER_DAY = int(os.environ.get("MAX_PUBLISHES_PER_DAY", "9"))
DESIGNS_PER_TYPE = int(os.environ.get("DESIGNS_PER_TYPE", "3"))


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def daily_run() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    ok, status = budget.publishing_allowed()
    log(f"Budget: {status}")
    if not ok:
        log("Skipping run — no free actions wasted while paused.")
        return

    channels = printify_client.shop_ids_by_channel()
    log(f"Connected channels: {', '.join(sorted(channels)) or 'NONE'}")
    if not channels:
        log("No sales channel connected in Printify — nothing to publish to.")
        return

    log("Stage 1: research (1 Sonnet call)...")
    concepts = research.generate_concepts(
        per_type=DESIGNS_PER_TYPE)[:MAX_PUBLISHES_PER_DAY]

    log("Stage 2-3: design prompts + IP gate (before any image spend)...")
    approved = []
    for c in concepts:
        d = design.write_design_prompt(c)
        verdict = ip_check.screen(c, d.get("text_on_design"))
        if verdict["approved"]:
            approved.append({"concept": c, "design": d, "verdict": verdict})
        else:
            log(f"  REJECTED: {c['concept'][:50]} ({verdict['reason'][:60]})")
    log(f"  {len(approved)}/{len(concepts)} approved")
    if not approved:
        return

    log("Stage 5: listings for all survivors (1 Haiku call)...")
    copies = listing.write_listings_bulk([a["concept"] for a in approved])

    for i, (a, copy) in enumerate(zip(approved, copies)):
        ok, status = budget.publishing_allowed()
        if not ok:
            log(f"Budget cap mid-run: {status}")
            break
        tag = f"c{i:02d}"
        try:
            png = str(RUN_DIR / f"{tag}.png")
            aspect = design.pick_aspect(a["concept"]["product_type"])
            design.render(a["design"]["image_prompt"], png,
                          tier=design.pick_tier(a["design"]), aspect=aspect)
            design.remove_background(png)  # art matches any garment color
            v2 = ip_check.screen_image(png, a["design"].get("text_on_design"))
            if not v2["approved"]:
                log(f"  IMAGE REJECTED [{tag}] ({v2['risk_level']}): {v2['reason'][:70]}")
                (RUN_DIR / f"{tag}.rejected.json").write_text(json.dumps(
                    {**a, "image_verdict": v2}, indent=2))  # provenance for tuning
                continue
            image_id = printify_client.upload_image(png)  # account-level: serves every shop
            products, shopify_product = {}, None
            for channel, shop in sorted(channels.items()):
                try:  # one channel failing must not sink the others
                    ch_copy = listing.for_channel(copy, channel)
                    product = printify_client.create_product(
                        shop, image_id, a["concept"]["product_type"],
                        ch_copy["title"], ch_copy["description"],
                        listing.price_for(a["concept"]["product_type"]), ch_copy["tags"],
                        image_aspect=design.ASPECT_VALUE[aspect])
                    products[channel] = product["id"]
                    if channel == "shopify":
                        shopify_product = product
                    if APPROVAL_MODE == "auto":
                        printify_client.publish(shop, product["id"])
                        if channel == "etsy":   # Etsy charges $0.20/listing; Shopify doesn't
                            budget.record_listing_fee()
                        log(f"  PUBLISHED [{channel}] {product['id']}")
                except Exception as e:
                    log(f"  ERROR [{tag}/{channel}]: {e}")
            if not products:
                continue
            (RUN_DIR / f"{tag}.json").write_text(json.dumps(
                {**a, "image_verdict": v2, "listing": copy, "products": products}, indent=2))
            if APPROVAL_MODE == "auto":
                if marketing.enabled() and shopify_product:
                    try:
                        mockup = (shopify_product.get("images") or [{}])[0].get("src", "")
                        url = (f"https://{os.environ['SHOPIFY_STORE']}"
                               f"/products/{shopify_product.get('external', {}).get('handle', '')}")
                        pin = marketing.post_pin(a["concept"], copy, mockup, url)
                        log(f"  PINNED {pin}")
                    except Exception as e:
                        log(f"  pin failed (non-fatal): {e}")
            else:
                log(f"  STAGED: {RUN_DIR}/{tag}.json")
        except Exception as e:
            log(f"  ERROR [{tag}]: {e}")

    log(f"Done. MTD spend ${budget.month_spend():.2f}, "
        f"MTD revenue ${budget.month_revenue():.2f}")


def approve_all() -> None:
    channels = printify_client.shop_ids_by_channel()
    for f in sorted(RUN_DIR.glob("c*.json")):
        if ".rejected" in f.name:   # IP-gate provenance, never publishable
            continue
        rec = json.loads(f.read_text())
        # pre-Etsy staged records carry a single Shopify "product_id"
        products = rec.get("products") or {"shopify": rec["product_id"]}
        for channel, pid in sorted(products.items()):
            shop = channels.get(channel)
            if not shop:
                log(f"SKIPPED [{channel}] {pid} — channel not connected")
                continue
            printify_client.publish(shop, pid)
            if channel == "etsy":
                budget.record_listing_fee()
            log(f"PUBLISHED [{channel}] {pid} ({rec['listing']['title'][:50]})")


if __name__ == "__main__":
    approve_all() if "--approve" in sys.argv else daily_run()
