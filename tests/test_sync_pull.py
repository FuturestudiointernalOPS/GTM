"""Tests for the Baserow -> PostgreSQL review action service.

The fake connection keeps the journal, the requests and the record status; the
fake client yields Baserow rows and records the acknowledgements. The tests
focus on the hard parts: replay, refusal, and an acknowledgement that fails
after the database move was committed.
"""

from integrations.baserow import BaserowError
from workflows import sync_pull

CREATORS = 11
BUYERS = 12
PLATFORMS = 13
RECORD_ID = "9c8f4b1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b"


def action_row(action="APPROVE", **overrides):
    values = {
        "id": 7,
        "record_id": RECORD_ID,
        "review_action": action,
        "review_action_note": "preuves vérifiées",
        "review_action_at": "2026-11-20T10:00:00Z",
        "assigned_to": "analyste",
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

        if "INSERT INTO baserow_event" in statement:
            external_event_id = params[0]
            event = state.events.get(external_event_id)
            if event is None:
                event = state.new_event()
                state.events[external_event_id] = event
                self._one = (event["id"], event["status"])
            else:
                self._one = None
            self.description = [("id",), ("status",)]
            return

        if "SELECT id, status FROM baserow_event" in statement:
            event = state.events.get(params[0])
            self._one = None if event is None else (event["id"], event["status"])
            self.description = [("id",), ("status",)]
            return

        if "UPDATE baserow_event" in statement and "SET status" in statement:
            status, error, event_id = params
            event = state.event_by_id(event_id)
            event["status"] = status
            event["error"] = error
            event["processed"] = True
            return

        if "UPDATE baserow_event" in statement and "SET error" in statement:
            error, event_id = params
            state.event_by_id(event_id)["error"] = error
            return

        if "SELECT kind::text, workflow_status::text" in statement:
            if params[0] != state.record["record_id"]:
                self._one = None
                self.description = []
            else:
                self._one = (
                    state.record["kind"],
                    state.record["workflow_status"],
                    state.record["criteria_version"],
                    state.record["score"],
                )
                self.description = [
                    ("kind",),
                    ("workflow_status",),
                    ("criteria_version",),
                    ("score",),
                ]
            return

        if "INSERT INTO review_request" in statement:
            record_id, action, note, requested_by, external_event_id = params
            request = state.requests.get(external_event_id)
            if request is None:
                request = state.new_request(
                    record_id, action, note, requested_by, external_event_id
                )
                state.requests[external_event_id] = request
            else:
                request["note"] = note
            self._one = (request["id"],)
            return

        if "UPDATE review_request" in statement:
            workflow_event_id, request_id = params
            state.request_by_id(request_id)["resulting_event_id"] = workflow_event_id
            return

        if "SELECT id FROM workflow_event" in statement:
            event_id = state.workflow_events.get(params[0])
            self._one = None if event_id is None else (event_id,)
            return

        if "SELECT transition_record" in statement:
            record_id, target, justification, actor, criteria, external_id, payload = (
                params
            )
            event_id = state.new_workflow_event(
                record_id, target, justification, actor, external_id
            )
            state.record["workflow_status"] = target
            self._one = (event_id,)
            return

        raise AssertionError(f"unexpected statement: {statement}")

    def fetchone(self):
        return self._one

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, *, kind="CREATOR", status="POOL"):
        self.record = {
            "record_id": RECORD_ID,
            "kind": kind,
            "workflow_status": status,
            "criteria_version": "1.4",
            "score": 80,
        }
        self.events = {}
        self.workflow_events = {}
        self.requests = {}
        self.commits = 0
        self.rollbacks = 0
        self._event_seq = 0
        self._workflow_seq = 0
        self._request_seq = 0

    def cursor(self):
        return FakeCursor(self)

    def new_event(self):
        self._event_seq += 1
        return {
            "id": f"event-{self._event_seq}",
            "status": "PENDING",
            "error": None,
            "processed": False,
        }

    def event_by_id(self, event_id):
        for event in self.events.values():
            if event["id"] == event_id:
                return event
        raise AssertionError(f"unknown event id {event_id}")

    def new_workflow_event(self, record_id, target, justification, actor, external_id):
        existing = self.workflow_events.get(external_id)
        if existing is not None:
            return existing
        self._workflow_seq += 1
        event_id = f"workflow-{self._workflow_seq}"
        self.workflow_events[external_id] = event_id
        return event_id

    def new_request(self, record_id, action, note, requested_by, external_event_id):
        self._request_seq += 1
        return {
            "id": f"request-{self._request_seq}",
            "record_id": record_id,
            "action": action,
            "note": note,
            "requested_by": requested_by,
            "external_event_id": external_event_id,
            "resulting_event_id": None,
        }

    def request_by_id(self, request_id):
        for request in self.requests.values():
            if request["id"] == request_id:
                return request
        raise AssertionError(f"unknown request id {request_id}")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeRowClient:
    def __init__(self, rows=None, *, fail_updates=0):
        self.rows = rows or {}
        self.updated = []
        self.fail_updates = fail_updates

    def iter_rows(self, table_id, *, max_pages=50):
        yield from self.rows.get(table_id, [])

    def update_row(self, table_id, row_id, fields):
        if self.fail_updates > 0:
            self.fail_updates -= 1
            raise BaserowError("Baserow refused PATCH")
        self.updated.append((table_id, row_id, dict(fields)))
        return {"id": row_id}

    def close(self):
        return None


def test_approve_moves_the_record_and_acknowledges():
    connection = FakeConnection()
    client = FakeRowClient({CREATORS: [action_row()]})

    report = sync_pull.pull_actions(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
    )

    assert report.ok
    assert report.applied == [f"CREATOR:{RECORD_ID}:APPROVE"]
    assert connection.record["workflow_status"] == "APPROVED"
    assert len(connection.workflow_events) == 1
    request = next(iter(connection.requests.values()))
    assert request["action"] == "APPROVE"
    assert request["requested_by"] == "analyste"
    assert request["resulting_event_id"] is not None

    event = next(iter(connection.events.values()))
    assert event["status"] == "APPLIED"

    table, row_id, fields = client.updated[-1]
    assert (table, row_id) == (CREATORS, 7)
    assert fields["review_action_processed"] is True
    assert fields["sync_status"] == "SYNCED"


def test_replaying_the_same_row_does_not_create_a_second_decision():
    connection = FakeConnection()
    client = FakeRowClient({CREATORS: [action_row()]})

    first = sync_pull.pull_actions(
        connection, client, creators=CREATORS, buyers=BUYERS, platforms=PLATFORMS
    )
    second = sync_pull.pull_actions(
        connection, client, creators=CREATORS, buyers=BUYERS, platforms=PLATFORMS
    )

    assert first.applied
    assert second.skipped == [f"CREATOR:{RECORD_ID}:APPROVE"]
    assert len(connection.workflow_events) == 1


def test_a_refused_action_is_shown_and_leaves_the_status_unchanged():
    connection = FakeConnection()
    row = action_row(review_action_note=None, assigned_to=None)
    client = FakeRowClient({CREATORS: [row]})

    report = sync_pull.pull_actions(
        connection, client, creators=CREATORS, buyers=BUYERS, platforms=PLATFORMS
    )

    assert not report.ok
    assert report.rejected[0][0] == f"CREATOR:{RECORD_ID}:APPROVE"
    assert "justification" in report.rejected[0][1]
    assert connection.record["workflow_status"] == "POOL"
    assert connection.workflow_events == {}
    assert next(iter(connection.events.values()))["status"] == "REJECTED"

    fields = client.updated[-1][2]
    assert fields["review_action_processed"] is False
    assert fields["sync_status"] == "ERROR"


def test_an_acknowledgement_failure_keeps_the_event_pending_and_retries():
    connection = FakeConnection()
    client = FakeRowClient({CREATORS: [action_row()]}, fail_updates=1)

    first = sync_pull.pull_actions(
        connection, client, creators=CREATORS, buyers=BUYERS, platforms=PLATFORMS
    )

    assert not first.ok
    assert connection.record["workflow_status"] == "APPROVED"
    assert len(connection.workflow_events) == 1
    event = next(iter(connection.events.values()))
    assert event["status"] == "PENDING"
    request = next(iter(connection.requests.values()))
    assert request["resulting_event_id"] is not None

    second = sync_pull.pull_actions(
        connection, client, creators=CREATORS, buyers=BUYERS, platforms=PLATFORMS
    )

    assert second.applied == [f"CREATOR:{RECORD_ID}:APPROVE"]
    assert len(connection.workflow_events) == 1
    assert event["status"] == "APPLIED"
    assert request["resulting_event_id"] is not None


def test_an_unknown_record_is_refused_with_a_readable_message():
    connection = FakeConnection()
    row = action_row(record_id="00000000-0000-0000-0000-000000000000")
    client = FakeRowClient({CREATORS: [row]})

    report = sync_pull.pull_actions(
        connection, client, creators=CREATORS, buyers=BUYERS, platforms=PLATFORMS
    )

    assert not report.ok
    assert "absente de PostgreSQL" in report.rejected[0][1]
    assert connection.record["workflow_status"] == "POOL"
