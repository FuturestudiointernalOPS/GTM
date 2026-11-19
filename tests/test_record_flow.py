"""Tests for the record flow: claims in, score rows out.

These are the only tests that exercise the whole chain the pipeline will call:
extraction, enrichment, engagement measure, scoring and the rows for the base.
"""

from datetime import datetime, timedelta

from processing.engagement import EngagementItem
from processing.evidence import INFERRED, EvidenceLedger, Source
from processing.scoring import PRESELECTED, QUALIFIED, TO_REVIEW
from workflows.record_flow import (
    creator_measure,
    score_buyer_record,
    score_creator_record,
)

READ = "2026-11-10T12:00:00+00:00"

CREATOR_CLAIMS = {
    "gaming_share": 60,
    "gaming_window": 30,
    "followers": 25_000,
    "published_last_30_days": 7,
    "ad_contact_or_rate_card": True,
    "past_labeled_ads": False,
    "main_platform": "VK Video",
    "russian_comment_share": 70,
    "comment_sample": 50,
}

BUYER_CLAIMS = {
    "creators_paid": 1,
    "sells_to_gamers": True,
    "decision_maker_role": "CMO",
    "decision_maker_email_verified": True,
    "employee_band": "50-199",
    "recent_event": True,
}


def evidence_for(claims, *, skip=(), proof_level="OBSERVED"):
    ledger = EvidenceLedger()
    for key, value in claims.items():
        if key in skip:
            continue
        ledger.add(
            key,
            value,
            Source(url=f"https://example.test/{key}", consulted_at=READ),
            proof_level=proof_level,
        )
    return ledger


def vk_items(count=30, value=2_000):
    base = datetime.fromisoformat(READ)
    return [
        EngagementItem(
            platform="vk_video",
            item_url=f"https://vk.test/video/{index}",
            item_kind="LONG_VIDEO",
            published_at=(base - timedelta(days=index)).isoformat(),
            value=value,
            read_at=READ,
        )
        for index in range(1, count + 1)
    ]


def line(record, criterion):
    return next(
        item for item in record.line_rows() if item["criterion_code"] == criterion
    )


# --- creator ----------------------------------------------------------------


def test_a_creator_record_goes_from_claims_to_rows():
    record = score_creator_record(
        CREATOR_CLAIMS,
        evidence_for(CREATOR_CLAIMS),
        items=vk_items(),
        snapshot=READ,
        measure_run_id="run-1",
    )

    assert record.result.total_exact == 79.875
    assert record.result.score == 79
    assert record.result.proposal == PRESELECTED
    assert record.rejected == ()

    run = record.run_row()
    assert run is not None and run["score"] == 79
    assert line(record, "engagement")["engagement_measure_run_id"] == "run-1"


def test_the_snapshot_can_come_from_the_sample():
    record = score_creator_record(
        CREATOR_CLAIMS, evidence_for(CREATOR_CLAIMS), items=vk_items()
    )

    assert record.result.score == 79
    assert record.result.proposal == PRESELECTED


def test_without_a_sample_the_engagement_stays_unknown():
    record = score_creator_record(CREATOR_CLAIMS, evidence_for(CREATOR_CLAIMS))

    assert line(record, "engagement")["status"] == "UNKNOWN"
    assert record.result.proposal == TO_REVIEW
    assert record.result.score == 59  # 59.875 without the engagement line


def test_an_unproven_claim_leaves_the_criterion_unknown():
    record = score_creator_record(
        CREATOR_CLAIMS,
        evidence_for(CREATOR_CLAIMS, skip={"gaming_share"}),
        items=vk_items(),
        snapshot=READ,
    )

    assert "gaming_share: aucune preuve" in record.rejected
    assert line(record, "focus_gaming")["status"] == "UNKNOWN"
    assert record.result.proposal == TO_REVIEW


def test_an_inferred_claim_never_scores():
    ledger = evidence_for(CREATOR_CLAIMS, skip={"gaming_share"})
    ledger.add(
        "gaming_share",
        60,
        Source(url="https://example.test/guess", consulted_at=READ),
        proof_level=INFERRED,
    )

    record = score_creator_record(
        CREATOR_CLAIMS, ledger, items=vk_items(), snapshot=READ
    )

    assert "gaming_share: fait inféré, aucun point" in record.rejected
    assert line(record, "focus_gaming")["status"] == "UNKNOWN"


def test_the_measure_can_be_written_before_the_score():
    ledger = evidence_for(CREATOR_CLAIMS)
    measured = creator_measure(CREATOR_CLAIMS, ledger, items=vk_items())

    assert measured is not None
    record = score_creator_record(
        CREATOR_CLAIMS,
        ledger,
        measure=measured,
        measure_run_id="measure-9",
    )

    assert record.result.score == 79
    assert line(record, "engagement")["engagement_measure_run_id"] == "measure-9"
    assert record.measure is measured


# --- buyer ------------------------------------------------------------------


def test_a_buyer_record_has_no_engagement_step():
    record = score_buyer_record(BUYER_CLAIMS, evidence_for(BUYER_CLAIMS))

    assert record.kind == "BUYER"
    assert record.result.total_exact == 85
    assert record.result.proposal == QUALIFIED
    assert [item["criterion_code"] for item in record.line_rows()] == [
        "pays_creators",
        "sells_to_gamers",
        "decision_maker",
        "size",
        "timing",
    ]
