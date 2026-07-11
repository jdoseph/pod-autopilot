"""Runner tests — multi-seed aggregation, review-first default, error isolation.

Offline (mock cfg + autouse no_network fixture)."""

from __future__ import annotations

import dataclasses

import pytest

from pod_autopilot import runner, pipeline


def test_run_all_aggregates_across_seeds(mock_cfg):
    report = runner.run_all(["cottagecore", "boho"], cap=2, auto_publish=False, cfg=mock_cfg)
    assert report.seeds == ["cottagecore", "boho"]
    assert report.staged == 4          # 2 seeds x 2 designs, review-first
    assert report.published == 0
    assert report.errors == 0
    assert set(report.per_seed) == {"cottagecore", "boho"}


def test_run_all_is_review_first_by_default(mock_cfg):
    report = runner.run_all(["cottagecore"], cap=2, auto_publish=False, cfg=mock_cfg)
    assert report.published == 0
    assert report.staged == 2


def test_run_all_auto_publish_goes_through_publish_path(mock_cfg):
    # mock variant costs clear the floor; auto-publish uses the no-op client.
    report = runner.run_all(["cottagecore"], cap=1, auto_publish=True, cfg=mock_cfg)
    # mock publish returns published=False (dry-run), so these land as staged,
    # but crucially they went through create_and_publish without error.
    assert report.errors == 0
    assert report.per_seed["cottagecore"]  # recorded


def test_run_all_isolates_seed_errors(mock_cfg, monkeypatch):
    calls = {"n": 0}
    real_run = pipeline.run

    def flaky(seed, *a, **k):
        calls["n"] += 1
        if seed == "boom":
            raise RuntimeError("kaboom")
        return real_run(seed, *a, **k)

    monkeypatch.setattr(pipeline, "run", flaky)
    report = runner.run_all(["cottagecore", "boom", "boho"], cap=1,
                            auto_publish=False, cfg=mock_cfg)
    assert report.errors == 1
    assert report.per_seed["boom"] == {"error": True}
    # the other two still ran
    assert report.per_seed["cottagecore"]["staged"] == 1
    assert report.per_seed["boho"]["staged"] == 1


def test_main_requires_seeds(monkeypatch, mock_cfg):
    # No --seeds and empty SEEDS in cfg -> exit code 2.
    monkeypatch.setattr(runner.config, "load", lambda: dataclasses.replace(mock_cfg, seeds=()))
    rc = runner.main(["--cap", "1"])
    assert rc == 2


def test_main_uses_cli_seeds_and_reports(monkeypatch, mock_cfg, capsys):
    monkeypatch.setattr(runner.config, "load", lambda: mock_cfg)
    rc = runner.main(["--seeds", "cottagecore", "--cap", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"published": 0' in out
    assert "cottagecore" in out


def test_main_auto_publish_flag_overrides_env(monkeypatch, mock_cfg):
    captured = {}
    monkeypatch.setattr(runner.config, "load", lambda: mock_cfg)

    def spy(seeds, cap, *, auto_publish, cfg=None):
        captured["auto_publish"] = auto_publish
        return runner.RunReport(seeds=seeds, auto_publish=auto_publish)

    monkeypatch.setattr(runner, "run_all", spy)
    runner.main(["--seeds", "x", "--auto-publish"])
    assert captured["auto_publish"] is True
