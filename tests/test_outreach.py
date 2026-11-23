"""Tests for outreach drafts and the full-run report. No network."""

from fractions import Fraction

from processing.contacts import BuyerProgram, PublicContact
from processing.scoring import PRESELECTED, TO_REVIEW, ScoreResult
from workflows import outreach, run_report
from workflows.record_flow import BUYER, CREATOR, RecordScore
from workflows.record_loop import LoopResult
from workflows.weekly_run import WeeklyRun

READ = "2026-11-23T12:00:00+00:00"


class FakeProvider:
    def __init__(self):
        self.payload = None

    def generate_outreach(self, data):
        self.payload = data
        return {
            "channel": "email",
            "subject": "Кампания",
            "message": "Здравствуйте! Мы делаем кампании с создателями.",
            "personalisation": "press@studio.ru",
        }


def score(value=79, proposal=PRESELECTED, *, lines=(), incomplete=False):
    return ScoreResult(
        proposal=proposal,
        score=value,
        total_exact=Fraction(value),
        lower_bound=Fraction(value),
        upper_bound=Fraction(value),
        incomplete=incomplete,
        lines=tuple(lines),
    )


def record(*, kind=CREATOR, contacts=(), programs=(), url="https://studio.example"):
    return RecordScore(
        kind=kind,
        result=score(),
        record_id="rec-1",
        source_url=url,
        title="Studio",
        page_excerpt="Мы издатель игр и платим создателям.",
        read_at=READ,
        contacts=tuple(contacts),
        programs=tuple(programs),
    )


def contact():
    return PublicContact(
        role="INFLUENCE_PARTNERSHIPS",
        channel_type="EMAIL",
        channel_value="press@studio.ru",
        description="partenariats",
        quote="По вопросам рекламы: press@studio.ru",
    )


def test_a_draft_uses_the_verified_contact():
    provider = FakeProvider()
    (result,) = outreach.build_drafts([record(contacts=(contact(),))], provider)

    assert result.message.startswith("Здравствуйте")
    assert result.channel == "email"
    assert provider.payload["contacts"][0]["value"] == "press@studio.ru"
    assert provider.payload["recipient_kind"] == "creator"


def test_a_target_without_contact_or_programme_gets_no_draft():
    (result,) = outreach.build_drafts([record()], FakeProvider())

    assert result.message == ""
    assert "aucun contact" in result.error


def test_a_programme_submission_is_enough_to_write():
    program = BuyerProgram(
        description="Nous payons des créateurs.",
        submission_method="formulaire",
        submission_url="https://studio.example/creators",
        quote="Подать заявку можно через форму",
    )
    (result,) = outreach.build_drafts(
        [record(kind=BUYER, programs=(program,))], FakeProvider()
    )

    assert result.message
    assert result.recipient["programs"]


def test_the_draft_cap_is_applied():
    records = [record(), record(url="https://other.example")]
    records = [replace_record(item, contacts=(contact(),)) for item in records]

    assert len(outreach.build_drafts(records, FakeProvider(), max_drafts=1)) == 1


def test_validation_text_lists_every_draft():
    results = outreach.build_drafts(
        [
            replace_record(record(), contacts=(contact(),)),
            replace_record(
                record(kind=BUYER, url="https://buyer.example"),
                contacts=(contact(),),
            ),
        ],
        FakeProvider(),
    )

    text = outreach.validation_text(results)

    assert text.count("BROUILLON ") == 2
    assert "aucun envoi automatique" in text
    assert "press@studio.ru" in text


def test_the_run_report_shows_scores_contacts_and_blockers():
    content = contact()
    program = BuyerProgram(
        description="Programme créateurs",
        submission_method="formulaire",
        submission_url="https://studio.example/creators",
        quote="Подать заявку можно через форму",
    )
    creator = replace_record(
        record(contacts=(content,)),
        result=score(72, TO_REVIEW, incomplete=True),
    )
    buyer = record(
        kind=BUYER,
        contacts=(content,),
        programs=(program,),
        url="https://buyer.example",
    )
    run = WeeklyRun(
        collected_at=READ,
        fresh_pages=2,
        scores=LoopResult(scored=(creator, buyer)),
        written=("run-1", "run-2"),
        write_failed=(("rec-3", "identité absente"),),
        eligibility_skipped=("rec-1",),
    )
    drafts = outreach.build_drafts((creator, buyer), FakeProvider())
    report = run_report.build_report(run, drafts)

    assert len(report.creators) == 1
    assert len(report.buyers) == 1
    assert report.creators[0].score == 72
    assert report.creators[0].contacts
    assert report.buyers[0].programs
    assert report.status == "PARTIAL"
    assert any("identité absente" in item for item in report.blockers)
    assert len(report.drafts) == 2


def replace_record(item: RecordScore, **changes) -> RecordScore:
    from dataclasses import replace

    return replace(item, **changes)
