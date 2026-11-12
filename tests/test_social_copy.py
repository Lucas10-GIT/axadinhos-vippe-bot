import pytest

from pinterest_publisher import build_pin_payload
from social_copy import MAX_SOCIAL_TITLE_CHARS, SocialCopyError, build_manual_copies


ROW = {
    "nome": "Organizador de gaveta",
    "preco": "R$ 29,90",
    "categoria": "Casa & Cozinha",
    "link": "https://s.shopee.com.br/affiliate-code?utm_source=axadinhos",
    "chamada": "Uma opção prática para organizar a casa",
}


def test_channel_drafts_have_distinct_ctas_and_keep_the_affiliate_url():
    copies = build_manual_copies(ROW)

    assert ROW["link"] in copies["whatsapp"]
    assert copies["pinterest_link"] == ROW["link"]
    assert ROW["link"] not in copies["instagram"]
    assert ROW["link"] not in copies["tiktok"]
    assert copies["instagram_bio_link"] == ROW["link"]
    assert copies["tiktok_profile_link"] == ROW["link"]
    assert copies["affiliate_link"] == ROW["link"]
    assert "na bio" in copies["instagram"]
    assert "link do perfil" in copies["tiktok"]
    assert "na Shopee" in copies["whatsapp"]
    assert "CasaCozinha" in copies["hashtags"]
    assert "#Achadinhos" in copies["instagram"]
    assert "#Ofertas" in copies["tiktok"]
    for key in ("whatsapp", "instagram", "tiktok"):
        assert "Aviso de afiliado" in copies[key]
        assert "Preço e disponibilidade podem mudar" in copies[key]
    assert "Link de afiliado" in copies["pinterest_description"]
    assert "Preço e disponibilidade podem mudar" in copies["pinterest_description"]
    assert "sem custo adicional" in copies["pinterest_description"]
    for key in ("whatsapp", "instagram", "tiktok"):
        assert "sem custo extra" in copies[key]
        assert ROW["chamada"] in copies[key]


def test_pinterest_manual_copy_matches_the_actual_api_payload():
    row = {**ROW, "imagem_url": "https://images.example.com/product.jpg"}
    copies = build_manual_copies(row)
    payload = build_pin_payload(row, "123456789")

    assert copies["pinterest_title"] == payload["title"]
    assert copies["pinterest_description"] == payload["description"]
    assert copies["pinterest_link"] == payload["link"] == ROW["link"]


def test_long_product_title_is_compacted_without_changing_catalog_link_or_price():
    row = {
        **ROW,
        "nome": "Conjunto organizador modular transparente com divisórias para gavetas e armários da cozinha",
    }
    copies = build_manual_copies(row)

    assert len(copies["whatsapp"].split("\n\n")[1]) <= MAX_SOCIAL_TITLE_CHARS
    assert "R$ 29,90" in copies["instagram"]
    assert row["link"] == copies["affiliate_link"]


@pytest.mark.parametrize(
    "row",
    [
        {**ROW, "nome": ""},
        {**ROW, "preco": ""},
        {**ROW, "link": "https://example.com/product"},
        {**ROW, "link": " https://s.shopee.com.br/affiliate-code"},
        {**ROW, "link": "https://shopee.com.br:8443/product"},
        {**ROW, "chamada": "x" * 181},
    ],
)
def test_manual_copy_rejects_incomplete_or_invalid_product_data(row):
    with pytest.raises(SocialCopyError):
        build_manual_copies(row)
