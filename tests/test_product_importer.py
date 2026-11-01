from __future__ import annotations

from product_importer import (
    extract_links,
    fetch_product_metadata,
    import_product_links,
    is_shopee_url,
    link_key,
    parse_product_metadata,
)


class FakeResponse:
    def __init__(self, status_code=200, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.text = text
        self.closed = False

    def iter_content(self, chunk_size=16_384):
        yield self.text.encode("utf-8")

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses[url]


HTML = '''
<html><head>
<meta property="og:title" content="Kit de Cozinha | Shopee Brasil">
<meta property="og:image" content="https://down-br.img.susercontent.com/product.jpg">
<meta property="product:price:amount" content="78.90">
<meta property="product:price:currency" content="BRL">
</head></html>
'''


def test_extract_links_from_multiline_input_and_strip_punctuation():
    links = extract_links(
        "Confira:\nhttps://s.shopee.com.br/abc,\nhttps://shopee.com.br/item/1."
    )
    assert links == [
        "https://s.shopee.com.br/abc",
        "https://shopee.com.br/item/1",
    ]


def test_bare_shopee_host_is_upgraded_but_external_host_is_not():
    assert extract_links("shopee.com.br/product/1") == ["https://shopee.com.br/product/1"]
    assert extract_links("meli.la/2b4zSqK") == ["meli.la/2b4zSqK"]
    assert not is_shopee_url("meli.la/2b4zSqK")


def test_shopee_url_allowlist_rejects_insecure_lookalikes_and_nonstandard_ports():
    assert is_shopee_url("https://s.shopee.com.br/abc")
    assert is_shopee_url("https://shp.ee/abc")
    assert is_shopee_url("https://seller.shopee.com.br/item")
    assert not is_shopee_url("http://shopee.com.br/item")
    assert not is_shopee_url("https://shopee.com.br.evil.example/item")
    assert not is_shopee_url("https://shopee.com.br:8443/item")


def test_link_key_ignores_hostname_case_trailing_slash_and_fragment_but_keeps_query():
    assert link_key("https://SHOPEE.com.br/item/1/#top") == link_key(
        "https://shopee.com.br/item/1"
    )
    assert link_key("https://shopee.com.br/item/1?aff=a") != link_key(
        "https://shopee.com.br/item/1?aff=b"
    )


def test_parse_open_graph_metadata_and_brazilian_price():
    metadata = parse_product_metadata(HTML)
    assert metadata == {
        "nome": "Kit de Cozinha",
        "preco": "R$ 78,90",
        "imagem_url": "https://down-br.img.susercontent.com/product.jpg",
    }


def test_parse_jsonld_product_when_open_graph_values_are_missing():
    html = '''<script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Product","name":"Produto JSON",
     "image":"/produto.jpg","offers":{"price":"45.50","priceCurrency":"BRL"}}
    </script>'''
    metadata = parse_product_metadata(html)
    assert metadata["nome"] == "Produto JSON"
    assert metadata["preco"] == "R$ 45,50"
    assert metadata["imagem_url"] == "/produto.jpg"


def test_fetch_follows_only_allowlisted_redirects_and_resolves_image_urls():
    short = "https://shope.ee/short"
    final = "https://shopee.com.br/product/1"
    session = FakeSession({
        short: FakeResponse(302, {"Location": final}),
        final: FakeResponse(200, {"Content-Type": "text/html"}, HTML),
    })
    metadata = fetch_product_metadata(short, session)
    assert len(session.calls) == 2
    assert metadata["nome"] == "Kit de Cozinha"
    assert metadata["imagem_url"] == "https://down-br.img.susercontent.com/product.jpg"


def test_fetch_does_not_follow_redirect_outside_shopee():
    short = "https://shope.ee/short"
    session = FakeSession({
        short: FakeResponse(302, {"Location": "https://example.com/collect"}),
    })
    metadata = fetch_product_metadata(short, session)
    assert metadata == {"nome": "", "preco": "", "imagem_url": ""}
    assert len(session.calls) == 1


def test_import_preserves_affiliate_link_and_never_approves_or_activates():
    link = "https://s.shopee.com.br/abc?affiliate=track123"
    session = FakeSession({link: FakeResponse(200, {"Content-Type": "text/html"}, HTML)})
    result = import_product_links(link, session=session)
    assert len(result["products"]) == 1
    row = result["products"][0]
    assert row["link"] == link
    assert row["nome"] == "Kit de Cozinha"
    assert row["preco"] == "R$ 78,90"
    assert row["ativo"] is False
    assert row["aprovado_publicacao"] is False
    assert row["status_publicacao"] == "pronto"


def test_import_reports_duplicates_and_rejects_other_marketplaces_without_fetching():
    link = "https://shopee.com.br/item/1"
    external = "https://meli.la/2b4zSqK"
    session = FakeSession({})
    result = import_product_links(
        f"{link} {external}",
        existing_links=["https://SHOPEE.com.br/item/1/"],
        session=session,
    )
    assert result["products"] == []
    assert result["duplicates"] == [link]
    assert result["invalid"] == [external]
    assert session.calls == []
