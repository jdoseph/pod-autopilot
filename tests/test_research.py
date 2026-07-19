from src import research


def test_concepts_filtered_sorted_and_balanced(monkeypatch):
    monkeypatch.setattr(research, "ask_json", lambda *a, **k: {"concepts": [
        {"concept": "meh mug", "product_type": "mug", "score": 5.0},
        {"concept": "great tee", "product_type": "t-shirt", "score": 9.1},
        {"concept": "spare tee", "product_type": "t-shirt", "score": 8.0},
        {"concept": "good mug", "product_type": "Mug", "score": 7.0},
    ]})
    out = research.generate_concepts(per_type=1)
    # >=7.0 only, ranked, at most one per product type (case-insensitive)
    assert [c["concept"] for c in out] == ["great tee", "good mug"]
