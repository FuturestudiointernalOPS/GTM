"""Tests for the PostgreSQL record store, against a fake connection.

The fake answers each statement in order and keeps the log, so the test checks
both the shape of the SQL and the values it would send. No server, no driver.
"""
import re
from pathlib import Path

import pytest

from integrations.record_store import (
    INSERT_BUYER,
    INSERT_CREATOR,
    INSERT_CREATOR_ACCOUNT,
    INSERT_RECORD,
    SELECT_BUYER_BY_DOMAIN,
    SELECT_BUYER_BY_TAX,
    SELECT_CREATOR_ACCOUNT,
    UPDATE_TAX_ID,
    PostgresRecordStore,
    UnknownPlatform,
)
from processing.deduplication import normalize_legal_name
from workflows.records import BuyerIdentity, CreatorIdentity, creator_identity

DDL = Path(__file__).resolve().parent.parent / "db" / "postgres" / "001_schema.sql"


class _Cursor:
    def __init__(self, connection):
        self._connection = connection
        self._row = None

    def execute(self, sql, params=()):
        self._connection.log.append((" ".join(sql.split()), params))
        answers = self._connection._answers
        self._row = answers.pop(0) if answers else None

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, answers=()):
        self.log = []
        self._answers = list(answers)

    def cursor(self):
        return _Cursor(self)


def identity(url="https://vk.com/creator", platform="VK Video", handle="creator"):
    return CreatorIdentity(platform=platform, handle=handle, url=url)


def buyer(domain="brand.ru", tax_id=None, legal_name=None):
    return BuyerIdentity(domain=domain, tax_id=tax_id, legal_name=legal_name)


def insert_columns(statement):
    header = statement.split("VALUES")[0]
    inside = header[header.index("(") + 1 : header.rindex(")")]
    return {part.strip() for part in inside.split(",")}


def ddl_columns(table):
    block = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", DDL.read_text(), re.DOTALL)
    assert block, f"{table} is missing from the schema"
    found = set()
    for raw in block.group(1).splitlines():
        text = raw.strip()
        if not text or text.startswith("--"):
            continue
        word = text.split()[0].rstrip(",")
        if word.upper() in {"CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN"}:
            continue
        if re.fullmatch(r"[a-z_][a-z0-9_]*", word):
            found.add(word)
    return found


# --- creators ---------------------------------------------------------------


def test_find_creator_reads_the_platform_and_the_handle():
    connection = FakeConnection(answers=[("rec-1", "acc-1")])
    store = PostgresRecordStore(connection)

    keys = store.find_creator(identity())

    assert keys.record_id == "rec-1"
    assert keys.account_id == "acc-1"
    assert keys.created is False

    sql, params = connection.log[0]
    assert sql == " ".join(SELECT_CREATOR_ACCOUNT.split())
    assert params == ("VK Video", "creator")


def test_find_creator_normalises_the_handle():
    connection = FakeConnection(answers=[None])
    store = PostgresRecordStore(connection)

    assert store.find_creator(identity(handle="@Creator")) is None
    assert connection.log[0][1] == ("VK Video", "creator")


def test_find_creator_without_a_row_returns_nothing():
    store = PostgresRecordStore(FakeConnection(answers=[None]))

    assert store.find_creator(identity()) is None


def test_create_creator_writes_the_record_the_creator_and_the_account():
    connection = FakeConnection(
        answers=[("platform-1",), ("rec-9",), None, ("acc-9",)]
    )
    store = PostgresRecordStore(connection)

    keys = store.create_creator(identity(), "1.4")

    assert keys.record_id == "rec-9"
    assert keys.account_id == "acc-9"
    assert keys.created is True
    assert keys.provisional is False

    assert len(connection.log) == 4
    assert connection.log[0][1] == ("VK Video",)
    assert connection.log[1][0] == " ".join(INSERT_RECORD.split())
    assert connection.log[1][1] == ("CREATOR", "1.4")
    assert connection.log[2][1] == ("rec-9", "creator")

    _, account = connection.log[3]
    assert account == (
        "rec-9",
        "platform-1",
        "creator",
        "creator",
        "https://vk.com/creator",
        "vk.com/creator",
    )


def test_create_creator_keeps_the_youtube_at_sign_in_the_handle():
    connection = FakeConnection(
        answers=[("platform-1",), ("rec-9",), None, ("acc-9",)]
    )
    store = PostgresRecordStore(connection)

    store.create_creator(
        creator_identity("https://www.youtube.com/@Creator") or identity(),
        "1.4",
    )

    _, account = connection.log[3]
    assert account[2] == "@creator"
    assert account[3] == "creator"
    # The address keeps its case; the identity key is the folded handle.
    assert account[5] == "youtube.com/@Creator"


def test_create_creator_on_an_unknown_platform_writes_nothing():
    connection = FakeConnection(answers=[None])
    store = PostgresRecordStore(connection)

    with pytest.raises(UnknownPlatform):
        store.create_creator(identity(platform="NouvellePlateforme"), "1.4")

    assert len(connection.log) == 1


# --- buyers -----------------------------------------------------------------


def test_find_buyer_by_tax_id_returns_the_provisional_flag():
    connection = FakeConnection(answers=[("rec-2", False)])
    store = PostgresRecordStore(connection)

    keys = store.find_buyer(buyer(tax_id="7707083893"))

    assert keys.record_id == "rec-2"
    assert keys.provisional is False
    sql, params = connection.log[0]
    assert sql == " ".join(SELECT_BUYER_BY_TAX.split())
    assert params == ("7707083893", "7707083893", "7707083893")


def test_find_buyer_falls_back_to_the_domain():
    connection = FakeConnection(answers=[None, ("rec-2", True)])
    store = PostgresRecordStore(connection)

    keys = store.find_buyer(buyer(tax_id="7707083893"))

    assert keys.record_id == "rec-2"
    assert keys.provisional is True
    assert connection.log[1][0] == " ".join(SELECT_BUYER_BY_DOMAIN.split())
    assert connection.log[1][1] == ("brand.ru",)


def test_find_buyer_by_domain_only_queries_the_domain():
    connection = FakeConnection(answers=[("rec-2", True)])
    store = PostgresRecordStore(connection)

    store.find_buyer(buyer())

    assert len(connection.log) == 1
    assert "official_domain = %s" in connection.log[0][0]


def test_find_buyer_without_a_row_returns_nothing():
    store = PostgresRecordStore(FakeConnection(answers=[None]))

    assert store.find_buyer(buyer()) is None


def test_create_buyer_writes_an_inn_in_the_inn_column():
    connection = FakeConnection(answers=[("rec-3",)])
    store = PostgresRecordStore(connection)

    keys = store.create_buyer(
        buyer(tax_id="7707083893", legal_name="ООО «Тест»"), "1.4"
    )

    assert keys.record_id == "rec-3"
    assert keys.created is True
    assert keys.provisional is False

    _, record = connection.log[0]
    assert record == ("BUYER", "1.4")

    _, params = connection.log[1]
    assert params == (
        "rec-3",
        "ООО «Тест»",
        "ооо тест",
        "7707083893",
        None,
        None,
        "INN",
        "brand.ru",
    )


def test_create_buyer_puts_an_ogrn_in_the_ogrn_column():
    connection = FakeConnection(answers=[("rec-3",)])
    store = PostgresRecordStore(connection)

    store.create_buyer(
        buyer(tax_id="1027700132195", legal_name="ООО Тест"), "1.4"
    )

    params = connection.log[1][1]
    assert params[3] is None
    assert params[4] == "1027700132195"
    assert params[6] == "OGRN"


def test_create_buyer_without_a_tax_id_is_provisional():
    connection = FakeConnection(answers=[("rec-3",)])
    store = PostgresRecordStore(connection)

    keys = store.create_buyer(buyer(legal_name="ООО Тест"), "1.4")

    assert keys.provisional is True
    params = connection.log[1][1]
    assert params[3:7] == (None, None, None, None)


def test_create_buyer_refuses_a_missing_legal_name():
    connection = FakeConnection()
    store = PostgresRecordStore(connection)

    with pytest.raises(ValueError, match="legal name"):
        store.create_buyer(buyer(tax_id="7707083893"), "1.4")

    assert connection.log == []


def test_attach_tax_id_updates_the_buyer_without_erasing_the_other_ids():
    connection = FakeConnection()
    store = PostgresRecordStore(connection)
    record_id = "9f1c0000-0000-0000-0000-000000000001"

    store.attach_tax_id(record_id, "1027700132195")

    sql, params = connection.log[0]
    assert sql == " ".join(UPDATE_TAX_ID.split())
    assert "COALESCE" in sql
    assert params == (None, "1027700132195", None, "OGRN", record_id)


# --- the contract -----------------------------------------------------------


def test_the_insert_columns_exist_in_the_schema():
    assert insert_columns(INSERT_RECORD) <= ddl_columns("record")
    assert insert_columns(INSERT_CREATOR) <= ddl_columns("creator")
    assert insert_columns(INSERT_CREATOR_ACCOUNT) <= ddl_columns(
        "creator_platform_account"
    )
    assert insert_columns(INSERT_BUYER) <= ddl_columns("buyer")


def test_the_legal_name_is_normalised_for_comparison():
    assert normalize_legal_name("ООО «Тест»") == "ооо тест"
    assert normalize_legal_name("  ООО   Тест.  ") == "ооо тест"
    assert normalize_legal_name("   ") is None
