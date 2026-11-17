"""Tests for the eligibility hand-over and the decision dispatch."""

import json
from fractions import Fraction

import pytest

from processing import eligibility
from processing.scoring import ScoreResult
from workflows.eligibility_step import (
    VerificationFile,
    build_verification,
    decide,
)
from workflows.record_flow import BUYER, CREATOR, RecordScore

CREATOR_ENTRY = {
    "platform_covered": True,
    "followers": 25_000,
    "foreign_agent_label": False,
    "rkn_status": "VERIFIED",
    "sanction_status": "NOT_FOUND",
}

BUYER_ENTRY = {
    "betting_brand": True,
    "license_status": "VERIFIED",
    "license_active": True,
    "license_activity_allowed": True,
    "country_mapped": True,
    "sanction_status": "NOT_FOUND",
}


def record(kind=CREATOR, *, source_url="https://vk.com/creator", record_id="rec-1"):
    result = ScoreResult(
        proposal="PRESELECTED",
        score=79,
        total_exact=Fraction(79),
        lower_bound=Fraction(79),
        upper_bound=Fraction(79),
        incomplete=False,
        lines=(),
    )
    return RecordScore(
        kind=kind,
        result=result,
        record_id=record_id,
        source_url=source_url,
    )


# --- building and deciding ---------------------------------------------------


def test_a_creator_entry_becomes_a_creator_verification():
    verification = build_verification(CREATOR, CREATOR_ENTRY)

    assert isinstance(verification, eligibility.CreatorVerification)
    assert verification.followers == 25_000


def test_a_buyer_entry_becomes_a_buyer_verification():
    verification = build_verification(BUYER, BUYER_ENTRY)

    assert isinstance(verification, eligibility.BuyerVerification)
    assert verification.license_active is True


def test_the_declared_kind_must_match_the_record():
    with pytest.raises(ValueError, match="does not match"):
        build_verification(CREATOR, {**CREATOR_ENTRY, "kind": "BUYER"})


def test_an_unknown_field_is_refused():
    with pytest.raises(ValueError, match="invalid CREATOR verification"):
        build_verification(CREATOR, {**CREATOR_ENTRY, "invented": 1})


def test_a_missing_required_field_is_refused():
    with pytest.raises(ValueError, match="invalid CREATOR verification"):
        build_verification(CREATOR, {"platform_covered": True})


def test_the_decision_follows_the_filon():
    creator = build_verification(CREATOR, CREATOR_ENTRY)
    buyer = build_verification(BUYER, BUYER_ENTRY)

    assert decide(CREATOR, creator).workflow_status == "PRESELECTED"
    assert decide(BUYER, buyer).workflow_status == "QUALIFIED"


def test_a_verification_for_the_wrong_filon_is_refused():
    creator = build_verification(CREATOR, CREATOR_ENTRY)

    with pytest.raises(TypeError, match="BuyerVerification"):
        decide(BUYER, creator)


# --- the file ----------------------------------------------------------------


def write_file(tmp_path, data):
    path = tmp_path / "verifications.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_verification_is_found_by_page_url(tmp_path):
    path = write_file(tmp_path, {"https://vk.com/creator": CREATOR_ENTRY})

    verification = VerificationFile.load(path).for_record(record())

    assert verification.followers == 25_000


def test_a_verification_can_be_found_by_record_id(tmp_path):
    path = write_file(tmp_path, {"rec-1": CREATOR_ENTRY})

    verification = VerificationFile.load(path).for_record(
        record(source_url="https://example.test/unknown")
    )

    assert verification is not None


def test_a_record_without_an_entry_gets_no_verification(tmp_path):
    path = write_file(tmp_path, {"https://vk.com/other": CREATOR_ENTRY})

    assert VerificationFile.load(path).for_record(record()) is None


def test_an_invalid_json_file_is_refused(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        VerificationFile.load(path)


def test_a_file_that_is_not_an_object_is_refused(tmp_path):
    path = write_file(tmp_path, [CREATOR_ENTRY])

    with pytest.raises(ValueError, match="object keyed by URL"):
        VerificationFile.load(path)
