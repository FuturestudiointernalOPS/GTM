"""Baserow schema client.

Why a dedicated client: the same tables and fields must be created the same way
on every environment, and a schema error must stop with a readable message. This
module only handles the schema (tables and fields), never row data.

The token is never logged and never included in an error message.
"""

from __future__ import annotations

import logging
from typing import Any, Self

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from config import settings

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class BaserowError(RuntimeError):
    """Baserow refused the request; repeating it unchanged will not help."""


class BaserowTemporaryError(BaserowError):
    """Rate limit, server problem or network down; retrying may succeed."""


class BaserowNotConfigured(BaserowError):
    """The URL or the token is missing from the settings."""


def is_configured() -> bool:
    """True when both the URL and the token are set."""
    return bool(settings.BASEROW_URL and settings.BASEROW_TOKEN)


def _api_root(url: str | None) -> str:
    """Return the API root, accepting an URL with or without the /api suffix."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    return url if url.endswith("/api") else f"{url}/api"


class BaserowClient:
    """Minimal client for the Baserow schema endpoints.

    Use it as a context manager so the HTTP connection is always closed::

        with BaserowClient() as client:
            client.list_tables(database_id)
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        auth_scheme: str | None = None,
    ):
        self.base_url = _api_root(base_url or settings.BASEROW_URL)
        self.token = token or settings.BASEROW_TOKEN or ""
        self.auth_scheme = auth_scheme or settings.BASEROW_AUTH_SCHEME or "JWT"

        if not self.base_url or not self.token:
            raise BaserowNotConfigured(
                "Baserow is not configured: set BASEROW_URL and BASEROW_TOKEN "
                "in the .env file"
            )

        self._client = httpx.Client(
            timeout=TIMEOUT,
            headers={"Authorization": f"{self.auth_scheme} {self.token}"},
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- tables ------------------------------------------------------------

    def list_tables(self, database_id: int) -> list[dict]:
        """Return every table of a Baserow database."""
        return _as_list(
            self._request_with_retry("GET", f"/database/tables/database/{database_id}/")
        )

    def create_table(self, database_id: int, name: str) -> dict:
        """Create a table. Baserow also creates a default primary text field.

        No automatic retry: a lost response after a successful creation would
        create a second table. The caller can rerun the idempotent seeder.
        """
        return self._request(
            "POST",
            f"/database/tables/database/{database_id}/",
            json={"name": name},
        )

    # -- fields ------------------------------------------------------------

    def list_fields(self, table_id: int) -> list[dict]:
        """Return every field of a table, in Baserow order."""
        return _as_list(
            self._request_with_retry("GET", f"/database/fields/table/{table_id}/")
        )

    def create_field(self, table_id: int, payload: dict) -> dict:
        """Create one field and return Baserow's description of it.

        No automatic retry: a lost response after a successful creation would
        create a duplicate field. Rerun the idempotent seeder instead.
        """
        return self._request(
            "POST",
            f"/database/fields/table/{table_id}/",
            json=payload,
        )

    def update_field(self, field_id: int, payload: dict) -> dict:
        """Rename a field or update its options."""
        return self._request_with_retry(
            "PATCH",
            f"/database/fields/{field_id}/",
            json=payload,
        )

    # -- rows --------------------------------------------------------------

    def list_rows(
        self,
        table_id: int,
        *,
        size: int = 200,
        page: int = 1,
        filters: dict[str, object] | None = None,
    ) -> list[dict]:
        """Return one page of rows, addressed by field name.

        Baserow caps the page size; callers that need every row ask for the
        next page, or use ``find_row`` when one row is enough.
        """
        params: dict[str, object] = {
            "user_field_names": "true",
            "size": size,
            "page": page,
        }
        if filters:
            for name, value in filters.items():
                params[f"filter__{name}__equal"] = value
        return _as_list(
            self._request_with_retry(
                "GET", f"/database/rows/table/{table_id}/", params=params
            )
        )

    def find_row(self, table_id: int, field: str, value: object) -> dict | None:
        """Return the first row whose field equals ``value``, or ``None``."""
        rows = self.list_rows(table_id, size=1, filters={field: value})
        return rows[0] if rows else None

    def create_row(self, table_id: int, fields: dict) -> dict:
        """Create one row and return Baserow's description of it.

        No automatic retry: a lost response after a successful creation would
        create a second row. The synchronization service resolves a row by its
        business key before creating one, so a replay stays safe.
        """
        return self._request(
            "POST",
            f"/database/rows/table/{table_id}/",
            params={"user_field_names": "true"},
            json=fields,
        )

    def update_row(self, table_id: int, row_id: int, fields: dict) -> dict | None:
        """Update one row, addressed by field name."""
        return self._request_with_retry(
            "PATCH",
            f"/database/rows/table/{table_id}/{row_id}/",
            params={"user_field_names": "true"},
            json=fields,
        )

    # -- transport ---------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(BaserowTemporaryError),
        wait=wait_exponential_jitter(initial=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _request_with_retry(self, method: str, path: str, **kwargs) -> Any:
        return self._request(method, path, **kwargs)

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.TransportError as error:
            # Only the error type: the raw message may quote request details.
            raise BaserowTemporaryError(
                f"cannot reach Baserow ({type(error).__name__})"
            ) from error

        if response.status_code == 429 or response.status_code >= 500:
            raise BaserowTemporaryError(
                f"Baserow answered {response.status_code} on {method} {path}: "
                f"{_description(response)}"
            )

        if response.status_code >= 400:
            raise BaserowError(
                f"Baserow refused {method} {path} ({response.status_code}): "
                f"{_description(response)}"
            )

        if response.status_code == 204 or not response.content:
            return None

        try:
            return response.json()
        except ValueError as error:
            raise BaserowError("Baserow answered with unreadable content") from error


class BaserowRowClient(BaserowClient):
    """Client for row data, using the durable database token when it is set.

    The schema endpoints need a short-lived JWT. A background synchronization
    service cannot refresh one every hour, so it reads a database token from
    its own setting. Keeping the two clients separate prevents a schema run
    from silently using the wrong credential.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        auth_scheme: str | None = None,
    ):
        row_token = token or settings.BASEROW_ROW_TOKEN
        if row_token:
            token = row_token
            if auth_scheme is None:
                auth_scheme = settings.BASEROW_ROW_AUTH_SCHEME or "Token"
        super().__init__(
            base_url=base_url,
            token=token,
            auth_scheme=auth_scheme,
        )


def _description(response: httpx.Response) -> str:
    """Read Baserow's own explanation, without ever exposing the token."""
    try:
        body = response.json()
    except ValueError:
        return "no description"
    if isinstance(body, dict):
        for key in ("detail", "error", "message"):
            value = body.get(key)
            if value:
                return str(value)[:500]
    return "no description"


def _as_list(payload: Any) -> list[dict]:
    """Accept both a plain list and a paginated Baserow answer."""
    if isinstance(payload, dict):
        results = payload.get("results")
        return results if isinstance(results, list) else []
    return payload if isinstance(payload, list) else []
