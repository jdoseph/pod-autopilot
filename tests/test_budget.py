import json
from datetime import datetime

import pytest

from src import budget


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(budget, "LEDGER", path)
    return path


def test_record_llm_math(ledger):
    # 1000 fresh in + 500 cached in + 200 out on Sonnet
    budget.record_llm("claude-sonnet-4-6", in_tok=1500, out_tok=200, cached_tok=500)
    entry = json.loads(ledger.read_text())
    expected = (1000 * 3.00 + 500 * 0.30 + 200 * 15.00) / 1e6
    assert entry["usd"] == pytest.approx(expected, abs=1e-9)


def test_month_spend_includes_first_of_month_midnight(ledger):
    now = datetime.utcnow()
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    lines = [
        {"ts": first.isoformat(), "kind": "llm", "usd": 1.0},          # midnight day 1: in
        {"ts": now.isoformat(), "kind": "image", "usd": 0.5},          # now: in
        {"ts": "2000-01-01T00:00:00", "kind": "llm", "usd": 99.0},     # old month: out
    ]
    ledger.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    assert budget.month_spend() == pytest.approx(1.5)


def test_publishing_paused_over_cap(ledger, monkeypatch):
    monkeypatch.setattr(budget, "month_revenue", lambda: 0.0)
    monkeypatch.setattr(budget, "GRACE_BUDGET", 1.0)
    budget._log("listing_fee", 0.95)
    ok, status = budget.publishing_allowed()   # 0.95 + 0.20 > 1.00 cap
    assert not ok and "paused" in status


def test_publishing_allowed_with_revenue(ledger, monkeypatch):
    monkeypatch.setattr(budget, "month_revenue", lambda: 100.0)
    monkeypatch.setattr(budget, "GRACE_BUDGET", 1.0)
    budget._log("listing_fee", 0.95)
    ok, _ = budget.publishing_allowed()        # cap = 100*0.25 + 1 = 26
    assert ok


def test_month_revenue_fails_to_zero(monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE", "x.myshopify.com")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(budget.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("net down")))
    assert budget.month_revenue() == 0.0
