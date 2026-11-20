"""Contract tests for the Baserow schema.

The JSON is the source used to create the operational tables. These tests keep
the file honest without needing a Baserow instance: they check the structure,
the link targets, and the mandatory fields from docs/scope.md.
"""

import json
from pathlib import Path

import pytest

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "baserow" / "schema.json"

FIELD_TYPES = {
    "text",
    "long_text",
    "number",
    "boolean",
    "date",
    "date_time",
    "url",
    "single_select",
    "multiple_select",
    "link_row",
    "lookup",
    "count",
    "formula",
    "created_on",
    "last_modified",
}

OWNERS = {"pg", "baserow", "derived"}

CREATOR_CONTRACT_FIELDS = {
    "main_platform",
    "handle",
    "platform_url",
    "platform_account_id",
    "platform_username",
    "platform_coverage_status",
    "coverage_checked_at",
    "display_name",
    "country",
    "content_language",
    "gaming_share",
    "followers",
    "followers_read_at",
    "engagement_status",
    "engagement_measure",
    "engagement_statistic",
    "engagement_value",
    "engagement_sample_size",
    "engagement_window",
    "engagement_read_at",
    "published_last_30_days",
    "last_published_at",
    "rkn_registry_url",
    "rkn_search_status",
    "rkn_search_query",
    "rkn_registry_status",
    "registry_domain_ok",
    "registry_url_match",
    "a_plus_badge",
    "creator_control_verified",
    "foreign_agent_label",
    "ad_contact_or_rate_card",
    "past_labeled_ads",
    "platform_risk",
    "eligibility_status",
    "verification_date",
    "verification_evidence",
    "contact_channel",
    "source_refs",
    "criteria_version",
}

BUYER_CONTRACT_FIELDS = {
    "inn",
    "ogrn",
    "legal_name",
    "legal_form",
    "registry_status",
    "activity_code",
    "country_of_incorporation",
    "region",
    "website",
    "sells_to_gamers_evidence",
    "labeled_ads_last_90_days",
    "ad_label_refs",
    "sanctions_checked_at",
    "employee_band",
    "decision_maker_role",
    "decision_maker_email_verified",
    "timing_signal",
    "license_authority",
    "license_number",
    "license_status",
    "licensed_activity",
    "license_country",
    "campaign_country",
    "official_domain",
    "domain_match",
    "domain_source_date",
    "license_registry_url",
    "license_checked_at",
    "eligibility_status",
    "verification_date",
    "verification_evidence",
    "contact_channel",
    "source_refs",
    "criteria_version",
}


@pytest.fixture(scope="module")
def schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


SCORE_FIELDS = {
    "score",
    "score_total_exact",
    "score_incomplete",
    "score_proposal",
    "score_bounds_lower",
    "score_bounds_upper",
}

ENGAGEMENT_FIELDS = {
    "engagement_status",
    "engagement_measure",
    "engagement_statistic",
    "engagement_value",
    "engagement_sample_size",
    "engagement_unreadable_count",
    "engagement_window",
    "engagement_read_at",
    "engagement_sample_ref",
    "engagement_flag",
}


def _tables(schema: dict) -> dict[str, dict]:
    tables = {}
    for table in schema["tables"]:
        assert table["name"] not in tables, f"duplicate table {table['name']}"
        tables[table["name"]] = table
    return tables


def test_every_table_has_a_valid_shape(schema: dict) -> None:
    for table in schema["tables"]:
        assert table["name"], "a table must have a name"
        assert table["fields"], f"{table['name']} has no fields"

        field_names = [field["name"] for field in table["fields"]]
        assert len(field_names) == len(set(field_names)), (
            f"{table['name']} has duplicate fields"
        )

        for field in table["fields"]:
            assert field["type"] in FIELD_TYPES, (
                f"{table['name']}.{field['name']} uses unknown type {field['type']}"
            )
            assert field["owner"] in OWNERS, (
                f"{table['name']}.{field['name']} has unknown owner {field['owner']}"
            )
            assert isinstance(field.get("required"), bool), (
                f"{table['name']}.{field['name']} must declare required"
            )

            if field["type"] in {"single_select", "multiple_select"}:
                options = field.get("options")
                assert options, f"{table['name']}.{field['name']} must declare options"
                assert len(options) == len(set(options)), (
                    f"{table['name']}.{field['name']} has duplicate options"
                )


def test_primary_field_matches_the_declared_primary(schema: dict) -> None:
    for table in schema["tables"]:
        primaries = [field for field in table["fields"] if field.get("primary")]
        assert len(primaries) == 1, (
            f"{table['name']} must declare exactly one primary field"
        )
        assert primaries[0]["name"] == table["primary_field"], (
            f"{table['name']} primary_field does not match the flagged field"
        )


def test_link_lookup_and_count_targets_resolve(schema: dict) -> None:
    tables = _tables(schema)

    for table in schema["tables"]:
        fields = {field["name"]: field for field in table["fields"]}

        for field in table["fields"]:
            if field["type"] == "link_row":
                target = field.get("link_row_table")
                assert target in tables, (
                    f"{table['name']}.{field['name']} links to unknown table {target}"
                )

            if field["type"] in {"lookup", "count"}:
                through = field.get("through_field")
                assert through in fields, (
                    f"{table['name']}.{field['name']} uses unknown through_field {through}"
                )
                assert fields[through]["type"] == "link_row", (
                    f"{table['name']}.{field['name']} must go through a link_row"
                )

            if field["type"] == "lookup":
                through = fields[field["through_field"]]
                target_table = tables[through["link_row_table"]]
                target_fields = {item["name"] for item in target_table["fields"]}
                assert field.get("target_field") in target_fields, (
                    f"{table['name']}.{field['name']} looks up an unknown field"
                )


def test_scope_contract_fields_are_present(schema: dict) -> None:
    tables = _tables(schema)

    creator_fields = {field["name"] for field in tables["Createurs"]["fields"]}
    buyer_fields = {field["name"] for field in tables["Acheteurs"]["fields"]}

    assert CREATOR_CONTRACT_FIELDS <= creator_fields, (
        f"Createurs misses: {sorted(CREATOR_CONTRACT_FIELDS - creator_fields)}"
    )
    assert BUYER_CONTRACT_FIELDS <= buyer_fields, (
        f"Acheteurs misses: {sorted(BUYER_CONTRACT_FIELDS - buyer_fields)}"
    )
    assert SCORE_FIELDS <= creator_fields, (
        f"Createurs misses score fields: {sorted(SCORE_FIELDS - creator_fields)}"
    )
    assert SCORE_FIELDS <= buyer_fields, (
        f"Acheteurs misses score fields: {sorted(SCORE_FIELDS - buyer_fields)}"
    )


def test_engagement_fields_follow_the_measure_contract(schema: dict) -> None:
    tables = _tables(schema)

    for table_name in ("Createurs", "Profils_plateforme"):
        fields = {field["name"]: field for field in tables[table_name]["fields"]}

        assert ENGAGEMENT_FIELDS <= fields.keys(), (
            f"{table_name} misses: {sorted(ENGAGEMENT_FIELDS - fields.keys())}"
        )
        assert fields["engagement_status"]["options"] == ["MEASURED", "UNKNOWN"]
        assert fields["engagement_measure"]["options"] == [
            "VIEWS_PER_ITEM",
            "CONCURRENT_VIEWERS",
        ]
        assert fields["engagement_statistic"]["options"] == ["MEDIAN"]
        assert fields["engagement_flag"]["options"] == [
            "WEAK_SAMPLE",
            "WINDOW_EXTENDED",
            "DISPERSION",
            "UNREADABLE",
        ]

    creator_fields = {field["name"]: field for field in tables["Createurs"]["fields"]}
    assert creator_fields["engagement_status"]["required"] is True
    assert creator_fields["average_views"]["required"] is False
    assert creator_fields["average_concurrent_viewers"]["required"] is False
