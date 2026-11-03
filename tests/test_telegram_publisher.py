from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import telegram_publisher as telegram


ROW = {
    "nome": "Organizador de gaveta",
    "preco": "R$ 29,90",
    "link": "https://s.shopee.com.br/affiliate-code?utm_source=telegram",
    "imagem_url": "https://down-br.img.susercontent.com/file/product.jpg",
}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code} for https://api.telegram.org/botsecret-token/sendMessage"
            )

    def json(self):
        return self.payload


def fake_session(payload=None, status=200):
    response = FakeResponse(payload, status)
    return SimpleNamespace(post=Mock(return_value=response))


def test_build_payload_preserves_affiliate_link_and_includes_disclosure():
    payload = telegram.build_telegram_payload(ROW, "@AchadinhosPublicos")

    assert payload["method"] == "sendPhoto"
    assert payload["chat_id"] == "@AchadinhosPublicos"
    assert payload["photo"] == ROW["imagem_url"]
    assert ROW["link"] in payload["caption"]
    assert "Link de afiliado" in payload["caption"]
    assert "sem custo adicional" in payload["caption"]
    assert "Preço e disponibilidade podem mudar" in payload["caption"]
    assert "parse_mode" not in payload


def test_build_payload_uses_text_when_image_is_not_public_https():
    payload = telegram.build_telegram_payload({**ROW, "imagem_url": "http://example.com/image.jpg"}, -1001234567890)
    assert payload["method"] == "sendMessage"
    assert payload["chat_id"] == "-1001234567890"
    assert ROW["link"] in payload["text"]
    assert len(payload["text"]) <= 4096


@pytest.mark.parametrize(
    ("row", "chat_id"),
    [
        ({**ROW, "nome": ""}, "@achadinhos"),
        ({**ROW, "preco": ""}, "@achadinhos"),
        ({**ROW, "link": "https://example.com/item"}, "@achadinhos"),
        ({**ROW, "link": " https://s.shopee.com.br/abc"}, "@achadinhos"),
        (ROW, "@bad"),
        (ROW, "@no-hyphens"),
        (ROW, "not-a-chat"),
    ],
)
def test_build_payload_rejects_invalid_product_or_destination(row, chat_id):
    with pytest.raises(telegram.TelegramPublisherError):
        telegram.build_telegram_payload(row, chat_id)


def test_build_payload_falls_back_to_complete_message_if_caption_is_too_long():
    row = {**ROW, "nome": "x" * 1100}
    payload = telegram.build_telegram_payload(row, 123456789)
    assert payload["method"] == "sendMessage"
    assert ROW["link"] in payload["text"]
    assert len(payload["text"]) <= 4096


def test_build_payload_rejects_message_that_cannot_fit_without_truncation():
    row = {**ROW, "nome": "x" * 4100}
    with pytest.raises(telegram.TelegramPublisherError, match="4096"):
        telegram.build_telegram_payload(row, "-1001234567890")


def test_send_uses_telegram_api_timeout_and_returns_message_id():
    session = fake_session({"ok": True, "result": {"message_id": 987}})
    result = telegram.send_telegram_message(ROW, "private-token", "-1001234567890", session=session)

    assert result == {"message_id": 987}
    args, kwargs = session.post.call_args
    assert args[0] == "https://api.telegram.org/botprivate-token/sendPhoto"
    assert kwargs["json"]["chat_id"] == "-1001234567890"
    assert kwargs["json"]["photo"] == ROW["imagem_url"]
    assert kwargs["timeout"] == 30


def test_send_rejects_missing_token_or_chat_before_network():
    session = SimpleNamespace(post=Mock())
    with pytest.raises(telegram.TelegramPublisherError, match="token"):
        telegram.send_telegram_message(ROW, "", "@achadinhos", session=session)
    with pytest.raises(telegram.TelegramPublisherError, match="destino"):
        telegram.send_telegram_message(ROW, "private-token", "", session=session)
    session.post.assert_not_called()


def test_send_rejects_api_ok_false_without_echoing_response_details():
    session = fake_session({"ok": False, "description": "private-token rejected"})
    with pytest.raises(telegram.TelegramPublisherError) as error:
        telegram.send_telegram_message(ROW, "private-token", "@achadinhos", session=session)
    assert "private-token" not in str(error.value)
    assert "description" not in str(error.value)


def test_send_sanitizes_http_error_without_token_or_authenticated_url():
    session = fake_session({"ok": False}, status=403)
    with pytest.raises(telegram.TelegramPublisherError) as error:
        telegram.send_telegram_message(ROW, "secret-telegram-token", "@achadinhos", session=session)
    assert "403" in str(error.value)
    assert "secret-telegram-token" not in str(error.value)
    assert "api.telegram.org" not in str(error.value)
    assert "botsecret" not in str(error.value)


def test_send_sanitizes_transport_failure_without_network_retry():
    session = SimpleNamespace(
        post=Mock(side_effect=RuntimeError("failed https://api.telegram.org/botsecret-token/sendMessage"))
    )
    with pytest.raises(telegram.TelegramPublisherError) as error:
        telegram.send_telegram_message(ROW, "secret-telegram-token", "@achadinhos", session=session)
    assert "secret-telegram-token" not in str(error.value)
    assert "api.telegram.org" not in str(error.value)
    session.post.assert_called_once()
