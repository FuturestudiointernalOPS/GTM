"""Translate a PostgreSQL fiche into the Baserow fields the database owns.

Why this module is pure: the same fiche must produce the same Baserow payload
on every run, and a mapping mistake must be visible in an offline test. It
never calls Baserow and never touches a connection.

The ownership rule comes from ``db/baserow/schema.json``: only fields marked
``owner = pg`` are pushed. ``owner = baserow`` fields belong to a human and
``owner = derived`` fields are computed by Baserow, so writing either would
overwrite work the service does not own.

A few fields are renamed on the way out because the database view and the
Baserow field do not share a name. Platform links need one extra step: Baserow
expects the row id of the platform, not its name, so the caller resolves the
reference table first and passes the mapping in.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

DEFAULT_SCHEMA = (
    Path(__file__).resolve().parent.parent / "db" / "baserow" / "schema.json"
)

CREATOR_TABLE = "Createurs"
BUYER_TABLE = "Acheteurs"
PLATFORM_TABLE = "Plateformes"

# The database view names two fields differently from the operational table.
CREATOR_ALIASES = {
    "engagement_sample_hash": "engagement_sample_ref",
    "engagement_flags": "engagement_flag",
}
PLATFORM_ALIASES = {"id": "platform_id"}

# A link_row needs the target row id, not the value read from the database.
RESOLVED_LINKS = {(CREATOR_TABLE, "main_platform")}

DERIVED_TYPES = {"formula", "lookup", "count", "created_on", "last_modified"}
WRITABLE_TYPES = {
    "text",
    "long_text",
    "number",
    "boolean",
    "date",
    "date_time",
    "url",
    "single_select",
    "multiple_select",
}


class MappingError(ValueError):
    """The schema cannot produce a payload; the caller must fix the mapping."""


def load_schema(path: Path | str = DEFAULT_SCHEMA) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def table_fields(schema: dict | None = None) -> dict[str, dict[str, dict]]:
    """Return ``{table_name: {field_name: field_spec}}``."""
    source = schema if schema is not None else load_schema()
    return {
        table["name"]: {field["name"]: field for field in table["fields"]}
        for table in source["tables"]
    }


def build_creator_row(
    fiche: Mapping[str, Any],
    *,
    platform_row_ids: Mapping[str, int] | None = None,
    schema: dict | None = None,
) -> dict[str, Any]:
    """Build the Baserow payload for a creator fiche."""
    return _build(
        CREATOR_TABLE,
        fiche,
        aliases=CREATOR_ALIASES,
        platform_row_ids=platform_row_ids or {},
        schema=schema,
    )


def build_buyer_row(
    fiche: Mapping[str, Any],
    *,
    schema: dict | None = None,
) -> dict[str, Any]:
    """Build the Baserow payload for a buyer fiche."""
    return _build(BUYER_TABLE, fiche, aliases={}, platform_row_ids={}, schema=schema)


def build_platform_row(
    platform: Mapping[str, Any],
    *,
    schema: dict | None = None,
) -> dict[str, Any]:
    """Build the Baserow payload for one row of the platform reference table."""
    return _build(
        PLATFORM_TABLE,
        platform,
        aliases=PLATFORM_ALIASES,
        platform_row_ids={},
        schema=schema,
    )


def payload_hash(payload: Mapping[str, Any]) -> str:
    """Stable fingerprint of a business payload, ignoring field order."""
    text = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build(
    table: str,
    values: Mapping[str, Any],
    *,
    aliases: Mapping[str, str],
    platform_row_ids: Mapping[str, int],
    schema: dict | None,
) -> dict[str, Any]:
    fields = table_fields(schema).get(table)
    if fields is None:
        raise MappingError(f"{table!r} is missing from the Baserow schema")

    payload: dict[str, Any] = {}
    for source_name, value in values.items():
        target_name = aliases.get(source_name, source_name)
        field = fields.get(target_name)
        if field is None or field.get("owner") != "pg":
            continue

        field_type = field.get("type")
        if field_type == "link_row":
            # Only links this module knows how to resolve are pushed. A link
            # without a target row is omitted, not cleared: a temporary
            # platform failure must not erase a correct link.
            if (table, target_name) in RESOLVED_LINKS and value is not None:
                row_id = platform_row_ids.get(str(value))
                if row_id is not None:
                    payload[target_name] = [row_id]
            elif value is None:
                payload[target_name] = None
            continue

        if field_type in DERIVED_TYPES or field_type not in WRITABLE_TYPES:
            continue

        payload[target_name] = _convert(table, target_name, value, field_type)

    return payload


def _convert(table: str, name: str, value: Any, field_type: str) -> Any:
    if value is None:
        # Baserow boolean fields reject null. Until the verification runs, the
        # fiche stores None; the status fields record that it is still pending.
        return False if field_type == "boolean" else None

    # A boolean is stored as a three-value list in the platform table.
    if (table, name) == (PLATFORM_TABLE, "stable_id_available"):
        if isinstance(value, str):
            return value.upper()
        return "YES" if value else "NO"

    if (table, name) == (BUYER_TABLE, "ad_label_refs"):
        return _ad_label_refs(value)

    if field_type in {"text", "long_text", "url"}:
        if isinstance(value, (list, tuple)):
            return "\n".join(str(item) for item in value)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

    if field_type == "number":
        if isinstance(value, Decimal):
            return float(value)
        return value

    if field_type == "boolean":
        return bool(value)

    if field_type == "date":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value)

    if field_type == "date_time":
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    if field_type == "single_select":
        return str(value)

    if field_type == "multiple_select":
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value]
        return [str(value)]

    return value


def _ad_label_refs(value: Any) -> str:
    """Turn the stored ad references into one readable line per advertisement."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                parts = [
                    str(item[key])
                    for key in ("date", "source", "erid")
                    if item.get(key) is not None
                ]
                if parts:
                    lines.append(" | ".join(parts))
            else:
                lines.append(str(item))
        return "\n".join(lines)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)
