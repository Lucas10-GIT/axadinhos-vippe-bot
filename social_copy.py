"""Platform-specific, copy-ready affiliate offer drafts; no publishing occurs here."""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from affiliate_links import (
    affiliate_destination,
    affiliate_disclosure,
    affiliate_program,
    explicit_true,
    is_valid_affiliate_link,
)
from offer_copy import get_custom_callout
from pinterest_publisher import PinterestPublisherError, build_pin_copy

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

    Pinterest uses the same title and description builder as the API publisher.
    WhatsApp receives the original affiliate URL in its message. Instagram and
    TikTok captions use platform-appropriate bio/profile calls to action, while
    the same URL is returned separately for the user to place where links are
    supported. This function never publishes or calls a network service.
    """
    try:
        name = _compact_title(row.get("nome"))
        price = _text(row.get("preco"))
        link = row.get("link")
        program = affiliate_program(link)
        category = _text(row.get("categoria"))
        callout = get_custom_callout(row)
    except ValueError as exc:
        raise SocialCopyError(str(exc)) from None
    except Exception:
        raise SocialCopyError("Não foi possível ler os dados deste produto.") from None

    try:
        pinterest_copy = build_pin_copy(row)
    except PinterestPublisherError as exc:
        raise SocialCopyError(str(exc)) from None

    if not name:
        raise SocialCopyError("Preencha o nome revisado antes de preparar o conteúdo.")
    if not is_valid_affiliate_link(link):
        raise SocialCopyError("O produto precisa ter um link afiliado Amazon/EPN válido.")

    opener = callout or "Confira este achadinho:"
    hashtags = _hashtags(category)
    disclosure = affiliate_disclosure(link)
    destination = affiliate_destination(link)
    price_line = (
        "Consulte o preço e a disponibilidade atuais diretamente na Amazon."
        if program == "amazon"
        else f"Preço de referência: {price}. Confirme o valor e a disponibilidade no eBay."
        if price
        else "Confira o preço e a disponibilidade atuais no eBay."
    )
    if program == "ebay" and not explicit_true(row.get("epn_promocao_aprovada", False)):
        raise SocialCopyError(
            "A EPN exige aprovação escrita para métodos ou conteúdo promocional próprios; confirme-a na coluna de aprovação antes de preparar peças."
        )

    whatsapp = "\n\n".join([
        opener,
        name,
        price_line,
        f"Veja a oferta {destination}: {link}",
        disclosure,
    ])
    whatsapp_warning = ""
    if program == "ebay" and not explicit_true(row.get("epn_mensageria_aprovada", False)):
        whatsapp = ""
        whatsapp_warning = (
            "A EPN classifica mensagens/e-mail/texto como método sujeito a aprovação prévia. "
            "Não use o rascunho em WhatsApp sem essa aprovação escrita."
        )
    instagram = "\n\n".join([
        opener,
        name,
        price_line,
        "Link da oferta na bio.",
        disclosure,
        hashtags,
    ])
    tiktok = "\n\n".join([
        opener,
        name,
        price_line,
        "Confira a oferta pelo link do perfil.",
        disclosure,
        hashtags,
    ])
    return {
        "whatsapp": whatsapp,
        "whatsapp_warning": whatsapp_warning,
        "instagram": instagram,
        "tiktok": tiktok,
        "pinterest_title": pinterest_copy["title"],
        "pinterest_description": pinterest_copy["description"],
        "pinterest_link": link,
        "instagram_bio_link": link,
        "tiktok_profile_link": link,
        "affiliate_link": link,
        "hashtags": hashtags,
        "tiktok_disclosure_reminder": (
            "Antes de publicar, ative no TikTok a opção de divulgação de conteúdo comercial aplicável."
        ),
    }
