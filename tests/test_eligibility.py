"""Tests for the eligibility decision table.

The table is pure: same checks, same verdict. The tests walk it row by row, and
check that doubt always suspends rather than passes.
"""
import pytest

from processing import eligibility
from processing.eligibility import (
    BETTING_LICENSE,
    COMPLIANCE_REVIEW,
    ELIGIBLE,
    FOREIGN_AGENT,
    INELIGIBLE,
    MANUAL_REVIEW_STATUS,
    NOT_APPLICABLE,
    NOT_FOUND,
    PENDING,
    PLATFORM_COVERAGE,
    PRESELECTED,
    QUALIFIED,
    REGULATORY_PENDING,
    REJECTED,
    RKN_REGISTRY,
    TO_REVIEW,
    VERIFIED,
    BuyerVerification,
    CreatorVerification,
    decide_buyer,
    decide_creator,
    workflow_status_for,
)


def creator(**overrides):
    values = {
        "platform_covered": True,
        "followers": 25_000,
        "foreign_agent_label": False,
        "rkn_status": VERIFIED,
        "sanction_status": NOT_FOUND,
    }
    values.update(overrides)
    return CreatorVerification(**values)


def buyer(**overrides):
    values = {
        "betting_brand": True,
        "license_status": VERIFIED,
        "license_active": True,
        "country_mapped": True,
        "sanction_status": NOT_FOUND,
    }
    values.update(overrides)
    return BuyerVerification(**values)


def check(decision, check_type):
    return next(item for item in decision.checks if item.check_type == check_type)


# --- creators ---------------------------------------------------------------


def test_a_labelled_foreign_agent_is_rejected_before_anything_else():
    decision = decide_creator(creator(foreign_agent_label=True))

    assert decision.status is None
    assert decision.workflow_status == REJECTED
    assert check(decision, FOREIGN_AGENT).status == VERIFIED
    # The rejection needs no registry lookup: nothing else was checked.
    assert [item.check_type for item in decision.checks] == [FOREIGN_AGENT]


def test_an_absent_label_does_not_block():
    decision = decide_creator(creator(foreign_agent_label=False))

    assert check(decision, FOREIGN_AGENT).status == NOT_FOUND
    assert decision.workflow_status == PRESELECTED


def test_an_unobserved_label_suspends_the_qualification():
    decision = decide_creator(creator(foreign_agent_label=None))

    assert check(decision, FOREIGN_AGENT).status == PENDING
    assert decision.status == REGULATORY_PENDING
    assert decision.workflow_status == MANUAL_REVIEW_STATUS


def test_a_sanctions_match_goes_to_compliance_not_to_a_verdict():
    decision = decide_creator(creator(sanction_status=VERIFIED))

    assert decision.status is None
    assert decision.workflow_status == COMPLIANCE_REVIEW


def test_unavailable_sanctions_lists_suspend_without_accusing():
    decision = decide_creator(creator(sanction_status=PENDING))

    assert decision.status == REGULATORY_PENDING
    assert decision.workflow_status == MANUAL_REVIEW_STATUS


def test_unchecked_sanctions_are_not_a_pass():
    decision = decide_creator(creator(sanction_status=None))

    assert check(decision, "SANCTIONS").status == PENDING
    assert decision.status == REGULATORY_PENDING


def test_an_uncovered_platform_is_not_concerned_by_the_registry():
    decision = decide_creator(creator(platform_covered=False))

    assert decision.status == ELIGIBLE
    assert decision.workflow_status == PRESELECTED
    assert check(decision, RKN_REGISTRY).status == NOT_APPLICABLE


def test_exactly_ten_thousand_followers_is_below_the_threshold():
    decision = decide_creator(creator(followers=10_000))

    assert check(decision, PLATFORM_COVERAGE).status == NOT_APPLICABLE
    assert decision.status == ELIGIBLE


def test_above_the_threshold_the_registry_is_looked_up():
    decision = decide_creator(creator(followers=10_001))

    assert check(decision, PLATFORM_COVERAGE).status == VERIFIED
    assert check(decision, RKN_REGISTRY).status == VERIFIED
    assert decision.status == ELIGIBLE


def test_unknown_coverage_suspends_rather_than_rejects():
    decision = decide_creator(creator(platform_covered=None))

    assert check(decision, PLATFORM_COVERAGE).status == PENDING
    assert decision.status == REGULATORY_PENDING
    assert decision.workflow_status == MANUAL_REVIEW_STATUS


def test_unknown_followers_suspend_because_the_threshold_is_unproven():
    decision = decide_creator(creator(followers=None))

    assert check(decision, PLATFORM_COVERAGE).status == PENDING
    assert decision.status == REGULATORY_PENDING


def test_a_partial_registry_match_is_enough_for_eligibility():
    decision = decide_creator(creator(rkn_status="PARTIAL"))

    assert decision.status == ELIGIBLE


def test_an_absent_registration_makes_the_page_ineligible():
    decision = decide_creator(creator(rkn_status=NOT_FOUND))

    assert decision.status == INELIGIBLE
    assert decision.workflow_status == "INELIGIBLE"


def test_a_registration_of_another_page_makes_the_page_ineligible():
    decision = decide_creator(creator(rkn_status="MISMATCH"))

    assert decision.status == INELIGIBLE


def test_an_unavailable_registry_suspends_the_qualification():
    decision = decide_creator(creator(rkn_status=PENDING))

    assert decision.status == REGULATORY_PENDING
    assert decision.workflow_status == MANUAL_REVIEW_STATUS


def test_an_unchecked_registry_suspends_the_qualification():
    decision = decide_creator(creator(rkn_status=None))

    assert check(decision, RKN_REGISTRY).status == PENDING
    assert decision.status == REGULATORY_PENDING


def test_the_registry_source_is_kept_with_the_check():
    decision = decide_creator(
        creator(rkn_source_url="https://example.test/registry/42")
    )

    assert check(decision, RKN_REGISTRY).source_url == "https://example.test/registry/42"


def test_every_creation_decision_carries_at_least_one_check():
    for verification in (
        creator(),
        creator(rkn_status=NOT_FOUND),
        creator(sanction_status=PENDING),
        creator(foreign_agent_label=True),
    ):
        assert decide_creator(verification).checks


# --- buyers -----------------------------------------------------------------


def test_a_buyer_sanctions_match_goes_to_compliance():
    decision = decide_buyer(buyer(sanction_status="MANUAL_REVIEW"))

    assert decision.status is None
    assert decision.workflow_status == COMPLIANCE_REVIEW


def test_a_non_betting_buyer_needs_no_licence():
    decision = decide_buyer(buyer(betting_brand=False))

    assert decision.status == ELIGIBLE
    assert decision.workflow_status == QUALIFIED
    assert check(decision, BETTING_LICENSE).status == NOT_APPLICABLE


def test_a_verified_active_licence_qualifies_the_brand():
    decision = decide_buyer(buyer())

    assert decision.status == ELIGIBLE
    assert decision.workflow_status == QUALIFIED
    assert check(decision, BETTING_LICENSE).status == VERIFIED


def test_a_revoked_licence_is_ineligible_even_though_the_fact_is_verified():
    decision = decide_buyer(buyer(license_active=False))

    assert check(decision, BETTING_LICENSE).status == VERIFIED
    assert decision.status == INELIGIBLE


def test_a_licence_held_by_another_company_is_ineligible():
    assert decide_buyer(buyer(license_status="MISMATCH")).status == INELIGIBLE


def test_an_incompatible_activity_makes_the_brand_ineligible():
    decision = decide_buyer(buyer(license_activity_allowed=False))

    assert decision.status == INELIGIBLE
    assert "activité" in decision.justification


def test_an_allowed_activity_qualifies():
    assert decide_buyer(buyer(license_activity_allowed=True)).status == ELIGIBLE


def test_an_absent_licence_is_ineligible():
    assert decide_buyer(buyer(license_status=NOT_FOUND)).status == INELIGIBLE


def test_an_unverified_licence_goes_to_review():
    decision = decide_buyer(buyer(license_status=PENDING))

    assert decision.status == REGULATORY_PENDING
    assert decision.workflow_status == TO_REVIEW


def test_an_untested_licence_goes_to_review():
    decision = decide_buyer(buyer(license_status=None))

    assert check(decision, BETTING_LICENSE).status == PENDING
    assert decision.status == REGULATORY_PENDING


def test_an_unmapped_country_suspends_the_qualification():
    decision = decide_buyer(buyer(license_status=PENDING, country_mapped=False))

    assert decision.status == REGULATORY_PENDING
    assert decision.workflow_status == TO_REVIEW
    assert "pays non cartographié" in decision.justification


def test_unavailable_sanctions_lists_come_before_the_licence():
    decision = decide_buyer(buyer(sanction_status=PENDING, license_status=NOT_FOUND))

    assert decision.status == REGULATORY_PENDING
    assert [item.check_type for item in decision.checks] == ["SANCTIONS"]


def test_the_threshold_is_a_single_documented_constant():
    assert eligibility.RKN_FOLLOWER_THRESHOLD == 10_000


# --- the move a human verdict implies ---------------------------------------


def test_a_positive_verdict_qualifies_a_buyer_and_preselects_a_creator():
    assert workflow_status_for(ELIGIBLE, "CREATOR") == PRESELECTED
    assert workflow_status_for(ELIGIBLE, "BUYER") == QUALIFIED


def test_a_negative_verdict_is_ineligible_for_both_filons():
    assert workflow_status_for(INELIGIBLE, "CREATOR") == "INELIGIBLE"
    assert workflow_status_for(INELIGIBLE, "BUYER") == "INELIGIBLE"


def test_a_pending_verdict_sends_each_filon_to_its_review_queue():
    assert workflow_status_for(REGULATORY_PENDING, "CREATOR") == MANUAL_REVIEW_STATUS
    assert workflow_status_for(REGULATORY_PENDING, "BUYER") == TO_REVIEW


def test_an_unknown_verdict_is_refused():
    with pytest.raises(ValueError, match="unknown eligibility status"):
        workflow_status_for("MAYBE", "CREATOR")
