"""Decide whether a human action read from Baserow may move a fiche.

Baserow records an intention, not a status. The push service translates a
field, but this module owns the product rule: which action is allowed from
which status, which move it implies, and when a justification or a named
analyst is required.

Keeping the rule pure means a refused action can be explained and tested
without a database or a running Baserow.
"""

from __future__ import annotations

from dataclasses import dataclass

REQUEST_REVIEW = "REQUEST_REVIEW"
APPROVE = "APPROVE"
REJECT = "REJECT"
COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
START_AUDIT = "START_AUDIT"
ADD_TO_POOL = "ADD_TO_POOL"
MARK_CONTACTED = "MARK_CONTACTED"
RECORD_OPT_OUT = "RECORD_OPT_OUT"

KIND_CREATOR = "CREATOR"
KIND_BUYER = "BUYER"

TO_REVIEW = "TO_REVIEW"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
COMPLIANCE = "COMPLIANCE_REVIEW"
AUDIT = "AUDIT"
POOL = "POOL"
CONTACTED = "CONTACTED"
OPT_OUT = "OPT_OUT"

TARGET = {
    REQUEST_REVIEW: TO_REVIEW,
    APPROVE: APPROVED,
    REJECT: REJECTED,
    COMPLIANCE_REVIEW: COMPLIANCE,
    START_AUDIT: AUDIT,
    ADD_TO_POOL: POOL,
    MARK_CONTACTED: CONTACTED,
    RECORD_OPT_OUT: OPT_OUT,
}

DEFAULT_JUSTIFICATION = {
    REQUEST_REVIEW: "revue demandée depuis Baserow",
    APPROVE: "approbation humaine depuis Baserow",
    REJECT: "rejet humain depuis Baserow",
    COMPLIANCE_REVIEW: "passage en revue de conformité depuis Baserow",
    START_AUDIT: "audit ProveItGo demandé depuis Baserow",
    ADD_TO_POOL: "ajout au vivier après audit, depuis Baserow",
    MARK_CONTACTED: "contact enregistré depuis Baserow",
    RECORD_OPT_OUT: "opposition au démarchage enregistrée depuis Baserow",
}

# These moves only make sense in one filon, or from one precise status.
APPROVE_FROM = {
    KIND_CREATOR: frozenset({POOL}),
    KIND_BUYER: frozenset({POOL, "QUALIFIED"}),
}
START_AUDIT_FROM = frozenset({KIND_CREATOR})
ADD_TO_POOL_FROM = frozenset({KIND_CREATOR})
MARK_CONTACTED_FROM = frozenset({APPROVED})

# A fiche here is closed: no action reopens it. RECORD_OPT_OUT is the one
# exception, because the most restrictive outcome always wins.
TERMINAL = frozenset({OPT_OUT, "CLIENT"})

NOTE_REQUIRED = frozenset({APPROVE, REJECT})


class ReviewRejected(ValueError):
    """The action is not allowed; the message is shown to the analyst."""


@dataclass(frozen=True)
class ReviewDecision:
    action: str
    target: str | None
    justification: str
    actor: str


def decide(
    action: str,
    *,
    kind: str,
    current: str,
    note: str | None = None,
    requested_by: str | None = None,
) -> ReviewDecision:
    """Return the move an action implies, or raise a readable refusal."""
    action = (action or "").strip().upper()
    if action not in TARGET:
        raise ReviewRejected(f"action inconnue : {action or 'vide'}")

    kind = (kind or "").strip().upper()
    if kind not in (KIND_CREATOR, KIND_BUYER):
        raise ReviewRejected(f"type de fiche inconnu : {kind or 'vide'}")

    current = (current or "").strip().upper()
    text = " ".join((note or "").split())
    actor = " ".join((requested_by or "").split())

    target = TARGET[action]

    if action != RECORD_OPT_OUT and current in TERMINAL:
        raise ReviewRejected(f"la fiche est en {current} : aucune action ne la rouvre")

    # Repeating the same action is a no-op, not an error. It lets a human
    # click twice or a reader replay the row without creating a second event.
    if target == current:
        return ReviewDecision(
            action=action,
            target=None,
            justification=text or DEFAULT_JUSTIFICATION[action],
            actor=actor or "baserow-review",
        )

    if action == START_AUDIT and kind not in START_AUDIT_FROM:
        raise ReviewRejected("START_AUDIT ne concerne que les créateurs")
    if action == START_AUDIT and current != "PRESELECTED":
        raise ReviewRejected(f"START_AUDIT n'est pas permis depuis {current}")
    if action == ADD_TO_POOL and kind not in ADD_TO_POOL_FROM:
        raise ReviewRejected("ADD_TO_POOL ne concerne que les créateurs")
    if action == ADD_TO_POOL and current != AUDIT:
        raise ReviewRejected(f"ADD_TO_POOL n'est pas permis depuis {current}")

    if action == APPROVE and current not in APPROVE_FROM[kind]:
        raise ReviewRejected(
            f"APPROVE n'est pas permis depuis {current} pour un {kind}"
        )
    if action == MARK_CONTACTED and current not in MARK_CONTACTED_FROM:
        raise ReviewRejected(f"MARK_CONTACTED n'est pas permis depuis {current}")

    if action in NOTE_REQUIRED and not text:
        raise ReviewRejected(f"l'action {action} exige une justification")

    if current == COMPLIANCE and not text:
        raise ReviewRejected("sortir de COMPLIANCE_REVIEW exige une justification")

    needs_actor = action in {APPROVE, REJECT} or current == COMPLIANCE
    if needs_actor and not actor:
        raise ReviewRejected(
            "cette action exige un responsable : renseigner assigned_to"
        )

    return ReviewDecision(
        action=action,
        target=target,
        justification=text or DEFAULT_JUSTIFICATION[action],
        actor=actor or "baserow-review",
    )
