"""Pipeline orchestrator — wires every stage together.

    seed → trends.fetch → ideation.ideate → screening.screen → design.generate_design
         → printify_client (upload → create → publish)

Default is REVIEW-FIRST: it stages art + copy into output/ and does NOT publish.
Pass --auto-publish to actually publish to Etsy via Printify.

MOCK mode (MOCK=1) makes the whole run offline and deterministic: canned trends,
canned concepts, local solid-color PNGs, and a no-op Printify client.

Open items (see CLAUDE.md "Definition of done" / HANDOFF.md Prompt 5): a SQLite run
ledger to skip repeated topics/titles, automatic Printify disclosure line in every
description, and a margin floor that refuses to publish below a configured minimum.
Those are stubbed/marked below and implemented in later prompts.

    python -m pod_autopilot.pipeline --seed "cottagecore" --count 3
    python -m pod_autopilot.pipeline --seed "cottagecore" --count 3 --auto-publish
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import config, trends, ideation, screening, design, printify_client

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

    for trend in topics:
        # One concept per topic keeps the scaffold simple; ideation can return more.
        concepts = ideation.ideate(trend.topic, count=1, cfg=cfg)
        for concept in concepts:
            slug = concept.slug()
            outcome = StageOutcome(
                topic=trend.topic, title=concept.title, slug=slug, screened_ok=False,
            )

            # --- ban-prevention gate (bias strict) ---
            result = screening.screen(concept)
            if not result.passed:
                outcome.skipped_reason = f"screening blocked: {'; '.join(result.reasons)}"
                summary.skipped += 1
                summary.outcomes.append(outcome)
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

            # TODO(Prompt 5): run-ledger dedupe (skip already-used topic/title) +
            # margin floor (refuse variants below cfg.min_margin) go here.

            if not auto_publish:
                summary.staged += 1
                summary.outcomes.append(outcome)
                logger.info("STAGED %s (review-first; not published)", slug)
                continue

            # --- publish path ---
            image_id = client.upload_image(art_path)
            variant_ids: list[int] = []  # Prompt 5 supplies real variant ids + margin check
            product_id = client.create_product(
                title=concept.title, description=description,
                image_id=image_id, variant_ids=variant_ids, price_cents=price_cents,
            )
            pub = client.publish_product(product_id)
            outcome.product_id = product_id
            outcome.published = pub.published
            summary.published += 1 if pub.published else 0
            summary.staged += 0 if pub.published else 1
            summary.outcomes.append(outcome)
            logger.info("PUBLISHED %s -> product %s (published=%s)", slug, product_id, pub.published)

    logger.info("=== done: published=%d staged=%d skipped=%d ===",
                summary.published, summary.staged, summary.skipped)
    return summary


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
