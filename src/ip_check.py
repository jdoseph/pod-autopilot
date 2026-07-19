"""Stage 3 — IP gate. Screens every phrase/concept against USPTO records plus a
Claude judgment call. Anything not clearly safe is rejected. This is the stage
that keeps your Printify/Etsy/Shopify accounts alive — do not weaken it."""
import json
import os

import requests

from .claude_client import ask_json, ask_vision

SYSTEM = """You are a conservative IP-risk screener for print-on-demand.
Reject anything that references or evokes: registered trademarks, brand names,
celebrities, athletes, teams, song lyrics, movie/TV/game characters or quotes,
or distinctive protected slogans. Common short phrases and generic humor are
fine. When in doubt, reject — a lost design costs nothing; a banned store
costs everything."""


def uspto_hits(phrase: str) -> list[str] | None:
    """Optional live-mark search. USPTO has no free public phrase-search API,
    so this is DISABLED unless USPTO_SEARCH_URL is set to a working endpoint
    (e.g. a paid TSDR proxy). Returns None when no search ran — the Claude
    screen then judges on its own knowledge rather than a fake 'no matches'."""
    url = os.environ.get("USPTO_SEARCH_URL")
    if not url:
        return None
    try:
        r = requests.get(url, params={"query": phrase, "rows": 5}, timeout=20)
        r.raise_for_status()
        docs = r.json().get("response", {}).get("docs", [])
        return [d.get("markText", "") for d in docs if d.get("markText")]
    except Exception:
        return None  # fail open: the Claude gate below still screens everything


def screen(concept: dict, text_on_design: str | None) -> dict:
    phrase = text_on_design or concept["concept"]
    hits = uspto_hits(phrase)
    uspto_line = ("no trademark database search was performed — judge from your "
                  "own knowledge of existing marks" if hits is None
                  else str(hits or "no matches"))
    verdict = ask_json(
        SYSTEM,
        f"""Design concept: {concept['concept']}
Text on design: {text_on_design or '(none)'}
USPTO search results for the phrase: {uspto_line}
Return JSON: {{"approved": bool, "risk_level": "low"|"medium"|"high",
"reason": str}}""",
        tier="smart",
    )
    verdict["approved"] = verdict["approved"] and verdict["risk_level"] == "low"
    return verdict


VISION_SYSTEM = """You are a conservative screener reviewing a RENDERED image
for print-on-demand. This is the last check before the design is sold.

Reject for IP RISK if the image visually resembles or evokes: any brand logo
or trade dress, a recognizable copyrighted character (even without text), a
celebrity or identifiable real person, a famous artwork, or a distinctive
protected visual style of a specific living artist.

Reject for QUALITY if the image has: garbled, misspelled, or half-formed
text/lettering anywhere; malformed anatomy, hands, faces, or objects;
rendering artifacts or smudged details; muddy gradients or an obviously
"AI-generated" look; a t-shirt/product mockup instead of standalone artwork;
or a busy background unsuitable for garment printing.

Common motifs, generic art styles, and clean original compositions are fine.
When in doubt, reject — a discarded image costs cents."""


def screen_image(png_path: str, expected_text: str | None = None) -> dict:
    """Second gate: screens the actual rendered pixels — IP risk, quality,
    and that any intended text rendered EXACTLY as designed (models sometimes
    drop the text or render placeholder words instead)."""
    if expected_text:
        expectation = (f'This design must display exactly this text, correctly '
                       f'spelled, and nothing else: "{expected_text}". Reject if '
                       'the text is missing, different, incomplete, misspelled, '
                       'or replaced by placeholder words.')
    else:
        expectation = ('This design must contain NO text or lettering at all — '
                       'reject if any words appear.')
    raw = ask_vision(
        VISION_SYSTEM,
        expectation + '\nReturn ONLY JSON: {"approved": bool, "risk_level": "low"|"medium"|"high", "reason": str}',
        png_path, tier="smart")
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    v = json.loads(raw)
    v["approved"] = v["approved"] and v["risk_level"] == "low"
    return v
