"""SQLite run ledger — dedupe topics/titles/designs across runs.

Records every design the pipeline touches (topic, title, slug, screening result,
publish status) so future runs skip already-used topics/titles and never repeat a
design. This is distinct from printify_client.PublishLedger, which handles
publish idempotency for a single slug; this one prevents repeating WORK/topics.

Dedupe is on a normalized form (lowercase, collapsed whitespace) so trivial
variants of a topic/title count as "seen".

Independently runnable:
    python -m pod_autopilot.ledger --path run.db --list
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS designs (
    slug            TEXT PRIMARY KEY,
    topic_norm      TEXT NOT NULL,
    title_norm      TEXT NOT NULL,
    topic           TEXT NOT NULL,
    title           TEXT NOT NULL,
    screened_ok     INTEGER NOT NULL,
    publish_status  TEXT NOT NULL,
    product_id      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topic_norm ON designs(topic_norm);
CREATE INDEX IF NOT EXISTS idx_title_norm ON designs(title_norm);
"""


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DesignRecord:
    slug: str
    topic: str
    title: str
    screened_ok: bool
    publish_status: str          # "staged" | "published" | "skipped"
    product_id: str | None = None


class RunLedger:
    """SQLite-backed ledger. Use as a context manager or call close()."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # -- dedupe queries ----------------------------------------------------

    def seen_slug(self, slug: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM designs WHERE slug = ?", (slug,))
        return cur.fetchone() is not None

    def seen_topic(self, topic: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM designs WHERE topic_norm = ? LIMIT 1", (_norm(topic),)
        )
        return cur.fetchone() is not None

    def seen_title(self, title: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM designs WHERE title_norm = ? LIMIT 1", (_norm(title),)
        )
        return cur.fetchone() is not None

    # -- writes ------------------------------------------------------------

    def record(self, rec: DesignRecord) -> None:
        """Upsert a design record by slug."""
        now = _now()
        self.conn.execute(
            """
            INSERT INTO designs (slug, topic_norm, title_norm, topic, title,
                                 screened_ok, publish_status, product_id,
                                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                topic_norm=excluded.topic_norm,
                title_norm=excluded.title_norm,
                topic=excluded.topic,
                title=excluded.title,
                screened_ok=excluded.screened_ok,
                publish_status=excluded.publish_status,
                product_id=excluded.product_id,
                updated_at=excluded.updated_at
            """,
            (rec.slug, _norm(rec.topic), _norm(rec.title), rec.topic, rec.title,
             int(rec.screened_ok), rec.publish_status, rec.product_id, now, now),
        )
        self.conn.commit()

    # -- inspection --------------------------------------------------------

    def all_records(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM designs ORDER BY created_at"))

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "RunLedger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Inspect the pod-autopilot run ledger.")
    ap.add_argument("--path", required=True)
    ap.add_argument("--list", action="store_true", help="print all recorded designs")
    args = ap.parse_args()

    with RunLedger(args.path) as led:
        if args.list:
            for row in led.all_records():
                print(f"{row['publish_status']:>9}  {row['slug']}  "
                      f"(topic={row['topic']!r}, product={row['product_id']})")
