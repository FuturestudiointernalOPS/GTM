"""Tests for the evidence ledger and the no-invented-facts rule."""
from processing.evidence import (
    UNVERIFIED,
    EvidenceLedger,
    Source,
    missing_evidence,
)


def _source(url="https://vk.com/red"):
    return Source(
        url=url,
        consulted_at="2026-11-10T00:00:00+00:00",
        query_used="creator.vk_live.cs2",
        service="exa",
    )


def test_ledger_collects_and_queries_facts():
    ledger = EvidenceLedger()
    ledger.add("followers", 42_000, _source(), confidence="PARTIAL")
    ledger.add("url", "https://vk.com/red", _source())

    assert ledger.keys() == {"followers", "url"}
    assert ledger.source_urls() == {"https://vk.com/red"}
    assert [fact.value for fact in ledger.for_key("followers")] == [42_000]


def test_missing_evidence_flags_only_asserted_claims():
    ledger = EvidenceLedger()
    ledger.add("followers", 42_000, _source())

    claims = {"followers": 42_000, "gaming_share": 0.8, "language": None}

    # language is None = the model asserts nothing about it, so it is allowed.
    assert missing_evidence(claims, ledger) == ["gaming_share"]


def test_an_empty_ledger_rejects_every_asserted_claim():
    ledger = EvidenceLedger()
    assert missing_evidence({"followers": 1}, ledger) == ["followers"]
    assert missing_evidence({"followers": None}, ledger) == []
    assert UNVERIFIED == "UNVERIFIED"
