import base64
import io
from datetime import datetime, timedelta, timezone

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
    "pinterest_status": "pendente",
    "pinterest_pin_id": "",
}
ENV_PINTEREST = {
    "PUBLISH_CONFIRMED": "true",
    "PINTEREST_PUBLISH_ENABLED": "true",
    "GITHUB_TOKEN": "test-github-token",
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
    """In-memory GitHub and Pinterest APIs; no request leaves the test process."""

    def __init__(self, frame=None, pinterest_error=False):
        self.frame = pd.DataFrame([ROW] if frame is None else frame).copy()
        self.sha = "sha-initial"
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
        payload = {"content": base64.b64encode(csv_bytes).decode("ascii"), "sha": self.sha}
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
        self.events.append("pinterest")
        assert url == "https://api.pinterest.com/v5/pins"
        if self.pinterest_error:
            return FakeResponse({"message": "permission denied"}, status=403)
        return FakeResponse({"id": "pin-789"})


def test_parse_bool_handles_secrets_and_csv_values():
    assert publisher.parse_bool("true") is True
    assert publisher.parse_bool("SIM") is True
    assert publisher.parse_bool("false") is False
    assert publisher.parse_bool(None, default=False) is False


def test_enabled_channels_only_returns_explicit_pinterest_opt_in():
    assert publisher.enabled_channels({"PINTEREST_PUBLISH_ENABLED": "true"}) == ["pinterest"]
    assert publisher.enabled_channels({"PINTEREST_PUBLISH_ENABLED": "false"}) == []
    assert publisher._normalise_channels(["whatsapp", "instagram", "tiktok"]) == ()


def test_is_due_requires_active_approved_ready_and_valid_shopee_link():
    assert publisher.is_due(ROW, NOW, ["pinterest"])
    assert not publisher.is_due({**ROW, "ativo": False}, NOW, ["pinterest"])
    assert not publisher.is_due({**ROW, "aprovado_publicacao": False}, NOW, ["pinterest"])
    assert not publisher.is_due({**ROW, "status_publicacao": "revisar"}, NOW, ["pinterest"])
    assert not publisher.is_due({**ROW, "link": "https://example.com/item"}, NOW, ["pinterest"])
    not_yet = {**ROW, "proxima_publicacao": (NOW + timedelta(minutes=1)).isoformat()}
    assert not publisher.is_due(not_yet, NOW, ["pinterest"])


def test_is_due_obeys_frequency_and_blocks_completed_items():
    old = (NOW - timedelta(days=4)).isoformat()
    recent = (NOW - timedelta(days=2)).isoformat()
    assert publisher.is_due({**ROW, "ultima_publicacao": old, "frequencia_dias": 3}, NOW, ["pinterest"])
    assert not publisher.is_due({**ROW, "ultima_publicacao": recent, "frequencia_dias": 3}, NOW, ["pinterest"])
    sent = {
        **ROW,
        "status_publicacao": "enviado",
        "pinterest_status": "enviado",
        "pinterest_pin_id": "pin-previously-sent",
        "ultima_publicacao": NOW.isoformat(),
    }
    assert not publisher.is_due(sent, NOW, ["pinterest"])


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


def test_publication_frequency_uses_performance_thresholds():
    assert publisher.publication_frequency({"pedidos": 2, "cliques": 3}) == 2
    assert publisher.publication_frequency({"pedidos": 0, "cliques": 10}) == 4
    assert publisher.publication_frequency({"pedidos": 0, "cliques": 2}) == 3


def test_pinterest_publishes_once_with_original_affiliate_link_and_checkpoints():
    session = FakeSession()
    assert publisher.main(ENV_PINTEREST, session=session, now=NOW) == 0

    assert len(session.post_calls) == 1
    url, request = session.post_calls[0]
    assert url == "https://api.pinterest.com/v5/pins"
    assert request["json"]["link"] == AFFILIATE_URL
    assert "Link de afiliado" in request["json"]["description"]
    assert session.events == ["get", "put", "pinterest", "put", "put"]
    assert len(session.put_calls) == 3
    saved = session.frame.iloc[0]
    assert saved["pinterest_pin_id"] == "pin-789"
    assert saved["pinterest_status"] == "enviado"
    assert saved["status_publicacao"] == "enviado"
    assert saved["ultima_publicacao"] == NOW.isoformat()
    assert saved["frequencia_dias"] == 4


def test_existing_pin_receipt_prevents_duplicate_post():
    sent = {
        **ROW,
        "status_publicacao": "pronto",
        "pinterest_status": "enviado",
        "pinterest_pin_id": "pin-already-sent",
    }
    session = FakeSession(frame=[sent])
    assert publisher.main(ENV_PINTEREST, session=session, now=NOW) == 0
    assert not session.post_calls


def test_pinterest_failure_marks_review_and_prevents_automatic_retry():
    session = FakeSession(pinterest_error=True)
    with pytest.raises(RuntimeError, match="revisão manual") as error:
        publisher.main(ENV_PINTEREST, session=session, now=NOW)

    assert "test-pinterest-token" not in str(error.value)
    assert session.events == ["get", "put", "pinterest", "put"]
    saved = session.frame.iloc[0]
    assert saved["pinterest_status"] == "revisar"
    assert saved["status_publicacao"] == "revisar"
    post_count = len(session.post_calls)
    assert publisher.main(ENV_PINTEREST, session=session, now=NOW + timedelta(days=1)) == 0
    assert len(session.post_calls) == post_count


def test_invalid_pin_payload_fails_before_post_and_marks_review():
    invalid = {**ROW, "imagem_url": ""}
    session = FakeSession(frame=[invalid])
    with pytest.raises(RuntimeError, match="Pré-validação do Pinterest"):
        publisher.main(ENV_PINTEREST, session=session, now=NOW)
    assert not session.post_calls
    assert session.frame.iloc[0]["pinterest_status"] == "revisar"
    assert session.frame.iloc[0]["status_publicacao"] == "revisar"


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
    assert publisher.main(ENV_PINTEREST, session=session, now=NOW) == 0
    assert len(session.get_calls) == 1
    assert not session.post_calls
    assert not session.put_calls


def test_no_channel_opt_in_fails_before_github_or_platform_network():
    session = FakeSession()
    env = {**ENV_PINTEREST, "PINTEREST_PUBLISH_ENABLED": "false"}
    with pytest.raises(RuntimeError, match="habilite explicitamente Pinterest"):
        publisher.main(env, session=session, now=NOW)
    assert not session.get_calls
    assert not session.post_calls


def test_missing_credentials_fail_before_github_network():
    session = FakeSession()
    env = {key: value for key, value in ENV_PINTEREST.items() if key != "PINTEREST_ACCESS_TOKEN"}
    with pytest.raises(RuntimeError, match="PINTEREST_ACCESS_TOKEN"):
        publisher.main(env, session=session, now=NOW)
    assert not session.get_calls
    assert not session.post_calls


def test_unconfirmed_or_unapproved_publication_fails_closed():
    session = FakeSession()
    with pytest.raises(RuntimeError, match="PUBLISH_CONFIRMED"):
        publisher.main({**ENV_PINTEREST, "PUBLISH_CONFIRMED": "false"}, session=session, now=NOW)
    assert not session.get_calls

    unapproved = {**ROW, "aprovado_publicacao": False}
    session = FakeSession(frame=[unapproved])
    assert publisher.main(ENV_PINTEREST, session=session, now=NOW) == 0
    assert not session.post_calls


def test_ambiguous_completed_state_without_pin_receipt_is_blocked_for_review():
    legacy = {**ROW, "status_publicacao": "enviado"}
    normalized = publisher._ensure_state_columns(pd.DataFrame([legacy]))
    assert normalized.iloc[0]["status_publicacao"] == "revisar"
    session = FakeSession(frame=[legacy])
    assert publisher.main(ENV_PINTEREST, session=session, now=NOW) == 0
    assert not session.post_calls


def test_redaction_replaces_github_and_pinterest_secrets():
    safe = publisher._redact(
        "failed github-secret pinterest-secret",
        "github-secret", "pinterest-secret",
    )
    assert "github-secret" not in safe
    assert "pinterest-secret" not in safe
    assert safe.count("[REDACTED]") == 2
