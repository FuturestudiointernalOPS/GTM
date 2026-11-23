"""Public professional contacts and company programmes, verified against a page.

The model may propose contacts and programmes, but nothing enters a fiche on
its word alone. Every value keeps its verbatim excerpt, and the control code
checks both the excerpt and the value against the page that was read. A contact
that is not published on that page is dropped.

This module does not decide whether a contact is "professional": the model is
told to return only professional, public channels, and a human still verifies
the row after it is stored. What the code can prove is that the address is on
the page; it cannot prove that the person behind it is the right one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from processing.deduplication import normalize_url

ROLES = {
    "ADVERTISING_CONTACT",
    "AGENCY",
    "MARKETING",
    "INFLUENCE_PARTNERSHIPS",
    "BRAND",
    "FOUNDER",
    "OTHER",
}

CHANNEL_TYPES = {"EMAIL", "TELEGRAM", "VK", "FORM", "PHONE", "OTHER"}

ROLE_ALIASES = {
    "ADVERTISING": "ADVERTISING_CONTACT",
    "ADS": "ADVERTISING_CONTACT",
    "PUBLICITY": "ADVERTISING_CONTACT",
    "COMMERCIAL": "ADVERTISING_CONTACT",
    "PARTNERSHIP": "INFLUENCE_PARTNERSHIPS",
    "PARTNERSHIPS": "INFLUENCE_PARTNERSHIPS",
    "INFLUENCER": "INFLUENCE_PARTNERSHIPS",
    "INFLUENCE": "INFLUENCE_PARTNERSHIPS",
    "CEO": "FOUNDER",
    "OWNER": "FOUNDER",
    "DIRECTOR": "FOUNDER",
}

CHANNEL_ALIASES = {
    "MAIL": "EMAIL",
    "E-MAIL": "EMAIL",
    "TG": "TELEGRAM",
    "TELEGRAMM": "TELEGRAM",
    "VKONTAKTE": "VK",
    "VKONTAKT": "VK",
    "FORMULAIRE": "FORM",
    "FORM_URL": "FORM",
    "FORM_URLS": "FORM",
    "TEL": "PHONE",
    "TELEPHONE": "PHONE",
    "WHATSAPP": "PHONE",
}

ROLE_LABELS = {
    "ADVERTISING_CONTACT": "contact publicitaire",
    "AGENCY": "agence",
    "MARKETING": "marketing",
    "INFLUENCE_PARTNERSHIPS": "influence / partenariats",
    "BRAND": "marque",
    "FOUNDER": "fondateur",
    "OTHER": "contact",
}

CHANNEL_LABELS = {
    "EMAIL": "e-mail",
    "TELEGRAM": "Telegram",
    "VK": "VK",
    "FORM": "formulaire",
    "PHONE": "téléphone",
    "OTHER": "autre",
}

MAX_CONTACTS = 3
MAX_PROGRAMS = 3
MIN_QUOTE = 8

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class PublicContact:
    """One public, professional contact found on a page."""

    role: str
    channel_type: str
    channel_value: str
    person_name: str | None = None
    description: str | None = None
    quote: str = ""

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, "contact")

    @property
    def channel_label(self) -> str:
        return CHANNEL_LABELS.get(self.channel_type, "autre")

    def summary(self) -> str:
        who = f"{self.role_label}"
        if self.person_name:
            who += f" ({self.person_name})"
        return f"{who} — {self.channel_value} · {self.channel_label}"


@dataclass(frozen=True)
class BuyerProgram:
    """What a company offers or asks for, and how to submit something."""

    description: str
    title: str | None = None
    submission_method: str | None = None
    submission_url: str | None = None
    quote: str = ""

    def summary(self) -> str:
        parts = [self.title or "Programme", self.description]
        if self.submission_method:
            parts.append(f"soumission : {self.submission_method}")
        if self.submission_url:
            parts.append(self.submission_url)
        return " — ".join(part for part in parts if part)


def verify_contacts(
    items: Iterable[object] | None,
    *,
    text: str,
    links: Iterable[str] = (),
    source_url: str = "",
) -> tuple[PublicContact, ...]:
    """Keep only contacts whose value and quote really appear on the page."""
    if not items:
        return ()

    page = _normalize(text)
    link_keys = {normalize_url(link) for link in links if link}
    kept: list[PublicContact] = []
    seen: set[tuple[str, str]] = set()

    for item in items:
        role = _role(_value(item, "role"))
        channel_type = _channel_type(_value(item, "channel_type"))
        value = _clean(_value(item, "channel_value"))
        quote = _clean(_value(item, "quote"))

        if channel_type == "FORM" and not value:
            value = source_url
        if role is None or not value:
            continue
        if not _quote_ok(quote, page):
            continue
        if (
            channel_type == "FORM"
            and value == source_url
            and not _looks_like_form(quote)
        ):
            continue
        if not _value_ok(
            channel_type, value, page=page, link_keys=link_keys, source_url=source_url
        ):
            continue

        key = (channel_type, value.casefold())
        if key in seen:
            continue
        seen.add(key)
        kept.append(
            PublicContact(
                role=role,
                channel_type=channel_type,
                channel_value=value[:300],
                person_name=_clean(_value(item, "person_name"))[:80] or None,
                description=_clean(_value(item, "description"))[:300] or None,
                quote=quote[:300],
            )
        )
        if len(kept) >= MAX_CONTACTS:
            break

    return tuple(kept)


def verify_programs(
    items: Iterable[object] | None,
    *,
    text: str,
    links: Iterable[str] = (),
) -> tuple[BuyerProgram, ...]:
    """Keep only programmes whose description and quote appear on the page."""
    if not items:
        return ()

    page = _normalize(text)
    link_keys = {normalize_url(link) for link in links if link}
    kept: list[BuyerProgram] = []
    seen: set[str] = set()

    for item in items:
        title = _clean(_value(item, "title"))
        description = _clean(_value(item, "description"))
        quote = _clean(_value(item, "quote"))
        method = _clean(_value(item, "submission_method"))
        url = _clean(_value(item, "submission_url"))

        if not description and not title:
            continue
        if not _quote_ok(quote, page):
            continue
        if url and not _url_ok(url, page=page, link_keys=link_keys):
            continue

        key = _normalize(description or title)
        if key in seen:
            continue
        seen.add(key)
        kept.append(
            BuyerProgram(
                title=title[:120] or None,
                description=description[:300],
                submission_method=method[:120] or None,
                submission_url=url[:500] or None,
                quote=quote[:300],
            )
        )
        if len(kept) >= MAX_PROGRAMS:
            break

    return tuple(kept)


def _value(item: object, key: str):
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def _role(value) -> str | None:
    text = _clean(value).upper().replace("-", "_").replace(" ", "_")
    if not text:
        return None
    text = ROLE_ALIASES.get(text, text)
    return text if text in ROLES else None


def _channel_type(value) -> str:
    text = _clean(value).upper().replace("-", "_").replace(" ", "_")
    if not text:
        return "OTHER"
    text = CHANNEL_ALIASES.get(text, text)
    return text if text in CHANNEL_TYPES else "OTHER"


def _quote_ok(quote: str, page: str) -> bool:
    normalized = _normalize(quote)
    return len(normalized) >= MIN_QUOTE and normalized in page


def _value_ok(
    channel_type: str,
    value: str,
    *,
    page: str,
    link_keys: set[str],
    source_url: str,
) -> bool:
    folded = value.casefold()

    if channel_type == "EMAIL":
        return bool(_EMAIL.match(value)) and folded in page

    if channel_type == "PHONE":
        digits = re.sub(r"\D", "", value)
        return len(digits) >= 7 and digits in re.sub(r"\D", "", page)

    if channel_type in {"TELEGRAM", "VK"}:
        handle = _handle(value)
        if not handle:
            return False
        if (
            f"@{handle}" in page
            or f"t.me/{handle}" in page
            or f"telegram.me/{handle}" in page
            or f"vk.com/{handle}" in page
        ):
            return True
        return _link_with_handle(link_keys, channel_type, handle)

    if channel_type == "FORM":
        if value == source_url:
            return True
        return _url_ok(value, page=page, link_keys=link_keys)

    if value.startswith(("http://", "https://")):
        return _url_ok(value, page=page, link_keys=link_keys)
    return folded in page


def _url_ok(value: str, *, page: str, link_keys: set[str]) -> bool:
    key = normalize_url(value)
    if key and key in link_keys:
        return True
    return _normalize(value) in page


def _link_with_handle(link_keys: set[str], channel_type: str, handle: str) -> bool:
    hosts = (
        {"t.me", "telegram.me"}
        if channel_type == "TELEGRAM"
        else {"vk.com", "vkvideo.ru"}
    )
    for key in link_keys:
        if not key:
            continue
        host, _, rest = key.partition("/")
        if (
            host.casefold() in hosts
            and rest.split("?", 1)[0].strip("/").casefold() == handle
        ):
            return True
    return False


def _handle(value: str) -> str | None:
    text = value.strip()
    if "://" in text:
        path = text.split("://", 1)[1].split("/", 1)
        text = path[1] if len(path) > 1 else ""
    text = text.split("?", 1)[0].strip("/")
    text = text.rsplit("/", 1)[-1].lstrip("@").casefold()
    return text or None


def _looks_like_form(quote: str) -> bool:
    text = _normalize(quote)
    return any(
        marker in text
        for marker in (
            "форм",
            "form",
            "заявк",
            "contact",
            "связ",
            "submit",
            "soumission",
        )
    )


def _normalize(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def _clean(value) -> str:
    return " ".join(str(value or "").split())
