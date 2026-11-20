"""Tests for the Baserow contacts -> PostgreSQL service.

The fake connection keeps the contacts, the opt-out events and the record
status. The checks cover the two rules that matter most: a non-public contact
is refused, and an opt-out is immediate and never reversed automatically.
"""

from workflows import sync_contacts

CREATORS = 11
BUYERS = 12
PLATFORMS = 13
CONTACTS = 14
RECORD_ID = "9c8f4b1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b"


def contact_row(**overrides):
    values = {
        "id": 21,
        "record_type": "CREATOR",
        "creator": [{"id": 7, "value": "Игрок"}],
        "acheteur": [],
        "role": "ADVERTISING_CONTACT",
        "person_name": "Иван",
        "channel_type": "EMAIL",
        "channel_value": "ivan@example.test",
        "is_professional_public": True,
        "source_url": "https://example.test/contact",
        "source_date": "2026-11-01",
        "status": "ACTIVE",
        "notes": "public contact page",
    }
    values.update(overrides)
    return values


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self._one = None
        self.description = None

    def execute(self, sql, params=()):
        statement = " ".join(sql.split())
        state = self.connection

        if "SELECT entity_type, entity_id FROM baserow_link" in statement:
            self._one = state.links.get((params[0], params[1]))
            return

        if "SELECT workflow_status::text" in statement:
            if params[0] != RECORD_ID:
                self._one = None
            else:
                self._one = (state.record_status,)
            return

        if "INSERT INTO contact_event" in statement:
            contact_id, record_id, actor, notes, external_event_id = params
            if external_event_id in state.event_ids:
                self._one = None
                return
            state.event_ids.add(external_event_id)
            state.contact_events.append(
                {
                    "contact_id": contact_id,
                    "record_id": record_id,
                    "actor": actor,
                    "notes": notes,
                }
            )
            state.apply_opt_out(record_id)
            self._one = (f"event-{len(state.contact_events)}",)
            return

        if "INSERT INTO contact (" in statement:
            (
                record_id,
                role,
                person_name,
                channel_type,
                channel_value,
                professional,
                source_url,
                source_date,
                status,
                notes,
            ) = params
            key = (record_id, channel_type, channel_value.lower())
            contact = state.contacts.get(key)
            if contact is None:
                contact = state.new_contact(record_id, channel_value)
                state.contacts[key] = contact
            contact.update(
                {
                    "role": role,
                    "person_name": person_name,
                    "channel_type": channel_type,
                    "is_professional_public": professional,
                    "source_url": source_url,
                    "source_date": source_date,
                    "status": status,
                    "notes": notes,
                }
            )
            self._one = (contact["id"],)
            return

        raise AssertionError(f"unexpected statement: {statement}")

    def fetchone(self):
        return self._one

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, *, status="APPROVED", links=None):
        self.record_status = status
        default_links = {(CREATORS, 7): ("CREATOR", RECORD_ID)}
        self.links = dict(default_links if links is None else links)
        self.contacts = {}
        self.contact_events = []
        self.event_ids = set()
        self.workflow_events = []
        self.commits = 0
        self.rollbacks = 0
        self._contact_seq = 0

    def cursor(self):
        return FakeCursor(self)

    def new_contact(self, record_id, channel_value):
        self._contact_seq += 1
        return {
            "id": f"contact-{self._contact_seq}",
            "record_id": record_id,
            "channel_value": channel_value,
        }

    def apply_opt_out(self, record_id):
        previous = self.record_status
        self.record_status = "OPT_OUT"
        for contact in self.contacts.values():
            if contact["record_id"] == record_id:
                contact["status"] = "OPT_OUT"
        if previous != "OPT_OUT":
            self.workflow_events.append((record_id, previous, "OPT_OUT"))

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeRowClient:
    def __init__(self, rows, *, fail_updates=0):
        self.rows = rows
        self.updated = []
        self.fail_updates = fail_updates

    def iter_rows(self, table_id, *, max_pages=50):
        yield from self.rows.get(table_id, [])

    def update_row(self, table_id, row_id, fields):
        if self.fail_updates > 0:
            self.fail_updates -= 1
            raise RuntimeError("Baserow unavailable")
        self.updated.append((table_id, row_id, dict(fields)))
        return {"id": row_id}

    def close(self):
        return None


def test_a_professional_contact_is_stored_and_acknowledged():
    connection = FakeConnection()
    client = FakeRowClient({CONTACTS: [contact_row()]})

    report = sync_contacts.pull_contacts(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        contacts=CONTACTS,
    )

    assert report.ok
    assert report.applied == ["CONTACT:21"]
    contact = next(iter(connection.contacts.values()))
    assert contact["status"] == "ACTIVE"
    assert contact["channel_value"] == "ivan@example.test"
    assert client.updated[-1][2]["sync_status"] == "SYNCED"


def test_a_non_public_contact_is_refused():
    connection = FakeConnection()
    client = FakeRowClient({CONTACTS: [contact_row(is_professional_public=False)]})

    report = sync_contacts.pull_contacts(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        contacts=CONTACTS,
    )

    assert not report.ok
    assert "K-01" in report.rejected[0][1]
    assert connection.contacts == {}
    assert client.updated[-1][2]["sync_status"] == "ERROR"


def test_an_opt_out_blocks_the_record_immediately():
    connection = FakeConnection(status="APPROVED")
    client = FakeRowClient({CONTACTS: [contact_row(status="OPT_OUT")]})

    report = sync_contacts.pull_contacts(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        contacts=CONTACTS,
    )

    assert report.applied == ["CONTACT:21"]
    assert connection.record_status == "OPT_OUT"
    assert len(connection.contact_events) == 1
    assert connection.workflow_events == [(RECORD_ID, "APPROVED", "OPT_OUT")]


def test_an_active_contact_cannot_reactivate_an_opted_out_record():
    connection = FakeConnection(status="OPT_OUT")
    client = FakeRowClient({CONTACTS: [contact_row(status="ACTIVE")]})

    report = sync_contacts.pull_contacts(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        contacts=CONTACTS,
    )

    assert report.applied == ["CONTACT:21"]
    assert connection.record_status == "OPT_OUT"
    contact = next(iter(connection.contacts.values()))
    assert contact["status"] == "OPT_OUT"
    assert len(connection.contact_events) == 1
    assert connection.workflow_events == []


def test_an_unsynchronised_linked_record_is_refused():
    connection = FakeConnection(links={})
    client = FakeRowClient({CONTACTS: [contact_row()]})

    report = sync_contacts.pull_contacts(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        contacts=CONTACTS,
    )

    assert not report.ok
    assert "non synchronisée" in report.rejected[0][1]
    assert connection.contacts == {}


def test_a_buyer_contact_uses_the_buyer_link():
    connection = FakeConnection(links={(BUYERS, 9): ("BUYER", RECORD_ID)})
    client = FakeRowClient(
        {
            CONTACTS: [
                contact_row(
                    record_type="BUYER",
                    creator=[],
                    acheteur=[{"id": 9, "value": "ООО"}],
                )
            ]
        }
    )

    report = sync_contacts.pull_contacts(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        contacts=CONTACTS,
    )

    assert report.applied == ["CONTACT:21"]
    assert next(iter(connection.contacts.values()))["record_id"] == RECORD_ID
