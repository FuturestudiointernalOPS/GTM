"""Tests for the query pool: syntax conversion, rotation and tracking ids."""
from collections import Counter

import pytest

from workflows import query_pool as qp


def _model(template_key: str, game_key: str) -> qp.Query:
    return next(
        query
        for query in qp.all_creator_model_queries()
        if query.id == f"creator.{template_key}.{game_key}"
    )


def test_every_game_and_template_is_expanded_once():
    models = qp.all_creator_model_queries()

    assert len(models) == len(qp.GAMES) * len(qp.CREATOR_TEMPLATES) == 70
    assert len({query.id for query in models}) == 70
    assert all("{game}" not in query.text for query in models)
    assert all("{game}" not in query.engine_query for query in models)


def test_the_whole_pool_has_unique_ids():
    pool = qp.all_queries()

    assert len(pool) == 114
    assert len({query.id for query in pool}) == len(pool)


def test_exa_text_never_uses_classic_engine_operators():
    for query in qp.all_queries():
        assert "site:" not in query.text
        assert '"' not in query.text
        assert " -" not in query.text


def test_the_supervisor_example_is_converted_for_exa():
    query = _model("twitch", "cs2")

    assert query.engine_query == "русскоязычные стримеры CS2 Twitch"
    assert query.text == "русскоязычный стример по CS2"
    assert query.include_domains == ("twitch.tv",)


def test_each_platform_template_keeps_its_domain_filter():
    assert _model("twitch", "cs2").include_domains == ("twitch.tv",)
    assert _model("vk_live", "cs2").include_domains == ("vk.com", "vkvideo.ru")
    assert _model("telegram", "cs2").include_domains == ("t.me",)
    assert _model("rutube", "cs2").include_domains == ("rutube.ru",)
    assert _model("tgstat", "cs2").include_domains == ("tgstat.com",)


def test_negative_filters_are_exclusions_not_query_text():
    query = _model("twitch", "cs2")

    assert set(query.exclude_text) == set(qp.CREATOR_NEGATIVE_TERMS)
    assert set(qp.CREATOR_NEGATIVE_TERMS) == {
        "казино",
        "слоты",
        "заносы",
        "читы",
        "взлом",
        "скачать",
        "торрент",
    }
    assert not any(term in query.text for term in qp.CREATOR_NEGATIVE_TERMS)
    assert query.exclude_domains == ("instagram.com", "facebook.com")


def test_young_audience_games_are_flagged_for_betting_exclusion():
    young = {"minecraft", "brawl_stars", "roblox"}

    for game in qp.GAMES:
        queries = [
            query
            for query in qp.all_creator_model_queries()
            if query.id.endswith(f".{game.key}")
        ]
        assert all(query.young_audience is (game.key in young) for query in queries)

    assert {game.key for game in qp.betting_compatible_games()} == {
        game.key for game in qp.GAMES
    } - young


def test_buyer_queries_keep_the_original_label_syntax_for_engines():
    query = next(q for q in qp.BUYER_ADS if q.id == "buyer.ads.games_promo")

    assert '"Реклама"' in query.engine_query
    assert '"erid"' in query.engine_query
    assert '"' not in query.text


def test_company_queries_are_stable_and_professional_only():
    first = qp.company_queries("ООО Игра")
    second = qp.company_queries("ООО Игра")

    assert first == second
    assert len(first) == 4
    assert len({query.id for query in first}) == 4
    assert all("ООО Игра" in query.text for query in first)
    assert "ИНН ОГРН" in first[-1].text


def test_an_empty_company_is_refused():
    with pytest.raises(ValueError, match="company"):
        qp.company_queries("   ")


def test_a_normal_week_has_the_supervisor_block_sizes():
    plan = qp.week_plan(1)
    counts = Counter(query.block for query in plan)

    assert len(plan) == 25
    assert len({query.id for query in plan}) == 25
    assert counts["creators.models"] == 8
    assert counts["creators.general"] == 4
    assert counts["buyers.ads"] == 5
    assert counts["buyers.sponsors"] == 3
    assert counts["buyers.categories"] == 3
    assert counts["buyers.timing"] == 2


def test_a_cis_week_replaces_the_creator_models():
    plan = qp.week_plan(3)
    counts = Counter(query.block for query in plan)

    assert len(plan) == 21
    assert counts["creators.models"] == 0
    assert counts["cis.creators"] == 2
    assert counts["cis.buyers"] == 2
    assert {query.market for query in plan if query.block.startswith("cis.")} == {
        "KZ",
        "UZ",
        "BY",
    }


def test_games_change_every_week():
    week_one = {
        query.id.rsplit(".", 1)[-1]
        for query in qp.creator_plan(1)
        if query.block == "creators.models"
    }
    week_two = {
        query.id.rsplit(".", 1)[-1]
        for query in qp.creator_plan(2)
        if query.block == "creators.models"
    }

    assert len(week_one) == 2
    assert len(week_two) == 2
    assert week_one != week_two


def test_betting_queries_are_opt_in_and_added_on_top():
    default_plan = qp.week_plan(1)
    with_betting = qp.week_plan(1, include_betting=True)

    assert not any(query.betting for query in default_plan)
    assert [query.id for query in with_betting if query.betting] == [
        query.id for query in qp.BETTING_QUERIES
    ]
    assert len(with_betting) == len(default_plan) + len(qp.BETTING_QUERIES)


def test_an_invalid_week_is_refused():
    with pytest.raises(ValueError, match="week"):
        qp.week_plan(0)


def test_the_current_week_is_an_iso_week():
    assert 1 <= qp.current_week() <= 53
