"""The evidence ledger: every fact is tied to a source and a date.

Why a ledger: the model may interpret evidence but never create it. A claim
must point to a fact that already exists; a claim about a key with no evidence
is rejected. This is the code form of the scope rule that keeps the model from
inventing facts.
"""

from dataclasses import dataclass, field

# Confidence says how sure the reader is; the proof level says what kind of fact
# it is. Only OBSERVED and DECLARED facts may score (P-01, Q-04).
VERIFIED = "VERIFIED"
PARTIAL = "PARTIAL"
UNVERIFIED = "UNVERIFIED"

OBSERVED = "OBSERVED"
DECLARED = "DECLARED"
INFERRED = "INFERRED"


@dataclass(frozen=True)
class Source:
    """Where a fact comes from: an address and a consultation date."""

    url: str
    consulted_at: str
    query_used: str | None = None
    service: str | None = None


@dataclass(frozen=True)
class Evidence:
    """One observed fact, with the source that supports it."""

    key: str
    value: object
    source: Source
    confidence: str = UNVERIFIED
    proof_level: str = OBSERVED


@dataclass
class EvidenceLedger:
    """A flat, ordered collection of facts for one run."""

    evidence: list[Evidence] = field(default_factory=list)

    def add(
        self,
        key: str,
        value: object,
        source: Source,
        *,
        confidence: str = UNVERIFIED,
        proof_level: str = OBSERVED,
    ) -> None:
        self.evidence.append(
            Evidence(
                key=key,
                value=value,
                source=source,
                confidence=confidence,
                proof_level=proof_level,
            )
        )

    def keys(self) -> set[str]:
        return {fact.key for fact in self.evidence}

    def source_urls(self) -> set[str]:
        return {fact.source.url for fact in self.evidence}

    def for_key(self, key: str) -> list[Evidence]:
        return [fact for fact in self.evidence if fact.key == key]


def missing_evidence(claims: dict, ledger: EvidenceLedger) -> list[str]:
    """Return the claim keys that have no supporting fact in the ledger.

    A ``None`` claim means "unknown" and is allowed: the model is not asserting
    anything about it. Any other value must be backed by a fact of the same
    key, otherwise the claim is rejected as an invented fact.
    """
    supported = ledger.keys()
    return [
        key
        for key, value in claims.items()
        if value is not None and key not in supported
    ]
