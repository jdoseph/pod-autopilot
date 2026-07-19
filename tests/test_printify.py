import pytest

from src import printify_client


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("PRINTIFY_API_KEY", "k")


def test_shop_ids_by_channel_normalizes_and_skips_disconnected(monkeypatch):
    monkeypatch.setattr(printify_client, "shops", lambda: [
        {"id": 1, "title": "S", "sales_channel": "shopify"},
        {"id": 2, "title": "E", "sales_channel": "Etsy"},
        {"id": 3, "title": "old", "sales_channel": "disconnected"},
    ])
    assert printify_client.shop_ids_by_channel() == {"shopify": 1, "etsy": 2}


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


def test_contain_scale_fits_portrait_in_square_area():
    # 3:4 portrait art on a square tote area must shrink below 0.75
    s = printify_client.contain_scale(0.75, 3300, 3300)
    assert s <= 0.75
    # image height as a fraction of area height must not exceed 1.0
    assert (s * 3300 / 0.75) / 3300 <= 1.0


def test_contain_scale_keeps_max_for_tall_areas():
    # portrait art on a taller-than-image shirt area keeps the 0.9 default
    assert printify_client.contain_scale(0.75, 4472, 5952) == 0.9


def test_contain_scale_defaults_without_dims():
    assert printify_client.contain_scale(0.75, None, None) == 0.9


def test_tote_places_art_in_top_panel(monkeypatch):
    """Blueprint 507's front area wraps under the bag — art must fit the
    top half and sit at y=0.25 or it prints past the fold."""
    seen = {}

    def fake_get_json(url):
        if url.endswith("/print_providers.json"):
            return [{"id": 48}]
        return {"variants": [{"id": 1, "placeholders":
                              [{"position": "front", "width": 2102, "height": 4051}]}]}

    class Resp:
        ok = True

        def json(self):
            return {"id": "p1", "variants": []}

    def fake_post(url, headers, json, timeout):
        seen["payload"] = json
        return Resp()

    monkeypatch.setattr(printify_client, "_get_json", fake_get_json)
    monkeypatch.setattr(printify_client.requests, "post", fake_post)
    printify_client.create_product(1, "img", "tote", "T", "D", 2395, ["x"],
                                   image_aspect=1.0)
    img = seen["payload"]["print_areas"][0]["placeholders"][0]["images"][0]
    assert img["y"] == 0.25
    # square art must fit within the top HALF of the 2102x4051 wrap
    panel_h = 4051 * 0.5
    assert img["scale"] * 2102 / 1.0 <= panel_h


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
