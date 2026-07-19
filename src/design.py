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

BACKGROUND: the background is deleted in post-processing so only the art
prints on the garment. Demand one plain solid uniform background color
clearly distinct from every artwork color, keep all artwork elements
connected and away from the edges, and never let the design depend on
its background.

BANNED: brand references, real people, copyrighted characters, named
artists/studios or 'in the style of' any identifiable creator, watercolor,
3D renders, drop shadows, busy backgrounds, photorealistic detail."""


def write_design_prompt(concept: dict) -> dict:
    d = ask_json(
        SYSTEM,
        f"""Concept: {concept['concept']}
Audience: {concept['audience']} | Product: {concept['product_type']}
Return JSON: {{"image_prompt": str,
"text_on_design": str or null (the EXACT words that appear on the design,
nothing else — no style notes), "style": str}}""",
        tier="cheap",
    )
    text = d.get("text_on_design")
    if text:
        # Enforce in code, not hope: Ideogram renders quoted text reliably,
        # but only when the prompt states it explicitly and prominently.
        d["image_prompt"] = (
            f'The design prominently features the text "{text}" — spelled '
            f'exactly, large and readable, integrated into the composition, '
            f'no other words anywhere. {d["image_prompt"]}')
    return d


MODEL_URLS = {
    "schnell": "black-forest-labs/flux-schnell",   # ~$0.003/img — textless drafts
    "pro": "black-forest-labs/flux-1.1-pro",       # ~$0.04/img — proven winners
    "text": "ideogram-ai/ideogram-v3-turbo",       # ~$0.03/img — any design with text
}

# Render aspect per product: shirts take portrait art, but tote/mug print
# areas are roughly square — portrait art there overflows and gets cut off.
ASPECT_RATIO = {"t-shirt": "3:4", "mug": "1:1", "tote": "1:1"}
ASPECT_VALUE = {"3:4": 0.75, "1:1": 1.0, "4:3": 4 / 3}


def pick_aspect(product_type: str) -> str:
    return ASPECT_RATIO.get(product_type.lower().strip(), "3:4")


def model_input(tier: str, image_prompt: str, aspect: str = "3:4") -> dict:
    """Per-model request payload. Ideogram v3 renders typography reliably
    (90%+ accuracy vs Flux Schnell's garble); Design style + magic prompt
    off keeps output faithful to our carefully constructed prompt."""
    if tier == "text":
        return {"prompt": image_prompt, "aspect_ratio": aspect,
                "style_type": "Design", "magic_prompt_option": "Off"}
    return {"prompt": image_prompt, "aspect_ratio": aspect,
            "output_format": "png"}


def pick_tier(design: dict) -> str:
    """Route text-bearing designs to the typography-capable model."""
    return "text" if design.get("text_on_design") else "schnell"


BG_REMOVER = "851-labs/background-remover"  # ~$0.0005/img, transparent PNG


def remove_background(png_path: str) -> bool:
    """Make the render transparent so only the art prints — the artwork then
    matches any garment color (the cream-rectangle-on-canvas-tote problem).
    Non-fatal: on failure the original opaque render is kept."""
    import base64
    try:
        headers = {"Authorization": f"Bearer {os.environ['REPLICATE_API_TOKEN']}"}
        with open(png_path, "rb") as f:
            data_uri = ("data:image/png;base64,"
                        + base64.b64encode(f.read()).decode())
        r = requests.post(
            f"https://api.replicate.com/v1/models/{BG_REMOVER}/predictions",
            headers={**headers, "Prefer": "wait"},
            json={"input": {"image": data_uri}}, timeout=120)
        r.raise_for_status()
        pred = r.json()
        while pred["status"] not in ("succeeded", "failed", "canceled"):
            time.sleep(2)
            pred = requests.get(pred["urls"]["get"], headers=headers,
                                timeout=30).json()
        if pred["status"] != "succeeded":
            raise RuntimeError(pred.get("error"))
        url = pred["output"] if isinstance(pred["output"], str) else pred["output"][0]
        png = requests.get(url, timeout=60).content
        with open(png_path, "wb") as f:
            f.write(png)
        budget.record_image("bgremove")
        return True
    except Exception as e:
        print(f"[design] background removal failed ({e}); keeping original")
        return False


def render(image_prompt: str, out_path: str, tier: str = "schnell",
           aspect: str = "3:4", retries: int = 2) -> str:
    """Render with retries — Replicate throws occasional transient 5xx/E-errors."""
    for attempt in range(retries + 1):
        try:
            return _render_once(image_prompt, out_path, tier, aspect)
        except Exception:
            if attempt == retries:
                raise
            time.sleep(5 * (attempt + 1))


def _render_once(image_prompt: str, out_path: str, tier: str, aspect: str) -> str:
    """Render via Replicate's HTTP API and save a PNG. Returns file path."""
    headers = {"Authorization": f"Bearer {os.environ['REPLICATE_API_TOKEN']}"}
    r = requests.post(
        f"https://api.replicate.com/v1/models/{MODEL_URLS[tier]}/predictions",
        headers={**headers, "Prefer": "wait"},
        json={"input": model_input(tier, image_prompt, aspect)},
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
