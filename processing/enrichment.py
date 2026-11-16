"""Turn a record's facts into the measures the score consumes.

Boundary: this step reads no page and infers nothing. An analyst or the model
extracts facts, each tied to a source; here they become the typed measures of
§5.3 and §6.3. The rules are those of the scope:

* a fact without a source is not a fact (P-03); it is dropped, not guessed;
* two facts on the same key with different values make the measure unknown
  (P-05), never a silent choice;
* a value outside its domain is an error, not a cap (S-02);
* an absent measure stays absent, never zero (S-03).

The engagement median does not come from here: it is produced by the measure
step and attached later with ``apply_engagement_measure``.
"""
from dataclasses import dataclass
from fractions import Fraction

from processing.scoring import SIZE_BANDS, BuyerMeasures, CreatorMeasures

_CONFLICT = object()

# The keys the extraction contract may hand over (docs/extraction.md). The step
# below is the only thing that knows how each one becomes a measure.
CREATOR_FACT_KEYS = frozenset(
    {
        "gaming_share",
        "gaming_window",
        "followers",
        "published_last_30_days",
        "ad_contact_or_rate_card",
        "past_labeled_ads",
        "main_platform",
        "russian_comment_share",
        "comment_sample",
    }
)

BUYER_FACT_KEYS = frozenset(
    {
        "creators_paid",
        "sells_to_gamers",
        "decision_maker_role",
        "decision_maker_email_verified",
        "employee_band",
        "recent_event",
    }
)


@dataclass(frozen=True)
class Fact:
    """One observed value, with the source that supports it."""

    key: str
    value: object
    source_url: str = ""


@dataclass(frozen=True)
class CreatorEnrichment:
    measures: CreatorMeasures
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuyerEnrichment:
    measures: BuyerMeasures
    notes: tuple[str, ...] = ()


def creator_measures(facts) -> CreatorEnrichment:
    """Build the creator criteria from facts, each already sourced."""
    notes: list[str] = []
    current = _current(facts, notes)

    measures = CreatorMeasures(
        gaming_share=_percent(current, "gaming_share", notes),
        gaming_window=_count(current, "gaming_window", notes),
        followers=_count(current, "followers", notes),
        published_last_30_days=_count(current, "published_last_30_days", notes),
        ad_contact=_boolean(current, "ad_contact_or_rate_card", notes),
        past_labeled_ads=_boolean(current, "past_labeled_ads", notes),
        platform=_text(current, "main_platform", notes),
        russian_share=_percent(current, "russian_comment_share", notes),
        comment_sample=_count(current, "comment_sample", notes),
    )
    return CreatorEnrichment(measures=measures, notes=tuple(notes))


def buyer_measures(facts) -> BuyerEnrichment:
    """Build the buyer criteria from facts, each already sourced."""
    notes: list[str] = []
    current = _current(facts, notes)

    measures = BuyerMeasures(
        creators_paid=_count(current, "creators_paid", notes),
        gaming_core=_boolean(current, "sells_to_gamers", notes),
        decision_maker=_decision_maker(current, notes),
        employee_band=_band(current, notes),
        recent_event=_boolean(current, "recent_event", notes),
    )
    return BuyerEnrichment(measures=measures, notes=tuple(notes))


def _current(facts, notes: list[str]) -> dict[str, object]:
    """Keep one value per key; a contradiction marks the key as unusable."""
    kept: dict[str, object] = {}
    for fact in facts:
        if not fact.source_url:
            notes.append(f"{fact.key}: fait sans source, ignoré")
            continue
        if fact.key not in kept:
            kept[fact.key] = fact.value
            continue
        if kept[fact.key] != fact.value:
            notes.append(f"{fact.key}: deux valeurs contradictoires")
            kept[fact.key] = _CONFLICT
    return kept


def _number(value) -> Fraction | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, Fraction)):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(str(value))
    if isinstance(value, str):
        try:
            return Fraction(value.strip())
        except (ValueError, ZeroDivisionError):
            return None
    return None


def _percent(current, key: str, notes: list[str]) -> Fraction | None:
    raw = current.get(key)
    if raw is None or raw is _CONFLICT:
        return None
    value = _number(raw)
    if value is None:
        notes.append(f"{key}: une valeur numérique est attendue")
        return None
    if not 0 <= value <= 100:
        notes.append(f"{key}: hors domaine (0 à 100)")
        return None
    return value


def _count(current, key: str, notes: list[str]) -> int | None:
    raw = current.get(key)
    if raw is None or raw is _CONFLICT:
        return None
    value = _number(raw)
    if value is None:
        notes.append(f"{key}: un comptage entier est attendu")
        return None
    if value.denominator != 1:
        notes.append(f"{key}: un comptage doit être entier")
        return None
    if value < 0:
        notes.append(f"{key}: hors domaine (négatif)")
        return None
    return int(value)


def _boolean(current, key: str, notes: list[str]) -> bool | None:
    value = current.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        notes.append(f"{key}: un booléen est attendu")
        return None
    return value


def _text(current, key: str, notes: list[str]) -> str | None:
    value = current.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        notes.append(f"{key}: un libellé non vide est attendu")
        return None
    return value.strip()


def _band(current, notes: list[str]) -> str | None:
    value = _text(current, "employee_band", notes)
    if value is None:
        return None
    if value.upper() == "UNKNOWN":
        return None
    if value not in SIZE_BANDS:
        notes.append(f"employee_band: bande inconnue ({value})")
        return None
    return value


def _decision_maker(current, notes: list[str]) -> str | None:
    """Map the two contact facts to the three tiers of §6.3.

    An absent role means enrichment has not run: unknown, not zero. An empty
    role means it ran and found nobody named: the generic tier.
    """
    if "decision_maker_role" not in current:
        return None

    role = current.get("decision_maker_role")
    if role is not None and not isinstance(role, str):
        notes.append("decision_maker_role: un libellé est attendu")
        return None
    verified = current.get("decision_maker_email_verified")
    if verified is not None and not isinstance(verified, bool):
        notes.append("decision_maker_email_verified: un booléen est attendu")
        verified = None

    if role and role.strip():
        return "named_verified" if verified is True else "named_unverified"
    return "generic_only"
