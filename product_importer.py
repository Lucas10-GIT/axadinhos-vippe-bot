"""Importação em lote de links Shopee com leitura best-effort de metadados públicos.

O módulo não salva dados nem publica ofertas. O link original de afiliado é
preservado; qualquer metadado extraído deve ser revisado antes da aprovação.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

MAX_LINKS_PER_BATCH = 20
MAX_REDIRECTS = 5
MAX_HTML_BYTES = 1_000_000
REQUEST_TIMEOUT = (3, 5)
USER_AGENT = "AxadinhosVippeProductImporter/1.0 (public metadata preview)"
REDIRECT_CODES = {301, 302, 303, 307, 308}
ALLOWED_HOSTS = {"shopee.com.br", "shopee.com", "shope.ee", "shp.ee"}
METADATA_FIELDS = ("nome", "preco", "imagem_url", "categoria")


def is_shopee_url(value: Any) -> bool:
    """Return true only for HTTPS Shopee hosts (not lookalike hostnames)."""
    text = str(value or "").strip()
    if not text or any(character.isspace() for character in text):
        return False
    try:
        parsed = urlsplit(text)
        host = (parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port
    except ValueError:
        return False
    host_ok = (
        host in ALLOWED_HOSTS
        or any(host.endswith("." + suffix) for suffix in ("shopee.com.br", "shopee.com", "shp.ee"))
    )
    return (
        parsed.scheme.casefold() == "https"
        and host_ok
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
    )


def _normalize_candidate(candidate: str) -> str:
    value = candidate.strip().strip("\"'<>[]{}")
    value = value.rstrip(".,;:!?)]}")
    if value.casefold().startswith("www."):
        value = "https://" + value
    elif "://" not in value:
        # Accept a bare Shopee hostname, but never upgrade arbitrary domains.
        if is_shopee_url("https://" + value):
            value = "https://" + value
    return value


def extract_links(text: str) -> list[str]:
    """Extract and de-duplicate pasted links from whitespace/comma/semicolon input."""
    found: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\s,;]+", text or ""):
        candidate = _normalize_candidate(token)
        if not candidate:
            continue
        host_token = candidate.split("/", 1)[0]
        if (
            candidate.casefold().startswith(("https://", "http://", "www."))
            or "://" in candidate
            or "." in host_token
        ):
            key = candidate
            if key not in seen:
                seen.add(key)
                found.append(candidate)
    return found


def link_key(value: str) -> str:
    """Canonical comparison key, preserving affiliate query parameters."""
    try:
        parsed = urlsplit(str(value).strip())
        host = (parsed.hostname or "").casefold().rstrip(".")
        path = parsed.path.rstrip("/") or "/"
        return urlunsplit((parsed.scheme.casefold(), host, path, parsed.query, ""))
    except ValueError:
        return str(value).strip()


class _MetadataParser(HTMLParser):
    """Collect standard meta tags, JSON-LD and JSON state blocks from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.json_parts: list[str] = []
        self._in_title = False
        self._in_json = False
        self._current_json: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        tag = tag.casefold()
        if tag == "meta":
            content = values.get("content", "").strip()
            # Read every supported attribute instead of choosing just one; some
            # stores combine property/name/itemprop on nonstandard meta tags.
            for attr in ("property", "name", "itemprop"):
                key = values.get(attr, "").casefold()
                if key and content:
                    self.meta.setdefault(key, content)
        elif tag == "title":
            self._in_title = True
        elif tag == "script":
            script_type = values.get("type", "").casefold()
            script_id = values.get("id", "").casefold()
            self._in_json = (
                "ld+json" in script_type
                or script_type.split(";", 1)[0].strip() == "application/json"
                or script_id in {"__next_data__", "__nuxt_data__", "__initial_state__"}
            )
            if self._in_json:
                self._current_json = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_json:
            value = "".join(self._current_json).strip()
            if value:
                self.json_parts.append(value)
            self._current_json = []
            self._in_json = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_json:
            self._current_json.append(data)


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _first_text(value: Any) -> str:
    """Convert common Schema.org scalar/list/object values to display text."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
    if isinstance(value, dict):
        for key in ("name", "@value", "value", "url"):
            text = _first_text(value.get(key))
            if text:
                return text
    return ""


def _is_product_type(value: Any) -> bool:
    types = value if isinstance(value, list) else [value]
    return any(str(item).casefold().rstrip("/").split("/")[-1] == "product" for item in types)


def _format_price(value: Any, currency: str = "BRL") -> str:
    text = _first_text(value)
    if not text:
        return ""
    if "R$" in text:
        return text
    if currency and currency.upper() not in {"BRL", "R$"}:
        return ""
    numeric = re.sub(r"[^0-9,.\-]", "", text)
    if not numeric:
        return ""
    if "," in numeric:
        numeric = numeric.replace(".", "").replace(",", ".")
    try:
        amount = float(numeric)
    except ValueError:
        return ""
    formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _empty_metadata(status: str) -> dict[str, str]:
    return {
        "nome": "",
        "preco": "",
        "imagem_url": "",
        "categoria": "",
        "status_metadados": status,
    }


def parse_product_metadata(html: str) -> dict[str, str]:
    """Extract product data from public Open Graph, itemprop and JSON metadata."""
    parser = _MetadataParser()
    try:
        parser.feed((html or "")[:MAX_HTML_BYTES])
    except Exception:
        pass

    products = []
    for raw in parser.json_parts:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        products.extend(
            item for item in _walk_json(payload)
            if _is_product_type(item.get("@type"))
            or (
                item.get("name")
                and any(key in item for key in ("offers", "price", "image", "category", "sku"))
            )
        )

    name = (
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
        or parser.meta.get("title")
        or parser.meta.get("name")
        or (" ".join(parser.title_parts).strip())
    )
    name = re.sub(r"\s*[|–—-]\s*Shopee(?:\s+Brasil)?\s*$", "", name, flags=re.IGNORECASE).strip()
    image = parser.meta.get("og:image") or parser.meta.get("twitter:image") or parser.meta.get("image") or ""
    category = (
        parser.meta.get("product:category")
        or parser.meta.get("og:category")
        or parser.meta.get("article:section")
        or parser.meta.get("category")
        or ""
    )

    price_value = (
        parser.meta.get("product:price:amount")
        or parser.meta.get("og:price:amount")
        or parser.meta.get("price")
        or ""
    )
    currency = (
        parser.meta.get("product:price:currency")
        or parser.meta.get("og:price:currency")
        or "BRL"
    )
    for product in products:
        if not name:
            name = _first_text(product.get("name"))
        if not image:
            image = _first_text(product.get("image"))
        if not category:
            category = _first_text(product.get("category") or product.get("categoryName"))
        if not price_value:
            offers = product.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if isinstance(offers, dict):
                price_value = offers.get("price") or offers.get("lowPrice") or product.get("price") or ""
                currency = offers.get("priceCurrency") or product.get("priceCurrency") or currency
            elif product.get("price"):
                price_value = product.get("price")

    metadata = {
        "nome": _first_text(name),
        "preco": _format_price(price_value, str(currency or "BRL")),
        "imagem_url": _first_text(image),
        "categoria": _first_text(category),
    }
    metadata["status_metadados"] = (
        "completo" if metadata["nome"] and metadata["preco"]
        else "parcial" if any(metadata[field] for field in METADATA_FIELDS)
        else "indisponivel"
    )
    return metadata


def _read_response_text(response: Any) -> str:
    """Read at most MAX_HTML_BYTES from a streaming response."""
    iterator = getattr(response, "iter_content", None)
    if callable(iterator):
        chunks: list[bytes] = []
        total = 0
        for chunk in iterator(chunk_size=16_384):
            if not chunk:
                continue
            remaining = MAX_HTML_BYTES - total
            chunks.append(chunk[:remaining])
            total += min(len(chunk), remaining)
            if total >= MAX_HTML_BYTES:
                break
        encoding = getattr(response, "encoding", None) or "utf-8"
        return b"".join(chunks).decode(encoding, errors="replace")
    return str(getattr(response, "text", ""))[:MAX_HTML_BYTES]


def fetch_product_metadata(url: str, session=requests) -> dict[str, str]:
    """Fetch metadata only through Shopee hosts, validating every redirect hop."""
    if not is_shopee_url(url):
        return _empty_metadata("link_invalido")

    current = url
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    for _ in range(MAX_REDIRECTS + 1):
        try:
            response = session.get(
                current,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException:
            return _empty_metadata("falha_de_conexao")
        try:
            if response.status_code in REDIRECT_CODES:
                location = response.headers.get("Location", "")
                if not location:
                    return _empty_metadata("redirecionamento_incompleto")
                current = urljoin(current, location)
                if not is_shopee_url(current):
                    return _empty_metadata("redirecionamento_bloqueado")
                continue
            if response.status_code != 200:
                return _empty_metadata(f"http_{response.status_code}")
            content_type = response.headers.get("Content-Type", "").casefold()
            if content_type and "html" not in content_type and "xhtml" not in content_type:
                return _empty_metadata("resposta_nao_html")
            metadata = parse_product_metadata(_read_response_text(response))
            if metadata.get("imagem_url"):
                metadata["imagem_url"] = urljoin(current, metadata["imagem_url"])
            return metadata
        except requests.RequestException:
            return _empty_metadata("falha_ao_ler_pagina")
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    return _empty_metadata("limite_de_redirecionamentos")


def import_product_links(text: str, existing_links=(), session=requests) -> dict[str, Any]:
    """Prepare rows for review; never activates or approves imported products."""
    candidates = extract_links(text)
    invalid: list[str] = []
    duplicates: list[str] = []
    accepted: list[str] = []
    seen = {link_key(str(link)) for link in existing_links if str(link).strip()}

    for candidate in candidates:
        if not is_shopee_url(candidate):
            invalid.append(candidate)
            continue
        key = link_key(candidate)
        if key in seen:
            duplicates.append(candidate)
            continue
        seen.add(key)
        accepted.append(candidate)

    limit_reached = len(accepted) > MAX_LINKS_PER_BATCH
    accepted = accepted[:MAX_LINKS_PER_BATCH]

    # A small worker pool avoids a long serial wait for multiple links while
    # keeping requests bounded. Pages that block extraction still yield drafts.
    with ThreadPoolExecutor(max_workers=4) as pool:
        metadata = list(pool.map(lambda link: fetch_product_metadata(link, session), accepted))

    products = []
    incomplete = []
    diagnostics = []
    for link, info in zip(accepted, metadata):
        row = {
            "id": "",
            "nome": info.get("nome", ""),
            "preco": info.get("preco", ""),
            # Keep the affiliate URL exactly as provided; redirects are only
            # followed for metadata and never replace the tracking link.
            "link": link,
            "imagem_url": info.get("imagem_url", ""),
            "categoria": info.get("categoria", ""),
            "comissao": 0,
            "ativo": False,
            "aprovado_publicacao": False,
            "status_publicacao": "pronto",
            "frequencia_dias": 3,
            "cliques": 0,
            "pedidos": 0,
            "comissao_estimada": 0,
            "ultima_publicacao": "",
            "proxima_publicacao": "",
            "ultima_tentativa": "",
            "telegram_message_id": "",
        }
        missing = [field for field in METADATA_FIELDS if not row[field]]
        if "nome" in missing or "preco" in missing:
            incomplete.append(link)
        diagnostics.append({
            "link": link,
            "status": info.get("status_metadados", "indisponivel"),
            "extraidos": [field for field in METADATA_FIELDS if row[field]],
            "faltando": missing,
        })
        products.append(row)

    return {
        "products": products,
        "invalid": invalid,
        "duplicates": duplicates,
        "incomplete": incomplete,
        "diagnostics": diagnostics,
        "limit_reached": limit_reached,
        "ignored_over_limit": max(0, len(accepted) + (len(candidates) - len(invalid) - len(duplicates) - len(accepted)) - MAX_LINKS_PER_BATCH),
    }
