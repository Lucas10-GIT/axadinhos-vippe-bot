from __future__ import annotations

import json

from product_importer import parse_product_metadata


def test_parse_product_from_javascript_state_assignment_in_page_source():
    html = '''<script>
    window.__PRODUCT_DATA__ = {"productName":"Fone Bluetooth","currentPrice":"129.90",
      "imageUrl":"/img/fone.jpg","categoryPath":"Eletrônicos"};
    </script>'''
    metadata = parse_product_metadata(html)
    assert metadata["nome"] == "Fone Bluetooth"
    assert metadata["preco"] == "R$ 129,90"
    assert metadata["imagem_url"] == "/img/fone.jpg"
    assert metadata["categoria"] == "Eletrônicos"
    assert metadata["status_metadados"] == "completo"


def test_parse_product_from_json_parse_string_in_inline_script():
    serialized = json.dumps({
        "productName": "Produto serializado",
        "price": {"amount": "54.90", "currency": "BRL"},
        "image": "https://img.example/item.jpg",
        "category": "Casa",
    })
    html = "<script>const productState = JSON.parse(" + json.dumps(serialized) + ");</script>"
    metadata = parse_product_metadata(html)
    assert metadata["nome"] == "Produto serializado"
    assert metadata["preco"] == "R$ 54,90"
    assert metadata["imagem_url"] == "https://img.example/item.jpg"
    assert metadata["categoria"] == "Casa"


def test_parse_itemprop_text_and_image_attributes_outside_meta_tags():
    html = '''<h1 itemprop="name">Organizador multiuso</h1>
      <span itemprop="price">R$ 32,90</span>
      <img itemprop="image" src="/images/organizador.jpg">
      <div itemprop="category">Organização</div>'''
    metadata = parse_product_metadata(html)
    assert metadata["nome"] == "Organizador multiuso"
    assert metadata["preco"] == "R$ 32,90"
    assert metadata["imagem_url"] == "/images/organizador.jpg"
    assert metadata["categoria"] == "Organização"


def test_parse_metadata_from_data_attributes_and_embedded_json():
    html = '''<div data-product-name="Luminária LED" data-price="R$ 26,90"
      data-image="/img/luminaria.jpg" data-category="Iluminação"></div>
      <div data-product='{"@type":"Product","name":"Segundo produto",
      "offers":{"price":"18.00","priceCurrency":"BRL"}}'></div>'''
    metadata = parse_product_metadata(html)
    assert metadata["nome"] == "Luminária LED"
    assert metadata["preco"] == "R$ 26,90"
    assert metadata["imagem_url"] == "/img/luminaria.jpg"
    assert metadata["categoria"] == "Iluminação"
