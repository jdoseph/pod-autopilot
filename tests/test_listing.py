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


def test_bulk_appends_disclosure_and_aligns(monkeypatch):
    monkeypatch.setattr(listing, "ask_json", lambda *a, **k: {"listings": [
        {"index": 1, "title": "Mug", "tags": ["a"], "description": "About mugs."},
        {"index": 0, "title": "Tee", "tags": ["b"], "description": "About tees."},
    ]})
    out = listing.write_listings_bulk(CONCEPTS)
    assert [l["title"] for l in out] == ["Tee", "Mug"]  # realigned to input order
    assert all(l["description"].endswith(listing.AI_DISCLOSURE) for l in out)


def test_bulk_fallback_when_model_skips_index(monkeypatch):
    monkeypatch.setattr(listing, "ask_json", lambda *a, **k: {"listings": [
        {"index": 0, "title": "Tee", "tags": ["b"], "description": "About tees."},
    ]})
    out = listing.write_listings_bulk(CONCEPTS)
    assert len(out) == 2
    assert "pottery" in out[1]["tags"]
    assert out[1]["description"].endswith(listing.AI_DISCLOSURE)


def test_empty_input():
    assert listing.write_listings_bulk([]) == []
