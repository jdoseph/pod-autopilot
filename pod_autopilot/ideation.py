"""Claude → original design concepts + Etsy copy, as structured `Concept`s.

Given a trend topic, asks Claude for N ORIGINAL t-shirt concepts. Each concept
carries the image prompt plus Etsy listing copy (title, description, tags).

HARD CONSTRAINT: the prompt instructs Claude to avoid trademarked brands,
characters, and song lyrics. This is a first line of defense only — every
Concept still passes through screening.py before anything is generated.

Independently runnable:
    python -m pod_autopilot.ideation --topic "cottagecore mushroom" --count 3
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict

from . import config

_ANTHROPIC_TIMEOUT = 60  # seconds

_SYSTEM = (
    "You are a print-on-demand t-shirt designer. You produce ORIGINAL artwork "
    "concepts only. You NEVER reference trademarked brands, company names, "
    "logos, copyrighted characters, celebrities, or song lyrics. You avoid any "
    "phrase likely to be a registered trademark. Output ONLY valid JSON."
)

_PROMPT_TEMPLATE = """\
Trend topic: "{topic}"

Generate {count} original t-shirt design concepts inspired by this topic.
Return a JSON object with a single key "concepts" whose value is an array of
exactly {count} objects, each with these string/array fields:

- "title": Etsy listing title, <= 140 chars, keyword-rich, no trademarks.
- "image_prompt": a vivid text-to-image prompt for original vector-style art on
  a transparent background. No brand/character references.
- "description": 2-3 sentence Etsy description of the design (no production
  partner disclosure — that is added later automatically).
- "tags": array of 8-13 short Etsy tags (each <= 20 chars), no trademarks.

Return ONLY the JSON object, no prose, no markdown fences.
"""


@dataclass(frozen=True)
class Concept:
    topic: str
    title: str
    image_prompt: str
    description: str
    tags: list[str] = field(default_factory=list)

    def slug(self) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")
        return base[:60] or "concept"

    def as_dict(self) -> dict:
        return asdict(self)


class IdeationError(RuntimeError):
    """Raised when Claude's response can't be parsed into Concepts."""


def _extract_json(text: str) -> dict:
    """Best-effort: strip markdown fences, grab the outermost JSON object."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise IdeationError(f"could not parse JSON from response: {exc}") from exc
    raise IdeationError("no JSON object found in response")


def parse_concepts(text: str, topic: str) -> list[Concept]:
    """Parse a raw model response into Concepts. Raises IdeationError on bad shape."""
    data = _extract_json(text)
    items = data.get("concepts")
    if not isinstance(items, list) or not items:
        raise IdeationError("response JSON missing non-empty 'concepts' array")

    concepts: list[Concept] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise IdeationError(f"concept #{i} is not an object")
        title = str(item.get("title", "")).strip()
        image_prompt = str(item.get("image_prompt", "")).strip()
        if not title or not image_prompt:
            raise IdeationError(f"concept #{i} missing title or image_prompt")
        raw_tags = item.get("tags", [])
        tags = [str(t).strip() for t in raw_tags if str(t).strip()] if isinstance(raw_tags, list) else []
        concepts.append(
            Concept(
                topic=topic,
                title=title,
                image_prompt=image_prompt,
                description=str(item.get("description", "")).strip(),
                tags=tags,
            )
        )
    return concepts


def _mock(topic: str, count: int) -> list[Concept]:
    out: list[Concept] = []
    for i in range(1, count + 1):
        out.append(
            Concept(
                topic=topic,
                title=f"Original {topic.title()} Cottage Tee Design {i}",
                image_prompt=(
                    f"original vector illustration inspired by {topic}, whimsical, "
                    "muted earth tones, transparent background, centered, no text"
                ),
                description=(
                    f"A hand-drawn original design inspired by {topic}. "
                    "Soft, nostalgic palette printed on a comfortable unisex tee."
                ),
                tags=[
                    "cottagecore", "original art", "botanical tee", "cottage tshirt",
                    "whimsical", "nature lover", "vintage aesthetic", "gift for her",
                ],
            )
        )
    return out


def ideate(topic: str, count: int = 3, cfg: config.Config | None = None) -> list[Concept]:
    """Generate `count` original Concepts for `topic`."""
    cfg = cfg or config.load()
    if cfg.mock:
        return _mock(topic, count)

    from anthropic import Anthropic  # lazy import

    client = Anthropic(api_key=cfg.anthropic_api_key, timeout=_ANTHROPIC_TIMEOUT)
    msg = client.messages.create(
        model=cfg.ideation_model,
        max_tokens=2000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _PROMPT_TEMPLATE.format(topic=topic, count=count)}],
    )
    text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
    return parse_concepts(text, topic)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Generate original t-shirt concepts for a topic.")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--count", type=int, default=3)
    args = ap.parse_args()

    for c in ideate(args.topic, count=args.count):
        print(json.dumps(c.as_dict(), indent=2))
