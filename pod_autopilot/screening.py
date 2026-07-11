"""Trademark / keyword gate — the ban-prevention layer.

HARD CONSTRAINT: IP risk is the #1 way this shop gets banned. This gate runs on
every Concept BEFORE any image is generated or anything is published. Bias toward
strictness: when in doubt, block.

STATUS: partial (per CLAUDE.md).
  - Blocklist here is a SEED only — HANDOFF.md Prompt 4 moves it to a data file,
    adds per-niche categories and fuzzy/leetspeak evasion matching.
  - `_uspto_live_check` endpoint is a GUESS and is DISABLED by default. Prompt 4
    says: verify the current USPTO endpoint before trusting it, fail closed on a
    positive match, fail open on network error, and log every decision.

`screen(concept)` returns a `ScreenResult`. `passed` is True only if nothing
tripped. Independently runnable:
    python -m pod_autopilot.screening --title "Just Do It vibes" --tags nike swoosh
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# SEED blocklist. Deliberately small and obvious — Prompt 4 expands + externalizes it.
# Lowercased substrings/phrases that must never appear in title/tags/prompt/description.
_SEED_BLOCKLIST: set[str] = {
    # megabrands
    "nike", "adidas", "gucci", "disney", "starbucks", "apple", "coca cola", "coca-cola",
    "just do it", "swoosh",
    # characters / franchises
    "mickey mouse", "pokemon", "pikachu", "star wars", "harry potter", "marvel",
    "spiderman", "spider-man", "batman", "barbie", "bluey", "taylor swift",
    # generic trademark tells
    "™", "®", "registered trademark",
}


@dataclass(frozen=True)
class ScreenResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"passed": self.passed, "reasons": self.reasons, "matched_terms": self.matched_terms}


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace. (Prompt 4 will add leetspeak folding.)"""
    return " ".join(text.lower().split())


def _find_blocked(text: str, blocklist: set[str]) -> list[str]:
    norm = _normalize(text)
    hits = []
    for term in blocklist:
        if not term:
            continue
        # word-boundary match for alphanumeric terms; plain substring for symbols.
        if term.isalnum() or " " in term or "-" in term:
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", norm):
                hits.append(term)
        elif term in norm:
            hits.append(term)
    return sorted(set(hits))


def _uspto_live_check(phrase: str) -> bool:
    """DISABLED stub. Endpoint below is UNVERIFIED (see CLAUDE.md / HANDOFF.md P4).

    When implemented: query the current USPTO trademark search API for a LIVE mark
    matching `phrase`. Return True if a live mark is found (=> block, fail closed).
    On network error the CALLER should fail OPEN (don't block on our own outage),
    and every decision should be logged.
    """
    raise NotImplementedError(
        "USPTO live-mark check is unverified/disabled — implement in HANDOFF.md Prompt 4"
    )


def screen(concept, *, blocklist: set[str] | None = None, use_uspto: bool = False) -> ScreenResult:
    """Screen a Concept (or any object exposing title/description/image_prompt/tags).

    Returns ScreenResult(passed=...). USPTO check is off by default until verified.
    """
    blocklist = blocklist if blocklist is not None else _SEED_BLOCKLIST

    fields_text = {
        "title": getattr(concept, "title", "") or "",
        "description": getattr(concept, "description", "") or "",
        "image_prompt": getattr(concept, "image_prompt", "") or "",
        "tags": " ".join(getattr(concept, "tags", []) or []),
    }

    reasons: list[str] = []
    matched: list[str] = []
    for field_name, text in fields_text.items():
        hits = _find_blocked(text, blocklist)
        if hits:
            reasons.append(f"blocked term(s) in {field_name}: {', '.join(hits)}")
            matched.extend(hits)

    if use_uspto:
        phrase = fields_text["title"]
        try:
            if _uspto_live_check(phrase):
                reasons.append(f"USPTO live mark matched: {phrase!r}")
                matched.append(phrase)
        except NotImplementedError:
            # Not verified yet — do not block on it (fail open on OUR limitation).
            reasons.append("USPTO check skipped (unimplemented)")
        except Exception as exc:  # network/other — fail OPEN, but record it.
            reasons.append(f"USPTO check errored, failing open: {exc}")

    passed = not matched
    return ScreenResult(passed=passed, reasons=reasons, matched_terms=sorted(set(matched)))


if __name__ == "__main__":
    import argparse
    import json
    from types import SimpleNamespace

    ap = argparse.ArgumentParser(description="Screen a concept for trademark/keyword risk.")
    ap.add_argument("--title", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--image-prompt", default="")
    ap.add_argument("--tags", nargs="*", default=[])
    args = ap.parse_args()

    fake = SimpleNamespace(
        title=args.title, description=args.description,
        image_prompt=args.image_prompt, tags=args.tags,
    )
    result = screen(fake)
    print(json.dumps(result.as_dict(), indent=2))
    raise SystemExit(0 if result.passed else 1)
