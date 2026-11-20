"""Tests for the Baserow schema seeder. No network, no real Baserow."""

import json

import httpx
import pytest
import respx
from tenacity import wait_none

from config import settings
from db.baserow.apply_schema import (
    TableState,
    _build_field_payload,
    _validate_schema,
    apply_schema,
    load_schema,
    main,
)
from integrations import baserow
from integrations.baserow import BaserowClient, BaserowError, BaserowNotConfigured

BASE = "https://baserow.test/api"
DATABASE_ID = 42
TOKEN = "fake-personal-token"

SCHEMA = {
    "tables": [
        {
            "name": "Parents",
            "primary_field": "name",
            "fields": [
                {"name": "name", "type": "text", "primary": True},
                {
                    "name": "status",
                    "type": "single_select",
                    "options": ["A", "B"],
                },
            ],
        },
        {
            "name": "Children",
            "primary_field": "title",
            "fields": [
                {"name": "title", "type": "text", "primary": True},
                {
                    "name": "parent",
                    "type": "link_row",
                    "link_row_table": "Parents",
                    "multiple": False,
                },
                {
                    "name": "status_lookup",
                    "type": "lookup",
                    "through_field": "parent",
                    "target_field": "status",
                },
                {
                    "name": "parent_count",
                    "type": "count",
                    "through_field": "parent",
                },
            ],
        },
    ]
}


@pytest.fixture(autouse=True)
def no_real_wait():
    baserow.BaserowClient._request_with_retry.retry.wait = wait_none()


def make_client() -> BaserowClient:
    return BaserowClient(base_url="https://baserow.test", token=TOKEN)


def _json(request) -> dict:
    return json.loads(request.content)


def test_the_real_schema_is_valid_for_the_seeder():
    assert _validate_schema(load_schema()) == []


def test_date_time_and_decimal_number_payloads():
    state = TableState("T", {"name": "T", "fields": []}, 1)

    date_payload = _build_field_payload(
        state, {"name": "seen_at", "type": "date_time"}, {}
    )
    assert date_payload == {
        "name": "seen_at",
        "type": "date",
        "date_format": "ISO",
        "date_include_time": True,
    }

    number_payload = _build_field_payload(
        state,
        {"name": "score", "type": "number", "number_decimal_places": 2},
        {},
    )
    assert number_payload["number_decimal_places"] == 2
    assert number_payload["number_negative"] is False


@respx.mock
def test_dry_run_reports_without_writing():
    respx.get(f"{BASE}/database/tables/database/{DATABASE_ID}/").mock(
        return_value=httpx.Response(200, json=[])
    )
    table_post = respx.post(f"{BASE}/database/tables/database/{DATABASE_ID}/").mock(
        return_value=httpx.Response(201, json={"id": 100, "name": "Parents"})
    )

    result = apply_schema(SCHEMA, DATABASE_ID, client=make_client(), dry_run=True)

    assert result.ok
    assert result.created_tables == ["Parents", "Children"]
    assert "Parents.name (primary)" in result.created_fields
    assert "Children.status_lookup" in result.created_fields
    assert table_post.call_count == 0


@respx.mock
def test_creates_tables_and_fields_in_dependency_order():
    respx.get(f"{BASE}/database/tables/database/{DATABASE_ID}/").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.post(f"{BASE}/database/tables/database/{DATABASE_ID}/").mock(
        side_effect=[
            httpx.Response(201, json={"id": 100, "name": "Parents"}),
            httpx.Response(201, json={"id": 200, "name": "Children"}),
        ]
    )
    respx.get(f"{BASE}/database/fields/table/100/").mock(
        return_value=httpx.Response(
            200, json=[{"id": 1, "name": "Name", "type": "text", "primary": True}]
        )
    )
    respx.get(f"{BASE}/database/fields/table/200/").mock(
        return_value=httpx.Response(
            200, json=[{"id": 2, "name": "Name", "type": "text", "primary": True}]
        )
    )
    respx.patch(f"{BASE}/database/fields/1/").mock(
        return_value=httpx.Response(
            200, json={"id": 1, "name": "name", "type": "text", "primary": True}
        )
    )
    respx.patch(f"{BASE}/database/fields/2/").mock(
        return_value=httpx.Response(
            200, json={"id": 2, "name": "title", "type": "text", "primary": True}
        )
    )
    parent_status = respx.post(f"{BASE}/database/fields/table/100/").mock(
        return_value=httpx.Response(
            201, json={"id": 3, "name": "status", "type": "single_select"}
        )
    )
    child_fields = respx.post(f"{BASE}/database/fields/table/200/").mock(
        side_effect=[
            httpx.Response(
                201,
                json={
                    "id": 4,
                    "name": "parent",
                    "type": "link_row",
                    "link_row_table_id": 100,
                    "has_many_relationships": False,
                },
            ),
            httpx.Response(
                201, json={"id": 5, "name": "status_lookup", "type": "lookup"}
            ),
            httpx.Response(
                201, json={"id": 6, "name": "parent_count", "type": "count"}
            ),
        ]
    )

    result = apply_schema(SCHEMA, DATABASE_ID, client=make_client())

    assert result.ok
    assert result.created_tables == ["Parents", "Children"]
    assert "Parents.status" in result.created_fields
    assert "Children.parent" in result.created_fields
    assert "Children.status_lookup" in result.created_fields
    assert "Children.parent_count" in result.created_fields

    status_payload = _json(parent_status.calls.last.request)
    assert status_payload["type"] == "single_select"
    assert [item["value"] for item in status_payload["select_options"]] == ["A", "B"]

    payloads = {
        _json(call.request)["name"]: _json(call.request) for call in child_fields.calls
    }
    assert payloads["parent"]["link_row_table_id"] == 100
    assert payloads["parent"]["has_many_relationships"] is False
    assert payloads["status_lookup"]["through_field_id"] == 4
    assert payloads["status_lookup"]["target_field_id"] == 3
    assert payloads["parent_count"]["through_field_id"] == 4


@respx.mock
def test_a_second_run_creates_nothing():
    respx.get(f"{BASE}/database/tables/database/{DATABASE_ID}/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 100, "name": "Parents"},
                {"id": 200, "name": "Children"},
            ],
        )
    )
    respx.get(f"{BASE}/database/fields/table/100/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "name", "type": "text", "primary": True},
                {
                    "id": 3,
                    "name": "status",
                    "type": "single_select",
                    "select_options": [
                        {"id": 10, "value": "A", "color": "blue"},
                        {"id": 11, "value": "B", "color": "green"},
                    ],
                },
            ],
        )
    )
    respx.get(f"{BASE}/database/fields/table/200/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 2, "name": "title", "type": "text", "primary": True},
                {
                    "id": 4,
                    "name": "parent",
                    "type": "link_row",
                    "link_row_table_id": 100,
                    "has_many_relationships": False,
                },
                {"id": 5, "name": "status_lookup", "type": "lookup"},
                {"id": 6, "name": "parent_count", "type": "count"},
            ],
        )
    )

    result = apply_schema(SCHEMA, DATABASE_ID, client=make_client())

    assert result.ok
    assert result.created_tables == []
    assert result.created_fields == []
    assert result.updated_fields == []
    assert result.errors == []


@respx.mock
def test_missing_select_options_are_added():
    respx.get(f"{BASE}/database/tables/database/{DATABASE_ID}/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 100, "name": "Parents"},
                {"id": 200, "name": "Children"},
            ],
        )
    )
    respx.get(f"{BASE}/database/fields/table/100/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "name", "type": "text", "primary": True},
                {
                    "id": 3,
                    "name": "status",
                    "type": "single_select",
                    "select_options": [{"id": 10, "value": "A", "color": "blue"}],
                },
            ],
        )
    )
    respx.get(f"{BASE}/database/fields/table/200/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 2, "name": "title", "type": "text", "primary": True},
                {
                    "id": 4,
                    "name": "parent",
                    "type": "link_row",
                    "link_row_table_id": 100,
                    "has_many_relationships": False,
                },
                {"id": 5, "name": "status_lookup", "type": "lookup"},
                {"id": 6, "name": "parent_count", "type": "count"},
            ],
        )
    )
    update = respx.patch(f"{BASE}/database/fields/3/").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 3,
                "name": "status",
                "type": "single_select",
                "select_options": [
                    {"id": 10, "value": "A", "color": "blue"},
                    {"id": 11, "value": "B", "color": "green"},
                ],
            },
        )
    )

    result = apply_schema(SCHEMA, DATABASE_ID, client=make_client())

    assert result.ok
    assert result.updated_fields == ["Parents.status (options: B)"]
    payload = _json(update.calls.last.request)
    options = payload["select_options"]
    assert {"id": 10, "value": "A", "color": "blue"} in options
    assert any(item["value"] == "B" and "id" not in item for item in options)


@respx.mock
def test_a_type_mismatch_is_reported_without_changing_the_field():
    respx.get(f"{BASE}/database/tables/database/{DATABASE_ID}/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 100, "name": "Parents"},
                {"id": 200, "name": "Children"},
            ],
        )
    )
    respx.get(f"{BASE}/database/fields/table/100/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "name", "type": "text", "primary": True},
                {"id": 3, "name": "status", "type": "text"},
            ],
        )
    )
    respx.get(f"{BASE}/database/fields/table/200/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 2, "name": "title", "type": "text", "primary": True},
                {
                    "id": 4,
                    "name": "parent",
                    "type": "link_row",
                    "link_row_table_id": 100,
                    "has_many_relationships": False,
                },
                {"id": 5, "name": "status_lookup", "type": "lookup"},
                {"id": 6, "name": "parent_count", "type": "count"},
            ],
        )
    )

    result = apply_schema(SCHEMA, DATABASE_ID, client=make_client())

    assert not result.ok
    assert any("Parents.status" in error for error in result.errors)


def test_unconfigured_baserow_says_what_to_set(monkeypatch):
    monkeypatch.setattr(settings, "BASEROW_URL", None)
    monkeypatch.setattr(settings, "BASEROW_TOKEN", None)

    assert baserow.is_configured() is False
    with pytest.raises(BaserowNotConfigured, match="BASEROW_URL"):
        BaserowClient()


@respx.mock
def test_the_cli_wires_settings_and_dry_run(monkeypatch):
    monkeypatch.setattr(settings, "BASEROW_URL", "https://baserow.test")
    monkeypatch.setattr(settings, "BASEROW_TOKEN", TOKEN)
    respx.get(f"{BASE}/database/tables/database/{DATABASE_ID}/").mock(
        return_value=httpx.Response(200, json=[])
    )

    assert main(["--database-id", str(DATABASE_ID), "--dry-run"]) == 0


@respx.mock
def test_default_auth_header_is_jwt(monkeypatch):
    monkeypatch.setattr(settings, "BASEROW_AUTH_SCHEME", None)
    route = respx.get(f"{BASE}/database/tables/database/{DATABASE_ID}/").mock(
        return_value=httpx.Response(200, json=[])
    )

    make_client().list_tables(DATABASE_ID)

    assert route.calls.last.request.headers["Authorization"] == f"JWT {TOKEN}"


@respx.mock
def test_the_token_never_appears_in_an_error():
    respx.get(f"{BASE}/database/tables/database/{DATABASE_ID}/").mock(
        return_value=httpx.Response(403, json={"detail": "Forbidden"})
    )
    client = make_client()

    with pytest.raises(BaserowError) as caught:
        client.list_tables(DATABASE_ID)

    assert TOKEN not in str(caught.value)


VIEW_SCHEMA = {
    "tables": [
        {
            "name": "Parents",
            "primary_field": "name",
            "fields": [
                {"name": "name", "type": "text", "primary": True},
                {
                    "name": "status",
                    "type": "single_select",
                    "options": ["A", "B"],
                },
            ],
        }
    ],
    "views": [
        {
            "name": "Parents à revoir",
            "table": "Parents",
            "type": "grid",
            "filter_type": "AND",
            "filters": [
                {
                    "field": "status",
                    "type": "single_select_is_any_of",
                    "value": "A,B",
                }
            ],
        }
    ],
}


def _mock_existing_parents():
    respx.get(f"{BASE}/database/tables/database/{DATABASE_ID}/").mock(
        return_value=httpx.Response(200, json=[{"id": 100, "name": "Parents"}])
    )
    respx.get(f"{BASE}/database/fields/table/100/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "name", "type": "text", "primary": True},
                {
                    "id": 3,
                    "name": "status",
                    "type": "single_select",
                    "select_options": [
                        {"id": 10, "value": "A", "color": "blue"},
                        {"id": 11, "value": "B", "color": "green"},
                    ],
                },
            ],
        )
    )


@respx.mock
def test_missing_views_and_filters_are_created():
    _mock_existing_parents()
    respx.get(f"{BASE}/database/views/table/100/").mock(
        return_value=httpx.Response(200, json=[])
    )
    view_post = respx.post(f"{BASE}/database/views/table/100/").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 70,
                "name": "Parents à revoir",
                "type": "grid",
                "filter_type": "AND",
            },
        )
    )
    filter_post = respx.post(f"{BASE}/database/views/70/filters/").mock(
        return_value=httpx.Response(
            200, json={"id": 1, "field": 3, "type": "single_select_is_any_of"}
        )
    )

    result = apply_schema(VIEW_SCHEMA, DATABASE_ID, client=make_client())

    assert result.ok
    assert result.created_views == ["Parents/Parents à revoir"]
    assert result.created_view_filters == [
        "Parents/Parents à revoir.status single_select_is_any_of A,B"
    ]
    assert _json(view_post.calls.last.request) == {
        "name": "Parents à revoir",
        "type": "grid",
        "filter_type": "AND",
    }
    assert _json(filter_post.calls.last.request) == {
        "field": 3,
        "type": "single_select_is_any_of",
        "value": "A,B",
    }


@respx.mock
def test_an_existing_view_is_not_recreated():
    _mock_existing_parents()
    respx.get(f"{BASE}/database/views/table/100/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 70,
                    "name": "Parents à revoir",
                    "type": "grid",
                    "filter_type": "AND",
                    "filters": [
                        {
                            "id": 1,
                            "field": 3,
                            "type": "single_select_is_any_of",
                            "value": "A,B",
                        }
                    ],
                }
            ],
        )
    )
    view_post = respx.post(f"{BASE}/database/views/table/100/")
    filter_post = respx.post(f"{BASE}/database/views/70/filters/")

    result = apply_schema(VIEW_SCHEMA, DATABASE_ID, client=make_client())

    assert result.ok
    assert result.created_views == []
    assert result.created_view_filters == []
    assert view_post.call_count == 0
    assert filter_post.call_count == 0


@respx.mock
def test_a_missing_filter_is_added_to_an_existing_view():
    _mock_existing_parents()
    respx.get(f"{BASE}/database/views/table/100/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 70,
                    "name": "Parents à revoir",
                    "type": "grid",
                    "filter_type": "AND",
                    "filters": [],
                }
            ],
        )
    )
    filter_post = respx.post(f"{BASE}/database/views/70/filters/").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )

    result = apply_schema(VIEW_SCHEMA, DATABASE_ID, client=make_client())

    assert result.ok
    assert result.created_views == []
    assert len(result.created_view_filters) == 1
    assert _json(filter_post.calls.last.request)["field"] == 3


@respx.mock
def test_dry_run_reports_views_without_writing():
    _mock_existing_parents()
    respx.get(f"{BASE}/database/views/table/100/").mock(
        return_value=httpx.Response(200, json=[])
    )
    view_post = respx.post(f"{BASE}/database/views/table/100/")
    filter_post = respx.post(f"{BASE}/database/views/70/filters/")

    result = apply_schema(VIEW_SCHEMA, DATABASE_ID, client=make_client(), dry_run=True)

    assert result.ok
    assert result.created_views == ["Parents/Parents à revoir"]
    assert len(result.created_view_filters) == 1
    assert view_post.call_count == 0
    assert filter_post.call_count == 0


def test_an_unknown_view_table_is_rejected():
    schema = {
        "tables": VIEW_SCHEMA["tables"],
        "views": [dict(VIEW_SCHEMA["views"][0], table="Unknown")],
    }

    errors = _validate_schema(schema)

    assert any("unknown table" in error for error in errors)


def test_a_filter_label_must_be_a_declared_option():
    schema = {
        "tables": VIEW_SCHEMA["tables"],
        "views": [
            {
                "name": "Bad",
                "table": "Parents",
                "filters": [
                    {
                        "field": "status",
                        "type": "single_select_equal",
                        "value": "C",
                    }
                ],
            }
        ],
    }

    errors = _validate_schema(schema)

    assert any("'C' is not an option" in error for error in errors)


def test_a_filter_operator_must_match_the_field_type():
    schema = {
        "tables": VIEW_SCHEMA["tables"],
        "views": [
            {
                "name": "Bad",
                "table": "Parents",
                "filters": [{"field": "name", "type": "boolean", "value": "true"}],
            }
        ],
    }

    errors = _validate_schema(schema)

    assert any("cannot filter" in error for error in errors)
