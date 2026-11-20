"""Turn a Baserow proof value into the one typed column a fact accepts.

The proof form stores every value as text. The database fact has exactly one
typed value column, and the score only consumes the typed form. Known fact keys
therefore get an explicit type; an unknown key stays text, which keeps the
evidence without pretending it can score.

Refusing a malformed value is deliberate: a follower count written as ``many``
must not become zero, and a percentage above 100 must not be capped silently.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

PROOF_LEVELS = frozenset({"OBSERVED", "DECLARED", "INFERRED"})
CONFIDENCES = frozenset({"VERIFIED", "PARTIAL", "UNVERIFIED"})
REVIEW_STATUSES = frozenset({"PENDING", "ACCEPTED", "REJECTED", "CONFLICT"})

PERCENT_KEYS = frozenset({"gaming_share", "russian_comment_share"})
COUNT_KEYS = frozenset(
    {
        "gaming_window",
        "followers",
        "published_last_30_days",
        "comment_sample",
        "creators_paid",
    }
)
BOOLEAN_KEYS = frozenset(
    {
        "ad_contact_or_rate_card",
        "past_labeled_ads",
        "sells_to_gamers",
        "decision_maker_email_verified",
        "recent_event",
    }
)
TEXT_KEYS = frozenset(
    {
        "main_platform",
        "decision_maker_role",
        "employee_band",
    }
)

_TRUE = {"true", "1", "yes", "oui", "да"}
_FALSE = {"false", "0", "no", "non", "нет"}


class FactRejected(ValueError):
    """The value cannot become a fact; the message is shown to the analyst."""


def parse_value(key: str, raw) -> tuple[str, object]:
    """Return ``(column_name, value)`` for a fact, or raise a readable refusal."""
    key = (key or "").strip()
    if not key:
        raise FactRejected("fact_key est vide")

    if raw is None:
        raise FactRejected("la valeur est vide")
    text = " ".join(str(raw).split())
    if not text:
        raise FactRejected("la valeur est vide")

    if key in BOOLEAN_KEYS:
        return "value_boolean", _boolean(text)
    if key in PERCENT_KEYS:
        return "value_number", _number(text, key, integer=False, maximum=100)
    if key in COUNT_KEYS:
        return "value_number", _number(text, key, integer=True, minimum=0)
    return "value_text", text


def validate_proof(proof_level: str, confidence: str, review_status: str) -> None:
    proof_level = (proof_level or "").strip().upper()
    confidence = (confidence or "").strip().upper()
    review_status = (review_status or "").strip().upper()

    if proof_level not in PROOF_LEVELS:
        raise FactRejected(f"proof_level inconnu : {proof_level or 'vide'}")
    if confidence not in CONFIDENCES:
        raise FactRejected(f"confidence inconnue : {confidence or 'vide'}")
    if review_status not in REVIEW_STATUSES:
        raise FactRejected(f"review_status inconnu : {review_status or 'vide'}")


def _boolean(text: str) -> bool:
    lowered = text.casefold()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise FactRejected(f"un booléen est attendu, reçu {text!r}")


def _number(
    text: str,
    key: str,
    *,
    integer: bool,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
) -> Decimal:
    cleaned = text.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as error:
        raise FactRejected(f"{key}: un nombre est attendu, reçu {text!r}") from error

    if not value.is_finite():
        raise FactRejected(f"{key}: un nombre fini est attendu")
    if integer and value != value.to_integral_value():
        raise FactRejected(f"{key}: un entier est attendu, reçu {text!r}")
    if minimum is not None and value < minimum:
        raise FactRejected(f"{key}: valeur négative ({value})")
    if maximum is not None and value > maximum:
        raise FactRejected(f"{key}: hors domaine (0 à {maximum})")
    return value
