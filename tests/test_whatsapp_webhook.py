import hashlib
import hmac
import json

import pytest

from whatsapp_webhook import (
    WhatsAppDraftWebhookError,
    build_whatsapp_draft_payload,
    send_whatsapp_draft_webhook,
    verify_whatsapp_webhook_admin_pin,
)


ROW = {
    "id": 17,
    "nome": "Organizador de gaveta",
    "preco": "R$ 29,90",
    "categoria": "Casa & Cozinha",
    "link": "https://amzn.to/affiliate-code?utm_source=axadinhos",
    "chamada": "Uma opção prática para organizar a casa",
    "ativo": True,
    "aprovado_publicacao": True,
}
URL = "https://hooks.example.com/receive/secret-path"
SIGNING_SECRET = "s" * 48


class Response:
    def __init__(self, status_code=202):
        self.status_code = status_code


class Session:
    def __init__(self, response=None, error=None):
        self.response = response or Response()
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def test_payload_is_a_draft_only_and_contains_no_recipient_data():
    payload = build_whatsapp_draft_payload(ROW)

    assert payload["action"] == "create_draft"
    assert payload["send"] is False
    assert payload["draft"]["channel"] == "whatsapp"
    assert ROW["link"] in payload["draft"]["text"]
    assert payload["product"]["affiliate_url"] == ROW["link"]
    assert "recipient" not in payload
    assert "phone" not in json.dumps(payload).casefold()


def test_disabled_webhook_makes_no_request():
    session = Session()

    with pytest.raises(WhatsAppDraftWebhookError, match="desativado"):
        send_whatsapp_draft_webhook(
            ROW,
            enabled=False,
            webhook_url=URL,
            signing_secret=SIGNING_SECRET,
            session=session,
        )

    assert session.calls == []


def test_admin_pin_is_checked_without_timing_sensitive_string_comparison():
    assert verify_whatsapp_webhook_admin_pin("operator-pin-123456", "operator-pin-123456")
    assert verify_whatsapp_webhook_admin_pin("senha-ação-privada-123", "senha-ação-privada-123")
    assert not verify_whatsapp_webhook_admin_pin("wrong-pin", "operator-pin-123456")
    assert not verify_whatsapp_webhook_admin_pin("short", "short")
    assert not verify_whatsapp_webhook_admin_pin(None, "operator-pin-123456")


def test_webhook_requires_approved_active_item_and_valid_configuration():
    with pytest.raises(WhatsAppDraftWebhookError, match="ativos e aprovados"):
        build_whatsapp_draft_payload({**ROW, "aprovado_publicacao": False})
    with pytest.raises(WhatsAppDraftWebhookError, match="HTTPS"):
        send_whatsapp_draft_webhook(
            ROW,
            enabled=True,
            webhook_url="http://hooks.example.com/receive",
            signing_secret=SIGNING_SECRET,
            session=Session(),
        )
    with pytest.raises(WhatsAppDraftWebhookError, match="32 caracteres"):
        send_whatsapp_draft_webhook(
            ROW,
            enabled=True,
            webhook_url=URL,
            signing_secret="short",
            session=Session(),
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@hooks.example.com/receive",
        "https://hooks.example.com/receive?token=secret",
        "https://localhost/receive",
        "https://127.0.0.1/receive",
        "https://hooks.example.com:8443/receive",
    ],
)
def test_unsafe_or_ambiguous_endpoint_urls_are_rejected(url):
    with pytest.raises(WhatsAppDraftWebhookError):
        send_whatsapp_draft_webhook(
            ROW,
            enabled=True,
            webhook_url=url,
            signing_secret=SIGNING_SECRET,
            session=Session(),
        )


def test_https_default_port_is_allowed():
    session = Session()
    result = send_whatsapp_draft_webhook(
        ROW,
        enabled=True,
        webhook_url="https://hooks.example.com:443/receive",
        signing_secret=SIGNING_SECRET,
        session=session,
    )

    assert result["accepted"] is True
    assert len(session.calls) == 1


def test_successful_handoff_is_signed_and_has_stable_idempotency_key():
    session = Session()
    result = send_whatsapp_draft_webhook(
        ROW,
        enabled=True,
        webhook_url=URL,
        signing_secret=SIGNING_SECRET,
        session=session,
        now=1234567890,
    )
    sent_url, request = session.calls[0]
    body = request["data"]
    expected_signature = hmac.new(
        SIGNING_SECRET.encode(),
        b"1234567890." + body,
        hashlib.sha256,
    ).hexdigest()
    expected_idempotency = hashlib.sha256(b"axadinhos-whatsapp-draft-v1." + body).hexdigest()

    assert sent_url == URL
    assert request["timeout"] == (5, 15)
    assert request["allow_redirects"] is False
    assert request["headers"]["X-Axadinhos-Timestamp"] == "1234567890"
    assert request["headers"]["X-Axadinhos-Signature"] == f"sha256={expected_signature}"
    assert request["headers"]["Idempotency-Key"] == expected_idempotency
    assert json.loads(body)["send"] is False
    assert result == {"accepted": True, "idempotency_key": expected_idempotency}


def test_non_success_or_uncertain_response_fails_without_retry():
    rejected = Session(response=Response(status_code=503))
    with pytest.raises(WhatsAppDraftWebhookError, match="Nenhuma repetição automática"):
        send_whatsapp_draft_webhook(
            ROW,
            enabled=True,
            webhook_url=URL,
            signing_secret=SIGNING_SECRET,
            session=rejected,
        )
    assert len(rejected.calls) == 1

    timeout = Session(error=TimeoutError("secret endpoint details"))
    with pytest.raises(WhatsAppDraftWebhookError, match="resposta incerta") as exc:
        send_whatsapp_draft_webhook(
            ROW,
            enabled=True,
            webhook_url=URL,
            signing_secret=SIGNING_SECRET,
            session=timeout,
        )
    assert "secret endpoint details" not in str(exc.value)
    assert len(timeout.calls) == 1
