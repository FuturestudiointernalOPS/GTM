"""Import accepted Baserow proofs as sourced facts.

A proof is imported only when a human has marked it ``ACCEPTED``. Pending or
refused proofs stay in Baserow for review and never reach the score. The source
and its consultation date are stored first; the fact always points to that
dated snapshot.

The proof identity is stable: row, record, key, source and consultation date.
A replayed row finds its existing fact and does not create a second one. A
value changed on the same proof is refused, because the contract says a
correction is a new proof, not an edit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass, field
from decimal import Decimal

from config import settings
from integrations import postgres, sync_store
from integrations.baserow import BaserowRowClient
from processing import fact_values
from processing.deduplication import normalize_url
from workflows.sync_common import (
    BaserowTables,
    SyncError,
    clean_text,
    error_fields,
    resolve_record_link,
    success_fields,
)

log = logging.getLogger("gtm.sync")

ACCEPTED = "ACCEPTED"
PENDING = "PENDING"
REJECTED = "REJECTED"
CONFLICT = "CONFLICT"


@dataclass
class EvidenceReport:
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.failed


def pull_evidence(
    connection,
    client,
    *,
    database_id=None,
    creators=None,
    buyers=None,
    platforms=None,
    proofs=None,
    max_pages: int = 50,
) -> EvidenceReport:
    """Read the Preuves table and import every accepted, well-formed proof."""
    tables = BaserowTables.resolve(
        client,
        database_id=database_id,
        creators=creators,
        buyers=buyers,
        platforms=platforms,
        proofs=proofs,
    )
    if tables.proofs is None:
        raise SyncError(
            "set BASEROW_TABLE_PROOFS, or set BASEROW_DATABASE_ID so the "
            "Preuves table can be found"
        )

    report = EvidenceReport()
    for row in client.iter_rows(tables.proofs, max_pages=max_pages):
        row_id = _row_id(row)
        if row_id is None:
            report.skipped.append("PROOF:?")
            continue

        label = f"PROOF:{row_id}"
        try:
            _apply_proof(
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
            log.error("%s could not be imported: %s", label, message)
    return report


def _apply_proof(
    connection,
    client,
    *,
    tables: BaserowTables,
    row: dict,
    row_id: int,
    label: str,
    report: EvidenceReport,
) -> None:
    record_id, problem = resolve_record_link(connection, tables, row)
    if problem:
        _reject(connection, client, tables.proofs, row_id, label, problem, report)
        return

    fact_key = clean_text(row.get("fact_key"))
    raw_value = row.get("value")
    proof_level = clean_text(row.get("proof_level")).upper()
    confidence = clean_text(row.get("confidence")).upper()
    review_status = clean_text(row.get("review_status")).upper()
    source_url = clean_text(row.get("source_url"))
    consulted_at = clean_text(row.get("consulted_at"))
    service = clean_text(row.get("service")) or None
    query_used = clean_text(row.get("query_used")) or None
    actor = clean_text(row.get("reviewed_by")) or "baserow"

    try:
        fact_values.validate_proof(proof_level, confidence, review_status)
    except fact_values.FactRejected as error:
        _reject(connection, client, tables.proofs, row_id, label, str(error), report)
        return

    if review_status != ACCEPTED:
        status = PENDING if review_status == PENDING else REJECTED
        message = (
            "preuve en attente de revue"
            if review_status == PENDING
            else f"preuve non importée (review_status={review_status})"
        )
        _defer(
            connection, client, tables.proofs, row_id, label, status, message, report
        )
        return

    if not source_url:
        _reject(
            connection,
            client,
            tables.proofs,
            row_id,
            label,
            "la source de la preuve est vide",
            report,
        )
        return
    if not consulted_at:
        _reject(
            connection,
            client,
            tables.proofs,
            row_id,
            label,
            "la date de consultation est vide",
            report,
        )
        return

    normalized = normalize_url(source_url)
    if normalized is None:
        _reject(
            connection,
            client,
            tables.proofs,
            row_id,
            label,
            f"adresse de source invalide : {source_url!r}",
            report,
        )
        return

    try:
        value_column, value = fact_values.parse_value(fact_key, raw_value)
    except fact_values.FactRejected as error:
        _reject(connection, client, tables.proofs, row_id, label, str(error), report)
        return

    proof_id = _proof_id(row_id, record_id, fact_key, source_url, consulted_at)
    existing = sync_store.load_fact_by_event(connection, proof_id)
    if existing is not None:
        if not _same_fact(existing, value_column, value, proof_level, confidence):
            _reject(
                connection,
                client,
                tables.proofs,
                row_id,
                label,
                "preuve déjà importée avec une autre valeur : "
                "une correction est une nouvelle preuve",
                report,
            )
            return
        connection.rollback()
        _finish(
            client,
            tables.proofs,
            row_id,
            existing,
            label,
            report,
            changed=False,
        )
        return

    source_id = sync_store.upsert_source(
        connection,
        url=source_url,
        normalized_url=normalized,
        kind=service,
    )
    snapshot_id = sync_store.upsert_snapshot(
        connection,
        source_id=source_id,
        consulted_at=consulted_at,
        query_used=query_used,
        service=service,
    )
    sync_store.link_record_source(
        connection,
        record_id=record_id,
        snapshot_id=snapshot_id,
    )
    fact_id = sync_store.insert_fact(
        connection,
        record_id=record_id,
        key=fact_key,
        value_column=value_column,
        value=value,
        proof_level=proof_level,
        confidence=confidence,
        snapshot_id=snapshot_id,
        recorded_by=actor,
        external_event_id=proof_id,
    )
    if fact_id is None:  # a concurrent import won the race
        existing = sync_store.load_fact_by_event(connection, proof_id)
        if existing is None or not _same_fact(
            existing, value_column, value, proof_level, confidence
        ):
            connection.rollback()
            _reject(
                connection,
                client,
                tables.proofs,
                row_id,
                label,
                "la preuve a changé pendant l'import : relancer la passe",
                report,
            )
            return
    else:
        existing = sync_store.load_fact_by_event(connection, proof_id)
        if existing is None:
            existing = {
                "id": fact_id,
                "is_current": True,
                "recorded_at": None,
            }

    connection.commit()
    _finish(
        client,
        tables.proofs,
        row_id,
        existing,
        label,
        report,
        changed=True,
    )


def _finish(
    client,
    table_id: int,
    row_id: int,
    fact: dict,
    label: str,
    report: EvidenceReport,
    *,
    changed: bool,
) -> None:
    fields = {
        "fact_id": str(fact["id"]),
        "is_current": bool(fact.get("is_current", True)),
        "recorded_at": _stamp(fact.get("recorded_at")),
        **success_fields(),
    }
    try:
        client.update_row(table_id, row_id, fields)
    except Exception as error:
        message = _message(error)
        report.failed.append((label, message))
        log.error("%s is stored but not acknowledged: %s", label, message)
        return
    (report.applied if changed else report.skipped).append(label)


def _defer(
    connection,
    client,
    table_id: int | None,
    row_id: int,
    label: str,
    status: str,
    message: str,
    report: EvidenceReport,
) -> None:
    connection.rollback()
    if table_id is not None:
        try:
            client.update_row(
                table_id,
                row_id,
                {
                    **success_fields(),
                    "sync_status": status,
                    "sync_error": message,
                },
            )
        except Exception as error:  # noqa: BLE001 - the review state matters more
            log.warning("could not show the proof state on %s: %s", label, error)
    report.skipped.append(label)


def _reject(
    connection,
    client,
    table_id: int | None,
    row_id: int,
    label: str,
    message: str,
    report: EvidenceReport,
) -> None:
    connection.rollback()
    if table_id is not None:
        try:
            client.update_row(table_id, row_id, error_fields(message))
        except Exception as error:  # noqa: BLE001 - the refusal is the main outcome
            log.warning("could not show the refusal on %s: %s", label, error)
    report.rejected.append((label, message))
    log.warning("%s refused: %s", label, message)


def _same_fact(
    existing: dict,
    value_column: str,
    value,
    proof_level: str,
    confidence: str,
) -> bool:
    stored = existing.get(value_column)
    if value_column == "value_number" and stored is not None:
        try:
            stored = Decimal(stored)
        except Exception:  # noqa: BLE001 - a malformed stored value is not a match
            return False
    return (
        stored == value
        and clean_text(existing.get("proof_level")).upper() == proof_level
        and clean_text(existing.get("confidence")).upper() == confidence
    )


def _proof_id(
    row_id: int,
    record_id: str,
    fact_key: str,
    source_url: str,
    consulted_at: str,
) -> str:
    seed = "|".join((str(row_id), record_id, fact_key, source_url, consulted_at))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"proof:{row_id}:{digest}"


def _stamp(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _row_id(row: dict) -> int | None:
    try:
        return int(row.get("id"))
    except (TypeError, ValueError):
        return None


def _message(error: Exception) -> str:
    text = str(error).strip()
    return text[:500] if text else type(error).__name__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.sync_evidence",
        description="Import accepted Baserow proofs into PostgreSQL.",
    )
    parser.add_argument("--database-id", default=settings.BASEROW_DATABASE_ID)
    parser.add_argument("--creators-table", default=settings.BASEROW_TABLE_CREATORS)
    parser.add_argument("--buyers-table", default=settings.BASEROW_TABLE_BUYERS)
    parser.add_argument("--platforms-table", default=settings.BASEROW_TABLE_PLATFORMS)
    parser.add_argument("--proofs-table", default=settings.BASEROW_TABLE_PROOFS)
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
        report = pull_evidence(
            connection,
            client,
            database_id=args.database_id,
            creators=args.creators_table,
            buyers=args.buyers_table,
            platforms=args.platforms_table,
            proofs=args.proofs_table,
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


def summary(report: EvidenceReport) -> dict:
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
