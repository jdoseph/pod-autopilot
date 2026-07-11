"""Ideation JSON-parsing tests, including malformed responses. No network."""

from __future__ import annotations

import pytest

from pod_autopilot import ideation


def test_parse_clean_response():
    raw = """
    {"concepts": [
      {"title": "Whimsical Mushroom Tee", "image_prompt": "mushrooms, vector",
       "description": "A cozy design.", "tags": ["cottagecore", "mushroom"]}
    ]}
    """
    concepts = ideation.parse_concepts(raw, topic="cottagecore")
    assert len(concepts) == 1
    c = concepts[0]
    assert c.title == "Whimsical Mushroom Tee"
    assert c.tags == ["cottagecore", "mushroom"]
    assert c.topic == "cottagecore"
    assert c.slug() == "whimsical-mushroom-tee"


def test_parse_strips_markdown_fences():
    raw = '```json\n{"concepts":[{"title":"T","image_prompt":"p"}]}\n```'
    concepts = ideation.parse_concepts(raw, topic="x")
    assert concepts[0].title == "T"
    assert concepts[0].tags == []  # missing tags -> empty list, not error


def test_parse_extracts_json_amid_prose():
    raw = 'Sure! Here you go:\n{"concepts":[{"title":"T","image_prompt":"p"}]}\nHope that helps.'
    concepts = ideation.parse_concepts(raw, topic="x")
    assert concepts[0].image_prompt == "p"


def test_malformed_not_json_raises():
    with pytest.raises(ideation.IdeationError):
        ideation.parse_concepts("this is not json at all", topic="x")


def test_malformed_missing_concepts_key_raises():
    with pytest.raises(ideation.IdeationError):
        ideation.parse_concepts('{"items": []}', topic="x")


def test_malformed_empty_concepts_raises():
    with pytest.raises(ideation.IdeationError):
        ideation.parse_concepts('{"concepts": []}', topic="x")


def test_malformed_concept_missing_required_field_raises():
    # image_prompt missing -> reject
    with pytest.raises(ideation.IdeationError):
        ideation.parse_concepts('{"concepts":[{"title":"only title"}]}', topic="x")


def test_mock_ideation_offline(mock_cfg):
    concepts = ideation.ideate("cottagecore mushroom", count=2, cfg=mock_cfg)
    assert len(concepts) == 2
    assert all(c.title and c.image_prompt for c in concepts)
    assert all(c.topic == "cottagecore mushroom" for c in concepts)
