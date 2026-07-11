"""Scheduled runner — process a list of seed niches on a cadence.

Wraps pipeline.run over several seeds with a per-run cap, structured logging, and
an aggregate run summary (published / staged / skipped) emitted at the end. This is
the entrypoint a scheduler (Windows Task Scheduler, cron, etc.) invokes.

REVIEW-FIRST by default. Scheduled runs publish to Etsy ONLY when auto-publish is
explicitly enabled — via the AUTO_PUBLISH env flag or the --auto-publish CLI flag.

    # one-off, review-first:
    python -m pod_autopilot.runner --seeds "cottagecore,boho" --cap 3
    # from env (SEEDS, PER_RUN_CAP, AUTO_PUBLISH) — how the scheduler calls it:
    python -m pod_autopilot.runner
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field

from . import config, pipeline

logger = logging.getLogger("pod_autopilot.runner")


@dataclass
class RunReport:
    seeds: list[str] = field(default_factory=list)
    auto_publish: bool = False
    published: int = 0
    staged: int = 0
    skipped: int = 0
    errors: int = 0
    per_seed: dict[str, dict] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "seeds": self.seeds,
            "auto_publish": self.auto_publish,
            "totals": {
                "published": self.published, "staged": self.staged,
                "skipped": self.skipped, "errors": self.errors,
            },
            "per_seed": self.per_seed,
        }


def run_all(
    seeds: list[str],
    cap: int,
    *,
    auto_publish: bool,
    cfg: config.Config | None = None,
) -> RunReport:
    """Run the pipeline for each seed; aggregate a report. One seed failing does
    not abort the others."""
    cfg = cfg or config.load()
    report = RunReport(seeds=list(seeds), auto_publish=auto_publish)

    logger.info("runner start: %d seed(s), cap=%d, auto_publish=%s, mock=%s",
                len(seeds), cap, auto_publish, cfg.mock)

    for seed in seeds:
        try:
            summary = pipeline.run(seed, count=cap, auto_publish=auto_publish, cfg=cfg)
        except Exception:
            report.errors += 1
            report.per_seed[seed] = {"error": True}
            logger.exception("seed %r failed", seed)
            continue

        report.published += summary.published
        report.staged += summary.staged
        report.skipped += summary.skipped
        report.per_seed[seed] = {
            "published": summary.published,
            "staged": summary.staged,
            "skipped": summary.skipped,
        }
        logger.info("seed %r done: published=%d staged=%d skipped=%d",
                    seed, summary.published, summary.staged, summary.skipped)

    logger.info(
        "runner summary: seeds=%d published=%d staged=%d skipped=%d errors=%d",
        len(seeds), report.published, report.staged, report.skipped, report.errors,
    )
    return report


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    cfg = config.load()

    ap = argparse.ArgumentParser(description="Scheduled pod-autopilot runner.")
    ap.add_argument("--seeds", help="comma-separated seed niches (overrides SEEDS env)")
    ap.add_argument("--cap", type=int, help="max designs per seed (overrides PER_RUN_CAP)")
    ap.add_argument("--auto-publish", action="store_true",
                    help="publish to Etsy (default review-first; also settable via AUTO_PUBLISH)")
    args = ap.parse_args(argv)

    seeds = (
        [s.strip() for s in args.seeds.split(",") if s.strip()]
        if args.seeds else list(cfg.seeds)
    )
    if not seeds:
        logger.error("no seeds provided (use --seeds or set SEEDS in .env)")
        return 2

    cap = args.cap if args.cap is not None else cfg.per_run_cap
    auto_publish = args.auto_publish or cfg.auto_publish

    report = run_all(seeds, cap, auto_publish=auto_publish, cfg=cfg)
    # Machine-readable summary on stdout for the scheduler/log to capture.
    print(json.dumps(report.as_dict(), indent=2))
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
