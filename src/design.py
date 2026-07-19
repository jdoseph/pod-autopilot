"""Stage 2 — Design agent. Claude writes the image prompt; an image model renders it.
Uses Replicate by default (swap for Ideogram — it's better at text-on-design)."""
import os
import time

import requests

from . import budget
from .claude_client import ask_json

SYSTEM = """You write prompts for an AI image model producing print-on-demand
artwork that must look professionally designed, never "AI-generated".

STYLE RULES (bake these into every prompt):
- flat vector illustration, bold simple shapes, clean sharp edges,
  high contrast, screen-print aesthetic
- limited palette: name 3-5 specific solid colors; say "solid color blocks,
  no gradients, no airbrush shading, no photorealism"
- single centered composition on a plain solid background with generous
  margin — the artwork only, never a t-shirt/mug mockup, never a model
- readable at 12x16 inches from across a room

TEXT RULES: if the concept includes text, quote the EXACT wording, keep it
under 6 words, and describe the type treatment (e.g. "bold retro serif
arched above the illustration"). No other words or lettering anywhere.

BANNED: brand references, real people, copyrighted characters, named
artists/studios or 'in the style of' any identifiable creator, watercolor,
3D renders, drop shadows, busy backgrounds, photorealistic detail."""


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
    "schnell": "black-forest-labs/flux-schnell",   # ~$0.003/img — textless drafts
    "pro": "black-forest-labs/flux-1.1-pro",       # ~$0.04/img — proven winners
    "text": "ideogram-ai/ideogram-v3-turbo",       # ~$0.03/img — any design with text
}


def model_input(tier: str, image_prompt: str) -> dict:
    """Per-model request payload. Ideogram v3 renders typography reliably
    (90%+ accuracy vs Flux Schnell's garble); Design style + magic prompt
    off keeps output faithful to our carefully constructed prompt."""
    if tier == "text":
        return {"prompt": image_prompt, "aspect_ratio": "3:4",
                "style_type": "Design", "magic_prompt_option": "Off"}
    return {"prompt": image_prompt, "aspect_ratio": "3:4",
            "output_format": "png"}


def pick_tier(design: dict) -> str:
    """Route text-bearing designs to the typography-capable model."""
    return "text" if design.get("text_on_design") else "schnell"


def render(image_prompt: str, out_path: str, tier: str = "schnell",
           retries: int = 2) -> str:
    """Render with retries — Replicate throws occasional transient 5xx/E-errors."""
    for attempt in range(retries + 1):
        try:
            return _render_once(image_prompt, out_path, tier)
        except Exception:
            if attempt == retries:
                raise
            time.sleep(5 * (attempt + 1))


def _render_once(image_prompt: str, out_path: str, tier: str) -> str:
    """Render via Replicate's HTTP API and save a PNG. Returns file path."""
    headers = {"Authorization": f"Bearer {os.environ['REPLICATE_API_TOKEN']}"}
    r = requests.post(
        f"https://api.replicate.com/v1/models/{MODEL_URLS[tier]}/predictions",
        headers={**headers, "Prefer": "wait"},
        json={"input": model_input(tier, image_prompt)},
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
