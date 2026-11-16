"""Tests for the enrichment step: sourced facts in, typed measures out.

The step is the only place where a stored fact becomes a criterion value. These
tests pin the four rules it must never break: no source, no fact; a
contradiction is not a choice; out of domain is not capped; absent is not zero.
"""
from dataclasses import asdict
from fractions import Fraction

from processing.enrichment import (
    BUYER_FACT_KEYS,
    CREATOR_FACT_KEYS,
    Fact,
    buyer_measures,
    creator_measures,
)
from processing.scoring import QUALIFIED, TO_REVIEW, score_buyer, score_creator

SRC = "https://example.test/record"


def fact(key, value, source=SRC):
    return Fact(key=key, value=value, source_url=source)


def creator_facts(**overrides):
    values = {
        "gaming_share": 60,
        "gaming_window": 30,
        "followers": 25_000,
        "published_last_30_days": 7,
        "ad_contact_or_rate_card": True,
        "past_labeled_ads": False,
        "main_platform": "VK Video",
        "russian_comment_share": 70,
        "comment_sample": 50,
    }
    values.update(overrides)
    return [fact(key, value) for key, value in values.items()]


def buyer_facts(**overrides):
    values = {
        "creators_paid": 1,
        "sells_to_gamers": True,
        "decision_maker_role": "CMO",
        "decision_maker_email_verified": True,
        "employee_band": "50-199",
        "recent_event": True,
    }
    values.update(overrides)
    return [fact(key, value) for key, value in values.items()]


def line(result, criterion):
    return next(item for item in result.lines if item.criterion == criterion)


# --- the happy path ---------------------------------------------------------


def test_facts_become_the_typed_measures():
    measures = creator_measures(creator_facts()).measures

    assert measures.gaming_share == Fraction(60)
    assert measures.gaming_window == 30
    assert measures.followers == 25_000
    assert measures.published_last_30_days == 7
    assert measures.ad_contact is True
    assert measures.past_labeled_ads is False
    assert measures.platform == "VK Video"
    assert measures.russian_share == Fraction(70)
    assert measures.comment_sample == 50


def test_the_engagement_is_left_to_the_measure_step():
    enriched = creator_measures(creator_facts())

    assert enriched.notes == ()
    assert enriched.measures.median_views is None
    result = score_creator(enriched.measures)
    assert result.total_exact == Fraction(479, 8)  # 59.875, five criteria
    assert result.proposal == TO_REVIEW


def test_a_complete_buyer_qualifies():
    result = score_buyer(buyer_measures(buyer_facts()).measures)

    assert result.total_exact == 85
    assert result.proposal == QUALIFIED


# --- P-03: no source, no fact ----------------------------------------------


def test_a_fact_without_a_source_is_dropped():
    facts = creator_facts() + [fact("followers", 999_999, source="")]
    enriched = creator_measures(facts)

    assert enriched.measures.followers == 25_000
    assert any("sans source" in note for note in enriched.notes)


# --- P-05: a contradiction is not a choice ----------------------------------


def test_two_contradictory_facts_make_the_measure_unknown():
    facts = creator_facts() + [fact("gaming_share", 80)]
    enriched = creator_measures(facts)

    assert enriched.measures.gaming_share is None
    assert any("contradictoires" in note for note in enriched.notes)


def test_two_equal_facts_are_not_a_conflict():
    facts = creator_facts() + [fact("gaming_share", 60)]
    enriched = creator_measures(facts)

    assert enriched.measures.gaming_share == Fraction(60)
    assert enriched.notes == ()


# --- S-02: out of domain is an error, not a cap -----------------------------


def test_out_of_domain_is_unknown_not_capped():
    enriched = creator_measures(creator_facts(gaming_share=180))

    assert enriched.measures.gaming_share is None
    assert any("hors domaine" in note for note in enriched.notes)
    gaming = line(score_creator(enriched.measures), "focus_gaming")
    assert gaming.status == "UNKNOWN"
    assert gaming.points is None


def test_a_string_with_a_unit_is_not_a_number():
    enriched = creator_measures(creator_facts(gaming_share="60 %"))

    assert enriched.measures.gaming_share is None
    assert any("numérique" in note for note in enriched.notes)


def test_a_boolean_is_not_a_count():
    enriched = creator_measures(creator_facts(followers=True))

    assert enriched.measures.followers is None


def test_a_count_must_be_a_whole_number():
    enriched = creator_measures(creator_facts(published_last_30_days=7.5))

    assert enriched.measures.published_last_30_days is None


# --- buyer specifics --------------------------------------------------------


def test_decision_maker_tiers():
    assert buyer_measures(buyer_facts()).measures.decision_maker == "named_verified"
    assert (
        buyer_measures(
            buyer_facts(decision_maker_email_verified=False)
        ).measures.decision_maker
        == "named_unverified"
    )
    assert (
        buyer_measures(buyer_facts(decision_maker_role="")).measures.decision_maker
        == "generic_only"
    )

    pending = [item for item in buyer_facts() if item.key != "decision_maker_role"]
    assert buyer_measures(pending).measures.decision_maker is None


def test_employee_band_maps_to_the_size_criterion():
    def size(band):
        enriched = buyer_measures(buyer_facts(employee_band=band))
        return line(score_buyer(enriched.measures), "size")

    assert size("20-49").points == 15
    assert size("200-999").points == 15
    assert size("0-19").points == 0
    assert size("1000+").points == 0
    assert size("UNKNOWN").status == "UNKNOWN"


def test_an_unknown_band_is_not_a_zero():
    enriched = buyer_measures(buyer_facts(employee_band="beaucoup"))
    size = line(score_buyer(enriched.measures), "size")

    assert size.points is None
    assert size.status == "UNKNOWN"


# --- the two lists of keys cannot drift apart -------------------------------

CREATOR_SAMPLES = {
    "gaming_share": 60,
    "gaming_window": 30,
    "followers": 25_000,
    "published_last_30_days": 7,
    "ad_contact_or_rate_card": True,
    "past_labeled_ads": False,
    "main_platform": "VK Video",
    "russian_comment_share": 70,
    "comment_sample": 50,
}

BUYER_SAMPLES = {
    "creators_paid": 1,
    "sells_to_gamers": True,
    "decision_maker_role": "CMO",
    "decision_maker_email_verified": True,
    "employee_band": "50-199",
    "recent_event": True,
}


def test_every_allowed_creator_key_is_wired():
    assert set(CREATOR_SAMPLES) == CREATOR_FACT_KEYS
    for key, value in CREATOR_SAMPLES.items():
        measures = creator_measures([fact(key, value)]).measures
        assert any(value is not None for value in asdict(measures).values()), key


def test_every_allowed_buyer_key_is_wired():
    assert set(BUYER_SAMPLES) == BUYER_FACT_KEYS
    for key, value in BUYER_SAMPLES.items():
        facts = [fact(key, value)]
        if key == "decision_maker_email_verified":
            facts.append(fact("decision_maker_role", "CMO"))
        measures = buyer_measures(facts).measures
        assert any(value is not None for value in asdict(measures).values()), key
