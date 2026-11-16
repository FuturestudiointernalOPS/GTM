"""Tests for the per-record collection loop.

One candidate in, one score out. The tests cover the two design choices that
matter: evidence is anchored to the page the candidate carries, and it is
partitioned per record so two creators cannot contradict each other.
"""
import json
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from ai.provider import AIProvider
from processing.engagement import EngagementItem
from processing.scoring import PRESELECTED, TO_REVIEW
from workflows.record_loop import (
    Candidate,
    collect_claims,
    record_claims,
    score_candidate,
    score_candidates,
)

READ = "2026-11-10T12:00:00+00:00"


def claims_answer(gaming_share=60):
    return json.dumps(
        {
            "gaming_share": gaming_share,
            "gaming_window": 30,
            "followers": 25_000,
            "published_last_30_days": 7,
            "ad_contact_or_rate_card": True,
            "past_labeled_ads": False,
            "main_platform": "VK Video",
            "russian_comment_share": 70,
            "comment_sample": 50,
        }
    )


class FakeProvider(AIProvider):
    """Answers from a function of the payload, so each page can differ."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def chat(self, system: str, user: str) -> str:
        self.calls += 1
        return self.answer(json.loads(user))


def candidate(record_id="rec-1", url="https://vk.com/creator", kind="CREATOR"):
    return Candidate(
        kind=kind,
        record_id=record_id,
        source_url=url,
        text="Подписчики: 25 000. 60 % гейминг.",
        read_at=READ,
    )


def items(count=30, value=2_000):
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


# --- one candidate ----------------------------------------------------------


def test_one_candidate_becomes_a_scored_record():
    record = score_candidate(
        FakeProvider(lambda payload: claims_answer()),
        candidate(),
        items=items(),
    )

    assert record.result.score == 79
    assert record.result.proposal == PRESELECTED
    assert record.rejected == ()
    assert record.measure is not None


def test_without_a_sample_the_record_stays_in_review():
    record = score_candidate(FakeProvider(lambda payload: claims_answer()), candidate())

    assert record.result.proposal == TO_REVIEW


def test_the_claims_are_anchored_to_the_candidate_page():
    claims = {"gaming_share": 60, "followers": 25_000}

    ledger = record_claims(claims, source_url="https://vk.com/x", read_at=READ)

    fact = ledger.for_key("gaming_share")[0]
    assert fact.source.url == "https://vk.com/x"
    assert fact.proof_level == "OBSERVED"


def test_an_unknown_candidate_kind_is_refused():
    with pytest.raises(ValueError):
        collect_claims(
            FakeProvider(lambda payload: claims_answer()),
            Candidate(kind="MASCOT", record_id="x", source_url="u", text="", read_at=READ),
        )


# --- evidence is per record -------------------------------------------------


def test_two_creators_do_not_share_their_evidence():
    def answer(payload):
        # The URL decides the gaming share: 60 % for "a", 100 % for "b".
        return claims_answer(60 if "/a" in payload["source_url"] else 100)

    result = score_candidates(
        FakeProvider(answer),
        [
            candidate(record_id="a", url="https://vk.com/a"),
            candidate(record_id="b", url="https://vk.com/b"),
        ],
    )

    assert result.failed == ()
    assert [record.result.score for record in result.scored] == [59, 66]


# --- one bad record does not stop the batch ---------------------------------


def test_a_bad_answer_is_listed_and_the_batch_continues():
    def answer(payload):
        if "/bad" in payload["source_url"]:
            return '{"gaming_share": 60, "invented_key": true}'
        return claims_answer()

    result = score_candidates(
        FakeProvider(answer),
        [
            candidate(record_id="bad", url="https://vk.com/bad"),
            candidate(record_id="good", url="https://vk.com/good"),
        ],
    )

    assert [record_id for record_id, _ in result.failed] == ["bad"]
    assert [record.result.score for record in result.scored] == [59]


def test_an_invented_key_fails_at_the_border():
    with pytest.raises(ValidationError):
        collect_claims(
            FakeProvider(lambda payload: '{"invented_key": 1}'), candidate()
        )
