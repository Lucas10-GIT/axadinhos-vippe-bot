"""Pinterest-only publisher for the Axadinhos Vippe offer catalog.

Importing this module does not make network calls. Publishing requires an
explicit Pinterest opt-in, PUBLISH_CONFIRMED=true, an approved product, and
credentials passed through the execution environment.
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

OWNER = "Lucas10-GIT"
REPO = "axadinhos-vippe-bot"
BRANCH = "main"
PATH = "data/products.csv"
DEFAULT_FREQUENCY_DAYS = 3
READY_STATUSES = {"", "pronto", "ready"}
CHANNELS = ("pinterest",)


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
    """Return the earliest next global publication time, if recorded."""
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
        _ = parsed.port
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
    """Return only Pinterest when its explicit opt-in is enabled."""
    return [
        "pinterest"
    ] if parse_bool(environ.get("PINTEREST_PUBLISH_ENABLED", False), default=False) else []


def _normalise_channels(channels: Iterable[str] | None) -> tuple[str, ...]:
    requested = CHANNELS if channels is None else tuple(channels)
    return tuple(channel for channel in CHANNELS if channel in requested)


def _channel_state(row: Any, channel: str) -> str:
    return _display(row.get(f"{channel}_status"), "pendente").casefold()


def is_due(
    row: Any,
    now: datetime | None = None,
    channels: Iterable[str] | None = None,
) -> bool:
    """Check approval, Pinterest state, and per-product frequency."""
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
    if not any(state == "pendente" for state in states):
        return False

    status = _display(row.get("status_publicacao"), "pronto").casefold()
    if status == "enviado":
        # A completed record cannot be sent again; the channel receipt is the
        # authoritative idempotency guard for this single-channel publisher.
        return False
    if status not in READY_STATUSES:
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


def rank_candidates(
    df: pd.DataFrame,
    now: datetime | None = None,
    channels: Iterable[str] | None = None,
) -> list[tuple[Any, Any]]:
    """Return eligible products in the same priority order used by publishing."""
    candidates = [
        (index, row)
        for index, row in df.iterrows()
        if is_due(row, now, channels)
    ]
    return sorted(candidates, key=lambda item: score(item[1]), reverse=True)


def select_candidate(
    df: pd.DataFrame,
    now: datetime | None = None,
    channels: Iterable[str] | None = None,
):
    candidates = rank_candidates(df, now, channels)
    return candidates[0] if candidates else None


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
        "pinterest_status": "pendente",
        "pinterest_pin_id": "",
    }
    for column, default in defaults.items():
        if column not in df.columns:
            df[column] = default
        df[column] = df[column].astype("object")
        df[column] = df[column].where(df[column].notna(), default)
    df["pinterest_status"] = df["pinterest_status"].astype(str).str.strip().str.casefold()
    for row_index, stored_row in df.iterrows():
        if _display(stored_row.get("pinterest_pin_id")):
            df.at[row_index, "pinterest_status"] = "enviado"
        status = _display(stored_row.get("status_publicacao"), "pronto").casefold()
        if status == "enviado" and not _display(stored_row.get("pinterest_pin_id")):
            df.at[row_index, "status_publicacao"] = "revisar"
    return df


def _persist_review(
    df: pd.DataFrame,
    index: Any,
    token: str,
    sha: str,
    session: Any,
) -> str:
    df.at[index, "pinterest_status"] = "revisar"
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
        raise RuntimeError("Publicação bloqueada: habilite explicitamente Pinterest.")

    github_token = env.get("GH_AUTOMATION_TOKEN") or env.get("GITHUB_TOKEN")
    pinterest_token = env.get("PINTEREST_ACCESS_TOKEN")
    pinterest_board_id = env.get("PINTEREST_BOARD_ID")
    missing = [
        name for name, value in (
            ("GH_AUTOMATION_TOKEN ou GITHUB_TOKEN", github_token),
            ("PINTEREST_ACCESS_TOKEN", pinterest_token),
            ("PINTEREST_BOARD_ID", pinterest_board_id),
        ) if not value
    ]
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
                "Publicação bloqueada: o produto deve estar ativo, aprovado, pronto e elegível para Pinterest."
            )
        candidate = (selected_index, selected_row)

    if candidate is None:
        print("Nenhum produto ativo, aprovado, válido e elegível para Pinterest.")
        return 0

    index, row = candidate
    if _channel_state(row, "pinterest") == "revisar":
        df.at[index, "status_publicacao"] = "revisar"
        save(github_token, df, sha, session)
        raise RuntimeError("Pinterest aguarda revisão manual antes de novo envio.")

    state = _channel_state(row, "pinterest")
    if state not in {"pendente", "enviado"}:
        _persist_review(df, index, github_token, sha, session)
        raise RuntimeError("Estado Pinterest desconhecido; revise antes de publicar.")
    if state == "enviado":
        print("O produto já tem recibo de Pin; nenhuma republicação foi feita.")
        return 0

    try:
        build_pin_payload(row, pinterest_board_id)
    except PinterestPublisherError as exc:
        try:
            _persist_review(df, index, github_token, sha, session)
        except Exception as save_exc:
            raise RuntimeError(
                "Pré-validação falhou e não foi possível registrar a revisão. "
                + _redact(save_exc, github_token, pinterest_token)
            ) from None
        raise RuntimeError("Pré-validação do Pinterest falhou; nenhum Pin foi criado. " + str(exc)) from None

    # Reserve the product in GitHub before making any external request.
    df.at[index, "status_publicacao"] = "enviando"
    df.at[index, "ultima_tentativa"] = current.isoformat()
    checkpoint_sha = save(github_token, df, sha, session)

    try:
        result = send_pinterest_pin(row, pinterest_token, pinterest_board_id, session)
        df.at[index, "pinterest_pin_id"] = str(result["id"])
        df.at[index, "pinterest_status"] = "enviado"
        df.at[index, "ultima_publicacao"] = current.isoformat()
        checkpoint_sha = save(github_token, df, checkpoint_sha, session)

        frequency = publication_frequency(row)
        df.at[index, "status_publicacao"] = "enviado"
        df.at[index, "frequencia_dias"] = frequency
        df.at[index, "proxima_publicacao"] = (current + timedelta(days=frequency)).isoformat()
        save(github_token, df, checkpoint_sha, session)
    except Exception as exc:
        if _channel_state(df.loc[index], "pinterest") != "enviado":
            df.at[index, "pinterest_status"] = "revisar"
        df.at[index, "status_publicacao"] = "revisar"
        try:
            save(github_token, df, checkpoint_sha, session)
        except Exception as save_exc:
            raise RuntimeError(
                "Falha no envio e no registro do estado; o produto permanece bloqueado para revisão. "
                + _redact(save_exc, github_token, pinterest_token)
            ) from None
        raise RuntimeError(
            "Pinterest não confirmou o envio; produto marcado para revisão manual. "
            + _redact(exc, github_token, pinterest_token)
        ) from None

    frequency = publication_frequency(row)
    print(
        f"Publicado no Pinterest: {_display(row.get('nome'), 'produto sem nome')} | "
        f"próxima publicação após {frequency} dias"
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
                os.environ.get("PINTEREST_ACCESS_TOKEN"),
            )
        )
        raise SystemExit(1) from None
