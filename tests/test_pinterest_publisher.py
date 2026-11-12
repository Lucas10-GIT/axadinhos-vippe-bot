from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import pinterest_publisher as pinterest

AMAZON_LINK = "https://amzn.to/affiliate-code"
EBAY_LINK = "https://www.ebay.com/itm/123?campid=1234567890&mkcid=1"
ROW = {
    "nome": "Organizador de gaveta",
    "preco": "R$ 29,90",
    "link": AMAZON_LINK,
    "imagem_url": "https://images.example.com/file/product.jpg",
    "imagem_autorizada": True,
}


def test_build_pin_payload_preserves_amazon_link_and_includes_exact_disclosure_without_static_price():
    payload = pinterest.build_pin_payload(ROW, "123456789")
    assert payload["board_id"] == "123456789"
    assert payload["title"] == "Organizador de gaveta"
    assert payload["link"] == ROW["link"]
    assert payload["media_source"] == {
        "source_type": "image_url",
        "url": ROW["imagem_url"],
        "is_standard": True,
    }
    assert "R$ 29,90" not in payload["description"]
    assert "Consulte o preço e a disponibilidade atuais diretamente na Amazon" in payload["description"]
    assert "Como participante do Programa de Associados da Amazon" in payload["description"]
    assert payload["alt_text"].startswith("Imagem do produto:")


def test_build_pin_payload_includes_callout_and_keeps_amazon_disclosure():
    callout = "Uma opção prática para organizar a casa"
    payload = pinterest.build_pin_payload({**ROW, "chamada": callout}, "123456789")
    assert payload["description"].startswith(callout + "\n\n")
    assert ROW["link"] == payload["link"]
    assert "Como participante do Programa de Associados da Amazon" in payload["description"]


def test_amazon_pin_rejects_static_price_entered_in_custom_callout():
    with pytest.raises(pinterest.PinterestPublisherError, match="preço estático"):
        pinterest.build_pin_payload(
            {**ROW, "chamada": "Aproveite por R$ 29,90 hoje"},
            "123456789",
        )


def test_build_ebay_pin_requires_approval_and_uses_ebay_disclosure():
    row = {**ROW, "link": EBAY_LINK, "epn_promocao_aprovada": True}
    payload = pinterest.build_pin_payload(row, "123456789")
    assert payload["link"] == EBAY_LINK
    assert "eBay Partner Network" in payload["description"]
    assert "R$ 29,90" in payload["description"]
    with pytest.raises(pinterest.PinterestPublisherError, match="aprovação escrita"):
        pinterest.build_pin_payload({**row, "epn_promocao_aprovada": "false"}, "123456789")


def test_build_pin_payload_rejects_overlong_callout_and_never_truncates_disclosure():
    with pytest.raises(pinterest.PinterestPublisherError, match="180 caracteres"):
        pinterest.build_pin_payload({**ROW, "chamada": "x" * 181}, "123456789")
    with pytest.raises(pinterest.PinterestPublisherError, match="limite de 800"):
        pinterest.build_pin_payload({**ROW, "nome": "x" * 900}, "123456789")


@pytest.mark.parametrize(
    ("row", "board", "message"),
    [
        ({**ROW, "imagem_url": ""}, "123", "imagem pública HTTPS"),
        ({**ROW, "link": "https://example.com/item"}, "123", "link afiliado Amazon/EPN válido"),
        ({**ROW, "nome": ""}, "123", "nome revisado"),
        ({**ROW, "imagem_autorizada": False}, "123", "direito de usar"),
        (ROW, "board-x", "Board ID"),
    ],
)
def test_build_pin_payload_rejects_incomplete_or_unsafe_inputs(row, board, message):
    with pytest.raises(pinterest.PinterestPublisherError, match=message):
        pinterest.build_pin_payload(row, board)


def test_send_pin_calls_official_api_and_returns_created_pin_id():
    response = SimpleNamespace(raise_for_status=Mock(), json=lambda: {"id": "pin-789"})
    session = SimpleNamespace(post=Mock(return_value=response))
    result = pinterest.send_pinterest_pin(ROW, "private-token", "123", session=session)
    assert result["id"] == "pin-789"
    args, kwargs = session.post.call_args
    assert args[0] == pinterest.CREATE_PIN_URL
    assert kwargs["headers"]["Authorization"] == "Bearer private-token"
    assert kwargs["json"]["link"] == ROW["link"]
    assert kwargs["timeout"] == 30


def test_send_pin_does_not_echo_token_in_http_errors():
    def fail(*args, **kwargs):
        raise RuntimeError("403 token private-token rejected")

    session = SimpleNamespace(post=Mock(side_effect=fail))
    with pytest.raises(pinterest.PinterestPublisherError) as error:
        pinterest.send_pinterest_pin(ROW, "private-token", "123", session=session)
    assert "private-token" not in str(error.value)


def test_send_pin_requires_token_before_network():
    session = SimpleNamespace(post=Mock())
    with pytest.raises(pinterest.PinterestPublisherError, match="PINTEREST_ACCESS_TOKEN"):
        pinterest.send_pinterest_pin(ROW, "", "123", session=session)
    session.post.assert_not_called()
