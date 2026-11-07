"""Optional manual handoff of an approved WhatsApp draft to an owned HTTPS endpoint.

This adapter does not send WhatsApp messages, accept recipient data, or run on a
schedule. The receiving endpoint must treat the payload as a draft (send=false).
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import time
from typing import Any
from urllib.parse import urlsplit

import requests

from social_copy import SocialCopyError, build_manual_copies

TIMEOUT = (5, 15)
MIN_SIGNING_SECRET_CHARS = 32
MIN_ADMIN_PIN_CHARS = 16
USER_AGENT = "AxadinhosVippeBot-DraftWebhook/1.0"


class WhatsAppDraftWebhookError(ValueError):
    """Raised when the optional draft handoff is not safely configured or fails."""


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _approved(row: Any) -> bool:
    try:
        return _truthy(row.get("ativo", False)) and _truthy(row.get("aprovado_publicacao", False))
    except Exception:
        return False


def verify_whatsapp_webhook_admin_pin(entered_pin: Any, configured_pin: Any) -> bool:
    """Constant-time check for the additional gate on a public Streamlit app."""
    if not isinstance(entered_pin, str) or not isinstance(configured_pin, str):
        return False
    if len(configured_pin) < MIN_ADMIN_PIN_CHARS:
        return False
    return hmac.compare_digest(entered_pin.encode("utf-8"), configured_pin.encode("utf-8"))


def _validate_endpoint(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise WhatsAppDraftWebhookError("Configure uma URL HTTPS válida para o webhook.")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        port = parsed.port
    except (ValueError, UnicodeError):
        raise WhatsAppDraftWebhookError("A URL do webhook é inválida.") from None
    try:
        ip = ipaddress.ip_address(hostname.strip("[]")) if hostname else None
    except ValueError:
        ip = None

    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or port not in (None, 443)
        or hostname.casefold() in {"localhost", "localhost.localdomain"}
        or hostname.casefold().endswith(".local")
        or (ip is not None and not ip.is_global)
    ):
        raise WhatsAppDraftWebhookError(
            "O webhook deve usar HTTPS público na porta padrão, sem credenciais, query ou fragmento na URL."
        )
    return value


def build_whatsapp_draft_payload(row: Any) -> dict[str, Any]:
    """Return an approved-product draft payload with no recipient or send command."""
    if not _approved(row):
        raise WhatsAppDraftWebhookError("Somente produtos ativos e aprovados podem ir ao webhook.")
    try:
        product_id = str(row.get("id", "")).strip()
        name = str(row.get("nome", "")).strip()
        price = str(row.get("preco", "")).strip()
        copies = build_manual_copies(row)
    except SocialCopyError as exc:
        raise WhatsAppDraftWebhookError(str(exc)) from None
    except Exception:
        raise WhatsAppDraftWebhookError("Não foi possível preparar o rascunho do produto.") from None
    if not product_id or product_id.casefold() in {"nan", "<na>"}:
        raise WhatsAppDraftWebhookError("O produto precisa ter um ID antes do handoff.")

    return {
        "event": "axadinhos.whatsapp.draft.created",
        "version": 1,
        "action": "create_draft",
        "send": False,
        "product": {
            "id": product_id,
            "name": name,
            "price": price,
            "affiliate_url": copies["affiliate_link"],
        },
        "draft": {
            "channel": "whatsapp",
            "text": copies["whatsapp"],
        },
    }


def send_whatsapp_draft_webhook(
    row: Any,
    *,
    enabled: bool,
    webhook_url: str,
    signing_secret: str,
    session: Any = requests,
    now: int | None = None,
) -> dict[str, Any]:
    """POST one approved draft to the configured endpoint; never auto-retry."""
    if not _truthy(enabled):
        raise WhatsAppDraftWebhookError("O webhook opcional está desativado.")
    endpoint = _validate_endpoint(webhook_url)
    if not isinstance(signing_secret, str) or len(signing_secret) < MIN_SIGNING_SECRET_CHARS:
        raise WhatsAppDraftWebhookError("O segredo HMAC precisa ter pelo menos 32 caracteres.")

    payload = build_whatsapp_draft_payload(row)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time() if now is None else now))
    signature = hmac.new(
        signing_secret.encode("utf-8"),
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    idempotency_key = hashlib.sha256(b"axadinhos-whatsapp-draft-v1." + body).hexdigest()
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": USER_AGENT,
        "X-Axadinhos-Event": payload["event"],
        "X-Axadinhos-Timestamp": timestamp,
        "X-Axadinhos-Signature": f"sha256={signature}",
        "Idempotency-Key": idempotency_key,
    }

    try:
        response = session.post(
            endpoint,
            data=body,
            headers=headers,
            timeout=TIMEOUT,
            allow_redirects=False,
        )
    except Exception:
        raise WhatsAppDraftWebhookError(
            "Falha ou resposta incerta do webhook. Verifique a fila do endpoint antes de tentar novamente."
        ) from None

    status = getattr(response, "status_code", 0)
    if not isinstance(status, int) or status < 200 or status >= 300:
        raise WhatsAppDraftWebhookError(
            f"O endpoint não aceitou o rascunho (HTTP {status or 'desconhecido'}). "
            "Nenhuma repetição automática foi feita."
        )
    return {"accepted": True, "idempotency_key": idempotency_key}
