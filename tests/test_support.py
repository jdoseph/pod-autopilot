import pytest

from src import support


def _raw(headers: dict, body: str = "hello") -> bytes:
    head = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    return (head + "Content-Type: text/plain\r\n\r\n" + body).encode()


class FakeIMAP:
    def __init__(self, msgs):
        self.msgs = msgs
        self.seen = []

    def select(self, box):
        pass

    def search(self, charset, query):
        ids = b" ".join(str(i + 1).encode() for i in range(len(self.msgs)))
        return "OK", [ids]

    def fetch(self, eid, spec):
        return "OK", [(b"", self.msgs[int(eid) - 1])]

    def store(self, eid, op, flags):
        self.seen.append(eid)

    def logout(self):
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPPORT_IMAP_HOST", "imap.example.com")
    monkeypatch.setattr(support, "FLAGGED", tmp_path / "flagged.jsonl")
    sent = []
    monkeypatch.setattr(support, "_send", lambda *a: sent.append(a))
    return sent


@pytest.mark.parametrize("headers", [
    {"From": "Shop <no-reply@big.com>", "Subject": "sale"},
    {"From": "Discord <notifications@discordapp.com>", "Subject": "missed msgs"},
    {"From": "News <news@x.com>", "Subject": "weekly", "List-Unsubscribe": "<mailto:u@x.com>"},
    {"From": "Bot <bot@x.com>", "Subject": "auto", "Precedence": "bulk"},
    {"From": "Sys <sys@x.com>", "Subject": "receipt", "Auto-Submitted": "auto-generated"},
])
def test_is_bulk_detects_noise(headers):
    import email
    assert support._is_bulk(email.message_from_bytes(_raw(headers)))


def test_is_bulk_passes_real_customers():
    import email
    raw = _raw({"From": "Jane Doe <jane@gmail.com>", "Subject": "where is my order"})
    assert not support._is_bulk(email.message_from_bytes(raw))


def test_bulk_backlog_costs_zero_llm_calls(monkeypatch, env):
    msgs = [_raw({"From": f"Promo <no-reply@spam{i}.com>", "Subject": "buy"})
            for i in range(50)]
    imap = FakeIMAP(msgs)
    monkeypatch.setattr(support, "_conn", lambda: imap)
    calls = []
    monkeypatch.setattr(support, "ask_json", lambda *a, **k: calls.append(a) or {})
    support.run()
    assert calls == []                      # not one LLM call for bulk mail
    assert len(imap.seen) == 50             # but all marked read
    assert env == []                        # and no replies sent


def test_cap_limits_llm_calls_and_leaves_rest_unseen(monkeypatch, env):
    msgs = [_raw({"From": f"C{i} <c{i}@gmail.com>", "Subject": "sizing?"})
            for i in range(10)]
    imap = FakeIMAP(msgs)
    monkeypatch.setattr(support, "_conn", lambda: imap)
    monkeypatch.setattr(support, "MAX_PER_RUN", 3)
    calls = []
    monkeypatch.setattr(support, "ask_json",
                        lambda *a, **k: calls.append(a) or {"category": "x", "answer": None})
    support.run()
    assert len(calls) == 3


def test_answer_sent_and_escalation_flagged(monkeypatch, env):
    msgs = [_raw({"From": "A <a@gmail.com>", "Subject": "sizing?"}),
            _raw({"From": "B <b@gmail.com>", "Subject": "refund!"})]
    monkeypatch.setattr(support, "_conn", lambda: FakeIMAP(msgs))
    verdicts = iter([{"category": "sizing", "answer": "Runs true to size."},
                     {"category": "refund", "answer": None}])
    monkeypatch.setattr(support, "ask_json", lambda *a, **k: next(verdicts))
    support.run()
    assert len(env) == 1 and env[0][0] == "A <a@gmail.com>"
    flagged = support.FLAGGED.read_text()
    assert "refund" in flagged and "a@gmail.com" not in flagged
