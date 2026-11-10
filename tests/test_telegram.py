"""Tests for the minimal Telegram notifier. No network, no real bot."""
import json

import httpx
import pytest
import respx
from tenacity import wait_none

from config import settings
from integrations import telegram

TOKEN = "123456:fake-token-for-tests"
CHAT = "-1001234567890"
URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


@pytest.fixture(autouse=True)
def telegram_settings(monkeypatch):
    """Pretend the .env is filled in."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", CHAT)


@pytest.fixture(autouse=True)
def no_real_wait():
    """Retries must not sleep during tests."""
    telegram._send_with_retry.retry.wait = wait_none()


def _ok(message_id: int = 42) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {"message_id": message_id}})


@respx.mock
def test_sends_plain_text_to_the_configured_chat():
    route = respx.post(URL).mock(return_value=_ok(42))

    assert telegram.send_message("Nouvelle entreprise qualifiée") == 42

    payload = json.loads(route.calls.last.request.content)
    assert payload["chat_id"] == CHAT
    assert payload["text"] == "Nouvelle entreprise qualifiée"
    # No parse_mode: data must never be interpreted as formatting.
    assert "parse_mode" not in payload


@respx.mock
def test_a_refusal_is_not_retried():
    route = respx.post(URL).mock(
        return_value=httpx.Response(400, json={"ok": False, "description": "chat not found"})
    )

    with pytest.raises(telegram.TelegramError, match="chat not found"):
        telegram.send_message("test")

    assert route.call_count == 1


@respx.mock
def test_a_rate_limit_is_retried():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(429, json={"ok": False, "description": "Too Many Requests"}),
            _ok(7),
        ]
    )

    assert telegram.send_message("test") == 7
    assert route.call_count == 2


@respx.mock
def test_text_longer_than_telegram_allows_is_cut():
    route = respx.post(URL).mock(return_value=_ok(1))

    telegram.send_message("a" * (telegram.MAX_TEXT + 500))

    payload = json.loads(route.calls.last.request.content)
    assert len(payload["text"]) == telegram.MAX_TEXT


@respx.mock
def test_the_token_never_appears_in_an_error():
    respx.post(URL).mock(
        return_value=httpx.Response(403, json={"ok": False, "description": "Forbidden"})
    )

    with pytest.raises(telegram.TelegramError) as caught:
        telegram.send_message("test")

    assert TOKEN not in str(caught.value)


@respx.mock
def test_safe_send_returns_false_instead_of_raising():
    respx.post(URL).mock(side_effect=httpx.ConnectError("network down"))

    assert telegram.send_message_safely("test") is False


@respx.mock
def test_safe_send_returns_true_on_success():
    respx.post(URL).mock(return_value=_ok(3))

    assert telegram.send_message_safely("test") is True


def test_unconfigured_telegram_says_what_to_set(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", None)

    assert telegram.is_configured() is False
    with pytest.raises(telegram.TelegramError, match="TELEGRAM_BOT_TOKEN"):
        telegram.send_message("test")
