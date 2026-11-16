"""Turn verification results into an eligibility decision.

Boundary: this step performs no search. The registry lookup, the label, the
sanctions screening and the licence are established by the procedures of
``docs/verification.md`` — by a human, or by a future collector. Here they are
read as check results, and the decision table of §2.9 and §3.6 is applied.

Two things it never does:

* it never turns a doubt into a yes. A check that is missing, unavailable or
  ambiguous suspends the qualification (``REGULATORY_PENDING``) and sends the
  fiche to a human; it never produces ``ELIGIBLE`` by default (H-04);
* it never computes points. Eligibility is not a score, and a score of 95 does
  not repair a missing check.

``EXCEPTION_APPROVED`` is never returned: it requires a dated, signed human
decision with an owner, and a function cannot invent one (V-22).
"""
from dataclasses import dataclass

# Eligibility, mirrored from the ``eligibility_status`` enum.
ELIGIBLE = "ELIGIBLE"
INELIGIBLE = "INELIGIBLE"
REGULATORY_PENDING = "REGULATORY_PENDING"

# Verification statuses, mirrored from the ``verification_status`` enum. The
# consequence of a status depends on the question: for the registry, NOT_FOUND
# is a refusal; for the sanctions lists, NOT_FOUND is the good outcome.
VERIFIED = "VERIFIED"
PARTIAL = "PARTIAL"
PENDING = "PENDING"
MISMATCH = "MISMATCH"
NOT_FOUND = "NOT_FOUND"
NOT_APPLICABLE = "NOT_APPLICABLE"
MANUAL_REVIEW = "MANUAL_REVIEW"

# Check types, as stored in ``eligibility_check.check_type``.
FOREIGN_AGENT = "FOREIGN_AGENT"
SANCTIONS = "SANCTIONS"
RKN_REGISTRY = "RKN_REGISTRY"
PLATFORM_COVERAGE = "PLATFORM_COVERAGE"
BETTING_LICENSE = "BETTING_LICENSE"

# Workflow statuses this step may propose (``workflow_status`` enum).
REJECTED = "REJECTED"
PRESELECTED = "PRESELECTED"
QUALIFIED = "QUALIFIED"
TO_REVIEW = "TO_REVIEW"
MANUAL_REVIEW_STATUS = "MANUAL_REVIEW"
COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"

# The registry concerns a page when the platform is listed and the page is above
# this threshold (V-05). "More than 10 000" is strict: 10 000 exactly is not.
RKN_FOLLOWER_THRESHOLD = 10_000


@dataclass(frozen=True)
class Check:
    """One control, as it will be stored and shown to a human."""

    check_type: str
    status: str
    reasons: tuple[str, ...] = ()
    source_url: str | None = None


@dataclass(frozen=True)
class EligibilityDecision:
    """The eligibility verdict and the workflow move that follows from it.

    ``status`` is ``None`` when no eligibility verdict is taken: a record
    rejected before ranking, or held for compliance. The checks still exist and
    are stored; the eligibility decision row, which requires a status, is not.
    """

    status: str | None
    workflow_status: str
    justification: str
    checks: tuple[Check, ...] = ()


@dataclass(frozen=True)
class CreatorVerification:
    """What the checks established about one creator page."""

    platform_covered: bool | None
    followers: int | None
    foreign_agent_label: bool | None = None
    rkn_status: str | None = None
    rkn_reasons: tuple[str, ...] = ()
    rkn_source_url: str | None = None
    sanction_status: str | None = None
    sanction_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuyerVerification:
    """What the checks established about one buyer."""

    betting_brand: bool
    license_status: str | None = None
    license_active: bool | None = None
    country_mapped: bool | None = None
    license_reasons: tuple[str, ...] = ()
    license_source_url: str | None = None
    sanction_status: str | None = None
    sanction_reasons: tuple[str, ...] = ()


def decide_creator(verification: CreatorVerification) -> EligibilityDecision:
    """Apply §2.9, in order: the first matching row decides."""
    checks: list[Check] = []

    foreign = _foreign_agent_check(verification.foreign_agent_label)
    checks.append(foreign)
    if foreign.status == VERIFIED:
        return EligibilityDecision(
            status=None,
            workflow_status=REJECTED,
            justification="étiquette d'agent étranger constatée",
            checks=tuple(checks),
        )
    if foreign.status == PENDING:
        # The label must be observed before any ranking: an unread page is not
        # a page without a label.
        return EligibilityDecision(
            status=REGULATORY_PENDING,
            workflow_status=MANUAL_REVIEW_STATUS,
            justification=(
                "étiquette d'agent étranger non observée : qualification suspendue"
            ),
            checks=tuple(checks),
        )

    sanctions = _sanctions_check(
        verification.sanction_status, verification.sanction_reasons
    )
    checks.append(sanctions)
    if sanctions.status in {VERIFIED, MANUAL_REVIEW}:
        return EligibilityDecision(
            status=None,
            workflow_status=COMPLIANCE_REVIEW,
            justification=(
                "correspondance ou doute sur les listes de sanctions : "
                "décision humaine requise"
            ),
            checks=tuple(checks),
        )
    if sanctions.status != NOT_FOUND:
        return EligibilityDecision(
            status=REGULATORY_PENDING,
            workflow_status=MANUAL_REVIEW_STATUS,
            justification="listes de sanctions non consultées : qualification suspendue",
            checks=tuple(checks),
        )

    coverage = _coverage_check(verification.platform_covered, verification.followers)
    checks.append(coverage)
    if coverage.status == PENDING:
        return EligibilityDecision(
            status=REGULATORY_PENDING,
            workflow_status=MANUAL_REVIEW_STATUS,
            justification=(
                "couverture de la plateforme ou nombre d'abonnés inconnu : "
                "qualification suspendue"
            ),
            checks=tuple(checks),
        )
    if coverage.status == NOT_APPLICABLE:
        checks.append(
            Check(RKN_REGISTRY, NOT_APPLICABLE, coverage.reasons)
        )
        return EligibilityDecision(
            status=ELIGIBLE,
            workflow_status=PRESELECTED,
            justification=(
                "page non concernée par le registre RKN : plateforme non couverte "
                "ou seuil de 10 000 abonnés non dépassé"
            ),
            checks=tuple(checks),
        )

    rkn = _rkn_check(
        verification.rkn_status,
        verification.rkn_reasons,
        verification.rkn_source_url,
    )
    checks.append(rkn)
    if rkn.status in {VERIFIED, PARTIAL}:
        return EligibilityDecision(
            status=ELIGIBLE,
            workflow_status=PRESELECTED,
            justification=(
                "page inscrite au registre RKN : plateforme couverte et "
                "page de plus de 10 000 abonnés"
            ),
            checks=tuple(checks),
        )
    if rkn.status in {NOT_FOUND, MISMATCH}:
        return EligibilityDecision(
            status=INELIGIBLE,
            workflow_status="INELIGIBLE",
            justification=(
                "page absente du registre RKN ou inscription d'une autre page, "
                "alors que la plateforme est couverte et la page dépasse "
                "10 000 abonnés"
            ),
            checks=tuple(checks),
        )
    return EligibilityDecision(
        status=REGULATORY_PENDING,
        workflow_status=MANUAL_REVIEW_STATUS,
        justification="contrôle RKN indisponible ou incomplet : qualification suspendue",
        checks=tuple(checks),
    )


def decide_buyer(verification: BuyerVerification) -> EligibilityDecision:
    """Apply §3.6 and E-B-01/04, in order: the first matching row decides."""
    checks: list[Check] = []

    sanctions = _sanctions_check(
        verification.sanction_status, verification.sanction_reasons
    )
    checks.append(sanctions)
    if sanctions.status in {VERIFIED, MANUAL_REVIEW}:
        return EligibilityDecision(
            status=None,
            workflow_status=COMPLIANCE_REVIEW,
            justification=(
                "correspondance ou doute sur les listes de sanctions : "
                "décision humaine requise"
            ),
            checks=tuple(checks),
        )
    if sanctions.status != NOT_FOUND:
        return EligibilityDecision(
            status=REGULATORY_PENDING,
            workflow_status=MANUAL_REVIEW_STATUS,
            justification="listes de sanctions non consultées : qualification suspendue",
            checks=tuple(checks),
        )

    if not verification.betting_brand:
        checks.append(Check(BETTING_LICENSE, NOT_APPLICABLE, ("NOT_A_BETTING_BRAND",)))
        return EligibilityDecision(
            status=ELIGIBLE,
            workflow_status=QUALIFIED,
            justification="aucune licence requise : l'acheteur n'est pas une marque de paris",
            checks=tuple(checks),
        )

    licence = _license_check(
        verification.license_status,
        verification.license_reasons,
        verification.license_source_url,
    )
    checks.append(licence)
    if licence.status == VERIFIED:
        if verification.license_active is False:
            return EligibilityDecision(
                status=INELIGIBLE,
                workflow_status="INELIGIBLE",
                justification="licence révoquée, suspendue ou annulée",
                checks=tuple(checks),
            )
        return EligibilityDecision(
            status=ELIGIBLE,
            workflow_status=QUALIFIED,
            justification="licence de paris vérifiée et active",
            checks=tuple(checks),
        )
    if licence.status in {MISMATCH, NOT_FOUND}:
        return EligibilityDecision(
            status=INELIGIBLE,
            workflow_status="INELIGIBLE",
            justification=(
                "licence de paris absente ou détenue par une autre entreprise"
            ),
            checks=tuple(checks),
        )
    if verification.country_mapped is False:
        return EligibilityDecision(
            status=REGULATORY_PENDING,
            workflow_status=TO_REVIEW,
            justification="pays non cartographié : qualification suspendue",
            checks=tuple(checks),
        )
    return EligibilityDecision(
        status=REGULATORY_PENDING,
        workflow_status=TO_REVIEW,
        justification="licence de paris non vérifiable : revue requise",
        checks=tuple(checks),
    )


# --- checks -----------------------------------------------------------------


def _foreign_agent_check(label: bool | None) -> Check:
    if label is True:
        return Check(FOREIGN_AGENT, VERIFIED, ("FOREIGN_AGENT_LABEL",))
    if label is False:
        return Check(FOREIGN_AGENT, NOT_FOUND, ("NO_LABEL",))
    return Check(FOREIGN_AGENT, PENDING, ("NOT_OBSERVED",))


def _sanctions_check(status: str | None, reasons: tuple[str, ...]) -> Check:
    """A hit or a doubt goes to compliance; an unavailable list does not accuse."""
    if status is None:
        return Check(SANCTIONS, PENDING, ("NOT_CHECKED",))
    if status == VERIFIED:
        return Check(SANCTIONS, MANUAL_REVIEW, reasons or ("MATCH",))
    if status == MANUAL_REVIEW:
        return Check(SANCTIONS, MANUAL_REVIEW, reasons or ("DOUBT",))
    if status == NOT_FOUND:
        return Check(SANCTIONS, NOT_FOUND, reasons or ("NO_MATCH",))
    return Check(SANCTIONS, PENDING, reasons or ("LISTS_UNAVAILABLE",))


def _coverage_check(covered: bool | None, followers: int | None) -> Check:
    """The two cumulative conditions of V-05, and nothing more."""
    if covered is None:
        return Check(PLATFORM_COVERAGE, PENDING, ("COVERAGE_UNKNOWN",))
    if covered is False:
        return Check(PLATFORM_COVERAGE, NOT_APPLICABLE, ("PLATFORM_NOT_COVERED",))
    if followers is None:
        return Check(PLATFORM_COVERAGE, PENDING, ("FOLLOWERS_UNKNOWN",))
    if followers <= RKN_FOLLOWER_THRESHOLD:
        return Check(PLATFORM_COVERAGE, NOT_APPLICABLE, ("BELOW_THRESHOLD",))
    return Check(PLATFORM_COVERAGE, VERIFIED, ("COVERED_ABOVE_THRESHOLD",))


def _rkn_check(
    status: str | None, reasons: tuple[str, ...], source_url: str | None
) -> Check:
    if status is None:
        return Check(RKN_REGISTRY, PENDING, ("NOT_CHECKED",), source_url)
    if status in {VERIFIED, PARTIAL, NOT_FOUND, MISMATCH}:
        return Check(RKN_REGISTRY, status, reasons, source_url)
    return Check(RKN_REGISTRY, PENDING, reasons or ("SERVICE_UNAVAILABLE",), source_url)


def _license_check(
    status: str | None, reasons: tuple[str, ...], source_url: str | None
) -> Check:
    if status is None:
        return Check(BETTING_LICENSE, PENDING, ("NOT_CHECKED",), source_url)
    if status in {VERIFIED, NOT_FOUND, MISMATCH}:
        return Check(BETTING_LICENSE, status, reasons, source_url)
    return Check(BETTING_LICENSE, PENDING, reasons or ("NOT_VERIFIABLE",), source_url)
