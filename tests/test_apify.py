"""Tests for the Apify Actor wrapper. No network, no real API token."""
from datetime import timedelta
from types import SimpleNamespace
from typing import ClassVar

import pytest

from config import settings
from integrations import apify

FAKE_TOKEN = "fake-apify-token"


class FakeApifyClient:
    """Stands in for the SDK client and records the run options."""

    actor_id: ClassVar[str | None] = None
    dataset_id: ClassVar[str | None] = None
    call_options: ClassVar[dict | None] = None
    run: ClassVar = None
    items: ClassVar[list[dict]] = []
    error: ClassVar[Exception | None] = None

    def __init__(self, token):
        assert token == FAKE_TOKEN

    def actor(self, actor_id):
        FakeApifyClient.actor_id = actor_id
        return SimpleNamespace(call=self._call)

    def _call(self, **options):
        FakeApifyClient.call_options = options
        if self.error is not None:
            raise self.error
        return self.run

    def dataset(self, dataset_id):
        FakeApifyClient.dataset_id = dataset_id
        return SimpleNamespace(iterate_items=lambda: iter(FakeApifyClient.items))


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    monkeypatch.setattr(settings, "APIFY_API_KEY", FAKE_TOKEN)
    monkeypatch.setattr(apify, "ApifyClient", FakeApifyClient)
    FakeApifyClient.run = SimpleNamespace(
        id="run-1",
        status="SUCCEEDED",
        status_message=None,
        default_dataset_id="dataset-1",
    )
    FakeApifyClient.items = [{"handle": "@red", "followers": 42_000}]
    FakeApifyClient.error = None
    FakeApifyClient.actor_id = None
    FakeApifyClient.dataset_id = None
    FakeApifyClient.call_options = None


def test_a_successful_run_returns_the_dataset_rows():
    rows = apify.run_actor(
        "apify/google-search-scraper",
        {"queries": "gaming studio", "maxPagesPerQuery": 1},
        max_items=20,
        wait_seconds=60,
    )

    assert rows == [{"handle": "@red", "followers": 42_000}]
    assert FakeApifyClient.actor_id == "apify/google-search-scraper"
    assert FakeApifyClient.dataset_id == "dataset-1"
    assert FakeApifyClient.call_options == {
        "run_input": {"queries": "gaming studio", "maxPagesPerQuery": 1},
        "max_items": 20,
        "wait_duration": timedelta(seconds=60),
    }


def test_max_items_is_omitted_when_not_given():
    apify.run_actor("apify/google-search-scraper", {"queries": "gaming"})

    assert "max_items" not in FakeApifyClient.call_options


def test_a_failed_run_is_reported_with_its_status():
    FakeApifyClient.run = SimpleNamespace(
        id="run-2",
        status="FAILED",
        status_message="Actor crashed",
        default_dataset_id="dataset-2",
    )

    with pytest.raises(apify.ApifyError, match="run-2.*FAILED.*Actor crashed"):
        apify.run_actor("apify/google-search-scraper", {"queries": "gaming"})


def test_a_run_still_running_is_not_started_twice():
    FakeApifyClient.run = SimpleNamespace(
        id="run-3",
        status="RUNNING",
        status_message=None,
        default_dataset_id=None,
    )

    with pytest.raises(apify.ApifyError, match="still RUNNING"):
        apify.run_actor("apify/google-search-scraper", {"queries": "gaming"})

    assert FakeApifyClient.dataset_id is None


def test_a_run_without_a_dataset_is_refused():
    FakeApifyClient.run = SimpleNamespace(
        id="run-4",
        status="SUCCEEDED",
        status_message=None,
        default_dataset_id=None,
    )

    with pytest.raises(apify.ApifyError, match="no dataset"):
        apify.run_actor("apify/google-search-scraper", {"queries": "gaming"})


def test_unconfigured_apify_says_what_to_set(monkeypatch):
    monkeypatch.setattr(settings, "APIFY_API_KEY", None)

    assert apify.is_configured() is False
    with pytest.raises(apify.ApifyNotConfigured, match="APIFY_API_KEY"):
        apify.run_actor("apify/google-search-scraper", {"queries": "gaming"})


def test_input_is_checked_before_the_network():
    with pytest.raises(ValueError, match="actor_id"):
        apify.run_actor("  ", {})
    with pytest.raises(TypeError, match="run_input"):
        apify.run_actor("apify/google-search-scraper", "not a dict")
    with pytest.raises(ValueError, match="wait_seconds"):
        apify.run_actor("apify/google-search-scraper", {}, wait_seconds=0)


def test_a_refusal_keeps_the_api_message():
    from apify_client.errors import ApifyClientError

    FakeApifyClient.error = ApifyClientError("invalid Actor input")

    with pytest.raises(apify.ApifyError, match="invalid Actor input"):
        apify.run_actor("apify/google-search-scraper", {"queries": "gaming"})


def test_a_transport_error_never_leaks_the_token():
    FakeApifyClient.error = RuntimeError(
        f"connection failed at https://api.apify.com/v2?token={FAKE_TOKEN}"
    )

    with pytest.raises(apify.ApifyError) as caught:
        apify.run_actor("apify/google-search-scraper", {"queries": "gaming"})

    assert FAKE_TOKEN not in str(caught.value)
