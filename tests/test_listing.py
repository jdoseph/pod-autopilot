from src import listing

CONCEPTS = [
    {"niche": "beekeeping", "product_type": "t-shirt",
     "concept": "Vintage bee anatomy diagram", "audience": "hobby beekeepers"},
    {"niche": "pottery", "product_type": "mug",
     "concept": "Wheel-thrown clay hands illustration", "audience": "potters"},
]


def test_price_covers_target_margin():
    price = listing.price_for("t-shirt")
    cost = listing.BASE_COST["t-shirt"]
    assert (price - cost) / price >= 0.5
    assert price % 100 == 95  # x.95 psychological pricing


def test_bulk_aligns_and_omits_disclosure_by_default(monkeypatch):
    monkeypatch.delenv("DISCLOSE_AI", raising=False)
    monkeypatch.setattr(listing, "ask_json", lambda *a, **k: {"listings": [
        {"index": 1, "title": "Mug", "tags": ["a"], "description": "About mugs."},
        {"index": 0, "title": "Tee", "tags": ["b"], "description": "About tees."},
    ]})
    out = listing.write_listings_bulk(CONCEPTS)
    assert [l["title"] for l in out] == ["Tee", "Mug"]  # realigned to input order
    assert all("AI" not in l["description"] for l in out)  # owner opt-out


def test_bulk_appends_disclosure_when_enabled(monkeypatch):
    monkeypatch.setenv("DISCLOSE_AI", "1")  # required mode for Etsy targets
    monkeypatch.setattr(listing, "ask_json", lambda *a, **k: {"listings": [
        {"index": 0, "title": "Tee", "tags": ["b"], "description": "About tees."},
        {"index": 1, "title": "Mug", "tags": ["a"], "description": "About mugs."},
    ]})
    out = listing.write_listings_bulk(CONCEPTS)
    assert all(l["description"].endswith(listing.AI_DISCLOSURE) for l in out)


def test_bulk_fallback_when_model_skips_index(monkeypatch):
    monkeypatch.delenv("DISCLOSE_AI", raising=False)
    monkeypatch.setattr(listing, "ask_json", lambda *a, **k: {"listings": [
        {"index": 0, "title": "Tee", "tags": ["b"], "description": "About tees."},
    ]})
    out = listing.write_listings_bulk(CONCEPTS)
    assert len(out) == 2
    assert "pottery" in out[1]["tags"]
    assert "AI" not in out[1]["description"]


def test_empty_input():
    assert listing.write_listings_bulk([]) == []


def test_for_channel_etsy_always_discloses(monkeypatch):
    monkeypatch.delenv("DISCLOSE_AI", raising=False)  # Shopify opt-out active
    copy = {"title": "T", "tags": ["x"], "description": "About tees."}
    out = listing.for_channel(copy, "etsy")
    assert out["description"].endswith(listing.AI_DISCLOSURE)
    assert "AI" not in copy["description"]  # original untouched for Shopify


def test_for_channel_etsy_enforces_limits():
    copy = {"title": "T" * 200,
            "tags": ["a really long tail keyword tag", "short", "SHORT", "", "b"],
            "description": "d" + listing.AI_DISCLOSURE}
    out = listing.for_channel(copy, "etsy")
    assert len(out["title"]) <= listing.ETSY_TITLE_MAX
    assert all(len(t) <= listing.ETSY_TAG_MAX for t in out["tags"])
    assert len(out["tags"]) == len({t.lower() for t in out["tags"]})  # deduped
    assert "" not in out["tags"]
    assert out["description"].count(listing.AI_DISCLOSURE) == 1  # not doubled


def test_for_channel_shopify_passthrough():
    copy = {"title": "T" * 200, "tags": ["x"], "description": "d"}
    assert listing.for_channel(copy, "shopify") is copy
