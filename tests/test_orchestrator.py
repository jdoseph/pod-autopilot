import json

from src import orchestrator


def test_daily_run_end_to_end_mocked(monkeypatch, tmp_path):
    concept = {"niche": "n", "product_type": "t-shirt", "concept": "c",
               "audience": "a", "score": 8.0, "rationale": "r"}
    published = []

    monkeypatch.setattr(orchestrator, "RUN_DIR", tmp_path)
    monkeypatch.setattr(orchestrator, "APPROVAL_MODE", "auto")
    monkeypatch.setattr(orchestrator.budget, "publishing_allowed", lambda: (True, "ok"))
    monkeypatch.setattr(orchestrator.budget, "record_listing_fee", lambda: None)
    monkeypatch.setattr(orchestrator.budget, "month_spend", lambda: 0.0)
    monkeypatch.setattr(orchestrator.budget, "month_revenue", lambda: 0.0)
    monkeypatch.setattr(orchestrator.printify_client, "shop_id", lambda: 1)
    monkeypatch.setattr(orchestrator.printify_client, "upload_image", lambda p: "img1")
    monkeypatch.setattr(orchestrator.printify_client, "create_product",
                        lambda *a, **k: {"id": "prod1", "images": []})
    monkeypatch.setattr(orchestrator.printify_client, "publish",
                        lambda shop, pid: published.append(pid))
    monkeypatch.setattr(orchestrator.research, "generate_concepts",
                        lambda per_type=3: [concept])
    monkeypatch.setattr(orchestrator.design, "write_design_prompt",
                        lambda c: {"image_prompt": "p", "text_on_design": None,
                                   "style": "s"})
    monkeypatch.setattr(orchestrator.design, "render",
                        lambda prompt, out, tier, aspect="3:4": out)
    monkeypatch.setattr(orchestrator.ip_check, "screen",
                        lambda c, t: {"approved": True, "risk_level": "low", "reason": ""})
    monkeypatch.setattr(orchestrator.ip_check, "screen_image",
                        lambda p, expected_text=None: {
                            "approved": True, "risk_level": "low", "reason": ""})
    monkeypatch.setattr(orchestrator.listing, "write_listings_bulk",
                        lambda cs: [{"index": 0, "title": "T", "tags": ["x"],
                                     "description": "d"}])
    monkeypatch.setattr(orchestrator.marketing, "enabled", lambda: False)

    orchestrator.daily_run()

    assert published == ["prod1"]
    rec = json.loads((tmp_path / "c00.json").read_text())
    assert rec["product_id"] == "prod1"
    assert rec["image_verdict"]["approved"] is True


def test_daily_run_skips_when_budget_paused(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator, "RUN_DIR", tmp_path)
    monkeypatch.setattr(orchestrator.budget, "publishing_allowed",
                        lambda: (False, "paused"))
    called = []
    monkeypatch.setattr(orchestrator.printify_client, "shop_id",
                        lambda: called.append(1))
    orchestrator.daily_run()
    assert not called  # returns before touching any external API
