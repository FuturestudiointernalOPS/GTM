"""Apply human review actions written in Baserow back to PostgreSQL.

Baserow sends an intention through ``review_action``; PostgreSQL owns the
status. This service reads the rows periodically, deduplicates an event by its
fingerprint, validates the transition, writes ``review_request`` and
``workflow_event``, then acknowledges the row in Baserow.

Why the acknowledgement is a separate step: a database commit must not be lost
because Baserow is briefly unavailable. The event stays pending until the row
is marked processed, so the next pass finishes the acknowledgement without
replaying the transition.

Examples::

    python -m workflows.sync_pull
    python -m workflows.sync_pull --max-pages 5
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
from processing import review_actions
from workflows.sync_common import BaserowTables, error_fields, success_fields

log = logging.getLogger("gtm.sync")

CREATOR = "CREATOR"
BUYER = "BUYER"
PENDING = "PENDING"
APPLIED = "APPLIED"
REJECTED = "REJECTED"


@dataclass
class PullReport:
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.failed


def pull_actions(
    connection,
    client,
    *,
    database_id=None,
    creators=None,
    buyers=None,
    platforms=None,
    max_pages: int = 50,
) -> PullReport:
    """Read both fiche tables and apply every pending human action."""
    tables = BaserowTables.resolve(
        client,
        database_id=database_id,
        creators=creators,
        buyers=buyers,
        platforms=platforms,
    )

    report = PullReport()
    for kind, table_id in (
        (CREATOR, tables.creators),
        (BUYER, tables.buyers),
    ):
        for row in client.iter_rows(table_id, max_pages=max_pages):
            action = _action(row)
            if not action or action == "NONE":
                continue

            label = f"{kind}:{_text(row.get('record_id'))}:{action}"
            try:
                _apply_row(
                    connection,
                    client,
                    kind=kind,
                    table_id=table_id,
                    row=row,
                    label=label,
                    report=report,
                )
            except Exception as error:
                connection.rollback()
                message = _message(error)
                report.failed.append((label, message))
                log.error("%s could not be applied: %s", label, message)
    return report


def _apply_row(
    connection,
    client,
    *,
    kind: str,
    table_id: int,
    row: dict,
    label: str,
    report: PullReport,
) -> None:
    row_id = _row_id(row)
    if row_id is None:
        report.skipped.append(label)
        log.warning("a %s row has no id; its action is ignored", kind)
        return

    record_id = _text(row.get("record_id"))
    action = _action(row)
    note = _text(row.get("review_action_note"))
    requested_by = _text(row.get("assigned_to"))
    external_event_id = _event_id(table_id, row)

    state = sync_store.store_event(
        connection,
        external_event_id=external_event_id,
        table_id=table_id,
        row_id=row_id,
        event_type="REVIEW_ACTION",
        payload=row,
    )
    if state.status != PENDING:
        connection.commit()
        report.skipped.append(label)
        return

    if not record_id:
        _reject(
            connection,
            client,
            state=state,
            table_id=table_id,
            row_id=row_id,
            label=label,
            message="record_id absent de la ligne Baserow",
            report=report,
        )
        return

    record = sync_store.load_record_for_action(connection, record_id)
    if record is None:
        _reject(
            connection,
            client,
            state=state,
            table_id=table_id,
            row_id=row_id,
            label=label,
            message=f"fiche {record_id} absente de PostgreSQL",
            report=report,
        )
        return

    try:
        decision = review_actions.decide(
            action,
            kind=record["kind"],
            current=record["workflow_status"],
            note=note,
            requested_by=requested_by,
        )
    except review_actions.ReviewRejected as error:
        _reject(
            connection,
            client,
            state=state,
            table_id=table_id,
            row_id=row_id,
            label=label,
            message=str(error),
            report=report,
        )
        return

    request_id = sync_store.insert_review_request(
        connection,
        record_id=record_id,
        action=action,
        note=decision.justification,
        requested_by=decision.actor,
        external_event_id=external_event_id,
    )

    # A previous attempt may have committed the transition but failed to
    # acknowledge Baserow. Reuse that journal entry instead of asking for the
    # same move again, which would look like a no-op now.
    workflow_event_id = sync_store.find_workflow_event(connection, external_event_id)
    if workflow_event_id is None and decision.target is not None:
        workflow_event_id = sync_store.transition_for_review(
            connection,
            record_id=record_id,
            target=decision.target,
            justification=decision.justification,
            actor=decision.actor,
            criteria_version=record.get("criteria_version"),
            external_event_id=external_event_id,
            payload={
                "source": "baserow",
                "action": action,
                "note": note,
                "table_id": table_id,
                "row_id": row_id,
            },
        )

    sync_store.finish_review_request(connection, request_id, workflow_event_id)
    connection.commit()

    _finish(
        connection,
        client,
        state=state,
        table_id=table_id,
        row_id=row_id,
        label=label,
        report=report,
    )


def _reject(
    connection,
    client,
    *,
    state: sync_store.EventState,
    table_id: int,
    row_id: int,
    label: str,
    message: str,
    report: PullReport,
) -> None:
    """Show the refusal in Baserow, then keep the event as refused."""
    try:
        client.update_row(
            table_id,
            row_id,
            {"review_action_processed": False, **error_fields(message)},
        )
    except Exception as error:  # noqa: BLE001 - the refusal is the main outcome
        log.warning("could not show the refusal on %s: %s", label, error)

    sync_store.mark_event(connection, state.id, REJECTED, message)
    connection.commit()
    report.rejected.append((label, message))
    log.warning("%s refused: %s", label, message)


def _finish(
    connection,
    client,
    *,
    state: sync_store.EventState,
    table_id: int,
    row_id: int,
    label: str,
    report: PullReport,
) -> None:
    """Acknowledge the row in Baserow; keep the event pending if that fails."""
    try:
        client.update_row(
            table_id,
            row_id,
            {"review_action_processed": True, **success_fields()},
        )
    except Exception as error:  # noqa: BLE001 - the database move is committed
        message = _message(error)
        try:
            sync_store.note_event_error(connection, state.id, message)
            connection.commit()
        except Exception:
            connection.rollback()
        report.failed.append((label, message))
        log.error("%s is applied but not acknowledged: %s", label, message)
        return

    sync_store.mark_event(connection, state.id, APPLIED)
    connection.commit()
    report.applied.append(label)


def _action(row: dict) -> str:
    value = row.get("review_action")
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return str(value or "").strip().upper()


def _event_id(table_id: int, row: dict) -> str:
    seed = "|".join(
        str(part or "")
        for part in (
            table_id,
            row.get("id"),
            row.get("record_id"),
            row.get("review_action"),
            row.get("review_action_note"),
            row.get("review_action_at"),
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"baserow:{table_id}:{row.get('id')}:{digest}"


def _row_id(row: dict) -> int | None:
    value = row.get("id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
        prog="python -m workflows.sync_pull",
        description="Apply Baserow review actions to PostgreSQL.",
    )
    parser.add_argument("--database-id", default=settings.BASEROW_DATABASE_ID)
    parser.add_argument("--creators-table", default=settings.BASEROW_TABLE_CREATORS)
    parser.add_argument("--buyers-table", default=settings.BASEROW_TABLE_BUYERS)
    parser.add_argument("--platforms-table", default=settings.BASEROW_TABLE_PLATFORMS)
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
        report = pull_actions(
            connection,
            client,
            database_id=args.database_id,
            creators=args.creators_table,
            buyers=args.buyers_table,
            platforms=args.platforms_table,
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


def summary(report: PullReport) -> dict:
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
