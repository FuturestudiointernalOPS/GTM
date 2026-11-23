"""End-to-end tests for the PostgreSQL -> Baserow push service.

No server and no network: a fake connection answers the queue and link
statements, and a fake client records the rows it was asked to create or
update. The checks focus on what matters in production: no duplicate row, no
overwrite of a human field, and a readable failure that can be retried.
"""

from integrations.baserow import BaserowError
from processing import baserow_mapping
from workflows import sync_push

CREATORS = 11
BUYERS = 12
PLATFORMS = 13
RECORD_ID = "9c8f4b1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b"


def creator_fiche(**overrides):
    values = {
        "record_id": RECORD_ID,
        "reference": "CR-000001",
        "workflow_status": "SCORED",
        "display_name": "Игрок",
        "main_platform": "vk_video",
        "handle": "player",
        "platform_url": "https://vk.com/player",
        "gaming_share": 87.5,
        "assigned_to": "analyst",
        "notes": "human note",
    }
    values.update(overrides)
    return values


def buyer_fiche(**overrides):
    values = {
        "record_id": RECORD_ID,
        "reference": "BY-000001",
        "workflow_status": "SCORED",
        "legal_name": "ООО Ромашка",
        "inn": "1234567890",
        "tax_id_type": "INN",
        "assigned_to": "analyst",
        "notes": "human note",
    }
    values.update(overrides)
    return values


def platform_row(**overrides):
    values = {
        "id": "6f1e4a7c-1111-2222-3333-444455556666",
        "name": "vk_video",
        "aliases": ["vk"],
        "coverage_status": "COVERED",
        "stable_id_available": True,
        "risk_level": "LOW",
        "creator_campaign_allowed": True,
        "source": "registry",
        "source_date": "2026-11-01",
        "checked_at": "2026-11-01",
        "version": "2026-11",
    }
    values.update(overrides)
    return values


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self._rows = []
        self._one = None
        self.description = None

    def execute(self, sql, params=()):
        statement = " ".join(sql.split())
        state = self.connection

        if "INSERT INTO baserow_link" in statement:
            entity_type, entity_id, table_id, row_id, sync_hash = params
            state.links[(entity_type, str(entity_id), int(table_id))] = (
                int(row_id),
                sync_hash,
            )
            self._rows = []
            return

        if "SELECT baserow_row_id, sync_hash FROM baserow_link" in statement:
            key = (str(params[0]), str(params[1]), int(params[2]))
            link = state.links.get(key)
            self._one = link
            self.description = [("baserow_row_id",), ("sync_hash",)]
            return

        if "FROM creator_fiche" in statement:
            row = state.fiches.get(("CREATOR", str(params[0])))
            self._set_rows([row] if row is not None else [])
            return

        if "FROM buyer_fiche" in statement:
            row = state.fiches.get(("BUYER", str(params[0])))
            self._set_rows([row] if row is not None else [])
            return

        if "SELECT * FROM platform ORDER BY name" in statement:
            self._set_rows(state.platforms)
            return

        if "WITH claimed AS" in statement:
            limit = int(params[0])
            claimed = state.claim(limit)
            self._set_rows(claimed)
            return

        if "UPDATE sync_outbox" in statement and "processed_at = now()" in statement:
            state.processed.add(int(params[0]))
            self._rows = []
            return

        if "UPDATE sync_outbox" in statement and "last_error" in statement:
            error, max_attempts, retry_seconds, outbox_id = params
            state.fail(int(outbox_id), error, int(max_attempts))
            self._rows = []
            return

        raise AssertionError(f"unexpected statement: {statement}")

    def _set_rows(self, rows):
        rows = list(rows)
        self.description = [(name,) for name in rows[0].keys()] if rows else []
        self._rows = [tuple(row.values()) for row in rows]
        self._one = self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._one

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, outbox, *, fiches=None, platforms=None, links=None):
        self.outbox = [dict(item) for item in outbox]
        self.fiches = dict(fiches or {})
        self.platforms = list(platforms or [])
        self.links = dict(links or {})
        self.processed = set()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def claim(self, limit):
        claimed = [item for item in self.outbox if item["id"] not in self.processed][
            :limit
        ]
        for item in claimed:
            item["attempts"] = item.get("attempts", 0) + 1
        return claimed

    def fail(self, outbox_id, error, max_attempts):
        for item in self.outbox:
            if item["id"] == outbox_id:
                item["last_error"] = error
                item["next_attempt_at"] = (
                    None if item["attempts"] >= max_attempts else "later"
                )

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeRowClient:
    def __init__(self, *, fail_tables=None):
        self.tables = [
            {"id": CREATORS, "name": "Createurs"},
            {"id": BUYERS, "name": "Acheteurs"},
            {"id": PLATFORMS, "name": "Plateformes"},
        ]
        self.rows = {}
        self.created = []
        self.updated = []
        self.fail_tables = set(fail_tables or ())
        self._next_id = 100

    def list_tables(self, database_id):
        return self.tables

    def find_row(self, table_id, field, value):
        return self.rows.get((table_id, field, str(value)))

    def create_row(self, table_id, fields):
        if table_id in self.fail_tables:
            raise BaserowError("Baserow refused POST")
        self._next_id += 1
        row = {"id": self._next_id, **fields}
        if "record_id" in fields:
            self.rows[(table_id, "record_id", str(fields["record_id"]))] = row
        if "platform_id" in fields:
            self.rows[(table_id, "platform_id", str(fields["platform_id"]))] = row
        self.created.append((table_id, dict(fields), row["id"]))
        return row

    def update_row(self, table_id, row_id, fields):
        if table_id in self.fail_tables:
            raise BaserowError("Baserow refused PATCH")
        self.updated.append((table_id, row_id, dict(fields)))
        return {"id": row_id}

    def close(self):
        return None


def outbox_item(entity_type="CREATOR", entity_id=RECORD_ID, item_id=1):
    return {
        "id": item_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "event_type": "UPSERT",
        "attempts": 0,
    }


def test_a_new_creator_is_created_with_only_database_fields():
    connection = FakeConnection(
        [outbox_item()],
        fiches={("CREATOR", RECORD_ID): creator_fiche()},
        platforms=[platform_row()],
    )
    client = FakeRowClient()

    report = sync_push.push_outbox(connection, client, database_id=1)

    assert report.ok
    assert report.platforms == ["vk_video"]
    assert report.pushed == [f"CREATOR:{RECORD_ID}"]

    platform_row_id = client.created[0][2]
    creator_call = [call for call in client.created if call[0] == CREATORS][0]
    created = creator_call[1]
    assert created["display_name"] == "Игрок"
    assert created["main_platform"] == [platform_row_id]
    assert created["sync_status"] == "SYNCED"
    assert created["sync_error"] is None
    assert "assigned_to" not in created
    assert "notes" not in created

    assert connection.processed == {1}
    assert (CREATORS, "record_id", RECORD_ID) in client.rows
    assert connection.links[("CREATOR", RECORD_ID, CREATORS)][0] == creator_call[2]


def test_a_buyer_uses_the_buyer_table():
    connection = FakeConnection(
        [outbox_item(entity_type="BUYER")],
        fiches={("BUYER", RECORD_ID): buyer_fiche()},
    )
    client = FakeRowClient()

    report = sync_push.push_outbox(connection, client, database_id=1)

    assert report.pushed == [f"BUYER:{RECORD_ID}"]
    created = client.created[0]
    assert created[0] == BUYERS
    assert created[1]["legal_name"] == "ООО Ромашка"
    assert "assigned_to" not in created[1]


def test_an_unchanged_fiche_is_not_sent_again():
    fiche = creator_fiche(main_platform=None)
    fingerprint = baserow_mapping.payload_hash(baserow_mapping.build_creator_row(fiche))
    connection = FakeConnection(
        [outbox_item()],
        fiches={("CREATOR", RECORD_ID): fiche},
        links={("CREATOR", RECORD_ID, CREATORS): (55, fingerprint)},
    )
    client = FakeRowClient()

    report = sync_push.push_outbox(connection, client, database_id=1)

    assert report.skipped == [f"CREATOR:{RECORD_ID}"]
    assert client.created == []
    assert client.updated == []
    assert connection.processed == {1}


def test_a_changed_fiche_updates_the_linked_row():
    connection = FakeConnection(
        [outbox_item()],
        fiches={("CREATOR", RECORD_ID): creator_fiche(main_platform=None)},
        links={("CREATOR", RECORD_ID, CREATORS): (55, "old-fingerprint")},
    )
    client = FakeRowClient()

    report = sync_push.push_outbox(connection, client, database_id=1)

    assert report.pushed == [f"CREATOR:{RECORD_ID}"]
    assert len(client.created) == 0
    table, row_id, fields = client.updated[0]
    assert (table, row_id) == (CREATORS, 55)
    assert fields["display_name"] == "Игрок"
    assert fields["sync_status"] == "SYNCED"
    assert connection.links[("CREATOR", RECORD_ID, CREATORS)][0] == 55


def test_a_failure_is_recorded_and_can_be_retried():
    connection = FakeConnection(
        [outbox_item()],
        fiches={("CREATOR", RECORD_ID): creator_fiche(main_platform=None)},
        links={("CREATOR", RECORD_ID, CREATORS): (55, "old-fingerprint")},
    )
    client = FakeRowClient(fail_tables={CREATORS})

    report = sync_push.push_outbox(
        connection,
        client,
        database_id=1,
        max_attempts=1,
        retry_seconds=30,
    )

    assert not report.ok
    assert report.failed[0][0] == f"CREATOR:{RECORD_ID}"
    assert "refused PATCH" in report.failed[0][1]
    item = connection.outbox[0]
    assert item["last_error"] == report.failed[0][1]
    assert item["next_attempt_at"] is None
    assert connection.processed == set()
    assert connection.rollbacks == 1


def test_an_unsupported_entity_is_refused_with_a_readable_error():
    connection = FakeConnection([outbox_item(entity_type="CONTACT")])
    client = FakeRowClient()

    report = sync_push.push_outbox(connection, client, database_id=1)

    assert not report.ok
    assert report.failed[0][0] == f"CONTACT:{RECORD_ID}"
    assert "unsupported entity type" in report.failed[0][1]


def test_configured_table_ids_avoid_the_schema_call():
    connection = FakeConnection(
        [outbox_item()],
        fiches={("CREATOR", RECORD_ID): creator_fiche(main_platform=None)},
    )
    client = FakeRowClient()

    sync_push.push_outbox(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
    )

    assert client.created[0][0] == CREATORS
