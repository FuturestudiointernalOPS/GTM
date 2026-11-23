"""Tests for matching advertisements to buyers by INN or OGRN.

The fake connection keeps buyers, ad rows and Baserow links; the fake client
records the acknowledgement. The checks cover an existing buyer, a buyer
created from the label, an ambiguous pair of identifiers, and the two-pass
case where a new buyer must first be pushed before the ad becomes imported.
"""

from workflows import match_ads

CREATORS = 11
BUYERS = 12
PLATFORMS = 13
ADS = 16


def ad(**overrides):
    values = {
        "id": "ad-1",
        "reference": "AD-000041",
        "advertiser_raw": "ООО Ромашка",
        "inn": "7707083893",
        "ogrn": None,
        "inn_valid": True,
        "ogrn_valid": None,
        "validation_status": "SUBMITTED",
    }
    values.update(overrides)
    return values


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self._one = None
        self._rows = []
        self.description = None

    def execute(self, sql, params=()):
        statement = " ".join(sql.split())
        state = self.connection

        if "FROM ad WHERE validation_status IN" in statement:
            rows = state.ads_to_match[: int(params[0])]
            self._set_rows(rows, "id")
            return

        if "SELECT record_id FROM buyer WHERE inn = %s" in statement:
            self._set_rows(
                [{"record_id": value} for value in state.buyers_inn.get(params[0], [])],
                "record_id",
            )
            return

        if "SELECT record_id FROM buyer WHERE ogrn = %s" in statement:
            self._set_rows(
                [
                    {"record_id": value}
                    for value in state.buyers_ogrn.get(params[0], [])
                ],
                "record_id",
            )
            return

        if "SELECT baserow_row_id, sync_hash FROM baserow_link" in statement:
            self._one = state.links.get(
                (str(params[0]), str(params[1]), int(params[2]))
            )
            self.description = [("baserow_row_id",), ("sync_hash",)]
            return

        if "INSERT INTO record (kind, criteria_version)" in statement:
            self._one = (state.new_record(),)
            return

        if "INSERT INTO buyer (" in statement:
            (
                record_id,
                legal_name,
                normalized_name,
                inn,
                ogrn,
                tax_id,
                tax_id_type,
                official_domain,
            ) = params
            state.buyers[record_id] = {
                "record_id": record_id,
                "legal_name": legal_name,
                "inn": inn,
                "ogrn": ogrn,
            }
            if inn:
                state.add_buyer_index(state.buyers_inn, inn, record_id)
            if ogrn:
                state.add_buyer_index(state.buyers_ogrn, ogrn, record_id)
            self._one = None
            return

        if "UPDATE buyer SET inn = COALESCE" in statement:
            inn, ogrn, record_id = params
            buyer = state.buyers[record_id]
            if inn:
                buyer["inn"] = inn
                state.add_buyer_index(state.buyers_inn, inn, record_id)
            if ogrn:
                buyer["ogrn"] = ogrn
                state.add_buyer_index(state.buyers_ogrn, ogrn, record_id)
            return

        if "UPDATE ad SET buyer_record_id" in statement:
            buyer_id, match_status, validation_status, ad_id = params
            row = state.ad_by_id(ad_id)
            row["buyer_record_id"] = buyer_id
            row["match_status"] = match_status
            row["validation_status"] = validation_status
            return

        raise AssertionError(f"unexpected statement: {statement}")

    def _set_rows(self, rows, key):
        rows = list(rows)
        self._rows = [tuple(row.values()) for row in rows]
        self._one = self._rows[0] if self._rows else None
        if rows and isinstance(rows[0], dict):
            self.description = [(name,) for name in rows[0].keys()]
        elif self._rows:
            self.description = [(key,)]
        else:
            self.description = []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(
        self, *, ads_to_match=None, links=None, buyers_inn=None, buyers_ogrn=None
    ):
        self.ads_to_match = list(ads_to_match or [])
        self.links = dict(links or {})
        self.buyers_inn = {
            key: list(value) for key, value in (buyers_inn or {}).items()
        }
        self.buyers_ogrn = {
            key: list(value) for key, value in (buyers_ogrn or {}).items()
        }
        self.buyers = {}
        self.commits = 0
        self.rollbacks = 0
        self._record_seq = 0

    def cursor(self):
        return FakeCursor(self)

    def new_record(self):
        self._record_seq += 1
        return f"record-{self._record_seq}"

    @staticmethod
    def add_buyer_index(index, value, record_id):
        values = index.setdefault(value, [])
        if record_id not in values:
            values.append(record_id)

    def ad_by_id(self, ad_id):
        for row in self.ads_to_match:
            if str(row["id"]) == str(ad_id):
                return row
        raise AssertionError(f"unknown ad {ad_id}")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeRowClient:
    def __init__(self):
        self.updated = []

    def update_row(self, table_id, row_id, fields):
        self.updated.append((table_id, row_id, dict(fields)))
        return {"id": row_id}


def test_an_existing_buyer_is_matched_and_the_ad_is_imported():
    row = ad()
    connection = FakeConnection(
        ads_to_match=[row],
        links={
            ("AD", "ad-1", ADS): (77, None),
            ("BUYER", "buyer-1", BUYERS): (88, None),
        },
        buyers_inn={"7707083893": ["buyer-1"]},
    )
    client = FakeRowClient()

    report = match_ads.match_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert report.ok
    assert report.matched == ["AD:AD-000041"]
    assert row["buyer_record_id"] == "buyer-1"
    assert row["match_status"] == "AUTO_MATCHED"
    assert row["validation_status"] == "IMPORTED"

    fields = client.updated[-1][2]
    assert fields["match_status"] == "AUTO_MATCHED"
    assert fields["validation_status"] == "IMPORTED"
    assert fields["buyer"] == [88]


def test_a_missing_buyer_is_created_from_the_label():
    row = ad()
    connection = FakeConnection(
        ads_to_match=[row],
        links={("AD", "ad-1", ADS): (77, None)},
    )
    client = FakeRowClient()

    report = match_ads.match_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert report.matched == ["AD:AD-000041"]
    assert report.created == ["AD:AD-000041"]
    assert len(connection.buyers) == 1
    buyer = next(iter(connection.buyers.values()))
    assert buyer["legal_name"] == "ООО Ромашка"
    assert buyer["inn"] == "7707083893"
    assert row["match_status"] == "AUTO_MATCHED"
    assert row["validation_status"] == "SUBMITTED"

    fields = client.updated[-1][2]
    assert fields["match_status"] == "AUTO_MATCHED"
    assert "buyer" not in fields
    assert "validation_status" not in fields


def test_the_created_buyer_is_imported_once_its_baserow_row_exists():
    row = ad()
    connection = FakeConnection(
        ads_to_match=[row],
        links={("AD", "ad-1", ADS): (77, None)},
    )
    client = FakeRowClient()
    match_ads.match_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    connection.links[("BUYER", "record-1", BUYERS)] = (88, None)
    connection.ads_to_match = [row]
    report = match_ads.match_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert report.matched == ["AD:AD-000041"]
    assert row["validation_status"] == "IMPORTED"
    assert client.updated[-1][2]["buyer"] == [88]


def test_two_identifiers_leading_to_two_buyers_are_ambiguous():
    row = ad(ogrn="1027700132195", inn_valid=True, ogrn_valid=True)
    connection = FakeConnection(
        ads_to_match=[row],
        links={("AD", "ad-1", ADS): (77, None)},
        buyers_inn={"7707083893": ["buyer-1"]},
        buyers_ogrn={"1027700132195": ["buyer-2"]},
    )
    client = FakeRowClient()

    report = match_ads.match_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert report.ambiguous == ["AD:AD-000041"]
    assert row["buyer_record_id"] is None
    assert row["match_status"] == "AMBIGUOUS"
    fields = client.updated[-1][2]
    assert fields["match_status"] == "AMBIGUOUS"
    assert fields["sync_status"] == "ERROR"


def test_an_ad_without_a_valid_identifier_stays_unmatched():
    row = ad(inn="not-an-inn", inn_valid=False)
    connection = FakeConnection(
        ads_to_match=[row],
        links={("AD", "ad-1", ADS): (77, None)},
    )
    client = FakeRowClient()

    report = match_ads.match_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert report.unmatched == ["AD:AD-000041"]
    assert row["buyer_record_id"] is None
    assert row["match_status"] == "UNMATCHED"
    assert client.updated[-1][2]["match_status"] == "UNMATCHED"


def test_an_ad_without_its_baserow_link_is_not_changed():
    row = ad()
    connection = FakeConnection(ads_to_match=[row], links={})
    client = FakeRowClient()

    report = match_ads.match_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert not report.ok
    assert "ligne Baserow inconnue" in report.failed[0][1]
    assert row.get("buyer_record_id") is None
    assert client.updated == []
