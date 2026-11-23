"""Structural guards for the synchronization migration.

These tests do not need a server. They keep the two schema files aligned: a new
installation reads 001, an existing one applies 004, and both must carry the
queue column, the one-pending-per-fiche index and the same triggers.
"""

from pathlib import Path

SCHEMA = Path(__file__).resolve().parents[1] / "db" / "postgres" / "001_schema.sql"
MIGRATION = Path(__file__).resolve().parents[1] / "db" / "postgres" / "004_sync.sql"
EVIDENCE = Path(__file__).resolve().parents[1] / "db" / "postgres" / "005_evidence.sql"

REQUIRED_TRIGGERS = {
    "record_enqueue_sync",
    "creator_enqueue_sync",
    "buyer_enqueue_sync",
    "creator_platform_enqueue_sync",
}


def test_both_files_define_the_same_sync_queue_objects():
    for path in (SCHEMA, MIGRATION):
        text = path.read_text(encoding="utf-8")
        assert "next_attempt_at" in text
        assert "sync_outbox_pending_entity_idx" in text
        assert "enqueue_record_sync" in text
        for trigger in REQUIRED_TRIGGERS:
            assert trigger in text, (path.name, trigger)


def test_the_migration_is_idempotent():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS" in text
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in text
    assert "CREATE OR REPLACE FUNCTION" in text
    assert text.count("DROP TRIGGER IF EXISTS") == len(REQUIRED_TRIGGERS)


def test_the_queue_keeps_one_pending_change_per_fiche():
    text = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE UNIQUE INDEX sync_outbox_pending_entity_idx" in text
    assert "ON sync_outbox (entity_type, entity_id)" in text
    assert "WHERE processed_at IS NULL" in text


def test_the_evidence_identity_is_in_both_files():
    for path in (SCHEMA, EVIDENCE):
        text = path.read_text(encoding="utf-8")
        assert "external_event_id" in text
        assert "fact_external_event_id_idx" in text
    assert "ADD COLUMN IF NOT EXISTS external_event_id" in (
        EVIDENCE.read_text(encoding="utf-8")
    )
