"""Tests for the Baserow row endpoints. No network: respx answers."""

import json

import httpx
import pytest
import respx
from tenacity import wait_none

from integrations import baserow
from integrations.baserow import BaserowError, BaserowRowClient

BASE = "https://baserow.test/api"
TABLE = 12
TOKEN = "row-token"


@pytest.fixture(autouse=True)
def no_real_wait():
    baserow.BaserowClient._request_with_retry.retry.wait = wait_none()


def make_client() -> BaserowRowClient:
    return BaserowRowClient(
        base_url="https://baserow.test",
        token=TOKEN,
        auth_scheme="Token",
    )


@respx.mock
def test_find_row_filters_by_field_name():
    route = respx.get(f"{BASE}/database/rows/table/{TABLE}/").mock(
        return_value=httpx.Response(
            200,
            json={"count": 1, "results": [{"id": 5, "record_id": "abc"}]},
        )
    )

    row = make_client().find_row(TABLE, "record_id", "abc")

    assert row == {"id": 5, "record_id": "abc"}
    request = route.calls[0].request
    assert request.headers["Authorization"] == f"Token {TOKEN}"
    assert request.url.params["user_field_names"] == "true"
    assert request.url.params["size"] == "1"
    assert request.url.params["filter__record_id__equal"] == "abc"


@respx.mock
def test_find_row_returns_none_when_no_row_matches():
    respx.get(f"{BASE}/database/rows/table/{TABLE}/").mock(
        return_value=httpx.Response(200, json={"count": 0, "results": []})
    )

    assert make_client().find_row(TABLE, "record_id", "missing") is None


@respx.mock
def test_create_row_uses_field_names_and_returns_the_row():
    route = respx.post(f"{BASE}/database/rows/table/{TABLE}/").mock(
        return_value=httpx.Response(200, json={"id": 9, "record_id": "abc"})
    )

    row = make_client().create_row(TABLE, {"record_id": "abc", "sync_status": "SYNCED"})

    assert row["id"] == 9
    request = route.calls[0].request
    assert request.url.params["user_field_names"] == "true"
    assert json.loads(request.content) == {
        "record_id": "abc",
        "sync_status": "SYNCED",
    }


@respx.mock
def test_update_row_patches_one_row():
    route = respx.patch(f"{BASE}/database/rows/table/{TABLE}/9/").mock(
        return_value=httpx.Response(200, json={"id": 9})
    )

    make_client().update_row(TABLE, 9, {"sync_status": "ERROR"})

    request = route.calls[0].request
    assert request.url.params["user_field_names"] == "true"
    assert json.loads(request.content) == {"sync_status": "ERROR"}


@respx.mock
def test_a_refused_row_is_a_baserow_error_without_the_token():
    respx.patch(f"{BASE}/database/rows/table/{TABLE}/9/").mock(
        return_value=httpx.Response(400, json={"detail": "unknown field"})
    )

    with pytest.raises(BaserowError) as raised:
        make_client().update_row(TABLE, 9, {"bad": 1})

    assert "unknown field" in str(raised.value)
    assert TOKEN not in str(raised.value)


@respx.mock
def test_iter_rows_follows_next_pages():
    route = respx.get(f"{BASE}/database/rows/table/{TABLE}/").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "next": "page-2",
                    "results": [{"id": 1}, {"id": 2}],
                },
            ),
            httpx.Response(200, json={"next": None, "results": [{"id": 3}]}),
        ]
    )

    rows = list(make_client().iter_rows(TABLE, size=2, max_pages=5))

    assert [row["id"] for row in rows] == [1, 2, 3]
    assert route.call_count == 2
    assert route.calls[0].request.url.params["page"] == "1"
    assert route.calls[1].request.url.params["page"] == "2"


@respx.mock
def test_iter_rows_respects_the_page_cap():
    route = respx.get(f"{BASE}/database/rows/table/{TABLE}/").mock(
        return_value=httpx.Response(
            200,
            json={"next": "still-more", "results": [{"id": 1}]},
        )
    )

    rows = list(make_client().iter_rows(TABLE, max_pages=1))

    assert len(rows) == 1
    assert route.call_count == 1


@respx.mock
def test_a_temporary_failure_is_retried_then_reported():
    route = respx.patch(f"{BASE}/database/rows/table/{TABLE}/9/").mock(
        return_value=httpx.Response(503, json={"detail": "busy"})
    )

    with pytest.raises(BaserowError):
        make_client().update_row(TABLE, 9, {"sync_status": "SYNCED"})

    assert route.call_count == 4
