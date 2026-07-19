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
MAX_PUBLISHES_PER_DAY = int(os.environ.get("MAX_PUBLISHES_PER_DAY", "5"))


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def daily_run() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    ok, status = budget.publishing_allowed()
    log(f"Budget: {status}")
    if not ok:
        log("Skipping run — no free actions wasted while paused.")
        return

    shop = printify_client.shop_id()

    log("Stage 1: research (1 Sonnet call)...")
    concepts = research.generate_concepts(n=10)[:MAX_PUBLISHES_PER_DAY]

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
            design.render(a["design"]["image_prompt"], png, tier="schnell")
            v2 = ip_check.screen_image(png)  # gate 2: the rendered pixels
            if not v2["approved"]:
                log(f"  IMAGE REJECTED [{tag}] ({v2['risk_level']}): {v2['reason'][:70]}")
                continue
            image_id = printify_client.upload_image(png)
            product = printify_client.create_product(
                shop, image_id, a["concept"]["product_type"],
                copy["title"], copy["description"],
                listing.price_for(a["concept"]["product_type"]), copy["tags"])
            (RUN_DIR / f"{tag}.json").write_text(json.dumps(
                {**a, "image_verdict": v2, "listing": copy, "product_id": product["id"]}, indent=2))
            if APPROVAL_MODE == "auto":
                printify_client.publish(shop, product["id"])
                budget.record_listing_fee()
                log(f"  PUBLISHED {product['id']}")
                if marketing.enabled():
                    try:
                        mockup = (product.get("images") or [{}])[0].get("src", "")
                        url = (f"https://{os.environ['SHOPIFY_STORE']}"
                               f"/products/{product.get('external', {}).get('handle', '')}")
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
    shop = printify_client.shop_id()
    for f in sorted(RUN_DIR.glob("c*.json")):
        rec = json.loads(f.read_text())
        printify_client.publish(shop, rec["product_id"])
        budget.record_listing_fee()
        log(f"PUBLISHED {rec['product_id']} ({rec['listing']['title'][:50]})")


if __name__ == "__main__":
    approve_all() if "--approve" in sys.argv else daily_run()
