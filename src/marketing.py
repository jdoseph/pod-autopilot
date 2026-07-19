"""Stage 9 — Traffic agent. Auto-posts a Pinterest pin per published product.
Pinterest chosen deliberately: POD niches perform well there, pins have months
of shelf life, and the API supports fully automated posting. Free to post;
only the Haiku caption call costs (~$0.001, logged to the ledger)."""
import os

import requests

from .claude_client import ask_json

SYSTEM = """You write Pinterest pin copy that earns saves and clicks.
Title: under 100 chars, keyword-led, no clickbait. Description: 2-3 sentences,
natural keywords, ends with a soft call to action. Honest — no scarcity, no
"handmade", no delivery promises. Never mention the design tools or process."""


def enabled() -> bool:
    return bool(os.environ.get("PINTEREST_ACCESS_TOKEN")
                and os.environ.get("PINTEREST_BOARD_ID"))


def post_pin(concept: dict, listing_copy: dict, image_url: str, product_url: str) -> str:
    copy = ask_json(
        SYSTEM,
        f"""Product: {concept['product_type']} for {concept['audience']}
Design: {concept['concept']}
Listing title: {listing_copy['title']}
Return JSON: {{"title": str, "description": str}}""",
        tier="cheap")
    r = requests.post(
        "https://api.pinterest.com/v5/pins",
        headers={"Authorization": f"Bearer {os.environ['PINTEREST_ACCESS_TOKEN']}"},
        json={"board_id": os.environ["PINTEREST_BOARD_ID"],
              "title": copy["title"][:100],
              "description": copy["description"][:800],
              "link": product_url,
              "media_source": {"source_type": "image_url", "url": image_url}},
        timeout=30)
    r.raise_for_status()
    return r.json()["id"]
