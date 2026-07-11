"""Trend parsing tests — CSV parsing and mock source. No network."""

from __future__ import annotations

import pytest

from pod_autopilot import trends


def test_mock_source_is_deterministic_and_ranked(mock_cfg):
    a = trends.fetch("cottagecore", count=3, cfg=mock_cfg)
    b = trends.fetch("cottagecore", count=3, cfg=mock_cfg)
    assert [t.topic for t in a] == [t.topic for t in b]  # deterministic
    assert len(a) == 3
    assert all(t.source == "mock" for t in a)
    scores = [t.score for t in a]
    assert scores == sorted(scores, reverse=True)  # ranked desc


def test_from_csv_parses_and_ranks(tmp_path):
    csv_path = tmp_path / "kw.csv"
    csv_path.write_text(
        "Keyword,Volume\n"
        "cottage frog tee,1200\n"
        "mushroom shirt,9800\n"
        "wildflower top,4500\n",
        encoding="utf-8",
    )
    result = trends.from_csv(csv_path, seed="cottagecore", count=10)
    assert [t.topic for t in result] == ["mushroom shirt", "wildflower top", "cottage frog tee"]
    assert result[0].score == 9800.0
    assert all(t.source == "csv" for t in result)


def test_from_csv_alternate_headers_and_count_cap(tmp_path):
    csv_path = tmp_path / "kw2.csv"
    # 'query'/'searches' column aliases, commas in numbers.
    csv_path.write_text(
        "query,searches\nretro sunset,\"1,000\"\nmoth moon,\"2,500\"\n",
        encoding="utf-8",
    )
    result = trends.from_csv(csv_path, count=1)
    assert len(result) == 1
    assert result[0].topic == "moth moon"
    assert result[0].score == 2500.0


def test_from_csv_missing_topic_column_raises(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        trends.from_csv(csv_path)


def test_from_csv_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        trends.from_csv(tmp_path / "nope.csv")
