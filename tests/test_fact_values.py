"""Tests for turning a proof's text value into a typed fact value."""

from decimal import Decimal

import pytest

from processing import fact_values
from processing.fact_values import FactRejected, parse_value, validate_proof


def test_a_count_accepts_spaces_and_commas():
    column, value = parse_value("followers", "25 000")

    assert column == "value_number"
    assert value == Decimal("25000")


def test_a_percentage_accepts_a_comma():
    column, value = parse_value("gaming_share", "87,5")

    assert column == "value_number"
    assert value == Decimal("87.5")


def test_a_boolean_accepts_french_and_russian_forms():
    assert parse_value("ad_contact_or_rate_card", "oui") == (
        "value_boolean",
        True,
    )
    assert parse_value("past_labeled_ads", "нет") == ("value_boolean", False)


def test_an_unknown_key_stays_text():
    assert parse_value("legal_form", "ООО") == ("value_text", "ООО")


def test_a_malformed_number_is_refused():
    with pytest.raises(FactRejected):
        parse_value("followers", "many")
    with pytest.raises(FactRejected):
        parse_value("followers", "12.5")
    with pytest.raises(FactRejected):
        parse_value("followers", "-1")


def test_a_percentage_outside_its_domain_is_refused():
    with pytest.raises(FactRejected):
        parse_value("gaming_share", "101")


def test_an_empty_value_is_refused():
    with pytest.raises(FactRejected):
        parse_value("followers", "   ")


def test_the_proof_vocabularies_are_checked():
    validate_proof("OBSERVED", "VERIFIED", "ACCEPTED")
    with pytest.raises(FactRejected):
        validate_proof("CERTAIN", "VERIFIED", "ACCEPTED")
    with pytest.raises(FactRejected):
        validate_proof("OBSERVED", "SURE", "ACCEPTED")
    with pytest.raises(FactRejected):
        validate_proof("OBSERVED", "VERIFIED", "MAYBE")


def test_the_known_vocabularies_are_exported():
    assert "followers" in fact_values.COUNT_KEYS
    assert "gaming_share" in fact_values.PERCENT_KEYS
    assert "sells_to_gamers" in fact_values.BOOLEAN_KEYS
