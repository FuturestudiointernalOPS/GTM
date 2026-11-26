"""Find public contacts by pattern, and the pages likely to hold them.

Why this exists: the model only sees the page the search returned. For a
company that is often a "bloggers programme" page, and for a creator a profile;
the e-mail, phone or Telegram handle usually sits on another page ("Контакты",
"Реклама", the channel description). Without it, nobody can write to the target.

Two deterministic helpers, no model call:

- ``find_in_text`` reads e-mails, Telegram handles and phone numbers straight
  from a page and its links. A value found this way is on the page by
  construction, and its quote is the text around it, so a human can check it.
- ``contact_page_urls`` lists up to three pages of the same site worth reading
  (contacts, advertising, partners), or the channel description for Telegram.

Nothing here decides that a contact is the right person: the row is still
verified by a human before any message, as for the model's contacts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import unquote, urljoin, urlsplit

from processing.contacts import MAX_CONTACTS, PublicContact

MAX_PAGES = 3

# Text around a value kept as its quote (each side).
QUOTE_WINDOW = 60

_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b")
# A phone written for people: +7 / 8 then 10 digits, or another CIS +code.
_PHONE = re.compile(
    r"(?<!\d)(?:\+7|8)[\s(.-]*\d{3}[\s).-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)"
    r"|(?<!\d)\+(?:375|380|374|994|995|996|998|992|993|373)[\s(.-]*\d{2,3}"
    r"[\s).-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)"
)
_AT_HANDLE = re.compile(r"(?<![\w@./])@([A-Za-z][A-Za-z0-9_]{4,31})\b")

# Addresses that are never a person to write to.
_EMAIL_NOISE = (
    "noreply",
    "no-reply",
    "donotreply",
    "example.",
    "sentry",
    "wixpress",
    "@2x.",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
)

_TG_NOT_A_HANDLE = {"share", "joinchat", "addstickers", "proxy", "socks", "s", "c"}

# Words near a value that tell its role. Russian stems on purpose.
_ROLE_WORDS = (
    ("ADVERTISING_CONTACT", ("реклам", "advert", "ads", "размещени", "promo")),
    (
        "INFLUENCE_PARTNERSHIPS",
        ("сотруднич", "партн", "блогер", "blogger", "influenc", "collab", "партнёр"),
    ),
    ("MARKETING", ("маркетинг", "marketing", "pr ", "пресс", "press", "smm")),
)
# A bare @handle only counts next to one of these words, or it is noise.
_HANDLE_CONTEXT = (
    "реклам",
    "сотруднич",
    "по вопросам",
    "менеджер",
    "manager",
    "связь",
    "contact",
    "контакт",
    "business",
    "ads",
    "пишите",
)

# Pages of a company site that usually list contacts, in order of interest.
_CONTACT_PATH_WORDS = (
    "reklam",
    "advert",
    "contact",
    "kontakt",
    "контакт",
    "реклам",
    "partner",
    "sotrud",
    "cooperation",
    "collaboration",
    "bloger",
    "blogger",
    "about",
    "o-nas",
    "o-kompanii",
)
_GUESSED_PATHS = ("/contacts", "/kontakty")

# A news article or a public body is not the company: its contacts would be
# the publisher's. Those pages get no extra read.
# Matched as a whole path segment, or its start before "-" / "_": "/blog/" and
# "/post-36508" are articles, "/bloggers/" is a company's programme page.
_ARTICLE_WORDS = (
    "news",
    "novosti",
    "article",
    "articles",
    "publication",
    "publications",
    "blog",
    "blogs",
    "post",
    "posts",
    "press",
    "stati",
    "story",
    "stories",
    "opinion",
)
_MEDIA_HOSTS = (
    "adindex.ru",
    "sostav.ru",
    "vc.ru",
    "dtf.ru",
    "habr.com",
    "rbc.ru",
    "kommersant.ru",
    "computerra.ru",
    "cybersport.ru",
    "cybersport.by",
    "mmo13.ru",
    "stopgame.ru",
    "igromania.ru",
    "kanobu.ru",
    "wikipedia.org",
)


def find_in_text(
    text: str | None,
    links: Iterable[str] = (),
    *,
    source_url: str = "",
    found_on: str | None = None,
) -> tuple[PublicContact, ...]:
    """Contacts written on the page, best first, at most ``MAX_CONTACTS``.

    ``found_on`` is the page the text comes from when it is not the record's
    own page; it is kept in the description so a human sees where to check.
    """
    text = text or ""
    links = tuple(link for link in links if link)
    own_handle = _telegram_handle(source_url)
    found: list[tuple[int, PublicContact]] = []
    seen: set[tuple[str, str]] = set()

    def add(channel: str, value: str, quote: str, context: str) -> None:
        key = (channel, value.casefold())
        if key in seen:
            return
        seen.add(key)
        role = _role(context)
        description = f"trouvé sur {found_on}" if found_on else None
        contact = PublicContact(
            role=role,
            channel_type=channel,
            channel_value=value[:300],
            description=description,
            quote=quote[:300],
        )
        found.append((_rank(role, channel), contact))

    for match in _EMAIL.finditer(text):
        value = match.group(0).strip(".")
        if _is_noise_email(value):
            continue
        add("EMAIL", value, *_around(text, match.start(), match.end()))
    for link in links:
        if link.lower().startswith("mailto:"):
            value = unquote(link[7:].split("?", 1)[0]).strip()
            if _EMAIL.fullmatch(value) and not _is_noise_email(value):
                add("EMAIL", value, link, "")

    # On a Telegram page, t.me links are mostly channels quoted in posts: they
    # count only next to a contact word. On a company site, a t.me link is
    # usually its own channel or support account.
    on_telegram = _telegram_handle(found_on or source_url) is not None
    for link in links:
        handle = _telegram_handle(link)
        if not handle or handle == own_handle:
            continue
        quote, context = _around_value(text, handle) or (link, "")
        if on_telegram and not _has_contact_word(context):
            continue
        add("TELEGRAM", f"@{handle}", quote, context)
    for match in _AT_HANDLE.finditer(text):
        handle = match.group(1)
        quote, context = _around(text, match.start(), match.end())
        if handle.casefold() == own_handle:
            continue
        if _has_contact_word(context):
            add("TELEGRAM", f"@{handle}", quote, context)

    for match in _PHONE.finditer(text):
        value = " ".join(match.group(0).split())
        add("PHONE", value, *_around(text, match.start(), match.end()))
    for link in links:
        if link.lower().startswith("tel:"):
            value = unquote(link[4:]).strip()
            if len(re.sub(r"\D", "", value)) >= 10:
                add("PHONE", value, link, "")

    found.sort(key=lambda pair: pair[0])
    return tuple(contact for _, contact in found[:MAX_CONTACTS])


def contact_page_urls(
    source_url: str, links: Iterable[str] = (), *, kind: str
) -> list[str]:
    """Up to ``MAX_PAGES`` pages worth reading to find a contact."""
    parts = urlsplit(source_url or "")
    host = (parts.hostname or "").removeprefix("www.")
    if not host:
        return []

    if kind == "CREATOR":
        handle = _telegram_handle(source_url)
        if handle:
            # The plain page shows the channel description, where creators put
            # "по рекламе: @manager"; the /s/ page shows the posts.
            return [f"https://t.me/{handle}"]
        if host == "rutube.ru" and parts.path.startswith("/channel/"):
            channel = parts.path.strip("/").split("/")[1:2]
            if channel:
                return [f"https://rutube.ru/channel/{channel[0]}/about/"]
        return []

    if not _is_company_site(host, parts.path):
        return []

    root = f"{parts.scheme or 'https'}://{parts.netloc}"
    current = source_url.rstrip("/")
    picked: list[str] = []
    for link in links:
        absolute = urljoin(source_url, link)
        target = urlsplit(absolute)
        if (target.hostname or "").removeprefix("www.") != host:
            continue
        path = unquote(target.path).casefold()
        if any(word in path for word in _CONTACT_PATH_WORDS):
            clean = absolute.split("#", 1)[0].rstrip("/")
            if clean != current and clean not in picked:
                picked.append(clean)
    picked.sort(key=_path_rank)
    for path in _GUESSED_PATHS:
        guess = root + path
        if guess not in picked and guess != current:
            picked.append(guess)
    return picked[:MAX_PAGES]


# --- helpers ---------------------------------------------------------------


def _is_company_site(host: str, path: str) -> bool:
    if any(host == media or host.endswith("." + media) for media in _MEDIA_HOSTS):
        return False
    if ".gov." in f".{host}." or host.endswith(".gov"):
        return False
    segments = [s for s in unquote(path).casefold().split("/") if s]
    if any(_is_article_segment(segment) for segment in segments):
        return False
    # Deep paths ending in an id are articles or product pages, not a site.
    return not (len(segments) >= 3 and re.search(r"\d{3,}", segments[-1]))


def _is_article_segment(segment: str) -> bool:
    return any(
        segment == word or segment.startswith((word + "-", word + "_"))
        for word in _ARTICLE_WORDS
    )


def _path_rank(url: str) -> int:
    path = unquote(urlsplit(url).path).casefold()
    for index, word in enumerate(_CONTACT_PATH_WORDS):
        if word in path:
            return index
    return len(_CONTACT_PATH_WORDS)


def _telegram_handle(url: str) -> str | None:
    parts = urlsplit(url or "")
    host = (parts.hostname or "").removeprefix("www.").casefold()
    if host not in {"t.me", "telegram.me"}:
        return None
    segments = [s for s in parts.path.split("/") if s]
    if segments and segments[0] == "s":
        segments = segments[1:]
    if not segments:
        return None
    handle = segments[0].lstrip("@")
    if handle.casefold() in _TG_NOT_A_HANDLE or handle.startswith("+"):
        return None
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", handle):
        return None
    return handle.casefold()


def _has_contact_word(context: str) -> bool:
    folded = context.casefold()
    return any(word in folded for word in _HANDLE_CONTEXT) or any(
        word in folded for _, words in _ROLE_WORDS for word in words
    )


def _is_noise_email(value: str) -> bool:
    folded = value.casefold()
    return any(noise in folded for noise in _EMAIL_NOISE)


def _around(text: str, start: int, end: int) -> tuple[str, str]:
    """The value with its surroundings, and the text just before it."""
    left = max(0, start - QUOTE_WINDOW)
    quote = " ".join(text[left : end + QUOTE_WINDOW].split())
    context = " ".join(text[left:end].split())
    return quote, context


def _around_value(text: str, handle: str) -> tuple[str, str] | None:
    match = re.search(rf"(?:@|t\.me/){re.escape(handle)}\b", text, re.IGNORECASE)
    if match is None:
        return None
    return _around(text, match.start(), match.end())


def _role(context: str) -> str:
    folded = context.casefold()
    for role, words in _ROLE_WORDS:
        if any(word in folded for word in words):
            return role
    return "OTHER"


def _rank(role: str, channel: str) -> int:
    roles = ("ADVERTISING_CONTACT", "INFLUENCE_PARTNERSHIPS", "MARKETING", "OTHER")
    channels = ("EMAIL", "TELEGRAM", "PHONE")
    return roles.index(role) * 10 + channels.index(channel)
