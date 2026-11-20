"""Shared settings for both synchronization directions.

The push worker and the pull worker must agree on which Baserow table receives
which PostgreSQL entity. Keeping the resolution in one place avoids a silent
mismatch where one direction writes to a table the other never reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from integrations import sync_store


class SyncError(RuntimeError):
    """The service cannot start: a setting or a table is missing."""


@dataclass(frozen=True)
class BaserowTables:
    creators: int
    buyers: int
    platforms: int
    contacts: int | None = None
    proofs: int | None = None

    @classmethod
    def resolve(
        cls,
        client,
        *,
        database_id=None,
        creators=None,
        buyers=None,
        platforms=None,
        contacts=None,
        proofs=None,
    ) -> "BaserowTables":
        """Use configured table ids, or discover them through the schema API."""
        if creators and buyers and platforms:
            return cls(
                creators=table_id("creators", creators),
                buyers=table_id("buyers", buyers),
                platforms=table_id("platforms", platforms),
                contacts=table_id("contacts", contacts) if contacts else None,
                proofs=table_id("proofs", proofs) if proofs else None,
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
            for name in ("Createurs", "Acheteurs", "Plateformes")
            if name not in by_name
        ]
        if missing:
            raise SyncError(
                "Baserow is missing these tables: " + ", ".join(sorted(missing))
            )

        return cls(
            creators=by_name["Createurs"],
            buyers=by_name["Acheteurs"],
            platforms=by_name["Plateformes"],
            contacts=by_name.get("Contacts"),
            proofs=by_name.get("Preuves"),
        )


def table_id(name: str, value) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError) as error:
        raise SyncError(f"invalid Baserow table id for {name}: {value!r}") from error
    if resolved <= 0:
        raise SyncError(f"invalid Baserow table id for {name}: {value!r}")
    return resolved


def resolve_record_link(
    connection, tables: "BaserowTables", row: dict
) -> tuple[str, str | None]:
    """Resolve the creator or buyer link of a Baserow row to a record id."""
    record_type = clean_text(row.get("record_type")).upper()
    creator_ids = link_ids(row.get("creator"))
    buyer_ids = link_ids(row.get("acheteur"))

    if record_type == "CREATOR":
        selected, table_id = creator_ids, tables.creators
    elif record_type == "BUYER":
        selected, table_id = buyer_ids, tables.buyers
    elif creator_ids and not buyer_ids:
        selected, table_id = creator_ids, tables.creators
    elif buyer_ids and not creator_ids:
        selected, table_id = buyer_ids, tables.buyers
    elif creator_ids and buyer_ids:
        return "", "la ligne porte à la fois un créateur et un acheteur"
    else:
        return "", "record_type ou lien vers une fiche absent"

    if not selected:
        return "", f"aucune ligne {record_type or 'de fiche'} liée"

    resolved = sync_store.resolve_link(connection, table_id, selected[0])
    if resolved is None:
        return "", (
            "fiche liée non synchronisée : lancer d'abord la synchronisation "
            "PostgreSQL → Baserow"
        )

    entity_type, entity_id = resolved
    if record_type and entity_type != record_type:
        return "", f"le lien pointe vers {entity_type}, pas {record_type}"
    return entity_id, None


def link_ids(value) -> list[int]:
    """Read a Baserow link_row value as a list of row ids."""
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, (list, tuple)):
        value = [value]

    ids = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("id")
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("value", "")
    return " ".join(str(value).split())


def success_fields() -> dict:
    return {
        "sync_status": "SYNCED",
        "sync_error": None,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
    }


def error_fields(message: str) -> dict:
    return {"sync_status": "ERROR", "sync_error": message[:500]}
