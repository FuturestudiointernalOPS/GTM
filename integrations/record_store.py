"""Find or create the record rows a score needs, in PostgreSQL.

The score pipeline needs two ids: the record, and — for a creator — the platform
account the engagement measure belongs to. This module resolves them from the
identity rules of ``workflows/records.py`` and the schema of
``db/postgres/001_schema.sql``.

Two properties are worth stating because they are schema requirements, not
preferences:

* ``record.reference`` (``CR-000001`` / ``BY-000001``) is assigned by the
  database trigger, so the insert leaves the column out;
* ``buyer.legal_name`` is required. A legal entity with a domain in place of its
  name would poison name matching and the registry checks, so a buyer is only
  created when its name is known — which is the case for a buyer born from a
  labelled advertisement, since the label carries the name and the tax id.

The caller owns the transaction: three inserts for a creator, two for a buyer.
Everything is passed to ``cursor.execute`` so the tests can check the shape of
each statement without a server.
"""
import re

from processing.deduplication import (
    normalize_handle,
    normalize_legal_name,
    normalize_url,
)
from workflows.records import BuyerIdentity, CreatorIdentity, RecordKeys

# A platform row is reference data: it carries the RKN coverage and the campaign
# constraints of docs/verification.md §2.4. This module never invents one.
SELECT_PLATFORM = "SELECT id FROM platform WHERE name = %s"

SELECT_CREATOR_ACCOUNT = """
SELECT a.record_id, a.id
FROM creator_platform_account a
JOIN platform p ON p.id = a.platform_id
WHERE p.name = %s AND a.normalized_handle = %s
"""

INSERT_RECORD = """
INSERT INTO record (kind, criteria_version) VALUES (%s, %s) RETURNING id
"""

INSERT_CREATOR = """
INSERT INTO creator (record_id, display_name) VALUES (%s, %s)
"""

INSERT_CREATOR_ACCOUNT = """
INSERT INTO creator_platform_account (
    record_id, platform_id, handle, normalized_handle,
    platform_url, normalized_url, is_primary
) VALUES (%s, %s, %s, %s, %s, %s, true)
RETURNING id
"""

# "Provisional" is the absence of every tax identifier. It is computed by the
# database so the store and the schema cannot disagree about what it means.
_PROVISIONAL = "(inn IS NULL AND ogrn IS NULL AND tax_id IS NULL)"

SELECT_BUYER_BY_TAX = f"""
SELECT record_id, {_PROVISIONAL}
FROM buyer
WHERE inn = %s OR ogrn = %s OR tax_id = %s
LIMIT 1
"""

SELECT_BUYER_BY_DOMAIN = f"""
SELECT record_id, {_PROVISIONAL}
FROM buyer
WHERE official_domain = %s
ORDER BY created_at
LIMIT 1
"""

INSERT_BUYER = """
INSERT INTO buyer (
    record_id, legal_name, legal_name_normalized,
    inn, ogrn, tax_id, tax_id_type, official_domain
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

UPDATE_TAX_ID = """
UPDATE buyer
SET inn = COALESCE(%s, inn),
    ogrn = COALESCE(%s, ogrn),
    tax_id = COALESCE(%s, tax_id),
    tax_id_type = COALESCE(%s, tax_id_type),
    updated_at = now()
WHERE record_id = %s
"""

# Russian identifiers, as the buyer checks in the schema accept them: an INN is
# 10 digits (12 for a sole trader), an OGRN is 13 (15 for a sole trader). Anything
# else is kept as a local tax id rather than guessed into a column with a format
# it does not match.
_INN = re.compile(r"[0-9]{10}|[0-9]{12}")
_OGRN = re.compile(r"[0-9]{13}|[0-9]{15}")


class UnknownPlatform(ValueError):
    """The platform is absent from the reference table; nothing was written."""


class PostgresRecordStore:
    """The ``RecordStore`` contract over a psycopg connection."""

    def __init__(self, connection):
        self._connection = connection

    # --- creators ---------------------------------------------------------

    def find_creator(self, identity: CreatorIdentity) -> RecordKeys | None:
        handle = normalize_handle(identity.handle)
        if handle is None:
            return None
        with self._connection.cursor() as cursor:
            cursor.execute(SELECT_CREATOR_ACCOUNT, (identity.platform, handle))
            row = cursor.fetchone()
        if row is None:
            return None
        return RecordKeys(record_id=str(row[0]), account_id=str(row[1]))

    def create_creator(
        self, identity: CreatorIdentity, criteria_version: str
    ) -> RecordKeys:
        platform_id = self._platform_id(identity.platform)

        handle = identity.handle
        normalized_handle = normalize_handle(handle)
        if normalized_handle is None:
            raise ValueError("a creator identity needs a handle")
        platform_url = identity.url
        normalized_url = normalize_url(platform_url)
        if normalized_url is None:
            raise ValueError("a creator identity needs an address")

        with self._connection.cursor() as cursor:
            cursor.execute(INSERT_RECORD, ("CREATOR", criteria_version))
            record_id = str(cursor.fetchone()[0])

            cursor.execute(INSERT_CREATOR, (record_id, handle))

            cursor.execute(
                INSERT_CREATOR_ACCOUNT,
                (
                    record_id,
                    platform_id,
                    handle,
                    normalized_handle,
                    platform_url,
                    normalized_url,
                ),
            )
            account_id = str(cursor.fetchone()[0])

        return RecordKeys(record_id=record_id, account_id=account_id, created=True)

    # --- buyers -----------------------------------------------------------

    def find_buyer(self, identity: BuyerIdentity) -> RecordKeys | None:
        with self._connection.cursor() as cursor:
            if identity.tax_id:
                cursor.execute(
                    SELECT_BUYER_BY_TAX,
                    (identity.tax_id, identity.tax_id, identity.tax_id),
                )
                row = cursor.fetchone()
                if row is not None:
                    return RecordKeys(
                        record_id=str(row[0]), provisional=bool(row[1])
                    )

            cursor.execute(SELECT_BUYER_BY_DOMAIN, (identity.domain,))
            row = cursor.fetchone()

        if row is None:
            return None
        return RecordKeys(record_id=str(row[0]), provisional=bool(row[1]))

    def create_buyer(
        self, identity: BuyerIdentity, criteria_version: str
    ) -> RecordKeys:
        # The schema requires a name. Refusing here keeps the rule in one place
        # instead of turning it into a NotNullViolation three layers down.
        legal_name = " ".join((identity.legal_name or "").split())
        if not legal_name:
            raise ValueError("a buyer record needs a legal name")
        normalized_name = normalize_legal_name(legal_name)
        if normalized_name is None:
            raise ValueError("a buyer record needs a legal name")

        inn, ogrn, local_tax_id, tax_id_type = _tax_columns(identity.tax_id)

        with self._connection.cursor() as cursor:
            cursor.execute(INSERT_RECORD, ("BUYER", criteria_version))
            record_id = str(cursor.fetchone()[0])

            cursor.execute(
                INSERT_BUYER,
                (
                    record_id,
                    legal_name,
                    normalized_name,
                    inn,
                    ogrn,
                    local_tax_id,
                    tax_id_type,
                    identity.domain,
                ),
            )

        return RecordKeys(
            record_id=record_id,
            created=True,
            provisional=identity.tax_id is None,
        )

    def attach_tax_id(self, record_id: str, tax_id: str) -> None:
        inn, ogrn, local_tax_id, tax_id_type = _tax_columns(tax_id)
        with self._connection.cursor() as cursor:
            cursor.execute(
                UPDATE_TAX_ID,
                (inn, ogrn, local_tax_id, tax_id_type, str(record_id)),
            )

    # --- internals --------------------------------------------------------

    def _platform_id(self, name: str) -> str:
        with self._connection.cursor() as cursor:
            cursor.execute(SELECT_PLATFORM, (name,))
            row = cursor.fetchone()
        if row is None:
            raise UnknownPlatform(
                f"{name!r} is not in the platform table: seed it before scoring"
            )
        return str(row[0])


def _tax_columns(tax_id: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    """Map a tax id onto the column that accepts it, and its declared type."""
    digits = (tax_id or "").strip()
    if not digits:
        return None, None, None, None
    if _INN.fullmatch(digits):
        return digits, None, None, "INN"
    if _OGRN.fullmatch(digits):
        return None, digits, None, "OGRN"
    return None, None, digits, "OTHER"
