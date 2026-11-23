"""Outreach drafts for every scored target, never sent to the target.

The model writes one short message per recipient. The draft is addressed to the
public contact that was verified on the page, and the programme text is passed
along when the company publishes one. Nothing leaves the machine for the target:
the draft is sent to the supervisor for approval, and a human decides.

A target without a verified contact, or without a submission channel, gets no
draft: there is nowhere to send it, and inventing an address would break the
rules that govern contact collection.
"""

from __future__ import annotations

from dataclasses import dataclass

from workflows.record_flow import BUYER, RecordScore
from workflows.telegram_report import display_name, platform_of

DEFAULT_MAX_DRAFTS = 20


@dataclass(frozen=True)
class Outreach:
    """One target's draft, or why it could not be written."""

    recipient: dict
    draft: dict | None = None
    error: str | None = None

    @property
    def message(self) -> str:
        return ((self.draft or {}).get("message") or "").strip()

    @property
    def channel(self) -> str:
        return ((self.draft or {}).get("channel") or "message").strip()


def build_drafts(
    records,
    provider,
    *,
    max_drafts: int | None = DEFAULT_MAX_DRAFTS,
) -> tuple[Outreach, ...]:
    """Write one draft per record that has a verified way to be reached."""
    limit = None if max_drafts in (None, 0) else max(1, int(max_drafts))
    results: list[Outreach] = []
    written = 0

    for record in records:
        if not record.page_excerpt:
            continue
        result = build_draft(record, provider)
        results.append(result)
        if result.message:
            written += 1
            if limit is not None and written >= limit:
                break
    return tuple(results)


def build_draft(record: RecordScore, provider) -> Outreach:
    """Ask the model for one message, using only the verified contact data."""
    if not record.page_excerpt:
        return Outreach(recipient=_recipient(record), error="page sans texte lisible")
    if not _reachable(record):
        return Outreach(
            recipient=_recipient(record),
            error="aucun contact public vérifié ni moyen de soumission",
        )

    try:
        draft = provider.generate_outreach(_payload(record))
    except Exception as error:  # noqa: BLE001 - one failed draft must not stop the run
        return Outreach(
            recipient=_recipient(record),
            error=f"génération impossible : {error}",
        )

    if not (draft.get("message") or "").strip():
        return Outreach(
            recipient=_recipient(record),
            error="le modèle n'a trouvé aucun élément vérifié : brouillon vide",
        )
    return Outreach(recipient=_recipient(record), draft=draft)


def validation_text(results) -> str | None:
    """All drafts waiting for approval, as one readable text for the supervisor."""
    blocks: list[str] = []
    number = 0
    for result in results:
        if not result.message:
            continue
        number += 1
        target = result.recipient
        lines = [
            f"BROUILLON {number} — {target.get('name')} "
            f"({target.get('platform') or 'entreprise'})",
            f"Page : {target.get('url')}",
        ]
        if target.get("contacts"):
            lines.append("Contacts : " + " | ".join(target["contacts"]))
        if target.get("programs"):
            lines.append("Programme : " + " | ".join(target["programs"]))
        if result.draft.get("personalisation"):
            lines.append(f"Élément cité : {result.draft['personalisation']}")
        lines += [
            "",
            "Message proposé :",
            result.message,
        ]
        blocks.append("\n".join(lines))

    if not blocks:
        return None
    return (
        "BROUILLONS À VALIDER — aucun envoi automatique aux cibles\n\n"
        + "\n\n".join(blocks)
    )


def _payload(record: RecordScore) -> dict:
    return {
        "recipient_kind": "creator" if record.kind != BUYER else "buyer",
        "name": _name(record),
        "url": record.source_url,
        "platform": platform_of(record.source_url or ""),
        "public_page_excerpt": record.page_excerpt,
        "contacts": [
            {
                "role": contact.role_label,
                "channel_type": contact.channel_label,
                "value": contact.channel_value,
                "description": contact.description,
            }
            for contact in record.contacts
        ],
        "programs": [
            {
                "title": program.title,
                "description": program.description,
                "submission_method": program.submission_method,
                "submission_url": program.submission_url,
            }
            for program in record.programs
        ],
    }


def _recipient(record: RecordScore) -> dict:
    return {
        "name": _name(record),
        "url": record.source_url,
        "platform": platform_of(record.source_url or ""),
        "contacts": [contact.summary() for contact in record.contacts],
        "programs": [program.summary() for program in record.programs],
    }


def _name(record: RecordScore) -> str:
    if record.legal_name:
        return record.legal_name
    return display_name(record.title, record.source_url or "")


def _reachable(record: RecordScore) -> bool:
    if record.contacts:
        return True
    return any(
        program.submission_method or program.submission_url
        for program in record.programs
    )
