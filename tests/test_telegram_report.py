from datetime import date

import pytest

from workflows.telegram_report import (
    Candidate,
    Draft,
    Target,
    WeeklyReport,
    candidates_from_pages,
    display_name,
    platform_of,
    readable_url,
    render,
    split,
)


def _report(**kwargs) -> WeeklyReport:
    return WeeklyReport(run_date=date(2026, 11, 30), **kwargs)


def test_empty_report_shows_every_section_and_invents_nothing():
    text = render(_report())
    for title in (
        "1) SPEND",
        "2) FUNNEL",
        "3) TOP 5 CREATORS",
        "4) TOP 5 BUYERS",
        "5) BLOCKERS",
        "DRAFTS AWAITING YOUR APPROVAL",
    ):
        assert title in text
    assert "not measured yet" in text
    assert "Nothing goes out without your reply." in text
    assert "DEMO" not in text


def test_demo_banner():
    assert render(_report(demo=True)).startswith("🧪 DEMO")


def test_top_is_sorted_by_score_and_capped_at_five():
    creators = tuple(
        Candidate(name=f"c{i}", url=f"https://twitch.tv/c{i}", score=s)
        for i, s in enumerate([50, None, 90, 70, 60, 80])
    )
    text = render(_report(creators=creators))
    assert text.index("C1 · c2 — 90/100") < text.index("C2 · c5 — 80/100")
    assert "c1" not in text.split("TOP 5 BUYERS")[0].replace("C1", "")
    assert "+ 1 more in Baserow" in text


def test_funnel_marks():
    text = render(
        _report(
            funnel=(
                Target("Screened", 64, 60),
                Target("Kept", 3, 5),
                Target("Checked", 2, note="pending"),
            )
        )
    )
    assert "✅ Screened: 64 / 60" in text
    assert "⚠️ Kept: 3 / 5" in text
    assert "▫️ Checked: 2" in text
    assert "↳ pending" in text


def test_drafts_are_numbered_with_reply_hint():
    text = render(
        _report(drafts=(Draft("B1", "BrandA", "email"), Draft("C1", "StreamerA", "DM")))
    )
    assert "1 · B1 BrandA — email" in text
    assert "2 · C1 StreamerA — DM" in text
    assert "send 1, 3; drop 2" in text


def test_draft_note_can_replace_the_baserow_hint():
    drafts = (Draft("C1", "StreamerA", "DM"),)
    text = render(_report(drafts=drafts, draft_note=("Shown in the console.",)))
    assert "Shown in the console." in text
    assert "Baserow" not in text
    assert text.endswith("Nothing goes out without your reply.")


def test_display_name_and_platform():
    assert display_name("About x - Twitch", "https://www.twitch.tv/krutoy/about") == (
        "krutoy"
    )
    assert display_name(
        "kotiki на VK Видео Live", "https://live.vkvideo.ru/kotiki"
    ) == ("kotiki")
    assert display_name("Блогеры / Хабр", "https://habr.com/a") == "Блогеры"
    assert display_name(None, "https://www.example.com/") == "example.com"
    assert len(display_name("x" * 100, "https://a.com/b")) == 58
    assert platform_of("https://live.vkvideo.ru/k") == "VK Video"
    assert platform_of("https://vk.com/wall-1") == "VK"
    assert platform_of("https://example.com") is None


def test_readable_url_decodes_cyrillic_but_keeps_spaces_encoded():
    assert readable_url("https://a.ru/%D1%85%D0%BE") == "https://a.ru/хо"
    assert readable_url("https://a.ru/a%20b") == "https://a.ru/a%20b"


def test_candidates_from_pages_drops_duplicates_and_empty_urls():
    pages = [
        {"url": "https://twitch.tv/a", "title": "A"},
        {"url": "https://twitch.tv/a", "title": "A again"},
        {"url": "", "title": "none"},
    ]
    result = candidates_from_pages(pages)
    assert [c.name for c in result] == ["a"]
    assert result[0].platform == "Twitch"


def test_split_keeps_sections_whole_and_respects_limit():
    text = "\n\n".join(["a" * 40, "b" * 40, "c" * 40])
    messages = split(text, limit=90)
    assert messages == ["a" * 40 + "\n\n" + "b" * 40, "c" * 40]


def test_split_cuts_an_oversized_block():
    messages = split("x" * 250, limit=100)
    assert all(len(m) <= 100 for m in messages)
    assert "".join(m.replace("\n", "") for m in messages) == "x" * 250


def test_split_rejects_bad_limit():
    with pytest.raises(ValueError):
        split("a", limit=0)


def test_full_report_fits_telegram_after_split():
    creators = tuple(
        Candidate(name=f"c{i}", url="https://twitch.tv/" + "z" * 900, why="w" * 200)
        for i in range(5)
    )
    for message in split(render(_report(creators=creators, buyers=creators))):
        assert len(message) <= 4096


def test_header_shows_the_real_weekday():
    assert "Monday 30 Nov 2026" in render(_report())
    friday = WeeklyReport(run_date=date(2026, 11, 20))
    assert "Friday 20 Nov 2026" in render(friday)
