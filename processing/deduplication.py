"""Deduplication and database-first lookup.

Rule D-03: before spending on a page read or a new search, check whether the
URL or handle is already known. Normalization makes "https://www.VK.com/red/"
and "vk.com/red?utm_source=x" the same key, so a known record is reused instead
of being collected twice.

The store is a plain JSON file today (no network, easy to test). Baserow will
replace it later; the contract is a set of known URLs and handles plus an
``add`` call.
"""
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

# Tracking parameters never identify a page; they only mark a link's origin.
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "yclid",
    "ref",
    "referrer",
    "_ga",
    "igshid",
    "si",
}


def normalize_url(url: str) -> str | None:
    """Return a stable key for a page, or None when the URL is unusable."""
    url = (url or "").strip()
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url

    parts = urlsplit(url)
    if not parts.netloc:
        return None

    host = parts.netloc.lower().removeprefix("www.")

    path = parts.path.rstrip("/") or "/"
    query = "&".join(
        f"{key}={value}"
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if key.lower() not in _TRACKING_PARAMS
    )
    return urlunsplit(("", host, path, query, "")).lstrip("/")


def normalize_handle(handle: str) -> str | None:
    """Return a lower-case handle without the leading @, or None."""
    handle = (handle or "").strip().lstrip("@").lower()
    return handle or None


class JsonRecordStore:
    """A persisted set of known URLs and handles.

    ``path`` is optional: without it the store lives in memory only, which is
    fine for one-off runs and tests.
    """

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self._urls: set[str] = set()
        self._handles: set[str] = set()
        self._load()

    def contains_url(self, url: str) -> bool:
        return bool(normalize_url(url) in self._urls)

    def contains_handle(self, handle: str) -> bool:
        return bool(normalize_handle(handle) in self._handles)

    def add(self, *, urls=(), handles=()) -> None:
        self._urls.update(normalize_url(url) for url in urls if normalize_url(url))
        self._handles.update(
            normalize_handle(handle) for handle in handles if normalize_handle(handle)
        )
        self._save()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._urls.update(data.get("urls", []))
        self._handles.update(data.get("handles", []))

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"urls": sorted(self._urls), "handles": sorted(self._handles)},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def partition_new(
    items,
    store: JsonRecordStore,
    *,
    url_key: str = "url",
    handle_key: str = "handle",
) -> tuple[list, list]:
    """Split items into (new, already_known) against the store.

    An item is known when its URL or its handle was already seen. New items are
    the only ones that may proceed to an expensive next step.
    """
    fresh: list = []
    known: list = []
    for item in items:
        url = item.get(url_key)
        handle = item.get(handle_key)
        if (url and store.contains_url(url)) or (
            handle and store.contains_handle(handle)
        ):
            known.append(item)
        else:
            fresh.append(item)
    return fresh, known
