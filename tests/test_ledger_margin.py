"""Tests for the run ledger (dedupe) and the margin floor. No network."""

from __future__ import annotations

import dataclasses

from pod_autopilot import ledger as ledger_mod
from pod_autopilot import pipeline
from pod_autopilot import printify_client


# --- run ledger dedupe ------------------------------------------------------

def test_ledger_records_and_dedupes_topic_title_slug(tmp_path):
    with ledger_mod.RunLedger(tmp_path / "run.db") as led:
        assert led.seen_slug("cozy-frog") is False
        led.record(ledger_mod.DesignRecord(
            slug="cozy-frog", topic="Cottagecore Frogs", title="Cozy Frog Tee",
            screened_ok=True, publish_status="staged",
        ))
        assert led.seen_slug("cozy-frog") is True
        # normalized topic/title dedupe (case + whitespace insensitive).
        assert led.seen_topic("cottagecore  frogs") is True
        assert led.seen_title("COZY FROG TEE") is True
        assert led.seen_topic("something else") is False


def test_ledger_persists_across_connections(tmp_path):
    db = tmp_path / "run.db"
    with ledger_mod.RunLedger(db) as led:
        led.record(ledger_mod.DesignRecord(
            slug="s1", topic="t1", title="T1", screened_ok=True,
            publish_status="published", product_id="p1",
        ))
    with ledger_mod.RunLedger(db) as led2:
        assert led2.seen_slug("s1") is True
        rows = led2.all_records()
        assert rows[0]["product_id"] == "p1"
        assert rows[0]["publish_status"] == "published"


def test_ledger_upsert_updates_status(tmp_path):
    with ledger_mod.RunLedger(tmp_path / "run.db") as led:
        rec = ledger_mod.DesignRecord(slug="s", topic="t", title="T",
                                      screened_ok=True, publish_status="staged")
        led.record(rec)
        rec.publish_status = "published"
        rec.product_id = "prod-9"
        led.record(rec)
        rows = led.all_records()
        assert len(rows) == 1  # upsert, not duplicate
        assert rows[0]["publish_status"] == "published"
        assert rows[0]["product_id"] == "prod-9"


def test_pipeline_second_run_dedupes_topics(mock_cfg):
    # First run stages designs; second run over the same seed must skip the topics.
    first = pipeline.run("cottagecore", count=2, auto_publish=False, cfg=mock_cfg)
    assert first.staged == 2 and first.skipped == 0

    second = pipeline.run("cottagecore", count=2, auto_publish=False, cfg=mock_cfg)
    assert second.staged == 0
    assert second.skipped == 2
    assert all("already used" in o.skipped_reason for o in second.outcomes)


# --- margin math ------------------------------------------------------------

def test_variant_margin_math():
    assert pipeline.variant_margin(2499, 1050) == (2499 - 1050) / 2499
    assert pipeline.variant_margin(0, 1000) == 0.0        # guard div-by-zero
    assert pipeline.variant_margin(1000, 1200) < 0        # underwater


def test_profitable_variants_filters_by_floor(mock_cfg):
    client = printify_client.PrintifyClient(mock_cfg)
    # mock cost = 1000 + (vid % 5) * 50. Retail 2499c.
    # vid 11 -> 1050 -> 58%; vid 12 -> 1100 -> 56%; vid 13 -> 1150 -> 54%.
    keep, skips = pipeline.profitable_variants(client, [11, 12, 13], 2499, 0.55)
    assert keep == [11, 12]            # 54% one is dropped
    assert len(skips) == 1 and "variant 13" in skips[0]


def test_margin_floor_blocks_publish_when_all_underwater(mock_cfg):
    cfg = dataclasses.replace(mock_cfg, min_margin=0.99)  # nothing clears 99%
    summary = pipeline.run("boho", count=1, auto_publish=True, cfg=cfg)
    assert summary.published == 0
    assert summary.skipped == 1
    assert "margin floor" in summary.outcomes[-1].skipped_reason


def test_publish_skipped_when_no_variants_configured(mock_cfg):
    cfg = dataclasses.replace(mock_cfg, printify_variant_ids=())
    summary = pipeline.run("boho", count=1, auto_publish=True, cfg=cfg)
    assert summary.published == 0
    assert summary.skipped == 1
    assert "no variants configured" in summary.outcomes[-1].skipped_reason


# --- disclosure survives to publish ----------------------------------------

def test_disclosure_present_in_published_description(mock_cfg, monkeypatch):
    # Capture what the client is asked to publish; assert the disclosure is in it.
    captured = {}
    orig = printify_client.PrintifyClient.create_and_publish

    def spy(self, *, slug, title, description, **kw):
        captured["description"] = description
        return orig(self, slug=slug, title=title, description=description, **kw)

    monkeypatch.setattr(printify_client.PrintifyClient, "create_and_publish", spy)
    pipeline.run("cottagecore", count=1, auto_publish=True, cfg=mock_cfg)
    assert pipeline.DISCLOSURE in captured["description"]
