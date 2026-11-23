"""Tests for the labelled advertisements -> PostgreSQL service.

The fake connection keeps advertisements and creator links; the fake client
yields Baserow rows and records the acknowledgements. The checks cover the
import rule, the imported-row immutability, the INN/OGRN flags and the two
links that come from Baserow.
"""

from workflows import sync_ads

CREATORS = 11
BUYERS = 12
PLATFORMS = 13
ADS = 16
RECORD_ID = "9c8f4b1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b"


def ad_row(**overrides):
    values = {
        "id": 41,
        "advertiser_raw": "ООО Ромашка",
        "ad_label_present": True,
        "inn": "7707083893",
        "ogrn": "1027700132195",
        "erid": "erid-1",
        "extraction_status": "COMPLETE",
        "ad_source": [{"id": 4, "value": "vk_video"}],
        "ad_source_other": "",
        "ad_url": "https://vk.com/feed?w=ad1",
        "creative_ref": "cr-1",
        "creator_refs": "Игрок",
        "collected_at": "2026-11-01T10:00:00Z",
        "collected_by": "intern1",
        "creators": [{"id": 7, "value": "Игрок"}],
        "validation_status": "DRAFT",
        "raw_extract": "Реклама ООО Ромашка ИНН 7707083893 erid-1",
        "notes": "",
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

        if "SELECT p.name FROM baserow_link" in statement:
            name = state.platform_names.get((params[0], params[1]))
            self._one = None if name is None else (name,)
            return

        if "SELECT entity_type, entity_id FROM baserow_link" in statement:
            self._one = state.links.get((params[0], params[1]))
            return

        if "SELECT id, reference, validation_status::text FROM ad" in statement:
            ad = state.ads.get((params[0], params[1]))
            if ad is None:
                self._one = None
                self.description = []
            else:
                self._one = (ad["id"], ad["reference"], ad["validation_status"])
                self.description = [
                    ("id",),
                    ("reference",),
                    ("validation_status",),
                ]
            return

        if "INSERT INTO ad (" in statement:
            ad = state.upsert_ad(params)
            self._one = (ad["id"], ad["reference"])
            return

        if "INSERT INTO ad_creator" in statement:
            state.ad_creators.add((params[0], params[1], params[2]))
            return

        if "INSERT INTO baserow_link" in statement:
            entity_type, entity_id, table_id, row_id, sync_hash = params
            state.links[(entity_type, str(entity_id), int(table_id))] = (
                int(row_id),
                sync_hash,
            )
            return

        raise AssertionError(f"unexpected statement: {statement}")

    def fetchone(self):
        return self._one

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, *, links=None, platform_names=None, ads=None):
        default_links = {(CREATORS, 7): ("CREATOR", RECORD_ID)}
        default_platforms = {(PLATFORMS, 4): "vk_video"}
        self.links = dict(default_links if links is None else links)
        self.platform_names = dict(
            default_platforms if platform_names is None else platform_names
        )
        self.ads = dict(ads or {})
        self.ad_creators = set()
        self.commits = 0
        self.rollbacks = 0
        self._ad_seq = 0

    def cursor(self):
        return FakeCursor(self)

    def upsert_ad(self, params):
        (
            reference,
            advertiser_raw,
            inn,
            ogrn,
            inn_valid,
            ogrn_valid,
            erid,
            label_present,
            extraction_status,
            ad_source,
            ad_url,
            normalized_url,
            creative_ref,
            creator_refs,
            collected_at,
            collected_by,
            raw_payload,
            validation_status,
        ) = params
        key = (normalized_url, erid or creative_ref or "")
        ad = self.ads.get(key)
        if ad is None:
            self._ad_seq += 1
            ad = {
                "id": f"ad-{self._ad_seq}",
                "reference": reference,
                "validation_status": validation_status,
                "advertiser_raw": advertiser_raw,
                "inn_valid": inn_valid,
                "ogrn_valid": ogrn_valid,
            }
            self.ads[key] = ad
        else:
            ad["validation_status"] = validation_status
            ad["advertiser_raw"] = advertiser_raw
            ad["inn_valid"] = inn_valid
            ad["ogrn_valid"] = ogrn_valid
            if ad["reference"] is None:
                ad["reference"] = reference
        return ad

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


def test_a_default_empty_row_is_skipped_without_writing_an_error():
    connection = FakeConnection()
    client = FakeRowClient(
        {
            ADS: [
                ad_row(
                    advertiser_raw="",
                    ad_url="",
                    validation_status=None,
                    extraction_status=None,
                )
            ]
        }
    )

    report = sync_ads.pull_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert report.ok
    assert report.skipped == ["AD:41"]
    assert connection.ads == {}
    assert client.updated == []


def test_an_editable_ad_is_imported_with_its_ids_and_links():
    connection = FakeConnection()
    client = FakeRowClient({ADS: [ad_row()]})

    report = sync_ads.pull_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert report.ok
    assert report.applied == ["AD:41"]
    ad = next(iter(connection.ads.values()))
    assert ad["reference"] == "AD-000041"
    assert ad["inn_valid"] is True
    assert ad["ogrn_valid"] is True
    assert connection.ad_creators == {(ad["id"], RECORD_ID, "lien Baserow")}

    fields = client.updated[-1][2]
    assert fields["ad_id"] == ad["id"]
    assert fields["reference"] == "AD-000041"
    assert fields["inn_valid"] is True
    assert fields["ogrn_valid"] is True
    assert fields["sync_status"] == "SYNCED"


def test_an_imported_ad_is_left_untouched():
    connection = FakeConnection()
    client = FakeRowClient({ADS: [ad_row(validation_status="IMPORTED")]})

    report = sync_ads.pull_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert report.skipped == ["AD:41"]
    assert connection.ads == {}
    fields = client.updated[-1][2]
    assert fields["sync_status"] == "SYNCED"
    assert fields["sync_error"] is None


def test_a_rejected_ad_is_not_imported():
    connection = FakeConnection()
    client = FakeRowClient({ADS: [ad_row(validation_status="REJECTED")]})

    report = sync_ads.pull_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert report.skipped == ["AD:41"]
    assert connection.ads == {}
    assert client.updated[-1][2]["sync_status"] == "REJECTED"


def test_a_missing_required_field_is_refused():
    connection = FakeConnection()
    client = FakeRowClient({ADS: [ad_row(ad_url="")]})

    report = sync_ads.pull_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert not report.ok
    assert "ad_url" in report.rejected[0][1]
    assert connection.ads == {}


def test_editing_an_imported_ad_is_refused():
    key = ("vk.com/feed?w=ad1", "erid-1")
    connection = FakeConnection(
        ads={
            key: {
                "id": "ad-old",
                "reference": "AD-000001",
                "validation_status": "IMPORTED",
            }
        }
    )
    client = FakeRowClient({ADS: [ad_row(validation_status="DRAFT")]})

    report = sync_ads.pull_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert not report.ok
    assert "déjà importée" in report.rejected[0][1]
    assert next(iter(connection.ads.values()))["validation_status"] == "IMPORTED"


def test_an_unresolved_creator_keeps_the_ad_and_reports_the_link():
    connection = FakeConnection(links={})
    client = FakeRowClient({ADS: [ad_row()]})

    report = sync_ads.pull_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert not report.ok
    assert "créateurs non synchronisés" in report.failed[0][1]
    assert len(connection.ads) == 1
    fields = client.updated[-1][2]
    assert fields["sync_status"] == "ERROR"


def test_an_unresolved_platform_is_refused():
    connection = FakeConnection(platform_names={})
    client = FakeRowClient({ADS: [ad_row()]})

    report = sync_ads.pull_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert not report.ok
    assert "support publicitaire non synchronisé" in report.rejected[0][1]
    assert connection.ads == {}


def test_an_invalid_inn_is_stored_with_a_false_flag():
    connection = FakeConnection()
    client = FakeRowClient({ADS: [ad_row(inn="7707083894")]})

    report = sync_ads.pull_ads(
        connection,
        client,
        creators=CREATORS,
        buyers=BUYERS,
        platforms=PLATFORMS,
        ads=ADS,
    )

    assert report.ok
    ad = next(iter(connection.ads.values()))
    assert ad["inn_valid"] is False
    assert client.updated[-1][2]["inn_valid"] is False
