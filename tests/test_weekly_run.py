"""Tests for the weekly run: collect, score, write.

The collector, the model, the actor fetcher and the writer are all injected, so
the whole run is exercised offline.
"""
import json
from datetime import datetime, timedelta

from ai.provider import AIProvider
from integrations.webreader import PageRead
from processing.evidence import EvidenceLedger
from workflows.pipeline import PipelineResult
from workflows.record_flow import RecordScore
from workflows.records import MemoryRecordStore
from workflows.weekly_run import run_and_score

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

TEXT = " | ".join(QUOTES.values())


class FakeProvider(AIProvider):
    def chat(self, system: str, user: str) -> str:
        return json.dumps({"claims": CLAIMS, "quotes": QUOTES})


def vk_rows(count=30, value=2_000):
    base = datetime.fromisoformat(READ)
    return [
        {
            "url": f"https://vk.com/video-1_{index}",
            "published_at": (base - timedelta(days=index)).isoformat(),
            "views": value,
        }
        for index in range(1, count + 1)
    ]


def collected() -> PipelineResult:
    page = {
        "url": "https://vk.com/creator",
        "query_used": "creator.general.telegram_rating_2026",
        "snippet": TEXT,
    }
    return PipelineResult(
        plan=(),
        pages=[page],
        fresh=[page],
        skipped=[],
        reads=[PageRead(url="https://vk.com/creator", text=TEXT)],
        ledger=EvidenceLedger(),
        collected_at=READ,
    )


def test_the_run_scores_the_fresh_pages():
    run = run_and_score(
        provider=FakeProvider(),
        fetch=lambda platform, url: vk_rows(),
        collect=collected,
    )

    assert run.fresh_pages == 1
    assert [record.result.score for record in run.scores.scored] == [79]
    assert run.scores.failed == ()
    assert run.written == ()


def test_the_writer_receives_each_record_with_its_id():
    seen = []

    def write(record: RecordScore) -> str:
        seen.append((record.record_id, record.result.score))
        return "run-1"

    run = run_and_score(
        provider=FakeProvider(),
        fetch=lambda platform, url: vk_rows(),
        collect=collected,
        write=write,
    )

    assert seen == [("vk.com/creator", 79)]
    assert run.written == ("run-1",)


def test_a_record_that_writes_nothing_is_not_a_failure():
    run = run_and_score(
        provider=FakeProvider(),
        fetch=lambda platform, url: vk_rows(),
        collect=collected,
        write=lambda record: None,
    )

    assert run.written == ()
    assert run.write_failed == ()


def test_a_failed_write_is_listed_and_stops_nothing():
    def write(record: RecordScore):
        raise RuntimeError("base indisponible")

    run = run_and_score(
        provider=FakeProvider(),
        fetch=lambda platform, url: vk_rows(),
        collect=collected,
        write=write,
    )

    assert run.write_failed == (("vk.com/creator", "base indisponible"),)


# --- records ----------------------------------------------------------------


def test_the_run_uses_real_ids_when_a_store_is_given():
    run = run_and_score(
        provider=FakeProvider(),
        fetch=lambda platform, url: vk_rows(),
        collect=collected,
        records=MemoryRecordStore(),
    )

    record = run.scores.scored[0]
    assert record.record_id == "rec-1"
    assert record.account_id == "acc-1"


def test_two_runs_on_the_same_page_reuse_the_record():
    store = MemoryRecordStore()

    first = run_and_score(
        provider=FakeProvider(),
        fetch=lambda platform, url: vk_rows(),
        collect=collected,
        records=store,
    )
    second = run_and_score(
        provider=FakeProvider(),
        fetch=lambda platform, url: vk_rows(),
        collect=collected,
        records=store,
    )

    assert (
        first.scores.scored[0].record_id == second.scores.scored[0].record_id
    )
