"""Platform-specific, copy-ready affiliate offer drafts; no publishing occurs here."""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit

from offer_copy import get_custom_callout

AFFILIATE_DISCLOSURE = (
    "Aviso de afiliado: posso receber comissão se você comprar por um link de afiliado, "
    "sem custo extra. Preço e disponibilidade podem mudar."
)
MAX_SOCIAL_TITLE_CHARS = 72


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
    text = re.sub(r"\s+", " ", str(value)).strip()
    return "" if text.casefold() in {"nan", "<na>"} else text


def _compact_title(value: Any, limit: int = MAX_SOCIAL_TITLE_CHARS) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    shortened = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    if len(shortened) < limit // 2:
        shortened = text[: limit - 1].rstrip(" ,;:-")
    return shortened + "…"


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


def _category_hashtag(value: Any) -> str:
    category = _text(value)
    if not category:
        return ""
    ascii_text = unicodedata.normalize("NFKD", category).encode("ascii", "ignore").decode("ascii")
    stop_words = {"e", "de", "da", "do", "das", "dos", "para"}
    words = [
        word
        for word in re.findall(r"[A-Za-z0-9]+", ascii_text)
        if word.casefold() not in stop_words
    ]
    if not words:
        return ""
    tag = "#" + "".join(word[:1].upper() + word[1:] for word in words[:3])
    return tag if len(tag) <= 30 else ""


def _hashtags(category: Any) -> str:
    tags = ["#Achadinhos", "#Ofertas"]
    category_tag = _category_hashtag(category)
    if category_tag and category_tag.casefold() not in {tag.casefold() for tag in tags}:
        tags.append(category_tag)
    return " ".join(tags)


def build_manual_copies(row: Any) -> dict[str, str]:
    """Build concise channel-specific drafts while preserving the submitted link.

    WhatsApp receives the original affiliate URL in its message. Instagram and
    TikTok captions use platform-appropriate bio/profile calls to action, while
    the same URL is returned separately for the user to place where links are
    supported. This function never publishes or calls a network service.
    """
    try:
        name = _compact_title(row.get("nome"))
        price = _text(row.get("preco"))
        link = row.get("link")
        category = _text(row.get("categoria"))
        callout = get_custom_callout(row)
    except ValueError as exc:
        raise SocialCopyError(str(exc)) from None
    except Exception:
        raise SocialCopyError("Não foi possível ler os dados deste produto.") from None

    if not name or not price:
        raise SocialCopyError("Preencha nome e preço revisados antes de preparar o conteúdo.")
    if not _valid_shopee_link(link):
        raise SocialCopyError("O produto precisa ter um link HTTPS válido da Shopee.")

    opener = callout or "Confira este achadinho:"
    hashtags = _hashtags(category)

    whatsapp = "\n\n".join([
        opener,
        name,
        f"Preço: {price}",
        f"Veja a oferta na Shopee: {link}",
        AFFILIATE_DISCLOSURE,
    ])
    instagram = "\n\n".join([
        opener,
        name,
        f"Preço: {price}",
        "Link da oferta na bio.",
        AFFILIATE_DISCLOSURE,
        hashtags,
    ])
    tiktok = "\n\n".join([
        opener,
        name,
        f"Preço: {price}",
        "Confira a oferta pelo link do perfil.",
        AFFILIATE_DISCLOSURE,
        hashtags,
    ])
    return {
        "whatsapp": whatsapp,
        "instagram": instagram,
        "tiktok": tiktok,
        "instagram_bio_link": link,
        "tiktok_profile_link": link,
        "affiliate_link": link,
        "hashtags": hashtags,
        "tiktok_disclosure_reminder": (
            "Antes de publicar, ative no TikTok a opção de divulgação de conteúdo comercial aplicável."
        ),
    }
