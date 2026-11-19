"""Tests for the registry search client. No network: responses are mocked.

The client is allowed to be unreadable, but it is not allowed to mistake an
unreadable answer for an absence — that difference is what the tests protect.
"""

import httpx
import pytest
import respx
from tenacity import wait_none

from config import settings
from integrations import rkn_search
from integrations.rkn_search import SearchPage
from processing.rkn import RegistryEntry

HTML = """
<table>
  <tr><th>Name</th><th>Page</th></tr>
  <tr>
    <td><a href="/channels/123">Креатор</a></td>
    <td><a href="https://vk.com/creator">vk.com/creator</a></td>
  </tr>
</table>
"""


@pytest.fixture(autouse=True)
def no_real_wait():
    rkn_search._fetch_with_retry.retry.wait = wait_none()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "RKN_SEARCH_URL", "https://rkn.example/search")
    monkeypatch.setattr(settings, "RKN_QUERY_FIELD", "pageUrl")
    monkeypatch.setattr(settings, "RKN_ALLOWED_DOMAINS", "rkn.example")
    return settings


# --- the parser -------------------------------------------------------------


def test_a_row_keeps_the_page_address_and_not_the_card_link(configured):
    (entry,) = rkn_search.parse_rows(HTML, base_url="https://rkn.example/search")

    assert entry.urls == ("https://vk.com/creator",)
    assert entry.name == "Креатор"
    assert entry.account_id == "123"


def test_a_relative_card_link_is_resolved_against_the_answer(configured):
    (entry,) = rkn_search.parse_rows(HTML, base_url="https://rkn.example/search")

    assert "rkn.example" not in " ".join(entry.urls)
    assert entry.account_id == "123"


def test_a_row_without_a_numeric_card_has_no_identifier(configured):
    html = (
        "<tr><td><a href='/channels/abc'>Креатор</a></td>"
        "<td><a href='https://vk.com/creator'>page</a></td></tr>"
    )

    (entry,) = rkn_search.parse_rows(html, base_url="https://rkn.example/search")

    assert entry.account_id is None


def test_without_an_allow_list_every_link_of_the_row_is_kept(monkeypatch):
    monkeypatch.setattr(settings, "RKN_ALLOWED_DOMAINS", "")

    (entry,) = rkn_search.parse_rows(HTML, base_url="https://rkn.example/search")

    assert len(entry.urls) == 2
    assert entry.account_id is None


def test_a_row_without_a_link_is_ignored(configured):
    html = "<tr><td>aucun lien</td></tr><tr><td><a href='/x/1'>x</a></td></tr>"

    entries = rkn_search.parse_rows(html)

    assert len(entries) == 1


# --- the search -------------------------------------------------------------


@respx.mock
def test_the_answer_is_posted_to_the_configured_form(configured):
    route = respx.post("https://rkn.example/search").mock(
        return_value=httpx.Response(200, text=HTML)
    )

    result = rkn_search.search("vk.com/creator")

    assert route.call_count == 1
    assert route.calls[0].request.content == b"pageUrl=vk.com%2Fcreator"
    assert result.entries[0].urls == ("https://vk.com/creator",)
    assert result.query == "vk.com/creator"
    assert result.unavailable is False
    assert result.lookalike is False


@respx.mock
def test_a_temporary_error_is_retried(configured):
    route = respx.post("https://rkn.example/search").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, text=HTML)]
    )

    result = rkn_search.search("vk.com/creator")

    assert route.call_count == 2
    assert result.entries


@respx.mock
def test_a_refused_form_is_unavailable_not_empty(configured):
    respx.post("https://rkn.example/search").mock(return_value=httpx.Response(404))

    result = rkn_search.search("vk.com/creator")

    assert result.unavailable is True
    assert result.entries == ()


@respx.mock
def test_a_page_without_a_result_table_is_unavailable(configured):
    respx.post("https://rkn.example/search").mock(
        return_value=httpx.Response(200, text="<html><body>maintenance</body></html>")
    )

    result = rkn_search.search("vk.com/creator")

    assert result.unavailable is True


@respx.mock
def test_an_empty_table_is_a_real_empty_result(configured):
    respx.post("https://rkn.example/search").mock(
        return_value=httpx.Response(200, text="<table><tr><th>Name</th></tr></table>")
    )

    result = rkn_search.search("vk.com/creator")

    assert result.unavailable is False
    assert result.entries == ()


@respx.mock
def test_an_answer_from_another_host_is_a_lookalike(configured, monkeypatch):
    monkeypatch.setattr(settings, "RKN_SEARCH_URL", "https://imit.rkn.example/s")
    respx.post("https://imit.rkn.example/s").mock(
        return_value=httpx.Response(200, text=HTML)
    )

    result = rkn_search.search("vk.com/creator")

    assert result.lookalike is True


def test_an_injected_fetch_replaces_the_network(configured):
    seen = {}

    def fetch(query):
        seen["query"] = query
        return SearchPage(html=HTML, url="https://rkn.example/search")

    result = rkn_search.search("vk.com/creator", fetch=fetch)

    assert seen["query"] == "vk.com/creator"
    assert result.entries[0].account_id == "123"


def test_an_unreadable_injected_fetch_is_unavailable(configured):
    result = rkn_search.search("vk.com/creator", fetch=lambda query: None)

    assert result.unavailable is True


def test_an_injected_parser_replaces_the_row_reader(configured):
    def parser(html, *, base_url=""):
        return (RegistryEntry(urls=(f"https://vk.com/{html}",)),)

    result = rkn_search.search(
        "creator",
        fetch=lambda query: SearchPage(html=query, url="https://rkn.example/s"),
        parser=parser,
    )

    assert result.entries[0].urls == ("https://vk.com/creator",)


def test_rows_are_capped(configured):
    def parser(html, *, base_url=""):
        return tuple(
            RegistryEntry(urls=(f"https://vk.com/{index}",))
            for index in range(rkn_search.MAX_ENTRIES + 10)
        )

    result = rkn_search.search(
        "creator",
        fetch=lambda query: SearchPage(html="<tr></tr>", url="https://rkn.example/s"),
        parser=parser,
    )

    assert len(result.entries) == rkn_search.MAX_ENTRIES


def test_a_search_is_refused_without_configuration(monkeypatch):
    monkeypatch.setattr(settings, "RKN_SEARCH_URL", "")
    monkeypatch.setattr(settings, "RKN_QUERY_FIELD", "")

    with pytest.raises(rkn_search.RknNotConfigured):
        rkn_search.search("vk.com/creator")


def test_an_empty_query_is_refused(configured):
    with pytest.raises(ValueError, match="needs a query"):
        rkn_search.search("  ")


# --- the whole path ---------------------------------------------------------


def test_the_check_combines_the_search_and_the_comparison(configured):
    check = rkn_search.check(
        "https://vk.com/creator",
        fetch=lambda query: SearchPage(html=HTML, url="https://rkn.example/search"),
    )

    assert check.check_type == "RKN_REGISTRY"
    assert check.status == "PARTIAL"
    assert "QUERY:https://vk.com/creator" in check.reasons


def test_an_imitated_host_produces_a_review(configured, monkeypatch):
    monkeypatch.setattr(settings, "RKN_SEARCH_URL", "https://imit.rkn.example/s")

    check = rkn_search.check(
        "https://vk.com/creator",
        fetch=lambda query: SearchPage(html=HTML, url="https://imit.rkn.example/s"),
    )

    assert check.status == "MANUAL_REVIEW"
    assert check.reasons == ("LOOKALIKE_DOMAIN",)


def test_an_unreadable_service_suspends_the_check(configured):
    check = rkn_search.check("https://vk.com/creator", fetch=lambda query: None)

    assert check.status == "PENDING"
