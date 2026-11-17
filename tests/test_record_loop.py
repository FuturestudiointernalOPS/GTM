"""Tests for the per-record collection loop.

One candidate in, one score out. The tests cover three design choices: evidence
is anchored to the page, it is partitioned per record, and a claim survives only
if its verbatim quote really appears on the page.
"""

import json
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from ai.provider import AIProvider
from integrations.webreader import PageRead
from processing.engagement import EngagementItem
from processing.scoring import PRESELECTED, TO_REVIEW
from workflows.record_flow import BUYER, CREATOR
from workflows.record_loop import (
    Candidate,
    Claims,
    candidates_from_pages,
    collect_claims,
    kind_for_query,
    record_claims,
    score_candidate,
    score_candidates,
    score_pages,
    verify_quotes,
)
from workflows.records import MemoryRecordStore, ensure_record

READ = "2026-11-10T12:00:00+00:00"

QUOTES = {
    "gaming_share": "60 % гейминг",
    "gaming_window": "окно 30 публикаций",
    "followers": "25 000 подписчиков",
    "published_last_30_days": "7 публикаций за 30 дней",
    "ad_contact_or_rate_card": "по вопросам рекламы",
    "past_labeled_ads": "реклама с erid",
    "main_platform": "платформа VK Video",
    "russian_comment_share": "70 % комментариев",
    "comment_sample": "50 сообщений",
}

CLAIMS = {
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


def page(share=60):
    quotes = dict(QUOTES, gaming_share=f"{share} % гейминг")
    return " | ".join(quotes.values()) + "."


def answer(share=60, *, drop=None, override=None, extra=None):
    claims = dict(CLAIMS, gaming_share=share)
    quotes = dict(QUOTES, gaming_share=f"{share} % гейминг")
    if drop:
        quotes.pop(drop, None)
    if override:
        quotes.update(override)
    if extra:
        claims.update(extra)
    return json.dumps({"claims": claims, "quotes": quotes})


class FakeProvider(AIProvider):
    """Answers from a function of the payload, so each page can differ."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def chat(self, system: str, user: str) -> str:
        self.calls += 1
        return self.reply(json.loads(user))


def candidate(
    record_id="rec-1", url="https://vk.com/creator", share=60, kind="CREATOR"
):
    return Candidate(
        kind=kind,
        record_id=record_id,
        source_url=url,
        text=page(share),
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
        FakeProvider(lambda payload: answer()), candidate(), items=items()
    )

    assert record.result.score == 79
    assert record.result.proposal == PRESELECTED
    assert record.rejected == ()
    assert record.measure is not None


def test_without_a_sample_the_record_stays_in_review():
    record = score_candidate(FakeProvider(lambda payload: answer()), candidate())

    assert record.result.proposal == TO_REVIEW


def test_the_claims_are_anchored_to_the_candidate_page():
    ledger = record_claims(
        {"gaming_share": 60}, source_url="https://vk.com/x", read_at=READ
    )

    fact = ledger.for_key("gaming_share")[0]
    assert fact.source.url == "https://vk.com/x"
    assert fact.proof_level == "OBSERVED"


def test_an_unknown_candidate_kind_is_refused():
    with pytest.raises(ValueError):
        collect_claims(
            FakeProvider(lambda payload: answer()),
            Candidate(
                kind="MASCOT",
                record_id="x",
                source_url="u",
                text="",
                read_at=READ,
            ),
        )


# --- the quote is checked ---------------------------------------------------


def test_a_missing_quote_costs_the_claim():
    record = score_candidate(
        FakeProvider(lambda payload: answer(drop="gaming_share")),
        candidate(),
        items=items(),
    )

    assert "gaming_share: citation manquante ou trop courte" in record.rejected
    assert record.result.proposal == TO_REVIEW
    assert record.result.score == 61


def test_a_quote_absent_from_the_page_is_dropped():
    kept, rejected = verify_quotes(
        Claims(values={"followers": 1}, quotes={"followers": "42 000 подписчиков"}),
        text="25 000 подписчиков",
    )

    assert kept == {}
    assert rejected == ("followers: citation introuvable dans la page",)


def test_a_too_short_quote_is_dropped():
    kept, rejected = verify_quotes(
        Claims(values={"followers": 1}, quotes={"followers": "25 000"}),
        text="25 000 подписчиков",
    )

    assert kept == {}
    assert rejected == ("followers: citation manquante ou trop courte",)


def test_a_quote_is_matched_ignoring_case_and_spacing():
    kept, rejected = verify_quotes(
        Claims(values={"followers": 1}, quotes={"followers": "25 000   ПОДПИСЧИКОВ"}),
        text="подписчики: 25 000 подписчиков",
    )

    assert kept == {"followers": 1}
    assert rejected == ()


# --- evidence is per record -------------------------------------------------


def test_two_creators_do_not_share_their_evidence():
    def reply(payload):
        return answer(60 if "/a" in payload["source_url"] else 100)

    result = score_candidates(
        FakeProvider(reply),
        [
            candidate(record_id="a", url="https://vk.com/a", share=60),
            candidate(record_id="b", url="https://vk.com/b", share=100),
        ],
    )

    assert result.failed == ()
    assert [record.result.score for record in result.scored] == [59, 66]


# --- one bad record does not stop the batch ---------------------------------


def test_a_bad_answer_is_listed_and_the_batch_continues():
    def reply(payload):
        if "/bad" in payload["source_url"]:
            return answer(extra={"invented_key": True})
        return answer()

    result = score_candidates(
        FakeProvider(reply),
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
            FakeProvider(lambda payload: '{"claims": {"invented_key": 1}}'),
            candidate(),
        )


# --- the weekly entry -------------------------------------------------------


def test_the_query_block_tells_the_filon():
    # The id prefix is not enough: "cis." carries both creators and buyers.
    assert kind_for_query("creator.general.telegram_rating_2026") == CREATOR
    assert kind_for_query("cis.uz_gaming_bloggers") == CREATOR
    assert kind_for_query("cis.kz_esports_partners") == BUYER
    assert kind_for_query("not.a.query") is None
    assert kind_for_query(None) is None


def test_pages_become_candidates():
    reads = [PageRead(url="https://vk.com/a", text=page())]
    pages = [
        {
            "url": "https://vk.com/a",
            "query_used": "creator.general.telegram_rating_2026",
            "snippet": "сниппет",
        },
        {
            "url": "https://vk.com/b",
            "query_used": "cis.kz_esports_partners",
            "snippet": "компания продаёт игрокам",
        },
    ]

    candidates = candidates_from_pages(pages, reads, read_at=READ)

    assert [item.kind for item in candidates] == [CREATOR, BUYER]
    assert candidates[0].text == page()  # the read text wins over the snippet
    assert candidates[1].text == "компания продаёт игрокам"
    assert candidates[0].record_id == "vk.com/a"


def test_a_page_without_text_or_known_query_is_skipped():
    pages = [
        {
            "url": "https://vk.com/x",
            "query_used": "creator.general.telegram_rating_2026",
        },
        {"url": "https://vk.com/y", "query_used": "not.a.query", "snippet": "txt"},
        {"query_used": "creator.general.telegram_rating_2026", "snippet": "txt"},
    ]

    assert candidates_from_pages(pages, read_at=READ) == []


def test_score_pages_scores_the_fresh_pages():
    pages = [
        {
            "url": "https://vk.com/a",
            "query_used": "creator.general.telegram_rating_2026",
            "snippet": page(),
        }
    ]

    result = score_pages(FakeProvider(lambda payload: answer()), pages, read_at=READ)

    assert result.failed == ()
    assert [record.result.score for record in result.scored] == [59]


# --- the sample can be collected on the way ----------------------------------


def test_a_sample_gives_the_creator_its_engagement_points():
    record = score_candidate(
        FakeProvider(lambda payload: answer()),
        candidate(),
        sample_for=lambda item: items(),
    )

    assert record.result.score == 79
    assert record.result.proposal == PRESELECTED


def test_score_pages_can_collect_samples():
    pages = [
        {
            "url": "https://vk.com/a",
            "query_used": "creator.general.telegram_rating_2026",
            "snippet": page(),
        }
    ]

    result = score_pages(
        FakeProvider(lambda payload: answer()),
        pages,
        read_at=READ,
        sample_for=lambda item: items(),
    )

    assert [record.result.score for record in result.scored] == [79]


# --- records and measure ids ------------------------------------------------


def test_the_loop_carries_the_record_and_account_ids():
    store = MemoryRecordStore()

    record = score_candidate(
        FakeProvider(lambda payload: answer()),
        candidate(),
        record_for=lambda item: ensure_record(store, item),
    )

    assert record.record_id is not None and record.record_id.startswith("rec-")
    assert record.account_id is not None and record.account_id.startswith("acc-")


def test_the_measure_is_saved_before_the_score_line_is_bound():
    store = MemoryRecordStore()
    saved = []

    def save(measure, account_id):
        saved.append((measure.value, account_id))
        return "measure-1"

    record = score_candidate(
        FakeProvider(lambda payload: answer()),
        candidate(),
        items=items(),
        record_for=lambda item: ensure_record(store, item),
        save_measure=save,
    )

    assert saved == [(2000, record.account_id)]
    line = next(
        row for row in record.line_rows() if row["criterion_code"] == "engagement"
    )
    assert line["engagement_measure_run_id"] == "measure-1"
