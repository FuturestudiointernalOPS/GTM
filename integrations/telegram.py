"""Minimal Telegram notifier: the bot speaks, it never listens.

Why one-way: reading replies and approving actions needs a single reader, and
that reader will be Hermes. A second one polling the same bot would steal its
updates, so this module only sends messages and needs no running gateway.

Why the "safely" variant: a notification that fails must never lose a run or a
record. Pipelines call send_message_safely() and carry on; the text is still
written to the log so nothing disappears silently.
"""
import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from config import settings

log = logging.getLogger(__name__)

API_ROOT = "https://api.telegram.org"

# Telegram refuses any message longer than this.
MAX_TEXT = 4096

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class TelegramError(RuntimeError):
    """The message was refused; sending it again unchanged will not help."""


class TelegramTemporaryError(TelegramError):
    """Rate limit, server problem or network down; retrying may succeed."""


def is_configured() -> bool:
    """True when both the bot token and the chat id are set."""
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def send_message(text: str) -> int:
    """Send a plain notification to the configured chat; return the message id.

    Plain text on purpose: without HTML or Markdown, a company name containing
    <, &, _ or * can never make Telegram refuse the whole message.
    """
    if not is_configured():
        raise TelegramError(
            "Telegram is not configured: set TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID in the .env file"
        )

    return _send_with_retry(
        payload_text=text[:MAX_TEXT],
        token=settings.TELEGRAM_BOT_TOKEN,
        chat_id=settings.TELEGRAM_CHAT_ID,
    )


def send_message_safely(text: str) -> bool:
    """Send a notification; on failure log it and return False, never raise.

    This is the call workflows should use, so an unreachable Telegram cannot
    abort a collection or an enrichment run.
    """
    try:
        message_id = send_message(text)
    except (TelegramError, httpx.HTTPError) as error:
        log.warning("Telegram notification not sent: %s | text: %s", error, text)
        return False

    log.info("Telegram notification sent (message %s)", message_id)
    return True


@retry(
    retry=retry_if_exception_type(TelegramTemporaryError),
    wait=wait_exponential_jitter(initial=1, max=20),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _send_with_retry(payload_text: str, token: str, chat_id: str) -> int:
    # The token is part of the URL. It is never logged, and never echoed in an
    # error message, so a log file cannot leak it.
    client = httpx.Client(timeout=TIMEOUT)
    try:
        response = client.post(
            f"{API_ROOT}/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": payload_text,
                "disable_web_page_preview": True,
            },
        )
    except httpx.TransportError as error:
        # Only the error type: the raw message may quote the URL, token included.
        raise TelegramTemporaryError(
            f"cannot reach Telegram ({type(error).__name__})"
        ) from error
    finally:
        client.close()

    # 429 = rate limit, 5xx = Telegram side: both are worth another attempt.
    if response.status_code == 429 or response.status_code >= 500:
        raise TelegramTemporaryError(
            f"Telegram answered {response.status_code}: {_description(response)}"
        )

    if response.status_code >= 400:
        raise TelegramError(
            f"Telegram refused the message ({response.status_code}): "
            f"{_description(response)}"
        )

    body = _body(response)
    if not body.get("ok"):
        raise TelegramError(
            f"Telegram refused the message: {body.get('description', 'no description')}"
        )

    return body.get("result", {}).get("message_id")


def _body(response: httpx.Response) -> dict:
    """Read Telegram's JSON answer, or stop with a clear error."""
    try:
        body = response.json()
    except ValueError as error:
        raise TelegramError("Telegram answered with unreadable content") from error
    return body if isinstance(body, dict) else {}


def _description(response: httpx.Response) -> str:
    """Telegram's own explanation of an error, when it gives one."""
    return str(_body(response).get("description", "no description"))
