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
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.jsonld_parts: list[str] = []
        self._in_title = False
        self._in_jsonld = False
        self._current_jsonld: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "meta":
            key = (values.get("property") or values.get("name") or values.get("itemprop") or "").casefold()
            content = values.get("content", "").strip()
            if key and content:
                self.meta.setdefault(key, content)
        elif tag.casefold() == "title":
            self._in_title = True
        elif tag.casefold() == "script" and "ld+json" in values.get("type", "").casefold():
            self._in_jsonld = True
            self._current_jsonld = []

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self._in_title = False
        elif tag.casefold() == "script" and self._in_jsonld:
            value = "".join(self._current_jsonld).strip()
            if value:
                self.jsonld_parts.append(value)
            self._current_jsonld = []
            self._in_jsonld = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_jsonld:
            self._current_jsonld.append(data)


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _format_price(value: Any, currency: str = "BRL") -> str:
    text = str(value or "").strip()
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


def parse_product_metadata(html: str) -> dict[str, str]:
    """Extract common Open Graph, product meta, and JSON-LD fields if present."""
    parser = _MetadataParser()
    try:
        parser.feed((html or "")[:MAX_HTML_BYTES])
    except Exception:
        pass

    products = []
    for raw in parser.jsonld_parts:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        products.extend(
            item for item in _walk_json(payload)
            if str(item.get("@type", "")).casefold() in {"product", "https://schema.org/product"}
            or (item.get("name") and item.get("offers"))
        )

    name = (
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
        or parser.meta.get("title")
        or (" ".join(parser.title_parts).strip())
    )
    name = re.sub(r"\s*[|–—-]\s*Shopee(?:\s+Brasil)?\s*$", "", name, flags=re.IGNORECASE).strip()
    image = parser.meta.get("og:image") or parser.meta.get("twitter:image") or ""

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
        if not name and isinstance(product.get("name"), str):
            name = product["name"].strip()
        if not image:
            image_value = product.get("image", "")
            if isinstance(image_value, list):
                image_value = image_value[0] if image_value else ""
            if isinstance(image_value, dict):
                image_value = image_value.get("url", "")
            if isinstance(image_value, str):
                image = image_value.strip()
        if not price_value:
            offers = product.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if isinstance(offers, dict):
                price_value = offers.get("price") or offers.get("lowPrice") or ""
                currency = offers.get("priceCurrency") or currency

    return {
        "nome": name,
        "preco": _format_price(price_value, currency),
        "imagem_url": image,
    }


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
        return {"nome": "", "preco": "", "imagem_url": ""}

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
            return {"nome": "", "preco": "", "imagem_url": ""}
        try:
            if response.status_code in REDIRECT_CODES:
                location = response.headers.get("Location", "")
                if not location:
                    return {"nome": "", "preco": "", "imagem_url": ""}
                current = urljoin(current, location)
                if not is_shopee_url(current):
                    return {"nome": "", "preco": "", "imagem_url": ""}
                continue
            if response.status_code != 200:
                return {"nome": "", "preco": "", "imagem_url": ""}
            content_type = response.headers.get("Content-Type", "").casefold()
            if content_type and "html" not in content_type and "xhtml" not in content_type:
                return {"nome": "", "preco": "", "imagem_url": ""}
            metadata = parse_product_metadata(_read_response_text(response))
            if metadata.get("imagem_url"):
                metadata["imagem_url"] = urljoin(current, metadata["imagem_url"])
            return metadata
        except requests.RequestException:
            return {"nome": "", "preco": "", "imagem_url": ""}
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    return {"nome": "", "preco": "", "imagem_url": ""}


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
    # keeping requests bounded. Any page that blocks extraction still yields a
    # draft link; missing title/price remain blank for human review.
    with ThreadPoolExecutor(max_workers=4) as pool:
        metadata = list(pool.map(lambda link: fetch_product_metadata(link, session), accepted))

    products = []
    incomplete = []
    for link, info in zip(accepted, metadata):
        row = {
            "id": "",
            "nome": info.get("nome", ""),
            "preco": info.get("preco", ""),
            # Keep the affiliate URL exactly as provided; redirects are only
            # followed for metadata and never replace the tracking link.
            "link": link,
            "imagem_url": info.get("imagem_url", ""),
            "categoria": "",
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
        if not row["nome"] or not row["preco"]:
            incomplete.append(link)
        products.append(row)

    return {
        "products": products,
        "invalid": invalid,
        "duplicates": duplicates,
        "incomplete": incomplete,
        "limit_reached": limit_reached,
        "ignored_over_limit": max(0, len(accepted) + (len(candidates) - len(invalid) - len(duplicates) - len(accepted)) - MAX_LINKS_PER_BATCH),
    }
