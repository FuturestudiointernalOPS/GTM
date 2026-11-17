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
