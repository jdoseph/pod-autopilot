"""Trademark / keyword gate — the ban-prevention layer.

HARD CONSTRAINT: IP risk is the #1 way this shop gets banned. This gate runs on
every Concept BEFORE any image is generated or anything is published. Bias toward
strictness: when in doubt, block.

Layers:
  1. Blocklist (blocklist.json) — categorized, easy to extend per niche.
  2. Fuzzy matcher — catches obvious evasions: spacing ("n i k e"), punctuation
     ("n.i.k.e"), leetspeak ("n1ke"), and simple plurals ("swooshes").
  3. USPTO live-mark check — CONFIG-DRIVEN and DISABLED by default. There is no
     stable free USPTO phrase-search JSON API (verified 2026-07; TSDR is
     lookup-by-number, tmsearch is a UI, ODP needs a key), so this is a pluggable
     hook: fail CLOSED on a positive match, fail OPEN on any network/parse/no-key
     error. The blocklist + fuzzy matcher carry the real weight — they can't fail open.

Every rejection is logged with reasons to output/screening_rejections.log for audit.

`screen(concept)` returns a `ScreenResult`; `passed` is True only if nothing tripped.

Independently runnable:
    python -m pod_autopilot.screening --title "Just Do It vibes" --tags nike swoosh
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)

_BLOCKLIST_PATH = Path(__file__).with_name("blocklist.json")
_USPTO_TIMEOUT = 15  # seconds

# Leetspeak fold: common letter<->symbol/number substitutions attackers use.
_LEET = {
    "a": "[a4@]", "b": "[b8]", "e": "[e3]", "g": "[g9]", "i": "[i1!|]",
    "l": "[l1|]", "o": "[o0]", "s": "[s5$]", "t": "[t7]", "z": "[z2]",
}


@dataclass(frozen=True)
class ScreenResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"passed": self.passed, "reasons": self.reasons, "matched_terms": self.matched_terms}


# --- blocklist loading ------------------------------------------------------

def load_blocklist(path: str | Path | None = None) -> list[str]:
    """Flatten the categorized blocklist JSON into a de-duped term list.

    Walks every list value (including nested `_niche_seed` categories). Keys and
    values starting with "_comment" are ignored.
    """
    path = Path(path) if path else _BLOCKLIST_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    terms: set[str] = set()

    def _collect(node) -> None:
        if isinstance(node, list):
            for item in node:
                if isinstance(item, str) and item.strip():
                    terms.add(item.strip().lower())
        elif isinstance(node, dict):
            for key, val in node.items():
                if key.startswith("_comment"):
                    continue
                _collect(val)

    _collect(data)
    return sorted(terms)


# --- fuzzy matching ---------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return " ".join(text.lower().split())


def _fuzzy_pattern(term: str) -> re.Pattern:
    """Build a regex that matches `term` tolerant to evasions.

    Between the letters of an alphanumeric run we allow optional spaces/punctuation,
    each letter may be its leetspeak equivalent, and a trailing optional plural
    ('s'/'es') is accepted. Non-alphanumeric terms (™, ®) match literally.
    """
    term = term.lower()
    alnum = [c for c in term if c.isalnum()]
    if not alnum:
        # symbol-only term (™, ®, ©): literal substring.
        return re.compile(re.escape(term))

    # Separator allowed between characters: spaces, dots, dashes, underscores, etc.
    sep = r"[\s._\-*]*"
    parts = []
    for ch in term:
        if ch.isalnum():
            parts.append(_LEET.get(ch, re.escape(ch)))
            parts.append(sep)
        else:
            # spaces/punctuation inside the term -> optional separator, so
            # "taylor swift", "taylorswift", and "taylor.swift" all match.
            if parts and parts[-1] != sep:
                parts.append(sep)
    core = "".join(parts).rstrip()
    # trim trailing separator group we may have appended
    if core.endswith(sep):
        core = core[: -len(sep)]
    # word-ish boundaries + optional simple plural.
    pattern = rf"(?<![a-z0-9]){core}(?:e?s)?(?![a-z0-9])"
    return re.compile(pattern)


class _Matcher:
    """Compiles the blocklist once, then screens text against it."""

    def __init__(self, terms: list[str]):
        self._compiled = [(t, _fuzzy_pattern(t)) for t in terms]

    def find(self, text: str) -> list[str]:
        norm = _normalize(text)
        return sorted({term for term, pat in self._compiled if pat.search(norm)})


_default_matcher: _Matcher | None = None


def _get_matcher() -> _Matcher:
    global _default_matcher
    if _default_matcher is None:
        _default_matcher = _Matcher(load_blocklist())
    return _default_matcher


# --- USPTO live-mark check (config-driven, disabled by default) -------------

def uspto_live_check(phrase: str, cfg: config.Config) -> bool | None:
    """Best-effort USPTO live-mark check.

    Returns:
      True  -> a live mark matched (caller should BLOCK / fail closed)
      False -> no match found
      None  -> could not determine (no endpoint/key, network/parse error) => the
               caller FAILS OPEN (does not block on our own outage).

    Disabled unless cfg.uspto_search_url is set. The endpoint contract is provided
    via config because USPTO has no stable free phrase-search API.
    """
    if not getattr(cfg, "uspto_search_url", ""):
        return None
    try:
        import requests  # lazy import

        headers = {}
        if getattr(cfg, "uspto_api_key", ""):
            headers["X-API-KEY"] = cfg.uspto_api_key
        resp = requests.get(
            cfg.uspto_search_url,
            params={"query": phrase},
            headers=headers,
            timeout=_USPTO_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning("USPTO check HTTP %s — failing open", resp.status_code)
            return None
        data = resp.json()
        # Generic shape handling: treat any live/active result as a positive.
        results = data.get("results") or data.get("trademarks") or data.get("data") or []
        for r in results if isinstance(results, list) else []:
            status = str(r.get("status", r.get("live", ""))).lower()
            if status in ("live", "registered", "active", "true"):
                return True
        return False
    except Exception as exc:  # network/parse/etc. — fail OPEN, but log it.
        logger.warning("USPTO check errored (%s) — failing open", exc)
        return None


# --- rejection logging ------------------------------------------------------

def _log_rejection(cfg: config.Config, result: ScreenResult, title: str) -> None:
    try:
        log_path = cfg.output_dir / "screening_rejections.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat()
        line = json.dumps({
            "ts": stamp, "title": title,
            "matched_terms": result.matched_terms, "reasons": result.reasons,
        })
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        logger.warning("could not write rejection log: %s", exc)


# --- main entry -------------------------------------------------------------

def screen(
    concept,
    *,
    blocklist: set[str] | list[str] | None = None,
    use_uspto: bool = False,
    cfg: config.Config | None = None,
    log_rejections: bool = True,
) -> ScreenResult:
    """Screen a Concept (or any object exposing title/description/image_prompt/tags).

    Returns ScreenResult(passed=...). Fuzzy matching is always applied. The USPTO
    check runs only if use_uspto=True AND a search URL is configured; it fails
    closed on a match and open on error. Rejections are logged for audit.
    """
    cfg = cfg or config.load()
    if blocklist is None:
        matcher = _get_matcher()
    else:
        matcher = _Matcher(sorted({t.lower() for t in blocklist if t}))

    fields_text = {
        "title": getattr(concept, "title", "") or "",
        "description": getattr(concept, "description", "") or "",
        "image_prompt": getattr(concept, "image_prompt", "") or "",
        "tags": " ".join(getattr(concept, "tags", []) or []),
    }

    reasons: list[str] = []
    matched: list[str] = []
    for field_name, text in fields_text.items():
        hits = matcher.find(text)
        if hits:
            reasons.append(f"blocked term(s) in {field_name}: {', '.join(hits)}")
            matched.extend(hits)

    if use_uspto:
        phrase = fields_text["title"]
        verdict = uspto_live_check(phrase, cfg)
        if verdict is True:
            reasons.append(f"USPTO live mark matched: {phrase!r}")
            matched.append(f"uspto:{phrase}")
        elif verdict is None:
            reasons.append("USPTO check inconclusive (failed open)")
        # verdict is False -> clean, no reason added.

    passed = not matched
    result = ScreenResult(passed=passed, reasons=reasons, matched_terms=sorted(set(matched)))
    if not passed and log_rejections:
        _log_rejection(cfg, result, fields_text["title"])
    return result


if __name__ == "__main__":
    import argparse
    from types import SimpleNamespace

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Screen a concept for trademark/keyword risk.")
    ap.add_argument("--title", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--image-prompt", default="")
    ap.add_argument("--tags", nargs="*", default=[])
    ap.add_argument("--uspto", action="store_true", help="also run the USPTO check (if configured)")
    args = ap.parse_args()

    fake = SimpleNamespace(
        title=args.title, description=args.description,
        image_prompt=args.image_prompt, tags=args.tags,
    )
    result = screen(fake, use_uspto=args.uspto, log_rejections=False)
    print(json.dumps(result.as_dict(), indent=2))
    raise SystemExit(0 if result.passed else 1)
