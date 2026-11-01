from __future__ import annotations

import hashlib
import json

import pytest

from shopee_affiliate_api import (
    API_URL,
    ShopeeAffiliateAPIError,
    build_authorization,
    check_connection,
    extract_item_id,
    lookup_product_by_item_id,
)


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_build_authorization_signs_the_exact_serialized_payload():
    payload = '{"query":"{ ping }"}'
    expected = hashlib.sha256(b"app1231700000000" + payload.encode() + b"secret456").hexdigest()
    header = build_authorization("app123", "secret456", payload, timestamp=1_700_000_000)
    assert header == (
        "SHA256 Credential=app123,Timestamp=1700000000,Signature=" + expected
    )


def test_test_connection_makes_a_small_read_only_query():
    session = FakeSession(FakeResponse({
        "data": {"productOfferV2": {"nodes": [], "pageInfo": {"page": 1}}}
    }))
    check_connection("app", "secret", session=session)
    url, request = session.calls[0]
    assert url == API_URL
    payload = json.loads(request["data"])
    assert "productOfferV2" in payload["query"]
    assert "limit: 1" in payload["query"]
    assert request["headers"]["Authorization"].startswith("SHA256 Credential=app,")
    assert request["timeout"]


def test_lookup_maps_api_values_and_formats_price_range():
    session = FakeSession(FakeResponse({
        "data": {"productOfferV2": {"nodes": [{
            "itemId": 456,
            "productName": "Fone sem fio",
            "productLink": "https://shopee.com.br/product/123/456",
            "offerLink": "https://s.shopee.com.br/affiliate",
            "imageUrl": "https://img.example/fone.jpg",
            "priceMin": "49.90",
            "priceMax": "59.90",
            "commissionRate": "0.05",
        }]}}
    }))
    result = lookup_product_by_item_id(456, "app", "secret", session=session)
    assert result["nome"] == "Fone sem fio"
    assert result["preco"] == "R$ 49,90–R$ 59,90"
    assert result["imagem_url"] == "https://img.example/fone.jpg"
    assert result["categoria"] == ""
    assert result["api_offer_link"] == "https://s.shopee.com.br/affiliate"


def test_extract_item_id_from_canonical_and_short_product_paths_only():
    assert extract_item_id("https://shopee.com.br/Fone-i.123.456?x=1") == 456
    assert extract_item_id("https://shopee.com.br/product/123/456") == 456
    assert extract_item_id("https://shopee.com.br/item?itemId=456") == 456
    assert extract_item_id("https://shopee.com.br.evil.example/Fone-i.123.456") is None
    assert extract_item_id("https://shp.ee/short") is None


def test_api_error_does_not_echo_secret_or_raw_server_message():
    session = FakeSession(FakeResponse({
        "errors": [{"message": "secret456 leaked?", "extensions": {"code": 10020}}]
    }))
    with pytest.raises(ShopeeAffiliateAPIError) as error:
        check_connection("app123", "secret456", session=session)
    assert "10020" in str(error.value)
    assert "secret456" not in str(error.value)
    assert "leaked" not in str(error.value)


class CombinedSession(FakeSession):
    def __init__(self, api_response, page_response):
        super().__init__(api_response)
        self.page_response = page_response
        self.get_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.page_response


def test_import_uses_affiliate_api_fields_and_preserves_original_link_as_inactive():
    from product_importer import import_product_links

    affiliate_link = "https://shopee.com.br/Fone-Bluetooth-i.123.456?affiliate=track-me"
    page_html = '''<meta property="og:title" content="Nome pela página">
      <meta property="product:price:amount" content="10.00">
      <meta property="product:price:currency" content="BRL">
      <meta property="product:category" content="Eletrônicos">
      <meta property="og:image" content="https://img.example/from-page.jpg">'''

    class PageResponse:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        text = page_html
        encoding = "utf-8"

        def iter_content(self, chunk_size=16_384):
            yield self.text.encode("utf-8")

        def close(self):
            pass

    session = CombinedSession(FakeResponse({
        "data": {"productOfferV2": {"nodes": [{
            "itemId": 456,
            "productName": "Nome pela API",
            "productLink": "https://shopee.com.br/item/123/456",
            "offerLink": "https://s.shopee.com.br/new-affiliate",
            "imageUrl": "https://img.example/from-api.jpg",
            "priceMin": "29.90",
            "priceMax": "29.90",
        }]}}
    }), PageResponse())

    result = import_product_links(
        affiliate_link,
        session=session,
        affiliate_api_credentials=("app", "secret"),
    )
    row = result["products"][0]
    assert row["link"] == affiliate_link
    assert row["nome"] == "Nome pela API"
    assert row["preco"] == "R$ 29,90"
    assert row["imagem_url"] == "https://img.example/from-api.jpg"
    assert row["categoria"] == "Eletrônicos"
    assert row["ativo"] is False
    assert row["aprovado_publicacao"] is False
    assert result["diagnostics"][0]["api_used"] is True


def test_import_resolves_safe_shopee_short_link_for_api_but_keeps_original_affiliate_url():
    from product_importer import import_product_links

    original = "https://shope.ee/affiliate-short?ref=campaign"
    final = "https://shopee.com.br/Fone-i.123.456"
    html = '<meta property="og:title" content="Nome HTML"><meta property="product:price:amount" content="10">'

    class RedirectResponse:
        status_code = 302
        headers = {"Location": final}
        text = ""

        def close(self):
            pass

    class PageResponse:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        text = html
        encoding = "utf-8"

        def iter_content(self, chunk_size=16_384):
            yield self.text.encode("utf-8")

        def close(self):
            pass

    class RedirectAndAPI:
        def __init__(self):
            self.page_responses = [RedirectResponse(), PageResponse()]
            self.api_session = FakeSession(FakeResponse({
                "data": {"productOfferV2": {"nodes": [{
                    "itemId": 456,
                    "productName": "Nome correto pela API",
                    "priceMin": "24.50",
                    "priceMax": "24.50",
                    "imageUrl": "https://img.example/456.jpg",
                }]}}
            }))
            self.get_urls = []

        def get(self, url, **kwargs):
            self.get_urls.append(url)
            return self.page_responses.pop(0)

        def post(self, url, **kwargs):
            return self.api_session.post(url, **kwargs)

    session = RedirectAndAPI()
    result = import_product_links(
        original,
        session=session,
        affiliate_api_credentials=("app", "secret"),
    )
    row = result["products"][0]
    assert session.get_urls == [original, final]
    assert row["link"] == original
    assert row["nome"] == "Nome correto pela API"
    assert row["preco"] == "R$ 24,50"
    assert result["diagnostics"][0]["api_used"] is True
