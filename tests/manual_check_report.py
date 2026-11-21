"""Manual check: show (and optionally send) the Monday report layout.

The pages below come from the week 45 demo search; scores, spend and drafts
are invented to show the layout, and the message carries a DEMO banner.

    python -m tests.manual_check_report          # print only
    python -m tests.manual_check_report --send   # also send it on Telegram
"""

import sys
from dataclasses import replace
from datetime import date

from integrations import telegram
from workflows.telegram_report import (
    Draft,
    Target,
    WeeklyReport,
    candidates_from_pages,
    render,
    split,
)

CREATOR_PAGES = [
    {
        "title": "About krutoymonitor2008 - Twitch",
        "url": "https://www.twitch.tv/krutoymonitor2008/about",
    },
    {
        "title": "kotiki_z на VK Видео Live – смотреть онлайн трансляции",
        "url": "https://live.vkvideo.ru/kotiki_z",
    },
    {
        "title": "⚡ShadowPriestok снова выбрали официальным русскоязычным.. | VK",
        "url": "https://vk.com/wall-160190425_257660",
    },
]

BUYER_PAGES = [
    {
        "title": "Хочу снимать контент для Black Russia — Black Russia",
        "url": "https://helpshift.blackrussian.games/hc/ru/3-black-russia/faq/"
        "48-%D1%85%D0%BE%D1%87%D1%83-%D1%81%D0%BD%D0%B8%D0%BC%D0%B0%D1%82%D1%8C",
    },
    {
        "title": "Программа сотрудничества с блогерами: подробности",
        "url": "https://tanki.su/ru/content/docs/blogger-program/",
    },
    {"title": "Сотрудничество", "url": "https://gameartpioneers.com/collaboration/"},
    {
        "title": "Блогеры | «Мир кораблей»",
        "url": "https://korabli.su/ru/content/bloggers-program/",
    },
]


def demo_report() -> WeeklyReport:
    creators = candidates_from_pages(CREATOR_PAGES)
    buyers = candidates_from_pages(BUYER_PAGES)
    # Invented scores, only to show how a scored line looks.
    first = replace(
        creators[0],
        detail="Minecraft",
        score=78,
        why="steady KZ audience, 2 sponsored streams in 30 days",
    )
    creators = (first, *creators[1:])
    return WeeklyReport(
        run_date=date.today(),
        finished_at="07:42 UTC",
        tool_spend={"Exa": 0.62, "Apify": 2.10},
        tool_budget=15,
        ai_spend=0.35,
        funnel=(
            Target("Creators screened", len(creators), 60),
            Target("Buyers researched", len(buyers), 30),
            Target("Sanctions checked", 0, note="rules from intern 3 pending"),
        ),
        creators=creators,
        buyers=buyers,
        blockers=(
            "Scoring rules not final (intern 2)",
            "Exa and Apify keys still to share",
        ),
        drafts=(Draft("C1", creators[0].name, "DM (RU, sent by a person)"),),
        demo=True,
    )


def main(argv: list[str]) -> None:
    messages = split(render(demo_report()))
    for number, text in enumerate(messages, start=1):
        print(f"----- message {number}/{len(messages)} ({len(text)} chars) -----")
        print(text)

    if "--send" not in argv:
        print("\nNot sent. Add --send to send it on Telegram.")
        return
    if not telegram.is_configured():
        raise SystemExit("Telegram is not configured (.env)")
    for text in messages:
        telegram.send_message(text)
    print(f"\nSent {len(messages)} message(s).")


if __name__ == "__main__":
    main(sys.argv[1:])
