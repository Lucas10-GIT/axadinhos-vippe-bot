"""Publicação orgânica de Pins aprovados via Pinterest API v5.

Credenciais são recebidas por parâmetro; este módulo não lê nem grava secrets.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import requests
from offer_copy import get_custom_callout

CREATE_PIN_URL = "https://api.pinterest.com/v5/pins"


class PinterestPublisherError(RuntimeError):
    """Erro sanitizado ao preparar ou publicar um Pin."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if value != value:  # NaN
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _valid_https_url(value: Any) -> bool:
    text = _text(value)
    if not text or any(character.isspace() for character in text):
        return False
    try:
        parsed = urlsplit(text)
        return (
            parsed.scheme.casefold() == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def _valid_shopee_link(value: Any) -> bool:
    if not _valid_https_url(value):
        return False
    host = (urlsplit(_text(value)).hostname or "").casefold().rstrip(".")
    return (
        host in {"shopee.com.br", "shopee.com", "shope.ee", "shp.ee"}
        or host.endswith(".shopee.com.br")
        or host.endswith(".shopee.com")
        or host.endswith(".shp.ee")
    )


def build_pin_payload(row: Any, board_id: str) -> dict[str, Any]:
    """Build a compliant image Pin; fail closed if the source is incomplete."""
    name = _text(row.get("nome"))
    price = _text(row.get("preco"))
    link = _text(row.get("link"))
    image = _text(row.get("imagem_url"))
    board = _text(board_id)
    try:
        callout = get_custom_callout(row)
    except ValueError as exc:
        raise PinterestPublisherError(str(exc)) from None

    if not name or not price:
        raise PinterestPublisherError("Pinterest exige nome e preço revisados para esta oferta.")
    if not _valid_shopee_link(link):
        raise PinterestPublisherError("O destino precisa ser um link HTTPS válido da Shopee.")
    if not _valid_https_url(image):
        raise PinterestPublisherError("Pinterest exige uma imagem pública HTTPS para criar o Pin.")
    if not board.isdigit():
        raise PinterestPublisherError("O Pinterest Board ID deve conter apenas números.")

    disclosure = (
        "Link de afiliado: posso receber comissão por compras feitas por este link, sem custo adicional. "
        "Preço e disponibilidade podem mudar na Shopee."
    )
    description_parts = [callout, f"{name}\n\nPreço: {price}", disclosure]
    description = "\n\n".join(part for part in description_parts if part)
    if len(description) > 800:
        raise PinterestPublisherError(
            "A descrição excede o limite de 800 caracteres; encurte o nome, o preço ou a chamada."
        )
    return {
        "board_id": board,
        "title": name[:100],
        "description": description,
        "alt_text": f"Imagem do produto: {name}"[:500],
        "link": link,
        "media_source": {
            "source_type": "image_url",
            "url": image,
            "is_standard": True,
        },
    }


def send_pinterest_pin(
    row: Any,
    access_token: str,
    board_id: str,
    session=requests,
) -> dict[str, Any]:
    """Create one Pin through Pinterest API v5; never prints or returns token."""
    if not _text(access_token):
        raise PinterestPublisherError("Configure PINTEREST_ACCESS_TOKEN antes de publicar no Pinterest.")
    payload = build_pin_payload(row, board_id)
    try:
        response = session.post(
            CREATE_PIN_URL,
            headers={
                "Authorization": f"Bearer {_text(access_token)}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
    except PinterestPublisherError:
        raise
    except Exception as exc:
        status = getattr(locals().get("response"), "status_code", "desconhecido")
        raise PinterestPublisherError(f"Pinterest não confirmou o envio (HTTP {status}).") from None

    try:
        result = response.json()
    except Exception:
        raise PinterestPublisherError("Pinterest retornou uma resposta que não pôde ser lida.") from None
    if not isinstance(result, dict) or not _text(result.get("id")):
        raise PinterestPublisherError("Pinterest não retornou o ID do Pin criado.")
    return result
