"""Contract tests for the PostgreSQL -> Baserow field mapping.

No network and no database: a representative fiche is translated with the real
schema, and the payload is checked field by field. The point is to catch an
ownership mistake before a human field is overwritten in a live Baserow.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from processing import baserow_mapping
from processing.baserow_mapping import (
    BUYER_TABLE,
    CREATOR_TABLE,
    PLATFORM_TABLE,
    build_buyer_row,
    build_creator_row,
    build_platform_row,
    payload_hash,
    table_fields,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 11, 1)
RECORD_ID = "9c8f4b1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b"


def creator_fiche() -> dict:
    return {
        "record_id": RECORD_ID,
        "reference": "CR-000001",
        "workflow_status": "SCORED",
        "eligibility_status": "ELIGIBLE",
        "score": 74,
        "score_total_exact": "74.9",
        "score_incomplete": False,
        "score_proposal": "PRESELECTED",
        "score_bounds_lower": "74.0",
        "score_bounds_upper": "75.0",
        "criteria_version": "1.4",
        "assigned_to": "analyst",
        "tags": ["hot"],
        "notes": "human note",
        "display_name": "Игрок",
        "country": "RU",
        "content_language": "ru",
        "gaming_share": Decimal("87.5"),
        "main_platform": "vk_video",
        "handle": "player",
        "platform_url": "https://vk.com/player",
        "platform_account_id": "123",
        "platform_username": "Player",
        "platform_coverage_status": "COVERED",
        "coverage_checked_at": NOW,
        "followers": 25_000,
        "followers_read_at": NOW,
        "average_views": 24_000,
        "average_concurrent_viewers": None,
        "published_last_30_days": 7,
        "last_published_at": NOW,
        "platform_risk": "LOW",
        "platform_campaign_allowed_until": TODAY,
        "rkn_registry_url": "https://example.test/registry",
        "rkn_search_status": "VERIFIED",
        "rkn_search_query": "player",
        "rkn_registry_status": "VERIFIED",
        "registry_domain_ok": True,
        "registry_url_match": True,
        "a_plus_badge": False,
        "creator_control_verified": True,
        "foreign_agent_label": False,
        "ad_contact_or_rate_card": True,
        "past_labeled_ads": True,
        "verification_date": TODAY,
        "verification_evidence": "registry page",
        "contact_channel": "TELEGRAM",
        "media_kit_url": "https://example.test/media",
        "agency": None,
        "audience_geography": "RU",
        "audit_notes": "human audit",
        "other_profiles": ["https://youtube.com/x", "https://t.me/x"],
        "source_refs": ["https://vk.com/player (2026-11-01)"],
        "profiles_count": 2,
        "ads_count_90d": 1,
        "last_ad_at": NOW,
        "engagement_status": "MEASURED",
        "engagement_measure": "VIEWS_PER_ITEM",
        "engagement_statistic": "MEDIAN",
        "engagement_value": Decimal("24000"),
        "engagement_sample_size": 30,
        "engagement_unreadable_count": 0,
        "engagement_window": "2026-10-11..2026-11-10 (TIME)",
        "engagement_read_at": NOW,
        "engagement_sample_hash": "abc123",
        "engagement_flags": ["DISPERSION"],
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_creator_payload_has_only_database_owned_fields():
    payload = build_creator_row(creator_fiche(), platform_row_ids={"vk_video": 7})

    assert payload["record_id"] == RECORD_ID
    assert payload["display_name"] == "Игрок"
    assert payload["score"] == 74
    assert payload["gaming_share"] == 87.5
    assert payload["main_platform"] == [7]
    assert payload["engagement_flag"] == ["DISPERSION"]
    assert payload["engagement_sample_ref"] == "abc123"
    assert payload["other_profiles"] == "https://youtube.com/x\nhttps://t.me/x"
    assert payload["source_refs"] == "https://vk.com/player (2026-11-01)"
    assert payload["coverage_checked_at"] == NOW.isoformat()
    assert payload["average_concurrent_viewers"] is None

    for human_field in ("assigned_to", "tags", "notes", "audit_notes"):
        assert human_field not in payload

    for derived_field in (
        "platform_risk",
        "platform_campaign_allowed_until",
        "created_at",
        "updated_at",
    ):
        assert derived_field not in payload


def test_creator_link_is_omitted_when_the_platform_is_not_resolved():
    payload = build_creator_row(creator_fiche(), platform_row_ids={})

    assert "main_platform" not in payload


def test_buyer_payload_formats_ad_references_and_skips_human_fields():
    fiche = {
        "record_id": RECORD_ID,
        "reference": "BY-000001",
        "workflow_status": "SCORED",
        "legal_name": "ООО Ромашка",
        "legal_name_normalized": "ооо ромашка",
        "legal_form": "ООО",
        "inn": "1234567890",
        "tax_id_type": "INN",
        "registry_status": "ACTIVE",
        "activity_code": "62.01",
        "country_of_incorporation": "RU",
        "region": "Moscow",
        "website": "https://example.test",
        "official_domain": "example.test",
        "domain_match": True,
        "domain_source_date": TODAY,
        "sells_to_gamers_evidence": "games in the catalogue",
        "labeled_ads_last_90_days": 2,
        "ad_label_refs": [
            {"source": "vk", "date": "2026-10-01", "erid": "abc"},
            {"source": "telegram", "date": "2026-09-01", "erid": None},
        ],
        "sanctions_checked_at": TODAY,
        "employee_band": "50-199",
        "decision_maker_role": "CMO",
        "decision_maker_email_verified": True,
        "timing_signal": "launch",
        "license_status": "NOT_APPLICABLE",
        "assigned_to": "analyst",
        "tags": ["hot"],
        "notes": "human note",
        "source_refs": ["https://example.test (2026-11-01)"],
        "ads_count_total": 4,
        "created_at": NOW,
        "updated_at": NOW,
    }

    payload = build_buyer_row(fiche)

    assert payload["legal_name"] == "ООО Ромашка"
    assert payload["inn"] == "1234567890"
    assert payload["ad_label_refs"] == ("2026-10-01 | vk | abc\n2026-09-01 | telegram")
    assert payload["source_refs"] == "https://example.test (2026-11-01)"
    assert "legal_name_normalized" not in payload
    assert "ads_count_total" not in payload
    for human_field in ("assigned_to", "tags", "notes"):
        assert human_field not in payload


def test_platform_payload_converts_boolean_and_dates():
    platform = {
        "id": RECORD_ID,
        "name": "vk_video",
        "aliases": ["vk", "vk video"],
        "coverage_status": "COVERED",
        "stable_id_available": True,
        "id_notes": None,
        "risk_level": "LOW",
        "creator_campaign_allowed": True,
        "campaign_allowed_until": TODAY,
        "campaign_note": None,
        "source": "registry",
        "source_date": TODAY,
        "checked_at": TODAY,
        "version": "2026-11",
        "created_at": NOW,
        "updated_at": NOW,
    }

    payload = build_platform_row(platform)

    assert payload["platform_id"] == RECORD_ID
    assert payload["aliases"] == "vk\nvk video"
    assert payload["stable_id_available"] == "YES"
    assert payload["creator_campaign_allowed"] is True
    assert payload["campaign_allowed_until"] == "2026-11-01"
    assert "created_at" not in payload


def test_every_mapped_field_is_owned_by_the_database():
    fields = table_fields()
    checks = [
        (CREATOR_TABLE, build_creator_row(creator_fiche())),
        (BUYER_TABLE, build_buyer_row({"legal_name": "x", "assigned_to": "y"})),
        (PLATFORM_TABLE, build_platform_row({"name": "x", "risk_level": "LOW"})),
    ]

    for table, payload in checks:
        for name in payload:
            assert fields[table][name]["owner"] == "pg", (table, name)


def test_payload_hash_is_stable_and_value_sensitive():
    first = {"b": [1, 2], "a": NOW}
    second = {"a": NOW, "b": [1, 2]}

    assert payload_hash(first) == payload_hash(second)
    assert payload_hash(first) != payload_hash({"a": NOW, "b": [1, 3]})


def test_mapping_rejects_an_unknown_table():
    try:
        baserow_mapping._build(
            "Nowhere",
            {},
            aliases={},
            platform_row_ids={},
            schema=None,
        )
    except baserow_mapping.MappingError as error:
        assert "Nowhere" in str(error)
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("an unknown table must be rejected")
