"""Send a single, silent, non-promotional Telegram smoke-test message."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MESSAGE = (
    "TESTE TÉCNICO — Axadinhos Vippe\n"
    "Mensagem de validação enviada pelo GitHub Actions.\n"
    "Este não é um anúncio de produto."
)


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise SystemExit("Faltam TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID nos secrets do workflow.")

    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urlencode(
            {
                "chat_id": chat_id,
                "text": MESSAGE,
                "disable_notification": "true",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
            description = str(payload.get("description", "erro sem descrição"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            description = "resposta de erro sem JSON válido"
        description = description.replace(token, "[REDACTED]")
        raise SystemExit(f"Telegram recusou o teste (HTTP {error.code}): {description}") from None
    except (URLError, TimeoutError, OSError):
        raise SystemExit("Falha de conexão com a API do Telegram; detalhes omitidos para proteger secrets.") from None

    if not result.get("ok"):
        description = str(result.get("description", "erro sem descrição")).replace(token, "[REDACTED]")
        raise SystemExit(f"Telegram recusou o teste: {description}")

    message_id = result.get("result", {}).get("message_id", "desconhecido")
    print(f"Mensagem de teste enviada com sucesso. message_id={message_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
