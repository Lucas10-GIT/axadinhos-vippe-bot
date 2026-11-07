"""Copy-ready offer drafts for platforms that are not connected to an API."""
from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlsplit

from offer_copy import get_custom_callout

AFFILIATE_DISCLOSURE = (
    "Aviso de afiliado: posso receber comissão por compras feitas por este link, "
    "sem custo adicional. Preço e disponibilidade podem mudar."
)


class SocialCopyError(ValueError):
    """Raised when a product is missing fields needed for a safe content draft."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if math.isnan(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.casefold() in {"nan", "<na>"} else text


def _valid_shopee_link(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port
    except (ValueError, UnicodeError):
        return False
    return (
        parsed.scheme.casefold() == "https"
        and bool(host)
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and (
            host in {"shopee.com.br", "shopee.com", "shope.ee", "shp.ee"}
            or host.endswith(".shopee.com.br")
            or host.endswith(".shopee.com")
            or host.endswith(".shp.ee")
        )
    )


def build_manual_copies(row: Any) -> dict[str, str]:
    """Build manual drafts; no API calls or platform publishing happen here.

    The original affiliate URL is included in WhatsApp and Instagram copy. For
    TikTok it is returned separately so it is not inserted into the video or
    caption; the user can place it only in a platform surface where links are
    permitted. Commercial-content disclosure must still be enabled in TikTok.
    """
    try:
        name = _text(row.get("nome"))
        price = _text(row.get("preco"))
        link = row.get("link")
        callout = get_custom_callout(row)
    except ValueError as exc:
        raise SocialCopyError(str(exc)) from None
    except Exception:
        raise SocialCopyError("Não foi possível ler os dados deste produto.") from None

    if not name or not price:
        raise SocialCopyError("Preencha nome e preço revisados antes de preparar o conteúdo.")
    if not _valid_shopee_link(link):
        raise SocialCopyError("O produto precisa ter um link HTTPS válido da Shopee.")

    base = [callout, name, f"Preço: {price}"]
    whatsapp = "\n\n".join([*base, AFFILIATE_DISCLOSURE, link])
    instagram = "\n\n".join([*base, AFFILIATE_DISCLOSURE, f"Link do produto: {link}"])
    tiktok = "\n\n".join([
        *base,
        "Aviso de afiliado: posso receber comissão. Preço e disponibilidade podem mudar.",
        "Conteúdo promocional. Consulte a oferta pelo link do perfil.",
        "A divulgação de conteúdo comercial deve ser ativada no próprio TikTok antes de publicar.",
    ])
    return {
        "whatsapp": whatsapp,
        "instagram": instagram,
        "tiktok": tiktok,
        "affiliate_link": link,
    }
