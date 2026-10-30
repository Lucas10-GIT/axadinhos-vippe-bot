from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

import publish_telegram as bot


NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def test_parse_bool_handles_csv_false_strings():
    assert bot.parse_bool("False") is False
    assert bot.parse_bool("0") is False
    assert bot.parse_bool("TRUE") is True
    assert bot.parse_bool("sim") is True


def test_due_date_handles_naive_and_timezone_aware_values():
    row = {"ativo": "TRUE", "frequencia_dias": "3", "ultima_publicacao": "2026-10-25T12:00:00"}
    assert bot.is_due(row, NOW) is True
    row["ultima_publicacao"] = "2026-10-28T12:00:00Z"
    assert bot.is_due(row, NOW) is False


def test_inactive_products_are_never_selected():
    df = pd.DataFrame([
        {"nome": "Desativado", "ativo": "False", "pedidos": 10, "cliques": 50},
        {"nome": "Ativo", "ativo": "True", "pedidos": 0, "cliques": 0},
    ])
    selected = bot.select_candidate(df, NOW)
    assert selected is not None
    assert selected[1]["nome"] == "Ativo"


def test_select_candidate_chooses_highest_score_among_due_products():
    df = pd.DataFrame([
        {"nome": "Baixo", "ativo": True, "ultima_publicacao": "", "pedidos": 0, "cliques": 0},
        {"nome": "Vencedor", "ativo": True, "ultima_publicacao": "", "pedidos": 2, "cliques": 20, "comissao_estimada": 4},
        {"nome": "Aguardando", "ativo": True, "frequencia_dias": 7, "ultima_publicacao": "2026-10-28T12:00:00Z", "pedidos": 100},
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


def test_ad_escapes_user_supplied_html():
    message = bot.ad({"nome": "Oferta <teste>", "preco": "R$ 10 & frete", "link": "https://shopee.com/item?a=1&b=2"})
    assert "Oferta &lt;teste&gt;" in message
    assert "R$ 10 &amp; frete" in message
    assert "a=1&amp;b=2" in message


def test_telegram_api_200_with_ok_false_is_still_failure():
    response = SimpleNamespace(
        raise_for_status=Mock(),
        json=lambda: {"ok": False, "description": "chat not found"},
    )
    session = SimpleNamespace(post=Mock(return_value=response))
    with pytest.raises(RuntimeError, match="chat not found"):
        bot.send_telegram({"nome": "Teste", "link": "https://example.com"}, "token", "chat", session)
    session.post.assert_called_once()


def test_telegram_send_uses_photo_when_image_url_exists():
    response = SimpleNamespace(raise_for_status=Mock(), json=lambda: {"ok": True, "result": {"message_id": 1}})
    session = SimpleNamespace(post=Mock(return_value=response))
    result = bot.send_telegram(
        {"nome": "Teste", "link": "https://example.com", "imagem_url": "https://example.com/image.jpg"},
        "token",
        "chat",
        session,
    )
    assert result["ok"] is True
    assert session.post.call_args.args[0].endswith("/sendPhoto")


def test_main_rejects_missing_secrets_before_network_calls():
    with pytest.raises(RuntimeError, match="Secrets/variáveis ausentes"):
        bot.main(environ={}, session=object())
