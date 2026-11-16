"""Tests for the deterministic score (scope S-01 to S-04, §5.3, §6.3).

The twelve cases below are the ones frozen in ``docs/scoring.md``. Their expected
values are signed: if the code disagrees with one of them, the code is wrong, not
the test.
"""
from fractions import Fraction

from processing.scoring import (
    ENGAGEMENT_THRESHOLDS,
    OUT_OF_PROFILE,
    PRESELECTED,
    REJECTED,
    TO_REVIEW,
    BuyerMeasures,
    CreatorMeasures,
    in_creator_profile,
    score_buyer,
    score_creator,
)


def creator(**overrides) -> CreatorMeasures:
    """A complete, coherent creator: 79.875 points (V1)."""
    values = {
        "gaming_share": Fraction(60),
        "gaming_window": 30,
        "median_views": 2_000,
        "followers": 25_000,
        "engagement_read_at": "2026-11-10T00:00:00+00:00",
        "engagement_sample": 30,
        "published_last_30_days": 7,
        "ad_contact": True,
        "past_labeled_ads": False,
        "platform": "vk_video",
        "russian_share": Fraction(70),
        "comment_sample": 50,
    }
    values.update(overrides)
    return CreatorMeasures(**values)


def buyer(**overrides) -> BuyerMeasures:
    """A complete buyer: 85 points (V9)."""
    values = {
        "creators_paid": 1,
        "gaming_core": True,
        "decision_maker": "named_verified",
        "employees": 250,
        "recent_event": True,
    }
    values.update(overrides)
    return BuyerMeasures(**values)


def line(result, criterion):
    return next(item for item in result.lines if item.criterion == criterion)


# --- the twelve frozen cases ------------------------------------------------


def test_v1_exact_total_is_truncated_once():
    result = score_creator(creator())

    assert result.total_exact == Fraction(639, 8)  # 79.875
    assert result.score == 79
    assert result.proposal == PRESELECTED
    assert result.incomplete is False


def test_v2_one_point_below_the_bar_stays_below():
    # 18.75 + 15 + 13.125 + 8 + 5 + 10 = 69.875; rounded line by line it
    # would read 70 and be preselected (S-01).
    result = score_creator(
        creator(
            platform="telegram",
            median_views=3_000,  # 12 % of 25 000, Telegram threshold 20 %
        )
    )

    assert result.total_exact == Fraction(559, 8)  # 69.875
    assert result.score == 69
    assert result.proposal == REJECTED


def test_v3_exactly_seventy_is_preselected():
    result = score_creator(
        creator(
            gaming_share=Fraction(64),
            median_views=2_500,  # 10 %, the VK Video threshold
            published_last_30_days=8,
            ad_contact=False,
            russian_share=Fraction(30),
        )
    )

    assert result.total_exact == 70
    assert result.score == 70
    assert result.proposal == PRESELECTED


def test_v4_hidden_views_block_a_preselection():
    # 75 points acquired elsewhere; engagement unknown and blocking.
    result = score_creator(
        creator(
            gaming_share=Fraction(100),
            median_views=None,
            published_last_30_days=8,
            ad_contact=True,
            past_labeled_ads=True,
        )
    )

    assert result.score == 75
    assert result.incomplete is True
    assert result.upper_bound == 100
    assert result.proposal == TO_REVIEW
    assert line(result, "engagement").status == "UNKNOWN"
    assert line(result, "engagement").points is None


def test_v5_missing_non_blocking_measure_still_preselects():
    # 85 points acquired; activity unknown and not blocking.
    result = score_creator(
        creator(
            gaming_share=Fraction(100),
            median_views=2_500,
            published_last_30_days=None,
            ad_contact=True,
            past_labeled_ads=True,
        )
    )

    assert result.total_exact == 85
    assert result.score == 85
    assert result.incomplete is True
    assert result.proposal == PRESELECTED


def test_v6_interval_straddling_the_bar_goes_to_review():
    result = score_creator(
        creator(
            platform="telegram",
            median_views=4_000,  # 16 %
            published_last_30_days=None,
        )
    )

    assert result.total_exact == Fraction(247, 4)  # 61.75
    assert result.lower_bound == Fraction(247, 4)
    assert result.upper_bound == Fraction(247, 4) + 15  # 76.75
    assert result.proposal == TO_REVIEW


def test_v7_unknown_cannot_rescue_a_lost_record():
    result = score_creator(
        creator(
            platform="telegram",
            median_views=2_250,  # 9 %
            published_last_30_days=None,
        )
    )

    assert result.total_exact == 53
    assert result.upper_bound == 68
    assert result.proposal == REJECTED
    assert result.incomplete is True


def test_v8_out_of_profile_is_not_scored():
    result = score_creator(creator(followers=0, median_views=None))

    assert result.proposal == OUT_OF_PROFILE
    assert result.score is None
    assert result.total_exact is None
    assert in_creator_profile(0) is False
    assert in_creator_profile(5_000) is True
    assert in_creator_profile(None) is True


def test_v9_buyer_one_integration():
    result = score_buyer(buyer())

    assert result.total_exact == 85
    assert result.score == 85
    assert result.proposal == PRESELECTED


def test_v10_buyer_exactly_seventy_qualifies():
    result = score_buyer(buyer(creators_paid=0))

    assert result.total_exact == 70
    assert result.score == 70
    assert result.proposal == PRESELECTED


def test_v11_buyer_with_unknown_headcount():
    result = score_buyer(buyer(creators_paid=2, employees=None))

    assert result.total_exact == 85
    assert result.proposal == PRESELECTED
    assert result.incomplete is True


def test_v12_integrations_are_capped():
    assert line(score_buyer(buyer(creators_paid=3)), "pays_creators").points == 30


def test_v13_rutube_threshold_is_five_percent():
    result = score_creator(creator(platform="rutube", median_views=1_250))

    assert line(result, "engagement").points == 25
    assert line(result, "platform_safety").points == 10


def test_v14_youtube_threshold_is_ten_percent():
    result = score_creator(creator(platform="youtube", median_views=2_500))

    assert line(result, "engagement").points == 25
    assert line(result, "platform_safety").points == 5


# --- S-01: exact arithmetic, one truncation --------------------------------


def test_total_is_exact_and_lines_sum_to_it():
    result = score_creator(creator())
    total = sum(
        item.points for item in result.lines if item.points is not None
    )

    assert total == result.total_exact
    assert isinstance(result.total_exact, Fraction)


def test_a_measure_above_threshold_adds_nothing():
    result = score_creator(
        creator(
            gaming_share=Fraction(100),
            median_views=99_999,
            published_last_30_days=8,
            ad_contact=True,
            past_labeled_ads=True,
        )
    )

    assert line(result, "focus_gaming").points == 25
    assert line(result, "engagement").points == 25
    assert result.total_exact == 100


# --- S-02: caps, domains ------------------------------------------------


def test_out_of_domain_measure_is_unknown_not_capped():
    result = score_creator(creator(gaming_share=Fraction(180)))

    assert line(result, "focus_gaming").status == "UNKNOWN"
    assert line(result, "focus_gaming").reason == "out_of_domain"
    assert result.proposal == TO_REVIEW  # focus gaming is blocking


def test_engagement_thresholds_follow_the_engagement_spec():
    assert ENGAGEMENT_THRESHOLDS == {
        "telegram": Fraction(20),
        "vk_video": Fraction(10),
        "twitch": Fraction(5),
        "rutube": Fraction(5),
        "youtube": Fraction(10),
    }
    assert all(value > 0 for value in ENGAGEMENT_THRESHOLDS.values())


def test_platform_without_threshold_is_unknown():
    result = score_creator(creator(platform="instagram"))

    assert line(result, "engagement").status == "UNKNOWN"
    assert line(result, "engagement").reason == "platform_without_threshold"
    assert result.proposal == TO_REVIEW


# --- S-03: unknown is never zero -------------------------------------------


def test_engagement_needs_one_snapshot_timestamp():
    # M-03: views and followers are read in the same snapshot.
    result = score_creator(creator(engagement_read_at=None))

    assert line(result, "engagement").reason == "snapshot_missing"
    assert result.proposal == TO_REVIEW


def test_a_short_engagement_sample_is_flagged_not_silent():
    # M-05: between five and nine items the median holds, with a flag.
    result = score_creator(creator(engagement_sample=7))

    assert line(result, "engagement").status == "MEASURED"
    assert line(result, "engagement").flags == ("WEAK_SAMPLE",)
    assert line(score_creator(creator(engagement_sample=30)), "engagement").flags == ()


def test_too_few_items_is_not_a_measure():
    assert line(score_creator(creator(engagement_sample=4)), "engagement").status == (
        "UNKNOWN"
    )
    assert line(score_creator(creator(gaming_window=9)), "focus_gaming").status == (
        "UNKNOWN"
    )
    assert line(score_creator(creator(comment_sample=9)), "audience_fit").status == (
        "UNKNOWN"
    )


def test_unreadable_ad_element_is_unknown_not_absent():
    result = score_creator(creator(past_labeled_ads=None))

    assert line(result, "ad_ready").status == "UNKNOWN"
    assert line(result, "ad_ready").points is None


def test_buyer_without_enrichment_goes_to_review():
    result = score_buyer(buyer(decision_maker=None))

    assert result.total_exact == 65
    assert result.upper_bound == 85
    assert result.proposal == TO_REVIEW


def test_half_of_the_audience_is_not_a_majority():
    assert line(score_creator(creator(russian_share=Fraction(50))), "audience_fit").points == 0
    assert line(score_creator(creator(russian_share=Fraction(51))), "audience_fit").points == 10


# --- table integrity --------------------------------------------------------


def test_both_tables_still_sum_to_one_hundred():
    creator_maxima = sum(item.maximum for item in score_creator(creator()).lines)
    buyer_maxima = sum(item.maximum for item in score_buyer(buyer()).lines)

    assert creator_maxima == 100
    assert buyer_maxima == 100
