"""Tests for the Baserow proofs -> PostgreSQL facts service.

The fake connection keeps sources, snapshots and facts; the fake client yields
proof rows and records the acknowledgements. The tests focus on the contract:
only accepted proofs are imported, the source is dated, and a replay or an edit
cannot create a second fact.
"""

from datetime import datetime, timezone
from decimal import Decimal

from workflows import sync_evidence

CREATORS = 11
BUYERS = 12
PLATFORMS = 13
PROOFS = 15
RECORD_ID = "9c8f4b1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b"


def proof_row(**overrides):
    values = {
        "id": 31,
        "record_type": "CREATOR",
        "creator": [{"id": 7, "value": "Игрок"}],
        "acheteur": [],
        "fact_key": "followers",
        "value": "25 000",
        "proof_level": "OBSERVED",
        "confidence": "VERIFIED",
        "source_url": "https://example.test/page",
        "consulted_at": "2026-11-01T10:00:00Z",
        "query_used": "followers",
        "service": "exa",
        "review_status": "ACCEPTED",
        "reviewed_by": "analyst",
        "notes": "profile page",
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

        if "SELECT id, value_text, value_number, value_boolean" in statement:
            fact = state.facts.get(params[0])
            if fact is None:
                self._one = None
                self.description = []
            else:
                self._one = (
                    fact["id"],
                    fact["value_text"],
                    fact["value_number"],
                    fact["value_boolean"],
                    fact["proof_level"],
                    fact["confidence"],
                    fact["is_current"],
                    fact["recorded_at"],
                )
                self.description = [
                    ("id",),
                    ("value_text",),
                    ("value_number",),
                    ("value_boolean",),
                    ("proof_level",),
                    ("confidence",),
                    ("is_current",),
                    ("recorded_at",),
                ]
            return

        if "INSERT INTO source (" in statement:
            url, normalized, kind = params
            source = state.sources.get(normalized)
            if source is None:
                source = state.new_source(url, normalized, kind)
                state.sources[normalized] = source
            self._one = (source["id"],)
            return

        if "INSERT INTO source_snapshot" in statement:
            source_id, consulted_at, query_used, service = params
            key = (source_id, consulted_at)
            snapshot = state.snapshots.get(key)
            if snapshot is None:
                snapshot = state.new_snapshot(
                    source_id, consulted_at, query_used, service
                )
                state.snapshots[key] = snapshot
            self._one = (snapshot["id"],)
            return

        if "INSERT INTO record_source" in statement:
            state.record_sources.add((params[0], params[1], params[2]))
            return

        if "INSERT INTO fact (" in statement:
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
            ) = params
            if external_event_id in state.facts:
                self._one = None
                return
            fact = state.new_fact(
                external_event_id,
                record_id,
                key,
                text,
                number,
                boolean,
                proof_level,
                confidence,
                snapshot_id,
                recorded_by,
            )
            state.facts[external_event_id] = fact
            self._one = (fact["id"],)
            return

        raise AssertionError(f"unexpected statement: {statement}")

    def fetchone(self):
        return self._one

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, *, links=None):
        default = {(CREATORS, 7): ("CREATOR", RECORD_ID)}
        self.links = dict(default if links is None else links)
        self.sources = {}
        self.snapshots = {}
        self.record_sources = set()
        self.facts = {}
        self.commits = 0
        self.rollbacks = 0
        self._source_seq = 0
        self._snapshot_seq = 0
        self._fact_seq = 0

    def cursor(self):
        return FakeCursor(self)

    def new_source(self, url, normalized, kind):
        self._source_seq += 1
        return {
            "id": f"source-{self._source_seq}",
            "url": url,
            "normalized": normalized,
        }

    def new_snapshot(self, source_id, consulted_at, query_used, service):
        self._snapshot_seq += 1
        return {
            "id": f"snapshot-{self._snapshot_seq}",
            "source_id": source_id,
            "consulted_at": consulted_at,
        }

    def new_fact(
        self,
        external_event_id,
        record_id,
        key,
        text,
        number,
        boolean,
        proof_level,
        confidence,
        snapshot_id,
        recorded_by,
    ):
        self._fact_seq += 1
        return {
            "id": f"fact-{self._fact_seq}",
            "external_event_id": external_event_id,
            "record_id": record_id,
            "key": key,
            "value_text": text,
            "value_number": number,
            "value_boolean": boolean,
            "proof_level": proof_level,
            "confidence": confidence,
            "source_snapshot_id": snapshot_id,
            "recorded_by": recorded_by,
            "is_current": True,
            "recorded_at": datetime.now(timezone.utc),
        }

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeRowClient:
    def __init__(self, rows):
        self.rows = rows
        self.updated = []

    def iter_rows(self, table_id, *, max_pages=50):
        yield from self.rows.get(table_id, [])

    def update_row(self, table_id, row_id, fields):
        self.updated.append((table_id, row_id, dict(fields)))
        return {"id": row_id}


def test_an_accepted_proof_creates_a_sourced_fact():
    connection = FakeConnection()
    client = FakeRowClient({PROOFS: [proof_row()]})

    report = sync_evidence.pull_evidence(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        proofs=PROOFS,
    )

    assert report.ok
    assert report.applied == ["PROOF:31"]
    fact = next(iter(connection.facts.values()))
    assert fact["key"] == "followers"
    assert fact["value_number"] == Decimal("25000")
    assert fact["proof_level"] == "OBSERVED"
    assert fact["confidence"] == "VERIFIED"
    assert len(connection.sources) == 1
    assert len(connection.snapshots) == 1
    assert connection.record_sources == {
        (RECORD_ID, next(iter(connection.snapshots.values()))["id"], "OTHER")
    }

    fields = client.updated[-1][2]
    assert fields["fact_id"] == fact["id"]
    assert fields["is_current"] is True
    assert fields["sync_status"] == "SYNCED"


def test_a_pending_proof_is_not_imported():
    connection = FakeConnection()
    client = FakeRowClient({PROOFS: [proof_row(review_status="PENDING")]})

    report = sync_evidence.pull_evidence(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        proofs=PROOFS,
    )

    assert report.skipped == ["PROOF:31"]
    assert connection.facts == {}
    fields = client.updated[-1][2]
    assert fields["sync_status"] == "PENDING"
    assert fields["sync_error"] == "preuve en attente de revue"


def test_a_rejected_proof_is_not_imported():
    connection = FakeConnection()
    client = FakeRowClient({PROOFS: [proof_row(review_status="REJECTED")]})

    report = sync_evidence.pull_evidence(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        proofs=PROOFS,
    )

    assert report.skipped == ["PROOF:31"]
    assert connection.facts == {}
    fields = client.updated[-1][2]
    assert fields["sync_status"] == "REJECTED"


def test_replaying_the_same_proof_does_not_create_a_second_fact():
    connection = FakeConnection()
    client = FakeRowClient({PROOFS: [proof_row()]})

    first = sync_evidence.pull_evidence(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        proofs=PROOFS,
    )
    second = sync_evidence.pull_evidence(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        proofs=PROOFS,
    )

    assert first.applied
    assert second.skipped == ["PROOF:31"]
    assert len(connection.facts) == 1


def test_changing_the_value_of_an_imported_proof_is_refused():
    connection = FakeConnection()
    client = FakeRowClient({PROOFS: [proof_row(value="1000")]})
    sync_evidence.pull_evidence(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        proofs=PROOFS,
    )

    client.rows = {PROOFS: [proof_row(value="2000")]}
    report = sync_evidence.pull_evidence(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        proofs=PROOFS,
    )

    assert not report.ok
    assert "autre valeur" in report.rejected[0][1]
    assert len(connection.facts) == 1


def test_a_malformed_value_is_refused():
    connection = FakeConnection()
    client = FakeRowClient({PROOFS: [proof_row(value="many")]})

    report = sync_evidence.pull_evidence(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        proofs=PROOFS,
    )

    assert not report.ok
    assert "nombre" in report.rejected[0][1]
    assert connection.facts == {}


def test_an_unsynchronised_record_is_refused():
    connection = FakeConnection(links={})
    client = FakeRowClient({PROOFS: [proof_row()]})

    report = sync_evidence.pull_evidence(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        proofs=PROOFS,
    )

    assert not report.ok
    assert "non synchronisée" in report.rejected[0][1]
    assert connection.facts == {}
