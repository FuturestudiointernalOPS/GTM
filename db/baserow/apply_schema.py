"""Create the Baserow tables, fields and views from db/baserow/schema.json.

Why a seeder: the operational schema must be reproducible, not retyped by hand.
The seeder is idempotent: it finds existing tables, fields and views by name,
creates what is missing, and reports type or link mismatches instead of
overwriting them.

Usage:
    python -m db.baserow.apply_schema --dry-run
    python -m db.baserow.apply_schema

The database itself is created in Baserow first; this tool fills it. See
db/README.md for the full step-by-step procedure.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from config import settings
from integrations.baserow import (
    BaserowClient,
    BaserowError,
    BaserowNotConfigured,
)

log = logging.getLogger(__name__)

DEFAULT_SCHEMA = Path(__file__).resolve().parent / "schema.json"

NORMAL_TYPES = {
    "text",
    "long_text",
    "number",
    "boolean",
    "date",
    "date_time",
    "url",
    "single_select",
    "multiple_select",
    "created_on",
    "last_modified",
}
LINK_TYPES = {"link_row"}
DERIVED_TYPES = {"formula", "lookup", "count"}
ALL_TYPES = NORMAL_TYPES | LINK_TYPES | DERIVED_TYPES

VIEW_TYPES = {"grid"}
FILTER_TYPES = {"AND", "OR"}

# Operators accepted in schema.json, with the field types they can filter.
# "formula" is allowed wherever the computed result could match, because the
# schema does not record the formula's result type.
VIEW_FILTER_OPERATORS: dict[str, set[str]] = {
    "equal": ALL_TYPES,
    "not_equal": ALL_TYPES,
    "contains": {
        "text",
        "long_text",
        "url",
        "single_select",
        "multiple_select",
        "formula",
    },
    "contains_not": {
        "text",
        "long_text",
        "url",
        "single_select",
        "multiple_select",
        "formula",
    },
    "empty": ALL_TYPES,
    "not_empty": ALL_TYPES,
    "boolean": {"boolean", "formula"},
    "higher_than": {"number", "date", "date_time", "formula"},
    "higher_than_or_equal": {"number", "date", "date_time", "formula"},
    "lower_than": {"number", "date", "date_time", "formula"},
    "lower_than_or_equal": {"number", "date", "date_time", "formula"},
    "single_select_equal": {"single_select", "formula"},
    "single_select_not_equal": {"single_select", "formula"},
    "single_select_is_any_of": {"single_select", "formula"},
    "single_select_is_none_of": {"single_select", "formula"},
    "multiple_select_has": {"multiple_select", "formula"},
    "multiple_select_has_not": {"multiple_select", "formula"},
    "link_row_has": {"link_row"},
    "link_row_has_not": {"link_row"},
    "date_equal": {"date", "date_time", "formula"},
    "date_before": {"date", "date_time", "formula"},
    "date_before_or_equal": {"date", "date_time", "formula"},
    "date_after": {"date", "date_time", "formula"},
    "date_after_or_equal": {"date", "date_time", "formula"},
    "date_not_equal": {"date", "date_time", "formula"},
}

COLORS = [
    "blue",
    "green",
    "orange",
    "red",
    "purple",
    "cyan",
    "yellow",
    "pink",
    "teal",
    "gray",
    "dark-blue",
    "dark-green",
    "dark-orange",
    "dark-red",
    "dark-purple",
    "dark-cyan",
    "dark-yellow",
    "dark-pink",
    "dark-teal",
    "dark-gray",
]


class SeedError(RuntimeError):
    """The schema cannot be applied without a human decision."""


@dataclass
class TableState:
    name: str
    schema: dict
    table_id: int | None
    fields: dict[str, dict] = field(default_factory=dict)


@dataclass
class ApplyResult:
    created_tables: list[str] = field(default_factory=list)
    created_fields: list[str] = field(default_factory=list)
    updated_fields: list[str] = field(default_factory=list)
    created_views: list[str] = field(default_factory=list)
    created_view_filters: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_schema(path: Path | str = DEFAULT_SCHEMA) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def apply_schema(
    schema: dict,
    database_id: int,
    *,
    client: BaserowClient,
    dry_run: bool = False,
) -> ApplyResult:
    """Create every missing table and field, then return a readable report."""
    result = ApplyResult()
    validation_errors = _validate_schema(schema)
    if validation_errors:
        result.errors.extend(validation_errors)
        return result

    states = _resolve_tables(schema, database_id, client, dry_run, result)

    if dry_run:
        _plan_tables(states, client, result)
        _ensure_views(states, schema, client, result, dry_run=True)
        return result

    _load_fields(states, client)
    for state in states.values():
        if state.table_id is not None:
            _ensure_primary(state, client, result, dry_run=False)

    # Normal fields first: a link target and a lookup target must exist.
    for state in states.values():
        if state.table_id is None:
            continue
        for spec in state.schema["fields"]:
            if spec.get("primary") or spec["type"] not in NORMAL_TYPES:
                continue
            _ensure_field(state, spec, states, client, result, dry_run=False)

    # Link fields second: every table now exists and has its primary field.
    for state in states.values():
        if state.table_id is None:
            continue
        for spec in state.schema["fields"]:
            if spec["type"] not in LINK_TYPES:
                continue
            _ensure_field(state, spec, states, client, result, dry_run=False)

    # Formula, lookup and count last: they depend on the link fields.
    for state in states.values():
        if state.table_id is None:
            continue
        for spec in state.schema["fields"]:
            if spec["type"] not in DERIVED_TYPES:
                continue
            _ensure_field(state, spec, states, client, result, dry_run=False)

    # Views last: their filters need the field ids.
    _ensure_views(states, schema, client, result, dry_run=False)

    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_schema(schema: dict) -> list[str]:
    """Catch structural mistakes before making any network call."""
    errors: list[str] = []
    tables = schema.get("tables")
    if not isinstance(tables, list) or not tables:
        return ["schema.tables must be a non-empty list"]

    table_names: set[str] = set()
    fields_by_table: dict[str, set[str]] = {}
    specs_by_table: dict[str, list[dict]] = {}

    for table in tables:
        name = table.get("name")
        if not name:
            errors.append("a table has no name")
            continue
        if name in table_names:
            errors.append(f"duplicate table {name!r}")
            continue
        table_names.add(name)

        fields = table.get("fields") or []
        specs_by_table[name] = fields
        field_names: set[str] = set()
        primaries: list[str] = []

        for spec in fields:
            field_name = spec.get("name")
            if not field_name:
                errors.append(f"{name}: a field has no name")
                continue
            if field_name in field_names:
                errors.append(f"{name}: duplicate field {field_name!r}")
                continue
            field_names.add(field_name)
            if spec.get("primary"):
                primaries.append(field_name)

            field_type = spec.get("type")
            if field_type not in ALL_TYPES:
                errors.append(f"{name}.{field_name}: unknown type {field_type!r}")
            if field_type in {"single_select", "multiple_select"} and not spec.get(
                "options"
            ):
                errors.append(f"{name}.{field_name}: select field without options")
            if field_type == "formula" and not spec.get("formula"):
                errors.append(f"{name}.{field_name}: formula field without formula")

        fields_by_table[name] = field_names

        if len(primaries) != 1:
            errors.append(f"{name}: exactly one primary field is required")
        elif primaries[0] != table.get("primary_field"):
            errors.append(f"{name}: primary_field does not match the flagged field")

    for name, fields in specs_by_table.items():
        for spec in fields:
            field_name = spec.get("name")
            field_type = spec.get("type")

            if field_type == "link_row":
                target = spec.get("link_row_table")
                if target not in table_names:
                    errors.append(
                        f"{name}.{field_name}: unknown link_row_table {target!r}"
                    )

            if field_type in {"lookup", "count"}:
                through = spec.get("through_field")
                if through not in fields_by_table[name]:
                    errors.append(
                        f"{name}.{field_name}: unknown through_field {through!r}"
                    )
                    continue
                through_spec = next(
                    item for item in fields if item.get("name") == through
                )
                if through_spec.get("type") != "link_row":
                    errors.append(
                        f"{name}.{field_name}: through_field must be a link_row"
                    )
                    continue
                if field_type == "lookup":
                    target_table = through_spec.get("link_row_table")
                    target_field = spec.get("target_field")
                    if target_field not in fields_by_table.get(target_table, set()):
                        errors.append(
                            f"{name}.{field_name}: unknown target_field {target_field!r}"
                        )

    errors.extend(_validate_views(schema, table_names, specs_by_table))

    return errors


def _validate_views(
    schema: dict,
    table_names: set[str],
    specs_by_table: dict[str, list[dict]],
) -> list[str]:
    """Check the view list before touching Baserow."""
    views = schema.get("views") or []
    if not isinstance(views, list):
        return ["schema.views must be a list"]

    errors: list[str] = []
    seen: set[tuple[str, str]] = set()

    for view in views:
        if not isinstance(view, dict):
            errors.append("a view is not an object")
            continue

        name = view.get("name")
        table_name = view.get("table")
        if not name:
            errors.append("a view has no name")
            continue
        if table_name not in table_names:
            errors.append(f"view {name!r}: unknown table {table_name!r}")
            continue
        if (table_name, name) in seen:
            errors.append(f"view {name!r}: duplicate on table {table_name!r}")
            continue
        seen.add((table_name, name))

        if view.get("type", "grid") not in VIEW_TYPES:
            errors.append(f"view {name!r}: unknown type {view.get('type')!r}")
        if view.get("filter_type", "AND") not in FILTER_TYPES:
            errors.append(
                f"view {name!r}: filter_type must be AND or OR, "
                f"got {view.get('filter_type')!r}"
            )

        fields = {spec.get("name"): spec for spec in specs_by_table[table_name]}
        for item in view.get("filters") or []:
            errors.extend(_validate_view_filter(name, item, fields))

    return errors


def _validate_view_filter(
    view_name: str,
    item: dict,
    fields: dict[str, dict],
) -> list[str]:
    field_name = item.get("field")
    spec = fields.get(field_name)
    if spec is None:
        return [f"view {view_name!r}: unknown field {field_name!r}"]

    operator = item.get("type")
    allowed = VIEW_FILTER_OPERATORS.get(operator)
    if allowed is None:
        return [f"view {view_name!r}: unknown filter operator {operator!r}"]

    field_type = spec.get("type")
    if field_type not in allowed:
        return [
            f"view {view_name!r}: {operator!r} cannot filter {field_name!r} "
            f"of type {field_type!r}"
        ]

    errors: list[str] = []
    value = str(item.get("value", ""))

    if operator in {"boolean"}:
        if value.lower() not in {"true", "false", "1", "0", ""}:
            errors.append(
                f"view {view_name!r}: boolean filter on {field_name!r} "
                f"needs true or false, got {value!r}"
            )
        return errors

    uses_select_labels = operator.startswith("single_select_") or operator.startswith(
        "multiple_select_"
    )
    if uses_select_labels and field_type in {"single_select", "multiple_select"}:
        options = set(spec.get("options") or [])
        tokens = [token.strip() for token in value.split(",") if token.strip()]
        if not tokens:
            errors.append(f"view {view_name!r}: filter on {field_name!r} has no value")
        for token in tokens:
            if token not in options:
                errors.append(
                    f"view {view_name!r}: {token!r} is not an option of {field_name!r}"
                )

    return errors


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _resolve_tables(
    schema: dict,
    database_id: int,
    client: BaserowClient,
    dry_run: bool,
    result: ApplyResult,
) -> dict[str, TableState]:
    existing = {table["name"]: table for table in client.list_tables(database_id)}
    states: dict[str, TableState] = {}

    for table_spec in schema["tables"]:
        name = table_spec["name"]
        if name in existing:
            table_id = existing[name].get("id")
            if table_id is None:
                result.errors.append(f"table {name!r} exists without an id")
            else:
                log.info("table %s exists (id %s)", name, table_id)
            states[name] = TableState(name, table_spec, table_id)
            continue

        if dry_run:
            log.info("[dry-run] would create table %s", name)
            result.created_tables.append(name)
            states[name] = TableState(name, table_spec, None)
            continue

        created = client.create_table(database_id, name)
        table_id = created.get("id") if isinstance(created, dict) else None
        if table_id is None:
            result.errors.append(f"table {name!r} was created without an id")
        else:
            log.info("created table %s (id %s)", name, table_id)
            result.created_tables.append(name)
        states[name] = TableState(name, table_spec, table_id)

    return states


def _load_fields(states: dict[str, TableState], client: BaserowClient) -> None:
    for state in states.values():
        if state.table_id is None:
            continue
        fields = client.list_fields(state.table_id)
        state.fields = {field["name"]: field for field in fields if field.get("name")}


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def _plan_tables(
    states: dict[str, TableState],
    client: BaserowClient,
    result: ApplyResult,
) -> None:
    for state in states.values():
        if state.table_id is not None:
            try:
                fields = client.list_fields(state.table_id)
            except BaserowError as error:
                result.errors.append(f"{state.name}: cannot read fields ({error})")
                continue
            state.fields = {
                field["name"]: field for field in fields if field.get("name")
            }
        _ensure_primary(state, client, result, dry_run=True)

    for state in states.values():
        for spec in state.schema["fields"]:
            if spec.get("primary"):
                continue
            _ensure_field(state, spec, states, client, result, dry_run=True)


# ---------------------------------------------------------------------------
# Primary field
# ---------------------------------------------------------------------------


def _ensure_primary(
    state: TableState,
    client: BaserowClient,
    result: ApplyResult,
    *,
    dry_run: bool,
) -> None:
    spec = _primary_spec(state.schema)

    if state.table_id is None or not state.fields:
        if dry_run:
            result.created_fields.append(f"{state.name}.{spec['name']} (primary)")
            log.info(
                "[dry-run] would create the primary field %s.%s",
                state.name,
                spec["name"],
            )
        else:
            result.errors.append(
                f"{state.name}: no primary field found after table creation"
            )
        return

    fields = list(state.fields.values())
    primary = next((item for item in fields if item.get("primary")), fields[0])

    if primary.get("name") == spec["name"]:
        if not _types_match(primary.get("type"), spec["type"]):
            result.errors.append(
                f"{state.name}.{spec['name']}: primary field has type "
                f"{primary.get('type')!r}, expected {_baserow_type(spec['type'])!r}"
            )
        return

    if spec["name"] in state.fields:
        result.errors.append(
            f"{state.name}: field {spec['name']!r} exists but is not the primary "
            f"field; the primary field is {primary.get('name')!r}"
        )
        return

    if primary.get("name") != "Name" and len(fields) > 1:
        result.errors.append(
            f"{state.name}: primary field is {primary.get('name')!r}, expected "
            f"{spec['name']!r}; rename it manually or use a fresh table"
        )
        return

    if dry_run:
        log.info(
            "[dry-run] would rename primary field %s.%s to %s",
            state.name,
            primary.get("name"),
            spec["name"],
        )
        result.updated_fields.append(
            f"{state.name}.{spec['name']} (primary renamed from {primary.get('name')})"
        )
        return

    updated = client.update_field(primary["id"], {"name": spec["name"]})
    state.fields.pop(primary.get("name"), None)
    state.fields[spec["name"]] = updated
    result.updated_fields.append(f"{state.name}.{spec['name']} (primary renamed)")
    log.info(
        "renamed primary field %s.%s to %s",
        state.name,
        primary.get("name"),
        spec["name"],
    )


def _primary_spec(table_schema: dict) -> dict:
    for spec in table_schema["fields"]:
        if spec.get("primary"):
            return spec
    raise SeedError(f"{table_schema.get('name')}: no primary field")


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------


def _ensure_field(
    state: TableState,
    spec: dict,
    states: dict[str, TableState],
    client: BaserowClient,
    result: ApplyResult,
    *,
    dry_run: bool,
) -> None:
    name = spec["name"]
    existing = state.fields.get(name)

    if existing:
        expected_type = _baserow_type(spec["type"])
        if existing.get("type") != expected_type:
            result.errors.append(
                f"{state.name}.{name}: field has type {existing.get('type')!r}, "
                f"expected {expected_type!r}; the seeder does not change types"
            )
            return

        if spec["type"] in {"single_select", "multiple_select"}:
            _ensure_select_options(state, spec, existing, client, result, dry_run)
        elif spec["type"] == "link_row":
            _check_link_row(state, spec, existing, states, result)
        return

    if dry_run:
        log.info(
            "[dry-run] would create field %s.%s (%s)", state.name, name, spec["type"]
        )
        result.created_fields.append(f"{state.name}.{name}")
        return

    try:
        payload = _build_field_payload(state, spec, states)
    except SeedError as error:
        result.errors.append(f"{state.name}.{name}: {error}")
        return

    created = client.create_field(state.table_id, payload)
    state.fields[name] = created
    result.created_fields.append(f"{state.name}.{name}")
    log.info("created field %s.%s (%s)", state.name, name, spec["type"])


def _build_field_payload(
    state: TableState,
    spec: dict,
    states: dict[str, TableState],
) -> dict:
    field_type = spec["type"]
    payload: dict = {"name": spec["name"], "type": _baserow_type(field_type)}

    if field_type == "number":
        payload["number_decimal_places"] = int(spec.get("number_decimal_places", 0))
        payload["number_negative"] = bool(spec.get("number_negative", False))

    elif field_type in {"date", "date_time"}:
        payload["date_format"] = "ISO"
        payload["date_include_time"] = field_type == "date_time"

    elif field_type in {"single_select", "multiple_select"}:
        payload["select_options"] = [
            {"value": value, "color": _color(value, index)}
            for index, value in enumerate(spec.get("options", []))
        ]

    elif field_type == "link_row":
        target_name = spec.get("link_row_table")
        target = states.get(target_name)
        if target is None or target.table_id is None:
            raise SeedError(f"target table {target_name!r} is not available")
        payload["link_row_table_id"] = target.table_id
        payload["has_many_relationships"] = bool(spec.get("multiple", False))

    elif field_type == "lookup":
        through_name = spec.get("through_field")
        through = state.fields.get(through_name)
        if through is None:
            raise SeedError(f"link field {through_name!r} must exist before the lookup")
        through_spec = _field_spec(state.schema, through_name)
        target_name = through_spec.get("link_row_table")
        target = states.get(target_name)
        target_field = target.fields.get(spec.get("target_field")) if target else None
        if target_field is None:
            raise SeedError(
                f"target field {spec.get('target_field')!r} is missing in {target_name!r}"
            )
        payload["through_field_id"] = through["id"]
        payload["target_field_id"] = target_field["id"]

    elif field_type == "count":
        through_name = spec.get("through_field")
        through = state.fields.get(through_name)
        if through is None:
            raise SeedError(f"link field {through_name!r} must exist before the count")
        payload["through_field_id"] = through["id"]

    elif field_type == "formula":
        formula = spec.get("formula")
        if not formula:
            raise SeedError("formula is empty")
        payload["formula"] = formula

    return payload


def _ensure_select_options(
    state: TableState,
    spec: dict,
    existing: dict,
    client: BaserowClient,
    result: ApplyResult,
    dry_run: bool,
) -> None:
    current = existing.get("select_options") or []
    current_values = {option.get("value") for option in current}
    desired = spec.get("options", [])
    missing = [value for value in desired if value not in current_values]
    if not missing:
        return

    if dry_run:
        log.info(
            "[dry-run] would add options to %s.%s: %s",
            state.name,
            spec["name"],
            ", ".join(missing),
        )
        result.updated_fields.append(
            f"{state.name}.{spec['name']} (options: {', '.join(missing)})"
        )
        return

    merged = []
    for option in current:
        item = {
            "value": option.get("value"),
            "color": option.get("color") or "gray",
        }
        if option.get("id") is not None:
            item["id"] = option["id"]
        merged.append(item)

    for index, value in enumerate(desired):
        if value not in current_values:
            merged.append({"value": value, "color": _color(value, index)})

    updated = client.update_field(existing["id"], {"select_options": merged})
    state.fields[spec["name"]] = updated
    result.updated_fields.append(
        f"{state.name}.{spec['name']} (options: {', '.join(missing)})"
    )
    log.info("added options to %s.%s: %s", state.name, spec["name"], ", ".join(missing))


def _check_link_row(
    state: TableState,
    spec: dict,
    existing: dict,
    states: dict[str, TableState],
    result: ApplyResult,
) -> None:
    target_name = spec.get("link_row_table")
    target = states.get(target_name)
    if target is None or target.table_id is None:
        result.errors.append(
            f"{state.name}.{spec['name']}: target table {target_name!r} is unavailable"
        )
        return

    existing_target = existing.get("link_row_table_id")
    if existing_target is not None and existing_target != target.table_id:
        result.errors.append(
            f"{state.name}.{spec['name']}: links to table {existing_target}, "
            f"expected {target.table_id} ({target_name}); change it manually"
        )

    existing_many = existing.get("has_many_relationships")
    desired_many = bool(spec.get("multiple", False))
    if existing_many is not None and bool(existing_many) != desired_many:
        result.errors.append(
            f"{state.name}.{spec['name']}: has_many_relationships is "
            f"{bool(existing_many)}, expected {desired_many}; change it manually"
        )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def _ensure_views(
    states: dict[str, TableState],
    schema: dict,
    client: BaserowClient,
    result: ApplyResult,
    *,
    dry_run: bool,
) -> None:
    """Create the working views and their filters, without deleting anything."""
    view_specs = schema.get("views") or []
    if not view_specs:
        return

    cache: dict[str, dict[str, dict]] = {}

    for view_spec in view_specs:
        table = states.get(view_spec["table"])
        if table is None or table.table_id is None:
            label = f"{view_spec['table']}/{view_spec['name']}"
            if dry_run:
                log.info("[dry-run] would create view %s", label)
                result.created_views.append(label)
            else:
                result.errors.append(
                    f"view {view_spec['name']!r}: table "
                    f"{view_spec['table']!r} is unavailable"
                )
            continue

        if table.name not in cache:
            try:
                existing_views = client.list_views(table.table_id, include="filters")
            except BaserowError as error:
                result.errors.append(f"{table.name}: cannot read views ({error})")
                cache[table.name] = {}
                continue
            cache[table.name] = {
                view["name"]: view for view in existing_views if view.get("name")
            }

        existing = cache[table.name].get(view_spec["name"])
        if existing is None:
            _create_view(table, view_spec, client, result, dry_run=dry_run)
            continue

        desired = _desired_view_filters(table, view_spec)
        if desired is None:
            result.errors.append(
                f"view {table.name}/{view_spec['name']}: a filter field is missing"
            )
            continue

        _check_view(
            table, view_spec, existing, desired, client, result, dry_run=dry_run
        )


def _desired_view_filters(table: TableState, view_spec: dict) -> list[dict] | None:
    """Translate field names into the field ids Baserow expects."""
    desired: list[dict] = []
    for item in view_spec.get("filters") or []:
        field = table.fields.get(item["field"])
        if field is None or field.get("id") is None:
            return None
        desired.append(
            {
                "field": field["id"],
                "type": item["type"],
                "value": str(item.get("value", "")),
            }
        )
    return desired


def _create_view(
    table: TableState,
    view_spec: dict,
    client: BaserowClient,
    result: ApplyResult,
    *,
    dry_run: bool,
) -> None:
    label = f"{table.name}/{view_spec['name']}"
    filter_labels = [
        _filter_label(table, item) for item in view_spec.get("filters") or []
    ]

    if dry_run:
        log.info("[dry-run] would create view %s", label)
        result.created_views.append(label)
        for filter_label in filter_labels:
            result.created_view_filters.append(f"{label}.{filter_label}")
        return

    desired = _desired_view_filters(table, view_spec)
    if desired is None:
        result.errors.append(f"view {label}: a filter field is missing")
        return

    created = client.create_view(
        table.table_id,
        view_spec["name"],
        view_spec.get("type", "grid"),
        view_spec.get("filter_type", "AND"),
    )
    view_id = created.get("id") if isinstance(created, dict) else None
    if view_id is None:
        result.errors.append(f"view {label} was created without an id")
        return

    result.created_views.append(label)
    log.info("created view %s (id %s)", label, view_id)

    for payload, filter_label in zip(desired, filter_labels):
        client.create_view_filter(view_id, payload)
        result.created_view_filters.append(f"{label}.{filter_label}")
        log.info("created view filter %s.%s", label, filter_label)


def _check_view(
    table: TableState,
    view_spec: dict,
    existing: dict,
    desired: list[dict],
    client: BaserowClient,
    result: ApplyResult,
    *,
    dry_run: bool,
) -> None:
    label = f"{table.name}/{view_spec['name']}"

    view_type = existing.get("type")
    if view_type not in (None, "grid"):
        result.errors.append(
            f"view {label}: has type {view_type!r}, expected 'grid'; "
            f"the seeder does not change view types"
        )
        return

    current_type = existing.get("filter_type")
    expected_type = view_spec.get("filter_type", "AND")
    if current_type is not None and current_type != expected_type:
        result.errors.append(
            f"view {label}: filter_type is {current_type!r}, expected "
            f"{expected_type!r}; change it manually"
        )
        return

    current = {
        (item.get("field"), item.get("type"), str(item.get("value", "")))
        for item in existing.get("filters") or []
    }
    wanted = {(item["field"], item["type"], item["value"]) for item in desired}

    missing = [
        (payload, filter_spec)
        for payload, filter_spec in zip(desired, view_spec.get("filters") or [])
        if (payload["field"], payload["type"], payload["value"]) not in current
    ]
    for payload, filter_spec in missing:
        filter_label = _filter_label(table, filter_spec)
        if dry_run:
            log.info("[dry-run] would add filter %s.%s", label, filter_label)
            result.created_view_filters.append(f"{label}.{filter_label}")
            continue
        client.create_view_filter(existing["id"], payload)
        result.created_view_filters.append(f"{label}.{filter_label}")
        log.info("added filter %s.%s", label, filter_label)

    extra = current - wanted
    if extra:
        result.warnings.append(
            f"view {label}: {len(extra)} filter(s) not in schema.json were left "
            f"untouched"
        )


def _filter_label(table: TableState, item: dict) -> str:
    return f"{item['field']} {item['type']} {item.get('value', '')}".strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _field_spec(table_schema: dict, name: str) -> dict:
    for spec in table_schema["fields"]:
        if spec.get("name") == name:
            return spec
    raise SeedError(f"{table_schema.get('name')}: unknown field {name!r}")


def _baserow_type(spec_type: str) -> str:
    """Baserow uses one 'date' type for both date and date/time fields."""
    return "date" if spec_type == "date_time" else spec_type


def _types_match(existing_type: str | None, spec_type: str) -> bool:
    return existing_type == _baserow_type(spec_type)


def _color(value: str, index: int) -> str:
    return COLORS[index % len(COLORS)]


def _default_database_id() -> int | None:
    value = (settings.BASEROW_DATABASE_ID or "").strip()
    return int(value) if value.isdigit() else None


def _print_summary(result: ApplyResult, *, dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "APPLIED"
    log.info(
        "%s: %s table(s) created, %s field(s) created, %s field(s) updated, "
        "%s view(s) created, %s view filter(s) created",
        mode,
        len(result.created_tables),
        len(result.created_fields),
        len(result.updated_fields),
        len(result.created_views),
        len(result.created_view_filters),
    )
    for warning in result.warnings:
        log.warning("%s", warning)
    for error in result.errors:
        log.error("%s", error)
    if result.ok:
        log.info("Baserow schema is up to date.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create the GTM Baserow tables and fields from schema.json."
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help="path to the schema JSON (default: db/baserow/schema.json)",
    )
    parser.add_argument(
        "--database-id",
        type=int,
        default=_default_database_id(),
        help="Baserow database id (default: BASEROW_DATABASE_ID)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be created without writing anything",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="show debug logs",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if not args.database_id:
        parser.error("--database-id or BASEROW_DATABASE_ID is required")

    try:
        schema = load_schema(args.schema)
    except (OSError, json.JSONDecodeError) as error:
        log.error("cannot read schema %s: %s", args.schema, error)
        return 2

    try:
        with BaserowClient() as client:
            result = apply_schema(
                schema,
                args.database_id,
                client=client,
                dry_run=args.dry_run,
            )
    except BaserowNotConfigured as error:
        log.error("%s", error)
        return 2
    except BaserowError as error:
        log.error("%s", error)
        return 2

    _print_summary(result, dry_run=args.dry_run)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
