"""Tests for the SerpApi backend. No network, no real key."""
import httpx
import pytest
import respx
from tenacity import wait_none

from config import settings
from integrations import serpapi

FAKE_KEY = "fake-serpapi-key"
URL = "https://serpapi.com/search.json"


@pytest.fixture(autouse=True)
def serpapi_settings(monkeypatch):
    monkeypatch.setattr(settings, "SERPAPI_API_KEY", FAKE_KEY)
    serpapi._search_with_retry.retry.wait = wait_none()


def _ok(results=None):
    return httpx.Response(
        200,
        json={
            "organic_results": [
                {
                    "position": 1,
                    "title": "Red",
                    "link": "https://www.twitch.tv/red",
                    "snippet": "CS2 streamer",
                    "source": "Twitch",
                    "date": "2026-01-01",
                },
                {"position": 2, "title": "No link"},
            ]
        }
        if results is None
        else {"organic_results": results},
    )


@respx.mock
def test_search_returns_normalized_rows_and_keeps_the_classic_query():
    route = respx.get(URL).mock(return_value=_ok())

    rows = serpapi.search(
        "site:twitch.tv стример CS2 -казино",
        num_results=5,
    )

    assert rows == [
        {
            "url": "https://www.twitch.tv/red",
            "title": "Red",
            "published_date": "2026-01-01",
            "author": None,
            "text": None,
            "snippet": "CS2 streamer",
            "source": "Twitch",
            "position": 1,
        }
    ]
    params = route.calls.last.request.url.params
    assert params["engine"] == "google"
    assert params["q"] == "site:twitch.tv стример CS2 -казино"
    assert params["num"] == "5"
    assert params["hl"] == "ru"
    assert params["gl"] == "ru"
    assert params["api_key"] == FAKE_KEY


@respx.mock
def test_engine_language_country_and_location_can_be_overridden():
    route = respx.get(URL).mock(return_value=_ok(results=[]))

    serpapi.search(
        "стример CS2",
        engine="yandex",
        language=None,
        country=None,
        location="Moscow",
        start=10,
    )

    params = route.calls.last.request.url.params
    assert params["engine"] == "yandex"
    assert params["start"] == "10"
    assert params["location"] == "Moscow"
    assert "hl" not in params
    assert "gl" not in params


@respx.mock
def test_a_rate_limit_is_retried():
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate limit"}),
            _ok(),
        ]
    )

    rows = serpapi.search("стример CS2")

    assert len(rows) == 1
    assert route.call_count == 2


@respx.mock
def test_a_server_error_with_an_html_body_is_still_retried():
    route = respx.get(URL).mock(
        return_value=httpx.Response(503, text="<html>down</html>")
    )

    with pytest.raises(serpapi.SerpApiTemporaryError, match="unreadable response"):
        serpapi.search("стример CS2")

    assert route.call_count == 4


@respx.mock
def test_a_bad_request_is_not_retried_and_the_key_is_masked():
    route = respx.get(URL).mock(
        return_value=httpx.Response(
            400, json={"error": f"Invalid API key {FAKE_KEY}"}
        )
    )

    with pytest.raises(serpapi.SerpApiError) as caught:
        serpapi.search("стример CS2")

    assert route.call_count == 1
    assert FAKE_KEY not in str(caught.value)
    assert "***" in str(caught.value)


@respx.mock
def test_a_200_with_an_error_is_refused():
    respx.get(URL).mock(
        return_value=httpx.Response(200, json={"error": "Invalid query"})
    )

    with pytest.raises(serpapi.SerpApiError, match="Invalid query"):
        serpapi.search("стример CS2")


@respx.mock
def test_a_transport_error_never_leaks_the_key():
    route = respx.get(URL).mock(side_effect=httpx.ConnectError("network down"))

    with pytest.raises(serpapi.SerpApiTemporaryError) as caught:
        serpapi.search("стример CS2")

    assert route.call_count == 4
    assert FAKE_KEY not in str(caught.value)


@respx.mock
def test_no_organic_results_returns_an_empty_list():
    respx.get(URL).mock(return_value=_ok(results=[]))

    assert serpapi.search("стример CS2") == []


def test_unconfigured_serpapi_says_what_to_set(monkeypatch):
    monkeypatch.setattr(settings, "SERPAPI_API_KEY", None)

    assert serpapi.is_configured() is False
    with pytest.raises(serpapi.SerpApiNotConfigured, match="SERPAPI_API_KEY"):
        serpapi.search("стример CS2")


def test_input_is_checked_before_the_network():
    with pytest.raises(ValueError, match="must not be empty"):
        serpapi.search("   ")
    with pytest.raises(ValueError, match="engine"):
        serpapi.search("q", engine="  ")
    with pytest.raises(ValueError, match="num_results"):
        serpapi.search("q", num_results=101)
    with pytest.raises(ValueError, match="start"):
        serpapi.search("q", start=-1)
