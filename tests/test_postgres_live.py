"""Opt-in checks against a real PostgreSQL database.

They are skipped unless ``GTM_TEST_DATABASE_URL`` names a database where
``db/postgres/001_schema.sql`` and ``db/postgres/002_seed_reference.sql`` have
already been applied::

    GTM_TEST_DATABASE_URL=postgresql://user:pass@host/gtm pytest tests/test_postgres_live.py

The smoke-test file is replayed as-is; it ends with ``ROLLBACK``, so it leaves
no row behind. These tests are the missing bridge between the fake connections
used by the offline suite and a real server.
"""

import os
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

DSN = os.getenv("GTM_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="GTM_TEST_DATABASE_URL is not set"),
]

ROOT = Path(__file__).resolve().parents[1]
SMOKE_TEST = ROOT / "db" / "postgres" / "smoke_test.sql"


def test_the_reference_criteria_version_is_present():
    with psycopg.connect(DSN) as connection:
        row = connection.execute(
            "SELECT version FROM criteria_version WHERE version = '1.4'"
        ).fetchone()

    assert row == ("1.4",)


def test_the_transition_entry_point_exists():
    with psycopg.connect(DSN) as connection:
        row = connection.execute(
            "SELECT 1 FROM information_schema.routines "
            "WHERE routine_name = 'transition_record'"
        ).fetchone()

    assert row == (1,)


def test_the_smoke_test_replays_and_leaves_nothing():
    sql = SMOKE_TEST.read_text(encoding="utf-8")

    with psycopg.connect(DSN) as connection:
        cursor = psycopg.ClientCursor(connection)
        cursor.execute(sql)

    with psycopg.connect(DSN) as connection:
        remaining = connection.execute(
            "SELECT count(*) FROM creator WHERE display_name = 'Тестовый креатор'"
        ).fetchone()[0]

    assert remaining == 0


def test_a_discovered_contact_enqueues_its_fiche_and_never_overwrites():
    from integrations import sync_store

    with psycopg.connect(DSN) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "INSERT INTO record (kind, criteria_version, workflow_status) "
                "VALUES ('CREATOR', '1.4', 'POOL') RETURNING id"
            )
            record_id = str(cursor.fetchone()[0])
            cursor.execute(
                "INSERT INTO creator (record_id, display_name) VALUES (%s, %s)",
                (record_id, "contact-live-test"),
            )
            cursor.execute("DELETE FROM sync_outbox WHERE entity_id = %s", (record_id,))

            first = sync_store.insert_discovered_contact(
                connection,
                record_id=record_id,
                role="MARKETING",
                person_name=None,
                channel_type="EMAIL",
                channel_value="live-contact@example.invalid",
                source_url="https://example.invalid/one",
                source_date="2026-11-23",
                notes="first",
            )
            pending = cursor.execute(
                "SELECT count(*) FROM sync_outbox "
                "WHERE entity_id = %s AND processed_at IS NULL",
                (record_id,),
            ).fetchone()[0]
            assert pending == 1

            second = sync_store.insert_discovered_contact(
                connection,
                record_id=record_id,
                role="AGENCY",
                person_name="Someone",
                channel_type="EMAIL",
                channel_value="LIVE-CONTACT@example.invalid",
                source_url="https://example.invalid/two",
                source_date="2026-11-24",
                notes="second",
            )
            assert second == first
            stored = cursor.execute(
                "SELECT role, source_url, notes FROM contact WHERE id = %s",
                (first,),
            ).fetchone()
            assert stored == (
                "MARKETING",
                "https://example.invalid/one",
                "first",
            )
        finally:
            connection.rollback()


def test_the_contact_writer_stores_a_verified_contact():
    from integrations import postgres
    from processing.contacts import PublicContact

    with psycopg.connect(DSN) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "INSERT INTO record (kind, criteria_version, workflow_status) "
                "VALUES ('CREATOR', '1.4', 'POOL') RETURNING id"
            )
            record_id = str(cursor.fetchone()[0])
            cursor.execute(
                "INSERT INTO creator (record_id, display_name) VALUES (%s, %s)",
                (record_id, "contact-writer-test"),
            )

            stored = postgres.write_contacts(
                connection,
                record_id=record_id,
                contacts=(
                    PublicContact(
                        role="MARKETING",
                        channel_type="EMAIL",
                        channel_value="writer@example.invalid",
                        description="contact presse",
                        quote="Пишите: writer@example.invalid",
                    ),
                ),
                source_url="https://example.invalid/profile",
                read_at="2026-11-23T12:00:00+00:00",
            )

            assert len(stored) == 1
            row = cursor.execute(
                "SELECT channel_value, source_date::text, verification_status "
                "FROM contact WHERE id = %s",
                (stored[0],),
            ).fetchone()
            assert row == ("writer@example.invalid", "2026-11-23", "PENDING")
        finally:
            connection.rollback()


def test_the_sync_outbox_and_a_review_action_round_trip():
    with psycopg.connect(DSN) as connection:
        sync_ready = connection.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'sync_outbox' AND column_name = 'next_attempt_at'"
        ).fetchone()
        if not sync_ready:
            pytest.skip("004_sync.sql is not applied")

        cursor = connection.cursor()
        try:
            cursor.execute(
                "INSERT INTO record (kind, criteria_version, workflow_status) "
                "VALUES ('CREATOR', '1.4', 'POOL') RETURNING id"
            )
            record_id = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO creator (record_id, display_name) VALUES (%s, %s)",
                (record_id, "live-sync-test"),
            )

            pending = cursor.execute(
                "SELECT count(*) FROM sync_outbox "
                "WHERE entity_type = 'CREATOR' AND entity_id = %s",
                (record_id,),
            ).fetchone()[0]
            assert pending == 1

            cursor.execute(
                "INSERT INTO baserow_event "
                "(external_event_id, table_id, row_id, event_type, payload) "
                "VALUES ('live-test:1', 1, 1, 'REVIEW_ACTION', '{}')"
            )
            cursor.execute(
                "INSERT INTO review_request "
                "(record_id, action, note, requested_by, external_event_id) "
                "VALUES (%s, 'APPROVE', 'live test', 'analyst', 'live-test:1')",
                (record_id,),
            )
            cursor.execute(
                "SELECT transition_record("
                "%s::uuid, 'APPROVED'::workflow_status, 'live test', 'analyst', "
                "'WORKFLOW'::decision_type, '1.4', 'live-test:1', '{}'::jsonb)",
                (record_id,),
            )
            status = cursor.execute(
                "SELECT workflow_status FROM record WHERE id = %s", (record_id,)
            ).fetchone()[0]

            assert status == "APPROVED"
        finally:
            connection.rollback()
