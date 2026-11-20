"""Read and write the synchronization bookkeeping in PostgreSQL.

The synchronization service is the only writer of the queue and the link
table, but it still receives an open connection: like the rest of the project,
this module never imports a driver and the caller owns when to commit.

A claim is deliberately short. The worker leases a few rows, commits at once,
and only then calls Baserow. Holding a database transaction open during an
HTTP call would keep row locks for seconds and make a stalled network call
block every other writer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

CLAIM_OUTBOX = """
WITH claimed AS (
    SELECT id
    FROM sync_outbox
    WHERE processed_at IS NULL
      AND next_attempt_at IS NOT NULL
      AND next_attempt_at <= now()
    ORDER BY created_at, id
    FOR UPDATE SKIP LOCKED
    LIMIT %s
)
UPDATE sync_outbox AS outbox
SET attempts = outbox.attempts + 1,
    next_attempt_at = now() + make_interval(secs => %s)
FROM claimed
WHERE outbox.id = claimed.id
RETURNING outbox.id, outbox.entity_type, outbox.entity_id,
          outbox.event_type, outbox.attempts
"""

MARK_PROCESSED = """
UPDATE sync_outbox
SET processed_at = now(),
    last_error = NULL
WHERE id = %s
"""

MARK_FAILED = """
UPDATE sync_outbox
SET last_error = %s,
    next_attempt_at = CASE
        WHEN attempts >= %s THEN NULL
        ELSE now() + make_interval(secs => %s)
    END
WHERE id = %s
"""

LOAD_FICHE = {
    "CREATOR": "SELECT * FROM creator_fiche WHERE record_id = %s",
    "BUYER": "SELECT * FROM buyer_fiche WHERE record_id = %s",
}

LOAD_PLATFORMS = "SELECT * FROM platform ORDER BY name"

SELECT_LINK = """
SELECT baserow_row_id, sync_hash
FROM baserow_link
WHERE entity_type = %s AND entity_id = %s AND baserow_table_id = %s
"""

SAVE_LINK = """
INSERT INTO baserow_link (
    entity_type, entity_id, baserow_table_id, baserow_row_id,
    last_pushed_at, sync_hash
) VALUES (%s, %s, %s, %s, now(), %s)
ON CONFLICT (entity_type, entity_id, baserow_table_id)
DO UPDATE SET
    baserow_row_id = EXCLUDED.baserow_row_id,
    last_pushed_at = EXCLUDED.last_pushed_at,
    sync_hash = EXCLUDED.sync_hash
"""

# --- incoming events ------------------------------------------------------

STORE_EVENT = """
INSERT INTO baserow_event (
    external_event_id, table_id, row_id, event_type, payload
) VALUES (%s, %s, %s, %s, %s::jsonb)
ON CONFLICT (external_event_id) DO NOTHING
RETURNING id, status
"""

SELECT_EVENT = """
SELECT id, status FROM baserow_event
WHERE external_event_id = %s
FOR UPDATE
"""

MARK_EVENT = """
UPDATE baserow_event
SET status = %s, processed_at = now(), error = %s
WHERE id = %s
"""

NOTE_EVENT_ERROR = "UPDATE baserow_event SET error = %s WHERE id = %s"

LOAD_RECORD_FOR_ACTION = """
SELECT kind::text, workflow_status::text, criteria_version, score
FROM record
WHERE id = %s
FOR UPDATE
"""

INSERT_REVIEW_REQUEST = """
INSERT INTO review_request (
    record_id, action, note, requested_by, external_event_id
) VALUES (%s::uuid, %s::review_action, %s, %s, %s)
ON CONFLICT (external_event_id)
DO UPDATE SET note = EXCLUDED.note
RETURNING id
"""

FINISH_REVIEW_REQUEST = """
UPDATE review_request
SET processed_at = now(), resulting_event_id = %s
WHERE id = %s
"""

SELECT_WORKFLOW_EVENT = """
SELECT id FROM workflow_event WHERE external_event_id = %s
"""

TRANSITION_FOR_REVIEW = """
SELECT transition_record(
    %s::uuid, %s::workflow_status, %s, %s, 'WORKFLOW'::decision_type,
    %s, %s, %s::jsonb
)
"""

# --- evidence -------------------------------------------------------------

UPSERT_SOURCE = """
INSERT INTO source (url, normalized_url, kind)
VALUES (%s, %s, %s)
ON CONFLICT (normalized_url) DO UPDATE SET url = EXCLUDED.url
RETURNING id
"""

UPSERT_SNAPSHOT = """
INSERT INTO source_snapshot (source_id, consulted_at, query_used, service)
VALUES (%s, %s, %s, %s)
ON CONFLICT (source_id, consulted_at)
DO UPDATE SET
    query_used = COALESCE(EXCLUDED.query_used, source_snapshot.query_used),
    service = COALESCE(EXCLUDED.service, source_snapshot.service)
RETURNING id
"""

LINK_RECORD_SOURCE = """
INSERT INTO record_source (record_id, source_snapshot_id, role)
VALUES (%s, %s, %s)
ON CONFLICT (record_id, source_snapshot_id) DO NOTHING
"""

INSERT_FACT = """
INSERT INTO fact (
    record_id, key, value_text, value_number, value_boolean,
    proof_level, confidence, source_snapshot_id, recorded_by,
    external_event_id
) VALUES (
    %s, %s, %s, %s, %s,
    %s::proof_level, %s::confidence_level, %s, %s, %s
)
ON CONFLICT (external_event_id) DO NOTHING
RETURNING id
"""

SELECT_FACT_BY_EVENT = """
SELECT id, value_text, value_number, value_boolean,
       proof_level::text, confidence::text, is_current, recorded_at
FROM fact
WHERE external_event_id = %s
"""

# --- contacts -------------------------------------------------------------

RESOLVE_LINK = """
SELECT entity_type, entity_id
FROM baserow_link
WHERE baserow_table_id = %s AND baserow_row_id = %s
"""

LOAD_RECORD_STATUS = """
SELECT workflow_status::text
FROM record
WHERE id = %s
FOR UPDATE
"""

UPSERT_CONTACT = """
INSERT INTO contact (
    record_id, role, person_name, channel_type, channel_value,
    is_professional_public, source_url, source_date, status, notes
) VALUES (
    %s, %s, %s, %s::contact_channel, %s,
    %s, %s, %s, %s::contact_status, %s
)
ON CONFLICT (record_id, channel_type, lower(channel_value))
DO UPDATE SET
    role = EXCLUDED.role,
    person_name = EXCLUDED.person_name,
    is_professional_public = EXCLUDED.is_professional_public,
    source_url = EXCLUDED.source_url,
    source_date = EXCLUDED.source_date,
    status = EXCLUDED.status,
    notes = EXCLUDED.notes,
    updated_at = now()
RETURNING id
"""

INSERT_OPT_OUT_EVENT = """
INSERT INTO contact_event (
    contact_id, record_id, event_type, actor, notes, external_event_id
) VALUES (%s, %s, 'OPT_OUT', %s, %s, %s)
ON CONFLICT (external_event_id) DO NOTHING
RETURNING id
"""


@dataclass(frozen=True)
class OutboxItem:
    id: int
    entity_type: str
    entity_id: str
    event_type: str
    attempts: int


@dataclass(frozen=True)
class Link:
    row_id: int
    sync_hash: str | None


@dataclass(frozen=True)
class EventState:
    id: str
    status: str


def claim_outbox(connection, *, limit: int, lease_seconds: int) -> list[OutboxItem]:
    """Lease up to ``limit`` pending items and commit the lease immediately."""
    with connection.cursor() as cursor:
        cursor.execute(CLAIM_OUTBOX, (limit, lease_seconds))
        rows = cursor.fetchall()

    # The lease, not the transaction, protects the rows from another worker.
    connection.commit()

    return [
        OutboxItem(
            id=int(row[0]),
            entity_type=str(row[1]),
            entity_id=str(row[2]),
            event_type=str(row[3]),
            attempts=int(row[4]),
        )
        for row in rows
    ]


def mark_processed(connection, outbox_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(MARK_PROCESSED, (outbox_id,))


def mark_failed(
    connection,
    outbox_id: int,
    error: str,
    *,
    max_attempts: int,
    retry_seconds: int,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            MARK_FAILED,
            (error, max_attempts, retry_seconds, outbox_id),
        )


def load_fiche(connection, entity_type: str, entity_id: str) -> dict | None:
    statement = LOAD_FICHE.get(entity_type)
    if statement is None:
        raise ValueError(f"unsupported fiche type: {entity_type!r}")

    with connection.cursor() as cursor:
        cursor.execute(statement, (entity_id,))
        return _one_dict(cursor)


def load_platforms(connection) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(LOAD_PLATFORMS)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_link(
    connection, entity_type: str, entity_id: str, table_id: int
) -> Link | None:
    with connection.cursor() as cursor:
        cursor.execute(SELECT_LINK, (entity_type, entity_id, table_id))
        row = cursor.fetchone()
    if row is None:
        return None
    return Link(row_id=int(row[0]), sync_hash=row[1])


def save_link(
    connection,
    *,
    entity_type: str,
    entity_id: str,
    table_id: int,
    row_id: int,
    sync_hash: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            SAVE_LINK,
            (entity_type, entity_id, table_id, row_id, sync_hash),
        )


def store_event(
    connection,
    *,
    external_event_id: str,
    table_id: int,
    row_id: int,
    event_type: str,
    payload: dict,
) -> "EventState":
    """Insert an incoming event, or return the state of the one already known."""
    with connection.cursor() as cursor:
        cursor.execute(
            STORE_EVENT,
            (
                external_event_id,
                table_id,
                row_id,
                event_type,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        row = cursor.fetchone()
        if row is None:
            cursor.execute(SELECT_EVENT, (external_event_id,))
            row = cursor.fetchone()

    if row is None:  # pragma: no cover - the unique key guarantees a row
        raise RuntimeError(f"baserow event {external_event_id} disappeared")
    return EventState(id=str(row[0]), status=str(row[1]))


def mark_event(
    connection, event_id: str, status: str, error: str | None = None
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(MARK_EVENT, (status, error, event_id))


def note_event_error(connection, event_id: str, error: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(NOTE_EVENT_ERROR, (error, event_id))


def load_record_for_action(connection, record_id: str) -> dict | None:
    with connection.cursor() as cursor:
        cursor.execute(LOAD_RECORD_FOR_ACTION, (record_id,))
        return _one_dict(cursor)


def insert_review_request(
    connection,
    *,
    record_id: str,
    action: str,
    note: str | None,
    requested_by: str,
    external_event_id: str,
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            INSERT_REVIEW_REQUEST,
            (record_id, action, note, requested_by, external_event_id),
        )
        return str(cursor.fetchone()[0])


def finish_review_request(
    connection, request_id: str, workflow_event_id: str | None
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(FINISH_REVIEW_REQUEST, (workflow_event_id, request_id))


def find_workflow_event(connection, external_event_id: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(SELECT_WORKFLOW_EVENT, (external_event_id,))
        row = cursor.fetchone()
    return None if row is None else str(row[0])


def transition_for_review(
    connection,
    *,
    record_id: str,
    target: str,
    justification: str,
    actor: str,
    criteria_version: str,
    external_event_id: str,
    payload: dict,
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            TRANSITION_FOR_REVIEW,
            (
                record_id,
                target,
                justification,
                actor,
                criteria_version,
                external_event_id,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        return str(cursor.fetchone()[0])


def resolve_link(connection, table_id: int, row_id: int) -> tuple[str, str] | None:
    with connection.cursor() as cursor:
        cursor.execute(RESOLVE_LINK, (table_id, row_id))
        row = cursor.fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1])


def upsert_source(
    connection, *, url: str, normalized_url: str, kind: str | None
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(UPSERT_SOURCE, (url, normalized_url, kind))
        return str(cursor.fetchone()[0])


def upsert_snapshot(
    connection,
    *,
    source_id: str,
    consulted_at: str,
    query_used: str | None,
    service: str | None,
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            UPSERT_SNAPSHOT,
            (source_id, consulted_at, query_used, service),
        )
        return str(cursor.fetchone()[0])


def link_record_source(
    connection,
    *,
    record_id: str,
    snapshot_id: str,
    role: str = "OTHER",
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(LINK_RECORD_SOURCE, (record_id, snapshot_id, role))


def insert_fact(
    connection,
    *,
    record_id: str,
    key: str,
    value_column: str,
    value,
    proof_level: str,
    confidence: str,
    snapshot_id: str,
    recorded_by: str,
    external_event_id: str,
) -> str | None:
    text = number = boolean = None
    if value_column == "value_text":
        text = value
    elif value_column == "value_number":
        number = value
    elif value_column == "value_boolean":
        boolean = value
    else:
        raise ValueError(f"unsupported fact value column: {value_column!r}")

    with connection.cursor() as cursor:
        cursor.execute(
            INSERT_FACT,
            (
                record_id,
                key,
                text,
                number,
                boolean,
                proof_level,
                confidence,
                snapshot_id,
                recorded_by,
                external_event_id,
            ),
        )
        row = cursor.fetchone()
    return None if row is None else str(row[0])


def find_fact(connection, external_event_id: str) -> str | None:
    fact = load_fact_by_event(connection, external_event_id)
    return None if fact is None else str(fact["id"])


def load_fact_by_event(connection, external_event_id: str) -> dict | None:
    with connection.cursor() as cursor:
        cursor.execute(SELECT_FACT_BY_EVENT, (external_event_id,))
        return _one_dict(cursor)


def load_record_status(connection, record_id: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(LOAD_RECORD_STATUS, (record_id,))
        row = cursor.fetchone()
    return None if row is None else str(row[0])


def upsert_contact(
    connection,
    *,
    record_id: str,
    role: str,
    person_name: str | None,
    channel_type: str,
    channel_value: str,
    is_professional_public: bool,
    source_url: str,
    source_date: str,
    status: str,
    notes: str | None,
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            UPSERT_CONTACT,
            (
                record_id,
                role,
                person_name,
                channel_type,
                channel_value,
                is_professional_public,
                source_url,
                source_date,
                status,
                notes,
            ),
        )
        return str(cursor.fetchone()[0])


def insert_opt_out_event(
    connection,
    *,
    contact_id: str,
    record_id: str,
    actor: str,
    notes: str | None,
    external_event_id: str,
) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            INSERT_OPT_OUT_EVENT,
            (contact_id, record_id, actor, notes, external_event_id),
        )
        row = cursor.fetchone()
    return None if row is None else str(row[0])


def _one_dict(cursor) -> dict | None:
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [column[0] for column in cursor.description]
    return dict(zip(columns, row))
