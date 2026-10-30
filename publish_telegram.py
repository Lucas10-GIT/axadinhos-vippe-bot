"""Publicador do Axadinhos Vippe.

Importar este módulo não faz chamadas de rede. Publicações reais exigem
PUBLISH_CONFIRMED=true e um produto ativo, aprovado e válido no CSV.
"""

from __future__ import annotations

import base64
import io
import math
import os
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any
from urllib.parse import urlsplit

import pandas as pd
import requests

OWNER = "Lucas10-GIT"
REPO = "axadinhos-vippe-bot"
BRANCH = "main"
PATH = "data/products.csv"
DEFAULT_FREQUENCY_DAYS = 3
READY_STATUSES = {"", "pronto", "ready"}


def headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def parse_bool(value: Any, default: bool = True) -> bool:
    """Interpret CSV booleans correctly (e.g. the string 'False' is false)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes", "y", "sim", "s", "ativo"}:
        return True
    if normalized in {"false", "0", "no", "n", "não", "nao", "inativo", ""}:
        return False
    return default


def parse_utc(value: Any) -> datetime | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _display(value: Any, fallback: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return fallback
    text = str(value).strip()
    return text or fallback


def _valid_https_url(value: Any) -> bool:
    text = _display(value)
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


def _valid_shopee_url(value: Any) -> bool:
    if not _valid_https_url(value):
        return False
    host = (urlsplit(_display(value)).hostname or "").casefold().rstrip(".")
    return (
        host in {"shopee.com.br", "shopee.com", "shope.ee", "shp.ee"}
        or host.endswith(".shopee.com.br")
        or host.endswith(".shopee.com")
        or host.endswith(".shp.ee")
    )


def is_publishable(row: Any) -> bool:
    """Require a product name, current price and HTTPS Shopee destination."""
    return bool(
        _display(row.get("nome"))
        and _display(row.get("preco"))
        and _valid_shopee_url(row.get("link"))
    )


def is_due(row: Any, now: datetime | None = None) -> bool:
    if not parse_bool(row.get("ativo", True)):
        return False
    if not parse_bool(row.get("aprovado_publicacao", False), default=False):
        return False
    status = _display(row.get("status_publicacao"), "pronto").casefold()
    if status not in READY_STATUSES or not is_publishable(row):
        return False

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    next_publication = parse_utc(row.get("proxima_publicacao", ""))
    if next_publication is not None:
        return current >= next_publication

    frequency = int(_number(row.get("frequencia_dias", DEFAULT_FREQUENCY_DAYS), DEFAULT_FREQUENCY_DAYS))
    frequency = min(30, max(1, frequency))
    last_published = parse_utc(row.get("ultima_publicacao", ""))
    if last_published is None:
        return True
    return current - last_published >= timedelta(days=frequency)


def score(row: Any) -> float:
    clicks = max(0.0, _number(row.get("cliques", 0)))
    orders = max(0.0, _number(row.get("pedidos", 0)))
    commission = max(0.0, _number(row.get("comissao_estimada", 0)))
    return orders * 5 + commission + (orders / max(clicks, 1)) * 100


def select_candidate(df: pd.DataFrame, now: datetime | None = None):
    """Return the due (index, row) with the highest score, or None."""
    candidates = [(index, row) for index, row in df.iterrows() if is_due(row, now)]
    return max(candidates, key=lambda item: score(item[1])) if candidates else None


def publication_frequency(row: Any) -> int:
    orders = _number(row.get("pedidos", 0))
    clicks = _number(row.get("cliques", 0))
    if orders >= 2:
        return 2
    if clicks >= 10:
        return 4
    return DEFAULT_FREQUENCY_DAYS


def ad(row: Any) -> str:
    """Build an HTML offer; escape all CSV values before using Telegram HTML."""
    name = escape(_display(row.get("nome"), "Achadinho"))
    price = escape(_display(row.get("preco"), "Confira o preço"))
    link = escape(_display(row.get("link")), quote=True)
    return (
        "🔥 <b>ACHADINHO DO DIA!</b>\n\n"
        f"🛍️ <b>{name}</b>\n\n"
        f"💰 <b>Preço:</b> {price}\n\n"
        f"👉 <a href=\"{link}\">Ver na Shopee</a>\n\n"
        "👑 <b>Axadinhos Vippe</b>\n<i>Se é útil, é achadinho!</i>\n\n"
        "<i>Link de afiliado: podemos receber comissão pela compra, sem custo adicional para você. "
        "Preço e disponibilidade podem mudar na Shopee.</i>"
    )


def load(token: str, session=requests) -> tuple[pd.DataFrame, str]:
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{PATH}?ref={BRANCH}"
    response = session.get(url, headers=headers(token), timeout=20)
    response.raise_for_status()
    payload = response.json()
    raw = base64.b64decode(payload["content"]).decode("utf-8-sig")
    return pd.read_csv(io.StringIO(raw)), payload["sha"]


def save(token: str, df: pd.DataFrame, sha: str, session=requests) -> str:
    """Commit CSV with optimistic concurrency and return its new Git blob SHA."""
    if not sha:
        raise ValueError("O SHA do CSV é obrigatório para evitar sobrescrever dados inesperadamente.")
    raw = df.to_csv(index=False).encode("utf-8")
    body = {
        "message": "Atualiza estado de publicação Axadinhos Vippe",
        "content": base64.b64encode(raw).decode("ascii"),
        "branch": BRANCH,
        "sha": sha,
    }
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{PATH}"
    response = session.put(url, headers=headers(token), json=body, timeout=30)
    response.raise_for_status()
    new_sha = response.json().get("content", {}).get("sha")
    if not new_sha:
        raise RuntimeError("GitHub não retornou o SHA atualizado do CSV.")
    return new_sha


def send_telegram(row: Any, token: str, chat_id: str, session=requests) -> dict[str, Any]:
    if not token or not chat_id:
        raise ValueError("Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID antes de publicar.")
    if not is_publishable(row):
        raise ValueError("Produto sem nome, preço ou link HTTPS válido; publicação bloqueada.")

    base = f"https://api.telegram.org/bot{token}"
    image = _display(row.get("imagem_url"))
    if image and _valid_https_url(image):
        response = session.post(
            f"{base}/sendPhoto",
            data={"chat_id": chat_id, "photo": image, "caption": ad(row), "parse_mode": "HTML"},
            timeout=30,
        )
    else:
        response = session.post(
            f"{base}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": ad(row),
                "parse_mode": "HTML",
                "disable_web_page_preview": "false",
            },
            timeout=30,
        )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram recusou a publicação: {result.get('description', 'erro sem descrição')}")
    return result


def _redact(text: Any, *secrets: str | None) -> str:
    safe = str(text)
    for secret in secrets:
        if secret:
            safe = safe.replace(secret, "[REDACTED]")
    return safe


def main(environ=os.environ, session=requests, now: datetime | None = None) -> int:
    if not parse_bool(environ.get("PUBLISH_CONFIRMED", False), default=False):
        raise RuntimeError("Publicação bloqueada: o workflow não confirmou PUBLISH_CONFIRMED=true.")

    token = environ.get("GH_AUTOMATION_TOKEN") or environ.get("GITHUB_TOKEN")
    telegram_token = environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = environ.get("TELEGRAM_CHAT_ID")
    missing = [
        name for name, value in (
            ("GH_AUTOMATION_TOKEN ou GITHUB_TOKEN", token),
            ("TELEGRAM_BOT_TOKEN", telegram_token),
            ("TELEGRAM_CHAT_ID", chat_id),
        ) if not value
    ]
    if missing:
        raise RuntimeError("Secrets/variáveis ausentes: " + ", ".join(missing))

    df, sha = load(token, session)
    state_defaults = {
        "status_publicacao": "pronto",
        "ultima_publicacao": "",
        "proxima_publicacao": "",
        "ultima_tentativa": "",
        "telegram_message_id": "",
    }
    for column, default in state_defaults.items():
        if column not in df.columns:
            df[column] = default
        df[column] = df[column].astype("object")
        df[column] = df[column].where(df[column].notna(), default)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    candidate = select_candidate(df, current)
    if candidate is None:
        print("Nenhum produto ativo, aprovado, válido e vencido para publicação.")
        return 0

    index, row = candidate
    # Reserva persistente antes de enviar: se o processo cair depois do envio,
    # a próxima execução não republicará automaticamente o mesmo produto.
    df.at[index, "status_publicacao"] = "enviando"
    df.at[index, "ultima_tentativa"] = current.isoformat()
    pending_sha = save(token, df, sha, session)

    try:
        result = send_telegram(row, telegram_token, chat_id, session)
    except Exception as exc:
        # Resultado ambíguo (por exemplo, timeout) exige revisão humana antes
        # de qualquer nova tentativa para evitar duplicar um post já entregue.
        df.at[index, "status_publicacao"] = "revisar"
        try:
            save(token, df, pending_sha, session)
        except Exception as save_exc:
            raise RuntimeError(
                "Falha no envio e não foi possível atualizar o estado; o produto permanece reservado para revisão. "
                + _redact(save_exc, token, telegram_token)
            ) from None
        raise RuntimeError(
            "Telegram não confirmou o envio; produto marcado para revisão manual. "
            + _redact(exc, token, telegram_token)
        ) from None

    frequency = publication_frequency(row)
    df.at[index, "status_publicacao"] = "enviado"
    df.at[index, "ultima_publicacao"] = current.isoformat()
    df.at[index, "frequencia_dias"] = frequency
    df.at[index, "proxima_publicacao"] = (current + timedelta(days=frequency)).isoformat()
    message_id = result.get("result", {}).get("message_id", "")
    df.at[index, "telegram_message_id"] = str(message_id) if message_id != "" else ""
    # Se este commit falhar, o estado persistido segue como "enviando"; o
    # próximo agendamento para e não repete automaticamente a oferta.
    save(token, df, pending_sha, session)
    print(f"Publicado: {_display(row.get('nome'), 'produto sem nome')} | próxima em {frequency} dias")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("Falha na publicação: " + _redact(
            exc,
            os.environ.get("GH_AUTOMATION_TOKEN"),
            os.environ.get("GITHUB_TOKEN"),
            os.environ.get("TELEGRAM_BOT_TOKEN"),
        ))
        raise SystemExit(1) from None
