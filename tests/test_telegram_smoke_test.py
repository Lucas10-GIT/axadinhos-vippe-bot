from __future__ import annotations

import json
from urllib.parse import parse_qs

import pytest

from scripts import telegram_smoke_test


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps({"ok": True, "result": {"message_id": 42}}).encode("utf-8")


def test_sends_one_silent_non_promotional_message(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")
    observed = {}

    def fake_urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        observed["body"] = parse_qs(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(telegram_smoke_test, "urlopen", fake_urlopen)

    assert telegram_smoke_test.main() == 0
    assert "test-token" in observed["url"]
    assert observed["timeout"] == 20
    assert observed["body"]["chat_id"] == ["test-chat"]
    assert observed["body"]["disable_notification"] == ["true"]
    assert observed["body"]["text"] == [telegram_smoke_test.MESSAGE]
    assert "não é um anúncio" in telegram_smoke_test.MESSAGE.casefold()
    assert "message_id=42" in capsys.readouterr().out


def test_missing_secrets_fails_before_network(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    def unexpected_urlopen(*args, **kwargs):
        pytest.fail("Não deve haver chamada de rede sem secrets")

    monkeypatch.setattr(telegram_smoke_test, "urlopen", unexpected_urlopen)
    with pytest.raises(SystemExit, match="Faltam TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID"):
        telegram_smoke_test.main()
