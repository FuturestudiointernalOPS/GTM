import logging

import config  # noqa: F401 - importing it installs the protection
from config.log_safety import HTTP_LOGGERS, redact

FAKE_TOKEN = "123456789:AAFakeTokenForTests_only-xyz"


def test_redact_telegram_token_in_url():
    url = f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"
    assert redact(url) == "https://api.telegram.org/bot***/sendMessage"


def test_redact_query_string_keys_and_bearer():
    text = "GET https://serpapi.com/search?q=x&api_key=SECRET123&num=10"
    assert redact(text) == "GET https://serpapi.com/search?q=x&api_key=***&num=10"
    assert redact("Authorization: Bearer abc.def") == "Authorization: Bearer ***"


def test_text_without_secret_is_unchanged():
    assert redact("Pipeline run: 170 page(s) found") == (
        "Pipeline run: 170 page(s) found"
    )


def test_http_loggers_are_capped_at_warning():
    for name in HTTP_LOGGERS:
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


def test_no_token_reaches_the_log_output(caplog):
    caplog.set_level(logging.DEBUG)
    url = f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"

    logging.getLogger("httpx").warning("HTTP Request: POST %s", url)
    logging.getLogger("gtm").error("send failed for %s", url)

    assert FAKE_TOKEN not in caplog.text
    assert "bot***/sendMessage" in caplog.text


def test_info_request_lines_are_dropped(caplog):
    caplog.set_level(logging.INFO)
    logging.getLogger("httpx").info("HTTP Request: POST https://example.com")
    assert "HTTP Request" not in caplog.text
