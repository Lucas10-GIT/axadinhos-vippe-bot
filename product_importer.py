"""Import affiliate URLs from Amazon Associates and eBay Partner Network for manual review."""
from __future__ import annotations

import re
from typing import Any

from affiliate_links import affiliate_link_error, affiliate_program, affiliate_program_label, link_key

MAX_LINKS_PER_BATCH = 20


def extract_links(text: str) -> list[str]:
    """Extract HTTPS URLs from pasted text without rewriting their query parameters."""
    found: list[str] = []
    seen: set[str] = set()
    for match in re.findall(r"https://[^\s,;<>\"']+", text or "", flags=re.IGNORECASE):
        candidate = match.strip().strip("\"'<>[]{}")
        candidate = candidate.rstrip(".,;:!?)]}")
        if candidate and candidate not in seen:
            seen.add(candidate)
            found.append(candidate)
    return found


def import_product_links(
    text: str,
    existing_links=(),
) -> dict[str, Any]:
    """Create inactive drafts from already-generated affiliate links; never fetch pages."""
    candidates = extract_links(text)
    invalid: list[str] = []
    duplicates: list[str] = []
    accepted: list[str] = []
    seen = {link_key(str(link)) for link in existing_links if str(link).strip()}

    for candidate in candidates:
        error = affiliate_link_error(candidate)
        if error:
            invalid.append(candidate)
            continue
        key = link_key(candidate)
        if key in seen:
            duplicates.append(candidate)
            continue
        seen.add(key)
        accepted.append(candidate)

    limit_reached = len(accepted) > MAX_LINKS_PER_BATCH
    overflow = max(0, len(accepted) - MAX_LINKS_PER_BATCH)
    accepted = accepted[:MAX_LINKS_PER_BATCH]

    products = []
    diagnostics = []
    for link in accepted:
        program = affiliate_program(link)
        products.append({
            "id": "",
            "programa": program,
            "nome": "",
            "preco": "",
            "link": link,
            "imagem_url": "",
            "categoria": "",
            "chamada": "",
            "comissao": 0,
            "ativo": False,
            "aprovado_publicacao": False,
            "imagem_autorizada": False,
            "epn_promocao_aprovada": False,
            "epn_mensageria_aprovada": False,
            "status_publicacao": "pronto",
            "frequencia_dias": 3,
            "cliques": 0,
            "pedidos": 0,
            "comissao_estimada": 0,
            "ultima_publicacao": "",
            "proxima_publicacao": "",
            "ultima_tentativa": "",
            "pinterest_status": "pendente",
            "pinterest_pin_id": "",
        })
        diagnostics.append({
            "link": link,
            "programa": affiliate_program_label(link),
            "status": "revisao_manual",
            "extraidos": ["link afiliado"],
            "faltando": ["nome", "imagem autorizada"],
            "nota": (
                "Link preservado sem abrir a página. Preencha os dados manualmente; "
                "Amazon não recebe preço/imagem por scraping e o eBay exige uso de links EPN."
            ),
        })

    return {
        "products": products,
        "invalid": invalid,
        "duplicates": duplicates,
        "incomplete": [item["link"] for item in products],
        "diagnostics": diagnostics,
        "limit_reached": limit_reached,
        "ignored_over_limit": overflow,
    }
