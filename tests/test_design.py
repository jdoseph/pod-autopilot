"""design.py tests — Recraft provider path with recorded fixtures, no live API.

Two layers:
  - `_finalize_png` directly (pure image processing): alpha promotion + upscale.
  - the full `generate_design` non-mock path with requests.post/get monkeypatched
    to return fixture bytes (never touches the network; the autouse no_network
    fixture would fail the test if it tried).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pod_autopilot import config, design

FIXTURES = Path(__file__).parent / "fixtures"
OPAQUE_PNG = (FIXTURES / "recraft_sample.png").read_bytes()
RGBA_PNG = (FIXTURES / "recraft_sample_rgba.png").read_bytes()


def _recraft_cfg(tmp_path):
    return config.Config(
        image_provider="recraft",
        image_api_key="test-key",
        output_dir=tmp_path / "output",
    )


# --- _finalize_png (pure, no network) --------------------------------------

def test_finalize_promotes_opaque_to_alpha_and_upscales(tmp_path):
    out = tmp_path / "art.png"
    d = design._finalize_png(OPAQUE_PNG, out, prompt="mushroom")
    assert d.has_alpha is True
    assert d.long_edge >= design.LONG_EDGE_MIN
    # square in -> square out, exactly the threshold on the long edge.
    assert d.width == design.LONG_EDGE_MIN and d.height == design.LONG_EDGE_MIN
    # And it passes the independent validator.
    design.validate_png(out)


def test_finalize_preserves_existing_alpha(tmp_path):
    out = tmp_path / "art.png"
    d = design._finalize_png(RGBA_PNG, out, prompt="frog")
    assert d.has_alpha is True
    assert d.long_edge >= design.LONG_EDGE_MIN
    design.validate_png(out)


# --- transparent-prompt helper ---------------------------------------------

def test_transparent_prompt_appends_once():
    once = design._transparent_prompt("a cozy mushroom")
    assert "transparent background" in once
    # idempotent: don't double-append if caller already asked for it.
    assert design._transparent_prompt(once) == once


# --- full generate_design non-mock path, monkeypatched HTTP -----------------

class _FakeResp:
    def __init__(self, *, status=200, json_data=None, content=b"", headers=None):
        self.status_code = status
        self._json = json_data
        self.content = content
        self.headers = headers or {}
        self.text = ""

    def json(self):
        return self._json


def test_generate_design_recraft_path(monkeypatch, tmp_path):
    cfg = _recraft_cfg(tmp_path)
    calls = {"post": 0, "get": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["post"] += 1
        assert "Bearer test-key" == headers["Authorization"]
        assert "transparent background" in json["prompt"]
        return _FakeResp(json_data={"data": [{"url": "https://img.example/x.png"}]})

    def fake_get(url, headers=None, timeout=None):
        calls["get"] += 1
        return _FakeResp(content=OPAQUE_PNG)

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "get", fake_get)

    out = tmp_path / "out" / "art.png"
    d = design.generate_design("a whimsical mushroom", out, cfg=cfg)

    assert calls == {"post": 1, "get": 1}
    assert d.has_alpha and d.long_edge >= design.LONG_EDGE_MIN
    assert Path(out).exists()


def test_generate_design_retries_on_500_then_succeeds(monkeypatch, tmp_path):
    cfg = _recraft_cfg(tmp_path)
    monkeypatch.setattr(design, "_sleep_backoff", lambda *a, **k: None)  # no real sleep
    seq = [_FakeResp(status=500), _FakeResp(status=200, json_data={"data": [{"url": "u"}]})]

    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResp(content=OPAQUE_PNG))

    d = design.generate_design("mushroom", tmp_path / "art.png", cfg=cfg)
    assert d.long_edge >= design.LONG_EDGE_MIN
    assert seq == []  # both responses consumed (one retry)


def test_generate_design_fails_fast_on_400(monkeypatch, tmp_path):
    cfg = _recraft_cfg(tmp_path)
    import requests

    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: _FakeResp(status=400, headers={}))
    with pytest.raises(design.DesignError):
        design.generate_design("bad", tmp_path / "art.png", cfg=cfg)


def test_real_provider_rejects_unknown_provider(tmp_path):
    cfg = config.Config(image_provider="", image_api_key="k", output_dir=tmp_path)
    with pytest.raises(design.DesignError):
        design.generate_design("x", tmp_path / "art.png", cfg=cfg)


def test_missing_api_key_raises(monkeypatch, tmp_path):
    cfg = config.Config(image_provider="recraft", image_api_key="", output_dir=tmp_path)
    with pytest.raises(design.DesignError):
        design.generate_design("x", tmp_path / "art.png", cfg=cfg)
