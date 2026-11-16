"""Tests for the deterministic pipeline. Discovery and reading are replaced."""
from types import SimpleNamespace

import pytest

from processing.deduplication import JsonRecordStore
from workflows import pipeline


def _page(url, query_used, service="exa", snippet=None):
    return {
        "url": url,
        "query_used": query_used,
        "service": service,
        "snippet": snippet,
        "title": "Page",
    }


def _read(url):
    return SimpleNamespace(url=url, status=200, title="Page", text="body", error=None)


def test_pipeline_skips_known_urls_and_reads_only_fresh(monkeypatch, tmp_path):
    store = JsonRecordStore(tmp_path / "records.json")
    store.add(urls=["https://old.example"])

    monkeypatch.setattr(
        pipeline.creator_hunt,
        "hunt_plan",
        lambda plan, **kwargs: {
            "pages": [
                _page("https://vk.com/red", "creator.vk_live.cs2"),
                _page("https://old.example", "creator.vk_live.cs2"),
            ]
        },
    )
    monkeypatch.setattr(
        pipeline.buyer_hunt,
        "hunt_plan",
        lambda plan, **kwargs: {
            "pages": [_page("https://brand.example", "buyer.ads.esports", "serpapi")]
        },
    )

    read_calls = []

    def fake_read_urls(urls, **kwargs):
        read_calls.append(list(urls))
        return [_read(url) for url in urls]

    monkeypatch.setattr(pipeline.webreader, "read_urls", fake_read_urls)

    result = pipeline.run_week(week=1, store=store, read_top=2)

    assert [page["url"] for page in result.skipped] == ["https://old.example"]
    read_urls = [url for batch in read_calls for url in batch]
    assert "https://old.example" not in read_urls
    assert set(read_urls) == {"https://vk.com/red", "https://brand.example"}
    assert result.ledger.keys() == {"url", "text"}
    assert store.contains_url("https://vk.com/red")
    assert store.contains_url("https://brand.example")


def test_read_top_caps_pages_per_query(monkeypatch):
    pages = [
        _page(f"https://vk.com/{index}", "creator.vk_live.cs2")
        for index in range(5)
    ]
    monkeypatch.setattr(
        pipeline.creator_hunt,
        "hunt_plan",
        lambda plan, **kwargs: {"pages": pages},
    )
    monkeypatch.setattr(
        pipeline.buyer_hunt, "hunt_plan", lambda plan, **kwargs: {"pages": []}
    )
    seen = []

    def fake_read_urls(urls, **kwargs):
        seen.extend(urls)
        return []

    monkeypatch.setattr(pipeline.webreader, "read_urls", fake_read_urls)

    pipeline.run_week(week=1, read_top=2)

    assert seen == ["https://vk.com/0", "https://vk.com/1"]


def test_pipeline_excludes_betting_by_default(monkeypatch):
    monkeypatch.setattr(
        pipeline.creator_hunt, "hunt_plan", lambda plan, **kwargs: {"pages": []}
    )
    monkeypatch.setattr(
        pipeline.buyer_hunt, "hunt_plan", lambda plan, **kwargs: {"pages": []}
    )
    monkeypatch.setattr(pipeline.webreader, "read_urls", lambda urls, **kwargs: [])

    result = pipeline.run_week(week=1)

    assert not any(query.betting for query in result.plan)


def test_read_batch_max_is_checked_before_any_work():
    with pytest.raises(ValueError, match="read_batch_max"):
        pipeline.run_week(week=1, read_batch_max=0)
