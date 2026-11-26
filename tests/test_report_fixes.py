from datetime import date

from workflows.run_report import short_error
from workflows.telegram_report import (
    Candidate,
    WeeklyReport,
    display_name,
    readable_url,
    render,
    short_line,
)

PYDANTIC = (
    "4 validation errors for CreatorExtraction\n"
    "quotes.gaming_share\n"
    "  Input should be a valid string [type=string_type, input_value=None]\n"
    "    For further information visit https://errors.pydantic.dev/2.14/v/string_type\n"
    "quotes.comment_sample\n"
    "  Input should be a valid string [type=string_type, input_value=None]\n"
)


def test_validation_error_becomes_one_line():
    assert short_error(PYDANTIC) == (
        "réponse IA incomplète (CreatorExtraction : gaming_share, comment_sample)"
    )


def test_other_errors_keep_their_first_line_only():
    assert short_error("timeout\ntraceback...") == "timeout"
    assert short_error("") == "erreur inconnue"


def test_blockers_are_one_short_line_each():
    report = WeeklyReport(run_date=date(2026, 11, 30), blockers=("a" * 300 + "\nb",))
    line = [x for x in render(report).splitlines() if x.startswith("• ")][0]
    assert len(line) <= 2 + 160
    assert line.endswith("…")
    assert short_line("x\ny") == "x"


def test_more_note_follows_the_run():
    items = tuple(
        Candidate(name=f"c{i}", url=f"https://t.me/c{i}xxxx", score=i) for i in range(7)
    )
    saved = render(WeeklyReport(run_date=date(2026, 11, 30), creators=items))
    assert "+ 2 more in Baserow" in saved
    dry = render(
        WeeklyReport(run_date=date(2026, 11, 30), creators=items, more_note="")
    )
    assert "+ 2 more\n" in dry + "\n"
    assert "Baserow" not in dry.split("BLOCKERS")[0]


def test_rutube_title_is_cleaned():
    title = "Смотреть Мишка и Юля на RUTUBE: 1666 подборки видео – онлайн"
    assert display_name(title, "https://rutube.ru/channel/912314/") == "Мишка и Юля"


def test_telegram_posts_link_points_to_the_channel():
    assert readable_url("https://t.me/s/psychoclxn?before=233") == (
        "https://t.me/psychoclxn"
    )
    assert readable_url("https://t.me/psychoclxn") == "https://t.me/psychoclxn"
