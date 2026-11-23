"""Match imported advertisements to buyers by their INN or OGRN.

The label identifies the advertiser. A buyer is matched when exactly one
existing buyer carries the label's INN, its OGRN, or both. When no buyer
exists, one is created from the advertiser name and the valid tax id, because
the label is the normal birth certificate of a buyer.

Two buyers reached by different identifiers, or several buyers sharing one
identifier, are ambiguous: the service refuses to choose and leaves the ad for
a human. A matched ad is marked ``IMPORTED`` only once its buyer row exists in
Baserow, so the row can carry the link before it becomes immutable.
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
from integrations.record_store import PostgresRecordStore
from processing.russian_ids import is_valid_inn, is_valid_ogrn
from processing.scoring import CRITERIA_VERSION
from workflows.records import BuyerIdentity
from workflows.sync_common import (
    BaserowTables,
    SyncError,
    clean_text,
    error_fields,
    success_fields,
)

log = logging.getLogger("gtm.sync")

AUTO_MATCHED = "AUTO_MATCHED"
AMBIGUOUS = "AMBIGUOUS"
UNMATCHED = "UNMATCHED"
IMPORTED = "IMPORTED"


@dataclass
class MatchReport:
    matched: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def match_ads(
    connection,
    client,
    *,
    database_id=None,
    creators=None,
    buyers=None,
    platforms=None,
    ads=None,
    limit: int = 100,
) -> MatchReport:
    """Match a batch of imported ads, then acknowledge the matched rows."""
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

    report = MatchReport()
    for ad in sync_store.load_ads_for_matching(connection, limit=max(1, limit)):
        label = f"AD:{ad.get('reference') or ad.get('id')}"
        try:
            _match_one(
                connection,
                client,
                tables=tables,
                ad=ad,
                label=label,
                report=report,
            )
        except Exception as error:
            connection.rollback()
            message = _message(error)
            report.failed.append((label, message))
            log.error("%s could not be matched: %s", label, message)
    return report


def _match_one(
    connection,
    client,
    *,
    tables: BaserowTables,
    ad: dict,
    label: str,
    report: MatchReport,
) -> None:
    ad_id = str(ad["id"])
    ad_link = sync_store.get_link(connection, "AD", ad_id, tables.ads)
    if ad_link is None:
        raise SyncError(
            "ligne Baserow inconnue : relancer d'abord la synchronisation "
            "des publicités"
        )

    inn = _identifier(ad.get("inn"), is_valid_inn)
    ogrn = _identifier(ad.get("ogrn"), is_valid_ogrn)
    if not inn and not ogrn:
        _store_outcome(
            connection,
            client,
            tables,
            ad,
            ad_link.row_id,
            buyer_id=None,
            match_status=UNMATCHED,
            validation_status=ad["validation_status"],
            fields={"match_status": UNMATCHED, **success_fields()},
        )
        report.unmatched.append(label)
        return

    by_inn = sync_store.find_buyers_by_inn(connection, inn) if inn else []
    by_ogrn = sync_store.find_buyers_by_ogrn(connection, ogrn) if ogrn else []
    candidates = set(by_inn + by_ogrn)

    if len(by_inn) > 1 or len(by_ogrn) > 1 or len(candidates) > 1:
        message = "plusieurs acheteurs correspondent à l'INN ou à l'OGRN"
        _store_outcome(
            connection,
            client,
            tables,
            ad,
            ad_link.row_id,
            buyer_id=None,
            match_status=AMBIGUOUS,
            validation_status=ad["validation_status"],
            fields={
                "match_status": AMBIGUOUS,
                **error_fields(message),
            },
        )
        report.ambiguous.append(label)
        log.warning("%s ambiguous: %s", label, message)
        return

    created = False
    if candidates:
        buyer_id = next(iter(candidates))
    else:
        legal_name = clean_text(ad.get("advertiser_raw"))
        if not legal_name:
            _store_outcome(
                connection,
                client,
                tables,
                ad,
                ad_link.row_id,
                buyer_id=None,
                match_status=UNMATCHED,
                validation_status=ad["validation_status"],
                fields={"match_status": UNMATCHED, **success_fields()},
            )
            report.unmatched.append(label)
            return

        store = PostgresRecordStore(connection)
        keys = store.create_buyer(
            BuyerIdentity(
                domain=None,
                tax_id=inn or ogrn,
                legal_name=legal_name,
            ),
            CRITERIA_VERSION,
        )
        buyer_id = keys.record_id
        sync_store.attach_buyer_identifiers(
            connection,
            record_id=buyer_id,
            inn=inn,
            ogrn=ogrn,
        )
        created = True

    buyer_link = sync_store.get_link(connection, "BUYER", buyer_id, tables.buyers)
    can_import = buyer_link is not None
    validation_status = IMPORTED if can_import else ad["validation_status"]

    fields = {"match_status": AUTO_MATCHED, **success_fields()}
    if can_import:
        fields["validation_status"] = IMPORTED
    if buyer_link is not None:
        fields["buyer"] = [buyer_link.row_id]

    _store_outcome(
        connection,
        client,
        tables,
        ad,
        ad_link.row_id,
        buyer_id=buyer_id,
        match_status=AUTO_MATCHED,
        validation_status=validation_status,
        fields=fields,
    )
    report.matched.append(label)
    if created:
        report.created.append(label)


def _store_outcome(
    connection,
    client,
    tables: BaserowTables,
    ad: dict,
    row_id: int,
    *,
    buyer_id: str | None,
    match_status: str,
    validation_status: str,
    fields: dict,
) -> None:
    """Write the PostgreSQL outcome, acknowledge Baserow, then commit.

    The acknowledgement is part of the transaction: if Baserow refuses it,
    nothing is kept, so a later run sees the same ad instead of a matched ad
    whose row was never updated.
    """
    sync_store.update_ad_match(
        connection,
        ad_id=str(ad["id"]),
        buyer_record_id=buyer_id,
        match_status=match_status,
        validation_status=validation_status,
    )
    try:
        client.update_row(tables.ads, row_id, fields)
    except Exception:
        connection.rollback()
        raise
    connection.commit()


def _identifier(value, validator) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    cleaned = text.replace("-", "").replace(" ", "")
    return cleaned if validator(cleaned) else None


def _message(error: Exception) -> str:
    text = str(error).strip()
    return text[:500] if text else type(error).__name__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m workflows.match_ads",
        description="Match imported advertisements to buyers by INN or OGRN.",
    )
    parser.add_argument("--database-id", default=settings.BASEROW_DATABASE_ID)
    parser.add_argument("--creators-table", default=settings.BASEROW_TABLE_CREATORS)
    parser.add_argument("--buyers-table", default=settings.BASEROW_TABLE_BUYERS)
    parser.add_argument("--platforms-table", default=settings.BASEROW_TABLE_PLATFORMS)
    parser.add_argument("--ads-table", default=settings.BASEROW_TABLE_ADS)
    parser.add_argument("--limit", type=int, default=100)
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
        report = match_ads(
            connection,
            client,
            database_id=args.database_id,
            creators=args.creators_table,
            buyers=args.buyers_table,
            platforms=args.platforms_table,
            ads=args.ads_table,
            limit=args.limit,
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


def summary(report: MatchReport) -> dict:
    return {
        "ok": report.ok,
        "matched": list(report.matched),
        "created": list(report.created),
        "ambiguous": list(report.ambiguous),
        "unmatched": list(report.unmatched),
        "failed": [
            {"entity": entity, "error": error} for entity, error in report.failed
        ],
    }


if __name__ == "__main__":
    sys.exit(main())
