from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import pinterest_publisher as pinterest


ROW = {
    "nome": "Organizador de gaveta",
    "preco": "R$ 29,90",
    "link": "https://s.shopee.com.br/affiliate-code",
    "imagem_url": "https://down-br.img.susercontent.com/file/product.jpg",
}


def test_build_pin_payload_preserves_affiliate_link_and_discloses_commission():
    payload = pinterest.build_pin_payload(ROW, "123456789")
    assert payload["board_id"] == "123456789"
    assert payload["title"] == "Organizador de gaveta"
    assert payload["link"] == ROW["link"]
    assert payload["media_source"] == {
        "source_type": "image_url",
        "url": ROW["imagem_url"],
        "is_standard": True,
    }
    assert "R$ 29,90" in payload["description"]
    assert "Link de afiliado" in payload["description"]
    assert "sem custo adicional" in payload["description"]
    assert payload["alt_text"].startswith("Imagem do produto:")


@pytest.mark.parametrize(
    ("row", "board", "message"),
    [
        ({**ROW, "imagem_url": ""}, "123", "imagem pública HTTPS"),
        ({**ROW, "link": "https://example.com/item"}, "123", "link HTTPS válido da Shopee"),
        ({**ROW, "nome": ""}, "123", "nome e preço"),
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
