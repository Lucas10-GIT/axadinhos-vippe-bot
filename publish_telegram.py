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

from pinterest_publisher import PinterestPublisherError, build_pin_payload, send_pinterest_pin

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


def publication_cooldown_until(df: pd.DataFrame, hours: int = 4) -> datetime | None:
    """Return the earliest next global publication time, if one is recorded."""
    if "ultima_publicacao" not in df.columns:
        return None
    published = [
        parsed for value in df["ultima_publicacao"]
        if (parsed := parse_utc(value)) is not None
    ]
    if not published:
        return None
    return max(published) + timedelta(hours=max(0, int(hours)))


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


def main(
    environ=os.environ,
    session=requests,
    now: datetime | None = None,
    product_id: Any | None = None,
) -> int:
    if not parse_bool(environ.get("PUBLISH_CONFIRMED", False), default=False):
        raise RuntimeError("Publicação bloqueada: o workflow não confirmou PUBLISH_CONFIRMED=true.")

    token = environ.get("GH_AUTOMATION_TOKEN") or environ.get("GITHUB_TOKEN")
    telegram_token = environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = environ.get("TELEGRAM_CHAT_ID")
    pinterest_enabled = parse_bool(environ.get("PINTEREST_PUBLISH_ENABLED", False), default=False)
    pinterest_token = environ.get("PINTEREST_ACCESS_TOKEN")
    pinterest_board_id = environ.get("PINTEREST_BOARD_ID")
    missing = [
        name for name, value in (
            ("GH_AUTOMATION_TOKEN ou GITHUB_TOKEN", token),
            ("TELEGRAM_BOT_TOKEN", telegram_token),
            ("TELEGRAM_CHAT_ID", chat_id),
        ) if not value
    ]
    if pinterest_enabled:
        missing.extend(
            name for name, value in (
                ("PINTEREST_ACCESS_TOKEN", pinterest_token),
                ("PINTEREST_BOARD_ID", pinterest_board_id),
            ) if not value
        )
    if missing:
        raise RuntimeError("Secrets/variáveis ausentes: " + ", ".join(missing))

    df, sha = load(token, session)
    state_defaults = {
        "status_publicacao": "pronto",
        "ultima_publicacao": "",
        "proxima_publicacao": "",
        "ultima_tentativa": "",
        "telegram_message_id": "",
        "telegram_status": "pendente",
        "pinterest_status": "pendente",
        "pinterest_pin_id": "",
    }
    for column, default in state_defaults.items():
        if column not in df.columns:
            df[column] = default
        df[column] = df[column].astype("object")
        df[column] = df[column].where(df[column].notna(), default)
    df["telegram_status"] = df["telegram_status"].astype(str).str.strip().str.casefold()
    df["pinterest_status"] = df["pinterest_status"].astype(str).str.strip().str.casefold()
    for row_index, stored_row in df.iterrows():
        if _display(stored_row.get("telegram_message_id")):
            df.at[row_index, "telegram_status"] = "enviado"
        if _display(stored_row.get("pinterest_pin_id")):
            df.at[row_index, "pinterest_status"] = "enviado"
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    cooldown_until = publication_cooldown_until(df, hours=4)
    if cooldown_until is not None and current < cooldown_until:
        message = (
            "Publicação adiada pelo intervalo global mínimo de quatro horas; "
            f"próxima janela após {cooldown_until.isoformat()}."
        )
        if product_id is not None:
            raise RuntimeError(message)
        print(message)
        return 0

    if product_id is None:
        candidate = select_candidate(df, current)
    else:
        if "id" not in df.columns:
            raise RuntimeError("Publicação bloqueada: o CSV não tem a coluna id.")
        requested_id = str(product_id).strip()
        matches = df.index[df["id"].map(lambda value: str(value).strip()) == requested_id]
        if len(matches) != 1:
            raise RuntimeError("Publicação bloqueada: produto não encontrado ou ID duplicado.")
        selected_index = matches[0]
        selected_row = df.loc[selected_index]
        if not is_due(selected_row, current):
            raise RuntimeError(
                "Publicação bloqueada: o produto escolhido precisa estar ativo, aprovado, pronto e vencido."
            )
        candidate = (selected_index, selected_row)
    if candidate is None:
        print("Nenhum produto ativo, aprovado, válido e vencido para publicação.")
        return 0

    index, row = candidate
    channels = ["telegram"] + (["pinterest"] if pinterest_enabled else [])
    review_channels = [
        channel for channel in channels
        if _display(row.get(f"{channel}_status"), "pendente").casefold() == "revisar"
    ]
    if review_channels:
        df.at[index, "status_publicacao"] = "revisar"
        save(token, df, sha, session)
        raise RuntimeError(
            "Canal(is) aguardando revisão antes de novo envio: " + ", ".join(review_channels)
        )

    pending_channels = [
        channel for channel in channels
        if _display(row.get(f"{channel}_status"), "pendente").casefold() == "pendente"
    ]
    unknown_channels = [
        channel for channel in channels
        if _display(row.get(f"{channel}_status"), "pendente").casefold() not in {"pendente", "enviado"}
    ]
    if unknown_channels:
        df.at[index, "status_publicacao"] = "revisar"
        save(token, df, sha, session)
        raise RuntimeError(
            "Estado de canal desconhecido; revise antes de publicar: " + ", ".join(unknown_channels)
        )
    if not pending_channels:
        df.at[index, "status_publicacao"] = "enviado"
        save(token, df, sha, session)
        print("Todos os canais configurados já registram envio; nenhuma republicação foi feita.")
        return 0

    if "pinterest" in pending_channels:
        try:
            build_pin_payload(row, pinterest_board_id)
        except PinterestPublisherError as exc:
            df.at[index, "status_publicacao"] = "revisar"
            df.at[index, "pinterest_status"] = "revisar"
            try:
                save(token, df, sha, session)
            except Exception as save_exc:
                raise RuntimeError(
                    "Pin inválido antes do envio; nenhum canal foi publicado e o estado não pôde ser registrado. "
                    + _redact(save_exc, token, telegram_token, pinterest_token)
                ) from None
            raise RuntimeError(
                "Pin inválido antes do envio; nenhum canal foi publicado e o produto foi marcado para revisão. "
                + str(exc)
            ) from None

    # Reserva persistente antes de publicar: quedas ou respostas ambíguas
    # ficam bloqueadas para revisão manual, em vez de gerar duplicatas.
    df.at[index, "status_publicacao"] = "enviando"
    df.at[index, "ultima_tentativa"] = current.isoformat()
    pending_sha = save(token, df, sha, session)

    current_channel = ""
    try:
        for position, channel in enumerate(pending_channels):
            current_channel = channel
            if channel == "telegram":
                result = send_telegram(row, telegram_token, chat_id, session)
                message_id = result.get("result", {}).get("message_id", "")
                df.at[index, "telegram_message_id"] = str(message_id) if message_id != "" else ""
            else:
                result = send_pinterest_pin(row, pinterest_token, pinterest_board_id, session)
                df.at[index, "pinterest_pin_id"] = str(result["id"])
            df.at[index, f"{channel}_status"] = "enviado"
            df.at[index, "ultima_publicacao"] = current.isoformat()
            # Checkpoint between channels so a successful destination is not
            # repeated if the next platform rejects or times out.
            if position < len(pending_channels) - 1:
                pending_sha = save(token, df, pending_sha, session)

        frequency = publication_frequency(row)
        df.at[index, "status_publicacao"] = "enviado"
        df.at[index, "frequencia_dias"] = frequency
        df.at[index, "proxima_publicacao"] = (current + timedelta(days=frequency)).isoformat()
        save(token, df, pending_sha, session)
    except Exception as exc:
        if current_channel:
            df.at[index, f"{current_channel}_status"] = "revisar"
        df.at[index, "status_publicacao"] = "revisar"
        try:
            save(token, df, pending_sha, session)
        except Exception as save_exc:
            raise RuntimeError(
                "Falha no envio e no registro do estado; o produto permanece reservado para revisão. "
                + _redact(save_exc, token, telegram_token, pinterest_token)
            ) from None
        raise RuntimeError(
            f"{current_channel.title() or 'Canal'} não confirmou o envio; produto marcado para revisão manual. "
            + _redact(exc, token, telegram_token, pinterest_token)
        ) from None

    channel_names = " + ".join(channel.title() for channel in channels)
    print(f"Publicado: {_display(row.get('nome'), 'produto sem nome')} | canais: {channel_names} | próxima em {frequency} dias")
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
            os.environ.get("PINTEREST_ACCESS_TOKEN"),
        ))
        raise SystemExit(1) from None
