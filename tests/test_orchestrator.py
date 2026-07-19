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
    monkeypatch.setattr(orchestrator.printify_client, "shop_ids_by_channel",
                        lambda: {"shopify": 1})
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
    monkeypatch.setattr(orchestrator.design, "remove_background", lambda p: True)
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
    assert rec["products"] == {"shopify": "prod1"}
    assert rec["image_verdict"]["approved"] is True


def test_daily_run_skips_when_budget_paused(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator, "RUN_DIR", tmp_path)
    monkeypatch.setattr(orchestrator.budget, "publishing_allowed",
                        lambda: (False, "paused"))
    called = []
    monkeypatch.setattr(orchestrator.printify_client, "shop_ids_by_channel",
                        lambda: called.append(1))
    orchestrator.daily_run()
    assert not called  # returns before touching any external API


def test_dual_channel_publishes_etsy_copy_with_disclosure(monkeypatch, tmp_path):
    """With Etsy connected: both channels get a product, the Etsy one carries
    the mandatory AI disclosure + a listing fee, the Shopify one stays clean."""
    concept = {"niche": "n", "product_type": "t-shirt", "concept": "c",
               "audience": "a", "score": 8.0, "rationale": "r"}
    created, published, fees = [], [], []

    monkeypatch.delenv("DISCLOSE_AI", raising=False)
    monkeypatch.setattr(orchestrator, "RUN_DIR", tmp_path)
    monkeypatch.setattr(orchestrator, "APPROVAL_MODE", "auto")
    monkeypatch.setattr(orchestrator.budget, "publishing_allowed", lambda: (True, "ok"))
    monkeypatch.setattr(orchestrator.budget, "record_listing_fee",
                        lambda: fees.append(1))
    monkeypatch.setattr(orchestrator.budget, "month_spend", lambda: 0.0)
    monkeypatch.setattr(orchestrator.budget, "month_revenue", lambda: 0.0)
    monkeypatch.setattr(orchestrator.printify_client, "shop_ids_by_channel",
                        lambda: {"shopify": 1, "etsy": 2})
    monkeypatch.setattr(orchestrator.printify_client, "upload_image", lambda p: "img1")

    def fake_create(shop, image_id, ptype, title, description, price, tags, **kw):
        created.append({"shop": shop, "description": description, "tags": tags})
        return {"id": f"prod-shop{shop}", "images": []}

    monkeypatch.setattr(orchestrator.printify_client, "create_product", fake_create)
    monkeypatch.setattr(orchestrator.printify_client, "publish",
                        lambda shop, pid: published.append((shop, pid)))
    monkeypatch.setattr(orchestrator.research, "generate_concepts",
                        lambda per_type=3: [concept])
    monkeypatch.setattr(orchestrator.design, "write_design_prompt",
                        lambda c: {"image_prompt": "p", "text_on_design": None,
                                   "style": "s"})
    monkeypatch.setattr(orchestrator.design, "render",
                        lambda prompt, out, tier, aspect="3:4": out)
    monkeypatch.setattr(orchestrator.design, "remove_background", lambda p: True)
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

    by_shop = {c["shop"]: c for c in created}
    assert orchestrator.listing.AI_DISCLOSURE in by_shop[2]["description"]  # etsy
    assert "AI" not in by_shop[1]["description"]                            # shopify opt-out
    assert sorted(published) == [(1, "prod-shop1"), (2, "prod-shop2")]
    assert fees == [1]   # exactly one Etsy listing fee, none for Shopify
    rec = json.loads((tmp_path / "c00.json").read_text())
    assert rec["products"] == {"shopify": "prod-shop1", "etsy": "prod-shop2"}


def test_approve_all_skips_rejected_and_unconnected(monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator, "RUN_DIR", tmp_path)
    monkeypatch.setattr(orchestrator.printify_client, "shop_ids_by_channel",
                        lambda: {"shopify": 1})
    published = []
    monkeypatch.setattr(orchestrator.printify_client, "publish",
                        lambda shop, pid: published.append((shop, pid)))
    monkeypatch.setattr(orchestrator.budget, "record_listing_fee", lambda: None)
    (tmp_path / "c00.json").write_text(json.dumps(
        {"products": {"shopify": "p1", "etsy": "p2"}, "listing": {"title": "t"}}))
    (tmp_path / "c01.rejected.json").write_text(json.dumps({"reason": "ip"}))
    (tmp_path / "c02.json").write_text(json.dumps(          # legacy single-id record
        {"product_id": "p3", "listing": {"title": "t"}}))
    orchestrator.approve_all()
    assert published == [(1, "p1"), (1, "p3")]   # etsy skipped (not connected), rejected skipped
