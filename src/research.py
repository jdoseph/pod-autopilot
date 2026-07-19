"""Stage 1 — Research agent: turn trend signals into ranked product concepts."""
from datetime import date

from .claude_client import ask_json

SYSTEM = """You are a print-on-demand product researcher. You find niches with
passionate audiences and low design competition. You avoid anything referencing
brands, celebrities, sports teams, song lyrics, or existing IP. Score honestly:
most ideas are mediocre and should score below 6."""


def gather_signals() -> str:
    """Assemble raw trend signals. Extend with real sources over time:
    Google Trends (pytrends), Reddit API (niche subreddits), Etsy search
    suggestions, Pinterest trends. Each returns text blobs appended here."""
    signals = [f"Today's date: {date.today().isoformat()} (consider upcoming holidays/seasons 6-8 weeks out, since that's the buying window)."]
    # TODO: signals.append(pytrends_rising_queries(...))
    # TODO: signals.append(reddit_hot_posts(["r/hobbies", "r/nursing", "r/teachers"]))
    return "\n".join(signals)


def generate_concepts(per_type: int = 3) -> list[dict]:
    """Returns list of {niche, product_type, concept, audience, score, rationale},
    a balanced slate across the three product types the store sells."""
    candidates = per_type * 2  # ask for spares so the >=7.0 bar still fills the slate
    data = ask_json(
        SYSTEM,
        f"""Trend signals:\n{gather_signals()}\n
Generate exactly {candidates} print-on-demand product concepts EACH for the
product types "t-shirt", "mug", and "tote" ({candidates * 3} concepts total).
product_type must be EXACTLY one of: "t-shirt", "mug", "tote" (lowercase).
Return JSON: {{"concepts": [{{"niche": str, "product_type": str,
"concept": str (the design idea in one sentence), "audience": str,
"score": float 1-10, "rationale": str}}]}}""",
        tier="smart",
        max_tokens=1000 + 400 * candidates * 3,
    )
    concepts = sorted(data["concepts"], key=lambda c: c["score"], reverse=True)
    picked, counts = [], {}
    for c in concepts:
        ptype = c.get("product_type", "").lower().strip()
        if c["score"] >= 7.0 and counts.get(ptype, 0) < per_type:
            counts[ptype] = counts.get(ptype, 0) + 1
            picked.append(c)
    return picked
