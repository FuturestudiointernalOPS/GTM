"""Apply the professional contacts written in Baserow to PostgreSQL.

A contact is the one place where a human action must take effect immediately:
an explicit opt-out blocks the fiche on the spot (K-03). This service therefore
upserts the contact, inserts the opt-out event that the database trigger turns
into a workflow transition, and only then acknowledges the Baserow row.

The contact row is never reactivated automatically. If the fiche is already
``OPT_OUT``, an incoming ``ACTIVE`` status is forced back to ``OPT_OUT``: the
most restrictive outcome wins.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass, field

from config import settings
from integrations import postgres, sync_store
from integrations.baserow import BaserowRowClient
from workflows.sync_common import (
    BaserowTables,
    SyncError,
    error_fields,
    link_ids,
    resolve_record_link,
    success_fields,
)

log = logging.getLogger("gtm.sync")

OPT_OUT = "OPT_OUT"
BLOCKED = "BLOCKED"

ROLES = {
    "ADVERTISING_CONTACT",
    "AGENCY",
    "MARKETING",
    "INFLUENCE_PARTNERSHIPS",
    "BRAND",
    "FOUNDER",
    "OTHER",
}
CHANNELS = {"EMAIL", "TELEGRAM", "VK", "FORM", "PHONE", "OTHER"}
STATUSES = {"ACTIVE", "VERIFIED", "OPT_OUT", "BLOCKED"}


@dataclass
class ContactReport:
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.failed


def pull_contacts(
    connection,
    client,
    *,
    database_id=None,
    creators=None,
    buyers=None,
    platforms=None,
    contacts=None,
    max_pages: int = 50,
) -> ContactReport:
    """Read the Contacts table and upsert every valid professional contact."""
    tables = BaserowTables.resolve(
        client,
        database_id=database_id,
        creators=creators,
        buyers=buyers,
        platforms=platforms,
        contacts=contacts,
    )
    if tables.contacts is None:
        raise SyncError(
            "set BASEROW_TABLE_CONTACTS, or set BASEROW_DATABASE_ID so the "
            "Contacts table can be found"
        )

    report = ContactReport()
    for row in client.iter_rows(tables.contacts, max_pages=max_pages):
        row_id = _row_id(row)
        if row_id is None:
            report.skipped.append("CONTACT:?")
            continue

        label = f"CONTACT:{row_id}"
        try:
            _apply_contact(
                connection,
                client,
                tables=tables,
                row=row,
                row_id=row_id,
                label=label,
                report=report,
            )
        except Exception as error:
            connection.rollback()
            message = _message(error)
            report.failed.append((label, message))
            log.error("%s could not be applied: %s", label, message)
    return report


def _apply_contact(
    connection,
    client,
    *,
    tables: BaserowTables,
    row: dict,
    row_id: int,
    label: str,
    report: ContactReport,
) -> None:
    if _is_placeholder(row):
        report.skipped.append(label)
        return

    record_id, problem = _resolve_record(connection, tables, row)
    if problem:
        _reject(connection, client, tables, row_id, label, problem, report)
        return

    role = _text(row.get("role")).upper()
    channel_type = _text(row.get("channel_type")).upper()
    channel_value = _text(row.get("channel_value"))
    status = _text(row.get("status")).upper()
    source_url = _text(row.get("source_url"))
    source_date = _text(row.get("source_date"))
    professional = _bool(row.get("is_professional_public"))

    problem = _validate(
        role=role,
        channel_type=channel_type,
        channel_value=channel_value,
        status=status,
        source_url=source_url,
        source_date=source_date,
        professional=professional,
    )
    if problem:
        _reject(connection, client, tables, row_id, label, problem, report)
        return

    current = sync_store.load_record_status(connection, record_id)
    if current is None:
        _reject(
            connection,
            client,
            tables,
            row_id,
            label,
            f"fiche {record_id} absente de PostgreSQL",
            report,
        )
        return

    if current == OPT_OUT and status != OPT_OUT:
        status = OPT_OUT
        log.warning("%s is forced to OPT_OUT: the fiche is already opted out", label)

    contact_id = sync_store.upsert_contact(
        connection,
        record_id=record_id,
        role=role,
        person_name=_text(row.get("person_name")) or None,
        channel_type=channel_type,
        channel_value=channel_value,
        is_professional_public=bool(professional),
        source_url=source_url,
        source_date=source_date,
        status=status,
        notes=_text(row.get("notes")) or None,
    )

    if status == OPT_OUT:
        sync_store.insert_opt_out_event(
            connection,
            contact_id=contact_id,
            record_id=record_id,
            actor=_text(row.get("assigned_to")) or "baserow",
            notes=_text(row.get("notes")) or None,
            external_event_id=f"{_event_id(row)}:OPT_OUT",
        )

    connection.commit()

    try:
        client.update_row(tables.contacts, row_id, success_fields())
    except Exception as error:
        message = _message(error)
        report.failed.append((label, message))
        log.error("%s is stored but not acknowledged: %s", label, message)
        return

    report.applied.append(label)


def _resolve_record(
    connection, tables: BaserowTables, row: dict
) -> tuple[str, str | None]:
    return resolve_record_link(connection, tables, row)


def _is_placeholder(row: dict) -> bool:
    """A default Baserow row has no value and no linked fiche."""
    return (
        not _text(row.get("channel_value"))
        and not _text(row.get("record_type"))
        and not link_ids(row.get("creator"))
        and not link_ids(row.get("acheteur"))
    )


def _validate(
    *,
    role: str,
    channel_type: str,
    channel_value: str,
    status: str,
    source_url: str,
    source_date: str,
    professional,
) -> str | None:
    if role not in ROLES:
        return f"rôle inconnu : {role or 'vide'}"
    if channel_type not in CHANNELS:
        return f"canal inconnu : {channel_type or 'vide'}"
    if status not in STATUSES:
        return f"statut de contact inconnu : {status or 'vide'}"
    if not channel_value:
        return "la valeur du contact est vide"
    if not source_url:
        return "la source du contact est vide"
    if not source_date:
        return "la date de la source est vide"
    if professional is None:
        return "is_professional_public est absent"
    if not professional and status not in {BLOCKED, OPT_OUT}:
        return "un contact non professionnel et non public est refusé (K-01)"
    return None


def _reject(
    connection,
    client,
    tables: BaserowTables,
    row_id: int,
    label: str,
    message: str,
    report: ContactReport,
) -> None:
    connection.rollback()
    try:
        client.update_row(tables.contacts, row_id, error_fields(message))
    except Exception as error:  # noqa: BLE001 - the refusal is the main outcome
        log.warning("could not show the refusal on %s: %s", label, error)

    report.rejected.append((label, message))
    log.warning("%s refused: %s", label, message)


def _event_id(row: dict) -> str:
    seed = "|".join(
        [
            str(row.get("id") or ""),
            _text(row.get("record_type")),
            ",".join(str(value) for value in link_ids(row.get("creator"))),
            ",".join(str(value) for value in link_ids(row.get("acheteur"))),
            _text(row.get("role")),
            _text(row.get("person_name")),
            _text(row.get("channel_type")),
            _text(row.get("channel_value")),
            str(row.get("is_professional_public")),
            _text(row.get("source_url")),
            _text(row.get("source_date")),
            _text(row.get("status")),
            _text(row.get("notes")),
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"contact:{row.get('id')}:{digest}"


def _row_id(row: dict) -> int | None:
    try:
        return int(row.get("id"))
    except (TypeError, ValueError):
        return None


def _bool(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("value", "")
    return " ".join(str(value).split())


def _message(error: Exception) -> str:
    text = str(error).strip()
    return text[:500] if text else type(error).__name__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.sync_contacts",
        description="Apply Baserow contacts to PostgreSQL.",
    )
    parser.add_argument("--database-id", default=settings.BASEROW_DATABASE_ID)
    parser.add_argument("--creators-table", default=settings.BASEROW_TABLE_CREATORS)
    parser.add_argument("--buyers-table", default=settings.BASEROW_TABLE_BUYERS)
    parser.add_argument("--platforms-table", default=settings.BASEROW_TABLE_PLATFORMS)
    parser.add_argument("--contacts-table", default=settings.BASEROW_TABLE_CONTACTS)
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    client = None
    try:
        client = BaserowRowClient()
        connection = postgres.connect()
    except Exception as error:
        if client is not None:
            client.close()
        log.error("%s", error)
        return 2

    try:
        report = pull_contacts(
            connection,
            client,
            database_id=args.database_id,
            creators=args.creators_table,
            buyers=args.buyers_table,
            platforms=args.platforms_table,
            contacts=args.contacts_table,
            max_pages=args.max_pages,
        )
    except Exception as error:
        connection.rollback()
        log.error("%s", error)
        return 2
    finally:
        connection.close()
        client.close()

    print(json.dumps(summary(report), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


def summary(report: ContactReport) -> dict:
    return {
        "ok": report.ok,
        "applied": list(report.applied),
        "skipped": list(report.skipped),
        "rejected": [
            {"entity": entity, "error": error} for entity, error in report.rejected
        ],
        "failed": [
            {"entity": entity, "error": error} for entity, error in report.failed
        ],
    }


if __name__ == "__main__":
    sys.exit(main())
