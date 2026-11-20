"""Tests for the demonstration command. No network and no model call."""

from integrations import webreader
from workflows import demo


def _page(url, title, **extra):
    return {
        "url": url,
        "title": title,
        "published_date": None,
        "author": None,
        "text": None,
        **extra,
    }


class FakeProvider:
    def __init__(self):
        self.payload = None

    def generate_outreach(self, data):
        self.payload = data
        return {
            "channel": "telegram",
            "subject": "",
            "message": "Здравствуйте! Мы делаем кампании с создателями контента.",
            "personalisation": "издатель игр",
        }


def _install(monkeypatch, creators, companies):
    monkeypatch.setattr(
        demo.creator_hunt,
        "hunt_plan",
        lambda plan, **options: {"queries": [plan[0].id], "pages": creators},
    )
    monkeypatch.setattr(
        demo.buyer_hunt,
        "hunt_plan",
        lambda plan, **options: {"queries": [plan[0].id], "pages": companies},
    )


def _read(url, *, max_chars):
    return webreader.PageRead(
        url=url,
        status=200,
        title="Издатель игр",
        text="Мы издатель игр и ищем блогеров для кампании.",
    )


def test_build_demo_lists_both_sides_and_drafts_a_message(monkeypatch):
    _install(
        monkeypatch,
        creators=[
            _page(
                "https://twitch.tv/streamer",
                "Streamer",
                platform="Twitch",
                query_used="creator.twitch.cs2",
            )
        ],
        companies=[
            _page(
                "https://studio.example",
                "Studio",
                query_used="buyer.category.game_studios",
            )
        ],
    )
    provider = FakeProvider()

    report = demo.build_demo(week=45, provider=provider, read=_read)

    assert report["week"] == 45
    assert [run["pages_found"] for run in report["queries"]] == [1, 1]
    assert report["creators"] == [
        {
            "title": "Streamer",
            "url": "https://twitch.tv/streamer",
            "platform": "Twitch",
            "query_used": "creator.twitch.cs2",
        }
    ]
    assert report["companies"] == [
        {
            "title": "Studio",
            "url": "https://studio.example",
            "query_used": "buyer.category.game_studios",
        }
    ]
    assert report["outreach"]["draft"]["message"].startswith("Здравствуйте")
    assert report["outreach"]["recipient"]["url"] == "https://twitch.tv/streamer"
    assert provider.payload["public_page_excerpt"].startswith("Мы издатель игр")
    assert "Créateurs trouvés : 1" in report["telegram_notification"]
    assert "Entreprises trouvées : 1" in report["telegram_notification"]


def test_build_demo_can_skip_the_model(monkeypatch):
    _install(
        monkeypatch,
        creators=[_page("https://twitch.tv/streamer", "Streamer", platform="Twitch")],
        companies=[],
    )

    report = demo.build_demo(week=45, no_ai=True, read=_read)

    assert report["outreach"]["draft"] is None
    assert "désactivée" in report["outreach"]["error"]


def test_the_buyer_recipient_is_preferred_when_asked(monkeypatch):
    _install(
        monkeypatch,
        creators=[_page("https://twitch.tv/streamer", "Streamer", platform="Twitch")],
        companies=[_page("https://studio.example", "Studio")],
    )
    provider = FakeProvider()

    report = demo.build_demo(
        week=45,
        recipient="buyer",
        provider=provider,
        read=_read,
    )

    assert report["outreach"]["recipient"]["url"] == "https://studio.example"


def test_a_directory_page_is_not_chosen_for_the_draft(monkeypatch):
    _install(
        monkeypatch,
        creators=[
            _page(
                "https://www.twitch.tv/directory/all/tags/minecraft",
                "Top Channels",
                platform="Twitch",
            ),
            _page("https://www.twitch.tv/real_streamer", "Streamer", platform="Twitch"),
        ],
        companies=[],
    )

    report = demo.build_demo(week=45, provider=FakeProvider(), read=_read)

    assert report["outreach"]["recipient"]["url"] == (
        "https://www.twitch.tv/real_streamer"
    )


def test_render_text_shows_the_demo_sections(monkeypatch):
    _install(
        monkeypatch,
        creators=[_page("https://twitch.tv/streamer", "Streamer", platform="Twitch")],
        companies=[_page("https://studio.example", "Studio")],
    )
    report = demo.build_demo(week=45, provider=FakeProvider(), read=_read)

    text = demo.render_text(report)

    assert "DÉMO GTM — SEMAINE 45" in text
    assert "1. RECHERCHE" in text
    assert "2. CRÉATEURS TROUVÉS (1)" in text
    assert "3. ENTREPRISES TROUVÉES (1)" in text
    assert "Streamer" in text
    assert "Studio" in text
    assert "Здравствуйте" in text
    assert "Non demandé" in text


def test_render_text_reports_an_empty_draft():
    report = {
        "week": 45,
        "queries": [],
        "creators": [],
        "companies": [],
        "telegram_notification": "Résumé",
        "outreach": {
            "recipient": None,
            "draft": None,
            "error": "aucune page trouvée",
        },
        "telegram_sent": False,
        "telegram_error": None,
    }

    text = demo.render_text(report)

    assert "Aucune page." in text
    assert "Aucun destinataire." in text
    assert "Attention : aucune page trouvée" in text
