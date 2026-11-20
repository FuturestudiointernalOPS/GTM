"""Shared settings for both synchronization directions.

The push worker and the pull worker must agree on which Baserow table receives
which PostgreSQL entity. Keeping the resolution in one place avoids a silent
mismatch where one direction writes to a table the other never reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


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
                creators=table_id("creators", creators),
                buyers=table_id("buyers", buyers),
                platforms=table_id("platforms", platforms),
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
        )


def table_id(name: str, value) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError) as error:
        raise SyncError(f"invalid Baserow table id for {name}: {value!r}") from error
    if resolved <= 0:
        raise SyncError(f"invalid Baserow table id for {name}: {value!r}")
    return resolved


def success_fields() -> dict:
    return {
        "sync_status": "SYNCED",
        "sync_error": None,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
    }


def error_fields(message: str) -> dict:
    return {"sync_status": "ERROR", "sync_error": message[:500]}
