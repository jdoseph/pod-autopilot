import pytest

from src import ip_check

CONCEPT = {"concept": "Minimalist mountain sunrise", "product_type": "poster"}


def test_uspto_disabled_by_default(monkeypatch):
    monkeypatch.delenv("USPTO_SEARCH_URL", raising=False)
    assert ip_check.uspto_hits("any phrase") is None


def test_uspto_fails_open(monkeypatch):
    monkeypatch.setenv("USPTO_SEARCH_URL", "https://example.invalid/search")
    monkeypatch.setattr(ip_check.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert ip_check.uspto_hits("any phrase") is None


@pytest.mark.parametrize("approved,risk,expect", [
    (True, "low", True),
    (True, "medium", False),   # approved but not low risk -> rejected
    (False, "low", False),
])
def test_screen_requires_low_risk(monkeypatch, approved, risk, expect):
    monkeypatch.delenv("USPTO_SEARCH_URL", raising=False)
    monkeypatch.setattr(ip_check, "ask_json", lambda *a, **k: {
        "approved": approved, "risk_level": risk, "reason": "r"})
    assert ip_check.screen(CONCEPT, None)["approved"] is expect


def test_screen_image_strips_fences(monkeypatch, tmp_path):
    png = tmp_path / "x.png"
    png.write_bytes(b"fake")
    monkeypatch.setattr(ip_check, "ask_vision", lambda *a, **k:
                        '```json\n{"approved": true, "risk_level": "low", "reason": "ok"}\n```')
    v = ip_check.screen_image(str(png))
    assert v["approved"] is True
