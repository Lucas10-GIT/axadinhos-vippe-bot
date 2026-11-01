import base64
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

import publish_telegram as bot


NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def approved_product():
    return {
        "id": 1,
        "nome": "Organizador de gaveta",
        "preco": "R$ 29,90",
        "link": "https://s.shopee.com.br/affiliate-code",
        "imagem_url": "https://down-br.img.susercontent.com/file/product.jpg",
        "categoria": "Casa",
        "comissao": 5,
        "ativo": True,
        "aprovado_publicacao": True,
        "status_publicacao": "pronto",
        "frequencia_dias": 3,
        "cliques": 0,
        "pedidos": 0,
        "comissao_estimada": 0,
        "ultima_publicacao": "",
        "proxima_publicacao": "",
        "ultima_tentativa": "",
        "telegram_message_id": "",
    }


class FakeResponse:
    def __init__(self, payload, error=None):
        self.payload = payload
        self.error = error
        self.status_code = 403 if error else 200

    def raise_for_status(self):
        if self.error:
            raise requests.HTTPError(self.error)

    def json(self):
        return self.payload


class FakeMultiChannelSession:
    def __init__(self, frame, pinterest_error=None):
        self.csv_text = frame.to_csv(index=False)
        self.sha = "sha-initial"
        self.events = []
        self.pinterest_error = pinterest_error
        self.frames = []
        self.post_payloads = []

    def get(self, url, **kwargs):
        self.events.append(("get", url))
        payload = {
            "content": base64.b64encode(self.csv_text.encode("utf-8")).decode("ascii"),
            "sha": self.sha,
        }
        return SimpleNamespace(raise_for_status=Mock(), json=lambda: payload)

    def put(self, url, headers, json, timeout):
        self.events.append(("put", url))
        self.csv_text = base64.b64decode(json["content"]).decode("utf-8")
        self.sha = f"sha-{len(self.frames) + 1}"
        self.frames.append(pd.read_csv(io.StringIO(self.csv_text)))
        return SimpleNamespace(raise_for_status=Mock(), json=lambda: {"content": {"sha": self.sha}})

    def post(self, url, data=None, json=None, headers=None, timeout=None):
        self.events.append(("post", url))
        self.post_payloads.append((url, data, json))
        if "api.pinterest.com/v5/pins" in url:
            return FakeResponse({"id": "pin-789"}, error=self.pinterest_error)
        return FakeResponse({"ok": True, "result": {"message_id": 42}})


BASE_ENV = {
    "PUBLISH_CONFIRMED": "true",
    "GITHUB_TOKEN": "github-test-token",
    "TELEGRAM_BOT_TOKEN": "telegram-test-token",
    "TELEGRAM_CHAT_ID": "channel-test",
}


def test_approved_offer_posts_to_both_channels_and_persists_each_id(capsys):
    frame = pd.DataFrame([approved_product()])
    session = FakeMultiChannelSession(frame)
    env = {
        **BASE_ENV,
        "PINTEREST_PUBLISH_ENABLED": "true",
        "PINTEREST_ACCESS_TOKEN": "pinterest-test-token",
        "PINTEREST_BOARD_ID": "123456789",
    }

    assert bot.main(environ=env, session=session, now=NOW) == 0

    destinations = [url for event, url in session.events if event == "post"]
    assert len(destinations) == 2
    assert "api.telegram.org" in destinations[0]
    assert destinations[1] == "https://api.pinterest.com/v5/pins"
    pinterest_payload = next(payload for url, _, payload in session.post_payloads if url == destinations[1])
    assert pinterest_payload["link"] == approved_product()["link"]
    assert len(session.frames) == 3  # reserve, checkpoint after first channel, final state
    final = session.frames[-1].iloc[0]
    assert final["status_publicacao"] == "enviado"
    assert final["telegram_status"] == "enviado"
    assert str(final["telegram_message_id"]) == "42"
    assert final["pinterest_status"] == "enviado"
    assert final["pinterest_pin_id"] == "pin-789"
    assert final["ultima_publicacao"] == NOW.isoformat()
    assert "canais: Telegram + Pinterest" in capsys.readouterr().out


def test_pinterest_failure_keeps_telegram_success_and_blocks_automatic_retry():
    frame = pd.DataFrame([approved_product()])
    session = FakeMultiChannelSession(frame, pinterest_error="403 private token rejected")
    env = {
        **BASE_ENV,
        "PINTEREST_PUBLISH_ENABLED": "true",
        "PINTEREST_ACCESS_TOKEN": "pinterest-test-token",
        "PINTEREST_BOARD_ID": "123456789",
    }

    with pytest.raises(RuntimeError, match="marcado para revisão manual") as error:
        bot.main(environ=env, session=session, now=NOW)
    assert "pinterest-test-token" not in str(error.value)
    saved = pd.read_csv(io.StringIO(session.csv_text)).iloc[0]
    assert saved["status_publicacao"] == "revisar"
    assert saved["telegram_status"] == "enviado"
    assert str(saved["telegram_message_id"]) == "42"
    assert saved["pinterest_status"] == "revisar"
    posts_before = len([event for event in session.events if event[0] == "post"])

    # The global workflow does not retry items under manual review.
    assert bot.main(environ=env, session=session, now=NOW) == 0
    posts_after = len([event for event in session.events if event[0] == "post"])
    assert posts_after == posts_before


def test_pinterest_enabled_without_secrets_fails_before_any_request():
    session = FakeMultiChannelSession(pd.DataFrame([approved_product()]))
    env = {**BASE_ENV, "PINTEREST_PUBLISH_ENABLED": "true"}

    with pytest.raises(RuntimeError, match="PINTEREST_ACCESS_TOKEN, PINTEREST_BOARD_ID"):
        bot.main(environ=env, session=session, now=NOW)
    assert session.events == []


def test_invalid_pinterest_pin_is_blocked_before_telegram_and_marked_for_review():
    row = approved_product()
    row["imagem_url"] = ""
    session = FakeMultiChannelSession(pd.DataFrame([row]))
    env = {
        **BASE_ENV,
        "PINTEREST_PUBLISH_ENABLED": "true",
        "PINTEREST_ACCESS_TOKEN": "pinterest-test-token",
        "PINTEREST_BOARD_ID": "123456789",
    }

    with pytest.raises(RuntimeError, match="nenhum canal foi publicado") as error:
        bot.main(environ=env, session=session, now=NOW)

    assert "imagem pública HTTPS" in str(error.value)
    assert not [event for event in session.events if event[0] == "post"]
    saved = pd.read_csv(io.StringIO(session.csv_text)).iloc[0]
    assert saved["status_publicacao"] == "revisar"
    assert saved["pinterest_status"] == "revisar"


def test_pinterest_is_not_contacted_when_feature_flag_is_false():
    session = FakeMultiChannelSession(pd.DataFrame([approved_product()]))

    assert bot.main(environ=BASE_ENV, session=session, now=NOW) == 0

    destinations = [url for event, url in session.events if event == "post"]
    assert len(destinations) == 1
    assert "api.telegram.org" in destinations[0]
