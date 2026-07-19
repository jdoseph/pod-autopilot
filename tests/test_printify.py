import pytest

from src import printify_client


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("PRINTIFY_API_KEY", "k")


def test_resolve_provider_keeps_valid_preferred(monkeypatch):
    monkeypatch.setattr(printify_client, "_get_json",
                        lambda url: [{"id": 27}, {"id": 99}])
    assert printify_client.resolve_provider(6, 99) == 99


def test_resolve_provider_falls_back_when_preferred_gone(monkeypatch):
    monkeypatch.setattr(printify_client, "_get_json", lambda url: [{"id": 27}])
    assert printify_client.resolve_provider(68, 28) == 27


def test_resolve_provider_errors_when_none(monkeypatch):
    monkeypatch.setattr(printify_client, "_get_json", lambda url: [])
    with pytest.raises(RuntimeError):
        printify_client.resolve_provider(6, 99)


def test_create_product_caps_variants(monkeypatch):
    seen = {}

    def fake_get_json(url):
        if url.endswith("/print_providers.json"):
            return [{"id": 99}]
        return {"variants": [{"id": i} for i in range(400)]}

    class Resp:
        ok = True

        def json(self):
            return {"id": "p1"}

    def fake_post(url, headers, json, timeout):
        seen["payload"] = json
        return Resp()

    monkeypatch.setattr(printify_client, "_get_json", fake_get_json)
    monkeypatch.setattr(printify_client.requests, "post", fake_post)
    out = printify_client.create_product(1, "img", "t-shirt", "T", "D", 2495, ["x"])
    assert out["id"] == "p1"
    assert len(seen["payload"]["variants"]) == printify_client.MAX_VARIANTS
    assert len(seen["payload"]["print_areas"][0]["variant_ids"]) == printify_client.MAX_VARIANTS
