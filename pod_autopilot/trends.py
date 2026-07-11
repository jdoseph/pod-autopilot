"""Trend proxy → a ranked list of `Trend`.

HARD CONSTRAINT: Etsy has NO trending/discovery API, and scraping Etsy search is
forbidden. So the trend signal comes ONLY from proxies:
  - Google Trends (pytrends), via `from_google`
  - a keyword-tool CSV export, via `from_csv`

Both return a list of `Trend` sorted by descending score. `fetch()` picks the
source from config (or MOCK mode).

Independently runnable:
    python -m pod_autopilot.trends --seed "cottagecore" --count 5
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from pathlib import Path

from . import config

# pytrends is optional at import time (mock mode / offline) — import lazily.
_PYTRENDS_TIMEOUT = (10, 30)  # (connect, read) seconds


@dataclass(frozen=True)
class Trend:
    topic: str
    score: float          # 0..100 relative interest
    source: str           # "google" | "csv" | "mock"
    seed: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _clean(topic: str) -> str:
    return " ".join(topic.strip().split())


def from_google(seed: str, count: int = 5) -> list[Trend]:
    """Related rising/top queries for `seed` from Google Trends."""
    from pytrends.request import TrendReq  # lazy import

    pytrends = TrendReq(hl="en-US", tz=0, timeout=_PYTRENDS_TIMEOUT)
    pytrends.build_payload([seed], timeframe="today 3-m")
    related = pytrends.related_queries()

    rows: list[Trend] = []
    bucket = (related or {}).get(seed, {}) or {}
    for kind in ("rising", "top"):
        frame = bucket.get(kind)
        if frame is None or getattr(frame, "empty", True):
            continue
        for _, row in frame.iterrows():
            topic = _clean(str(row.get("query", "")))
            if not topic:
                continue
            raw = row.get("value", 0)
            # "rising" values can be huge / "Breakout"; clamp to 0..100 band.
            score = 100.0 if str(raw).lower() == "breakout" else min(float(raw), 100.0)
            rows.append(Trend(topic=topic, score=score, source="google", seed=seed))

    # De-dupe by topic, keep highest score, sort desc, cap.
    best: dict[str, Trend] = {}
    for t in rows:
        if t.topic not in best or t.score > best[t.topic].score:
            best[t.topic] = t
    ranked = sorted(best.values(), key=lambda t: t.score, reverse=True)
    return ranked[:count]


def from_csv(path: str | Path, seed: str = "", count: int = 5) -> list[Trend]:
    """Parse a keyword-tool CSV export.

    Expected columns (case-insensitive), extras ignored:
      keyword / query / topic   -> topic
      volume / score / value    -> score
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"trend CSV not found: {path}")

    rows: list[Trend] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = {h.lower().strip(): h for h in (reader.fieldnames or [])}
        topic_key = _first(headers, ("keyword", "query", "topic", "term"))
        score_key = _first(headers, ("volume", "score", "value", "searches"))
        if topic_key is None:
            raise ValueError(f"CSV has no keyword/topic column: {list(headers)}")
        for record in reader:
            topic = _clean(str(record.get(topic_key, "")))
            if not topic:
                continue
            score = _parse_score(record.get(score_key)) if score_key else 0.0
            rows.append(Trend(topic=topic, score=score, source="csv", seed=seed))

    ranked = sorted(rows, key=lambda t: t.score, reverse=True)
    return ranked[:count]


def _first(headers: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        if c in headers:
            return headers[c]
    return None


def _parse_score(raw) -> float:
    if raw is None:
        return 0.0
    cleaned = str(raw).replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _mock(seed: str, count: int) -> list[Trend]:
    base = seed or "cottagecore"
    canned = [
        (f"{base} mushroom aesthetic", 100.0),
        (f"vintage {base} sunset", 88.0),
        (f"{base} frog cottagecore", 76.0),
        (f"retro {base} wildflower", 64.0),
        (f"{base} moth moon phases", 52.0),
    ]
    return [
        Trend(topic=_clean(t), score=s, source="mock", seed=seed)
        for t, s in canned[:count]
    ]


def fetch(seed: str, count: int = 5, cfg: config.Config | None = None) -> list[Trend]:
    """Top-level entry: choose source from config, honoring MOCK mode."""
    cfg = cfg or config.load()
    if cfg.mock:
        return _mock(seed, count)
    if cfg.trend_source == "csv":
        return from_csv(cfg.trend_csv_path, seed=seed, count=count)
    return from_google(seed, count=count)


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Fetch trend proxies for a seed niche.")
    ap.add_argument("--seed", required=True)
    ap.add_argument("--count", type=int, default=5)
    args = ap.parse_args()

    trends = fetch(args.seed, count=args.count)
    print(json.dumps([t.as_dict() for t in trends], indent=2))
