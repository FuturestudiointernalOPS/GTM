"""Deterministic score computation.

The scope fixes the rules this module applies: exact arithmetic, a single
truncation at the end (S-01), a cap per criterion (S-02), and an unknown measure
that never counts as zero (S-03). The criteria, weights and thresholds are in
``docs/scope.md`` (§5.3 for creators, §6.3 for buyers); this module does not
invent any of them.

Nothing here reads a page, calls a model or looks at the clock. A score is a
function of measures that other stages already collected and sourced, so the
same facts always give the same integer. Eligibility is never decided here
(H-04): a high score cannot repair a missing registry check.
"""
from dataclasses import dataclass
from fractions import Fraction
from math import floor

CRITERIA_VERSION = "1.4"

THRESHOLD = 70

# Line and decision vocabulary, mirrored from the scope's journey.
MEASURED = "MEASURED"
UNKNOWN = "UNKNOWN"
PRESELECTED = "PRESELECTED"
REJECTED = "REJECTED"
TO_REVIEW = "TO_REVIEW"
OUT_OF_PROFILE = "OUT_OF_PROFILE"

# E-C-04: outside this range a creator is out of profile, not rejected.
PROFILE_MIN_FOLLOWERS = 5_000
PROFILE_MAX_FOLLOWERS = 300_000

# A share computed on fewer items than this is not a measure (C-02).
MIN_SAMPLE = 10

# Engagement: at least five readable items, flagged below ten (M-05).
ENGAGEMENT_MIN_SAMPLE = 5
ENGAGEMENT_FULL_SAMPLE = 10

# Engagement thresholds, in percent of followers, per platform (§5.3, 1.4).
ENGAGEMENT_THRESHOLDS = {
    "telegram": Fraction(20),
    "vk_video": Fraction(10),
    "twitch": Fraction(5),
    "rutube": Fraction(5),
    "youtube": Fraction(10),
}

# Platform safety ("sûreté de la plateforme"), in points (§5.3).
PLATFORM_SAFETY = {
    "vk_video": 10,
    "twitch": 10,
    "rutube": 10,
    "telegram": 5,
    "youtube": 5,
}

_PLATFORM_ALIASES = {
    "vk": "vk_video",
    "vkvideo": "vk_video",
    "vk_video_live": "vk_video",
}

_DECISION_MAKER_POINTS = {
    "named_verified": 20,
    "named_unverified": 10,
    "generic_only": 0,
    "none": 0,
}


@dataclass(frozen=True)
class ScoreLine:
    """One criterion's contribution, with the measure that produced it."""

    criterion: str
    maximum: int
    blocking: bool
    points: Fraction | None = None
    measure: str | None = None
    reason: str | None = None
    flags: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        return MEASURED if self.points is not None else UNKNOWN


@dataclass(frozen=True)
class ScoreResult:
    """A full score: the lines, the exact total, the integer, the bounds."""

    proposal: str
    score: int | None
    total_exact: Fraction | None
    lower_bound: Fraction | None
    upper_bound: Fraction | None
    incomplete: bool
    lines: tuple[ScoreLine, ...]
    criteria_version: str = CRITERIA_VERSION

    @classmethod
    def out_of_profile(cls) -> "ScoreResult":
        """A record outside the profile is not scored at all (E-C-04)."""
        return cls(
            proposal=OUT_OF_PROFILE,
            score=None,
            total_exact=None,
            lower_bound=None,
            upper_bound=None,
            incomplete=False,
            lines=(),
        )


@dataclass(frozen=True)
class CreatorMeasures:
    """What the creator criteria need, each value already sourced.

    ``None`` means unknown. It never means zero: an unreadable counter and a
    counter at zero produce different decisions (S-03).
    """

    gaming_share: Fraction | None = None  # percent of gaming posts, 0..100
    gaming_window: int | None = None  # posts the share was computed on
    median_views: Fraction | int | None = None  # exact median, views or viewers
    followers: int | None = None
    engagement_read_at: str | None = None  # one snapshot for views and followers
    engagement_sample: int | None = None  # readable items behind the median
    published_last_30_days: int | None = None
    ad_contact: bool | None = None  # contact or rate card in bio
    past_labeled_ads: bool | None = None
    platform: str | None = None
    russian_share: Fraction | None = None  # percent of comments in Russian
    comment_sample: int | None = None


@dataclass(frozen=True)
class BuyerMeasures:
    """What the buyer criteria need, each value already sourced."""

    creators_paid: int | None = None  # distinct creators, last 90 days
    gaming_core: bool | None = None  # gaming is the primary activity shown
    decision_maker: str | None = None  # named_verified, named_unverified, ...
    employees: int | None = None
    recent_event: bool | None = None  # dated within 60 days


def in_creator_profile(followers: int | None) -> bool:
    """False only when the follower count is known and out of range.

    An unknown count is not an out-of-profile verdict: the record is scored, and
    the engagement line becomes unknown, which sends it to review.
    """
    if followers is None:
        return True
    return PROFILE_MIN_FOLLOWERS <= followers <= PROFILE_MAX_FOLLOWERS


def score_creator(
    measures: CreatorMeasures, *, threshold: int = THRESHOLD
) -> ScoreResult:
    """Score a creator from measures that are already observed and sourced."""
    if not in_creator_profile(measures.followers):
        return ScoreResult.out_of_profile()

    lines = (
        _focus_gaming(measures),
        _engagement(measures),
        _activity(measures),
        _ad_ready(measures),
        _platform_safety(measures),
        _audience_fit(measures),
    )
    return _result(lines, threshold)


def score_buyer(measures: BuyerMeasures, *, threshold: int = THRESHOLD) -> ScoreResult:
    """Score a buyer from measures that are already observed and sourced."""
    lines = (
        _pays_creators(measures),
        _sells_to_gamers(measures),
        _decision_maker(measures),
        _size(measures),
        _timing(measures),
    )
    return _result(lines, threshold)


def _result(lines: tuple[ScoreLine, ...], threshold: int) -> ScoreResult:
    """Sum exactly, truncate once, then read the decision table in order."""
    measured = [line for line in lines if line.points is not None]
    unknown = [line for line in lines if line.points is None]

    total = sum((line.points for line in measured), Fraction(0))
    missing = sum(line.maximum for line in unknown)
    blocking_missing = any(line.blocking for line in unknown)

    return ScoreResult(
        proposal=_decide(total, missing, blocking_missing, threshold),
        score=floor(total),
        total_exact=total,
        lower_bound=total,
        upper_bound=total + missing,
        incomplete=bool(unknown),
        lines=lines,
    )


def _decide(
    total: Fraction,
    missing: int,
    blocking_missing: bool,
    threshold: int,
) -> str:
    """S-03, read from top to bottom: the first matching row decides."""
    if missing == 0:
        return PRESELECTED if total >= threshold else REJECTED
    # Certain rejection: even the maximum on everything unknown stays below.
    if total + missing < threshold:
        return REJECTED
    if blocking_missing:
        return TO_REVIEW
    if total >= threshold:
        return PRESELECTED
    return TO_REVIEW


# --- creator criteria -------------------------------------------------------


def _focus_gaming(measures: CreatorMeasures) -> ScoreLine:
    base = {"criterion": "focus_gaming", "maximum": 25, "blocking": True}
    share = measures.gaming_share
    if share is None:
        return _unknown(**base, reason="missing")
    if not 0 <= share <= 100:
        return _unknown(**base, reason="out_of_domain")
    if measures.gaming_window is None or measures.gaming_window < MIN_SAMPLE:
        return _unknown(**base, reason="sample_too_small")
    return _measured(
        **base,
        points=_ratio_points(share, Fraction(80), 25),
        measure=f"{_number(share)} % sur {measures.gaming_window} publications",
    )


def _engagement(measures: CreatorMeasures) -> ScoreLine:
    base = {"criterion": "engagement", "maximum": 25, "blocking": True}
    if measures.median_views is None or measures.followers is None:
        return _unknown(**base, reason="missing")

    threshold_percent = ENGAGEMENT_THRESHOLDS.get(_platform_key(measures.platform))
    if threshold_percent is None:
        return _unknown(**base, reason="platform_without_threshold")
    if measures.followers <= 0:
        return _unknown(**base, reason="no_denominator")
    if not measures.engagement_read_at:
        # M-03: views and followers come from one snapshot, with one timestamp.
        return _unknown(**base, reason="snapshot_missing")
    sample = measures.engagement_sample
    if sample is None or sample < ENGAGEMENT_MIN_SAMPLE:
        return _unknown(**base, reason="sample_too_small")
    if measures.median_views < 0:
        return _unknown(**base, reason="out_of_domain")

    ratio = Fraction(measures.median_views) * 100 / measures.followers
    return _measured(
        **base,
        points=_ratio_points(ratio, threshold_percent, 25),
        measure=f"{_number(ratio)} % sur un seuil de {_number(threshold_percent)} %",
        flags=("WEAK_SAMPLE",) if sample < ENGAGEMENT_FULL_SAMPLE else (),
    )


def _activity(measures: CreatorMeasures) -> ScoreLine:
    base = {"criterion": "activity", "maximum": 15, "blocking": False}
    count = measures.published_last_30_days
    if count is None:
        return _unknown(**base, reason="missing")
    if count < 0:
        return _unknown(**base, reason="out_of_domain")
    return _measured(
        **base,
        points=_ratio_points(Fraction(count), Fraction(8), 15),
        measure=f"{count} publications sur 30 jours",
    )


def _ad_ready(measures: CreatorMeasures) -> ScoreLine:
    base = {"criterion": "ad_ready", "maximum": 15, "blocking": False}
    if measures.ad_contact is None or measures.past_labeled_ads is None:
        # An unreadable element is not an absent element (C-02).
        return _unknown(**base, reason="element_unreadable")

    elements = int(measures.ad_contact) + int(measures.past_labeled_ads)
    points = {2: 15, 1: 8, 0: 0}[elements]
    label = {2: "deux éléments", 1: "un élément", 0: "aucun élément"}[elements]
    return _measured(**base, points=Fraction(points), measure=label)


def _platform_safety(measures: CreatorMeasures) -> ScoreLine:
    base = {"criterion": "platform_safety", "maximum": 10, "blocking": False}
    platform = _platform_key(measures.platform)
    if platform is None:
        return _unknown(**base, reason="missing")
    points = PLATFORM_SAFETY.get(platform)
    if points is None:
        return _unknown(**base, reason="unknown_platform")
    return _measured(**base, points=Fraction(points), measure=platform)


def _audience_fit(measures: CreatorMeasures) -> ScoreLine:
    base = {"criterion": "audience_fit", "maximum": 10, "blocking": False}
    share = measures.russian_share
    if share is None or measures.comment_sample is None:
        return _unknown(**base, reason="missing")
    if not 0 <= share <= 100:
        return _unknown(**base, reason="out_of_domain")
    if measures.comment_sample < MIN_SAMPLE:
        return _unknown(**base, reason="sample_too_small")

    # More than half of the readable messages are in Russian.
    points = 10 if share > 50 else 0
    return _measured(
        **base,
        points=Fraction(points),
        measure=f"{_number(share)} % sur {measures.comment_sample} messages",
    )


# --- buyer criteria ---------------------------------------------------------


def _pays_creators(measures: BuyerMeasures) -> ScoreLine:
    base = {"criterion": "pays_creators", "maximum": 30, "blocking": True}
    count = measures.creators_paid
    if count is None:
        return _unknown(**base, reason="missing")
    if count < 0:
        return _unknown(**base, reason="out_of_domain")
    return _measured(
        **base,
        points=Fraction(15 * min(2, count)),
        measure=f"{count} créateurs payés sur 90 jours",
    )


def _sells_to_gamers(measures: BuyerMeasures) -> ScoreLine:
    base = {"criterion": "sells_to_gamers", "maximum": 20, "blocking": True}
    if measures.gaming_core is None:
        return _unknown(**base, reason="missing")
    return _measured(
        **base,
        points=Fraction(20 if measures.gaming_core else 0),
        measure="gaming au cœur de l'activité" if measures.gaming_core else "hors gaming",
    )


def _decision_maker(measures: BuyerMeasures) -> ScoreLine:
    base = {"criterion": "decision_maker", "maximum": 20, "blocking": False}
    state = (measures.decision_maker or "").strip().lower()
    if not state:
        # Enrichment has not run yet: unknown until a contact is looked for.
        return _unknown(**base, reason="enrichment_pending")
    points = _DECISION_MAKER_POINTS.get(state)
    if points is None:
        return _unknown(**base, reason="out_of_domain")
    return _measured(**base, points=Fraction(points), measure=state)


def _size(measures: BuyerMeasures) -> ScoreLine:
    base = {"criterion": "size", "maximum": 15, "blocking": False}
    employees = measures.employees
    if employees is None:
        return _unknown(**base, reason="missing")
    if employees < 0:
        return _unknown(**base, reason="out_of_domain")
    inside = 20 <= employees <= 1_000
    return _measured(
        **base,
        points=Fraction(15 if inside else 0),
        measure=f"{employees} employés",
    )


def _timing(measures: BuyerMeasures) -> ScoreLine:
    base = {"criterion": "timing", "maximum": 15, "blocking": False}
    if measures.recent_event is None:
        return _unknown(**base, reason="missing")
    return _measured(
        **base,
        points=Fraction(15 if measures.recent_event else 0),
        measure="événement daté" if measures.recent_event else "aucun événement daté",
    )


# --- shared helpers ---------------------------------------------------------


def _ratio_points(measure: Fraction, threshold: Fraction, maximum: int) -> Fraction:
    """S-02: the ratio is capped at 1 before multiplying."""
    if threshold <= 0:
        raise ValueError("a criterion threshold must be strictly positive")
    return Fraction(maximum) * min(Fraction(1), Fraction(measure) / threshold)


def _measured(
    *,
    criterion: str,
    maximum: int,
    blocking: bool,
    points: Fraction,
    measure: str,
    flags: tuple[str, ...] = (),
) -> ScoreLine:
    if not 0 <= points <= maximum:
        raise ValueError(f"{criterion}: {points} is outside 0..{maximum}")
    return ScoreLine(
        criterion=criterion,
        maximum=maximum,
        blocking=blocking,
        points=points,
        measure=measure,
        flags=flags,
    )


def _unknown(
    *, criterion: str, maximum: int, blocking: bool, reason: str
) -> ScoreLine:
    return ScoreLine(
        criterion=criterion,
        maximum=maximum,
        blocking=blocking,
        reason=reason,
    )


def _platform_key(platform: str | None) -> str | None:
    """Normalize a platform label to one of the keys the tables use."""
    if not platform:
        return None
    key = platform.strip().lower().replace("-", " ").replace("_", " ")
    key = "_".join(key.split())
    return _PLATFORM_ALIASES.get(key, key)


def _number(value: Fraction) -> str:
    """Render an exact value for a human measure label."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{float(value):.2f}".rstrip("0").rstrip(".")
