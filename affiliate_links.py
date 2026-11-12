"""Allowlisted affiliate-link validation for Amazon Associates and eBay Partner Network."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

AMAZON_MARKETPLACES = {
    "amazon.com.br", "amazon.com", "amazon.ca", "amazon.com.mx", "amazon.co.uk",
    "amazon.de", "amazon.fr", "amazon.it", "amazon.es", "amazon.nl", "amazon.se",
    "amazon.pl", "amazon.com.au", "amazon.co.jp", "amazon.in", "amazon.sg",
    "amazon.ae", "amazon.sa", "amazon.com.tr", "amazon.eg",
}
AMAZON_SHORT_HOSTS = {"amzn.to"}
EBAY_MARKETPLACES = {
    "ebay.com", "ebay.com.br", "ebay.ca", "ebay.com.au", "ebay.co.uk", "ebay.de",
    "ebay.fr", "ebay.it", "ebay.es", "ebay.nl", "ebay.be", "ebay.at", "ebay.ch",
    "ebay.ie", "ebay.pl", "ebay.com.sg", "ebay.com.my", "ebay.ph", "ebay.co.jp",
}
EBAY_TRACKING_HOSTS = {"rover.ebay.com"}
EBAY_SHORT_HOSTS = {"ebay.us"}

AMAZON_DISCLOSURE = (
    "Como participante do Programa de Associados da Amazon, sou remunerado pelas compras qualificadas efetuadas."
)
EBAY_DISCLOSURE = (
    "Como afiliado da eBay Partner Network, posso receber comissão por compras qualificadas."
)
_AMAZON_PRICE_CLAIM = re.compile(
    r"(?:\bR\$\s*\d|\bUS\$\s*\d|[$€£]\s*\d|\bpre[cç]o\b.{0,24}\d)",
    flags=re.IGNORECASE,
)


def _safe_parts(value: Any):
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    if any(character.isspace() for character in value):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (ValueError, UnicodeError):
        return None
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return parsed


def is_valid_https_url(value: Any) -> bool:
    """Validate a public-looking HTTPS URL without fetching or following it."""
    return _safe_parts(value) is not None


def _host_matches(host: str, domains: set[str]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def affiliate_program(value: Any) -> str | None:
    """Detect a supported program from its host, even if tracking is malformed."""
    parsed = _safe_parts(value)
    if parsed is None:
        return None
    host = (parsed.hostname or "").casefold().rstrip(".")
    if host in AMAZON_SHORT_HOSTS or _host_matches(host, AMAZON_MARKETPLACES):
        return "amazon"
    if (
        host in EBAY_SHORT_HOSTS
        or host in EBAY_TRACKING_HOSTS
        or _host_matches(host, EBAY_MARKETPLACES)
    ):
        return "ebay"
    return None


def affiliate_program_label(value: Any) -> str:
    program = affiliate_program(value)
    return {"amazon": "Amazon Associados", "ebay": "eBay Partner Network"}.get(
        program, "Não suportado"
    )


def explicit_true(value: Any) -> bool:
    """Return True only for explicit truthy values; strings like 'false' stay false."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if value is None:
        return False
    try:
        if value != value:  # NaN
            return False
    except (TypeError, ValueError):
        return False
    return str(value).strip().casefold() in {"true", "1", "yes", "y", "sim", "s", "ativo"}


def affiliate_link_error(value: Any) -> str:
    """Return a safe explanation when a URL is not a recognizable tracked link."""
    parsed = _safe_parts(value)
    if parsed is None:
        return "Use uma URL HTTPS sem credenciais embutidas e sem porta personalizada."
    host = (parsed.hostname or "").casefold().rstrip(".")
    query = parse_qs(parsed.query, keep_blank_values=False)

    if host in AMAZON_SHORT_HOSTS:
        return ""
    if _host_matches(host, AMAZON_MARKETPLACES):
        if query.get("tag") and query["tag"][0].strip():
            return ""
        return "O link direto da Amazon precisa conter a tag de Associado; links amzn.to também são aceitos."

    if host in EBAY_SHORT_HOSTS:
        return ""
    if host in EBAY_TRACKING_HOSTS or _host_matches(host, EBAY_MARKETPLACES):
        campaign_ids = query.get("campid", [])
        if any(campaign_id.isdigit() and len(campaign_id) == 10 for campaign_id in campaign_ids):
            return ""
        return "O link direto do eBay precisa conter o campid de 10 dígitos da EPN; links ebay.us também são aceitos."

    return "O domínio não é um link Amazon ou eBay suportado."


def is_valid_affiliate_link(value: Any) -> bool:
    return not affiliate_link_error(value)


def affiliate_disclosure(value: Any) -> str:
    program = affiliate_program(value)
    if program == "amazon":
        return AMAZON_DISCLOSURE
    if program == "ebay":
        return EBAY_DISCLOSURE
    return "Link de afiliado: posso receber comissão por compras qualificadas."


def affiliate_destination(value: Any) -> str:
    program = affiliate_program(value)
    return {"amazon": "na Amazon", "ebay": "no eBay"}.get(program, "na loja")


def contains_amazon_price_claim(value: Any) -> bool:
    """Detect explicit currency/price text that should not be statically copied for Amazon."""
    return bool(_AMAZON_PRICE_CLAIM.search(str(value or "")))


def link_key(value: str) -> str:
    """Normalize host/path/fragment for duplicate checks while preserving tracking query."""
    try:
        parsed = urlsplit(str(value).strip())
        host = (parsed.hostname or "").casefold().rstrip(".")
        path = parsed.path.rstrip("/") or "/"
        return urlunsplit((parsed.scheme.casefold(), host, path, parsed.query, ""))
    except ValueError:
        return str(value).strip()
