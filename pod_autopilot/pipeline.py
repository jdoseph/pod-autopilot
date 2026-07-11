"""Pipeline orchestrator — wires every stage together.

    seed → trends.fetch → ideation.ideate → screening.screen → design.generate_design
         → printify_client (upload → create → publish)

Default is REVIEW-FIRST: it stages art + copy into output/ and does NOT publish.
Pass --auto-publish to actually publish to Etsy via Printify.

MOCK mode (MOCK=1) makes the whole run offline and deterministic: canned trends,
canned concepts, local solid-color PNGs, and a no-op Printify client.

Persistence & compliance (HANDOFF.md Prompt 5):
  - a SQLite run ledger (ledger.py) records every topic/title/slug/screening/publish
    status; future runs skip already-used topics and titles and never repeat a design.
  - the required Printify production-partner disclosure is injected into every
    description and asserted present before publishing.
  - a margin floor refuses to publish any variant whose (retail - base - shipping) /
    retail is below cfg.min_margin; skips are logged.

    python -m pod_autopilot.pipeline --seed "cottagecore" --count 3
    python -m pod_autopilot.pipeline --seed "cottagecore" --count 3 --auto-publish
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import config, trends, ideation, screening, design, printify_client, ledger as ledger_mod

logger = logging.getLogger(__name__)

# Etsy requires disclosing the production partner. Prompt 5 injects this
# automatically into every description and confirms it survives publishing.
DISCLOSURE = (
    "Production & shipping by our print partner Printify. "
    "Designed originally for this shop."
)


@dataclass
class StageOutcome:
    topic: str
    title: str
    slug: str
    screened_ok: bool
    art_path: str | None = None
    product_id: str | None = None
    published: bool = False
    skipped_reason: str | None = None


@dataclass
class RunSummary:
    seed: str
    published: int = 0
    staged: int = 0
    skipped: int = 0
    outcomes: list[StageOutcome] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "seed": self.seed,
            "published": self.published,
            "staged": self.staged,
            "skipped": self.skipped,
            "outcomes": [o.__dict__ for o in self.outcomes],
        }


def _with_disclosure(description: str) -> str:
    """Append the required Printify disclosure once (idempotent)."""
    if DISCLOSURE in description:
        return description
    sep = "\n\n" if description else ""
    return f"{description}{sep}{DISCLOSURE}"


def variant_margin(retail_cents: int, cost_cents: int) -> float:
    """Profit margin as a fraction of retail. 0 retail => 0 margin (never publish)."""
    if retail_cents <= 0:
        return 0.0
    return (retail_cents - cost_cents) / retail_cents


def profitable_variants(
    client: printify_client.PrintifyClient,
    variant_ids: list[int],
    retail_cents: int,
    min_margin: float,
) -> tuple[list[int], list[str]]:
    """Split variants into (keep, skipped_reasons) by the margin floor.

    A variant is kept only if (retail - base - shipping) / retail >= min_margin.
    """
    keep: list[int] = []
    skipped: list[str] = []
    for vid in variant_ids:
        cost = client.variant_cost_cents(vid)
        margin = variant_margin(retail_cents, cost)
        if margin >= min_margin:
            keep.append(vid)
        else:
            skipped.append(
                f"variant {vid}: margin {margin:.0%} < floor {min_margin:.0%} "
                f"(retail {retail_cents}c, cost {cost}c)"
            )
    return keep, skipped


def run(
    seed: str,
    count: int = 3,
    *,
    auto_publish: bool = False,
    cfg: config.Config | None = None,
) -> RunSummary:
    cfg = cfg or config.load()
    summary = RunSummary(seed=seed)

    logger.info("=== pod-autopilot run: seed=%r count=%d mock=%s auto_publish=%s ===",
                seed, count, cfg.mock, auto_publish)

    topics = trends.fetch(seed, count=count, cfg=cfg)
    logger.info("fetched %d trend topics", len(topics))

    client = printify_client.PrintifyClient(cfg)
    price_cents = int(round(cfg.retail_price * 100))
    ledger = ledger_mod.RunLedger(cfg.output_dir / "run_ledger.db")

    try:
        _run_topics(topics, cfg, client, ledger, price_cents, auto_publish, summary)
    finally:
        ledger.close()

    logger.info("=== done: published=%d staged=%d skipped=%d ===",
                summary.published, summary.staged, summary.skipped)
    return summary


def _run_topics(topics, cfg, client, ledger, price_cents, auto_publish, summary) -> None:
    for trend in topics:
        # --- dedupe: skip topics we've already used in a prior run ---
        if ledger.seen_topic(trend.topic):
            summary.skipped += 1
            summary.outcomes.append(StageOutcome(
                topic=trend.topic, title="", slug="", screened_ok=False,
                skipped_reason="topic already used (ledger)",
            ))
            logger.info("SKIP topic %r — already used", trend.topic)
            continue

        # One concept per topic keeps the scaffold simple; ideation can return more.
        concepts = ideation.ideate(trend.topic, count=1, cfg=cfg)
        for concept in concepts:
            slug = concept.slug()
            outcome = StageOutcome(
                topic=trend.topic, title=concept.title, slug=slug, screened_ok=False,
            )

            # --- dedupe: skip already-used titles/slugs ---
            if ledger.seen_slug(slug) or ledger.seen_title(concept.title):
                outcome.skipped_reason = "title/slug already used (ledger)"
                summary.skipped += 1
                summary.outcomes.append(outcome)
                logger.info("SKIP %s — title/slug already used", slug)
                continue

            # --- ban-prevention gate (bias strict) ---
            result = screening.screen(concept, cfg=cfg)
            if not result.passed:
                outcome.skipped_reason = f"screening blocked: {'; '.join(result.reasons)}"
                summary.skipped += 1
                summary.outcomes.append(outcome)
                _record(ledger, outcome, "skipped")
                logger.warning("SKIP %s — %s", slug, outcome.skipped_reason)
                continue
            outcome.screened_ok = True

            # --- per-design output folder ---
            design_dir = cfg.output_dir / slug
            design_dir.mkdir(parents=True, exist_ok=True)

            # --- art ---
            art_path = design_dir / "art.png"
            try:
                design.generate_design(concept.image_prompt, art_path, cfg=cfg)
            except Exception as exc:
                outcome.skipped_reason = f"design failed: {exc}"
                summary.skipped += 1
                summary.outcomes.append(outcome)
                _record(ledger, outcome, "skipped")
                logger.error("SKIP %s — %s", slug, outcome.skipped_reason)
                continue
            outcome.art_path = str(art_path)

            # --- copy (with required disclosure) ---
            description = _with_disclosure(concept.description)
            (design_dir / "concept.json").write_text(
                json.dumps(
                    {**concept.as_dict(), "description": description, "trend": trend.as_dict()},
                    indent=2,
                ),
                encoding="utf-8",
            )

            if not auto_publish:
                summary.staged += 1
                summary.outcomes.append(outcome)
                _record(ledger, outcome, "staged")
                logger.info("STAGED %s (review-first; not published)", slug)
                continue

            # --- margin floor: refuse variants below the configured minimum ---
            keep, margin_skips = profitable_variants(
                client, list(cfg.printify_variant_ids), price_cents, cfg.min_margin,
            )
            for reason in margin_skips:
                logger.warning("margin skip for %s: %s", slug, reason)
            if not keep:
                outcome.skipped_reason = (
                    "no variant clears margin floor: " + "; ".join(margin_skips)
                    if margin_skips else "no variants configured (PRINTIFY_VARIANT_IDS empty)"
                )
                summary.skipped += 1
                summary.outcomes.append(outcome)
                _record(ledger, outcome, "skipped")
                logger.warning("SKIP %s — %s", slug, outcome.skipped_reason)
                continue

            # --- publish path (idempotent via the client's slug ledger) ---
            # Belt-and-suspenders: never publish a description missing the disclosure.
            assert DISCLOSURE in description, "disclosure line missing before publish"
            image_id = client.upload_image(art_path)
            pub = client.create_and_publish(
                slug=slug, title=concept.title, description=description,
                image_id=image_id, variant_ids=keep, price_cents=price_cents,
                mockup_dir=design_dir,
            )
            outcome.product_id = pub.product_id
            outcome.published = pub.published
            if pub.skipped:
                outcome.skipped_reason = "already published (ledger)"
                summary.skipped += 1
                _record(ledger, outcome, "published")
            elif pub.published:
                summary.published += 1
                _record(ledger, outcome, "published")
            else:
                summary.staged += 1
                _record(ledger, outcome, "staged")
            summary.outcomes.append(outcome)
            logger.info("PUBLISHED %s -> product %s (published=%s, skipped=%s, variants=%d)",
                        slug, pub.product_id, pub.published, pub.skipped, len(keep))


def _record(ledger, outcome: "StageOutcome", status: str) -> None:
    """Persist a design outcome to the run ledger (skips blank dedupe placeholders)."""
    if not outcome.slug:
        return
    ledger.record(ledger_mod.DesignRecord(
        slug=outcome.slug, topic=outcome.topic, title=outcome.title,
        screened_ok=outcome.screened_ok, publish_status=status,
        product_id=outcome.product_id,
    ))


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Run the pod-autopilot pipeline for a seed niche.")
    ap.add_argument("--seed", required=True)
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--auto-publish", action="store_true",
                    help="actually publish to Etsy via Printify (default: review-first)")
    args = ap.parse_args()

    s = run(args.seed, count=args.count, auto_publish=args.auto_publish)
    print(json.dumps(s.as_dict(), indent=2))
