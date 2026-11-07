import pytest

from social_copy import SocialCopyError, build_manual_copies


ROW = {
    "nome": "Organizador de gaveta",
    "preco": "R$ 29,90",
    "link": "https://s.shopee.com.br/affiliate-code?utm_source=axadinhos",
    "chamada": "Uma opção prática para organizar a casa",
}


def test_manual_copies_keep_original_affiliate_url_and_disclosure():
    copies = build_manual_copies(ROW)

    assert ROW["link"] in copies["whatsapp"]
    assert ROW["link"] in copies["instagram"]
    assert copies["affiliate_link"] == ROW["link"]
    for key in ("whatsapp", "instagram"):
        assert "Aviso de afiliado" in copies[key]
        assert "sem custo adicional" in copies[key]
        assert "Preço e disponibilidade podem mudar" in copies[key]
        assert ROW["chamada"] in copies[key]


def test_tiktok_copy_keeps_affiliate_url_separate_from_post_text():
    copies = build_manual_copies(ROW)

    assert copies["affiliate_link"] == ROW["link"]
    assert ROW["link"] not in copies["tiktok"]
    assert "Conteúdo promocional" in copies["tiktok"]
    assert "Aviso de afiliado" in copies["tiktok"]
    assert "divulgação de conteúdo comercial" in copies["tiktok"]
    assert ROW["chamada"] in copies["tiktok"]


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
