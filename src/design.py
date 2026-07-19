"""Stage 2 — Design agent. Claude writes the image prompt; an image model renders it.
Uses Replicate by default (swap for Ideogram — it's better at text-on-design)."""
import os
import time

import requests

from . import budget
from .claude_client import ask_json

SYSTEM = """You write prompts for an AI image model producing print-on-demand
artwork. Requirements: transparent/solid background suitable for garment
printing, bold and readable at 12x16 inches, no brand references, no real
people, no copyrighted characters, and NEVER reference a named artist,
studio, or 'in the style of' any identifiable creator — describe the desired
aesthetic in generic terms instead. If the concept includes text, spell it
exactly and keep it short."""


def write_design_prompt(concept: dict) -> dict:
    return ask_json(
        SYSTEM,
        f"""Concept: {concept['concept']}
Audience: {concept['audience']} | Product: {concept['product_type']}
Return JSON: {{"image_prompt": str, "text_on_design": str or null,
"style": str}}""",
        tier="cheap",
    )


MODEL_URLS = {
    "schnell": "black-forest-labs/flux-schnell",   # ~$0.003/img — default for tests
    "pro": "black-forest-labs/flux-1.1-pro",       # ~$0.04/img — winners only
}


def render(image_prompt: str, out_path: str, tier: str = "schnell") -> str:
    """Render via Replicate's HTTP API and save a PNG. Returns file path."""
    headers = {"Authorization": f"Bearer {os.environ['REPLICATE_API_TOKEN']}"}
    r = requests.post(
        f"https://api.replicate.com/v1/models/{MODEL_URLS[tier]}/predictions",
        headers={**headers, "Prefer": "wait"},
        json={"input": {"prompt": image_prompt, "aspect_ratio": "3:4",
                        "output_format": "png"}},
        timeout=120,
    )
    r.raise_for_status()
    pred = r.json()
    while pred["status"] not in ("succeeded", "failed", "canceled"):
        time.sleep(2)
        pred = requests.get(pred["urls"]["get"], headers=headers, timeout=30).json()
    if pred["status"] != "succeeded":
        raise RuntimeError(f"Image generation failed: {pred.get('error')}")
    url = pred["output"] if isinstance(pred["output"], str) else pred["output"][0]
    png = requests.get(url, timeout=60).content
    with open(out_path, "wb") as f:
        f.write(png)
    budget.record_image(tier)
    return out_path
