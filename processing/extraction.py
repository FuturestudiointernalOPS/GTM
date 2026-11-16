"""Turn a model's or an analyst's claims into facts, refusing the unproven.

Contract: ``docs/extraction.md``. A claim is a key/value asserted about one
record. It becomes a fact only when three conditions hold: the key belongs to the
filon's schema, the ledger holds a source for it, and that source is not an
inference (Q-04). Anything else is rejected with a reason and never scored.

The ledger stays the only source of provenance: this module never invents a URL.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field

from processing.enrichment import Fact
from processing.evidence import INFERRED, Evidence, EvidenceLedger

REJECTED_UNKNOWN_KEY = "clé inconnue"
REJECTED_NO_EVIDENCE = "aucune preuve"
REJECTED_INFERRED = "fait inféré, aucun point"


@dataclass(frozen=True)
class Extraction:
    """The facts a record may be scored on, and the claims that were refused."""

    facts: tuple[Fact, ...] = ()
    rejected: tuple[str, ...] = field(default=())


def extract(
    claims: Mapping[str, object],
    ledger: EvidenceLedger,
    *,
    allowed: frozenset[str],
) -> Extraction:
    """Keep the claims the record can prove, reject the rest."""
    facts: list[Fact] = []
    rejected: list[str] = []

    for key, value in claims.items():
        if key not in allowed:
            rejected.append(f"{key}: {REJECTED_UNKNOWN_KEY}")
            continue
        if value is None:
            # The extractor asserts nothing about this key: not a claim.
            continue

        evidence = _evidence_for(key, ledger)
        if evidence is None:
            rejected.append(f"{key}: {REJECTED_NO_EVIDENCE}")
            continue
        if evidence.proof_level == INFERRED:
            rejected.append(f"{key}: {REJECTED_INFERRED}")
            continue

        facts.append(
            Fact(key=key, value=value, source_url=evidence.source.url)
        )

    return Extraction(facts=tuple(facts), rejected=tuple(rejected))


def _evidence_for(key: str, ledger: EvidenceLedger) -> Evidence | None:
    """The first source that proves the key, falling back to an inference.

    A later observed fact supersedes an earlier inference; the fallback keeps
    the inference visible so the rejection can say why.
    """
    entries = ledger.for_key(key)
    for entry in entries:
        if entry.proof_level != INFERRED:
            return entry
    return entries[-1] if entries else None
