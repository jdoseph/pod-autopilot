from src import research


def test_concepts_filtered_and_sorted(monkeypatch):
    monkeypatch.setattr(research, "ask_json", lambda *a, **k: {"concepts": [
        {"concept": "meh", "score": 5.0},
        {"concept": "great", "score": 9.1},
        {"concept": "good", "score": 7.0},
    ]})
    out = research.generate_concepts(n=3)
    assert [c["concept"] for c in out] == ["great", "good"]  # >=7.0 only, ranked
