"""Client for the Shopee Affiliate Open API (credentials must come from secrets)."""

from __future__ import annotations

import hashlib
import json
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

API_URL = "https://open-api.affiliate.shopee.com.br/graphql"
API_TIMEOUT = (3, 12)


class ShopeeAffiliateAPIError(RuntimeError):
    """Safe, user-facing API error that never includes credential material."""


def build_authorization(app_id: str, app_secret: str, payload: str, timestamp: int | None = None) -> str:
    """Build the documented SHA256 Authorization header for one exact JSON body."""
    if not app_id or not app_secret:
        raise ShopeeAffiliateAPIError("Credenciais da API de Afiliados Shopee não configuradas.")
    current_timestamp = int(timestamp if timestamp is not None else time.time())
    signature_input = f"{app_id}{current_timestamp}{payload}{app_secret}"
    signature = hashlib.sha256(signature_input.encode("utf-8")).hexdigest()
    return (
        f"SHA256 Credential={app_id},Timestamp={current_timestamp},"
        f"Signature={signature}"
    )


def _request(query: str, app_id: str, app_secret: str, session=requests) -> dict[str, Any]:
    payload = json.dumps({"query": query}, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json",
        "Authorization": build_authorization(app_id, app_secret, payload),
    }
    try:
        response = session.post(API_URL, data=payload, headers=headers, timeout=API_TIMEOUT)
    except requests.RequestException as exc:
        raise ShopeeAffiliateAPIError("Não foi possível conectar à Shopee Affiliate Open API.") from exc

    if getattr(response, "status_code", 200) != 200:
        status = getattr(response, "status_code", "desconhecido")
        raise ShopeeAffiliateAPIError(f"A API Shopee retornou HTTP {status}.")
    try:
        body = response.json()
    except (ValueError, AttributeError) as exc:
        raise ShopeeAffiliateAPIError("A resposta da API Shopee não era JSON válido.") from exc
    if not isinstance(body, dict):
        raise ShopeeAffiliateAPIError("A resposta da API Shopee veio em formato inesperado.")
    if body.get("errors"):
        first_error = body["errors"][0] if isinstance(body["errors"], list) and body["errors"] else {}
        extensions = first_error.get("extensions", {}) if isinstance(first_error, dict) else {}
        code = extensions.get("code") if isinstance(extensions, dict) else None
        suffix = f" (código {code})" if code is not None else ""
        raise ShopeeAffiliateAPIError(
            "A Shopee recusou a consulta" + suffix + ". Confira se a API está habilitada e as credenciais estão corretas."
        )
    data = body.get("data")
    if not isinstance(data, dict):
        raise ShopeeAffiliateAPIError("A resposta da API Shopee não trouxe dados.")
    return data


def check_connection(app_id: str, app_secret: str, session=requests) -> None:
    """Make a minimal read-only query to validate credentials and API access."""
    data = _request(
        "query { productOfferV2(listType: 0, page: 1, limit: 1) "
        "{ nodes { itemId productName } pageInfo { page limit hasNextPage } } }",
        app_id,
        app_secret,
        session=session,
    )
    if not isinstance(data.get("productOfferV2"), dict):
        raise ShopeeAffiliateAPIError("A resposta não corresponde ao schema esperado da API de Afiliados.")


def extract_item_id(url: str) -> int | None:
    """Extract an item ID only from common Shopee product URL formats."""
    try:
        parsed = urlsplit(str(url or "").strip())
        host = (parsed.hostname or "").casefold().rstrip(".")
        query = parse_qs(parsed.query)
    except ValueError:
        return None
    if not (host == "shopee.com.br" or host.endswith(".shopee.com.br")
            or host == "shopee.com" or host.endswith(".shopee.com")):
        return None
    for key in ("itemid", "item_id", "itemId", "product_id", "productId"):
        values = query.get(key, [])
        if values and values[0].isdigit():
            return int(values[0])
    path = parsed.path
    match = re.search(r"(?:-i|/i)\.(\d+)\.(\d+)(?:$|/)", path, flags=re.IGNORECASE)
    if match:
        return int(match.group(2))
    match = re.search(r"/product/(\d+)/(\d+)(?:$|/)", path, flags=re.IGNORECASE)
    if match:
        return int(match.group(2))
    return None


def _price_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        amount = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        text = str(value).strip()
        return text if "R$" in text else ""
    if not amount.is_finite() or amount < 0:
        return ""
    formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def lookup_product_by_item_id(
    item_id: int,
    app_id: str,
    app_secret: str,
    session=requests,
) -> dict[str, str]:
    """Return mapped product fields from Affiliate API for an exact Shopee item ID."""
    if not isinstance(item_id, int) or item_id <= 0:
        raise ShopeeAffiliateAPIError("O link não contém um ID de produto Shopee compatível com a API.")
    query = (
        "query { productOfferV2(itemId: " + str(item_id) + ", page: 1, limit: 1) { nodes { "
        "itemId productName productLink offerLink imageUrl priceMin priceMax commissionRate "
        "} pageInfo { page limit hasNextPage } } }"
    )
    data = _request(query, app_id, app_secret, session=session)
    result = data.get("productOfferV2")
    nodes = result.get("nodes", []) if isinstance(result, dict) else []
    if not isinstance(nodes, list) or not nodes:
        return {}
    product = nodes[0]
    if not isinstance(product, dict):
        return {}
    low = _price_text(product.get("priceMin"))
    high = _price_text(product.get("priceMax"))
    price = low if low == high or not high else f"{low}–{high}"
    return {
        "nome": str(product.get("productName") or "").strip(),
        "preco": price,
        "imagem_url": str(product.get("imageUrl") or "").strip(),
        "categoria": "",
        "status_metadados": "completo" if product.get("productName") and price else "parcial",
        "api_offer_link": str(product.get("offerLink") or "").strip(),
        "api_product_link": str(product.get("productLink") or "").strip(),
    }
