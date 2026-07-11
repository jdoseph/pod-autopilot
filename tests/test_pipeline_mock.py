"""Full mock pipeline run — offline, produces output/ files, never publishes."""

from __future__ import annotations

from pod_autopilot import pipeline, design


def test_mock_run_stages_designs_without_publishing(mock_cfg):
    summary = pipeline.run("cottagecore", count=2, auto_publish=False, cfg=mock_cfg)

    assert summary.seed == "cottagecore"
    assert summary.staged == 2
    assert summary.published == 0
    assert summary.skipped == 0
    assert len(summary.outcomes) == 2

    for outcome in summary.outcomes:
        assert outcome.screened_ok is True
        assert outcome.published is False
        assert outcome.product_id is None
        # art.png exists, is print-ready, and lives under the temp output dir.
        assert outcome.art_path is not None
        art = design.validate_png(outcome.art_path)
        assert art.has_alpha and art.long_edge >= design.LONG_EDGE_MIN
        # concept.json written alongside, with the required disclosure baked in.
        design_dir = mock_cfg.output_dir / outcome.slug
        concept_json = design_dir / "concept.json"
        assert concept_json.exists()
        assert pipeline.DISCLOSURE in concept_json.read_text(encoding="utf-8")


def test_mock_auto_publish_uses_noop_client(mock_cfg):
    # auto_publish=True in mock mode goes through the no-op Printify client:
    # it must NOT actually publish (dry_run), and must not hit the network
    # (guaranteed by the autouse no_network fixture).
    summary = pipeline.run("cottagecore", count=1, auto_publish=True, cfg=mock_cfg)
    assert len(summary.outcomes) == 1
    outcome = summary.outcomes[0]
    assert outcome.product_id is not None          # a fake id was returned
    assert outcome.published is False              # mock publish is a dry-run
    assert summary.published == 0


def test_disclosure_injection_is_idempotent():
    once = pipeline._with_disclosure("Base description.")
    twice = pipeline._with_disclosure(once)
    assert once == twice
    assert once.count(pipeline.DISCLOSURE) == 1
