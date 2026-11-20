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
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [column[0] for column in cursor.description]
        return dict(zip(columns, row))


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
