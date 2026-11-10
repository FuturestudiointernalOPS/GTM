"""Tests for the Exa search wrapper. No network, no real API key."""
from types import SimpleNamespace
from typing import ClassVar

import pytest
from exa_py.errors import ExaTimeoutError
from tenacity import wait_none

from config import settings
from integrations import exa

FAKE_KEY = "fake-exa-key"


class FakeExa:
    """Stands in for the SDK client and records every call."""

    calls: ClassVar[list[dict]] = []
    answers: ClassVar[list] = []

    def __init__(self, api_key):
        assert api_key == FAKE_KEY

    def search(self, query, **options):
        self.calls.append({"query": query, **options})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(results=answer)


@pytest.fixture(autouse=True)
def fake_exa(monkeypatch):
    monkeypatch.setattr(settings, "EXA_API_KEY", FAKE_KEY)
    monkeypatch.setattr(exa, "Exa", FakeExa)
    FakeExa.calls = []
    FakeExa.answers = []
    # Retries must not sleep during tests.
    exa._search_with_retry.retry.wait = wait_none()


def _result(url="https://example.ru", title="Studio", text=None):
    return SimpleNamespace(
        url=url,
        title=title,
        published_date="2026-01-02",
        author="Red",
        text=text,
    )


def test_search_returns_the_same_keys_for_every_row():
    FakeExa.answers = [
        [
            _result(),
            SimpleNamespace(
                url="https://b.ru",
                title=None,
                published_date=None,
                author=None,
                text=None,
            ),
        ]
    ]

    rows = exa.search("gaming studio", num_results=5, include_domains=["vk.com"])

    assert rows == [
        {
            "url": "https://example.ru",
            "title": "Studio",
            "published_date": "2026-01-02",
            "author": "Red",
            "text": None,
        },
        {
            "url": "https://b.ru",
            "title": None,
            "published_date": None,
            "author": None,
            "text": None,
        },
    ]
    assert FakeExa.calls == [
        {
            "query": "gaming studio",
            "num_results": 5,
            "include_domains": ["vk.com"],
        }
    ]


def test_text_is_requested_only_when_asked():
    FakeExa.answers = [[_result(text="page body")]]

    rows = exa.search("gaming studio", with_text=True, max_characters=500)

    assert rows[0]["text"] == "page body"
    assert FakeExa.calls[0]["contents"] == {"text": {"max_characters": 500}}


def test_text_filters_replace_unsupported_operators():
    FakeExa.answers = [[_result()]]

    exa.search("gaming studio", include_text=("erid",), exclude_text=("казино",))

    assert FakeExa.calls[0]["include_text"] == ["erid"]
    assert FakeExa.calls[0]["exclude_text"] == ["казино"]


def test_empty_query_is_refused_before_the_network():
    with pytest.raises(ValueError, match="must not be empty"):
        exa.search("   ")

    assert FakeExa.calls == []


def test_more_than_one_hundred_results_is_refused():
    with pytest.raises(ValueError, match="num_results"):
        exa.search("gaming studio", num_results=101)


def test_unconfigured_exa_says_what_to_set(monkeypatch):
    monkeypatch.setattr(settings, "EXA_API_KEY", None)

    assert exa.is_configured() is False
    with pytest.raises(exa.ExaNotConfigured, match="EXA_API_KEY"):
        exa.search("gaming studio")


def test_a_rate_limit_is_retried():
    FakeExa.answers = [
        Exception("Request failed with status code 429: slow down"),
        [_result()],
    ]

    rows = exa.search("gaming studio")

    assert len(rows) == 1
    assert len(FakeExa.calls) == 2


def test_a_bad_request_is_not_retried():
    FakeExa.answers = [Exception("Request failed with status code 400: bad query")]

    with pytest.raises(exa.ExaError) as caught:
        exa.search("gaming studio")

    assert not isinstance(caught.value, exa.ExaTemporaryError)
    assert len(FakeExa.calls) == 1


def test_a_timeout_is_retried_then_reported_as_temporary():
    FakeExa.answers = [ExaTimeoutError("read timed out") for _ in range(4)]

    with pytest.raises(exa.ExaTemporaryError):
        exa.search("gaming studio")

    assert len(FakeExa.calls) == 4


def test_a_connection_failure_is_retried():
    FakeExa.answers = [ConnectionError("network down"), [_result()]]

    rows = exa.search("gaming studio")

    assert len(rows) == 1
    assert len(FakeExa.calls) == 2


def test_a_server_error_is_retried_then_reported_as_temporary():
    FakeExa.answers = [
        Exception("Request failed with status code 503") for _ in range(4)
    ]

    with pytest.raises(exa.ExaTemporaryError):
        exa.search("gaming studio")

    assert len(FakeExa.calls) == 4
