"""Import the labelled advertisements collected in Baserow into PostgreSQL.

The advertisement row is raw collection data. It is imported while its
validation status is ``DRAFT`` or ``SUBMITTED``; once a row is imported, an
edit is refused because the contract says a correction is a new row.

The INN and OGRN control digits are computed here, so Baserow can display the
completeness formula. The buyer link is not read: it is PostgreSQL-owned and is
filled later by the buyer matching step. Creator links are read, because the
same advertisement feeds both filons.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field

from config import settings
from integrations import postgres, sync_store
from integrations.baserow import BaserowRowClient
from processing.deduplication import normalize_url
from processing.russian_ids import is_valid_inn, is_valid_ogrn
from workflows.sync_common import (
    BaserowTables,
    SyncError,
    clean_text,
    error_fields,
    link_ids,
    success_fields,
)

log = logging.getLogger("gtm.sync")

DRAFT = "DRAFT"
SUBMITTED = "SUBMITTED"
IMPORTED = "IMPORTED"
REJECTED = "REJECTED"
EDITABLE = {DRAFT, SUBMITTED}
EXTRACTION_STATUSES = {
    "COMPLETE",
    "INCOMPLETE",
    "AMBIGUOUS",
    "MISSING",
    "UNREADABLE",
}


@dataclass
class AdsReport:
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.failed


def pull_ads(
    connection,
    client,
    *,
    database_id=None,
    creators=None,
    buyers=None,
    platforms=None,
    ads=None,
    max_pages: int = 50,
) -> AdsReport:
    """Read the labelled advertisements and import the editable ones."""
    tables = BaserowTables.resolve(
        client,
        database_id=database_id,
        creators=creators,
        buyers=buyers,
        platforms=platforms,
        ads=ads,
    )
    if tables.ads is None:
        raise SyncError(
            "set BASEROW_TABLE_ADS, or set BASEROW_DATABASE_ID so the "
            "Publicites_etiquetees table can be found"
        )

    report = AdsReport()
    for row in client.iter_rows(tables.ads, max_pages=max_pages):
        row_id = _row_id(row)
        if row_id is None:
            report.skipped.append("AD:?")
            continue

        label = f"AD:{row_id}"
        try:
            _apply_ad(
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


def _apply_ad(
    connection,
    client,
    *,
    tables: BaserowTables,
    row: dict,
    row_id: int,
    label: str,
    report: AdsReport,
) -> None:
    validation_status = clean_text(row.get("validation_status")).upper()
    if validation_status not in EDITABLE:
        status = "SYNCED" if validation_status == IMPORTED else "REJECTED"
        message = (
            None
            if validation_status == IMPORTED
            else f"publicité non importée (validation_status={validation_status})"
        )
        _defer(
            connection,
            client,
            tables.ads,
            row_id,
            label,
            status,
            message,
            report,
        )
        return

    advertiser_raw = clean_text(row.get("advertiser_raw"))
    ad_url = clean_text(row.get("ad_url"))
    collected_at = clean_text(row.get("collected_at"))
    collected_by = clean_text(row.get("collected_by"))
    extraction_status = clean_text(row.get("extraction_status")).upper()
    label_present = _bool(row.get("ad_label_present"))
    inn = clean_text(row.get("inn")) or None
    ogrn = clean_text(row.get("ogrn")) or None
    erid = clean_text(row.get("erid")) or None
    creative_ref = clean_text(row.get("creative_ref")) or None
    creator_refs = clean_text(row.get("creator_refs")) or None

    problem = _validate(
        advertiser_raw=advertiser_raw,
        ad_url=ad_url,
        collected_at=collected_at,
        collected_by=collected_by,
        extraction_status=extraction_status,
        label_present=label_present,
    )
    if problem:
        _reject(connection, client, tables.ads, row_id, label, problem, report)
        return

    normalized_url = normalize_url(ad_url)
    if normalized_url is None:
        _reject(
            connection,
            client,
            tables.ads,
            row_id,
            label,
            f"adresse de publicité invalide : {ad_url!r}",
            report,
        )
        return

    ad_source, problem = _resolve_source(connection, tables, row)
    if problem:
        _reject(connection, client, tables.ads, row_id, label, problem, report)
        return

    creator_ids, unresolved = _resolve_creators(connection, tables, row)
    natural_key = erid or creative_ref or ""
    existing = sync_store.load_ad_for_update(
        connection,
        normalized_url=normalized_url,
        natural_key=natural_key,
    )
    if existing is not None and existing["validation_status"] == IMPORTED:
        _reject(
            connection,
            client,
            tables.ads,
            row_id,
            label,
            "publicité déjà importée : une correction est une nouvelle ligne",
            report,
        )
        return

    reference = f"AD-{row_id:06d}"
    inn_valid = is_valid_inn(inn) if inn else None
    ogrn_valid = is_valid_ogrn(ogrn) if ogrn else None
    ad_id, stored_reference = sync_store.upsert_ad(
        connection,
        reference=reference,
        advertiser_raw=advertiser_raw,
        inn=inn,
        ogrn=ogrn,
        inn_valid=inn_valid,
        ogrn_valid=ogrn_valid,
        erid=erid,
        ad_label_present=bool(label_present),
        extraction_status=extraction_status,
        ad_source=ad_source,
        ad_url=ad_url,
        normalized_ad_url=normalized_url,
        creative_ref=creative_ref,
        creator_refs=creator_refs,
        collected_at=collected_at,
        collected_by=collected_by,
        raw_payload=row,
        validation_status=validation_status,
    )
    sync_store.save_link(
        connection,
        entity_type="AD",
        entity_id=ad_id,
        table_id=tables.ads,
        row_id=row_id,
        sync_hash=None,
    )
    for creator_id in creator_ids:
        sync_store.link_ad_creator(
            connection,
            ad_id=ad_id,
            creator_id=creator_id,
            note="lien Baserow",
        )
    connection.commit()

    fields = {
        "ad_id": ad_id,
        "reference": stored_reference,
        "inn_valid": inn_valid,
        "ogrn_valid": ogrn_valid,
        **success_fields(),
    }

    message = None
    if unresolved:
        message = "créateurs non synchronisés : " + ", ".join(
            str(value) for value in unresolved
        )
        fields.update(error_fields(message))

    try:
        client.update_row(tables.ads, row_id, fields)
    except Exception as error:
        message = _message(error)
        report.failed.append((label, message))
        log.error("%s is stored but not acknowledged: %s", label, message)
        return

    if message:
        report.failed.append((label, message))
    else:
        report.applied.append(label)


def _resolve_source(
    connection, tables: BaserowTables, row: dict
) -> tuple[str | None, str | None]:
    source_ids = link_ids(row.get("ad_source"))
    if source_ids:
        name = sync_store.platform_name_for_row(
            connection, tables.platforms, source_ids[0]
        )
        if name is None:
            return None, (
                "support publicitaire non synchronisé : lancer d'abord la "
                "sortie PostgreSQL → Baserow"
            )
        return name, None
    return clean_text(row.get("ad_source_other")) or None, None


def _resolve_creators(
    connection, tables: BaserowTables, row: dict
) -> tuple[list[str], list[int]]:
    resolved = []
    unresolved = []
    for row_id in link_ids(row.get("creators")):
        link = sync_store.resolve_link(connection, tables.creators, row_id)
        if link is None:
            unresolved.append(row_id)
        else:
            resolved.append(link[1])
    return resolved, unresolved


def _validate(
    *,
    advertiser_raw: str,
    ad_url: str,
    collected_at: str,
    collected_by: str,
    extraction_status: str,
    label_present,
) -> str | None:
    if not advertiser_raw:
        return "advertiser_raw est vide"
    if not ad_url:
        return "ad_url est vide"
    if not collected_at:
        return "collected_at est vide"
    if not collected_by:
        return "collected_by est vide"
    if extraction_status not in EXTRACTION_STATUSES:
        return f"extraction_status inconnu : {extraction_status or 'vide'}"
    if label_present is None:
        return "ad_label_present est absent"
    return None


def _defer(
    connection,
    client,
    table_id: int | None,
    row_id: int,
    label: str,
    status: str,
    message: str | None,
    report: AdsReport,
) -> None:
    connection.rollback()
    if table_id is not None:
        fields = {**success_fields(), "sync_status": status}
        fields["sync_error"] = message
        try:
            client.update_row(table_id, row_id, fields)
        except Exception as error:  # noqa: BLE001 - the review state matters more
            log.warning("could not show the ad state on %s: %s", label, error)
    report.skipped.append(label)


def _reject(
    connection,
    client,
    table_id: int | None,
    row_id: int,
    label: str,
    message: str,
    report: AdsReport,
) -> None:
    connection.rollback()
    if table_id is not None:
        try:
            client.update_row(table_id, row_id, error_fields(message))
        except Exception as error:  # noqa: BLE001 - the refusal is the main outcome
            log.warning("could not show the refusal on %s: %s", label, error)
    report.rejected.append((label, message))
    log.warning("%s refused: %s", label, message)


def _bool(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "oui", "да"}
    return bool(value)


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
        prog="python -m workflows.sync_ads",
        description="Import labelled Baserow advertisements into PostgreSQL.",
    )
    parser.add_argument("--database-id", default=settings.BASEROW_DATABASE_ID)
    parser.add_argument("--creators-table", default=settings.BASEROW_TABLE_CREATORS)
    parser.add_argument("--buyers-table", default=settings.BASEROW_TABLE_BUYERS)
    parser.add_argument("--platforms-table", default=settings.BASEROW_TABLE_PLATFORMS)
    parser.add_argument("--ads-table", default=settings.BASEROW_TABLE_ADS)
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
        report = pull_ads(
            connection,
            client,
            database_id=args.database_id,
            creators=args.creators_table,
            buyers=args.buyers_table,
            platforms=args.platforms_table,
            ads=args.ads_table,
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


def summary(report: AdsReport) -> dict:
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
