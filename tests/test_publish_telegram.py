import base64
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

import publish_telegram as bot


NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def approved_product(**overrides):
    row = {
        "id": 1,
        "nome": "Produto de teste",
        "preco": "R$ 29,90",
        "link": "https://shopee.com.br/producto-demo",
        "imagem_url": "",
        "categoria": "Casa",
        "comissao": 5,
        "ativo": True,
        "aprovado_publicacao": True,
        "status_publicacao": "pronto",
        "frequencia_dias": 3,
        "cliques": 20,
        "pedidos": 2,
        "comissao_estimada": 4,
        "ultima_publicacao": "",
        "proxima_publicacao": "",
        "ultima_tentativa": "",
        "telegram_message_id": "",
    }
    row.update(overrides)
    return row


def test_parse_bool_handles_csv_false_strings():
    assert bot.parse_bool("False") is False
    assert bot.parse_bool("0") is False
    assert bot.parse_bool("TRUE") is True
    assert bot.parse_bool("sim") is True


def test_due_date_handles_naive_and_timezone_aware_values():
    row = approved_product(ultima_publicacao="2026-10-25T12:00:00")
    assert bot.is_due(row, NOW) is True
    row["proxima_publicacao"] = "2026-10-28T12:00:00Z"
    assert bot.is_due(row, NOW) is True
    row["proxima_publicacao"] = "2026-10-30T12:00:00Z"
    assert bot.is_due(row, NOW) is False


def test_unapproved_or_inactive_products_are_never_selected():
    df = pd.DataFrame([
        approved_product(nome="Desativado", ativo="False", pedidos=10, cliques=50),
        approved_product(nome="Aguardando aprovação", aprovado_publicacao="False", pedidos=100),
    ])
    assert bot.select_candidate(df, NOW) is None


def test_unreviewed_publication_state_is_not_selected():
    df = pd.DataFrame([approved_product(status_publicacao="revisar")])
    assert bot.select_candidate(df, NOW) is None


def test_select_candidate_chooses_highest_score_among_due_approved_products():
    df = pd.DataFrame([
        approved_product(nome="Baixo", pedidos=0, cliques=0, comissao_estimada=0),
        approved_product(nome="Vencedor", pedidos=2, cliques=20, comissao_estimada=4),
        approved_product(
            nome="Aguardando", ultima_publicacao="2026-10-28T12:00:00Z",
            proxima_publicacao="2026-11-04T12:00:00Z", pedidos=100,
        ),
    ])
    selected = bot.select_candidate(df, NOW)
    assert selected is not None
    assert selected[1]["nome"] == "Vencedor"


def test_score_treats_invalid_and_nan_numbers_as_zero():
    assert bot.score({"pedidos": float("nan"), "cliques": "bad", "comissao_estimada": None}) == 0


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"pedidos": 2, "cliques": 0}, 2),
        ({"pedidos": 1, "cliques": 10}, 4),
        ({"pedidos": 0, "cliques": 2}, 3),
    ],
)
def test_publication_frequency(row, expected):
    assert bot.publication_frequency(row) == expected


def test_product_requires_name_price_and_https_link():
    assert bot.is_publishable(approved_product()) is True
    assert bot.is_publishable(approved_product(link="http://shopee.com.br/item")) is False
    assert bot.is_publishable(approved_product(link="javascript:alert(1)")) is False
    assert bot.is_publishable(approved_product(link="https://example.com/item")) is False
    assert bot.is_publishable(approved_product(link="https://s.shopee.com.br/abc")) is True
    assert bot.is_publishable(approved_product(preco="")) is False


def test_ad_escapes_user_supplied_html_and_discloses_affiliate_link():
    message = bot.ad(approved_product(
        nome="Oferta <teste>", preco="R$ 10 & frete",
        link="https://shopee.com.br/item?a=1&b=2",
    ))
    assert "Oferta &lt;teste&gt;" in message
    assert "R$ 10 &amp; frete" in message
    assert "a=1&amp;b=2" in message
    assert "Link de afiliado" in message
    assert "sem custo adicional" in message


def test_telegram_api_200_with_ok_false_is_still_failure():
    response = SimpleNamespace(
        raise_for_status=Mock(),
        json=lambda: {"ok": False, "description": "chat not found"},
    )
    session = SimpleNamespace(post=Mock(return_value=response))
    with pytest.raises(RuntimeError, match="chat not found"):
        bot.send_telegram(approved_product(), "token", "chat", session)
    session.post.assert_called_once()


def test_invalid_product_is_rejected_before_network_call():
    session = SimpleNamespace(post=Mock())
    with pytest.raises(ValueError, match="Produto sem nome"):
        bot.send_telegram(approved_product(link="http://example.com"), "token", "chat", session)
    session.post.assert_not_called()


def test_telegram_send_uses_photo_when_image_url_is_valid():
    response = SimpleNamespace(raise_for_status=Mock(), json=lambda: {"ok": True, "result": {"message_id": 1}})
    session = SimpleNamespace(post=Mock(return_value=response))
    result = bot.send_telegram(
        approved_product(imagem_url="https://example.com/image.jpg"),
        "token",
        "chat",
        session,
    )
    assert result["ok"] is True
    assert session.post.call_args.args[0].endswith("/sendPhoto")


def test_main_requires_explicit_publish_confirmation_before_network():
    with pytest.raises(RuntimeError, match="PUBLISH_CONFIRMED=true"):
        bot.main(environ={}, session=object())


def test_main_rejects_missing_secrets_before_network_calls():
    with pytest.raises(RuntimeError, match="Secrets/variáveis ausentes"):
        bot.main(environ={"PUBLISH_CONFIRMED": "true"}, session=object())


class FakeGitHubTelegramSession:
    """In-memory GitHub Contents API and Telegram responses; never uses network."""

    def __init__(self, frame, telegram_result=None):
        self.csv_text = frame.to_csv(index=False)
        self.sha = "sha-inicial"
        self.telegram_result = telegram_result or {"ok": True, "result": {"message_id": 42}}
        self.put_frames = []
        self.events = []

    def get(self, url, **kwargs):
        self.events.append("get")
        payload = {
            "content": base64.b64encode(self.csv_text.encode("utf-8")).decode("ascii"),
            "sha": self.sha,
        }
        return SimpleNamespace(raise_for_status=Mock(), json=lambda: payload)

    def put(self, url, headers, json, timeout):
        self.events.append("put")
        self.csv_text = base64.b64decode(json["content"]).decode("utf-8")
        self.sha = f"sha-{len(self.put_frames) + 1}"
        self.put_frames.append(pd.read_csv(io.StringIO(self.csv_text)))
        payload = {"content": {"sha": self.sha}}
        return SimpleNamespace(raise_for_status=Mock(), json=lambda: payload)

    def post(self, url, data, timeout):
        self.events.append("post")
        response = {"ok": True, "result": {"message_id": 42}} if self.telegram_result is None else self.telegram_result
        return SimpleNamespace(raise_for_status=Mock(), json=lambda: response)


def test_main_reserves_product_before_send_and_marks_sent_after_success(capsys):
    frame = pd.DataFrame([approved_product()])
    session = FakeGitHubTelegramSession(frame, telegram_result=None)
    env = {
        "PUBLISH_CONFIRMED": "true",
        "GITHUB_TOKEN": "github-test-token",
        "TELEGRAM_BOT_TOKEN": "telegram-test-token",
        "TELEGRAM_CHAT_ID": "channel-test",
    }

    assert bot.main(environ=env, session=session, now=NOW) == 0
    assert session.events.index("put") < session.events.index("post") < len(session.events) - 1
    assert len(session.put_frames) == 2
    assert session.put_frames[0].loc[0, "status_publicacao"] == "enviando"
    final = session.put_frames[1].loc[0]
    assert final["status_publicacao"] == "enviado"
    assert final["ultima_publicacao"] == NOW.isoformat()
    assert final["proxima_publicacao"] == "2026-10-31T12:00:00+00:00"
    assert str(final["telegram_message_id"]) == "42"
    assert "Publicado: Produto de teste" in capsys.readouterr().out


def test_failed_or_ambiguous_send_is_marked_for_review_and_not_retried():
    frame = pd.DataFrame([approved_product()])
    session = FakeGitHubTelegramSession(frame, telegram_result={
        "ok": False,
        "description": "permission denied; token=telegram-test-token",
    })
    env = {
        "PUBLISH_CONFIRMED": "true",
        "GITHUB_TOKEN": "github-test-token",
        "TELEGRAM_BOT_TOKEN": "telegram-test-token",
        "TELEGRAM_CHAT_ID": "channel-test",
    }

    with pytest.raises(RuntimeError, match="marcado para revisão manual") as error:
        bot.main(environ=env, session=session, now=NOW)
    assert "telegram-test-token" not in str(error.value)
    saved_after_failure = pd.read_csv(io.StringIO(session.csv_text))
    assert saved_after_failure.loc[0, "status_publicacao"] == "revisar"
    post_count = session.events.count("post")

    assert bot.main(environ=env, session=session, now=NOW + pd.Timedelta(days=1).to_pytimedelta()) == 0
    assert session.events.count("post") == post_count


def test_error_message_redacts_tokens():
    assert bot._redact("failure telegram-secret", "telegram-secret") == "failure [REDACTED]"
