"""Publicação orgânica de Pins aprovados via Pinterest API v5.

Credenciais são recebidas por parâmetro; este módulo não lê nem grava secrets.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import requests
from affiliate_links import (
    affiliate_disclosure,
    affiliate_destination,
    contains_amazon_price_claim,
    explicit_true,
    affiliate_program,
    is_valid_affiliate_link,
)
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


def build_pin_copy(row: Any) -> dict[str, str]:
    """Build the exact title and description used for an affiliate Pin."""
    name = _text(row.get("nome"))
    link = _text(row.get("link"))
    program = affiliate_program(link)
    try:
        callout = get_custom_callout(row)
    except ValueError as exc:
        raise PinterestPublisherError(str(exc)) from None

    if not name:
        raise PinterestPublisherError("Pinterest exige o nome revisado do produto.")
    if not is_valid_affiliate_link(link):
        raise PinterestPublisherError("O destino precisa ser um link afiliado Amazon/EPN válido.")
    if program == "amazon" and contains_amazon_price_claim(f"{name} {callout}"):
        raise PinterestPublisherError(
            "Não inclua preço estático no título ou na chamada Amazon; consulte preço e disponibilidade na loja."
        )
    if program == "ebay" and not explicit_true(row.get("epn_promocao_aprovada", False)):
        raise PinterestPublisherError(
            "Confirme a aprovação escrita da EPN para usar conteúdo promocional próprio antes de preparar o Pin."
        )

    if program == "amazon":
        price_note = "Consulte o preço e a disponibilidade atuais diretamente na Amazon."
    elif _text(row.get("preco")):
        price_note = f"Preço de referência: {_text(row.get('preco'))}. Confirme o valor e a disponibilidade no eBay."
    else:
        price_note = "Confirme o preço e a disponibilidade atuais no eBay."
    disclosure = affiliate_disclosure(link)
    description_parts = [callout, name, price_note, disclosure]
    description = "\n\n".join(part for part in description_parts if part)
    if len(description) > 800:
        raise PinterestPublisherError(
            "A descrição excede o limite de 800 caracteres; encurte o nome, o preço ou a chamada."
        )
    return {"title": name[:100], "description": description}


def build_pin_payload(row: Any, board_id: str) -> dict[str, Any]:
    """Build a compliant image Pin; fail closed if the source is incomplete."""
    image = _text(row.get("imagem_url"))
    board = _text(board_id)
    copy = build_pin_copy(row)
    link = _text(row.get("link"))
    name = _text(row.get("nome"))
    if not explicit_true(row.get("imagem_autorizada", False)):
        raise PinterestPublisherError(
            "Confirme que você tem direito de usar esta imagem/arte antes de criar um Pin."
        )
    if not _valid_https_url(image):
        raise PinterestPublisherError("Pinterest exige uma imagem pública HTTPS para criar o Pin.")
    if not board.isdigit():
        raise PinterestPublisherError("O Pinterest Board ID deve conter apenas números.")
    return {
        "board_id": board,
        "title": copy["title"],
        "description": copy["description"],
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
