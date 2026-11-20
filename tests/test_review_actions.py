"""Contract tests for the human action rules. No database, no Baserow."""

import pytest

from processing import review_actions as actions
from processing.review_actions import (
    ADD_TO_POOL,
    APPROVE,
    COMPLIANCE_REVIEW,
    MARK_CONTACTED,
    RECORD_OPT_OUT,
    REJECT,
    REQUEST_REVIEW,
    START_AUDIT,
    ReviewRejected,
    decide,
)


def test_request_review_moves_to_review_with_a_default_trace():
    decision = decide(REQUEST_REVIEW, kind="CREATOR", current="SCORED")

    assert decision.target == "TO_REVIEW"
    assert decision.justification == actions.DEFAULT_JUSTIFICATION[REQUEST_REVIEW]
    assert decision.actor == "baserow-review"


def test_approve_needs_a_note_and_a_named_analyst():
    with pytest.raises(ReviewRejected):
        decide(APPROVE, kind="CREATOR", current="POOL")
    with pytest.raises(ReviewRejected):
        decide(APPROVE, kind="CREATOR", current="POOL", note="vu")

    decision = decide(
        APPROVE,
        kind="CREATOR",
        current="POOL",
        note="preuves vérifiées",
        requested_by="analyste",
    )

    assert decision.target == "APPROVED"
    assert decision.actor == "analyste"
    assert decision.justification == "preuves vérifiées"


def test_approve_is_only_allowed_after_the_audit_step():
    with pytest.raises(ReviewRejected):
        decide(
            APPROVE,
            kind="CREATOR",
            current="PRESELECTED",
            note="vu",
            requested_by="analyste",
        )


def test_a_buyer_is_approved_from_the_qualified_status():
    decision = decide(
        APPROVE,
        kind="BUYER",
        current="QUALIFIED",
        note="dossier complet",
        requested_by="analyste",
    )

    assert decision.target == "APPROVED"


def test_reject_needs_a_justification():
    with pytest.raises(ReviewRejected):
        decide(REJECT, kind="CREATOR", current="TO_REVIEW")

    decision = decide(
        REJECT,
        kind="CREATOR",
        current="TO_REVIEW",
        note="hors profil",
        requested_by="analyste",
    )

    assert decision.target == "REJECTED"


def test_compliance_review_is_an_escalation():
    decision = decide(COMPLIANCE_REVIEW, kind="BUYER", current="SCORED")

    assert decision.target == "COMPLIANCE_REVIEW"


def test_leaving_compliance_review_needs_a_justification_and_an_analyst():
    with pytest.raises(ReviewRejected):
        decide(REQUEST_REVIEW, kind="CREATOR", current="COMPLIANCE_REVIEW")
    with pytest.raises(ReviewRejected):
        decide(
            REQUEST_REVIEW,
            kind="CREATOR",
            current="COMPLIANCE_REVIEW",
            note="à revoir",
        )

    decision = decide(
        REQUEST_REVIEW,
        kind="CREATOR",
        current="COMPLIANCE_REVIEW",
        note="sanctions levées",
        requested_by="analyste",
    )

    assert decision.target == "TO_REVIEW"


def test_audit_and_pool_are_creator_steps():
    assert decide(START_AUDIT, kind="CREATOR", current="PRESELECTED").target == "AUDIT"
    with pytest.raises(ReviewRejected):
        decide(START_AUDIT, kind="BUYER", current="PRESELECTED")
    with pytest.raises(ReviewRejected):
        decide(START_AUDIT, kind="CREATOR", current="SCORED")

    assert decide(ADD_TO_POOL, kind="CREATOR", current="AUDIT").target == "POOL"
    with pytest.raises(ReviewRejected):
        decide(ADD_TO_POOL, kind="BUYER", current="AUDIT")
    with pytest.raises(ReviewRejected):
        decide(ADD_TO_POOL, kind="CREATOR", current="PRESELECTED")


def test_mark_contacted_requires_approval():
    assert (
        decide(MARK_CONTACTED, kind="CREATOR", current="APPROVED").target == "CONTACTED"
    )
    with pytest.raises(ReviewRejected):
        decide(MARK_CONTACTED, kind="CREATOR", current="POOL")


def test_opt_out_is_the_most_restrictive_outcome():
    assert decide(RECORD_OPT_OUT, kind="CREATOR", current="APPROVED").target == (
        "OPT_OUT"
    )
    assert decide(RECORD_OPT_OUT, kind="BUYER", current="CLIENT").target == "OPT_OUT"


def test_a_closed_fiche_is_not_reopened():
    with pytest.raises(ReviewRejected):
        decide(REQUEST_REVIEW, kind="CREATOR", current="OPT_OUT")
    with pytest.raises(ReviewRejected):
        decide(REQUEST_REVIEW, kind="CREATOR", current="CLIENT")


def test_repeating_the_same_action_is_a_no_op():
    decision = decide(REQUEST_REVIEW, kind="CREATOR", current="TO_REVIEW")

    assert decision.target is None
    assert decision.justification == actions.DEFAULT_JUSTIFICATION[REQUEST_REVIEW]


def test_unknown_action_or_kind_is_refused():
    with pytest.raises(ReviewRejected):
        decide("SOMETHING_ELSE", kind="CREATOR", current="SCORED")
    with pytest.raises(ReviewRejected):
        decide(REQUEST_REVIEW, kind="CONTACT", current="SCORED")
