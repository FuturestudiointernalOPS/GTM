"""Push PostgreSQL fiches to Baserow, one short outbox batch at a time.

The database remains the source of truth. This service reads a pending change,
loads the current fiche, translates only the fields the database owns, and
creates or updates the corresponding Baserow row. A human-owned field is never
overwritten, and a fiche whose fingerprint did not change is not sent again.

Why a separate command: a weekly run and a synchronization worker have
different failure modes. The run must finish a collection; the worker must be
safe to rerun at any time, at any frequency, without creating a second row.

Examples::

    python -m workflows.sync_push --limit 50
    python -m workflows.sync_push --max-attempts 3 --retry-seconds 60
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from config import settings
from integrations import postgres, sync_store
from integrations.baserow import BaserowRowClient
from processing import baserow_mapping

log = logging.getLogger("gtm.sync")

CREATOR = "CREATOR"
BUYER = "BUYER"
PLATFORM = "PLATFORM"


class SyncError(RuntimeError):
    """The service cannot start: a setting or a table is missing."""


@dataclass(frozen=True)
class BaserowTables:
    creators: int
    buyers: int
    platforms: int

    @classmethod
    def resolve(
        cls,
        client,
        *,
        database_id=None,
        creators=None,
        buyers=None,
        platforms=None,
    ) -> "BaserowTables":
        """Use configured table ids, or discover them through the schema API."""
        if creators and buyers and platforms:
            return cls(
                creators=_table_id("creators", creators),
                buyers=_table_id("buyers", buyers),
                platforms=_table_id("platforms", platforms),
            )

        if not database_id:
            raise SyncError(
                "set BASEROW_TABLE_CREATORS, BASEROW_TABLE_BUYERS and "
                "BASEROW_TABLE_PLATFORMS, or set BASEROW_DATABASE_ID"
            )

        try:
            listed = client.list_tables(int(database_id))
        except (TypeError, ValueError) as error:
            raise SyncError(f"invalid Baserow database id: {database_id!r}") from error

        by_name = {str(table["name"]): int(table["id"]) for table in listed}
        missing = [
            name
            for name in (
                baserow_mapping.CREATOR_TABLE,
                baserow_mapping.BUYER_TABLE,
                baserow_mapping.PLATFORM_TABLE,
            )
            if name not in by_name
        ]
        if missing:
            raise SyncError(
                "Baserow is missing these tables: " + ", ".join(sorted(missing))
            )

        return cls(
            creators=by_name[baserow_mapping.CREATOR_TABLE],
            buyers=by_name[baserow_mapping.BUYER_TABLE],
            platforms=by_name[baserow_mapping.PLATFORM_TABLE],
        )


@dataclass
class PushReport:
    platforms: list[str] = field(default_factory=list)
    pushed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def push_outbox(
    connection,
    client,
    *,
    database_id=None,
    creators=None,
    buyers=None,
    platforms=None,
    limit: int = 50,
    max_attempts: int = 5,
    retry_seconds: int = 300,
    lease_seconds: int = 600,
    schema: dict | None = None,
) -> PushReport:
    """Push reference platforms, then every leased fiche change.

    The caller owns the connection but not the transaction: progress is
    committed after each item, so a crash loses at most one item, which the
    lease makes retryable.
    """
    tables = BaserowTables.resolve(
        client,
        database_id=database_id,
        creators=creators,
        buyers=buyers,
        platforms=platforms,
    )

    report = PushReport()
    max_attempts = max(1, max_attempts)
    retry_seconds = max(0, retry_seconds)
    platform_row_ids = _push_platforms(connection, client, tables, report, schema)

    items = sync_store.claim_outbox(
        connection,
        limit=max(1, limit),
        lease_seconds=max(1, lease_seconds),
    )
    for item in items:
        _process_item(
            connection,
            client,
            tables,
            item,
            platform_row_ids,
            report,
            max_attempts=max_attempts,
            retry_seconds=retry_seconds,
            schema=schema,
        )
    return report


def _push_platforms(connection, client, tables, report, schema) -> dict[str, int]:
    """Keep the reference table in step, and return name -> Baserow row id."""
    row_ids: dict[str, int] = {}
    for platform in sync_store.load_platforms(connection):
        name = str(platform.get("name") or "")
        entity_id = str(platform.get("id"))
        payload = baserow_mapping.build_platform_row(platform, schema=schema)
        try:
            row_id, changed = _upsert(
                connection,
                client,
                table_id=tables.platforms,
                entity_type=PLATFORM,
                entity_id=entity_id,
                payload=payload,
                key_field="platform_id",
                key_value=entity_id,
                with_sync_fields=False,
            )
        except Exception as error:
            connection.rollback()
            message = _message(error)
            report.failed.append((f"{PLATFORM}:{name}", message))
            log.error("platform %s could not be pushed: %s", name, message)
            continue

        connection.commit()
        row_ids[name] = row_id
        if changed:
            report.platforms.append(name)
    return row_ids


def _process_item(
    connection,
    client,
    tables,
    item: sync_store.OutboxItem,
    platform_row_ids,
    report,
    *,
    max_attempts: int,
    retry_seconds: int,
    schema,
) -> None:
    label = f"{item.entity_type}:{item.entity_id}"

    if item.entity_type == CREATOR:
        table_id = tables.creators
    elif item.entity_type == BUYER:
        table_id = tables.buyers
    else:
        _fail(
            connection,
            item,
            f"unsupported entity type: {item.entity_type}",
            max_attempts=max_attempts,
            retry_seconds=retry_seconds,
        )
        report.failed.append((label, "unsupported entity type"))
        return

    try:
        fiche = sync_store.load_fiche(connection, item.entity_type, item.entity_id)
        if fiche is None:
            sync_store.mark_processed(connection, item.id)
            connection.commit()
            report.skipped.append(label)
            return

        if item.entity_type == CREATOR:
            payload = baserow_mapping.build_creator_row(
                fiche, platform_row_ids=platform_row_ids, schema=schema
            )
        else:
            payload = baserow_mapping.build_buyer_row(fiche, schema=schema)

        _, changed = _upsert(
            connection,
            client,
            table_id=table_id,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            payload=payload,
            key_field="record_id",
            key_value=item.entity_id,
            with_sync_fields=True,
        )
        sync_store.mark_processed(connection, item.id)
        connection.commit()
        (report.pushed if changed else report.skipped).append(label)
    except Exception as error:
        connection.rollback()
        message = _message(error)
        _report_error(
            connection,
            client,
            table_id=table_id,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            key_field="record_id",
            key_value=item.entity_id,
            message=message,
        )
        _fail(
            connection,
            item,
            message,
            max_attempts=max_attempts,
            retry_seconds=retry_seconds,
        )
        report.failed.append((label, message))
        log.error("%s could not be pushed: %s", label, message)


def _upsert(
    connection,
    client,
    *,
    table_id: int,
    entity_type: str,
    entity_id: str,
    payload: dict,
    key_field: str,
    key_value: str,
    with_sync_fields: bool,
) -> tuple[int, bool]:
    """Create or update one row, and remember which row it became.

    The business fingerprint is computed before the synchronization fields are
    added, so a successful push does not make the next one look different.
    """
    fingerprint = baserow_mapping.payload_hash(payload)
    link = sync_store.get_link(connection, entity_type, entity_id, table_id)

    if link is not None:
        if link.sync_hash == fingerprint:
            return link.row_id, False
        client.update_row(
            table_id, link.row_id, _write_fields(payload, with_sync_fields)
        )
        row_id = link.row_id
    else:
        existing = client.find_row(table_id, key_field, key_value)
        if existing is None:
            created = client.create_row(
                table_id, _write_fields(payload, with_sync_fields)
            )
            row_id = int(created["id"])
        else:
            row_id = int(existing["id"])
            client.update_row(
                table_id, row_id, _write_fields(payload, with_sync_fields)
            )

    sync_store.save_link(
        connection,
        entity_type=entity_type,
        entity_id=entity_id,
        table_id=table_id,
        row_id=row_id,
        sync_hash=fingerprint,
    )
    return row_id, True


def _report_error(
    connection,
    client,
    *,
    table_id: int,
    entity_type: str,
    entity_id: str,
    key_field: str,
    key_value: str,
    message: str,
) -> None:
    """Try to show the failure on the fiche, without hiding the first error."""
    try:
        link = sync_store.get_link(connection, entity_type, entity_id, table_id)
        row_id = link.row_id if link else None
        if row_id is None:
            existing = client.find_row(table_id, key_field, key_value)
            if existing is not None:
                row_id = int(existing["id"])
        if row_id is not None:
            client.update_row(table_id, row_id, _error_fields(message))
    except Exception as report_error:  # noqa: BLE001 - the first error matters more
        log.warning(
            "could not display the sync error for %s: %s", entity_id, report_error
        )


def _fail(
    connection,
    item: sync_store.OutboxItem,
    message: str,
    *,
    max_attempts: int,
    retry_seconds: int,
) -> None:
    sync_store.mark_failed(
        connection,
        item.id,
        message,
        max_attempts=max_attempts,
        retry_seconds=retry_seconds,
    )
    connection.commit()


def _write_fields(payload: dict, with_sync_fields: bool) -> dict:
    if not with_sync_fields:
        return dict(payload)
    return {**payload, **_success_fields()}


def _success_fields() -> dict:
    return {
        "sync_status": "SYNCED",
        "sync_error": None,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
    }


def _error_fields(message: str) -> dict:
    return {"sync_status": "ERROR", "sync_error": message[:500]}


def _table_id(name: str, value) -> int:
    try:
        table_id = int(value)
    except (TypeError, ValueError) as error:
        raise SyncError(f"invalid Baserow table id for {name}: {value!r}") from error
    if table_id <= 0:
        raise SyncError(f"invalid Baserow table id for {name}: {value!r}")
    return table_id


def _message(error: Exception) -> str:
    text = str(error).strip()
    return text[:500] if text else type(error).__name__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.sync_push",
        description="Push pending PostgreSQL fiches to Baserow.",
    )
    parser.add_argument("--database-id", default=settings.BASEROW_DATABASE_ID)
    parser.add_argument("--creators-table", default=settings.BASEROW_TABLE_CREATORS)
    parser.add_argument("--buyers-table", default=settings.BASEROW_TABLE_BUYERS)
    parser.add_argument("--platforms-table", default=settings.BASEROW_TABLE_PLATFORMS)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--retry-seconds", type=int, default=300)
    parser.add_argument("--lease-seconds", type=int, default=600)
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
        report = push_outbox(
            connection,
            client,
            database_id=args.database_id,
            creators=args.creators_table,
            buyers=args.buyers_table,
            platforms=args.platforms_table,
            limit=args.limit,
            max_attempts=args.max_attempts,
            retry_seconds=args.retry_seconds,
            lease_seconds=args.lease_seconds,
        )
    except Exception as error:
        connection.rollback()
        log.error("%s", error)
        return 2
    finally:
        connection.close()
        client.close()

    print(json.dumps(summary(report), ensure_ascii=False, indent=2))
    return 1 if report.failed else 0


def summary(report: PushReport) -> dict:
    return {
        "ok": report.ok,
        "platforms": list(report.platforms),
        "pushed": list(report.pushed),
        "skipped": list(report.skipped),
        "failed": [
            {"entity": entity, "error": error} for entity, error in report.failed
        ],
    }


if __name__ == "__main__":
    sys.exit(main())
