"""Screening gate tests — clean passes, infringing blocked. No network."""

from __future__ import annotations

from types import SimpleNamespace

from pod_autopilot import screening


def _concept(title, description="", image_prompt="", tags=None):
    return SimpleNamespace(
        title=title, description=description,
        image_prompt=image_prompt, tags=tags or [],
    )


def test_clean_concept_passes():
    c = _concept(
        "Whimsical Mushroom Cottage Tee",
        description="An original hand-drawn design.",
        image_prompt="mushrooms, wildflowers, muted earth tones, transparent bg",
        tags=["cottagecore", "botanical", "original art"],
    )
    result = screening.screen(c)
    assert result.passed is True
    assert result.matched_terms == []


def test_infringing_title_blocked():
    c = _concept("Just Do It Nike Swoosh Tee", tags=["nike"])
    result = screening.screen(c)
    assert result.passed is False
    assert "nike" in result.matched_terms
    assert "just do it" in result.matched_terms


def test_blocked_term_in_tags_only():
    c = _concept("A perfectly nice title", tags=["pokemon", "cute"])
    result = screening.screen(c)
    assert result.passed is False
    assert "pokemon" in result.matched_terms


def test_blocked_term_in_image_prompt():
    c = _concept("Nice title", image_prompt="mickey mouse in a field")
    result = screening.screen(c)
    assert result.passed is False
    assert "mickey mouse" in result.matched_terms


def test_word_boundary_avoids_false_positive():
    # "apple" is blocked, but "pineapple" / "grapple" must not trip it.
    c = _concept("Pineapple Grapple Tee", image_prompt="a ripe pineapple")
    result = screening.screen(c)
    assert result.passed is True


def test_trademark_symbol_blocked():
    c = _concept("Cool Brand™ Tee")  # ™
    result = screening.screen(c)
    assert result.passed is False


def test_uspto_disabled_does_not_block_clean_concept():
    # use_uspto=True but no endpoint configured -> fail OPEN (does not block).
    c = _concept("Whimsical Mushroom Tee")
    result = screening.screen(c, use_uspto=True)
    assert result.passed is True
    assert any("USPTO" in r for r in result.reasons)


# --- fuzzy matcher ---------------------------------------------------------

import pytest  # noqa: E402
from pod_autopilot import config  # noqa: E402


@pytest.fixture
def matcher():
    return screening._Matcher(screening.load_blocklist())


@pytest.mark.parametrize("text,expected", [
    ("nike", "nike"),
    ("N I K E", "nike"),          # spacing
    ("n1ke", "nike"),            # leetspeak
    ("N.I.K.E", "nike"),        # punctuation
    ("swooshes", "swoosh"),     # plural
    ("taylorswift", "taylor swift"),   # removed space
    ("justdoit", "just do it"),
    ("d1sney world", "disney"),
])
def test_fuzzy_catches_evasions(matcher, text, expected):
    assert expected in matcher.find(text)


@pytest.mark.parametrize("text", [
    "pineapple", "grapple", "snapple",     # must not trip "apple"
    "cottagecore mushroom aesthetic",
    "a whimsical botanical wildflower tee",
])
def test_fuzzy_no_false_positives(matcher, text):
    assert matcher.find(text) == []


def test_blocklist_loads_categories():
    terms = screening.load_blocklist()
    # a megabrand, a slogan, a character, and a niche-seed term all present.
    for expected in ("nike", "just do it", "pikachu", "crossfit"):
        assert expected in terms


# --- USPTO fail-open / fail-closed -----------------------------------------

def _uspto_cfg(tmp_path, url="https://uspto.example/search"):
    return config.Config(uspto_search_url=url, uspto_api_key="k", output_dir=tmp_path / "o")


class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}

    def json(self):
        return self._data


def test_uspto_fail_closed_on_live_match(monkeypatch, tmp_path):
    cfg = _uspto_cfg(tmp_path)
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: _Resp(data={"results": [{"status": "LIVE"}]}))
    c = _concept("Some Original Phrase")
    result = screening.screen(c, use_uspto=True, cfg=cfg, log_rejections=False)
    assert result.passed is False
    assert any("USPTO live mark" in r for r in result.reasons)


def test_uspto_clean_when_no_live_match(monkeypatch, tmp_path):
    cfg = _uspto_cfg(tmp_path)
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: _Resp(data={"results": [{"status": "DEAD"}]}))
    c = _concept("Some Original Phrase")
    result = screening.screen(c, use_uspto=True, cfg=cfg, log_rejections=False)
    assert result.passed is True


def test_uspto_fail_open_on_network_error(monkeypatch, tmp_path):
    cfg = _uspto_cfg(tmp_path)
    import requests

    def boom(*a, **k):
        raise requests.RequestException("connection reset")

    monkeypatch.setattr(requests, "get", boom)
    c = _concept("Some Original Phrase")
    result = screening.screen(c, use_uspto=True, cfg=cfg, log_rejections=False)
    # network error must NOT block (fail open).
    assert result.passed is True
    assert any("inconclusive" in r for r in result.reasons)


def test_uspto_fail_open_on_http_500(monkeypatch, tmp_path):
    cfg = _uspto_cfg(tmp_path)
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(status=500))
    assert screening.uspto_live_check("phrase", cfg) is None  # inconclusive -> fail open


def test_uspto_disabled_returns_none(tmp_path):
    cfg = config.Config(uspto_search_url="", output_dir=tmp_path)
    assert screening.uspto_live_check("phrase", cfg) is None


# --- rejection logging -----------------------------------------------------

def test_rejection_is_logged(tmp_path):
    cfg = config.Config(output_dir=tmp_path / "out")
    c = _concept("Nike Swoosh Tee", tags=["nike"])
    result = screening.screen(c, cfg=cfg)
    assert result.passed is False
    log = tmp_path / "out" / "screening_rejections.log"
    assert log.exists()
    contents = log.read_text(encoding="utf-8")
    assert "nike" in contents and "Nike Swoosh Tee" in contents
