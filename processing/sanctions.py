"""Screen a name against sanctions lists, without accusing anyone.

A match here is never a verdict: it opens a compliance review (E-B-01, X-01).
The screen is therefore deliberately generous — a name that contains a listed
name, or a listed alias, is a match — because a false positive costs one review,
while a false negative lets a listed entity through.

Two failures are distinguished, and they do not lead to the same place:

* a list that could not be read **suspends** the screening (``PENDING``): it says
  nothing about the entity;
* lists that were read and matched nothing give ``NOT_FOUND``, the clear result.

Nothing here fetches: the lists arrive as data, with their source and version.
"""

from dataclasses import dataclass

from processing.deduplication import normalize_legal_name
from processing.eligibility import (
    MANUAL_REVIEW,
    NOT_FOUND,
    PENDING,
    SANCTIONS,
    Check,
)

# Below this length, a contained name is noise ("АО" is inside half the list).
MIN_CONTAINMENT = 6


@dataclass(frozen=True)
class SanctionsList:
    """One list, with the edition that was screened."""

    source: str
    names: tuple[str, ...] = ()
    version: str | None = None


@dataclass(frozen=True)
class SanctionsScreening:
    """The lists that were screened, and those that could not be read."""

    lists: tuple[SanctionsList, ...] = ()
    unavailable: tuple[str, ...] = ()


def screen(subject: str, screening: SanctionsScreening, *, aliases=()) -> Check:
    """Screen one name, and its aliases, against every list."""
    if screening.unavailable:
        return Check(
            SANCTIONS,
            PENDING,
            tuple(f"SOURCE_UNAVAILABLE:{source}" for source in screening.unavailable),
        )
    if not screening.lists:
        return Check(SANCTIONS, PENDING, ("NOT_CHECKED",))

    candidates = tuple(
        key for key in (_key(name) for name in (subject, *aliases)) if key
    )
    if not candidates:
        return Check(SANCTIONS, PENDING, ("SUBJECT_UNUSABLE",))

    for sanctions_list in screening.lists:
        for listed in sanctions_list.names:
            key = _key(listed)
            if key and any(_related(key, candidate) for candidate in candidates):
                return Check(
                    SANCTIONS,
                    MANUAL_REVIEW,
                    (f"MATCH:{sanctions_list.source}",),
                )

    return Check(
        SANCTIONS,
        NOT_FOUND,
        ("NO_MATCH",)
        + tuple(
            f"SCREENED:{sanctions_list.source}" for sanctions_list in screening.lists
        ),
    )


def _key(name: str) -> str | None:
    return normalize_legal_name(name)


def _related(listed: str, candidate: str) -> bool:
    """Equal, or one contains the other when that containment means something."""
    if listed == candidate:
        return True
    shorter, longer = sorted((listed, candidate), key=len)
    return len(shorter) >= MIN_CONTAINMENT and shorter in longer
