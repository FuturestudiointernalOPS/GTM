"""Tests for the betting licence check, and for the registry reader.

Two distinctions carry the module: a verified fact can be unfavourable, and a
country nobody mapped suspends instead of rejecting.
"""
import json

import pytest

from config import settings
from integrations import licence as client
from processing.eligibility import MISMATCH, NOT_FOUND, PENDING, VERIFIED
from processing.licence import LicenceRecord, LicenceRegistry, check

HOLDER = "ООО «Ромашка»"


def registry(*records, **overrides):
    values = {"country": "RU", "records": tuple(records)}
    values.update(overrides)
    return LicenceRegistry(**values)


def record(**overrides):
    values = {
        "number": "26-01-000123",
        "holder": HOLDER,
        "activity": "букмекерская деятельность",
        "status": "ACTIVE",
    }
    values.update(overrides)
    return LicenceRecord(**values)


# --- the check --------------------------------------------------------------


def test_an_active_licence_of_the_right_holder_is_verified():
    result = check(registry(record()), number="26-01-000123", holder=HOLDER)

    assert result.status == VERIFIED
    assert result.active is True


def test_a_revoked_licence_is_verified_and_inactive():
    result = check(
        registry(record(status="REVOKED")), number="26-01-000123", holder=HOLDER
    )

    assert result.status == VERIFIED
    assert result.active is False
    assert result.reasons == ("STATUS:REVOKED",)


def test_a_missing_status_is_not_claimed_active():
    result = check(registry(record(status=None)), number="26-01-000123", holder=HOLDER)

    assert result.status == PENDING
    assert result.active is None
    assert result.reasons == ("STATUS_UNKNOWN",)


def test_a_licence_held_by_another_company_is_a_mismatch():
    result = check(
        registry(record(holder="ООО Другое")), number="26-01-000123", holder=HOLDER
    )

    assert result.status == MISMATCH
    assert result.reasons == ("HOLDER_MISMATCH",)


def test_an_unknown_number_is_absent_even_if_the_holder_matches():
    result = check(registry(record()), number="99-99-999999", holder=HOLDER)

    assert result.status == NOT_FOUND


def test_the_holder_alone_can_find_the_licence():
    result = check(registry(record()), holder=HOLDER)

    assert result.status == VERIFIED


def test_an_incompatible_activity_is_reported_without_denying_the_fact():
    result = check(
        registry(record(activity="тотализатор")),
        number="26-01-000123",
        holder=HOLDER,
        allowed_activities=("букмекерская деятельность",),
    )

    assert result.status == VERIFIED
    assert result.active is True
    assert result.activity_allowed is False
    assert "ACTIVITY_NOT_ALLOWED" in result.reasons


def test_an_allowed_activity_is_confirmed():
    result = check(
        registry(record()),
        number="26-01-000123",
        holder=HOLDER,
        allowed_activities=("БУКМЕКЕРСКАЯ ДЕЯТЕЛЬНОСТЬ",),
    )

    assert result.activity_allowed is True


def test_the_activity_question_is_not_asked_when_no_list_is_given():
    result = check(registry(record()), number="26-01-000123", holder=HOLDER)

    assert result.activity_allowed is None


def test_an_unmapped_country_suspends():
    result = check(
        registry(mapped=False, country="KZ"), number="1", holder=HOLDER
    )

    assert result.status == PENDING
    assert result.country_mapped is False
    assert result.reasons == ("COUNTRY_NOT_MAPPED",)


def test_an_unreadable_registry_suspends():
    result = check(
        registry(unavailable=True), number="26-01-000123", holder=HOLDER
    )

    assert result.status == PENDING
    assert result.reasons == ("REGISTRY_UNAVAILABLE",)


# --- reading the registries -------------------------------------------------


def test_a_json_export_becomes_records():
    text = json.dumps(
        [
            {
                "number": "26-01-000123",
                "holder": HOLDER,
                "activity": "ставки",
                "status": "ACTIVE",
                "domains": ["brand.ru"],
            }
        ]
    )

    reading = client.parse_registry(text, country="RU", source_url="https://r.example")

    assert reading.country == "RU"
    assert reading.source_url == "https://r.example"
    (item,) = reading.records
    assert item.number == "26-01-000123"
    assert item.holder == HOLDER
    assert item.domains == ("brand.ru",)
    assert item.country == "RU"


def test_an_export_wrapped_in_an_object_is_accepted():
    text = json.dumps({"records": [{"number": "1", "holder": HOLDER}]})

    (item,) = client.parse_registry(text, country="RU").records

    assert item.number == "1"
    assert item.status is None


def test_a_row_without_number_or_holder_is_skipped():
    text = json.dumps(
        [
            {"number": "", "holder": HOLDER},
            {"number": "2"},
            {"number": "3", "holder": HOLDER},
        ]
    )

    (item,) = client.parse_registry(text, country="RU").records

    assert item.number == "3"


def test_a_single_domain_string_is_read_as_one_domain():
    text = json.dumps([{"number": "1", "holder": HOLDER, "domains": "brand.ru"}])

    (item,) = client.parse_registry(text, country="RU").records

    assert item.domains == ("brand.ru",)


def test_a_broken_export_is_refused():
    with pytest.raises(client.LicenceError):
        client.parse_registry("[{", country="RU")


def test_an_export_that_is_not_a_list_is_refused():
    with pytest.raises(client.LicenceError, match="not a list"):
        client.parse_registry('{"records": "nope"}', country="RU")


def test_a_country_without_an_address_is_not_mapped(monkeypatch):
    monkeypatch.setattr(settings, "BETTING_LICENCE_URLS", "RU=https://r.example")

    reading = client.load("KZ", fetch=lambda url: "[]")

    assert reading.mapped is False
    assert reading.records == ()


def test_a_configured_country_is_read(monkeypatch):
    monkeypatch.setattr(settings, "BETTING_LICENCE_URLS", "RU=https://r.example")

    reading = client.load(
        "ru",
        fetch=lambda url: json.dumps([{"number": "1", "holder": HOLDER}]),
    )

    assert reading.mapped is True
    assert reading.country == "RU"
    assert reading.source_url == "https://r.example"
    assert reading.records[0].number == "1"


def test_an_unreachable_registry_is_unavailable_not_empty(monkeypatch):
    monkeypatch.setattr(settings, "BETTING_LICENCE_URLS", "RU=https://r.example")

    reading = client.load("RU", fetch=lambda url: None)

    assert reading.unavailable is True
    assert reading.mapped is True


def test_the_client_checks_one_company_end_to_end(monkeypatch):
    monkeypatch.setattr(settings, "BETTING_LICENCE_URLS", "RU=https://r.example")

    result = client.check(
        country="RU",
        holder=HOLDER,
        number="26-01-000123",
        fetch=lambda url: json.dumps(
            [{"number": "26-01-000123", "holder": HOLDER, "status": "ACTIVE"}]
        ),
    )

    assert result.status == VERIFIED
    assert result.active is True
    assert result.source_url == "https://r.example"


def test_a_verified_licence_feeds_the_buyer_decision():
    from processing.eligibility import BuyerVerification, decide_buyer

    result = check(registry(record()), number="26-01-000123", holder=HOLDER)
    decision = decide_buyer(
        BuyerVerification(
            betting_brand=True,
            license_status=result.status,
            license_active=result.active,
            license_activity_allowed=result.activity_allowed,
            country_mapped=result.country_mapped,
            sanction_status=NOT_FOUND,
        )
    )

    assert decision.status == "ELIGIBLE"
    assert decision.workflow_status == "QUALIFIED"
