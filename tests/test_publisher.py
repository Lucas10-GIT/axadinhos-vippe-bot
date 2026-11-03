import base64
import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

import publisher

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
AFFILIATE_URL = "https://s.shopee.com.br/affiliate-code?utm_source=axadinhos"
ROW = {
    "id": 7,
    "nome": "Organizador de gaveta",
    "preco": "R$ 29,90",
    "link": AFFILIATE_URL,
    "imagem_url": "https://down-br.img.susercontent.com/file/product.jpg",
    "categoria": "Casa",
    "ativo": True,
    "aprovado_publicacao": True,
    "status_publicacao": "pronto",
    "frequencia_dias": 3,
    "cliques": 20,
    "pedidos": 1,
    "comissao_estimada": 4.5,
    "ultima_publicacao": "",
    "proxima_publicacao": "",
    "ultima_tentativa": "",
    "telegram_message_id": "",
    "telegram_status": "pendente",
    "pinterest_status": "pendente",
    "pinterest_pin_id": "",
}
ENV_TELEGRAM = {
    "PUBLISH_CONFIRMED": "true",
    "TELEGRAM_PUBLISH_ENABLED": "true",
    "PINTEREST_PUBLISH_ENABLED": "false",
    "GITHUB_TOKEN": "test-github-token",
    "TELEGRAM_PUBLISHER_BOT_TOKEN": "test-new-telegram-token",
    "TELEGRAM_PUBLISHER_CHAT_ID": "@AxadinhosPublicos",
}
ENV_PINTEREST = {
    "PUBLISH_CONFIRMED": "true",
    "TELEGRAM_PUBLISH_ENABLED": "false",
    "PINTEREST_PUBLISH_ENABLED": "true",
    "GITHUB_TOKEN": "test-github-token",
    "PINTEREST_ACCESS_TOKEN": "test-pinterest-token",
    "PINTEREST_BOARD_ID": "123456789",
}
ENV_BOTH = {
    **ENV_TELEGRAM,
    "PINTEREST_PUBLISH_ENABLED": "true",
    "PINTEREST_ACCESS_TOKEN": "test-pinterest-token",
    "PINTEREST_BOARD_ID": "123456789",
}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload = {} if payload is None else payload
        self.status_code = status
        self.ok = status < 400
        self.text = "fake response"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}: fake response")

    def json(self):
        return self.payload


class FakeSession:
    """In-memory GitHub + social APIs; no request leaves the test process."""

    def __init__(self, frame=None, telegram_error=False, pinterest_error=False):
        self.frame = pd.DataFrame([ROW] if frame is None else frame).copy()
        self.sha = "sha-initial"
        self.telegram_error = telegram_error
        self.pinterest_error = pinterest_error
        self.get_calls = []
        self.put_calls = []
        self.post_calls = []
        self.events = []
        self.saved_frames = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        self.events.append("get")
        csv_bytes = self.frame.to_csv(index=False).encode("utf-8")
        payload = {
            "content": base64.b64encode(csv_bytes).decode("ascii"),
            "sha": self.sha,
        }
        return FakeResponse(payload)

    def put(self, url, **kwargs):
        self.put_calls.append((url, kwargs))
        self.events.append("put")
        assert kwargs["json"]["sha"] == self.sha
        csv_bytes = base64.b64decode(kwargs["json"]["content"])
        self.frame = pd.read_csv(io.BytesIO(csv_bytes))
        self.saved_frames.append(self.frame.copy())
        self.sha = f"sha-{len(self.put_calls)}"
        return FakeResponse({"content": {"sha": self.sha}})

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        if url.startswith("https://api.telegram.org/"):
            self.events.append("telegram")
            if self.telegram_error:
                return FakeResponse({"ok": False, "description": "test failure"})
            return FakeResponse({"ok": True, "result": {"message_id": 4242}})
        if url == "https://api.pinterest.com/v5/pins":
            self.events.append("pinterest")
            if self.pinterest_error:
                return FakeResponse({"message": "permission denied"}, status=403)
            return FakeResponse({"id": "pin-789"})
        raise AssertionError(f"Unexpected endpoint: {url}")


def test_parse_bool_handles_secrets_and_csv_values():
    assert publisher.parse_bool("true") is True
    assert publisher.parse_bool("SIM") is True
    assert publisher.parse_bool("false") is False
    assert publisher.parse_bool(None, default=False) is False


def test_is_due_requires_active_approved_ready_and_valid_shopee_link():
    assert publisher.is_due(ROW, NOW, ["telegram"])
    assert not publisher.is_due({**ROW, "ativo": False}, NOW, ["telegram"])
    assert not publisher.is_due({**ROW, "aprovado_publicacao": False}, NOW, ["telegram"])
    assert not publisher.is_due({**ROW, "status_publicacao": "revisar"}, NOW, ["telegram"])
    assert not publisher.is_due({**ROW, "link": "https://example.com/item"}, NOW, ["telegram"])
    not_yet = {**ROW, "proxima_publicacao": (NOW + timedelta(minutes=1)).isoformat()}
    assert not publisher.is_due(not_yet, NOW, ["telegram"])


def test_is_due_obeys_frequency_but_allows_pending_channel_to_complete_crosspost():
    old = (NOW - timedelta(days=4)).isoformat()
    recent = (NOW - timedelta(days=2)).isoformat()
    assert publisher.is_due({**ROW, "ultima_publicacao": old, "frequencia_dias": 3}, NOW, ["telegram"])
    assert not publisher.is_due({**ROW, "ultima_publicacao": recent, "frequencia_dias": 3}, NOW, ["telegram"])

    telegram_sent = {
        **ROW,
        "status_publicacao": "enviado",
        "telegram_status": "enviado",
        "telegram_message_id": "4242",
        "ultima_publicacao": NOW.isoformat(),
        "proxima_publicacao": (NOW + timedelta(days=30)).isoformat(),
    }
    assert not publisher.is_due(telegram_sent, NOW, ["telegram"])
    assert publisher.is_due(telegram_sent, NOW, ["pinterest"])


def test_publication_cooldown_uses_latest_recorded_publication():
    frame = pd.DataFrame([
        {"ultima_publicacao": (NOW - timedelta(hours=5)).isoformat()},
        {"ultima_publicacao": (NOW - timedelta(hours=2)).isoformat()},
    ])
    assert publisher.publication_cooldown_until(frame) == NOW + timedelta(hours=2)


def test_candidate_selection_returns_highest_scored_due_product():
    low = {**ROW, "id": 1, "pedidos": 0, "comissao_estimada": 0}
    high = {**ROW, "id": 2, "pedidos": 2, "comissao_estimada": 8}
    index, selected = publisher.select_candidate(pd.DataFrame([low, high]), NOW, ["pinterest"])
    assert index == 1
    assert selected["id"] == 2
    ranked = publisher.rank_candidates(pd.DataFrame([low, high]), NOW, ["pinterest"])
    assert [row["id"] for _, row in ranked] == [2, 1]
    selected_again = publisher.select_candidate(pd.DataFrame([low, high]), NOW, ["pinterest"])
    assert selected_again[0] == ranked[0][0]
    assert selected_again[1]["id"] == ranked[0][1]["id"]


def test_publication_frequency_uses_performance_thresholds():
    assert publisher.publication_frequency({"pedidos": 2, "cliques": 3}) == 2
    assert publisher.publication_frequency({"pedidos": 0, "cliques": 10}) == 4
    assert publisher.publication_frequency({"pedidos": 0, "cliques": 2}) == 3


def test_telegram_only_publishes_once_and_preserves_original_affiliate_link():
    session = FakeSession()
    assert publisher.main(ENV_TELEGRAM, session=session, now=NOW) == 0

    assert len(session.post_calls) == 1
    url, request = session.post_calls[0]
    assert url == "https://api.telegram.org/bottest-new-telegram-token/sendPhoto"
    assert request["json"]["chat_id"] == "@AxadinhosPublicos"
    assert AFFILIATE_URL in request["json"]["caption"]
    assert "Link de afiliado" in request["json"]["caption"]
    assert session.events == ["get", "put", "telegram", "put", "put"]
    assert len(session.put_calls) == 3
    saved = session.frame.iloc[0]
    assert str(saved["telegram_message_id"]) == "4242"
    assert saved["telegram_status"] == "enviado"
    assert saved["pinterest_status"] == "pendente"
    assert saved["status_publicacao"] == "enviado"
    assert saved["ultima_publicacao"] == NOW.isoformat()
    assert saved["frequencia_dias"] == 4


def test_pinterest_only_does_not_call_telegram():
    session = FakeSession()
    assert publisher.main(ENV_PINTEREST, session=session, now=NOW) == 0

    assert len(session.post_calls) == 1
    url, request = session.post_calls[0]
    assert url == "https://api.pinterest.com/v5/pins"
    assert request["json"]["link"] == AFFILIATE_URL
    assert "Link de afiliado" in request["json"]["description"]
    assert session.events == ["get", "put", "pinterest", "put", "put"]
    saved = session.frame.iloc[0]
    assert saved["telegram_status"] == "pendente"
    assert saved["pinterest_pin_id"] == "pin-789"
    assert saved["pinterest_status"] == "enviado"


def test_both_channels_publish_sequentially_and_checkpoint_each_result():
    session = FakeSession()
    assert publisher.main(ENV_BOTH, session=session, now=NOW) == 0

    assert session.events == ["get", "put", "telegram", "put", "pinterest", "put", "put"]
    destinations = [
        "telegram" if url.startswith("https://api.telegram.org/") else "pinterest"
        for url, _ in session.post_calls
    ]
    assert destinations == ["telegram", "pinterest"]
    after_telegram = session.saved_frames[1].iloc[0]
    assert after_telegram["telegram_status"] == "enviado"
    assert str(after_telegram["telegram_message_id"]) == "4242"
    assert after_telegram["pinterest_status"] == "pendente"
    final = session.frame.iloc[0]
    assert final["telegram_status"] == "enviado"
    assert final["pinterest_status"] == "enviado"
    assert final["pinterest_pin_id"] == "pin-789"
    assert final["status_publicacao"] == "enviado"


def test_pinterest_failure_preserves_telegram_success_and_marks_only_failed_channel_for_review():
    session = FakeSession(pinterest_error=True)
    with pytest.raises(RuntimeError, match="revisão manual") as error:
        publisher.main(ENV_BOTH, session=session, now=NOW)

    assert "test-new-telegram-token" not in str(error.value)
    assert session.events == ["get", "put", "telegram", "put", "pinterest", "put"]
    saved = session.frame.iloc[0]
    assert saved["telegram_status"] == "enviado"
    assert str(saved["telegram_message_id"]) == "4242"
    assert saved["pinterest_status"] == "revisar"
    assert saved["status_publicacao"] == "revisar"


def test_telegram_ambiguous_failure_stops_before_pinterest_and_is_not_retried():
    session = FakeSession(telegram_error=True)
    with pytest.raises(RuntimeError, match="revisão manual") as error:
        publisher.main(ENV_BOTH, session=session, now=NOW)

    assert "test-new-telegram-token" not in str(error.value)
    assert [event for event in session.events if event in {"telegram", "pinterest"}] == ["telegram"]
    assert session.frame.iloc[0]["telegram_status"] == "revisar"
    assert session.frame.iloc[0]["pinterest_status"] == "pendente"
    post_count = len(session.post_calls)

    assert publisher.main(ENV_BOTH, session=session, now=NOW + timedelta(days=1)) == 0
    assert len(session.post_calls) == post_count


def test_preflight_validates_both_destinations_before_any_social_post():
    invalid_pin = {**ROW, "imagem_url": ""}
    session = FakeSession(frame=[invalid_pin])
    with pytest.raises(RuntimeError, match="Pré-validação de Pinterest"):
        publisher.main(ENV_BOTH, session=session, now=NOW)

    assert not session.post_calls
    saved = session.frame.iloc[0]
    assert saved["telegram_status"] == "pendente"
    assert saved["pinterest_status"] == "revisar"
    assert saved["status_publicacao"] == "revisar"


def test_invalid_telegram_destination_fails_before_first_social_post():
    session = FakeSession()
    env = {**ENV_TELEGRAM, "TELEGRAM_PUBLISHER_CHAT_ID": "not-a-chat"}
    with pytest.raises(RuntimeError, match="Pré-validação de Telegram"):
        publisher.main(env, session=session, now=NOW)
    assert not session.post_calls
    assert session.frame.iloc[0]["telegram_status"] == "revisar"


def test_manual_product_id_targets_only_selected_product():
    other = {**ROW, "id": 8, "nome": "Outro produto", "link": "https://shopee.com.br/outro"}
    session = FakeSession(frame=[ROW, other])
    assert publisher.main(ENV_PINTEREST, session=session, now=NOW, product_id=8) == 0
    assert len(session.post_calls) == 1
    assert session.post_calls[0][1]["json"]["link"] == other["link"]
    assert session.frame.loc[session.frame["id"] == 7, "pinterest_status"].iloc[0] == "pendente"
    assert session.frame.loc[session.frame["id"] == 8, "pinterest_status"].iloc[0] == "enviado"


def test_global_cooldown_blocks_before_any_social_post():
    recent = {**ROW, "ultima_publicacao": (NOW - timedelta(hours=1)).isoformat()}
    session = FakeSession(frame=[recent])
    assert publisher.main(ENV_BOTH, session=session, now=NOW) == 0
    assert len(session.get_calls) == 1
    assert not session.post_calls
    assert not session.put_calls


def test_no_channel_opt_in_fails_before_github_or_social_network():
    session = FakeSession()
    env = {**ENV_TELEGRAM, "TELEGRAM_PUBLISH_ENABLED": "false", "PINTEREST_PUBLISH_ENABLED": "false"}
    with pytest.raises(RuntimeError, match="pelo menos um canal"):
        publisher.main(env, session=session, now=NOW)
    assert not session.get_calls
    assert not session.post_calls


def test_old_telegram_secrets_are_never_used_for_the_new_bot():
    session = FakeSession()
    env = {
        "PUBLISH_CONFIRMED": "true",
        "TELEGRAM_PUBLISH_ENABLED": "true",
        "PINTEREST_PUBLISH_ENABLED": "false",
        "GITHUB_TOKEN": "test-github-token",
        "TELEGRAM_BOT_TOKEN": "old-frozen-bot-token",
        "TELEGRAM_CHAT_ID": "@oldchannel",
    }
    with pytest.raises(RuntimeError, match="TELEGRAM_PUBLISHER_BOT_TOKEN"):
        publisher.main(env, session=session, now=NOW)
    assert not session.get_calls
    assert not session.post_calls


def test_missing_channel_credentials_fail_before_github_network():
    session = FakeSession()
    env = {key: value for key, value in ENV_PINTEREST.items() if key != "PINTEREST_ACCESS_TOKEN"}
    with pytest.raises(RuntimeError, match="PINTEREST_ACCESS_TOKEN"):
        publisher.main(env, session=session, now=NOW)
    assert not session.get_calls
    assert not session.post_calls


def test_unconfirmed_or_unapproved_publication_fails_closed():
    session = FakeSession()
    with pytest.raises(RuntimeError, match="PUBLISH_CONFIRMED"):
        publisher.main({**ENV_TELEGRAM, "PUBLISH_CONFIRMED": "false"}, session=session, now=NOW)
    assert not session.get_calls

    unapproved = {**ROW, "aprovado_publicacao": False}
    session = FakeSession(frame=[unapproved])
    assert publisher.main(ENV_TELEGRAM, session=session, now=NOW) == 0
    assert not session.post_calls


def test_ambiguous_legacy_sent_state_is_blocked_for_manual_review():
    legacy = {**ROW, "status_publicacao": "enviado"}
    session = FakeSession(frame=[legacy])
    assert publisher.main(ENV_TELEGRAM, session=session, now=NOW) == 0
    assert not session.post_calls
    # The UI and CSV migration surface this state as review-required.
    assert publisher._ensure_state_columns(session.frame.copy()).iloc[0]["status_publicacao"] == "revisar"


def test_already_sent_channel_is_not_duplicated_even_after_global_status_reset():
    sent = {
        **ROW,
        "status_publicacao": "pronto",
        "telegram_status": "enviado",
        "telegram_message_id": "message-previously-sent",
    }
    session = FakeSession(frame=[sent])
    assert publisher.main(ENV_TELEGRAM, session=session, now=NOW) == 0
    assert not session.post_calls


def test_redaction_replaces_multiple_secret_values():
    safe = publisher._redact(
        "failed github-secret telegram-secret pinterest-secret",
        "github-secret", "telegram-secret", "pinterest-secret",
    )
    assert "github-secret" not in safe
    assert "telegram-secret" not in safe
    assert "pinterest-secret" not in safe
    assert safe.count("[REDACTED]") == 3
