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


def test_price_covers_margin_after_shipping():
    for ptype, cost in [("t-shirt", 1100), ("t-shirt", 1800),  # 2XL upcharge
                        ("mug", 600), ("tote", 900)]:
        price = printify_client.price_from_cost(cost, ptype)
        landed = cost + printify_client.SHIPPING_EST[ptype]
        assert (price - landed) / price >= printify_client.MIN_MARGIN - 0.01
        assert price % 100 == 95  # x.95 retail ending


def test_price_floor():
    assert printify_client.price_from_cost(1, "mug") >= printify_client.PRICE_FLOOR


def test_create_product_reprices_from_real_costs(monkeypatch):
    seen = {}

    def fake_get_json(url):
        if url.endswith("/print_providers.json"):
            return [{"id": 99}]
        return {"variants": [{"id": 1}, {"id": 2}]}

    class PostResp:
        ok = True

        def json(self):
            return {"id": "p1", "variants": [
                {"id": 1, "cost": 1100, "is_enabled": True},
                {"id": 2, "cost": 1800, "is_enabled": True}]}

    class PutResp:
        ok = True

        def json(self):
            return {"id": "p1", "repriced": True}

    monkeypatch.setattr(printify_client, "_get_json", fake_get_json)
    monkeypatch.setattr(printify_client.requests, "post",
                        lambda *a, **k: PostResp())

    def fake_put(url, headers, timeout, json):
        seen["variants"] = json["variants"]
        return PutResp()

    monkeypatch.setattr(printify_client.requests, "put", fake_put)
    out = printify_client.create_product(1, "img", "Tote", "T", "D", 1995, ["x"])
    assert out["repriced"] is True
    prices = {v["id"]: v["price"] for v in seen["variants"]}
    assert prices[2] > prices[1]  # costlier variant priced higher
    assert prices[1] == printify_client.price_from_cost(1100, "tote")


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
