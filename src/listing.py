"""Stage 5 — Listing agent: SEO copy + margin pricing.
Cost optimization: ONE Haiku call writes listings for ALL approved concepts,
instead of one call per product. Shared system prompt is cached."""
import os

from .claude_client import ask_json

SYSTEM = """You write ecommerce listings that rank in marketplace search.
Per listing — Title: front-load highest-intent keywords, under 130 chars,
human-readable. Tags: 13 long-tail tags, no repeats. Description: benefit-led,
scannable, gift-occasion keywords, honest. HARD BANS (never use): the words
"handmade"/"hand-crafted"/"hand-made", any delivery timeline or shipping
promise, fake scarcity or urgency ("only X left", "limited time"), and any
health, safety, or therapeutic claims."""

# Etsy REQUIRES an AI disclosure on AI-assisted listings (enforced since
# Jan 14, 2026; missing it risks takedowns and suspension). The owner
# publishes to their own Shopify store and opted out of disclosure there,
# so it is gated by DISCLOSE_AI (default off). Set DISCLOSE_AI=1 before
# publishing to Etsy — do not delete this constant or the gate.
AI_DISCLOSURE = (
    "\n\n---\nAI-assisted design: artwork generated with AI image tools "
    "from this shop's original concepts and creative direction; "
    "listing text drafted with AI assistance and reviewed. "
    "Printed and shipped by our production partner."
)


def disclosure() -> str:
    """The disclosure suffix, or empty when the owner has opted out."""
    on = os.environ.get("DISCLOSE_AI", "").lower() in ("1", "true", "yes")
    return AI_DISCLOSURE if on else ""

# Provisional prices for the create payload only — the moment Printify
# returns real per-variant costs, printify_client reprices every variant.
BASE_COST = {"t-shirt": 1100, "mug": 600, "tote": 900, "poster": 800}  # cents
TARGET_MARGIN = 0.55


def price_for(product_type: str) -> int:
    cost = BASE_COST.get(product_type.lower().strip(), 1100)
    return int(round((cost / (1 - TARGET_MARGIN)) / 100) * 100 - 5)


def write_listings_bulk(concepts: list[dict]) -> list[dict]:
    """One call, N listings. Returns list aligned with input order."""
    if not concepts:
        return []
    items = "\n".join(
        f'{i}. {c["product_type"]} | niche: {c["niche"]} | design: {c["concept"]} '
        f'| audience: {c["audience"]}' for i, c in enumerate(concepts))
    data = ask_json(
        SYSTEM,
        f"""Write one listing per numbered product:\n{items}\n
Return JSON: {{"listings": [{{"index": int, "title": str,
"tags": [str x13], "description": str}}]}}""",
        tier="cheap",
        max_tokens=1200 * len(concepts),
    )
    by_index = {l["index"]: l for l in data["listings"]}
    out = []
    for i, c in enumerate(concepts):
        l = by_index.get(i) or {  # model skipped one — plain fallback, still aligned
            "index": i,
            "title": f"{c['concept'][:100]} {c['product_type']}".strip(),
            "tags": [c["niche"], c["product_type"], c["audience"]][:13],
            "description": f"{c['concept']} — designed for {c['audience']}.",
        }
        l["description"] = l["description"].rstrip() + disclosure()
        out.append(l)
    return out
