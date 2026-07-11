"""Printify client hardening tests — mocked HTTP, no network.

We inject a fake requests.Session onto the client so no real socket is used
(the autouse no_network fixture would also fail any real attempt). Covers:
retry/backoff on 429+5xx, Retry-After, fail-fast on 4xx with body, idempotent
publish via the ledger, and mockup download/save.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pod_autopilot import config, printify_client as pc


# --- fake HTTP plumbing -----------------------------------------------------

class FakeResp:
    def __init__(self, status=200, json_data=None, content=b"", headers=None, text=""):
        self.status_code = status
        self._json = json_data if json_data is not None else {}
        # _request returns .json() only when .content is truthy; mirror a real
        # JSON response having a body so json_data isn't silently dropped.
        if json_data is not None and not content:
            content = b"{}"
        self.content = content
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json


class FakeSession:
    """Returns queued responses in order; records calls."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self._responses:
            raise AssertionError(f"unexpected extra request: {method} {url}")
        return self._responses.pop(0)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)


def _client(tmp_path, responses, *, mock=False):
    cfg = config.Config(
        printify_api_token="t", printify_shop_id="99",
        printify_blueprint_id=1, printify_print_provider_id=2,
        output_dir=tmp_path / "output",
    )
    client = pc.PrintifyClient(cfg, mock=mock, ledger_path=tmp_path / "ledger.json")
    client._session = FakeSession(responses)
    return client


# --- retry / backoff --------------------------------------------------------

def test_retry_on_500_then_success(tmp_path, monkeypatch):
    monkeypatch.setattr(pc.PrintifyClient, "_sleep_backoff", staticmethod(lambda *a, **k: None))
    client = _client(tmp_path, [
        FakeResp(status=500, text="boom"),
        FakeResp(status=200, json_data={"id": "abc"}),
    ])
    out = client._request("GET", "/anything.json")
    assert out == {"id": "abc"}
    assert len(client._session.calls) == 2  # one retry


def test_retry_on_429_respects_retry_after(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(pc.PrintifyClient, "_sleep_backoff",
                        staticmethod(lambda attempt, retry_after=None: slept.append(retry_after)))
    client = _client(tmp_path, [
        FakeResp(status=429, headers={"Retry-After": "7"}, text="slow down"),
        FakeResp(status=200, json_data={"ok": True}),
    ])
    client._session = client._session  # keep fake
    assert client._request("GET", "/x.json") == {"ok": True}
    assert slept == ["7"]  # Retry-After was passed through


def test_4xx_fails_fast_with_body(tmp_path):
    client = _client(tmp_path, [FakeResp(status=422, text='{"error":"bad variant"}')])
    with pytest.raises(pc.PrintifyError) as exc:
        client._request("POST", "/products.json", json={})
    assert exc.value.status == 422
    assert "bad variant" in (exc.value.body or "")
    assert len(client._session.calls) == 1  # no retry on 422


def test_exhausted_retries_raises_last_error(tmp_path, monkeypatch):
    monkeypatch.setattr(pc.PrintifyClient, "_sleep_backoff", staticmethod(lambda *a, **k: None))
    client = _client(tmp_path, [FakeResp(status=503, text="down")] * pc._MAX_RETRIES)
    with pytest.raises(pc.PrintifyError) as exc:
        client._request("GET", "/x.json")
    assert exc.value.status == 503


# --- idempotent publish -----------------------------------------------------

def test_create_and_publish_records_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(pc.PrintifyClient, "_sleep_backoff", staticmethod(lambda *a, **k: None))
    client = _client(tmp_path, [
        FakeResp(status=200, json_data={"id": "prod-1"}),       # create_product
        FakeResp(status=200, json_data={}),                     # publish
        FakeResp(status=200, json_data={"images": [{"src": "http://m/1.png"}]}),  # fetch mockups
        FakeResp(status=200, content=b"PNGBYTES"),              # download mockup_0
    ])
    result = client.create_and_publish(
        slug="cozy-frog", title="Cozy Frog", description="d",
        image_id="img-1", variant_ids=[10], price_cents=2499, mockup_dir=tmp_path / "art",
    )
    assert result.product_id == "prod-1"
    assert result.published is True
    assert result.skipped is False
    assert result.saved_mockups == [str(tmp_path / "art" / "mockup_0.png")]
    assert (tmp_path / "art" / "mockup_0.png").read_bytes() == b"PNGBYTES"
    # Ledger persisted as published.
    led = json.loads((tmp_path / "ledger.json").read_text())
    assert led["cozy-frog"] == {"product_id": "prod-1", "published": True}


def test_re_publish_is_skipped_no_duplicate(tmp_path):
    # Pre-seed the ledger as already published.
    (tmp_path / "ledger.json").write_text(
        json.dumps({"cozy-frog": {"product_id": "prod-1", "published": True}})
    )
    # No responses queued: if it tried to create/publish, FakeSession would raise.
    client = _client(tmp_path, [])
    result = client.create_and_publish(
        slug="cozy-frog", title="Cozy Frog", description="d",
        image_id="img-1", variant_ids=[10], price_cents=2499,
    )
    assert result.skipped is True
    assert result.published is True
    assert result.product_id == "prod-1"
    assert client._session.calls == []  # nothing sent


def test_reuses_created_but_unpublished_product(tmp_path, monkeypatch):
    monkeypatch.setattr(pc.PrintifyClient, "_sleep_backoff", staticmethod(lambda *a, **k: None))
    (tmp_path / "ledger.json").write_text(
        json.dumps({"cozy-frog": {"product_id": "prod-1", "published": False}})
    )
    client = _client(tmp_path, [
        FakeResp(status=200, json_data={}),                                  # publish
        FakeResp(status=200, json_data={"images": [{"src": "http://m/1.png"}]}),  # mockups
    ])
    result = client.create_and_publish(
        slug="cozy-frog", title="Cozy Frog", description="d",
        image_id="img-1", variant_ids=[10], price_cents=2499,
    )
    # It must NOT have created a new product (first call is the publish POST).
    assert result.product_id == "prod-1"
    assert result.published is True
    first_method, first_url, _ = client._session.calls[0]
    assert "publish.json" in first_url


# --- mockup save resilience -------------------------------------------------

def test_save_mockups_skips_failed_downloads(tmp_path):
    client = _client(tmp_path, [
        FakeResp(status=404),                    # first url fails
        FakeResp(status=200, content=b"OK"),     # second succeeds
    ])
    saved = client.save_mockups(["http://a/1.png", "http://b/2.png"], tmp_path / "d")
    assert saved == [str(tmp_path / "d" / "mockup_1.png")]


def test_mock_client_never_calls_network(tmp_path):
    client = _client(tmp_path, [], mock=True)
    pid = client.create_product(title="X", description="d", image_id="i",
                                variant_ids=[1], price_cents=2499)
    assert pid.startswith("mock-product-")
    res = client.publish_product(pid)
    assert res.dry_run is True and res.published is False
    assert client._session.calls == []  # no HTTP in mock mode
