import pytest

from src.claude_client import extract_json

DOC = {"approved": True, "risk_level": "low", "reason": "ok"}


@pytest.mark.parametrize("raw", [
    '{"approved": true, "risk_level": "low", "reason": "ok"}',
    '```json\n{"approved": true, "risk_level": "low", "reason": "ok"}\n```',
    'Here is my assessment:\n{"approved": true, "risk_level": "low", "reason": "ok"}',
    '{"approved": true, "risk_level": "low", "reason": "ok"}\nLet me know if you need more.',
])
def test_extract_json_tolerates_wrappers(raw):
    assert extract_json(raw) == DOC


def test_extract_json_raises_on_garbage():
    with pytest.raises(Exception):
        extract_json("no json here at all")
