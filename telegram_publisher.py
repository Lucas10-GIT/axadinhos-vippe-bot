"""Publicação de uma oferta no Telegram Bot API.

Credenciais são recebidas somente como parâmetros; este módulo não lê,
grava nem imprime secrets. Chamadas de rede usam a sessão injetada.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

import requests
from offer_copy import get_custom_callout

TELEGRAM_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT = 30
AFFILIATE_DISCLOSURE = (
    "Link de afiliado: posso receber comissão por compras feitas por este link, "
    "sem custo adicional. Preço e disponibilidade podem mudar."
)


class TelegramPublisherError(RuntimeError):
    """Erro sanitizado ao preparar ou enviar uma mensagem ao Telegram."""


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
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme.casefold() != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
        ):
            return False
        # Avoid URLs that cannot be public image/link destinations.
        normalized_host = host.casefold().rstrip(".")
        if normalized_host in {"localhost", "localhost.localdomain"} or normalized_host.endswith(".local"):
            return False
        try:
            if not ipaddress.ip_address(normalized_host).is_global:
                return False
        except ValueError:
            pass
        # Force malformed ports to fail during validation, not at request time.
        _ = parsed.port
        return True
    except (ValueError, UnicodeError):
        return False


def _valid_shopee_link(value: Any) -> bool:
    if not _valid_https_url(value):
        return False
    host = (urlsplit(value).hostname or "").casefold().rstrip(".")
    return (
        host in {"shopee.com.br", "shopee.com", "shope.ee", "shp.ee"}
        or host.endswith(".shopee.com.br")
        or host.endswith(".shopee.com")
        or host.endswith(".shp.ee")
    )


def _valid_chat_id(value: Any) -> bool:
    chat_id = _text(value)
    if not chat_id:
        return False
    if chat_id.startswith("@"):
        # Telegram public usernames: 5–32 characters, starting with a letter.
        return re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{4,31}", chat_id) is not None
    # String IDs avoid losing precision for large Telegram channel IDs. This
    # accepts regular numeric IDs and signed supergroup/channel IDs (-100...).
    return re.fullmatch(r"-?[1-9][0-9]*", chat_id) is not None


def build_telegram_payload(row: Any, chat_id: Any) -> dict[str, Any]:
    """Build a single safe sendPhoto/sendMessage request payload.

    A photo is used only when the HTTPS image URL is valid and the complete
    caption fits Telegram's 1,024-character limit. Otherwise the complete text
    is sent via sendMessage, provided it fits Telegram's 4,096-character limit.
    The affiliate URL is preserved verbatim and is never shortened or truncated.
    """
    destination = _text(chat_id)
    if not _valid_chat_id(destination):
        raise TelegramPublisherError(
            "O destino do Telegram deve ser um @username público ou um ID numérico válido."
        )

    try:
        name = _text(row.get("nome"))
        price = _text(row.get("preco"))
        link = row.get("link")
        image = _text(row.get("imagem_url"))
        callout = get_custom_callout(row)
    except ValueError as exc:
        raise TelegramPublisherError(str(exc)) from None
    except Exception:
        raise TelegramPublisherError("Não foi possível ler os dados do produto para o Telegram.") from None

    if not name or not price:
        raise TelegramPublisherError("Telegram exige nome e preço válidos para esta oferta.")
    if not _valid_shopee_link(link):
        raise TelegramPublisherError("O destino precisa ser um link HTTPS válido da Shopee.")

    # Do not modify link, even to trim whitespace: invalid surrounding spaces
    # are rejected by validation, while valid input remains exactly as supplied.
    intro = f"{callout}\n\n" if callout else ""
    message = f"{intro}{name}\nPreço: {price}\n\n{AFFILIATE_DISCLOSURE}\n\n{link}"
    if _valid_https_url(image) and len(message) <= 1024:
        return {
            "method": "sendPhoto",
            "chat_id": destination,
            "photo": image,
            "caption": message,
        }
    if len(message) > 4096:
        raise TelegramPublisherError(
            "A mensagem completa excede o limite de 4096 caracteres do Telegram."
        )
    return {"method": "sendMessage", "chat_id": destination, "text": message}


def send_telegram_message(
    row: Any,
    bot_token: Any,
    chat_id: Any,
    session=requests,
) -> dict[str, Any]:
    """Send one offer through Telegram Bot API, returning only its message ID."""
    token = _text(bot_token)
    if not token:
        raise TelegramPublisherError("Configure o token do bot do Telegram antes de publicar.")
    if not _valid_chat_id(chat_id):
        raise TelegramPublisherError(
            "O destino do Telegram deve ser um @username público ou um ID numérico válido."
        )

    payload = build_telegram_payload(row, chat_id)
    method = payload["method"]
    body = {key: value for key, value in payload.items() if key != "method"}
    endpoint = f"{TELEGRAM_API_BASE}/bot{token}/{method}"

    try:
        response = session.post(endpoint, json=body, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception:
        raw_status = getattr(locals().get("response"), "status_code", None)
        status = str(raw_status) if isinstance(raw_status, int) and 100 <= raw_status <= 599 else "desconhecido"
        raise TelegramPublisherError(
            f"Telegram não confirmou o envio (HTTP {status})."
        ) from None

    try:
        result = response.json()
    except Exception:
        raise TelegramPublisherError("Telegram retornou uma resposta que não pôde ser lida.") from None

    if not isinstance(result, dict) or result.get("ok") is not True:
        raise TelegramPublisherError("Telegram recusou a publicação da mensagem.")
    message_result = result.get("result")
    if not isinstance(message_result, dict):
        raise TelegramPublisherError("Telegram não retornou os dados da mensagem enviada.")
    message_id = message_result.get("message_id")
    if message_id is None or _text(message_id) == "":
        raise TelegramPublisherError("Telegram não retornou o ID da mensagem enviada.")
    return {"message_id": message_id}
