"""Publicador multicanal do Axadinhos Vippe.

Importar este módulo não faz chamadas de rede. Cada canal exige opt-in próprio,
PUBLISH_CONFIRMED=true, produto aprovado e credenciais recebidas pelo ambiente.
"""
from __future__ import annotations

import base64
import io
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit

import pandas as pd
import requests

from pinterest_publisher import PinterestPublisherError, build_pin_payload, send_pinterest_pin
from telegram_publisher import (
    TelegramPublisherError,
    build_telegram_payload,
    send_telegram_message,
)

OWNER = "Lucas10-GIT"
REPO = "axadinhos-vippe-bot"
BRANCH = "main"
PATH = "data/products.csv"
DEFAULT_FREQUENCY_DAYS = 3
READY_STATUSES = {"", "pronto", "ready"}
CHANNELS = ("telegram", "pinterest")


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
    """Interpret CSV, TOML and environment booleans conservatively."""
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
    """Require a reviewed name, price and HTTPS Shopee affiliate destination."""
    return bool(
        _display(row.get("nome"))
        and _display(row.get("preco"))
        and _valid_shopee_url(row.get("link"))
    )


def enabled_channels(environ: Any) -> list[str]:
    """Return only destinations explicitly opted in for this execution."""
    return [
        channel for channel, variable in (
            ("telegram", "TELEGRAM_PUBLISH_ENABLED"),
            ("pinterest", "PINTEREST_PUBLISH_ENABLED"),
        )
        if parse_bool(environ.get(variable, False), default=False)
    ]


def _normalise_channels(channels: Iterable[str] | None) -> tuple[str, ...]:
    requested = CHANNELS if channels is None else tuple(channels)
    normalized = tuple(channel for channel in CHANNELS if channel in requested)
    return normalized


def _channel_state(row: Any, channel: str) -> str:
    return _display(row.get(f"{channel}_status"), "pendente").casefold()


def _channel_has_receipt(row: Any, channel: str) -> bool:
    id_column = "telegram_message_id" if channel == "telegram" else "pinterest_pin_id"
    return bool(_display(row.get(id_column)))


def is_due(
    row: Any,
    now: datetime | None = None,
    channels: Iterable[str] | None = None,
) -> bool:
    """Check approval, channel state and frequency for the opted-in destinations.

    A product already sent to one channel may complete a pending cross-post
    without waiting its full repost frequency. The global four-hour cooldown
    is still enforced by ``main``.
    """
    if not parse_bool(row.get("ativo", True)):
        return False
    if not parse_bool(row.get("aprovado_publicacao", False), default=False):
        return False
    if not is_publishable(row):
        return False

    targets = _normalise_channels(channels)
    if not targets:
        return False
    states = [_channel_state(row, channel) for channel in targets]
    if any(state not in {"pendente", "enviado"} for state in states):
        return False
    has_pending = any(state == "pendente" for state in states)
    if not has_pending:
        return False

    status = _display(row.get("status_publicacao"), "pronto").casefold()
    completing_crosspost = status == "enviado"
    if status not in READY_STATUSES and not completing_crosspost:
        return False

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    if completing_crosspost:
        return True

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


def select_candidate(
    df: pd.DataFrame,
    now: datetime | None = None,
    channels: Iterable[str] | None = None,
):
    """Return the due (index, row) with the highest score, or None."""
    candidates = [
        (index, row)
        for index, row in df.iterrows()
        if is_due(row, now, channels)
    ]
    return max(candidates, key=lambda item: score(item[1])) if candidates else None


def publication_frequency(row: Any) -> int:
    orders = _number(row.get("pedidos", 0))
    clicks = _number(row.get("cliques", 0))
    if orders >= 2:
        return 2
    if clicks >= 10:
        return 4
    return DEFAULT_FREQUENCY_DAYS


def load(token: str, session=requests) -> tuple[pd.DataFrame, str]:
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{PATH}?ref={BRANCH}"
    response = session.get(url, headers=headers(token), timeout=20)
    response.raise_for_status()
    payload = response.json()
    raw = base64.b64decode(payload["content"]).decode("utf-8-sig")
    return pd.read_csv(io.StringIO(raw)), payload["sha"]


def save(token: str, df: pd.DataFrame, sha: str, session=requests) -> str:
    """Commit the CSV using optimistic concurrency and return its new blob SHA."""
    if not sha:
        raise ValueError("O SHA do CSV é obrigatório para evitar sobrescrever dados inesperadamente.")
    raw = df.to_csv(index=False, lineterminator="\n").encode("utf-8")
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


def _redact(text: Any, *secrets: str | None) -> str:
    safe = str(text)
    for secret in secrets:
        if secret:
            safe = safe.replace(str(secret), "[REDACTED]")
    return safe


def _ensure_state_columns(df: pd.DataFrame) -> pd.DataFrame:
    defaults = {
        "status_publicacao": "pronto",
        "ultima_publicacao": "",
        "proxima_publicacao": "",
        "ultima_tentativa": "",
        "telegram_message_id": "",
        "telegram_status": "pendente",
        "pinterest_status": "pendente",
        "pinterest_pin_id": "",
    }
    for column, default in defaults.items():
        if column not in df.columns:
            df[column] = default
        df[column] = df[column].astype("object")
        df[column] = df[column].where(df[column].notna(), default)
    for channel in CHANNELS:
        df[f"{channel}_status"] = df[f"{channel}_status"].astype(str).str.strip().str.casefold()
        id_column = "telegram_message_id" if channel == "telegram" else "pinterest_pin_id"
        for row_index, stored_row in df.iterrows():
            if _display(stored_row.get(id_column)):
                df.at[row_index, f"{channel}_status"] = "enviado"
    # A previous combined status without a channel receipt is ambiguous after
    # migration; require a human check instead of risking a duplicate post.
    for row_index, stored_row in df.iterrows():
        status = _display(stored_row.get("status_publicacao"), "pronto").casefold()
        if status == "enviado" and not any(
            _channel_has_receipt(stored_row, channel) for channel in CHANNELS
        ):
            df.at[row_index, "status_publicacao"] = "revisar"
    return df


def _persist_review(
    df: pd.DataFrame,
    index: Any,
    channel: str | None,
    token: str,
    sha: str,
    session: Any,
) -> str:
    if channel:
        df.at[index, f"{channel}_status"] = "revisar"
    df.at[index, "status_publicacao"] = "revisar"
    return save(token, df, sha, session)


def main(
    environ=None,
    session=requests,
    now: datetime | None = None,
    product_id: Any | None = None,
) -> int:
    env = os.environ if environ is None else environ
    if not parse_bool(env.get("PUBLISH_CONFIRMED", False), default=False):
        raise RuntimeError("Publicação bloqueada: PUBLISH_CONFIRMED=true é obrigatório.")

    channels = enabled_channels(env)
    if not channels:
        raise RuntimeError("Publicação bloqueada: habilite explicitamente pelo menos um canal.")

    github_token = env.get("GH_AUTOMATION_TOKEN") or env.get("GITHUB_TOKEN")
    telegram_token = env.get("TELEGRAM_PUBLISHER_BOT_TOKEN") if "telegram" in channels else ""
    telegram_chat_id = env.get("TELEGRAM_PUBLISHER_CHAT_ID") if "telegram" in channels else ""
    pinterest_token = env.get("PINTEREST_ACCESS_TOKEN") if "pinterest" in channels else ""
    pinterest_board_id = env.get("PINTEREST_BOARD_ID") if "pinterest" in channels else ""

    required = [("GH_AUTOMATION_TOKEN ou GITHUB_TOKEN", github_token)]
    if "telegram" in channels:
        required.extend([
            ("TELEGRAM_PUBLISHER_BOT_TOKEN", telegram_token),
            ("TELEGRAM_PUBLISHER_CHAT_ID", telegram_chat_id),
        ])
    if "pinterest" in channels:
        required.extend([
            ("PINTEREST_ACCESS_TOKEN", pinterest_token),
            ("PINTEREST_BOARD_ID", pinterest_board_id),
        ])
    missing = [name for name, value in required if not value]
    if missing:
        raise RuntimeError("Secrets ausentes: " + ", ".join(missing))

    df, sha = load(github_token, session)
    df = _ensure_state_columns(df)

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
        candidate = select_candidate(df, current, channels)
    else:
        if "id" not in df.columns:
            raise RuntimeError("Publicação bloqueada: o CSV não tem a coluna id.")
        requested_id = str(product_id).strip()
        matches = df.index[df["id"].map(lambda value: str(value).strip()) == requested_id]
        if len(matches) != 1:
            raise RuntimeError("Publicação bloqueada: produto não encontrado ou ID duplicado.")
        selected_index = matches[0]
        selected_row = df.loc[selected_index]
        if not is_due(selected_row, current, channels):
            raise RuntimeError(
                "Publicação bloqueada: o produto deve estar ativo, aprovado, pronto e elegível para os canais habilitados."
            )
        candidate = (selected_index, selected_row)

    if candidate is None:
        print("Nenhum produto ativo, aprovado, válido e elegível para os canais habilitados.")
        return 0

    index, row = candidate
    review_channels = [channel for channel in channels if _channel_state(row, channel) == "revisar"]
    if review_channels:
        df.at[index, "status_publicacao"] = "revisar"
        save(github_token, df, sha, session)
        raise RuntimeError(
            "Canal(is) aguardando revisão manual antes de novo envio: " + ", ".join(review_channels)
        )

    valid_states = {"pendente", "enviado"}
    unknown_channels = [channel for channel in channels if _channel_state(row, channel) not in valid_states]
    if unknown_channels:
        for channel in unknown_channels:
            df.at[index, f"{channel}_status"] = "revisar"
        df.at[index, "status_publicacao"] = "revisar"
        try:
            save(github_token, df, sha, session)
        except Exception as exc:
            raise RuntimeError(
                "Estado de canal desconhecido e falha ao registrar revisão: "
                + _redact(exc, github_token, telegram_token, pinterest_token)
            ) from None
        raise RuntimeError("Estado de canal desconhecido; revise antes de publicar: " + ", ".join(unknown_channels))

    pending_channels = [channel for channel in channels if _channel_state(row, channel) == "pendente"]
    if not pending_channels:
        print("Os canais habilitados já registram envio; nenhuma republicação foi feita.")
        return 0

    # Validate every pending destination before the first public post.
    try:
        for channel in pending_channels:
            if channel == "telegram":
                build_telegram_payload(row, telegram_chat_id)
            else:
                build_pin_payload(row, pinterest_board_id)
    except (TelegramPublisherError, PinterestPublisherError) as exc:
        try:
            _persist_review(df, index, channel, github_token, sha, session)
        except Exception as save_exc:
            raise RuntimeError(
                "Validação do destino falhou antes de qualquer post; não foi possível registrar a revisão. "
                + _redact(save_exc, github_token, telegram_token, pinterest_token)
            ) from None
        raise RuntimeError(
            f"Pré-validação de {channel.title()} falhou; nenhum canal foi publicado. " + str(exc)
        ) from None

    # Reserve the product in GitHub before making any external request.
    df.at[index, "status_publicacao"] = "enviando"
    df.at[index, "ultima_tentativa"] = current.isoformat()
    checkpoint_sha = save(github_token, df, sha, session)

    current_channel = ""
    try:
        for channel in pending_channels:
            current_channel = channel
            if channel == "telegram":
                result = send_telegram_message(row, telegram_token, telegram_chat_id, session)
                df.at[index, "telegram_message_id"] = str(result["message_id"])
            else:
                result = send_pinterest_pin(row, pinterest_token, pinterest_board_id, session)
                df.at[index, "pinterest_pin_id"] = str(result["id"])
            df.at[index, f"{channel}_status"] = "enviado"
            df.at[index, "ultima_publicacao"] = current.isoformat()
            # Persist each destination result before moving to the next one.
            checkpoint_sha = save(github_token, df, checkpoint_sha, session)

        frequency = publication_frequency(row)
        df.at[index, "status_publicacao"] = "enviado"
        df.at[index, "frequencia_dias"] = frequency
        df.at[index, "proxima_publicacao"] = (current + timedelta(days=frequency)).isoformat()
        checkpoint_sha = save(github_token, df, checkpoint_sha, session)
    except Exception as exc:
        if current_channel and _channel_state(df.loc[index], current_channel) != "enviado":
            df.at[index, f"{current_channel}_status"] = "revisar"
        df.at[index, "status_publicacao"] = "revisar"
        try:
            save(github_token, df, checkpoint_sha, session)
        except Exception as save_exc:
            raise RuntimeError(
                "Falha no envio e no registro do estado; o produto permanece bloqueado para revisão. "
                + _redact(save_exc, github_token, telegram_token, pinterest_token)
            ) from None
        raise RuntimeError(
            f"{current_channel.title() or 'Canal'} não confirmou o envio; produto marcado para revisão manual. "
            + _redact(exc, github_token, telegram_token, pinterest_token)
        ) from None

    channel_names = " + ".join(channel.title() for channel in channels)
    print(
        f"Publicado: {_display(row.get('nome'), 'produto sem nome')} | "
        f"canais: {channel_names} | próxima em {frequency} dias"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            "Falha na publicação: "
            + _redact(
                exc,
                os.environ.get("GH_AUTOMATION_TOKEN"),
                os.environ.get("GITHUB_TOKEN"),
                os.environ.get("TELEGRAM_PUBLISHER_BOT_TOKEN"),
                os.environ.get("PINTEREST_ACCESS_TOKEN"),
            )
        )
        raise SystemExit(1) from None
