"""Claude API wrapper with cost optimization: model tiering, prompt caching,
and per-call cost logging into the budget ledger.

Tiers:  smart  -> Sonnet (research scoring, IP judgment — where being wrong costs money)
        cheap  -> Haiku  (copywriting, prompt-writing, variants — 3-5x cheaper)
Caching: system prompts are cached (reads cost 0.1x input); within a daily run
the same system prompt recurs, so all but the first call hit cache.
"""
import json
import os

import anthropic

from . import budget

MODELS = {"smart": "claude-sonnet-4-6", "cheap": "claude-haiku-4-5-20251001"}
_client = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def ask(system: str, user: str, tier: str = "cheap", max_tokens: int = 1500) -> str:
    model = MODELS[tier]
    resp = client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    u = resp.usage
    budget.record_llm(model, u.input_tokens, u.output_tokens,
                      getattr(u, "cache_read_input_tokens", 0) or 0)
    return "".join(b.text for b in resp.content if b.type == "text")


def ask_vision(system: str, user: str, png_path: str,
               tier: str = "smart", max_tokens: int = 500) -> str:
    """Text+image call (used by the post-render IP screen)."""
    import base64
    with open(png_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    model = MODELS[tier]
    resp = client().messages.create(
        model=model, max_tokens=max_tokens,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
             "media_type": "image/png", "data": b64}},
            {"type": "text", "text": user}]}],
    )
    u = resp.usage
    budget.record_llm(model, u.input_tokens, u.output_tokens,
                      getattr(u, "cache_read_input_tokens", 0) or 0)
    return "".join(b.text for b in resp.content if b.type == "text")


def extract_json(raw: str):
    """Parse JSON from a model reply, tolerating fences, preamble, and
    trailing prose — models occasionally add them despite instructions."""
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(raw[start:end + 1])


def ask_json(system: str, user: str, tier: str = "cheap", max_tokens: int = 1500):
    raw = ask(system + "\nRespond with ONLY valid JSON. No markdown fences, no preamble.",
              user, tier, max_tokens)
    return extract_json(raw)
