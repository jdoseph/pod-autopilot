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
    # use_uspto=True but the check is unimplemented -> must fail OPEN (not block).
    c = _concept("Whimsical Mushroom Tee")
    result = screening.screen(c, use_uspto=True)
    assert result.passed is True
    assert any("USPTO" in r for r in result.reasons)
