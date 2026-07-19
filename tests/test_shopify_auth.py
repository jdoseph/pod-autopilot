import pytest

from src import shopify_auth


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for var in ("SHOPIFY_ACCESS_TOKEN", "SHOPIFY_CLIENT_ID",
                "SHOPIFY_CLIENT_SECRET", "SHOPIFY_STORE"):
        monkeypatch.delenv(var, raising=False)
    shopify_auth._cached.update({"token": None, "exp": 0.0})


def test_no_credentials_returns_none():
    assert shopify_auth.access_token() is None
    assert shopify_auth.headers() == {}


def test_static_token_preferred(monkeypatch):
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_static")
    assert shopify_auth.headers() == {"X-Shopify-Access-Token": "shpat_static"}


def test_client_credentials_exchange_and_cache(monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE", "x.myshopify.com")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "sec")
    calls = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "shpat_minted", "expires_in": 86399}

    def fake_post(url, timeout, data):
        calls.append((url, data["grant_type"]))
        return Resp()

    monkeypatch.setattr(shopify_auth.requests, "post", fake_post)
    assert shopify_auth.access_token() == "shpat_minted"
    assert shopify_auth.access_token() == "shpat_minted"  # cached, no 2nd call
    assert len(calls) == 1
    assert calls[0] == ("https://x.myshopify.com/admin/oauth/access_token",
                        "client_credentials")
