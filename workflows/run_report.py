"""Turn one weekly run into the Playbook report the supervisor already reads.

The report is built from the scores that were actually computed, not from a
sample. Missing data stays visible: an unknown criterion is named, a failed
write is listed, and a target without a verified contact is reported as a
blocker instead of receiving an invented address.
"""

from __future__ import annotations

from datetime import UTC, datetime

from workflows.telegram_report import (
    Candidate,
    Draft,
    Target,
    WeeklyReport,
    display_name,
    platform_of,
)

CREATOR = "CREATOR"
BUYER = "BUYER"


def build_report(run, outreaches=(), *, drafts_requested: bool = False) -> WeeklyReport:
    """Build the report from the run's scored records and drafted messages."""
    records = list(run.scores.scored)
    creators = [_candidate(record) for record in records if record.kind == CREATOR]
    buyers = [_candidate(record) for record in records if record.kind == BUYER]
    refs = _refs(creators, buyers)

    drafts = tuple(
        Draft(
            refs.get(outreach.recipient.get("url") or "", "—"),
            outreach.recipient.get("name") or "—",
            outreach.channel,
        )
        for outreach in outreaches
        if outreach.message
    )

    blockers = _blockers(run, outreaches)
    if not drafts_requested:
        blockers.append("brouillons non demandés (ajouter --send-draft)")
    now = datetime.now(UTC)
    return WeeklyReport(
        run_date=now.date(),
        status="PARTIAL" if (run.write_failed or run.scores.failed) else "OK",
        finished_at=f"{now:%H:%M} UTC",
        funnel=(
            Target("Creators found", len(creators)),
            Target("Buyers found", len(buyers)),
            Target("Scored", len(records)),
            Target("Written", len(run.written)),
            Target("Drafts", len(drafts)),
        ),
        creators=tuple(creators),
        buyers=tuple(buyers),
        blockers=tuple(blockers),
        drafts=drafts,
        draft_note=("Le texte complet est envoyé pour validation, jamais à la cible.",),
    )


def _candidate(record) -> Candidate:
    url = record.source_url or ""
    return Candidate(
        name=record.legal_name or display_name(record.title, url),
        url=url,
        platform=platform_of(url),
        score=record.result.score,
        why=_why(record),
        contacts=tuple(contact.summary() for contact in record.contacts),
        programs=tuple(program.summary() for program in record.programs),
    )


def _why(record) -> str:
    result = record.result
    if result.score is None:
        return f"{result.proposal} — {result.reason or 'non noté'}"
    unknown = [line.criterion for line in result.lines if line.points is None]
    if unknown:
        return f"{result.proposal} — inconnu : {', '.join(unknown)}"
    return result.proposal


def _refs(creators, buyers) -> dict[str, str]:
    refs: dict[str, str] = {}
    for prefix, items in (("C", creators), ("B", buyers)):
        for index, item in enumerate(items, start=1):
            if item.url:
                refs[item.url] = f"{prefix}{index}"
    return refs


def _blockers(run, outreaches) -> list[str]:
    blockers: list[str] = []
    for record_id, error in run.scores.failed:
        blockers.append(f"score {record_id}: {error}")
    for record_id, error in run.write_failed:
        blockers.append(f"écriture {record_id}: {error}")
    if run.eligibility_skipped:
        blockers.append(
            f"{len(run.eligibility_skipped)} fiche(s) sans vérification réglementaire"
        )
    for outreach in outreaches:
        if outreach.error:
            blockers.append(
                f"brouillon {outreach.recipient.get('name') or '?'}: {outreach.error}"
            )
    return blockers[:10]
