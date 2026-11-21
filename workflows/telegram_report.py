"""Build the Monday Telegram report for Henry, in the Playbook layout.

Five parts (spend, funnel vs targets, top 5 creators, top 5 buyers, blockers),
then the numbered drafts waiting for approval. The text is plain (the notifier
sends no HTML or Markdown), so the layout relies on emoji headers, blank lines
and one idea per line: easy to scan on a phone.

This module only formats. It computes no score and decides no rule: whatever
is missing is shown as "not measured yet", never invented.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import unquote, urlparse

from integrations.telegram import MAX_TEXT

TOP_N = 5
MISSING = "not measured yet"
DIVIDER = "━━━━━━━━━━━━━━━"

# Platform shown in the report, found from the page address.
_PLATFORMS = {
    "twitch.tv": "Twitch",
    "vkvideo.ru": "VK Video",
    "vk.com": "VK",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "t.me": "Telegram",
    "rutube.ru": "Rutube",
    "kick.com": "Kick",
    "tiktok.com": "TikTok",
}

# Noise that search engines add to page titles.
_TITLE_NOISE = (
    r"^about\s+",
    r"\s+[-|–]\s+twitch$",
    r"\s+на vk видео.*$",
    r"\s+[-|–]\s+youtube$",
    r"\s+\|\s+vk$",
    r"\s+/\s+хабр$",
)


@dataclass(frozen=True)
class Candidate:
    """One creator or one buyer, as shown in a top 5."""

    name: str
    url: str
    platform: str | None = None
    detail: str | None = None  # game, or sector for a buyer
    score: int | None = None
    why: str | None = None  # what made the score, one short sentence


@dataclass(frozen=True)
class Target:
    """One funnel line: what was done against the weekly goal."""

    label: str
    done: int
    goal: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class Draft:
    """One message waiting for Henry's approval."""

    ref: str  # C1, B2... the candidate it is written for
    name: str
    channel: str  # e.g. "email (EN + RU)", "DM (RU, sent by a person)"


@dataclass(frozen=True)
class WeeklyReport:
    run_date: date
    status: str = "OK"
    finished_at: str | None = None  # e.g. "07:42 UTC"
    tool_spend: dict[str, float] = field(default_factory=dict)
    tool_budget: float | None = None
    ai_spend: float | None = None
    funnel: tuple[Target, ...] = ()
    creators: tuple[Candidate, ...] = ()
    buyers: tuple[Candidate, ...] = ()
    blockers: tuple[str, ...] = ()
    drafts: tuple[Draft, ...] = ()
    demo: bool = False  # adds a banner: test data, nothing to act on
    # Lines under the drafts; None keeps the Playbook text (Baserow + reply).
    draft_note: tuple[str, ...] | None = None


APPROVAL_NOTE = (
    "Full texts are in Baserow (status: Awaiting approval).",
    'Reply with what to send, e.g. "send 1, 3; drop 2".',
)


def render(report: WeeklyReport) -> str:
    """The full report as one text (may exceed Telegram's limit: see split)."""
    parts = [
        _header(report),
        _spend(report),
        _funnel(report),
        _top("🎮 3) TOP 5 CREATORS", "C", report.creators),
        _top("🏢 4) TOP 5 BUYERS", "B", report.buyers),
        _blockers(report),
        _drafts(report),
    ]
    return "\n\n".join(parts)


def split(text: str, limit: int = MAX_TEXT) -> list[str]:
    """Cut the text into messages under ``limit``, between sections if possible.

    Paragraphs (blocks separated by a blank line) are never cut unless one alone
    is too long; then it is cut between lines, and a line between characters.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")

    messages: list[str] = []
    current = ""
    for block in _pieces(text, limit):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
        else:
            messages.append(current)
            current = block
    if current:
        messages.append(current)
    return messages


def candidates_from_pages(pages: Iterable[dict]) -> tuple[Candidate, ...]:
    """Turn raw search pages into report lines, with a readable name.

    For a demo before scoring exists: no score, no reason, only who and where.
    """
    seen: set[str] = set()
    result: list[Candidate] = []
    for page in pages:
        url = page.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(
            Candidate(
                name=display_name(page.get("title"), url),
                url=url,
                platform=page.get("platform") or platform_of(url),
            )
        )
    return tuple(result)


def platform_of(url: str) -> str | None:
    host = (urlparse(url).hostname or "").removeprefix("www.")
    for domain, name in _PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def display_name(title: str | None, url: str) -> str:
    """A short name: the channel handle for streaming sites, else a clean title."""
    handle = _handle(url)
    if handle:
        return handle

    name = (title or "").strip()
    for pattern in _TITLE_NOISE:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip(" -|–·")
    if not name:
        name = (urlparse(url).hostname or url).removeprefix("www.")
    return name if len(name) <= 60 else name[:57].rstrip() + "…"


def readable_url(url: str) -> str:
    """Decode %D0%... into letters, so a Cyrillic address stays readable."""
    decoded = unquote(url)
    # A decoded space would cut the link in Telegram: keep the original then.
    return url if re.search(r"\s", decoded) else decoded


# --- sections --------------------------------------------------------------


def _header(report: WeeklyReport) -> str:
    lines = []
    if report.demo:
        lines += ["🧪 DEMO: nothing to approve", ""]
    lines.append("🗓 ProveItGo Creator Hunt")
    lines.append(f"{report.run_date:%A %d %b %Y}")
    status = f"Status: {report.status}"
    if report.finished_at:
        status = f"Run finished {report.finished_at} · {status}"
    lines.append(status)
    lines.append(DIVIDER)
    return "\n".join(lines)


def _spend(report: WeeklyReport) -> str:
    lines = ["💰 1) SPEND"]
    if report.tool_spend:
        total = sum(report.tool_spend.values())
        budget = f" of ${report.tool_budget:.2f}" if report.tool_budget else ""
        lines.append(f"Tools: ${total:.2f}{budget}")
        for tool, amount in report.tool_spend.items():
            lines.append(f"   • {tool}: ${amount:.2f}")
    else:
        lines.append(f"Tools: {MISSING}")
    ai = f"${report.ai_spend:.2f}" if report.ai_spend is not None else MISSING
    lines.append(f"AI (DeepSeek): {ai}")
    return "\n".join(lines)


def _funnel(report: WeeklyReport) -> str:
    lines = ["📊 2) FUNNEL vs WEEKLY TARGETS"]
    if not report.funnel:
        lines.append(MISSING)
    for target in report.funnel:
        line = f"{_mark(target)} {target.label}: {target.done}"
        if target.goal is not None:
            line += f" / {target.goal}"
        lines.append(line)
        if target.note:
            lines.append(f"   ↳ {target.note}")
    return "\n".join(lines)


def _mark(target: Target) -> str:
    if target.goal is None:
        return "▫️"
    return "✅" if target.done >= target.goal else "⚠️"


def _top(title: str, prefix: str, items: Sequence[Candidate]) -> str:
    ranked = sorted(items, key=lambda c: (c.score is None, -(c.score or 0)))[:TOP_N]
    if not ranked:
        return f"{title}\nNone found this week."

    blocks = [title]
    for index, item in enumerate(ranked, start=1):
        score = f" — {item.score}/100" if item.score is not None else ""
        lines = [f"{prefix}{index} · {item.name}{score}"]
        about = " · ".join(x for x in (item.platform, item.detail) if x)
        if about:
            lines.append(f"   {about}")
        lines.append(f"   💬 {item.why}" if item.why else "   💬 score: " + MISSING)
        lines.append(f"   🔗 {readable_url(item.url)}")
        blocks.append("\n".join(lines))
    hidden = len(items) - len(ranked)
    if hidden > 0:
        blocks.append(f"   + {hidden} more in Baserow")
    return "\n\n".join(blocks)


def _blockers(report: WeeklyReport) -> str:
    lines = ["🚧 5) BLOCKERS & QUESTIONS"]
    if not report.blockers:
        lines.append("None 🎉")
    lines += [f"• {item}" for item in report.blockers]
    return "\n".join(lines)


def _drafts(report: WeeklyReport) -> str:
    lines = [DIVIDER, "✉️ DRAFTS AWAITING YOUR APPROVAL"]
    if not report.drafts:
        lines.append("No draft this week.")
        lines.append("")
        lines.append("Nothing goes out without your reply.")
        return "\n".join(lines)

    for number, draft in enumerate(report.drafts, start=1):
        lines.append(f"{number} · {draft.ref} {draft.name} — {draft.channel}")
    note = APPROVAL_NOTE if report.draft_note is None else report.draft_note
    lines += ["", *note, "Nothing goes out without your reply."]
    return "\n".join(lines)


# --- helpers ---------------------------------------------------------------


def _handle(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.")
    path = [p for p in unquote(parsed.path).split("/") if p]
    if not path:
        return None
    first = path[0]
    if host in ("twitch.tv", "live.vkvideo.ru", "kick.com", "t.me"):
        return first
    if host in ("youtube.com", "tiktok.com") and first.startswith("@"):
        return first
    return None


def _pieces(text: str, limit: int) -> list[str]:
    pieces: list[str] = []
    for block in text.split("\n\n"):
        if len(block) <= limit:
            pieces.append(block)
            continue
        chunk = ""
        for line in block.split("\n"):
            while len(line) > limit:
                if chunk:
                    pieces.append(chunk)
                    chunk = ""
                pieces.append(line[:limit])
                line = line[limit:]
            candidate = f"{chunk}\n{line}" if chunk else line
            if len(candidate) <= limit:
                chunk = candidate
            else:
                pieces.append(chunk)
                chunk = line
        if chunk:
            pieces.append(chunk)
    return pieces
