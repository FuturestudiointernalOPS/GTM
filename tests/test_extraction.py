"""Tests for the extraction contract (``docs/extraction.md``).

A claim becomes a fact only when the key is known, a source exists, and that
source is not an inference. These tests pin each of the three refusals.
"""

from processing.enrichment import CREATOR_FACT_KEYS
from processing.evidence import (
    DECLARED,
    INFERRED,
    OBSERVED,
    EvidenceLedger,
    Source,
)
from processing.extraction import extract

READ = "2026-11-10T00:00:00+00:00"


def source(key, url=None):
    return Source(
        url=url or f"https://example.test/{key}",
        consulted_at=READ,
    )


def ledger_with(key, proof_level=OBSERVED, url=None):
    ledger = EvidenceLedger()
    ledger.add(key, 60, source(key, url), proof_level=proof_level)
    return ledger


def test_a_proven_claim_becomes_a_fact():
    result = extract(
        {"gaming_share": 60}, ledger_with("gaming_share"), allowed=CREATOR_FACT_KEYS
    )

    assert result.rejected == ()
    assert len(result.facts) == 1
    assert result.facts[0].key == "gaming_share"
    assert result.facts[0].value == 60
    assert result.facts[0].source_url == "https://example.test/gaming_share"


def test_a_declared_fact_is_accepted():
    result = extract(
        {"gaming_share": 60},
        ledger_with("gaming_share", proof_level=DECLARED),
        allowed=CREATOR_FACT_KEYS,
    )

    assert result.rejected == ()
    assert len(result.facts) == 1


def test_an_unknown_key_is_rejected():
    # average_views is a diagnostic field: it never feeds a criterion.
    result = extract(
        {"average_views": 1}, ledger_with("average_views"), allowed=CREATOR_FACT_KEYS
    )

    assert result.facts == ()
    assert result.rejected == ("average_views: clé inconnue",)


def test_a_claim_without_evidence_is_rejected():
    result = extract({"gaming_share": 60}, EvidenceLedger(), allowed=CREATOR_FACT_KEYS)

    assert result.facts == ()
    assert result.rejected == ("gaming_share: aucune preuve",)


def test_an_inferred_fact_is_rejected():
    result = extract(
        {"gaming_share": 60},
        ledger_with("gaming_share", proof_level=INFERRED),
        allowed=CREATOR_FACT_KEYS,
    )

    assert result.facts == ()
    assert result.rejected == ("gaming_share: fait inféré, aucun point",)


def test_a_later_observed_fact_supersedes_an_inference():
    ledger = EvidenceLedger()
    ledger.add(
        "gaming_share",
        20,
        source("gaming_share", "https://old.test"),
        proof_level=INFERRED,
    )
    ledger.add(
        "gaming_share",
        60,
        source("gaming_share", "https://new.test"),
        proof_level=OBSERVED,
    )

    result = extract({"gaming_share": 60}, ledger, allowed=CREATOR_FACT_KEYS)

    assert result.rejected == ()
    assert result.facts[0].source_url == "https://new.test"


def test_a_null_claim_is_not_a_claim():
    result = extract(
        {"gaming_share": None}, EvidenceLedger(), allowed=CREATOR_FACT_KEYS
    )

    assert result.facts == ()
    assert result.rejected == ()
