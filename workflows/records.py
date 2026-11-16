"""Find or create a record, and return the ids the rest of the chain needs.

Identity (scope §3.4):

* a **creator** is identified by platform and handle. A creator present on two
  platforms is, for now, two records: nothing in the evidence ties two accounts
  together yet. The professional address is the secondary key, and it arrives
  later; merging then is an explicit act.
* a **buyer** is identified by its tax id when known. That is the normal case,
  because a buyer is born from a labelled advertisement, and the label carries
  the ИНН or the ОГРН. When the tax id is unknown, the domain is a provisional
  key, and the record is promoted the day the tax id appears — not duplicated.

Creation is idempotent: running twice on the same page returns the same ids.
"""
import re
from dataclasses import dataclass, replace
from typing import Protocol
from urllib.parse import urlsplit

from processing.deduplication import normalize_url
from processing.scoring import CRITERIA_VERSION
from workflows.creator_hunt import platform_for
from workflows.record_flow import BUYER, CREATOR
from workflows.record_loop import Candidate

# Path segments that are pages, not profiles: a video or a wall is not a creator.
# On VK the id is glued with a dash (video-1_2, wall-1_5), so match the prefix
# followed by a separator: a handle may well start with "video" (videogamer).
_VK_NON_PROFILE = re.compile(r"^(video|wall|clip|clips|shorts|feed|search|away)[-_]")

_NOT_A_PROFILE = {
    "t.me": {"s", "joinchat", "addstickers", "proxy", "share"},
    "twitch.tv": {"directory", "videos", "settings", "p"},
}


@dataclass(frozen=True)
class RecordKeys:
    """The two ids the score and the measure need."""

    record_id: str
    account_id: str | None = None
    created: bool = False
    provisional: bool = False


@dataclass(frozen=True)
class CreatorIdentity:
    platform: str
    handle: str
    url: str = ""


@dataclass(frozen=True)
class BuyerIdentity:
    domain: str
    tax_id: str | None = None
    legal_name: str | None = None


class RecordStore(Protocol):
    """The narrow storage contract this step needs, and nothing more."""

    def find_creator(self, identity: CreatorIdentity) -> RecordKeys | None: ...
    def create_creator(
        self, identity: CreatorIdentity, criteria_version: str
    ) -> RecordKeys: ...
    def find_buyer(self, identity: BuyerIdentity) -> RecordKeys | None: ...
    def create_buyer(
        self, identity: BuyerIdentity, criteria_version: str
    ) -> RecordKeys: ...
    def attach_tax_id(self, record_id: str, tax_id: str) -> None: ...


def ensure_record(
    store: RecordStore,
    candidate: Candidate,
    *,
    tax_id: str | None = None,
    legal_name: str | None = None,
) -> RecordKeys | None:
    """Find the record behind a candidate, or create it."""
    if candidate.kind == CREATOR:
        return ensure_creator(store, candidate)
    if candidate.kind == BUYER:
        return ensure_buyer(store, candidate, tax_id=tax_id, legal_name=legal_name)
    return None


def ensure_creator(store: RecordStore, candidate: Candidate) -> RecordKeys | None:
    identity = creator_identity(candidate.source_url)
    if identity is None:
        return None
    return store.find_creator(identity) or store.create_creator(
        identity, CRITERIA_VERSION
    )


def ensure_buyer(
    store: RecordStore,
    candidate: Candidate,
    *,
    tax_id: str | None = None,
    legal_name: str | None = None,
) -> RecordKeys | None:
    identity = buyer_identity(candidate.source_url, tax_id, legal_name)
    if identity is None:
        return None

    found = store.find_buyer(identity)
    if found is None:
        # A legal entity is never created without a legal name: the column is
        # required, and a domain in its place would poison name matching later.
        # A buyer is born from a labelled advertisement, which carries the name.
        if not identity.legal_name:
            return None
        return store.create_buyer(identity, CRITERIA_VERSION)

    if identity.tax_id and found.provisional:
        store.attach_tax_id(found.record_id, identity.tax_id)
        return replace(found, provisional=False)
    return found


def creator_identity(url: str) -> CreatorIdentity | None:
    """Platform and handle, or None when the address is not a profile."""
    platform = platform_for(url)
    if platform is None:
        return None

    host, segments = _host_and_segments(url)
    if host is None:
        return None

    handle = _handle(host, segments)
    if handle is None:
        return None
    return CreatorIdentity(platform=platform, handle=handle, url=url)


def buyer_identity(
    url: str, tax_id: str | None = None, legal_name: str | None = None
) -> BuyerIdentity | None:
    host, _ = _host_and_segments(url)
    if host is None:
        return None
    cleaned = (tax_id or "").strip()
    name = " ".join((legal_name or "").split())
    return BuyerIdentity(domain=host, tax_id=cleaned or None, legal_name=name or None)


def _host_and_segments(url: str) -> tuple[str | None, list[str]]:
    if not url:
        return None, []
    target = url if "://" in url else f"https://{url}"
    parts = urlsplit(target)
    host = (parts.hostname or "").lower().removeprefix("www.")
    if not host:
        return None, []
    segments = [segment for segment in parts.path.split("/") if segment]
    return host, segments


def _handle(host: str, segments: list[str]) -> str | None:
    if not segments:
        return None

    first = segments[0]
    if first in _NOT_A_PROFILE.get(host, set()):
        return None
    if host in {"vk.com", "vkvideo.ru"} and _VK_NON_PROFILE.match(first):
        return None

    # YouTube: @name, /channel/ID, /c/name, /user/name. A watch page is not a profile.
    if host == "youtube.com" or host == "youtu.be":
        if first.startswith("@"):
            return first.casefold()
        if first in {"channel", "c", "user"} and len(segments) > 1:
            return f"{first}:{segments[1]}".casefold()
        return None

    # Rutube: /channel/ID or a plain handle.
    if host == "rutube.ru":
        if first in {"channel", "c"} and len(segments) > 1:
            return f"{first}:{segments[1]}".casefold()
        return first.casefold()

    return first.casefold()


@dataclass
class MemoryRecordStore:
    """An in-memory store, for tests and for a run without a database."""

    _creators: dict = None
    _buyers_by_tax: dict = None
    _buyers_by_domain: dict = None
    _counter: int = 0

    def __post_init__(self):
        self._creators = {}
        self._buyers_by_tax = {}
        self._buyers_by_domain = {}

    def _next(self) -> str:
        self._counter += 1
        return str(self._counter)

    def find_creator(self, identity: CreatorIdentity) -> RecordKeys | None:
        found = self._creators.get((identity.platform, identity.handle))
        return replace(found, created=False) if found is not None else None

    def create_creator(
        self, identity: CreatorIdentity, criteria_version: str
    ) -> RecordKeys:
        number = self._next()
        keys = RecordKeys(
            record_id=f"rec-{number}",
            account_id=f"acc-{number}",
            created=True,
        )
        self._creators[(identity.platform, identity.handle)] = keys
        return keys

    def find_buyer(self, identity: BuyerIdentity) -> RecordKeys | None:
        if identity.tax_id:
            found = self._buyers_by_tax.get(identity.tax_id)
            if found is not None:
                return replace(found, created=False)
        found = self._buyers_by_domain.get(identity.domain)
        return replace(found, created=False) if found is not None else None

    def create_buyer(
        self, identity: BuyerIdentity, criteria_version: str
    ) -> RecordKeys:
        number = self._next()
        keys = RecordKeys(
            record_id=f"rec-{number}",
            created=True,
            provisional=identity.tax_id is None,
        )
        if identity.tax_id:
            self._buyers_by_tax[identity.tax_id] = keys
        self._buyers_by_domain.setdefault(identity.domain, keys)
        return keys

    def attach_tax_id(self, record_id: str, tax_id: str) -> None:
        for domain, keys in list(self._buyers_by_domain.items()):
            if keys.record_id == record_id:
                promoted = replace(keys, provisional=False)
                self._buyers_by_domain[domain] = promoted
                self._buyers_by_tax[tax_id] = promoted
                return


def identity_of(candidate: Candidate) -> str | None:
    """A readable identity for logs and reports."""
    return normalize_url(candidate.source_url)
