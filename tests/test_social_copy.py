import pytest

from pinterest_publisher import build_pin_payload
from social_copy import MAX_SOCIAL_TITLE_CHARS, SocialCopyError, build_manual_copies

AMAZON_LINK = "https://amzn.to/affiliate-code?utm_source=axadinhos"
EBAY_LINK = "https://www.ebay.com/itm/123?campid=1234567890&mkcid=1"
ROW = {
    "nome": "Organizador de gaveta",
    "preco": "R$ 29,90",
    "categoria": "Casa & Cozinha",
    "link": AMAZON_LINK,
    "chamada": "Uma opção prática para organizar a casa",
}


def test_channel_drafts_have_distinct_ctas_and_preserve_amazon_affiliate_url():
    copies = build_manual_copies(ROW)
    assert copies["whatsapp"].find(AMAZON_LINK) >= 0
    assert copies["pinterest_link"] == AMAZON_LINK
    assert AMAZON_LINK not in copies["instagram"]
    assert AMAZON_LINK not in copies["tiktok"]
    assert copies["instagram_bio_link"] == AMAZON_LINK
    assert copies["tiktok_profile_link"] == AMAZON_LINK
    assert copies["affiliate_link"] == AMAZON_LINK
    assert "na bio" in copies["instagram"]
    assert "link do perfil" in copies["tiktok"]
    assert "na Amazon" in copies["whatsapp"]
    assert "CasaCozinha" in copies["hashtags"]
    assert "#Achadinhos" in copies["instagram"]
    assert "#Ofertas" in copies["tiktok"]
    for key in ("whatsapp", "instagram", "tiktok"):
        assert "Como participante do Programa de Associados da Amazon" in copies[key]
        assert "Consulte o preço e a disponibilidade atuais diretamente na Amazon" in copies[key]
        assert "R$ 29,90" not in copies[key]
    assert "Link de afiliado" not in copies["pinterest_description"]
    assert "Como participante do Programa de Associados da Amazon" in copies["pinterest_description"]
    assert "R$ 29,90" not in copies["pinterest_description"]
    for key in ("whatsapp", "instagram", "tiktok"):
        assert ROW["chamada"] in copies[key]


def test_pinterest_manual_copy_matches_actual_amazon_api_payload():
    row = {**ROW, "imagem_url": "https://images.example.com/product.jpg", "imagem_autorizada": True}
    copies = build_manual_copies(row)
    payload = build_pin_payload(row, "123456789")
    assert copies["pinterest_title"] == payload["title"]
    assert copies["pinterest_description"] == payload["description"]
    assert copies["pinterest_link"] == payload["link"] == AMAZON_LINK


def test_ebay_copies_require_content_approval_and_whatsapp_requires_messaging_approval():
    row = {**ROW, "link": EBAY_LINK, "epn_promocao_aprovada": True}
    copies = build_manual_copies(row)
    assert copies["whatsapp"] == ""
    assert "aprovação prévia" in copies["whatsapp_warning"]
    assert "eBay Partner Network" in copies["instagram"]
    assert "R$ 29,90" in copies["instagram"]
    assert copies["pinterest_link"] == EBAY_LINK

    copies_with_messaging_approval = build_manual_copies(
        {**row, "epn_mensageria_aprovada": True}
    )
    assert EBAY_LINK in copies_with_messaging_approval["whatsapp"]


def test_ebay_draft_is_blocked_until_written_promotion_approval():
    with pytest.raises(SocialCopyError, match="aprovação escrita"):
        build_manual_copies({**ROW, "link": EBAY_LINK})


def test_long_product_title_is_compacted_without_changing_catalog_link():
    row = {
        **ROW,
        "nome": "Conjunto organizador modular transparente com divisórias para gavetas e armários da cozinha",
    }
    copies = build_manual_copies(row)
    assert len(copies["whatsapp"].split("\n\n")[1]) <= MAX_SOCIAL_TITLE_CHARS
    assert "R$ 29,90" not in copies["instagram"]
    assert row["link"] == copies["affiliate_link"]


@pytest.mark.parametrize(
    "row",
    [
        {**ROW, "nome": ""},
        {**ROW, "link": "https://example.com/product"},
        {**ROW, "link": "https://www.amazon.com.br/dp/B000000000"},
        {**ROW, "link": " https://amzn.to/affiliate-code"},
        {**ROW, "link": "https://www.ebay.com/itm/123"},
        {**ROW, "chamada": "x" * 181},
    ],
)
def test_manual_copy_rejects_incomplete_or_invalid_product_data(row):
    with pytest.raises(SocialCopyError):
        build_manual_copies(row)
