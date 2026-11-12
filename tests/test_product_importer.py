from affiliate_links import affiliate_link_error, is_valid_affiliate_link, link_key
from product_importer import extract_links, import_product_links

AMAZON = "https://www.amazon.com.br/dp/B000000000?tag=axadinhos-20&linkCode=ll1"
AMAZON_SHORT = "https://amzn.to/abc123"
EBAY = "https://www.ebay.com/itm/123456?mkevt=1&mkcid=1&mkrid=711-53200-19255-0&campid=1234567890&toolid=10050"
EBAY_SHORT = "https://ebay.us/xyz123"


def test_extract_links_from_multiline_text_without_rewriting_urls():
    assert extract_links(f"Confira:\n{AMAZON},\n{EBAY}.") == [AMAZON, EBAY]


def test_amazon_affiliate_urls_require_tag_or_official_short_domain():
    assert is_valid_affiliate_link(AMAZON)
    assert is_valid_affiliate_link(AMAZON_SHORT)
    assert "tag" in affiliate_link_error("https://www.amazon.com.br/dp/B000000000")
    assert not is_valid_affiliate_link("https://amazon.com.br.evil.example/dp/B000000000?tag=x")
    assert not is_valid_affiliate_link("http://www.amazon.com.br/dp/B000000000?tag=x")
    assert not is_valid_affiliate_link("https://www.amazon.com.br:8443/dp/B000000000?tag=x")


def test_ebay_direct_links_require_ten_digit_campaign_id_or_official_short_domain():
    assert is_valid_affiliate_link(EBAY)
    assert is_valid_affiliate_link(EBAY_SHORT)
    assert "campid" in affiliate_link_error("https://www.ebay.com/itm/123456")
    assert not is_valid_affiliate_link("https://ebay.com.evil.example/itm/123?campid=1234567890")


def test_link_key_normalizes_host_case_and_fragment_but_preserves_attribution_query():
    assert link_key("https://WWW.AMAZON.COM.BR/dp/a/?tag=x#top") == link_key(
        "https://www.amazon.com.br/dp/a?tag=x"
    )
    assert link_key("https://www.amazon.com.br/dp/a?tag=x") != link_key(
        "https://www.amazon.com.br/dp/a?tag=y"
    )


def test_import_preserves_affiliate_url_and_creates_unapproved_manual_draft():
    result = import_product_links(f"{AMAZON}\n{EBAY}")
    assert len(result["products"]) == 2
    amazon, ebay = result["products"]
    assert amazon["link"] == AMAZON
    assert amazon["programa"] == "amazon"
    assert amazon["nome"] == amazon["preco"] == amazon["imagem_url"] == ""
    assert amazon["ativo"] is False
    assert amazon["aprovado_publicacao"] is False
    assert amazon["imagem_autorizada"] is False
    assert amazon["pinterest_status"] == "pendente"
    assert ebay["link"] == EBAY
    assert ebay["programa"] == "ebay"
    assert ebay["epn_promocao_aprovada"] is False
    assert ebay["epn_mensageria_aprovada"] is False
    assert result["incomplete"] == [AMAZON, EBAY]
    assert all(item["status"] == "revisao_manual" for item in result["diagnostics"])


def test_import_never_fetches_pages_and_preserves_short_links_exactly():
    result = import_product_links(f"{AMAZON_SHORT}\n{EBAY_SHORT}")
    assert [row["link"] for row in result["products"]] == [AMAZON_SHORT, EBAY_SHORT]
    assert all(not row["nome"] and not row["preco"] for row in result["products"])


def test_import_deduplicates_without_losing_tracking_parameters_and_rejects_untracked_urls():
    result = import_product_links(
        f"{AMAZON}\n{AMAZON}\nhttps://www.amazon.com.br/dp/B000000000\nhttps://example.com/item",
        existing_links=[AMAZON],
    )
    assert result["products"] == []
    assert result["duplicates"] == [AMAZON]
    assert result["invalid"] == [
        "https://www.amazon.com.br/dp/B000000000",
        "https://example.com/item",
    ]


def test_import_limits_each_batch_to_twenty_links():
    links = "\n".join(f"https://amzn.to/link{i}" for i in range(22))
    result = import_product_links(links)
    assert len(result["products"]) == 20
    assert result["limit_reached"] is True
    assert result["ignored_over_limit"] == 2
