import base64
import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlparse
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

import publish_pinterest as publisher

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
ROW = {
    "id": 7,
    "nome": "Organizador de gaveta",
    "preco": "R$ 29,90",
    "link": "https://s.shopee.com.br/affiliate-code",
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
    "pinterest_status": "pendente",
    "pinterest_pin_id": "",
}
ENV = {
    "PUBLISH_CONFIRMED": "true",
    "PINTEREST_PUBLISH_ENABLED": "true",
    "GITHUB_TOKEN": "test-github-token",
    "PINTEREST_ACCESS_TOKEN": "test-pinterest-token",
    "PINTEREST_BOARD_ID": "123456789",
}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload = payload or {}
        self.status_code = status
        self.ok = status < 400
        self.text = "fake response"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}: {self.text}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, frame=None, pin_error=False):
        self.frame = pd.DataFrame([ROW] if frame is None else frame)
        self.sha = "sha-initial"
        self.pin_error = pin_error
        self.get_calls = []
        self.put_calls = []
        self.post_calls = []
        self.events = []

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
        self.sha = f"sha-{len(self.put_calls)}"
        return FakeResponse({"content": {"sha": self.sha}})

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        self.events.append("post")
        if self.pin_error:
            return FakeResponse({"message": "permission denied"}, status=403)
        return FakeResponse({"id": "pin-789"})


def test_parse_bool_handles_secrets_and_csv_values():
    assert publisher.parse_bool("true") is True
    assert publisher.parse_bool("SIM") is True
    assert publisher.parse_bool("false") is False
    assert publisher.parse_bool(None, default=False) is False


def test_is_due_requires_active_approved_ready_and_valid_shopee_link():
    assert publisher.is_due(ROW, NOW)
    assert not publisher.is_due({**ROW, "ativo": False}, NOW)
    assert not publisher.is_due({**ROW, "aprovado_publicacao": False}, NOW)
    assert not publisher.is_due({**ROW, "status_publicacao": "enviado"}, NOW)
    assert not publisher.is_due({**ROW, "link": "https://example.com/item"}, NOW)
    not_yet = {**ROW, "proxima_publicacao": (NOW + timedelta(minutes=1)).isoformat()}
    assert not publisher.is_due(not_yet, NOW)


def test_is_due_obeys_per_product_frequency():
    old = (NOW - timedelta(days=4)).isoformat()
    recent = (NOW - timedelta(days=2)).isoformat()
    assert publisher.is_due({**ROW, "ultima_publicacao": old, "frequencia_dias": 3}, NOW)
    assert not publisher.is_due({**ROW, "ultima_publicacao": recent, "frequencia_dias": 3}, NOW)


def test_publication_cooldown_uses_latest_recorded_publication():
    frame = pd.DataFrame([
        {"ultima_publicacao": (NOW - timedelta(hours=5)).isoformat()},
        {"ultima_publicacao": (NOW - timedelta(hours=2)).isoformat()},
    ])
    assert publisher.publication_cooldown_until(frame) == NOW + timedelta(hours=2)


def test_candidate_selection_returns_highest_scored_due_product():
    low = {**ROW, "id": 1, "pedidos": 0, "comissao_estimada": 0}
    high = {**ROW, "id": 2, "pedidos": 2, "comissao_estimada": 8}
    index, selected = publisher.select_candidate(pd.DataFrame([low, high]), NOW)
    assert index == 1
    assert selected["id"] == 2


def test_publication_frequency_uses_performance_thresholds():
    assert publisher.publication_frequency({"pedidos": 2, "cliques": 3}) == 2
    assert publisher.publication_frequency({"pedidos": 0, "cliques": 10}) == 4
    assert publisher.publication_frequency({"pedidos": 0, "cliques": 2}) == 3


def test_success_creates_one_linked_pin_and_persists_state():
    session = FakeSession()
    assert publisher.main(ENV, session=session, now=NOW) == 0

    assert len(session.post_calls) == 1
    url, request = session.post_calls[0]
    assert url == "https://api.pinterest.com/v5/pins"
    assert request["headers"]["Authorization"] == "Bearer test-pinterest-token"
    assert request["json"]["link"] == ROW["link"]
    assert "Link de afiliado" in request["json"]["description"]
    assert "sem custo adicional" in request["json"]["description"]
    assert session.events.index("put") < session.events.index("post")
    assert session.events[-1] == "put"
    assert len(session.put_calls) == 2
    saved = session.frame.iloc[0]
    assert saved["pinterest_pin_id"] == "pin-789"
    assert saved["pinterest_status"] == "enviado"
    assert saved["status_publicacao"] == "enviado"
    assert saved["ultima_publicacao"] == NOW.isoformat()
    assert saved["frequencia_dias"] == 4


def test_manual_product_id_targets_only_that_approved_product():
    other = {**ROW, "id": 8, "nome": "Outro produto"}
    session = FakeSession(frame=[ROW, other])
    assert publisher.main(ENV, session=session, now=NOW, product_id=8) == 0
    assert len(session.post_calls) == 1
    assert session.post_calls[0][1]["json"]["link"] == other["link"]
    assert session.frame.loc[session.frame["id"] == 7, "pinterest_status"].iloc[0] == "pendente"
    assert session.frame.loc[session.frame["id"] == 8, "pinterest_status"].iloc[0] == "enviado"


def test_global_cooldown_blocks_before_pinterest_call():
    recently_published = {**ROW, "ultima_publicacao": (NOW - timedelta(hours=1)).isoformat()}
    session = FakeSession(frame=[recently_published])
    assert publisher.main(ENV, session=session, now=NOW) == 0
    assert len(session.get_calls) == 1
    assert session.post_calls == []
    assert session.put_calls == []


def test_disabled_pinterest_fails_closed_before_github_or_pinterest_network():
    session = FakeSession()
    disabled = {**ENV, "PINTEREST_PUBLISH_ENABLED": "false"}
    with pytest.raises(RuntimeError, match="desativado por padrão"):
        publisher.main(disabled, session=session, now=NOW)
    assert not session.get_calls
    assert not session.post_calls


def test_unconfirmed_publication_fails_before_network():
    session = FakeSession()
    unconfirmed = {**ENV, "PUBLISH_CONFIRMED": "false"}
    with pytest.raises(RuntimeError, match="PUBLISH_CONFIRMED"):
        publisher.main(unconfirmed, session=session, now=NOW)
    assert not session.get_calls
    assert not session.post_calls


def test_missing_credentials_fail_before_network():
    session = FakeSession()
    incomplete = {key: value for key, value in ENV.items() if key != "PINTEREST_ACCESS_TOKEN"}
    with pytest.raises(RuntimeError, match="PINTEREST_ACCESS_TOKEN"):
        publisher.main(incomplete, session=session, now=NOW)
    assert not session.get_calls
    assert not session.post_calls


def test_preflight_failure_marks_for_review_without_posting():
    invalid = {**ROW, "imagem_url": ""}
    session = FakeSession(frame=[invalid])
    with pytest.raises(RuntimeError, match="Pin inválido antes do envio"):
        publisher.main(ENV, session=session, now=NOW)
    assert session.post_calls == []
    assert session.frame.iloc[0]["status_publicacao"] == "revisar"
    assert session.frame.iloc[0]["pinterest_status"] == "revisar"


def test_ambiguous_pinterest_failure_marks_for_review_and_redacts_token():
    session = FakeSession(pin_error=True)
    with pytest.raises(RuntimeError) as error:
        publisher.main(ENV, session=session, now=NOW)
    assert "revisão manual" in str(error.value)
    assert "test-pinterest-token" not in str(error.value)
    assert len(session.post_calls) == 1
    assert session.frame.iloc[0]["pinterest_status"] == "revisar"
    assert session.frame.iloc[0]["status_publicacao"] == "revisar"


def test_already_sent_pin_is_not_duplicated_even_if_product_is_reset():
    sent = {**ROW, "pinterest_status": "enviado", "pinterest_pin_id": "pin-existing"}
    session = FakeSession(frame=[sent])
    assert publisher.main(ENV, session=session, now=NOW) == 0
    assert not session.post_calls
    assert session.frame.iloc[0]["pinterest_pin_id"] == "pin-existing"


def test_redaction_replaces_multiple_secret_values():
    safe = publisher._redact("failed github-secret pinterest-secret", "github-secret", "pinterest-secret")
    assert "github-secret" not in safe
    assert "pinterest-secret" not in safe
    assert safe.count("[REDACTED]") == 2
